#!/usr/bin/env python3
"""
Snapshot secondary-market get-in prices for upcoming fixtures.

Coventry (PL): StubHub UK via HTTP.
Portland (WNBA): StubHub US via Playwright (SeatGeek optional fallback).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import RAW
from fetch_schedule import load_coventry, load_portland, next_n_home
from stubhub_scraper import stubhub_search


def estimate_pl_secondary(row: pd.Series, days_out: int) -> dict:
    base = 42.0
    if row.get("big_six_away"):
        base = 95.0
    elif row.get("promoted_away"):
        base = 48.0
    urgency = max(0, (14 - days_out) * 1.5)
    get_in = base + urgency
    return {
        "secondary_get_in": round(get_in, 2),
        "listing_count_est": 55 if get_in < 60 else 28,
        "obs_source": "pl_tier_prior",
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fixture_date": str(row["date"].date()),
        "home": row["home"],
        "away": row["away"],
        "days_out": days_out,
    }


def estimate_wnba_secondary(row: pd.Series) -> dict:
    tier = int(row.get("opponent_tier", 2))
    base = {2: 34, 3: 40, 4: 52, 5: 70}.get(tier, 36)
    weekend = 1.08 if row.get("is_weekend") else 1.0
    get_in = round(base * weekend, 2)
    return {
        "secondary_get_in": get_in,
        "listing_count_est": max(20, 90 - tier * 12),
        "obs_source": "wnba_tier_prior",
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fixture_date": str(row["date"].date()),
        "home": row["home"],
        "away": row["away"],
    }


def snapshot_coventry(as_of: datetime, n: int = 3, try_live: bool = True) -> pd.DataFrame:
    df = next_n_home(load_coventry(), as_of, n)
    rows = []
    for _, row in df.iterrows():
        days_out = (row["date"].to_pydatetime().date() - as_of.date()).days
        snap = None
        if try_live:
            print(f"StubHub UK: Coventry vs {row['away']} ({days_out}d out)...")
            snap = stubhub_search(
                row["home"], row["away"], row["date"], region="uk"
            )
            if snap:
                print(f"  get-in £{snap['secondary_get_in']}")
        if snap is None:
            snap = estimate_pl_secondary(row, days_out)
            print(f"  prior estimate: £{snap['secondary_get_in']}")
        snap["fixture_id"] = row["fixture_id"]
        snap["track"] = "pl_coventry"
        snap["horizon_days"] = days_out
        rows.append(snap)
    return pd.DataFrame(rows)


def snapshot_portland_upcoming(
    as_of: datetime, try_live: bool = True, headed: bool = False
) -> pd.DataFrame:
    por = load_portland()
    upcoming = por[(por["date"] >= pd.Timestamp(as_of)) & (por["season_phase"] == "upcoming")]
    rows = []
    for _, row in upcoming.iterrows():
        days_out = (row["date"].to_pydatetime().date() - as_of.date()).days
        snap = None
        if try_live:
            print(f"StubHub US: Portland vs {row['away']} ({days_out}d out)...")
            snap = stubhub_search(
                row["home"],
                row["away"],
                row["date"],
                region="us",
                fixture_id=row["fixture_id"],
                headed=headed,
            )
            if snap:
                print(f"  get-in ${snap['secondary_get_in']}")
        if snap is None:
            # Optional SeatGeek if approved later
            try:
                from seatgeek_client import find_home_game, get_client_id

                if try_live and get_client_id():
                    sg = find_home_game(
                        row["home"], row["away"], str(row["date"].date())
                    )
                    if sg and sg.get("secondary_get_in"):
                        snap = {
                            **sg,
                            "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                            "fixture_date": str(row["date"].date()),
                            "home": row["home"],
                            "away": row["away"],
                            "days_out": days_out,
                            "search_url": "",
                            "event_url": sg.get("seatgeek_url", ""),
                        }
                        print(f"  SeatGeek get-in: ${snap['secondary_get_in']}")
            except Exception:
                pass
        if snap is None:
            snap = estimate_wnba_secondary(row)
            snap["days_out"] = days_out
            print(f"  prior estimate: ${snap['secondary_get_in']}")
        snap["fixture_id"] = row["fixture_id"]
        snap["track"] = "wnba_portland"
        snap["horizon_days"] = days_out
        rows.append(snap)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot secondary prices")
    parser.add_argument("--as-of", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (helps if StubHub US blocks headless)",
    )
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d")
    out_dir = RAW / "secondary_snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    cov = snapshot_coventry(as_of, n=3, try_live=not args.no_live)
    por = snapshot_portland_upcoming(
        as_of, try_live=not args.no_live, headed=args.headed
    )
    combined = pd.concat([cov, por], ignore_index=True)

    stamp = as_of.strftime("%Y%m%d")
    out_path = out_dir / f"snapshot_{stamp}.csv"
    combined.to_csv(out_path, index=False)
    json_path = out_dir / f"snapshot_{stamp}.json"
    json_path.write_text(combined.to_json(orient="records", indent=2))

    print(f"\nWrote {len(combined)} rows → {out_path}")


if __name__ == "__main__":
    main()
