#!/usr/bin/env python3
"""
Snapshot secondary-market get-in prices for upcoming fixtures.

Attempts StubHub UK search for Coventry home games. Falls back to tier-based
estimates when live fetch fails (ToS / bot protection). WNBA uses Ticketmaster
starting-price proxy from reference data when live scrape unavailable.
"""

from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from config import COVENTRY_FIXTURES, PORTLAND_FIXTURES, RAW, WNBA_TIER
from fetch_schedule import load_coventry, load_portland, next_n_home


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _http_get(url: str, timeout: int = 15) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"  fetch failed: {exc}")
        return None


def stubhub_uk_search(home: str, away: str, date: pd.Timestamp) -> dict | None:
    """Best-effort parse of StubHub UK search results."""
    q = f"{home} {away} tickets"
    url = "https://www.stubhub.co.uk/find/s/?q=" + urllib.parse.quote(q)
    html = _http_get(url)
    if not html:
        return None

    # Look for GBP price patterns in page
    prices = [int(p.replace(",", "")) for p in re.findall(r"£(\d+(?:,\d{3})*)", html)]
    if not prices:
        prices = [int(p) for p in re.findall(r'"rawPrice":\s*(\d+)', html)]
    if not prices:
        return None

    get_in = min(prices)
    return {
        "secondary_get_in": get_in,
        "listing_count_est": max(10, len(prices) * 3),
        "obs_source": "stubhub_uk_live",
        "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "search_url": url,
        "fixture_date": str(date.date()),
        "home": home,
        "away": away,
    }


def estimate_pl_secondary(row: pd.Series, days_out: int) -> dict:
    """Tier prior for promoted PL home games when live data missing."""
    base = 42.0
    if row.get("big_six_away"):
        base = 95.0
    elif row.get("promoted_away"):
        base = 48.0
    # urgency premium closer to kickoff
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
            print(f"Trying StubHub UK: Coventry vs {row['away']} ({days_out}d out)...")
            snap = stubhub_uk_search(row["home"], row["away"], row["date"])
        if snap is None:
            snap = estimate_pl_secondary(row, days_out)
            print(f"  using prior estimate: £{snap['secondary_get_in']}")
        snap["fixture_id"] = row["fixture_id"]
        snap["track"] = "pl_coventry"
        snap["horizon_days"] = days_out
        rows.append(snap)
    return pd.DataFrame(rows)


def snapshot_portland_upcoming(as_of: datetime, try_live: bool = True) -> pd.DataFrame:
    from seatgeek_client import find_home_game, get_client_id

    por = load_portland()
    upcoming = por[(por["date"] >= pd.Timestamp(as_of)) & (por["season_phase"] == "upcoming")]
    rows = []
    for _, row in upcoming.iterrows():
        days_out = (row["date"].to_pydatetime().date() - as_of.date()).days
        snap = None
        if try_live and get_client_id():
            print(f"Trying SeatGeek: Portland vs {row['away']} ({days_out}d out)...")
            sg = find_home_game(
                row["home"], row["away"], str(row["date"].date()),
                performer_slug="portland-fire",
            )
            if sg and sg.get("secondary_get_in"):
                snap = {
                    **sg,
                    "snapshot_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "fixture_date": str(row["date"].date()),
                    "home": row["home"],
                    "away": row["away"],
                    "days_out": days_out,
                }
                print(f"  SeatGeek get-in: ${snap['secondary_get_in']}")
        if snap is None:
            snap = estimate_wnba_secondary(row)
            snap["days_out"] = days_out
            if try_live and not get_client_id():
                print(f"  SeatGeek skipped (no API key); prior: ${snap['secondary_get_in']}")
            elif snap["obs_source"] == "wnba_tier_prior":
                print(f"  SeatGeek no match; prior: ${snap['secondary_get_in']}")
        snap["fixture_id"] = row["fixture_id"]
        snap["track"] = "wnba_portland"
        snap["horizon_days"] = days_out
        rows.append(snap)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Snapshot secondary prices")
    parser.add_argument("--as-of", default="2026-08-18")
    parser.add_argument("--no-live", action="store_true")
    args = parser.parse_args()

    as_of = datetime.strptime(args.as_of, "%Y-%m-%d")
    out_dir = RAW / "secondary_snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    cov = snapshot_coventry(as_of, n=3, try_live=not args.no_live)
    por = snapshot_portland_upcoming(as_of, try_live=not args.no_live)
    combined = pd.concat([cov, por], ignore_index=True)

    stamp = as_of.strftime("%Y%m%d")
    out_path = out_dir / f"snapshot_{stamp}.csv"
    combined.to_csv(out_path, index=False)
    json_path = out_dir / f"snapshot_{stamp}.json"
    json_path.write_text(combined.to_json(orient="records", indent=2))

    print(f"\nWrote {len(combined)} rows → {out_path}")


if __name__ == "__main__":
    main()
