from __future__ import annotations

from api.trading.kalshi.client import KalshiClient
from api.trading.types import ExecutionIntent, MarketRef, OrderEvent, PortfolioState, Signal


class KalshiAdapter:
    """Adapter implementing the trading Protocols via KalshiClient.

    All methods raise NotImplementedError because KalshiClient raises — the class
    wiring, type signatures, and client_order_id handling are in place for in-season
    activation (replace NotImplementedError in client.py, no callers change).
    """

    def __init__(self, client: KalshiClient) -> None:
        self._client = client

    async def list_markets(self, stat: str, player_id: str) -> list[MarketRef]:
        raw = self._client.list_markets(stat, player_id)
        return [
            MarketRef(
                venue="kalshi",
                market_id=m["market_id"],
                ticker=m["ticker"],
                tick_size=m.get("tick_size", 0.01),
                min_size=m.get("min_size", 1.0),
                yes_token=m.get("yes_token", ""),
                no_token=m.get("no_token", ""),
            )
            for m in raw
        ]

    def map_signal(self, signal: Signal, markets: list[MarketRef]) -> ExecutionIntent | None:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    async def submit(self, intent: ExecutionIntent) -> OrderEvent:
        self._client.place_order(intent)
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    async def cancel(self, venue_order_id: str) -> OrderEvent:
        self._client.cancel_order(venue_order_id)
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def apply(self, event: OrderEvent) -> PortfolioState:
        raise NotImplementedError("Kalshi scaffold — activate in-season")

    def snapshot(self) -> PortfolioState:
        raise NotImplementedError("Kalshi scaffold — activate in-season")
