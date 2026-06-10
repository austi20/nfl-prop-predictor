"""Discover Kalshi NFL prop series tickers.

Roadmap risk R1 mitigation: NFL series may not exist or may differ structurally
from NBA's KXNBA* set. This script enumerates series via the Kalshi REST API,
filters to a configurable prefix (default KXNFL), and dumps results to
cache/kalshi_nfl_series.json for downstream P4 decision-brain work.

Run as a script: ``uv run python scripts/discover_kalshi_nfl_series.py``
Requires NFL_KALSHI_ACCESS_KEY and NFL_KALSHI_PRIVATE_KEY_PEM env vars (read from
.env via api.settings, never hardcoded).

Defined in docs/superpowers/specs/2026-06-10-modernization-roadmap-design.md §4 R1.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from api.trading.kalshi.client import KalshiClient

DEFAULT_BASE_URL = "https://api.elections.kalshi.com"
SERIES_PATH = "/trade-api/v2/series"
DEFAULT_PREFIX = "KXNFL"
DEFAULT_OUTPUT = Path("cache") / "kalshi_nfl_series.json"


@dataclass(frozen=True)
class SeriesRecord:
    ticker: str
    title: str


class _HttpClient(Protocol):
    def get(self, url: str, *, params: dict, headers: dict) -> httpx.Response: ...


def discover_nfl_series(
    *,
    http_client: _HttpClient,
    kalshi_client: KalshiClient,
    prefix: str = DEFAULT_PREFIX,
    base_url: str = DEFAULT_BASE_URL,
) -> list[SeriesRecord]:
    records: list[SeriesRecord] = []
    cursor = ""
    while True:
        timestamp_ms = int(time.time() * 1000)
        headers = kalshi_client.auth_headers("GET", SERIES_PATH, timestamp_ms)
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
        resp = http_client.get(base_url + SERIES_PATH, params=params, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
        for entry in payload.get("series", []):
            ticker = entry.get("ticker", "")
            if ticker.startswith(prefix):
                records.append(
                    SeriesRecord(ticker=ticker, title=entry.get("title", ""))
                )
        cursor = payload.get("cursor", "")
        if not cursor:
            break
    return records


def write_series_json(records: list[SeriesRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(records),
        "prefix": DEFAULT_PREFIX,
        "series": [{"ticker": r.ticker, "title": r.title} for r in records],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    import os
    import sys

    access_key = os.environ.get("NFL_KALSHI_ACCESS_KEY")
    private_key = os.environ.get("NFL_KALSHI_PRIVATE_KEY_PEM")
    if not access_key or not private_key:
        print(
            "error: NFL_KALSHI_ACCESS_KEY and NFL_KALSHI_PRIVATE_KEY_PEM must be set",
            file=sys.stderr,
        )
        sys.exit(2)

    kalshi_client = KalshiClient(
        access_key=access_key,
        private_key_pem=private_key,
        base_url=DEFAULT_BASE_URL,
    )
    with httpx.Client(timeout=30.0) as http_client:
        records = discover_nfl_series(
            http_client=http_client, kalshi_client=kalshi_client
        )
    write_series_json(records, DEFAULT_OUTPUT)
    print(f"wrote {len(records)} NFL series to {DEFAULT_OUTPUT}")


if __name__ == "__main__":
    main()
