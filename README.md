# Google Trends Bot

Simple `uv`-managed wrapper around [`dballinari/GoogleTrends-Scraper`](https://github.com/dballinari/GoogleTrends-Scraper), posting weekly Google Trends updates for `multibagger stock` in India to a Discord webhook.

## What It Does
- Pulls Google Trends index data for:
  - short term (90 days)
  - medium term (12 months)
  - long term (5 years)
  - all time (`2004-01-01` to run date)
- Generates chart images:
  - short-term move
  - long-horizon context
- Sends Discord embeds with key stats and ASCII trend snippets.

## Dependency Model
The upstream scraper code has been copied directly into our repository (`src/trends_bot/GoogleTrendsScraper.py`) instead of using a git submodule. This allows us to modify it (e.g. handle 429 Too Many Requests, infinite loop fixes) without dealing with upstream unmaintained code issues.

## Local Setup
```bash
uv sync
```

Required env vars:
- `DISCORD_WEBHOOK_URL`: destination webhook.
- `CHROMEDRIVER`: path to `chromedriver` binary.

Optional env vars:
- `SCRAPER_SLEEP` (default: `3`)

Run:
```bash
uv run trends-bot
```

## GitHub Actions
Workflow file: `.github/workflows/weekly-trends.yml`

- Schedule: weekly on Monday at `13:00 UTC`
- Manual runs: enabled via `workflow_dispatch`
- Secret required:
  - `DISCORD_WEBHOOK_URL`

## Notes
- Google Trends values are relative index values (`0-100`), not absolute search volumes.
- The scraper uses Selenium and can break if Google Trends page structure changes.
