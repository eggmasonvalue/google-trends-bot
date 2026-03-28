from __future__ import annotations

import logging
import random
import time
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from pytrends.request import TrendReq
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

if TYPE_CHECKING:
    from trends_bot.main import Period

logger = logging.getLogger(__name__)

# Seconds to sleep between consecutive period fetches (uniform jitter)
_MIN_INTER_REQUEST_SLEEP = 5
_MAX_INTER_REQUEST_SLEEP = 15

# Pytrends timeframes that yield the desired granularity automatically.
# Google chooses the granularity based on the requested window:
#   today 3-m  → daily
#   today 12-m → weekly
#   today 5-y  → weekly
# Note: "all_time" is NOT in this table — it is fetched via chunked weekly
# requests in fetch_all_time_weekly() to avoid Google's monthly-only granularity
# for windows > ~5 years.
_PERIOD_TIMEFRAMES: dict[str, str] = {
    "short_term": "today 3-m",
    "medium_term": "today 12-m",
    "long_term": "today 5-y",
}


def timeframe_for_period(period_name: str) -> str:
    """Return the pytrends timeframe string for a named period.

    Raises ValueError for 'all_time' — use fetch_all_time_weekly() instead.
    """
    try:
        return _PERIOD_TIMEFRAMES[period_name]
    except KeyError:
        raise ValueError(
            f"Unknown period name '{period_name}'. "
            f"Valid names: {list(_PERIOD_TIMEFRAMES)} "
            f"(use fetch_all_time_weekly() for 'all_time')"
        )


def _build_trend_req() -> TrendReq:
    """Create a fresh TrendReq instance with sensible defaults."""
    return TrendReq(
        hl="en-US",
        tz=0,
        timeout=(10, 30),
        retries=2,
        backoff_factor=2,
    )


