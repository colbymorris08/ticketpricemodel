#!/usr/bin/env python3
"""
Coventry matchday revenue: actual vs optimized.

Method borrows Warriors ticket-timing analytics framing (HBS case + lab CSV):
  total_matchday = ticket_revenue + concession_revenue
  Customer timing segments inform promo targeting (Planner / In-Between / Last-Minute).
  Optimization = capture willingness-to-pay when arena is near capacity (price too low),
                 or lift fill with targeted promo when soft (Warriors-style targeting, not spray).

Historical certainty: 2025-26 Championship home attendances (completed).
Forward projection: 2026-27 PL homes using live StubHub secondary + historical fill priors.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HIST = ROOT / "data" / "reference" / "coventry_2526_home_attendance.csv"
OUT_JSON = ROOT / "results" / "coventry_profit_analysis.json"
OUT_CSV = ROOT / "results" / "coventry_profit_by_game.csv"
CAP = 32609

# Warriors lab: ~$5.27 concession per ticket; UK football matchday F&B ~£8/head (scaled domain)
CONC_PER_HEAD = 8.0

# How much of secondary–primary gap we can capture without killing fill when near sellout
CAPTURE_RATE = 0.55


def wtp_from_fill(primary: float, fill: float, tier: int) -> float:
    """Implied willingness-to-pay when we lack StubHub history (Championship)."""
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

    # Near capacity + secondary >> primary → undervalued: raise price, keep fill
    # Soft fill → Warriors-style promo: slight price cut + fill lift (targeted, not blast)
    ratio = secondary / max(primary, 1)

    if fill >= 0.88 and ratio >= 1.25:
        opt_price = primary + CAPTURE_RATE * (secondary - primary)
        opt_att = att  # already packed — price capture only
        action = "PRICE_CAPTURE"
        cls = "undervalued"
    elif fill < 0.88 or ratio < 1.08:
        opt_price = primary * 0.95
        opt_att = min(CAP, int(att * 1.08))  # promo targeting lift ~8%
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
        })
        rows.append(out)
    return pd.DataFrame(rows)


def analyze_forward() -> pd.DataFrame:
    """2026-27 PL projection using live StubHub where available."""
    forward = [
        {"date": "2026-08-29", "opponent": "Hull City", "secondary": 114, "primary": 45, "live": True, "tier": 2},
        {"date": "2026-09-13", "opponent": "Brighton & Hove Albion", "secondary": 133, "primary": 45, "live": True, "tier": 3},
        {"date": "2026-10-10", "opponent": "Newcastle United", "secondary": 240, "primary": 48, "live": True, "tier": 4},
        {"date": "2026-10-24", "opponent": "Fulham", "secondary": 67.5, "primary": 45, "live": False, "tier": 3},
        {"date": "2026-12-26", "opponent": "Chelsea", "secondary": 95, "primary": 45, "live": False, "tier": 5},
        {"date": "2027-02-10", "opponent": "Liverpool", "secondary": 95, "primary": 55, "live": False, "tier": 5},
        {"date": "2027-03-13", "opponent": "Manchester City", "secondary": 95, "primary": 55, "live": False, "tier": 5},
        {"date": "2027-04-10", "opponent": "Arsenal", "secondary": 95, "primary": 55, "live": False, "tier": 5},
    ]
    # Historical mean fill / std for projection interval
    hist = pd.read_csv(HIST)
    mean_fill = (hist["attendance"] / hist["capacity"]).mean()
    std_fill = (hist["attendance"] / hist["capacity"]).std()

    rows = []
    for f in forward:
        # Hot secondary → near sellout; softer → mean fill
        if f["secondary"] / f["primary"] >= 1.5:
            fill = min(0.98, mean_fill + 1.2 * std_fill)
        elif f["secondary"] / f["primary"] >= 1.25:
            fill = min(0.96, mean_fill + 0.6 * std_fill)
        else:
            fill = mean_fill
        att = int(CAP * fill)
        out = optimize_game(att, f["primary"], f["secondary"])
        # 90% interval on attendance from hist std
        lo = int(CAP * max(0.75, fill - 1.645 * std_fill))
        hi = int(CAP * min(0.99, fill + 1.645 * std_fill))
        out.update({
            "date": f["date"],
            "opponent": f["opponent"],
            "competition": "Premier League",
            "phase": "projection",
            "certainty": "live_secondary" if f["live"] else "model_secondary",
            "att_lo90": lo,
            "att_hi90": hi,
            "lift_lo90": round(optimize_game(lo, f["primary"], f["secondary"])["lift"]),
            "lift_hi90": round(optimize_game(hi, f["primary"], f["secondary"])["lift"]),
        })
        rows.append(out)
    return pd.DataFrame(rows)


def main() -> None:
    hist = analyze_historical()
    fwd = analyze_forward()
    all_df = pd.concat([hist, fwd], ignore_index=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_csv(OUT_CSV, index=False)

    summary = {
        "capacity": CAP,
        "conc_per_head_gbp": CONC_PER_HEAD,
        "capture_rate": CAPTURE_RATE,
        "method": {
            "source": "Warriors ticket timing + matchday revenue (ticket + concession)",
            "historical": "2025-26 Championship home attendances (observed)",
            "wtp_proxy": "fill-based willingness-to-pay when StubHub history unavailable",
            "optimization": "PRICE_CAPTURE when near-full & secondary>>primary; PROMO_TARGET when soft",
        },
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
        },
        "projection_pl": {
            "n_games": int(len(fwd)),
            "actual_matchday_total_gbp": int(fwd["actual_total"].sum()),
            "optimized_matchday_total_gbp": int(fwd["opt_total"].sum()),
            "total_lift_gbp": int(fwd["lift"].sum()),
            "lift_pct": round(100 * fwd["lift"].sum() / fwd["actual_total"].sum(), 1),
            "lift_lo90_sum": int(fwd["lift_lo90"].sum()),
            "lift_hi90_sum": int(fwd["lift_hi90"].sum()),
        },
        "games": all_df.replace({np.nan: None}).to_dict(orient="records"),
    }
    OUT_JSON.write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in ("historical", "projection_pl", "method")}, indent=2))
    print(f"\nWrote {OUT_CSV}\nWrote {OUT_JSON}")


if __name__ == "__main__":
    main()
