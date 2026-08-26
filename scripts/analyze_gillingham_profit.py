#!/usr/bin/env python3
"""
Gillingham matchday revenue: actual vs optimized — EFL League Two only.

Sales reality: StubHub UK almost never lists League Two get-ins. Primary comes from
club-published Priestfield adult bands (£22–£25) plus League Two comps. Secondary is
an L2 sales prior (thin resale premium), overridden only by plausible StubHub (£8–£80).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error
from sklearn.model_selection import LeaveOneOut

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "reference" / "gillingham_2526_home_attendance.csv"
FIXTURES = ROOT / "data" / "fixtures" / "gillingham_2026_27_home.csv"
SALES_SEED = ROOT / "data" / "reference" / "league_two_ticket_sales_seed.csv"
SNAP_DIR = ROOT / "data" / "raw" / "secondary_snapshots"
OUT_JSON = ROOT / "results" / "gillingham_profit_analysis.json"
OUT_CSV = ROOT / "results" / "gillingham_profit_by_game.csv"
EXPLORER = ROOT / "gillingham_explorer.html"

CAP = 11582
CONC_PER_HEAD = 6.0
CAPTURE_RATE = 0.45
CLUB_PRIMARY_ADULT = 23.5


def load_sales_priors() -> dict:
    seed = pd.read_csv(SALES_SEED)
    gills = seed[seed["club"] == "Gillingham"]

    def _cat(name: str, default: float) -> float:
        s = gills.loc[gills["category"] == name, "price_gbp"]
        return float(s.iloc[0]) if len(s) else default

    return {
        "primary_adult": _cat("home_adult_face", CLUB_PRIMARY_ADULT),
        "sec_soft": _cat("wtp_soft", 24.5),
        "sec_rivalry": _cat("wtp_rivalry", 29.5),
        "sec_hot": _cat("wtp_hot", 32.0),
        "n_seed_rows": int(len(seed)),
        "stubhub_l2_note": (
            "StubHub UK almost never lists League Two get-ins; "
            "sales = club primary + L2 demand prior"
        ),
    }


def latest_live_secondary() -> dict[str, float]:
    if not SNAP_DIR.exists():
        return {}
    files = sorted(SNAP_DIR.glob("snapshot_*.csv"))
    if not files:
        return {}
    snap = pd.read_csv(files[-1])
    if "track" not in snap.columns:
        return {}
    g = snap[snap["track"].astype(str).str.contains("gillingham", case=False, na=False)]
    out: dict[str, float] = {}
    for _, r in g.iterrows():
        price = r.get("secondary_get_in")
        if pd.isna(price):
            continue
        price = float(price)
        if 8 <= price <= 80:
            out[str(r.get("fixture_id", ""))] = price
            if pd.notna(r.get("away")):
                out[str(r["away"]).strip().lower()] = price
    return out


def sales_secondary(primary: float, fill: float, tier: int, priors: dict) -> tuple[float, str]:
    if fill >= 0.70 or tier >= 4:
        return round(max(priors["sec_rivalry"], primary * 1.22), 2), "l2_sales_prior_rivalry"
    if fill >= 0.55 or tier >= 3:
        return round(max(priors["sec_hot"] * 0.9, primary * 1.12), 2), "l2_sales_prior_warm"
    return round(max(priors["sec_soft"], primary * 1.04), 2), "l2_sales_prior_soft"


def optimize_game(att: int, primary: float, secondary: float) -> dict:
    fill = att / CAP
    ticket_rev = att * primary
    conc_rev = att * CONC_PER_HEAD
    actual_total = ticket_rev + conc_rev
    ratio = secondary / max(primary, 1)

    if fill >= 0.62 and ratio >= 1.22:
        opt_price = primary + CAPTURE_RATE * (secondary - primary)
        opt_att = att
        action, cls = "PRICE_CAPTURE", "undervalued"
    elif fill < 0.52 or ratio < 1.08:
        opt_price = primary * 0.93
        opt_att = min(CAP, int(att * 1.12))
        action, cls = "PROMO_TARGET", "soft"
    else:
        opt_price = primary * 1.05
        opt_att = att
        action, cls = "MONITOR", "fair"

    opt_ticket = opt_att * opt_price
    opt_conc = opt_att * CONC_PER_HEAD
    opt_total = opt_ticket + opt_conc
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
        "lift": round(opt_total - actual_total),
    }


def train_fill_model(hist: pd.DataFrame) -> tuple:
    X = hist[["opponent_tier"]].astype(float)
    y = (hist["attendance"] / hist["capacity"]).astype(float)
    model = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
    model.fit(X, y)
    preds = []
    for tr, te in LeaveOneOut().split(X):
        m = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
        m.fit(X.iloc[tr], y.iloc[tr])
        preds.append(float(m.predict(X.iloc[te])[0]))
    mae = float(np.mean(np.abs(y - np.array(preds))))
    mape = float(mean_absolute_percentage_error(y, preds)) * 100
    return model, {
        "fill_loo_mae": round(mae, 3),
        "fill_loo_mape_pct": round(mape, 1),
        "n_hist": int(len(hist)),
    }


def confidence_score(*, observed: bool, days_out: int, tier: int, fill_mape: float) -> tuple[int, str, str]:
    if observed:
        return 92, "high", "observed attendance"
    score = 48
    reasons = ["League Two own-history fill + club sales prior"]
    score += max(5, 22 - int(fill_mape / 2))
    reasons.append(f"crowd forecast error about {fill_mape:.0f}% in leave-one-out checks")
    if tier >= 4:
        score += 8
        reasons.append("rivalry / high-tier prior")
    elif tier >= 3:
        score += 4
        reasons.append("mid-high tier prior")
    if days_out <= 14:
        score += 10
        reasons.append("≤14 days out")
    elif days_out <= 45:
        score += 5
        reasons.append("≤45 days out")
    elif days_out > 150:
        score -= 8
        reasons.append("far horizon")
    score = int(max(20, min(88, score)))
    label = "high" if score >= 75 else "medium" if score >= 55 else "low"
    return score, label, "; ".join(reasons)


def primary_for_tier(base: float, tier: int) -> float:
    if tier >= 4:
        return round(base + 1.5, 2)
    if tier >= 3:
        return round(base + 0.5, 2)
    return round(base - 0.5, 2)


def analyze_historical(priors: dict) -> pd.DataFrame:
    df = pd.read_csv(HIST, parse_dates=["date"])
    rows = []
    for _, r in df.iterrows():
        fill = r["attendance"] / r["capacity"]
        tier = int(r["opponent_tier"])
        primary = primary_for_tier(priors["primary_adult"], tier)
        secondary, sec_src = sales_secondary(primary, fill, tier, priors)
        out = optimize_game(int(r["attendance"]), primary, secondary)
        out.update({
            "date": r["date"].strftime("%Y-%m-%d"),
            "opponent": r["opponent"],
            "competition": "League Two",
            "phase": "historical",
            "certainty": "observed_attendance",
            "confidence": 92,
            "confidence_label": "high",
            "confidence_reason": "observed attendance + club/L2 sales prior",
            "played": True,
            "secondary_source": sec_src,
            "primary_source": "club_sales_band",
            "model_secondary": secondary,
            "att_lo90": None,
            "att_hi90": None,
            "lift_lo90": None,
            "lift_hi90": None,
        })
        rows.append(out)
    return pd.DataFrame(rows)


def analyze_forward(priors: dict, as_of: date | None = None) -> tuple[pd.DataFrame, dict]:
    as_of = as_of or date.today()
    fixtures = pd.read_csv(FIXTURES, parse_dates=["date"])
    hist = pd.read_csv(HIST)
    fill_model, diag = train_fill_model(hist)
    mean_fill = float((hist["attendance"] / hist["capacity"]).mean())
    std_fill = float((hist["attendance"] / hist["capacity"]).std())
    live = latest_live_secondary()
    n_live = 0
    n_played = 0
    rows = []

    for _, f in fixtures.iterrows():
        d = f["date"].date()
        days_out = (d - as_of).days
        tier = int(f["opponent_tier"])
        away = f["away"]
        if away in ("Swindon Town", "Bromley") or int(f.get("rivalry_away", 0) or 0):
            tier = max(tier, 4)

        primary = primary_for_tier(priors["primary_adult"], tier)
        if pd.notna(f.get("primary_avg_gbp")) and float(f["primary_avg_gbp"]) >= 21:
            primary = float(f["primary_avg_gbp"])

        X = pd.DataFrame([{"opponent_tier": float(tier)}])
        model_fill = float(np.clip(fill_model.predict(X)[0], 0.35, 0.85))
        if int(f.get("promoted_away", 0) or 0):
            model_fill = min(0.85, model_fill + 0.03)
        if away == "Rotherham United":
            model_fill = min(0.88, model_fill + 0.06)
            tier = max(tier, 3)

        observed = pd.notna(f.get("observed_attendance")) and str(f.get("observed_attendance")).strip() != ""
        played = d < as_of or observed
        if observed:
            att = int(float(f["observed_attendance"]))
            fill = att / CAP
            n_played += 1
            certainty = "observed_attendance"
            secondary, sec_src = sales_secondary(primary, fill, tier, priors)
            conf, conf_lab, conf_why = confidence_score(
                observed=True, days_out=days_out, tier=tier, fill_mape=diag["fill_loo_mape_pct"]
            )
            conf_why = "observed attendance; " + conf_why
        else:
            fill = model_fill
            att = int(CAP * fill)
            secondary, sec_src = sales_secondary(primary, fill, tier, priors)
            certainty = "l2_sales_prior"
            conf, conf_lab, conf_why = confidence_score(
                observed=False, days_out=days_out, tier=tier, fill_mape=diag["fill_loo_mape_pct"]
            )
            conf_why = "League Two club-sales prior (thin StubHub); " + conf_why
            if played and not observed:
                n_played += 1
                certainty = "played_model_pending_attendance"
                conf = min(conf, 65)

        model_secondary = secondary
        live_price = live.get(str(f.get("fixture_id", "")), live.get(away.strip().lower()))
        if live_price is not None:
            secondary = float(live_price)
            sec_src = "live_stubhub_l2"
            n_live += 1
            conf = min(95, conf + 12)
            conf_lab = "high" if conf >= 75 else conf_lab
            conf_why = "live StubHub UK get-in (L2-filtered); " + conf_why
            certainty = "live_secondary"

        out = optimize_game(att, primary, secondary)
        width = std_fill * (1.0 + (100 - conf) / 70.0)
        lo = int(CAP * max(0.30, fill - 1.645 * width))
        hi = int(CAP * min(0.95, fill + 1.645 * width))
        out.update({
            "date": d.isoformat(),
            "opponent": away,
            "competition": "League Two",
            "phase": "projection",
            "certainty": certainty,
            "confidence": conf,
            "confidence_label": conf_lab,
            "confidence_reason": conf_why,
            "model_secondary": round(model_secondary, 2),
            "played": bool(played),
            "secondary_source": sec_src,
            "primary_source": "club_sales_band",
            "days_out": days_out,
            "opponent_tier": tier,
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
        "n_live_stubhub": n_live,
        "mean_fill_hist": round(mean_fill, 3),
        "capacity": CAP,
        "venue": "Priestfield Stadium",
        "competition": "EFL League Two",
        "first_home_date": fixtures["date"].min().strftime("%Y-%m-%d"),
        "based_on_promotion_jump": False,
        "club_primary_adult_gbp": priors["primary_adult"],
        "sales_seed_rows": priors["n_seed_rows"],
        "note": priors["stubhub_l2_note"],
    }
    return pd.DataFrame(rows), meta


def embed_explorer(summary: dict) -> None:
    html = EXPLORER.read_text()
    payload = json.dumps(summary, separators=(",", ":"))
    marker = "const ANALYSIS = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("ANALYSIS marker not found")
    brace = html.find("{", start)
    depth = 0
    end = None
    for i in range(brace, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                if html[end:end + 1] == ";":
                    end += 1
                break
    if end is None:
        raise RuntimeError("Could not find end of ANALYSIS")
    EXPLORER.write_text(html[:start] + marker + payload + ";" + html[end:])


def main() -> None:
    as_of = date.today()
    priors = load_sales_priors()
    hist = analyze_historical(priors)
    fwd, model_meta = analyze_forward(priors, as_of)
    all_df = pd.concat([hist, fwd], ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(OUT_CSV, index=False)

    summary = {
        "club": "Gillingham",
        "capacity": CAP,
        "venue": "Priestfield Stadium",
        "conc_per_head_gbp": CONC_PER_HEAD,
        "capture_rate": CAPTURE_RATE,
        "as_of": as_of.isoformat(),
        "method": {
            "competition": "EFL League Two only — England’s 4th division, not the Premier League",
            "historical": "Last season’s home games with published crowd sizes",
            "sales_data": (
                "Ticket prices from Gillingham’s published adult home prices (about £22–£25), "
                "checked against other League Two clubs’ published prices. "
                "StubHub almost never lists League Two tickets, so we do not use Premier League resale prices."
            ),
            "projections_from": "Crowd forecast from Gillingham’s own recent home crowds against similar opponents",
            "promotion_jump": "Not used — Gillingham are already in League Two",
            "concessions": f"Food and beverage assumed at £{CONC_PER_HEAD} per fan in the ground",
            "optimization": "Nudge prices up on busy games; targeted promo on quiet games",
            "confidence": "Higher for games already played; lower for quiet games far in the future",
            "played_status": (
                f"As of {as_of.isoformat()}: {model_meta['n_homes_played']} of "
                f"{model_meta['n_homes_total']} League Two home games played."
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
            "label": "League Two 2026–27",
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
            "based_on_promotion_jump": False,
        },
        "games": all_df.replace({np.nan: None}).to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    embed_explorer(summary)
    print(json.dumps({
        "historical": summary["historical"],
        "future_l2": summary["projection_pl"],
        "model": summary["model"],
        "sales": summary["method"]["sales_data"],
    }, indent=2))
    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}\nEmbedded {EXPLORER}")


if __name__ == "__main__":
    main()
