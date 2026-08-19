#!/usr/bin/env python3
"""
Train LightGBM demand models and output HOLD / MONITOR / PROMOTE recommendations.

WNBA: train on Portland Fire completed 2026 home games, predict rest of season.
PL: train on promoted-club seed panel, predict Coventry 2026-27 home fixtures.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
except ImportError:
    lgb = None

from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_percentage_error

from config import FORECAST_HORIZONS, PROCESSED, RESULTS


def _train_model(X: pd.DataFrame, y: pd.Series):
    if lgb is not None:
        model = lgb.LGBMRegressor(
            n_estimators=80,
            max_depth=4,
            learning_rate=0.08,
            random_state=42,
            verbose=-1,
        )
    else:
        model = GradientBoostingRegressor(n_estimators=80, max_depth=3, random_state=42)
    model.fit(X, y)
    return model


def classify_action(gap: float, pred: float, primary: float, listing_est: float = 50) -> str:
    """HOLD = underpriced hot demand; PROMOTE = soft demand; else MONITOR."""
    ratio = pred / max(primary, 1)
    if pred > primary * 1.35 and ratio > 1.25 and listing_est < 60:
        return "HOLD"
    if pred < primary * 1.05 and listing_est > 70:
        return "PROMOTE"
    if gap > primary * 0.25:
        return "HOLD"
    if pred < primary * 0.95:
        return "PROMOTE"
    return "MONITOR"


def backtest_wnba(train_df: pd.DataFrame) -> dict:
    features = ["opponent_tier", "is_weekend", "game_number"]
    X = train_df[features]
    y = train_df["target"]

    # leave-last-3-out backtest on completed season
    if len(train_df) < 6:
        return {"mape": None, "n_holdout": 0}

    holdout = train_df.tail(3)
    fit = train_df.iloc[:-3]
    model = _train_model(fit[features], fit["target"])
    preds = model.predict(holdout[features])
    mape = mean_absolute_percentage_error(holdout["target"], preds)
    return {"mape": round(mape * 100, 1), "n_holdout": 3, "model": model}


def train_wnba_full(train_df: pd.DataFrame):
    features = ["opponent_tier", "is_weekend", "game_number"]
    return _train_model(train_df[features], train_df["target"]), features


def train_pl(pl_train: pd.DataFrame):
    features = ["big_six_away", "attendance_pct"]
    X = pl_train[features]
    y = pl_train["target"]
    return _train_model(X, y), features


def predict_horizons(base_pred: float, days_out: int) -> dict:
    """Simple horizon adjustment: prices rise as event approaches."""
    out = {}
    for h in FORECAST_HORIZONS:
        if days_out >= h:
            adj = 1.0 + (30 - h) * 0.008
        else:
            adj = 1.0 + (30 - days_out) * 0.012
        out[f"pred_t{h}"] = round(base_pred * adj, 2)
    # pick closest horizon to current days_out
    closest = min(FORECAST_HORIZONS, key=lambda x: abs(x - days_out))
    out["pred_active"] = out[f"pred_t{closest}"]
    out["active_horizon"] = closest
    return out


def run(as_of: str) -> pd.DataFrame:
    wnba_train = pd.read_csv(PROCESSED / "wnba_train.csv")
    pl_train = pd.read_csv(PROCESSED / "pl_train.csv")
    cov_score = pd.read_csv(PROCESSED / "coventry_score.csv", parse_dates=["date"])
    por_score = pd.read_csv(PROCESSED / "portland_score.csv", parse_dates=["date"])

    bt = backtest_wnba(wnba_train)
    wnba_model, wnba_feats = train_wnba_full(wnba_train)
    pl_model, pl_feats = train_pl(pl_train)

    rows = []
    as_of_ts = pd.Timestamp(as_of)

    # Coventry predictions
    for _, r in cov_score.iterrows():
        days_out = (r["date"] - as_of_ts).days
        pl_row = pd.DataFrame([{
            "big_six_away": int(r["big_six_away"]),
            "attendance_pct": 0.88 if not r["big_six_away"] else 0.97,
        }])
        base = float(pl_model.predict(pl_row[pl_feats])[0])
        if int(r["big_six_away"]):
            base = max(base, 95.0 + max(0, (14 - days_out) * 2.0))
        elif int(r.get("promoted_away", 0)):
            base = max(base, 48.0)
        hz = predict_horizons(base, days_out)
        primary = float(r["primary_band_gbp"])
        pred = hz["pred_active"]
        gap = pred - primary
        live_sec = r.get("secondary_get_in")
        if pd.notna(live_sec) and live_sec:
            pred = float(live_sec)
            gap = pred - primary
        listing = 35 if r["big_six_away"] else 55
        action = classify_action(gap, pred, primary, listing)
        rows.append({
            "track": "pl_coventry",
            "fixture": f"{r['home']} vs {r['away']}",
            "date": r["date"].strftime("%Y-%m-%d"),
            "days_out": days_out,
            "horizon_days": hz["active_horizon"],
            "pred_secondary": pred,
            "pred_t30": hz["pred_t30"],
            "pred_t14": hz["pred_t14"],
            "pred_t3": hz["pred_t3"],
            "primary_band": primary,
            "gap": round(gap, 2),
            "live_secondary": live_sec if pd.notna(live_sec) else "",
            "action": action,
            "big_six_away": int(r["big_six_away"]),
        })

    # Portland predictions
    for _, r in por_score.iterrows():
        days_out = (r["date"] - as_of_ts).days
        por_row = pd.DataFrame([{
            "opponent_tier": int(r["opponent_tier"]),
            "is_weekend": int(r["is_weekend"]),
            "game_number": int(r["game_number"]),
        }])
        base = float(wnba_model.predict(por_row[wnba_feats])[0])
        hz = predict_horizons(base, days_out)
        primary = float(r["primary_band_usd"])
        pred = hz["pred_active"]
        gap = pred - primary
        listing = max(20, 90 - int(r["opponent_tier"]) * 12)
        action = classify_action(gap, pred, primary, listing)
        rows.append({
            "track": "wnba_portland",
            "fixture": f"{r['home']} vs {r['away']}",
            "date": r["date"].strftime("%Y-%m-%d"),
            "days_out": days_out,
            "horizon_days": hz["active_horizon"],
            "pred_secondary": pred,
            "pred_t30": hz["pred_t30"],
            "pred_t14": hz["pred_t14"],
            "pred_t3": hz["pred_t3"],
            "primary_band": primary,
            "gap": round(gap, 2),
            "live_secondary": "",
            "action": action,
            "opponent_tier": int(r["opponent_tier"]),
        })

    recs = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "recommendations.csv"
    recs.to_csv(out, index=False)

    summary_path = RESULTS / "backtest_summary.txt"
    mape_str = f"{bt['mape']}%" if bt["mape"] is not None else "n/a"
    summary_path.write_text(
        f"WNBA Portland Fire leave-last-3-out MAPE: {mape_str}\n"
        f"PL training rows: {len(pl_train)} (promoted-club seed)\n"
        f"Recommendations: {len(recs)} fixtures\n"
    )
    print(recs.to_string(index=False))
    print(f"\n→ {out}")
    return recs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-08-18")
    args = parser.parse_args()
    run(args.as_of)


if __name__ == "__main__":
    main()
