from __future__ import annotations

import time
from typing import Any

import httpx

from api.trading.kalshi.signing import sign_request

_API_ROOT = "/trade-api/v2"


def _split_base_url(base_url: str) -> tuple[str, str]:
    url = httpx.URL(base_url.rstrip("/"))
    root = url.path.rstrip("/")
    api_path = root if root.endswith(_API_ROOT) else f"{root}{_API_ROOT}" if root else _API_ROOT
    origin = str(url.copy_with(path="/")).rstrip("/")
    return origin, api_path


class KalshiClient:
    """Kalshi REST client.

    Market-data GETs (markets, events) are live and need no account — the
    signature header is sent when a key is configured, ignored otherwise.
    Order methods still raise NotImplementedError until trading is activated.
    """

    def __init__(
        self,
        access_key: str = "",
        private_key_pem: str = "",
        base_url: str = "https://external-api.kalshi.com/trade-api/v2",
        timeout: float = 10.0,
    ) -> None:
        self._access_key = access_key
        self._private_key = private_key_pem  # PEM text or a path to a .pem
        self._origin, self._api_path = _split_base_url(base_url)
        self._http = httpx.Client(base_url=self._origin, timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def auth_headers(self, method: str, path: str, timestamp_ms: int | None = None) -> dict[str, str]:
        """Signed headers for an arbitrary path (used by the series-discovery script)."""
        ts = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self._access_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": sign_request(self._private_key, ts, method, path),
        }

    def _headers(self, method: str, path: str) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self._access_key and self._private_key:
            ts = str(int(time.time() * 1000))
            try:
                headers.update(
                    {
                        "KALSHI-ACCESS-KEY": self._access_key,
                        "KALSHI-ACCESS-TIMESTAMP": ts,
                        "KALSHI-ACCESS-SIGNATURE": sign_request(self._private_key, ts, method, path),
                    }
                )
            except Exception:  # noqa: BLE001 - unsigned GET still works for market data
                pass
        return headers

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        path = f"{self._api_path}{endpoint}"
        resp = self._http.get(path, params=params, headers=self._headers("GET", path))
        resp.raise_for_status()
        return resp.json()

    # ---- market data (live) -------------------------------------------------
    def get_events(self, *, series_ticker: str = "", status: str = "open", limit: int = 200,
                   cursor: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "status": status, "with_nested_markets": "true"}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/events", params)

    def get_markets(self, *, series_ticker: str = "", event_ticker: str = "", status: str = "open",
                    limit: int = 200, cursor: str = "") -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor
        return self._get("/markets", params)

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}")

    # ---- trading (scaffold) ----------------------------------------------
    def list_markets(self, stat: str, player_id: str) -> list[dict]:
        raise NotImplementedError("Kalshi trading scaffold — activate in-season")

    def place_order(self, intent: object) -> dict:
        raise NotImplementedError("Kalshi trading scaffold — activate in-season")

    def cancel_order(self, venue_order_id: str) -> dict:
        raise NotImplementedError("Kalshi trading scaffold — activate in-season")

    def get_order(self, venue_order_id: str) -> dict:
        raise NotImplementedError("Kalshi trading scaffold — activate in-season")

    def get_balance(self) -> dict:
        raise NotImplementedError("Kalshi trading scaffold — activate in-season")
