#!/usr/bin/env python3
"""Build modeling features from fixtures, snapshots, and reference prices."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import (
    COVENTRY_FIXTURES,
    PL_SEED,
    PORTLAND_FIXTURES,
    PRIMARY_BANDS,
    PROCESSED,
    RAW,
    WNBA_OBSERVED,
    FORECAST_HORIZONS,
)
from fetch_schedule import load_coventry, load_portland


def latest_snapshot(as_of: str) -> pd.DataFrame | None:
    snap_dir = RAW / "secondary_snapshots"
    if not snap_dir.exists():
        return None
    candidates = sorted(snap_dir.glob("snapshot_*.csv"))
    if not candidates:
        return None
    return pd.read_csv(candidates[-1])


def build_wnba_train() -> pd.DataFrame:
    fixtures = load_portland()
    obs = pd.read_csv(WNBA_OBSERVED)
    train = fixtures[fixtures["season_phase"] == "completed"].merge(
        obs[["fixture_id", "observed_get_in_usd", "listing_count_est"]],
        on="fixture_id",
        how="left",
    )
    train = train.rename(columns={"observed_get_in_usd": "secondary_get_in"})
    bands = pd.read_csv(PRIMARY_BANDS)
    train = train.merge(
        bands[["fixture_id", "primary_band_usd"]],
        on="fixture_id",
        how="left",
    )
    train["primary_band_usd"] = train["primary_band_usd"].fillna(30)
    train["gap_usd"] = train["secondary_get_in"] - train["primary_band_usd"]
    train["target"] = train["secondary_get_in"]
    return train


def build_pl_train() -> pd.DataFrame:
    seed = pd.read_csv(PL_SEED)
    seed["big_six_away"] = seed["big_six_away"].astype(int)
    seed["target"] = seed["secondary_get_in_gbp"]
    seed["primary_band_gbp"] = seed["primary_band_gbp"]
    seed["gap_gbp"] = seed["secondary_get_in_gbp"] - seed["primary_band_gbp"]
    return seed


def build_coventry_scoring(as_of: str, snapshot: pd.DataFrame | None) -> pd.DataFrame:
    cov = load_coventry()
    cov = cov[cov["date"] >= pd.Timestamp(as_of)].copy()
    bands = pd.read_csv(PRIMARY_BANDS)
    cov = cov.merge(bands[["fixture_id", "primary_band_gbp"]], on="fixture_id", how="left")
    cov["primary_band_gbp"] = cov["primary_band_gbp"].fillna(45)

    if snapshot is not None and not snapshot.empty:
        pl_snap = snapshot[snapshot["track"] == "pl_coventry"][
            ["fixture_id", "secondary_get_in", "horizon_days", "obs_source"]
        ]
        cov = cov.merge(pl_snap, on="fixture_id", how="left")
    return cov


def build_portland_scoring(as_of: str) -> pd.DataFrame:
    por = load_portland()
    por = por[(por["date"] >= pd.Timestamp(as_of)) & (por["season_phase"] == "upcoming")].copy()
    bands = pd.read_csv(PRIMARY_BANDS)
    por = por.merge(bands[["fixture_id", "primary_band_usd"]], on="fixture_id", how="left")
    por["primary_band_usd"] = por["primary_band_usd"].fillna(28)
    return por


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", default="2026-08-18")
    args = parser.parse_args()

    PROCESSED.mkdir(parents=True, exist_ok=True)
    snap = latest_snapshot(args.as_of)

    wnba_train = build_wnba_train()
    pl_train = build_pl_train()
    cov_score = build_coventry_scoring(args.as_of, snap)
    por_score = build_portland_scoring(args.as_of)

    wnba_train.to_csv(PROCESSED / "wnba_train.csv", index=False)
    pl_train.to_csv(PROCESSED / "pl_train.csv", index=False)
    cov_score.to_csv(PROCESSED / "coventry_score.csv", index=False)
    por_score.to_csv(PROCESSED / "portland_score.csv", index=False)

    print(f"WNBA train rows: {len(wnba_train)}")
    print(f"PL seed train rows: {len(pl_train)}")
    print(f"Coventry to score: {len(cov_score)}")
    print(f"Portland upcoming: {len(por_score)}")


if __name__ == "__main__":
    main()
