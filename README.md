# Ticket Price Model

Compare-contrast demand project for **inaugural / “new home” venues**:

| Track | Case study | Why |
|-------|------------|-----|
| **A · WNBA** | 2026 expansion team(s) — inaugural season | Live forward: build model in retrospect as season plays out |
| **B · Premier League** | Recently promoted clubs (Championship → PL) | Historical backtest: first PL season at existing ground, new price tier |

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

## Status

**Shell only** — explorer UI + data plan. Model training starts once secondary price history is collected for Track A (WNBA 2026) and Track B (PL promoted seasons).
