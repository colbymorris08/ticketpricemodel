# Research questions — ticket price model

## Teams locked for live tracks

| Track | Team | Rationale |
|-------|------|-----------|
| **WNBA** | **Portland Fire** | Newest expansion franchise (2026 debut, #1 expansion pick). 22 home games at Moda Center. |
| **PL** | **Coventry City** | 2026–27 promoted side; 25-year PL absence. Season starts Aug 22, 2026. |

Toronto Tempo is the other 2026 expansion team (Canada’s first WNBA market) — good Track C later.

---

## Questions we answer (in order)

### Q1 — Demand forecast
*What will secondary get-in be at T−30, T−14, and T−3?*

Foundation metric for any ticketing analytics role.

### Q2 — Money on the table (HOLD)
*Which home games are underpriced on primary?*

`gap = pred_secondary − primary_band` when sell-through is strong → **HOLD**, no promos, consider higher bands next cycle.

### Q3 — Promo targeting (PROMOTE)
*Which home games need demand stimulation?*

Low predicted secondary + high listing volume → **PROMOTE** (bundles, kids day, targeted email).

### Q4 — Marquee premium
*How much does Big Six / tier-5 opponent add at a new home market?*

PL: `big_six_away × coventry_home`  
WNBA: `opponent_tier` at expansion home

### Q5 — Decision rule (product output)

| Action | When |
|--------|------|
| **HOLD** | pred_secondary >> primary; scarce listings |
| **MONITOR** | in between |
| **PROMOTE** | soft demand; pred ≈ or below primary |

---

## Sprint outputs

- `results/recommendations.csv` — fixture × horizon × pred × gap × action
- `results/backtest_summary.txt` — WNBA leave-last-3-out MAPE
- `data/raw/secondary_snapshots/` — daily Coventry StubHub pulls

Run: `python scripts/run_sprint.py --as-of 2026-08-18`
