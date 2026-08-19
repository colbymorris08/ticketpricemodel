# Data sources — ticket price model

What we need to build **Track A (WNBA 2026 expansion)** and **Track B (Premier League promoted clubs)**, plus shared modeling inputs.

---

## Target variables (what we predict)

| Target | Use | Notes |
|--------|-----|-------|
| **Secondary get-in / median price** | Primary demand signal | Snapshot at T−30, T−14, T−3 days before event |
| **Secondary listing count** | Scarcity proxy | Low listings + high price = hot game |
| **Attendance (if published)** | Validation | WNBA box scores; PL club reports / media |
| **Primary category availability** | Optional | “Sold out” flags, % seats left on club site |

We forecast **secondary price level** (and optionally volume) at three horizons — same framing as pro sports ticketing analytics roles.

---

## Track A — WNBA 2026 expansion (forward / retrospective)

**Case:** Inaugural season for new franchise(s) (e.g. Portland 2026, Toronto 2026 — confirm final expansion calendar).

### Required

| Source | Data | Access |
|--------|------|--------|
| **WNBA schedule API / site** | Date, opponent, home/away, arena, tip time | [stats.wnba.com](https://stats.wnba.com), [wnba.com/schedule](https://www.wnba.com/schedule) — no public API; scrape or manual CSV |
| **Secondary market listings** | Price, section, quantity, timestamp | **SeatGeek API** (`stats.lowest_price` — see [`docs/SEATGEEK_SETUP.md`](SEATGEEK_SETUP.md)), StubHub, Ticketmaster resale |
| **Team metadata** | Expansion flag, arena name, capacity, market size | Wikipedia / league press releases / [Basketball Reference](https://www.basketball-reference.com/wnba/) |
| **Opponent tier** | “Marquee” flag (e.g. Aces, Liberty, Storm) | Rule-based from prior-season record / star index |

### Nice-to-have

| Source | Data |
|--------|------|
| **Google Trends** | Local interest in team name + opponent |
| **Ticketmaster primary** | Face-value bands, on-sale date |
| **ESPN / social** | National TV slot (demand shock) |
| **Weather** | Outdoor-adjacent promos only (mostly indoor) |

### WNBA-specific features

- `days_to_event`, `day_of_week`, `is_weekend`
- `opponent_tier` (1–5), `is_rivalry`, `doubleheader` / same-arena night
- `expansion_season` = 1, `home_game_number` (game 1 vs game 10)
- `arena_capacity`, `metro_population`
- **Hypothesis feature:** `marquee_away` × `expansion_home` interaction

---

## Track B — Premier League promoted clubs (backtest)

**Case:** First PL season after promotion — e.g. **Leeds, Burnley, Sunderland (2025–26)** or historical promoted sets (Luton, Sheffield Utd, etc.).

### Required

| Source | Data | Access |
|--------|------|--------|
| **Fixtures & results** | Date, home, away, competition | [football-data.co.uk](https://www.football-data.co.uk/englandm.php) (free CSV), [API-Football](https://www.api-football.com/) |
| **Promoted team list** | Season → club | football-data promotion/relegation columns |
| **Secondary UK listings** | Min/median price by match | **StubHub UK**, **Viagogo**, **Live Football Tickets** — scrape with date + fixture ID |
| **Opponent tier (Big Six +)** | Arsenal, Chelsea, Liverpool, Man City, Man Utd, Spurs | Rule-based dummy + `table_position` |
| **Stadium capacity** | Home ground seats | Club sites / Wikipedia |

### Primary market (England — separate from secondary)

| Source | Data | Notes |
|--------|------|-------|
| **Club ticket pages** | Published price bands by category | Often PDF or JS — manual or scrape per club |
| **Premier League price cap context** | Category caps (policy changes by season) | Feature, not target |
| **Membership / ST priority** | On-sale windows | `days_since_general_sale` feature |

**Important:** Primary face value ≠ secondary resale. Model both as **features** (primary band, sold-out proxy) and predict **secondary**.

### Nice-to-have

| Source | Data |
|--------|------|
| **Travel distance** | Away fan influx proxy |
| **TV broadcast list** | Sky/TNT selection |
| **xG / table position** | Opponent strength continuous |
| **Derby / regional rivalry flags** | Manual lookup |

### PL-specific features

- `promoted_club_home` = 1
- `big_six_away` = 1
- **`big_six_away × promoted_home`** — core compare-contrast hypothesis vs WNBA `marquee_away × expansion_home`
- `matchweek`, `days_to_event`, `is_boxing_day`, `is_midweek`
- `capacity_pct` (attendance / capacity if available)

---

## Shared pipeline

```
raw listings (timestamped)  +  schedule/fixtures
        ↓
align to fixture_id, compute T−30 / T−14 / T−3 snapshots
        ↓
feature table (one row per fixture × horizon)
        ↓
LightGBM (nonlinear interactions) + GAM (smooth time / DOW effects)
        ↓
backtest: rolling origin by season
```

---

## Legal & ethics

- Respect **robots.txt** and platform ToS; prefer **official affiliate APIs** (SeatGeek, Ticketmaster) where available.
- Do not republish full listing dumps; store aggregates in repo, raw data gitignored.
- Scraping frequency: low cadence (1–2×/day per fixture window) to avoid hammering sites.

---

## Priority order (start here)

1. **Fixture/schedule tables** — WNBA 2026 + PL 2024–26 promoted seasons (free CSV).
2. **One secondary source with history** — SeatGeek API (if approved) or StubHub snapshot script.
3. **Opponent tier lookup** — static CSV (Big Six, WNBA marquee teams).
4. **Manual primary price bands** — 3–5 games per track for sanity check.
5. **Attendance validation** — post-hoc only.

---

## Open questions

- [ ] Confirm 2026 WNBA expansion cities and start dates
- [ ] Which PL season to anchor backtest (2025–26 live vs full historical panel)
- [ ] SeatGeek affiliate vs scrape-only for portfolio demo
- [ ] Whether to add **NWSL expansion** as Track C later (same shell)
