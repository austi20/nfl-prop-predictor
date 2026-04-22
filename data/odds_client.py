"""Minimal The Odds API historical wrapper for NFL player props.

Used by Step 3 calibration and Step 4 replay once an API key is available.
Historical player-prop odds require a paid plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


_BASE_URL = "https://api.the-odds-api.com/v4"


@dataclass
class OddsApiClient:
    api_key: str | None = None
    base_url: str = _BASE_URL
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.getenv("THE_ODDS_API_KEY")
        if not self.api_key:
            raise ValueError("THE_ODDS_API_KEY is required for The Odds API access")
        self.session = self.session or requests.Session()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        assert self.session is not None
        query = {"apiKey": self.api_key, **params}
        response = self.session.get(f"{self.base_url}{path}", params=query, timeout=30)
        response.raise_for_status()
        return response.json()

    def historical_events(
        self,
        sport: str,
        date: str,
        *,
        event_ids: list[str] | None = None,
        commence_time_from: str | None = None,
        date_format: str = "iso",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "date": date,
            "dateFormat": date_format,
        }
        if event_ids:
            params["eventIds"] = ",".join(event_ids)
        if commence_time_from:
            params["commenceTimeFrom"] = commence_time_from
        return self._get(f"/historical/sports/{sport}/events", params)

    def historical_event_odds(
        self,
        sport: str,
        event_id: str,
        date: str,
        *,
        markets: list[str],
        regions: str = "us",
        odds_format: str = "american",
        date_format: str = "iso",
        bookmakers: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "regions": regions,
            "markets": ",".join(markets),
            "date": date,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params["bookmakers"] = ",".join(bookmakers)
        return self._get(f"/historical/sports/{sport}/events/{event_id}/odds", params)
