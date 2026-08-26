#!/usr/bin/env python3
"""
Coventry matchday revenue: actual vs optimized — full 2026–27 home slate.

Past: 2025–26 Championship homes with observed attendance.
Future: all 19 Premier League homes. Secondary from live StubHub when present,
else a GradientBoosting model trained on recent Championship→PL promoted clubs
(Ipswich, Luton, Sunderland seed panel). Fill blends Coventry Championship
baseline with promotion-jump fill priors. Confidence is evidence-based (0–100).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import LeaveOneOut
from sklearn.metrics import mean_absolute_percentage_error

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "reference" / "coventry_2526_home_attendance.csv"
FIXTURES = ROOT / "data" / "fixtures" / "coventry_2026_27_home.csv"
PL_SEED = ROOT / "data" / "reference" / "pl_promoted_home_seed.csv"
PRIMARY_BANDS = ROOT / "data" / "reference" / "primary_bands.csv"
SNAP_DIR = ROOT / "data" / "raw" / "secondary_snapshots"
OUT_JSON = ROOT / "results" / "coventry_profit_analysis.json"
OUT_CSV = ROOT / "results" / "coventry_profit_by_game.csv"
EXPLORER = ROOT / "coventry_explorer.html"
CAP = 32609
CONC_PER_HEAD = 8.0
CAPTURE_RATE = 0.55

# Default primary face by opponent type when fixture band missing
PRIMARY_DEFAULT = 45.0
PRIMARY_BIG_SIX = 55.0
PRIMARY_HOT = 48.0  # Newcastle-class travel demand


def wtp_from_fill(primary: float, fill: float, tier: int) -> float:
    """Implied WTP when we lack StubHub (Championship past)."""
    if fill >= 0.95:
        mult = 1.55
    elif fill >= 0.90:
        mult = 1.35
    elif fill >= 0.85:
        mult = 1.18
    else:
        mult = 1.02
    tier_bump = {2: 0.0, 3: 0.06, 4: 0.12, 5: 0.20}.get(int(tier), 0.0)
    return round(primary * (mult + tier_bump), 2)


def optimize_game(att: int, primary: float, secondary: float) -> dict:
    fill = att / CAP
    ticket_rev = att * primary
    conc_rev = att * CONC_PER_HEAD
    actual_total = ticket_rev + conc_rev
    ratio = secondary / max(primary, 1)

    if fill >= 0.88 and ratio >= 1.25:
        opt_price = primary + CAPTURE_RATE * (secondary - primary)
        opt_att = att
        action = "PRICE_CAPTURE"
        cls = "undervalued"
    elif fill < 0.88 or ratio < 1.08:
        opt_price = primary * 0.95
        opt_att = min(CAP, int(att * 1.08))
        action = "PROMO_TARGET"
        cls = "soft"
    else:
        opt_price = primary * 1.06
        opt_att = att
        action = "MONITOR"
        cls = "fair"

    opt_ticket = opt_att * opt_price
    opt_conc = opt_att * CONC_PER_HEAD
    opt_total = opt_ticket + opt_conc
    lift = opt_total - actual_total

    return {
        "attendance": att,
        "fill_pct": round(100 * fill, 1),
        "primary": round(primary, 2),
        "secondary_or_wtp": round(secondary, 2),
        "ratio": round(ratio, 2),
        "class": cls,
        "action": action,
        "actual_ticket_rev": round(ticket_rev),
        "actual_conc_rev": round(conc_rev),
        "actual_total": round(actual_total),
        "opt_price": round(opt_price, 2),
        "opt_attendance": opt_att,
        "opt_fill_pct": round(100 * opt_att / CAP, 1),
        "opt_ticket_rev": round(opt_ticket),
        "opt_conc_rev": round(opt_conc),
        "opt_total": round(opt_total),
        "lift": round(lift),
    }


def latest_stubhub() -> pd.DataFrame:
    if not SNAP_DIR.exists():
        return pd.DataFrame()
    files = sorted(SNAP_DIR.glob("snapshot_*.csv"))
    if not files:
        return pd.DataFrame()
    snap = pd.read_csv(files[-1])
    return snap[snap["track"] == "pl_coventry"].copy()


def load_primary_map() -> dict[str, float]:
    bands = pd.read_csv(PRIMARY_BANDS)
    return {
        r["fixture_id"]: float(r["primary_band_gbp"])
        for _, r in bands.iterrows()
        if pd.notna(r.get("primary_band_gbp"))
    }


def primary_for(fixture_id: str, big_six: int, away: str, band_map: dict) -> float:
    if fixture_id in band_map:
        return band_map[fixture_id]
    if big_six:
        return PRIMARY_BIG_SIX
    if "Newcastle" in away:
        return PRIMARY_HOT
    return PRIMARY_DEFAULT


def train_promotion_models(seed: pd.DataFrame) -> tuple:
    """Train secondary + fill models on Championship→PL promoted-club analogs."""
    feats = ["big_six_away", "attendance_pct"]
    X = seed[feats].astype(float)
    y_sec = seed["secondary_get_in_gbp"].astype(float)
    y_fill = seed["attendance_pct"].astype(float)

    sec_model = GradientBoostingRegressor(n_estimators=80, max_depth=2, random_state=42)
    fill_model = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
    # Fill model uses big_six only (attendance_pct would leak the target)
    fill_X = seed[["big_six_away"]].astype(float)
    sec_model.fit(X, y_sec)
    fill_model.fit(fill_X, y_fill)

    loo = LeaveOneOut()
    sec_preds, fill_preds = [], []
    for train_idx, test_idx in loo.split(X):
        m_s = GradientBoostingRegressor(n_estimators=80, max_depth=2, random_state=42)
        m_f = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
        m_s.fit(X.iloc[train_idx], y_sec.iloc[train_idx])
        m_f.fit(fill_X.iloc[train_idx], y_fill.iloc[train_idx])
        sec_preds.append(float(m_s.predict(X.iloc[test_idx])[0]))
        fill_preds.append(float(m_f.predict(fill_X.iloc[test_idx])[0]))
    sec_mape = float(mean_absolute_percentage_error(y_sec, sec_preds)) * 100
    fill_mae = float(np.mean(np.abs(y_fill - np.array(fill_preds))))

    diagnostics = {
        "n_seed_rows": int(len(seed)),
        "seed_clubs": sorted(seed["club"].unique().tolist()),
        "sec_features": feats,
        "sec_loo_mape_pct": round(sec_mape, 1),
        "fill_loo_mae": round(fill_mae, 3),
        "big_six_mean_secondary": round(float(seed.loc[seed.big_six_away == 1, "secondary_get_in_gbp"].mean()), 1),
        "other_mean_secondary": round(float(seed.loc[seed.big_six_away == 0, "secondary_get_in_gbp"].mean()), 1),
        "big_six_mean_fill": round(float(seed.loc[seed.big_six_away == 1, "attendance_pct"].mean()), 3),
        "other_mean_fill": round(float(seed.loc[seed.big_six_away == 0, "attendance_pct"].mean()), 3),
    }
    return sec_model, fill_model, diagnostics


def confidence_score(
    *,
    live: bool,
    big_six: int,
    days_out: int,
    promoted_away: int,
    sec_mape: float,
) -> tuple[int, str, str]:
    """
    0–100 confidence + label + short reason.
    Domain shift Championship→PL starts uncertain; live StubHub and close dates lift it.
    """
    score = 38  # base: Coventry never played PL in this sample; jump is the risk
    reasons = ["Champ→PL domain shift"]

    if live:
        score += 40
        reasons.append("live StubHub secondary")
    else:
        # Model trained on other promoted clubs — penalize by LOO error
        score += max(8, 28 - int(sec_mape / 3))
        reasons.append(f"promotion-jump model (seed LOO MAPE {sec_mape:.0f}%)")

    if big_six:
        score += 10
        reasons.append("big-six analogs in seed")
    elif promoted_away:
        score += 4
        reasons.append("promoted-away prior")
    else:
        score += 2
        reasons.append("mid-table prior")

    if days_out <= 14:
        score += 8
        reasons.append("≤14 days out")
    elif days_out <= 45:
        score += 5
        reasons.append("≤45 days out")
    elif days_out > 150:
        score -= 8
        reasons.append("far horizon (>150d)")

    score = int(max(15, min(95, score)))
    if score >= 75:
        label = "high"
    elif score >= 55:
        label = "medium"
    else:
        label = "low"
    return score, label, "; ".join(reasons)


def analyze_historical() -> pd.DataFrame:
    df = pd.read_csv(HIST, parse_dates=["date"])
    rows = []
    for _, r in df.iterrows():
        fill = r["attendance"] / r["capacity"]
        secondary = wtp_from_fill(r["primary_avg_gbp"], fill, r["opponent_tier"])
        out = optimize_game(int(r["attendance"]), float(r["primary_avg_gbp"]), secondary)
        out.update({
            "date": r["date"].strftime("%Y-%m-%d"),
            "opponent": r["opponent"],
            "competition": r["competition"],
            "phase": "historical",
            "certainty": "observed_attendance",
            "confidence": 95,
            "confidence_label": "high",
            "confidence_reason": "observed attendance + fill-implied WTP",
            "model_secondary": None,
            "played": True,
            "secondary_source": "wtp_from_fill",
        })
        rows.append(out)
    return pd.DataFrame(rows)


def analyze_forward(as_of: date | None = None) -> tuple[pd.DataFrame, dict]:
    as_of = as_of or date.today()
    fixtures = pd.read_csv(FIXTURES, parse_dates=["date"])
    seed = pd.read_csv(PL_SEED)
    sec_model, fill_model, diag = train_promotion_models(seed)
    snap = latest_stubhub()
    live_map = {}
    if not snap.empty:
        for _, r in snap.iterrows():
            if pd.notna(r.get("secondary_get_in")):
                live_map[r["fixture_id"]] = float(r["secondary_get_in"])

    band_map = load_primary_map()
    hist = pd.read_csv(HIST)
    cov_mean_fill = float((hist["attendance"] / hist["capacity"]).mean())
    cov_std_fill = float((hist["attendance"] / hist["capacity"]).std())

    rows = []
    n_played = 0
    for _, f in fixtures.iterrows():
        fid = f["fixture_id"]
        d = f["date"].date()
        days_out = (d - as_of).days
        big_six = int(f["big_six_away"])
        promoted = int(f["promoted_away"])
        away = f["away"]
        primary = primary_for(fid, big_six, away, band_map)

        X_fill = pd.DataFrame([{"big_six_away": float(big_six)}])
        model_fill = float(fill_model.predict(X_fill)[0])
        # Expected fill for secondary model (Coventry sells better than soft Luton/Ipswich mids)
        expected_fill = 0.97 if big_six else (0.92 if promoted else 0.88)
        X_sec = pd.DataFrame([{
            "big_six_away": float(big_six),
            "attendance_pct": float(expected_fill),
        }])
        model_sec = float(sec_model.predict(X_sec)[0])
        if big_six:
            model_sec = max(model_sec, 95.0)
        elif promoted:
            model_sec = max(model_sec, primary * 1.15, 48.0)
        else:
            # Coventry home demand floor — seed soft games (~£35–42) understate CBS Arena PL midweeks
            model_sec = max(model_sec, primary * 1.2, 55.0)
        if promoted and not big_six:
            model_sec *= 1.05

        live = fid in live_map
        secondary = live_map[fid] if live else model_sec
        secondary_source = "live_stubhub" if live else "promotion_jump_model"

        # Fill: blend Coventry Championship baseline with promotion-jump prior;
        # hot secondary (esp. live) pulls toward sellout.
        ratio = secondary / max(primary, 1)
        jump_weight = 0.55 if big_six else 0.40
        fill = (1 - jump_weight) * cov_mean_fill + jump_weight * model_fill
        if ratio >= 2.0:
            fill = max(fill, min(0.98, cov_mean_fill + 1.4 * cov_std_fill))
        elif ratio >= 1.5:
            fill = max(fill, min(0.96, cov_mean_fill + 0.8 * cov_std_fill))
        elif ratio < 1.15:
            fill = min(fill, cov_mean_fill - 0.3 * cov_std_fill)
        fill = float(np.clip(fill, 0.78, 0.99))
        att = int(CAP * fill)

        played = d < as_of
        if played:
            n_played += 1
            # No official PL home attendance yet in reference — keep model until logged
            certainty = "played_model_pending_attendance"
            conf, conf_lab, conf_why = confidence_score(
                live=live, big_six=big_six, days_out=0,
                promoted_away=promoted, sec_mape=diag["sec_loo_mape_pct"],
            )
            conf = min(conf, 70)  # played but no observed attendance logged
            conf_why = "home already played; attendance not yet in reference — " + conf_why
        else:
            certainty = "live_secondary" if live else "model_secondary"
            conf, conf_lab, conf_why = confidence_score(
                live=live, big_six=big_six, days_out=days_out,
                promoted_away=promoted, sec_mape=diag["sec_loo_mape_pct"],
            )

        out = optimize_game(att, primary, secondary)
        z = 1.645
        # Wider bands when confidence is low
        width = cov_std_fill * (1.0 + (100 - conf) / 80.0)
        lo = int(CAP * max(0.72, fill - z * width))
        hi = int(CAP * min(0.995, fill + z * width))
        out.update({
            "date": d.isoformat(),
            "opponent": away,
            "competition": "Premier League",
            "phase": "projection",
            "certainty": certainty,
            "confidence": conf,
            "confidence_label": conf_lab,
            "confidence_reason": conf_why,
            "model_secondary": round(model_sec, 2),
            "played": played,
            "secondary_source": secondary_source,
            "days_out": days_out,
            "big_six_away": big_six,
            "promoted_away": promoted,
            "att_lo90": lo,
            "att_hi90": hi,
            "lift_lo90": round(optimize_game(lo, primary, secondary)["lift"]),
            "lift_hi90": round(optimize_game(hi, primary, secondary)["lift"]),
        })
        rows.append(out)

    meta = {
        **diag,
        "as_of": as_of.isoformat(),
        "n_homes_total": int(len(fixtures)),
        "n_homes_played": n_played,
        "n_live_stubhub": int(len(live_map)),
        "coventry_champ_mean_fill": round(cov_mean_fill, 3),
        "first_home_date": fixtures["date"].min().strftime("%Y-%m-%d"),
        "based_on_promotion_jump": True,
    }
    return pd.DataFrame(rows), meta


def embed_explorer(summary: dict) -> None:
    if not EXPLORER.exists():
        return
    html = EXPLORER.read_text()
    payload = json.dumps(summary, separators=(",", ":"))
    marker = "const ANALYSIS = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(f"ANALYSIS marker not found in {EXPLORER}")
    brace = html.find("{", start)
    # Find matching closing }; for the object literal
    depth = 0
    i = brace
    end = None
    while i < len(html):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                if html[end:end + 1] == ";":
                    end += 1
                break
        i += 1
    if end is None:
        raise RuntimeError("Could not find end of ANALYSIS object")
    new_html = html[:start] + marker + payload + ";" + html[end:]
    EXPLORER.write_text(new_html)


def main() -> None:
    as_of = date.today()
    hist = analyze_historical()
    fwd, model_meta = analyze_forward(as_of)
    all_df = pd.concat([hist, fwd], ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(OUT_CSV, index=False)

    summary = {
        "capacity": CAP,
        "conc_per_head_gbp": CONC_PER_HEAD,
        "capture_rate": CAPTURE_RATE,
        "as_of": as_of.isoformat(),
        "method": {
            "ideas_from": "Sports ticket analytics practice (timing segments, ticket+concession, targeted promo) — ideas only, not NBA profit rates",
            "projections_from": "Full 19-home PL slate; live StubHub UK where available; else GradientBoosting on Championship→PL promoted-club seed (big_six + expected fill)",
            "historical": "2025-26 Championship home attendances (observed)",
            "promotion_jump": (
                f"Yes — secondary & fill priors from {', '.join(model_meta['seed_clubs'])} "
                f"first PL seasons after promotion ({model_meta['n_seed_rows']} seed fixtures). "
                f"LOO MAPE on secondary ≈ {model_meta['sec_loo_mape_pct']}%. "
                "Coventry Championship fill is blended in; this is analog transfer, not Coventry PL history."
            ),
            "wtp_proxy": "fill-based willingness-to-pay for Championship past when StubHub unavailable",
            "optimization": "PRICE_CAPTURE when near-full & secondary>>primary; PROMO_TARGET when soft",
            "confidence": "Per-game 0–100 from evidence (live StubHub, seed analogs, days-out, domain-shift penalty)",
            "played_status": (
                f"As of {as_of.isoformat()}: {model_meta['n_homes_played']} of "
                f"{model_meta['n_homes_total']} PL homes played. "
                f"First home listed {model_meta['first_home_date']}."
            ),
        },
        "model": model_meta,
        "historical": {
            "n_games": int(len(hist)),
            "total_attendance": int(hist["attendance"].sum()),
            "avg_fill_pct": round(hist["fill_pct"].mean(), 1),
            "actual_matchday_total_gbp": int(hist["actual_total"].sum()),
            "optimized_matchday_total_gbp": int(hist["opt_total"].sum()),
            "total_lift_gbp": int(hist["lift"].sum()),
            "lift_pct": round(100 * hist["lift"].sum() / hist["actual_total"].sum(), 1),
            "n_undervalued": int((hist["class"] == "undervalued").sum()),
            "n_soft": int((hist["class"] == "soft").sum()),
            "avg_confidence": round(float(hist["confidence"].mean()), 1),
        },
        "projection_pl": {
            "n_games": int(len(fwd)),
            "n_played": int(model_meta["n_homes_played"]),
            "n_live_stubhub": int(model_meta["n_live_stubhub"]),
            "actual_matchday_total_gbp": int(fwd["actual_total"].sum()),
            "optimized_matchday_total_gbp": int(fwd["opt_total"].sum()),
            "total_lift_gbp": int(fwd["lift"].sum()),
            "lift_pct": round(100 * fwd["lift"].sum() / fwd["actual_total"].sum(), 1),
            "lift_lo90_sum": int(fwd["lift_lo90"].sum()),
            "lift_hi90_sum": int(fwd["lift_hi90"].sum()),
            "avg_confidence": round(float(fwd["confidence"].mean()), 1),
            "based_on_promotion_jump": True,
        },
        "games": all_df.replace({np.nan: None}).to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    embed_explorer(summary)
    print(json.dumps({
        "historical": summary["historical"],
        "projection_pl": summary["projection_pl"],
        "model": summary["model"],
        "method_played": summary["method"]["played_status"],
        "method_jump": summary["method"]["promotion_jump"],
    }, indent=2))
    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}\nEmbedded {EXPLORER}")


if __name__ == "__main__":
    main()