@retry(
    wait=wait_exponential_jitter(initial=15, max=120, jitter=10),
    stop=stop_after_attempt(5),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def fetch_interest_over_time(
    keyword: str,
    timeframe: str,
    geo: str,
    category: int,
) -> pd.Series:
    """
    Fetch Google Trends interest-over-time data for a single keyword.

    Returns a pandas Series indexed by date, with float values 0-100.

    Retries up to 5 times with exponential backoff + jitter on any exception
    (covers 429 rate-limits, transient network errors, empty responses).
    """
    pytrend = _build_trend_req()
    pytrend.build_payload(
        kw_list=[keyword],
        cat=category,
        timeframe=timeframe,
        geo=geo,
    )
    df = pytrend.interest_over_time()

    if df is None or df.empty:
        raise RuntimeError(
            f"Empty response from Google Trends for keyword='{keyword}', "
            f"timeframe='{timeframe}', geo='{geo}', category={category}. "
            "This may be a rate-limit or a keyword with no data."
        )

    # Drop the 'isPartial' flag column added by pytrends
    if "isPartial" in df.columns:
        df = df.drop(columns=["isPartial"])

    series = df[keyword].astype(float)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    return series


# ---------------------------------------------------------------------------
# All-time weekly: anchor-based chunked fetch
# ---------------------------------------------------------------------------

# Maximum window (days) that Google reliably returns *weekly* data for.
# ~4.5 years keeps us well under the ~5-year monthly threshold.
_WEEKLY_CHUNK_DAYS = int(4.5 * 365)
# Overlap between adjacent chunks (days). A small overlap lets us average the
# seam region rather than hard-cut; 4 weeks is enough.
_WEEKLY_CHUNK_OVERLAP_DAYS = 4 * 7


def _scale_chunk_to_anchor(
    chunk: pd.Series,
    anchor_monthly: pd.Series,
) -> pd.Series:
    """
    Rescale a weekly chunk to the global monthly anchor's scale.

    All chunks pass through this function independently, so there is no
    error accumulation across joins — every chunk is tied to the same
    global reference frame.

    Steps:
      1. Resample the weekly chunk to month-start (MS) using mean.
      2. Align with the anchor on shared months.
      3. Compute median(anchor / chunk_monthly) over valid (non-zero, finite) months.
      4. Multiply the original weekly series by that scalar.
    """
    chunk = chunk.astype(float)
    chunk_monthly = chunk.resample("MS").mean().astype(float)

    shared = anchor_monthly.index.intersection(chunk_monthly.index)
    if len(shared) == 0:
        logger.warning("No shared months between chunk and anchor; skipping rescale.")
        return chunk

    a = anchor_monthly.loc[shared]
    c = chunk_monthly.loc[shared]
    valid = (a > 0) & (c > 0) & np.isfinite(a) & np.isfinite(c)

    if valid.sum() < 2:
        logger.warning(
            "Too few valid anchor overlap points (%d); skipping rescale.", valid.sum()
        )
        return chunk

    factor = float(np.median(a[valid].values / c[valid].values))
    logger.debug("Anchor rescale factor=%.4f (%d monthly points)", factor, valid.sum())
    return chunk * factor


def fetch_all_time_weekly(
    keyword: str,
    geo: str,
    category: int,
    start: date,
    end: date,
) -> pd.Series:
    """
    Fetch weekly trend data from *start* to *end* with anchor-based rescaling.

    Algorithm:
      1. Fetch "all" timeframe (monthly, globally normalised so 100 = all-time
         peak) as the anchor. This is the common reference frame.
      2. Split start→end into ~4.5-year chunks (each returns weekly granularity).
      3. Scale each chunk independently to the anchor via median ratio — no
         error accumulation across joins.
      4. Average values in short overlap regions for smooth seams.
      5. Normalise the final combined series to [0, 100].
    """
    # Step 1: fetch global monthly anchor
    logger.info("Fetching all-time monthly anchor...")
    anchor_raw = fetch_interest_over_time(keyword, "all", geo, category)
    anchor_monthly = anchor_raw.resample("MS").mean().astype(float)
    sleep_s = random.uniform(_MIN_INTER_REQUEST_SLEEP, _MAX_INTER_REQUEST_SLEEP)
    logger.debug("Sleeping %.1fs after anchor fetch", sleep_s)
    time.sleep(sleep_s)

    # Step 2: build chunk date ranges
    chunk_ranges: list[tuple[date, date]] = []
    cs = start
    while cs < end:
        ce = min(cs + timedelta(days=_WEEKLY_CHUNK_DAYS), end)
        chunk_ranges.append((cs, ce))
        if ce >= end:
            break
        cs = ce - timedelta(days=_WEEKLY_CHUNK_OVERLAP_DAYS)

    logger.info(
        "Fetching all-time weekly in %d chunk(s) from %s to %s",
        len(chunk_ranges), start, end,
    )

    # Steps 3+4: fetch each chunk, scale to anchor, combine
    combined: pd.Series | None = None

    for i, (cs, ce) in enumerate(chunk_ranges):
        timeframe = f"{cs.strftime('%Y-%m-%d')} {ce.strftime('%Y-%m-%d')}"
        logger.info("  chunk %d/%d: %s", i + 1, len(chunk_ranges), timeframe)

        raw = fetch_interest_over_time(keyword, timeframe, geo, category)
        scaled = _scale_chunk_to_anchor(raw, anchor_monthly)

        if combined is None:
            combined = scaled.copy()
        else:
            # Average the overlap region; append new dates
            overlap_idx = combined.index.intersection(scaled.index)
            if not overlap_idx.empty:
                combined.loc[overlap_idx] = (
                    combined.loc[overlap_idx] + scaled.loc[overlap_idx]
                ) / 2.0
            new_idx = scaled.index.difference(combined.index)
            if not new_idx.empty:
                combined = pd.concat([combined, scaled.loc[new_idx]]).sort_index()

        if i < len(chunk_ranges) - 1:
            sleep_s = random.uniform(_MIN_INTER_REQUEST_SLEEP, _MAX_INTER_REQUEST_SLEEP)
            logger.debug("Sleeping %.1fs before next chunk", sleep_s)
            time.sleep(sleep_s)

    if combined is None or combined.empty:
        raise RuntimeError("fetch_all_time_weekly produced no data")

    # Step 5: normalise to [0, 100]
    mx = combined.max()
    if mx > 0:
        combined = 100.0 * combined / mx
    return combined


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def fetch_all_periods(
    periods: list[Period],
    keyword: str,
    geo: str,
    category: int,
) -> dict[str, pd.Series]:
    """
    Fetch trend data for all periods sequentially, with random inter-request
    sleep to reduce the chance of triggering Google's rate limiter.

    'all_time' is handled specially via fetch_all_time_weekly() to obtain
    weekly (not monthly) granularity for the full date range.

    Returns a dict mapping period.name → pd.Series.
    """
    results: dict[str, pd.Series] = {}
    for i, period in enumerate(periods):
        if period.name == "all_time":
            logger.info(
                "Fetching all-time weekly (chunked): keyword=%s geo=%s cat=%d start=%s end=%s",
                keyword, geo, category, period.start, period.end,
            )
            results[period.name] = fetch_all_time_weekly(
                keyword, geo, category, start=period.start, end=period.end
            )
        else:
            timeframe = timeframe_for_period(period.name)
            logger.info(
                "Fetching period '%s' (timeframe=%s, keyword=%s, geo=%s, cat=%d)",
                period.name, timeframe, keyword, geo, category,
            )
            results[period.name] = fetch_interest_over_time(keyword, timeframe, geo, category)

        # Sleep between top-level periods (skip after the last one)
        # Note: fetch_all_time_weekly already sleeps between its own chunks.
        if i < len(periods) - 1:
            sleep_s = random.uniform(_MIN_INTER_REQUEST_SLEEP, _MAX_INTER_REQUEST_SLEEP)
            logger.debug("Sleeping %.1fs before next period", sleep_s)
            time.sleep(sleep_s)

    return results
