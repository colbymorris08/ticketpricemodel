#!/usr/bin/env python3
"""
SeatGeek Platform API client (v2).

Sign up: https://seatgeek.com/build  →  get a free client_id (500 req/day).

Note: SeatGeek does NOT expose individual listings via the public API.
We use event stats: stats.lowest_price, stats.average_price, stats.listing_count
as the secondary-market demand signal for WNBA (and US sports).

Set env: SEATGEEK_CLIENT_ID=your_client_id
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.seatgeek.com/2"
ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    """Load .env from repo root if present (no extra dependency)."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def get_client_id() -> str | None:
    _load_dotenv()
    cid = os.environ.get("SEATGEEK_CLIENT_ID", "").strip()
    return cid or None


def _get(path: str, params: dict[str, Any]) -> dict | None:
    client_id = get_client_id()
    if not client_id:
        print("  SeatGeek: no SEATGEEK_CLIENT_ID — skip (see docs/SEATGEEK_SETUP.md)")
        return None

    params = {**params, "client_id": client_id}
    url = f"{API_BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ticketpricemodel/1.0 (research)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        print(f"  SeatGeek API error: {exc}")
        return None


def search_events(
    *,
    query: str | None = None,
    performer_slug: str | None = None,
    venue_id: int | None = None,
    date_gte: str | None = None,
    date_lte: str | None = None,
    per_page: int = 25,
) -> list[dict]:
    """Return event dicts from /events."""
    params: dict[str, Any] = {"per_page": per_page, "sort": "datetime_local.asc"}
    if query:
        params["q"] = query
    if performer_slug:
        params["performers.slug"] = performer_slug
    if venue_id:
        params["venue.id"] = venue_id
    if date_gte:
        params["datetime_utc.gte"] = date_gte
    if date_lte:
        params["datetime_utc.lte"] = date_lte

    data = _get("/events", params)
    if not data:
        return []
    return data.get("events", [])


def event_secondary_stats(event: dict) -> dict:
    """Extract demand signals from an event document."""
    stats = event.get("stats") or {}
    return {
        "secondary_get_in": stats.get("lowest_price") or stats.get("lowest_sg_base_price"),
        "secondary_avg": stats.get("average_price") or stats.get("average_sg_base_price"),
        "listing_count_est": stats.get("listing_count") or stats.get("ticket_count"),
        "seatgeek_event_id": event.get("id"),
        "seatgeek_url": event.get("url") or event.get("short_title"),
        "event_title": event.get("title"),
        "datetime_local": event.get("datetime_local"),
        "obs_source": "seatgeek_api",
    }


def find_home_game(
    home_team: str,
    away_team: str,
    game_date: str,
    *,
    performer_slug: str = "portland-fire",
) -> dict | None:
    """
    Match a home fixture to a SeatGeek event by date + opponent in title.
    game_date: YYYY-MM-DD
    """
    date_gte = f"{game_date}T00:00:00"
    date_lte = f"{game_date}T23:59:59"

    # Try performer slug first, then text search
    candidates = search_events(
        performer_slug=performer_slug,
        date_gte=date_gte,
        date_lte=date_lte,
    )
    if not candidates:
        candidates = search_events(
            query=f"{home_team} {away_team}",
            date_gte=date_gte,
            date_lte=date_lte,
        )

    away_tokens = [t for t in away_team.lower().replace(".", "").split() if len(t) > 2]
    for ev in candidates:
        title = (ev.get("title") or "").lower()
        if any(tok in title for tok in away_tokens):
            return event_secondary_stats(ev)
    if len(candidates) == 1:
        return event_secondary_stats(candidates[0])
    return None


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "Portland Fire"
    events = search_events(query=q, per_page=5)
    print(f"Found {len(events)} events for q={q!r}")
    for ev in events[:3]:
        s = event_secondary_stats(ev)
        print(f"  {ev.get('datetime_local')} | {ev.get('title')} | get-in ${s['secondary_get_in']}")
