# Ticket Price Model

Compare-contrast demand project for **inaugural / “new home” venues**:

| Track | Case study | Why |
|-------|------------|-----|
| **A · WNBA** | **Portland Fire** (2026 expansion, newest franchise) | Train on completed 2026 home games; predict rest of season |
| **B · Premier League** | **Coventry City** (2026–27 promoted) | Train on promoted-club seed panel; live-track home games from Aug 29 |

**Hypothesis:** When a marquee opponent visits a new or newly-promoted home market, **secondary-market prices** spike more than **primary face value** — scarcity + fan travel + “see the big name once” demand.

**Job story (Wave / ticketing analytics):** forecast demand at **30 / 14 / 3 days** before tip-off or kickoff; recommend **hold / promo / package** using LightGBM + GAM (same hybrid as commercial sports analytics roles).

## Live explorer

https://colbymorris08.github.io/ticketpricemodel/

Open `ticket_price_explorer.html` locally for the same UI (self-contained).

## Primary vs secondary (England)

They are **not the same market**:

- **Primary** — sold by the club (season tickets, memberships, general sale). Price is set by the club’s ticketing strategy.
- **Secondary** — resale platforms (StubHub, Viagogo, SeatGeek, etc.). Price reflects **scarcity and demand** when primary inventory is gone or limited.

For modeling we usually treat **secondary median/get-in price** as the demand signal and **primary published bands** as a control / feature (not the same target variable).

## Data sources

See [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) for the full checklist (required vs nice-to-have, APIs, scraping notes, legal).

## Repo layout (planned)

```
data/raw/           # gitignored — scraped/API pulls
data/processed/     # gitignored — game-level feature table
scripts/            # ingest, features, train, backtest
ticket_price_explorer.html
docs/DATA_SOURCES.md
```

## Run the sprint

```bash
pip install -r requirements.txt
cp .env.example .env   # add SEATGEEK_CLIENT_ID for WNBA
python scripts/run_sprint.py --as-of 2026-08-18
```

**SeatGeek:** free `client_id` at [seatgeek.com/build](https://seatgeek.com/build) → see [`docs/SEATGEEK_SETUP.md`](docs/SEATGEEK_SETUP.md).

**Daily auto-snapshot:** GitHub Action runs at 12:00 UTC once you add `SEATGEEK_CLIENT_ID` as a repo secret.

Outputs: `results/recommendations.csv`, daily snapshots in `data/raw/secondary_snapshots/`.

See [`docs/RESEARCH_QUESTIONS.md`](docs/RESEARCH_QUESTIONS.md) for HOLD / PROMOTE framing.

## Status

**Sprint pipeline live** — fixture CSVs, snapshot script, LightGBM train/predict, recommendations table. Coventry StubHub pulls run daily; WNBA uses observed T-14 proxies for completed games.
