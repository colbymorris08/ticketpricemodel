# StubHub scraping

## Coventry (PL) — works today

UK search returns prices in HTML (no browser needed):

```bash
python3 scripts/snapshot_secondary.py --as-of 2026-08-24
```

Uses `stubhub.co.uk/find/s/?q=Coventry+City+Hull+City+tickets`.

---

## Portland (WNBA) — Playwright required

US StubHub hides prices behind JavaScript and **blocks bots on event pages** (HTTP 403) from many IPs — especially GitHub Actions.

### Setup (one time)

```bash
cd ~/ticketpricemodel
pip3 install playwright
playwright install chromium
```

### Run scrape

```bash
# Headless (may 403 on event page → falls back to tier prior)
python3 scripts/snapshot_secondary.py --as-of 2026-08-24

# If headless fails, try visible browser (often works on home Wi‑Fi)
python3 scripts/snapshot_secondary.py --as-of 2026-08-24 --headed
```

### How it works

1. Search `stubhub.com/search?q=Portland+Fire+{opponent}`
2. Match event URL by date slug (`8-30-2026`) in path
3. Cache URL in `data/reference/stubhub_event_urls.csv`
4. Load event page → parse `$` prices from HTML
5. If blocked → tier prior estimate

### Manual event URL cache

If auto-discovery finds the wrong event, edit:

`data/reference/stubhub_event_urls.csv`

Find URLs from StubHub in your browser → paste `fixture_id` + `event_url`.

---

## GitHub Actions note

Daily workflow runs Coventry (UK HTTP) fine. **Portland US may stay on tier priors in CI** until SeatGeek approves or you run `--headed` locally and commit snapshots.

---

## Legal

Low cadence (1×/day), research use, respect StubHub ToS. Do not republish raw listing dumps.
