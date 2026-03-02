from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests


KEYWORD = "multibagger stock"
GEO = "IN"
CATEGORY = 7
ALL_TIME_START = date(2004, 1, 1)
ASCII_CHARSET = " .:-=+*#%@"

ROOT_DIR = Path(__file__).resolve().parents[2]

from .GoogleTrendsScraper import GoogleTrendsScraper


@dataclass(frozen=True)
class Period:
    name: str
    start: date
    end: date


def build_periods(run_date: date) -> List[Period]:
    return [
        Period("short_term", run_date - timedelta(days=90), run_date),
        Period("medium_term", run_date - timedelta(days=365), run_date),
        Period("long_term", run_date - timedelta(days=365 * 5), run_date),
        Period("all_time", ALL_TIME_START, run_date),
    ]


def to_ascii_sparkline(series: pd.Series, width: int = 28) -> str:
    cleaned = series.dropna().astype(float)
    if cleaned.empty:
        return "(no data)"
    if len(cleaned) > width:
        idx = pd.Index(np.linspace(0, len(cleaned) - 1, width).round().astype(int))
        cleaned = cleaned.iloc[idx]
    lo = cleaned.min()
    hi = cleaned.max()
    if hi == lo:
        return "-" * len(cleaned)
    bins = len(ASCII_CHARSET) - 1
    chars = []
    for value in cleaned:
        normalized = (value - lo) / (hi - lo)
        chars.append(ASCII_CHARSET[int(round(normalized * bins))])
    return "".join(chars)


def summarize_series(series: pd.Series) -> Dict[str, float]:
    cleaned = series.dropna().astype(float)
    if cleaned.empty:
        return {
            "latest": 0.0,
            "delta_7d": 0.0,
            "delta_28d": 0.0,
            "min": 0.0,
            "max": 0.0,
        }

    latest = cleaned.iloc[-1]
    delta_7d = latest - cleaned.iloc[max(0, len(cleaned) - 8)] if len(cleaned) >= 2 else 0.0
    delta_28d = latest - cleaned.iloc[max(0, len(cleaned) - 29)] if len(cleaned) >= 2 else 0.0
    return {
        "latest": float(latest),
        "delta_7d": float(delta_7d),
        "delta_28d": float(delta_28d),
        "min": float(cleaned.min()),
        "max": float(cleaned.max()),
    }


def fetch_period_data(scraper: GoogleTrendsScraper, period: Period) -> pd.Series:
    frame = scraper.get_trends(
        KEYWORD,
        period.start.strftime("%Y-%m-%d"),
        period.end.strftime("%Y-%m-%d"),
        region=GEO,
        category=CATEGORY,
    )
    if KEYWORD not in frame.columns:
        raise RuntimeError(f"Keyword column missing for period: {period.name}")
    data = frame[KEYWORD].copy()
    data.index = pd.to_datetime(data.index)
    data = data.sort_index()
    return data


def plot_short_term(series: pd.Series, output_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=140)
    ax.plot(series.index, series.values, color="#0f766e", linewidth=2.2)
    ax.fill_between(series.index, series.values, color="#14b8a6", alpha=0.20)
    ax.set_title("Google Trends: multibagger stock (India) - Short Term", fontsize=12)
    ax.set_ylabel("Trend Index (0-100)")
    ax.grid(alpha=0.25)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def plot_context(data_by_period: Dict[str, pd.Series], output_path: Path) -> None:
    fig, axes = plt.subplots(3, 1, figsize=(10, 9), dpi=140, sharey=True)
    items = [
        ("medium_term", "Medium Term (12 Months)", "#0369a1"),
        ("long_term", "Long Term (5 Years)", "#7c3aed"),
        ("all_time", "All Time (2004-Present)", "#b45309"),
    ]
    for ax, (key, title, color) in zip(axes, items):
        series = data_by_period[key]
        ax.plot(series.index, series.values, color=color, linewidth=1.8)
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.25)
        ax.set_ylabel("0-100")
    axes[-1].set_xlabel("Date")
    fig.suptitle("Google Trends Context: multibagger stock (India)", fontsize=13)
    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)


