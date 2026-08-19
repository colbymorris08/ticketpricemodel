#!/usr/bin/env python3
"""Load and validate fixture schedules for Coventry (PL) and Portland Fire (WNBA)."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import COVENTRY_FIXTURES, PORTLAND_FIXTURES, ROOT


def load_coventry() -> pd.DataFrame:
    df = pd.read_csv(COVENTRY_FIXTURES, parse_dates=["date"])
    df["track"] = "pl_coventry"
    df["currency"] = "GBP"
    return df


def load_portland() -> pd.DataFrame:
    df = pd.read_csv(PORTLAND_FIXTURES, parse_dates=["date"])
    df["track"] = "wnba_portland"
    df["currency"] = "USD"
    if "opponent_tier" not in df.columns:
        from config import WNBA_TIER

        df["opponent_tier"] = df["away"].map(WNBA_TIER).fillna(2).astype(int)
    return df


def next_n_home(df: pd.DataFrame, as_of: datetime, n: int = 3) -> pd.DataFrame:
    upcoming = df[df["date"] >= pd.Timestamp(as_of)].sort_values("date")
    return upcoming.head(n)


def main() -> None:
    parser = argparse.ArgumentParser(description="Load fixture schedules")
    parser.add_argument("--as-of", default="2026-08-18", help="Reference date (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "fixtures_summary.txt")
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d")
    cov = load_coventry()
    por = load_portland()

    first3_cov = next_n_home(cov, as_of, 3)
    por_completed = por[por["season_phase"] == "completed"]
    por_upcoming = por[por["season_phase"] == "upcoming"]

    lines = [
        f"Fixtures loaded as of {as_of.date()}",
        "",
        "=== Coventry City — next 3 home (PL 2026-27) ===",
    ]
    for _, r in first3_cov.iterrows():
        lines.append(f"  {r['date'].date()} vs {r['away']} (MW{r['matchweek']})")

    lines += [
        "",
        f"=== Portland Fire — completed home: {len(por_completed)} | upcoming: {len(por_upcoming)} ===",
    ]
    for _, r in por_upcoming.head(5).iterrows():
        lines.append(f"  {r['date'].date()} vs {r['away']} (tier {r['opponent_tier']})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
