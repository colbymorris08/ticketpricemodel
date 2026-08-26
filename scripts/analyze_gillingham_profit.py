#!/usr/bin/env python3
"""
Gillingham matchday revenue: actual vs optimized — League Two only.

Past: 2025–26 League Two homes with observed attendance.
Future: all 23 League Two 2026–27 homes. No Premier League module.
Fill / WTP from Gillingham's own League Two history + opponent tier;
observed attendance used when a home has already been played.
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
HIST = ROOT / "data" / "reference" / "gillingham_2526_home_attendance.csv"
FIXTURES = ROOT / "data" / "fixtures" / "gillingham_2026_27_home.csv"
OUT_JSON = ROOT / "results" / "gillingham_profit_analysis.json"
OUT_CSV = ROOT / "results" / "gillingham_profit_by_game.csv"
EXPLORER = ROOT / "gillingham_explorer.html"
CAP = 11582
CONC_PER_HEAD = 6.0  # lower-league F&B placeholder vs PL £8
CAPTURE_RATE = 0.45


def wtp_from_fill(primary: float, fill: float, tier: int) -> float:
    if fill >= 0.70:
        mult = 1.45
    elif fill >= 0.55:
        mult = 1.28
    elif fill >= 0.45:
        mult = 1.12
    else:
        mult = 1.02
    tier_bump = {2: 0.0, 3: 0.05, 4: 0.12}.get(int(tier), 0.0)
    return round(primary * (mult + tier_bump), 2)


def optimize_game(att: int, primary: float, secondary: float) -> dict:
    fill = att / CAP
    ticket_rev = att * primary
    conc_rev = att * CONC_PER_HEAD
    actual_total = ticket_rev + conc_rev
    ratio = secondary / max(primary, 1)

    # Soft gates common in L2 — promo room when fill < ~55%
    if fill >= 0.62 and ratio >= 1.22:
        opt_price = primary + CAPTURE_RATE * (secondary - primary)
        opt_att = att
        action = "PRICE_CAPTURE"
        cls = "undervalued"
    elif fill < 0.52 or ratio < 1.08:
        opt_price = primary * 0.93
        opt_att = min(CAP, int(att * 1.12))
        action = "PROMO_TARGET"
        cls = "soft"
    else:
        opt_price = primary * 1.05
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


def train_fill_model(hist: pd.DataFrame) -> tuple:
    X = hist[["opponent_tier"]].astype(float)
    y = (hist["attendance"] / hist["capacity"]).astype(float)
    model = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
    model.fit(X, y)
    loo = LeaveOneOut()
    preds = []
    for tr, te in loo.split(X):
        m = GradientBoostingRegressor(n_estimators=60, max_depth=2, random_state=42)
        m.fit(X.iloc[tr], y.iloc[tr])
        preds.append(float(m.predict(X.iloc[te])[0]))
    mae = float(np.mean(np.abs(y - np.array(preds))))
    mape = float(mean_absolute_percentage_error(y, preds)) * 100
    return model, {"fill_loo_mae": round(mae, 3), "fill_loo_mape_pct": round(mape, 1), "n_hist": int(len(hist))}


def confidence_score(*, observed: bool, days_out: int, tier: int, fill_mape: float) -> tuple[int, str, str]:
    if observed:
        return 92, "high", "observed attendance"
    score = 48
    reasons = ["League Two own-history model"]
    score += max(5, 22 - int(fill_mape / 2))
    reasons.append(f"fill LOO MAPE {fill_mape:.0f}%")
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
            "competition": "League Two",
            "phase": "historical",
            "certainty": "observed_attendance",
            "confidence": 92,
            "confidence_label": "high",
            "confidence_reason": "observed attendance + fill-implied WTP",
            "played": True,
            "secondary_source": "wtp_from_fill",
        })
        rows.append(out)
    return pd.DataFrame(rows)


def analyze_forward(as_of: date | None = None) -> tuple[pd.DataFrame, dict]:
    as_of = as_of or date.today()
    fixtures = pd.read_csv(FIXTURES, parse_dates=["date"])
    hist = pd.read_csv(HIST)
    fill_model, diag = train_fill_model(hist)
    mean_fill = float((hist["attendance"] / hist["capacity"]).mean())
    std_fill = float((hist["attendance"] / hist["capacity"]).std())

    rows = []
    n_played = 0
    for _, f in fixtures.iterrows():
        d = f["date"].date()
        days_out = (d - as_of).days
        tier = int(f["opponent_tier"])
        primary = float(f["primary_avg_gbp"])
        away = f["away"]
        rivalry = int(f.get("rivalry_away", 0) or 0)
        if away in ("Swindon Town", "Bromley") or rivalry:
            tier = max(tier, 4)

        X = pd.DataFrame([{"opponent_tier": float(tier)}])
        model_fill = float(np.clip(fill_model.predict(X)[0], 0.35, 0.85))
        # mild bumps
        if int(f.get("promoted_away", 0) or 0):
            model_fill = min(0.85, model_fill + 0.03)
        if away == "Rotherham United":
            model_fill = min(0.88, model_fill + 0.06)

        observed = pd.notna(f.get("observed_attendance")) and str(f.get("observed_attendance")).strip() != ""
        played = d < as_of or observed
        if observed:
            att = int(float(f["observed_attendance"]))
            fill = att / CAP
            n_played += 1
            certainty = "observed_attendance"
            secondary = wtp_from_fill(primary, fill, tier)
            secondary_source = "wtp_from_fill_played"
            conf, conf_lab, conf_why = confidence_score(
                observed=True, days_out=days_out, tier=tier, fill_mape=diag["fill_loo_mape_pct"]
            )
        else:
            fill = model_fill
            att = int(CAP * fill)
            secondary = wtp_from_fill(primary, fill, tier)
            # floor secondary slightly above soft primary for rivalry
            if tier >= 4:
                secondary = max(secondary, primary * 1.35)
            secondary_source = "league_two_fill_model"
            certainty = "model_secondary"
            conf, conf_lab, conf_why = confidence_score(
                observed=False, days_out=days_out, tier=tier, fill_mape=diag["fill_loo_mape_pct"]
            )
            if played and not observed:
                n_played += 1
                certainty = "played_model_pending_attendance"
                conf = min(conf, 65)

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
            "model_secondary": round(secondary, 2),
            "played": bool(played),
            "secondary_source": secondary_source,
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
        "mean_fill_hist": round(mean_fill, 3),
        "capacity": CAP,
        "venue": "Priestfield Stadium",
        "competition": "EFL League Two",
        "first_home_date": fixtures["date"].min().strftime("%Y-%m-%d"),
        "based_on_promotion_jump": False,
        "note": "Gillingham compete in League Two (not Championship / Premier League).",
    }
    return pd.DataFrame(rows), meta


def embed_explorer(summary: dict) -> None:
    if not EXPLORER.exists():
        raise FileNotFoundError(EXPLORER)
    html = EXPLORER.read_text()
    payload = json.dumps(summary, separators=(",", ":"))
    marker = "const ANALYSIS = "
    start = html.find(marker)
    if start < 0:
        raise RuntimeError("ANALYSIS marker not found")
    brace = html.find("{", start)
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
        raise RuntimeError("Could not find end of ANALYSIS")
    EXPLORER.write_text(html[:start] + marker + payload + ";" + html[end:])


def main() -> None:
    as_of = date.today()
    hist = analyze_historical()
    fwd, model_meta = analyze_forward(as_of)
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
            "competition": "EFL League Two only — no Premier League projection",
            "historical": "2025-26 League Two home attendances (observed)",
            "projections_from": "Own-history GradientBoosting fill model by opponent tier + fill-implied WTP",
            "promotion_jump": "Not applicable — Gillingham are League Two, not a Championship→PL jump case",
            "concessions": f"£{CONC_PER_HEAD}/head League Two F&B placeholder",
            "optimization": "PRICE_CAPTURE when relatively full & WTP≫face; PROMO_TARGET on soft gates",
            "confidence": "Per-game 0–100 from observed vs model, tier, days-out",
            "played_status": (
                f"As of {as_of.isoformat()}: {model_meta['n_homes_played']} of "
                f"{model_meta['n_homes_total']} League Two homes played/logged."
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
        "projection_pl": {  # keep key name for explorer reuse; content is League Two future
            "label": "League Two 2026–27",
            "n_games": int(len(fwd)),
            "n_played": int(model_meta["n_homes_played"]),
            "n_live_stubhub": 0,
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
        "played": summary["method"]["played_status"],
    }, indent=2))
    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}\nEmbedded {EXPLORER}")


if __name__ == "__main__":
    main()