def build_embeds(
    run_time: datetime,
    summaries: Dict[str, Dict[str, float]],
    sparklines: Dict[str, str],
) -> List[Dict[str, object]]:
    period_title = {
        "short_term": "Short (90D)",
        "medium_term": "Medium (12M)",
        "long_term": "Long (5Y)",
        "all_time": "All Time (2004+)",
    }

    stats_lines: List[str] = []
    for key in ["short_term", "medium_term", "long_term", "all_time"]:
        stats = summaries[key]
        stats_lines.append(
            f"**{period_title[key]}** | latest: {stats['latest']:.1f} | 7D: {stats['delta_7d']:+.1f} | "
            f"28D: {stats['delta_28d']:+.1f} | min/max: {stats['min']:.1f}/{stats['max']:.1f}"
        )
        stats_lines.append(f"`{sparklines[key]}`")

    short_embed = {
        "title": "India Google Trends Weekly Check",
        "description": "Keyword: `multibagger stock`\n\n" + "\n".join(stats_lines),
        "color": 0x0F766E,
        "timestamp": run_time.isoformat(),
        "image": {"url": "attachment://short_term.png"},
    }

    context_embed = {
        "title": "Long-Horizon Context",
        "color": 0x334155,
        "timestamp": run_time.isoformat(),
        "image": {"url": "attachment://context.png"},
    }
    return [short_embed, context_embed]


def post_discord_webhook(
    webhook_url: str,
    embeds: List[Dict[str, object]],
    files_to_attach: Iterable[Path],
) -> None:
    payload = {"embeds": embeds}
    form_files = {}
    handles = []
    try:
        for i, path in enumerate(files_to_attach):
            handle = open(path, "rb")
            handles.append(handle)
            form_files[f"files[{i}]"] = (path.name, handle, "image/png")

        response = requests.post(
            webhook_url,
            data={"payload_json": json.dumps(payload)},
            files=form_files,
            timeout=60,
        )
        response.raise_for_status()
    finally:
        for handle in handles:
            handle.close()


def post_discord_failure(webhook_url: str, run_time: datetime, error_text: str) -> None:
    payload = {
        "embeds": [
            {
                "title": "India Google Trends Weekly Check Failed",
                "description": f"```\n{error_text[:1800]}\n```",
                "color": 0xB91C1C,
                "timestamp": run_time.isoformat(),
            }
        ]
    }
    response = requests.post(webhook_url, json=payload, timeout=60)
    response.raise_for_status()


def run() -> None:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("DISCORD_WEBHOOK_URL environment variable is required")

    run_time = datetime.now(timezone.utc)
    run_date = run_time.date()
    periods = build_periods(run_date)

    output_dir = ROOT_DIR / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    short_chart = output_dir / "short_term.png"
    context_chart = output_dir / "context.png"

    scraper = GoogleTrendsScraper(
        sleep=int(os.getenv("SCRAPER_SLEEP", "3")),
        path_driver=os.getenv("CHROMEDRIVER"),
        headless=True,
    )

    try:
        data_by_period: Dict[str, pd.Series] = {}
        for period in periods:
            data_by_period[period.name] = fetch_period_data(scraper, period)

        summaries = {name: summarize_series(series) for name, series in data_by_period.items()}
        sparklines = {name: to_ascii_sparkline(series) for name, series in data_by_period.items()}

        plot_short_term(data_by_period["short_term"], short_chart)
        plot_context(data_by_period, context_chart)

        embeds = build_embeds(run_time, summaries, sparklines)
        post_discord_webhook(webhook_url, embeds, [short_chart, context_chart])
    except Exception:
        error_text = traceback.format_exc()
        post_discord_failure(webhook_url, run_time, error_text)
        raise
    finally:
        del scraper


def main() -> None:
    run()


if __name__ == "__main__":
    main()
