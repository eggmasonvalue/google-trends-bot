# Google Trends Bot
Google Trends → Discord webhook. Fetches multi-horizon trend data weekly and posts charts + stats to a Discord channel.

---

## What It Does

Fetches Google Trends interest-over-time for a keyword across four time horizons:

| Period | Env var window | Google granularity |
|---|---|---|
| Short term | Last 90 days | **Daily** |
| Medium term | Last 12 months | **Weekly** |
| Long term | Last 5 years | **Weekly** |
| All time | 2004-01-01 → today | **Weekly** (see below) |

Generates two chart PNGs and sends them to Discord as rich embeds with stats and an ASCII sparkline per period.

---

## All-Time Weekly — How It Works

Google only returns **monthly** granularity for windows longer than ~5 years. To get weekly resolution all the way back to 2004:

1. **Anchor fetch** — one request with `timeframe="all"` returns a monthly series globally normalised so 100 = the all-time peak. This is the common reference frame.
2. **Weekly chunks** — the full date range is split into ~4.5-year windows (each short enough to receive weekly data from Google). Each chunk arrives normalised to 100 within its own window.
3. **Independent rescaling** — each chunk is resampled to month-start and compared against the anchor over the same months. `median(anchor_monthly / chunk_monthly)` gives a scalar that maps the chunk back into the global reference frame.  Because every chunk is tied to the same anchor (not to its neighbour), there is **no error accumulation** across joins.
4. **Seam smoothing** — adjacent chunks overlap by 4 weeks; values in the overlap are averaged.
5. **Final normalisation** — the combined series is rescaled to [0, 100].

Result: a weekly series from 2004 to today where 100 = the keyword's all-time peak globally.

---

## Configuration

### Required
| Env var | Description |
|---|---|
| `DISCORD_WEBHOOK_URL` | Full Discord webhook URL |

### Optional (fall back to defaults)
| Env var | Default | Description |
|---|---|---|
| `TRENDS_KEYWORD` | `multibagger stock` | Search term passed to Google Trends |
| `TRENDS_GEO` | `IN` | ISO 3166-1 alpha-2 country code (see below) |
| `TRENDS_CATEGORY` | `7` | Google Trends category ID (see below) |

### `TRENDS_GEO` — country codes
Standard ISO 3166-1 alpha-2. Common values:

| Code | Country |
|---|---|
| *(empty string)* | Worldwide |
| `IN` | India |
| `US` | United States |
| `GB` | United Kingdom |
| `SG` | Singapore |
| `AU` | Australia |

Any valid two-letter code works. See the full list at [Wikipedia](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2).

### `TRENDS_CATEGORY` — category IDs
Filters trends to a specific topic category. Common values:

| ID | Category |
|---|---|
| `0` | All categories |
| `7` | Finance |
| `12` | Business & Industrial |
| `16` | News |
| `632` | Investing |
| `1163` | Stocks & Bonds |

To find others: open Google Trends in a browser, select a category, and read the `cat=` parameter from the URL.

---

## Discord Output

The bot sends **one message with two embeds** to the webhook URL:

**Embed 1 — Weekly Check**
- Title: `{GEO} Google Trends Weekly Check`
- Body: stats table for all four periods — latest value, 7-day delta, 28-day delta, min/max, and a 28-character ASCII sparkline showing the shape of the trend
- Image: short-term (90-day daily) chart attached inline

**Embed 2 — Long-Horizon Context**
- Image: 3-subplot chart showing medium term, long term, and all-time weekly series stacked vertically

On failure, the bot posts a **single error embed** (red) with the Python traceback (up to 1800 characters), so you know exactly what went wrong without checking GHA logs.

---

## Local Setup

```bash
uv sync
```

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... uv run trends-bot
```

To override keyword/geo/category:
```bash
TRENDS_KEYWORD="bitcoin" TRENDS_GEO="US" TRENDS_CATEGORY="0" \
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/... uv run trends-bot
```

---

## GitHub Actions

Workflow: `.github/workflows/weekly-trends.yml`

- Schedule: every Monday at 13:00 UTC
- Manual: `workflow_dispatch`
- **Secret required**: `DISCORD_WEBHOOK_URL`
- **Optional repository variables** (Settings → Variables → Actions): `TRENDS_KEYWORD`, `TRENDS_GEO`, `TRENDS_CATEGORY`

---

## Notes
- Google Trends values are relative indices (0–100), not absolute search volumes.
- Data fetched via [pytrends](https://github.com/GeneralMills/pytrends) — HTTP only, no browser.
- Retries: exponential backoff + jitter via [tenacity](https://github.com/jd/tenacity), 5 attempts, up to 2-minute wait per attempt.
- Inter-request sleep: 5–15 s random jitter between period fetches to stay under Google's rate limiter.
