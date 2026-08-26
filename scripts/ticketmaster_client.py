#!/usr/bin/env python3
"""
Ticketmaster Discovery API v2 — instant free API key.

Sign up: https://developer.ticketmaster.com/ → Consumer Key = TICKETMASTER_API_KEY

Returns priceRanges.min/max when Ticketmaster publishes them (PRIMARY face value).
Many WNBA/sports events omit priceRanges (dynamic / all-in pricing) — API still
gives schedule, event IDs, on-sale status, and Ticketmaster URLs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API = "https://app.ticketmaster.com/discovery/v2"

# Portland Fire attraction ID (Discovery /attractions)
PORTLAND_FIRE_ATTRACTION_ID = "K8vZ9171xZf"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_api_key() -> str | None:
    _load_dotenv()
    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    placeholders = {"", "your_api_key_here", "paste_key_here"}
    return key if key and key.lower() not in placeholders else None


def _get(path: str, params: dict[str, Any]) -> dict | None:
    api_key = get_api_key()
    if not api_key:
        return None
    params = {**params, "apikey": api_key}
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "ticketpricemodel/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"  Ticketmaster API: HTTP {exc.code} — check TICKETMASTER_API_KEY")
        return None
    except Exception as exc:
        print(f"  Ticketmaster API error: {exc}")
        return None


def search_events(
    *,
    keyword: str | None = None,
    attraction_id: str | None = None,
    venue_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    city: str | None = None,
    state_code: str | None = None,
    country_code: str = "US",
    source: str | None = None,
    classification_name: str | None = None,
    size: int = 20,
) -> list[dict]:
    params: dict[str, Any] = {"size": size, "sort": "date,asc", "countryCode": country_code}
    if keyword:
        params["keyword"] = keyword
    if attraction_id:
        params["attractionId"] = attraction_id
    if venue_id:
        params["venueId"] = venue_id
    if start_date:
        params["startDateTime"] = f"{start_date}T00:00:00Z"
    if end_date:
        params["endDateTime"] = f"{end_date}T23:59:59Z"
    if city:
        params["city"] = city
    if state_code:
        params["stateCode"] = state_code
    if source:
        params["source"] = source
    if classification_name:
        params["classificationName"] = classification_name

    data = _get("/events.json", params)
    if not data:
        return []
    return data.get("_embedded", {}).get("events", [])


def event_price_stats(event: dict) -> dict:
    ranges = event.get("priceRanges") or []
    primary_min = primary_max = None
    for pr in ranges:
        t = (pr.get("type") or "standard").lower()
        mn, mx = pr.get("min"), pr.get("max")
        if t == "standard" or primary_min is None:
            primary_min = mn if primary_min is None else min(primary_min, mn or primary_min)
            primary_max = mx if primary_max is None else max(primary_max or 0, mx or 0)
    status = (event.get("dates") or {}).get("status", {}).get("code", "")
    return {
        "primary_min": primary_min,
        "primary_max": primary_max,
        "has_price_ranges": bool(ranges),
        "onsale_status": status,
        "ticketmaster_event_id": event.get("id"),
        "ticketmaster_url": event.get("url"),
        "event_name": event.get("name"),
        "datetime_local": (event.get("dates") or {}).get("start", {}).get("localDate"),
        "obs_source": "ticketmaster_api_primary",
    }


def find_home_game(
    home_team: str,
    away_team: str,
    game_date: str,
    *,
    city: str = "Portland",
    state_code: str = "OR",
    attraction_id: str = PORTLAND_FIRE_ATTRACTION_ID,
) -> dict | None:
    """Match TM event by attraction + date + opponent in title."""
    events = search_events(
        attraction_id=attraction_id,
        start_date=game_date,
        end_date=game_date,
        city=city,
        state_code=state_code,
        classification_name="Basketball",
    )
    if not events:
        events = search_events(
            keyword=f"{home_team} {away_team}",
            start_date=game_date,
            end_date=game_date,
            city=city,
            state_code=state_code,
            classification_name="Basketball",
        )

    away_tokens = [t.lower() for t in away_team.replace(".", "").split() if len(t) > 2]
    for ev in events:
        name = (ev.get("name") or "").lower()
        if " vs" not in name and "vs." not in name:
            continue
        if any(tok in name for tok in away_tokens):
            return event_price_stats(ev)
    if len(events) == 1:
        return event_price_stats(events[0])
    return None


if __name__ == "__main__":
    key = get_api_key()
    if not key:
        print("Set TICKETMASTER_API_KEY in .env (free at developer.ticketmaster.com)")
        raise SystemExit(1)

    events = search_events(
        attraction_id=PORTLAND_FIRE_ATTRACTION_ID,
        city="Portland",
        state_code="OR",
        classification_name="Basketball",
        size=10,
    )
    print(f"API OK — found {len(events)} Portland Fire basketball events")
    priced = 0
    for ev in events:
        s = event_price_stats(ev)
        if s["has_price_ranges"]:
            priced += 1
            price_str = f"${s['primary_min']}-${s['primary_max']}"
        else:
            price_str = "no priceRanges (dynamic/all-in — TM often omits sports prices)"
        print(f"  {s['datetime_local']} | {s['event_name']}")
        print(f"    status={s['onsale_status']} | primary={price_str}")
        print(f"    id={s['ticketmaster_event_id']}")
    print()
    if priced == 0 and events:
        print("Key works. Schedule/on-sale data is usable.")
        print("Discovery does not publish face-value bands for these WNBA games.")
        print("Use primary_bands.csv + manual StubHub log for secondary, or wait for SeatGeek.")
