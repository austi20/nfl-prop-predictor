from __future__ import annotations

import time

from api.trading.kalshi.signing import sign_request


class KalshiWebSocketListener:
    """Kalshi WebSocket listener scaffold.

    Auth-header construction is real (tested via signing.py).
    `connect()` raises NotImplementedError until in-season activation.
    """

    def __init__(self, access_key: str, private_key_pem: str, ws_url: str = "wss://demo-api.kalshi.co/trade-api/ws/v2") -> None:
        self._access_key = access_key
        self._private_key_pem = private_key_pem
        self._ws_url = ws_url

    def auth_headers(self) -> dict[str, str]:
        ts = int(time.time() * 1000)
        sig = sign_request(self._private_key_pem, ts, "GET", "/trade-api/ws/v2")
        return {
            "KALSHI-ACCESS-KEY": self._access_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": str(ts),
        }

    async def connect(self) -> None:
        raise NotImplementedError("Kalshi scaffold — activate in-season")
