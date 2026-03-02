# Google Trends Discord Bot Implementation Plan

## Objective
Build a simple Python wrapper around `dballinari/GoogleTrends-Scraper` that fetches Google Trends for `"multibagger stock"` in India across multiple horizons, then posts weekly Discord updates with charts and compact text summaries.

## Confirmed Constraints and Decisions
- Dependency management must use `uv`.
- Upstream scraper is not pip-installable from Git (no `pyproject.toml`/`setup.py`), so we copied its code directly into the repository, mitigating unhandled exceptions and infinite loops.
- No local testing in this environment; implementation-only changes.
- Add MIT license.
- Include one additional period called `all_time` using explicit range:
  - `start = 2004-01-01`
  - `end = run date`

## Period Definitions
- `short_term`: last 90 days
- `medium_term`: last 12 months (365 days)
- `long_term`: last 5 years (1825 days)
- `all_time`: 2004-01-01 to run date

## Output Format
- Discord webhook message with embeds.
- Attach chart images (preferred over pure text for readability).
- Include compact ASCII trend summary in embed fields/description.
- Include key metrics per period:
  - latest value
  - 7-day change
  - 28-day change
  - sample min/max

## Implementation Steps
1. Initialize repository structure and `uv` project files (`pyproject.toml`, package layout).
2. Add upstream scraper as git submodule under `vendor/GoogleTrends-Scraper`.
3. Implement wrapper module that:
   - imports scraper from submodule path
   - fetches data for all 4 periods (`IN`, keyword `multibagger stock`)
   - normalizes/summarizes results
4. Implement plotting module that creates:
   - short-term chart image
   - long-horizon context image (medium/long/all-time)
5. Implement Discord webhook sender:
   - embeds with stats and ASCII trend snippets
   - file attachments for generated charts
   - failure embed path for scrape/runtime errors
6. Add CLI entrypoint (`python -m trends_bot.main`).
7. Add GitHub Actions workflow:
   - weekly cron + manual trigger
   - checkout with submodules
   - install Python + `uv`
   - install Chromium + chromedriver
   - `uv sync`
   - run bot with webhook secret
8. Add `LICENSE` (MIT) and `README.md` with setup and operations notes.
9. Create `.gitignore` suitable for Python/uv/artifacts.
10. Commit and push via GitHub CLI (`gh`) and set remote repository.

## GitHub Workflow Design Notes
- Schedule: weekly, Monday 13:00 UTC.
- Trigger: `workflow_dispatch` for manual runs.
- Secret required: `DISCORD_WEBHOOK_URL`.
- Runtime env:
  - `CHROMEDRIVER` path detected via `which chromedriver`
  - headless scraping enabled.

## Risks and Mitigations
- Google Trends UI selector changes may break Selenium export:
  - mitigate with error reporting to Discord failure embed.
- Trends values are sampled and normalized by Google:
  - communicate as directional/relative indicators, not absolute volume.
- Selenium/chromedriver compatibility:
  - pin dependencies compatible with upstream scraper and stable Python version in CI.
