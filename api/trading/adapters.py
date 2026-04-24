from __future__ import annotations

from typing import AsyncIterator, Protocol

from api.trading.types import (
    ExecutionIntent,
    MarketRef,
    OrderEvent,
    PortfolioState,
    RiskDecision,
    Signal,
)


class MarketDiscoveryAdapter(Protocol):
    async def list_markets(self, stat: str, player_id: str) -> list[MarketRef]: ...


class SignalMapper(Protocol):
    def map_signal(self, signal: Signal, markets: list[MarketRef]) -> ExecutionIntent | None: ...


class RiskEngine(Protocol):
    def evaluate(self, intent: ExecutionIntent, portfolio: PortfolioState) -> RiskDecision: ...
    def trip(self, reason: str) -> None: ...
    def is_tripped(self) -> bool: ...


class OrderRouter(Protocol):
    async def submit(self, intent: ExecutionIntent) -> OrderEvent: ...
    async def cancel(self, venue_order_id: str) -> OrderEvent: ...


class MarketDataStream(Protocol):
    async def stream(self, market_id: str) -> AsyncIterator[dict]: ...


class OrderStatusTracker(Protocol):
    async def stream_events(self, intent_id: str) -> AsyncIterator[OrderEvent]: ...


class PortfolioLedger(Protocol):
    def apply(self, event: OrderEvent) -> PortfolioState: ...
    def snapshot(self) -> PortfolioState: ...


class KillSwitch(Protocol):
    def trip(self, reason: str) -> None: ...
    def is_tripped(self) -> bool: ...
    def reset(self) -> None: ...
