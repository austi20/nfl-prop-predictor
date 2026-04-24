from __future__ import annotations

from api.trading.kalshi.signing import sign_request


class KalshiClient:
    """Kalshi REST client scaffold.

    All network-touching methods raise NotImplementedError until in-season activation.
    The signing helper is real and tested (see tests/trading/test_kalshi_signing.py).
    """

    def __init__(self, access_key: str, private_key_pem: str, base_url: str = "https://demo-api.kalshi.co") -> None:
        self._access_key = access_key
        self._private_key_pem = private_key_pem
        self._base_url = base_url

    # Real signing — usable without a Kalshi account.
    def auth_headers(self, method: str, path: str, timestamp_ms: int) -> dict[str, str]:
        sig = sign_request(self._private_key_pem, timestamp_ms, method, path)
        return {
            "KALSHI-ACCESS-KEY": self._access_key,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": str(timestamp_ms),
        }

    def list_markets(self, stat: str, player_id: str) -> list[dict]:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def place_order(self, intent: object) -> dict:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def cancel_order(self, venue_order_id: str) -> dict:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def get_order(self, venue_order_id: str) -> dict:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def get_balance(self) -> dict:
        raise NotImplementedError("Kalshi scaffold — activate in-season")
