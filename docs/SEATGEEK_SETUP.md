# SeatGeek API setup

SeatGeek is the **preferred US secondary-demand signal** for Portland Fire (WNBA). The public API does **not** return individual ticket listings — it returns **event-level stats** (`lowest_price`, `average_price`, `listing_count`), which is enough for our model.

---

## 1. Get a free client ID (~2 minutes)

1. Go to **[seatgeek.com/build](https://seatgeek.com/build)** (SeatGeek Platform / developer signup).
2. Create an account and register an application.
3. Copy your **`client_id`** (free tier ≈ **500 requests/day** — plenty for daily snapshots of 4–7 games).

Docs: [platform.seatgeek.com](https://platform.seatgeek.com/) · legacy reference [seatgeek.github.io](https://seatgeek.github.io/)

---

## 2. Store the key locally

```bash
# In ~/ticketpricemodel
cp .env.example .env
# Edit .env and set:
# SEATGEEK_CLIENT_ID=your_client_id_here
```

Test:

```bash
export SEATGEEK_CLIENT_ID=your_client_id_here
python3 scripts/seatgeek_client.py "Portland Fire"
```

You should see upcoming Moda Center events with `$get-in` prices.

---

## 3. GitHub Actions (daily auto-snapshot)

Add a **repository secret** so the daily workflow can call SeatGeek:

1. Open [github.com/colbymorris08/ticketpricemodel/settings/secrets/actions](https://github.com/colbymorris08/ticketpricemodel/settings/secrets/actions)
2. **New repository secret**
   - Name: `SEATGEEK_CLIENT_ID`
   - Value: your client_id

The workflow `.github/workflows/daily_snapshot.yml` runs at **12:00 UTC daily** and on manual dispatch. It:

- Snapshots Coventry (StubHub UK) + Portland (SeatGeek)
- Rebuilds features and `results/recommendations.csv`
- Commits updated results back to `main`

---

## 4. What the API returns (example)

```bash
curl "https://api.seatgeek.com/2/events?performers.slug=portland-fire&client_id=YOUR_ID&per_page=3"
```

Each event includes:

| Field | Use |
|-------|-----|
| `stats.lowest_price` | **Secondary get-in** (target) |
| `stats.average_price` | Demand level |
| `stats.listing_count` | Scarcity |
| `url` | Link out to SeatGeek (required by ToS — don’t republish listings) |

---

## 5. Limits & ToS

- **No individual listings** via public API — redirect users to `event.url` for purchase.
- Do **not** build a competing marketplace; research/forecast use is fine.
- Rate limit: stay under 500 req/day on free tier (we use ~10/day).

---

## 6. UK / Coventry

SeatGeek is US/Canada-focused. **Coventry stays on StubHub UK** in `snapshot_secondary.py`. No SeatGeek key needed for PL track.
