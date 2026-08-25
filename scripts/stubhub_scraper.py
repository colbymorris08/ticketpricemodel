#!/usr/bin/env python3
"""
StubHub secondary-price scraper (UK urllib + US Playwright).

UK / Coventry: simple HTTP fetch of stubhub.co.uk/find/s — prices in HTML.
US / WNBA: Playwright search → match event by date/opponent → event page prices.
           Event pages may 403 in CI/datacenter IPs; often works on a home Mac.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVENT_URL_CACHE = ROOT / "data" / "reference" / "stubhub_event_urls.csv"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

Region = Literal["uk", "us"]


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _http_get(url: str, timeout: int = 20) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        print(f"  HTTP fetch failed: {exc}")
        return None


def parse_prices(html: str, currency: Region) -> list[float]:
    """Extract numeric prices from HTML."""
    if currency == "uk":
        patterns = [
            r"£(\d+(?:,\d{3})*)",
            r'"rawPrice":\s*(\d+(?:\.\d+)?)',
        ]
    else:
        patterns = [
            r"\$(\d+(?:,\d{3})*(?:\.\d{2})?)",
            r'"rawPrice":\s*(\d+(?:\.\d+)?)',
            r'"listPrice":\s*(\d+(?:\.\d+)?)',
            r'"amount":\s*(\d+(?:\.\d+)?)',
        ]
    out: list[float] = []
    for pat in patterns:
        for m in re.findall(pat, html):
            try:
                out.append(float(str(m).replace(",", "")))
            except ValueError:
                pass
    # Drop obvious junk (fees displayed as cents-only, etc.)
    if currency == "us":
        out = [p for p in out if p >= 5]
    else:
        out = [p for p in out if p >= 5]
    return out


def _result(
    *,
    get_in: float,
    n_prices: int,
    source: str,
    search_url: str,
    home: str,
    away: str,
    fixture_date: str,
    event_url: str = "",
) -> dict:
    return {
        "secondary_get_in": round(get_in, 2),
        "listing_count_est": max(10, n_prices * 3),
        "obs_source": source,
        "snapshot_date": _today(),
        "search_url": search_url,
        "event_url": event_url,
        "fixture_date": fixture_date,
        "home": home,
        "away": away,
    }


def stubhub_search_uk(home: str, away: str, date: pd.Timestamp) -> dict | None:
    q = f"{home} {away} tickets"
    url = "https://www.stubhub.co.uk/find/s/?q=" + urllib.parse.quote(q)
    html = _http_get(url)
    if not html:
        return None
    prices = parse_prices(html, "uk")
    if not prices:
        return None
    return _result(
        get_in=min(prices),
        n_prices=len(prices),
        source="stubhub_uk_live",
        search_url=url,
        home=home,
        away=away,
        fixture_date=str(date.date()),
    )


def _load_event_cache() -> pd.DataFrame:
    if EVENT_URL_CACHE.exists():
        return pd.read_csv(EVENT_URL_CACHE)
    return pd.DataFrame(columns=["fixture_id", "event_url", "stubhub_event_id", "notes"])


def _date_slug(date: pd.Timestamp) -> str:
    """StubHub URL date format: 8-30-2026"""
    d = date.to_pydatetime()
    return f"{d.month}-{d.day}-{d.year}"


def _match_event_url(html: str, away: str, date: pd.Timestamp, home_slug: str = "portland-fire") -> str | None:
    slug = _date_slug(date)
    away_tokens = [t.lower() for t in away.replace(".", "").split() if len(t) > 2]

    urls = re.findall(r'(https://www\.stubhub\.com/[^"\']+/event/\d+/)', html)
    # Prefer home game at portland with matching date in path
    for u in urls:
        path = u.lower()
        if home_slug in path and slug in path:
            return u.split("?")[0]
    for u in urls:
        path = u.lower()
        if slug in path and any(tok in path for tok in away_tokens[:2]):
            return u.split("?")[0]
    for u in urls:
        if slug in u:
            return u.split("?")[0]
    return None


def stubhub_search_us_playwright(
    home: str,
    away: str,
    date: pd.Timestamp,
    *,
    fixture_id: str | None = None,
    headed: bool = False,
) -> dict | None:
    """US StubHub via Playwright (search + optional cached event URL)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  StubHub US: install playwright — pip install playwright && playwright install chromium")
        return None

    cache = _load_event_cache()
    event_url = None
    if fixture_id and not cache.empty:
        hit = cache[cache["fixture_id"] == fixture_id]
        if not hit.empty:
            event_url = str(hit.iloc[0]["event_url"])

    search_q = f"{home} {away}"
    search_url = "https://www.stubhub.com/search?q=" + urllib.parse.quote(search_q)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        if not event_url:
            page.goto(search_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(4000)
            html = page.content()
            event_url = _match_event_url(html, away, date)
            if event_url and fixture_id:
                _append_event_cache(fixture_id, event_url)

        prices: list[float] = []
        final_event_url = event_url or search_url

        if event_url:
            resp = page.goto(event_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(6000)
            status = resp.status if resp else 0
            if status == 403:
                print(f"  StubHub US event 403 (bot block): {event_url}")
            else:
                prices = parse_prices(page.content(), "us")
                final_event_url = page.url

        if not prices:
            # Prices sometimes only on search cards — re-check search page
            page.goto(search_url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(3000)
            prices = parse_prices(page.content(), "us")

        browser.close()

    if not prices:
        return None

    return _result(
        get_in=min(prices),
        n_prices=len(prices),
        source="stubhub_us_playwright",
        search_url=search_url,
        event_url=final_event_url,
        home=home,
        away=away,
        fixture_date=str(date.date()),
    )


def _append_event_cache(fixture_id: str, event_url: str) -> None:
    EVENT_URL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    eid = re.search(r"/event/(\d+)/", event_url)
    row = {
        "fixture_id": fixture_id,
        "event_url": event_url,
        "stubhub_event_id": eid.group(1) if eid else "",
        "notes": f"auto-discovered {_today()}",
    }
    df = _load_event_cache()
    df = df[df["fixture_id"] != fixture_id]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(EVENT_URL_CACHE, index=False)


def stubhub_search(
    home: str,
    away: str,
    date: pd.Timestamp,
    *,
    region: Region = "uk",
    fixture_id: str | None = None,
    headed: bool = False,
) -> dict | None:
    if region == "uk":
        return stubhub_search_uk(home, away, date)
    return stubhub_search_us_playwright(
        home, away, date, fixture_id=fixture_id, headed=headed
    )
