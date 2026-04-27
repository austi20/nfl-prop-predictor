from __future__ import annotations

import logging
import math
import random
import uuid
from datetime import datetime, timezone

from api.trading.types import ExecutionIntent, MarketRef, OrderEvent

_logger = logging.getLogger(__name__)
_warned = False


class FakePaperAdapter:
    """Fake paper adapter — fills are immediate at limit price, not realistic."""

    def __init__(self) -> None:
        global _warned
        if not _warned:
            _logger.warning("fake paper adapter active -- fills are not realistic.")
            _warned = True
        self._tripped = False
        self._trip_reason = ""

    # MarketDiscoveryAdapter
    async def list_markets(self, stat: str, player_id: str) -> list[MarketRef]:
        market_id = f"PAPER-{player_id[:8].upper()}-{stat[:4].upper()}"
        return [
            MarketRef(
                venue="paper",
                market_id=market_id,
                ticker=market_id,
                tick_size=0.01,
                min_size=1.0,
                yes_token=f"{market_id}-YES",
                no_token=f"{market_id}-NO",
            )
        ]

    # OrderRouter
    async def submit(self, intent: ExecutionIntent) -> OrderEvent:
        now = datetime.now(timezone.utc)
        if intent.size <= 0 or intent.limit_price < 0 or intent.limit_price > 1:
            return OrderEvent(
                intent_id=intent.client_order_id,
                event_type="rejected",
                venue_order_id="",
                price=intent.limit_price,
                size=intent.size,
                ts=now,
                side=intent.side,
                action="open",
            )
        return OrderEvent(
            intent_id=intent.client_order_id,
            event_type="filled",
            venue_order_id=uuid.uuid4().hex[:12],
            price=intent.limit_price,
            size=intent.size,
            ts=now,
            side=intent.side,
            action="open",
        )

    async def cancel(self, venue_order_id: str) -> OrderEvent:
        return OrderEvent(
            intent_id="",
            event_type="canceled",
            venue_order_id=venue_order_id,
            price=0.0,
            size=0.0,
            ts=datetime.now(timezone.utc),
        )

    # KillSwitch
    def trip(self, reason: str) -> None:
        self._tripped = True
        self._trip_reason = reason

    def is_tripped(self) -> bool:
        return self._tripped

    def reset(self) -> None:
        self._tripped = False
        self._trip_reason = ""


class RealisticPaperAdapter(FakePaperAdapter):
    """Paper adapter with spread, slippage, partial fills, and non-fills."""

    def __init__(
        self,
        *,
        mid_price: float = 0.50,
        spread: float = 0.02,
        nonfill_midpoint: float = 0.05,
        rng: random.Random | None = None,
    ) -> None:
        super().__init__()
        self._mid_price = mid_price
        self._spread = spread
        self._nonfill_midpoint = nonfill_midpoint
        self._rng = rng or random.Random()

    async def submit(self, intent: ExecutionIntent) -> OrderEvent:
        now = datetime.now(timezone.utc)
        if intent.size <= 0 or intent.limit_price < 0 or intent.limit_price > 1:
            return OrderEvent(
                intent_id=intent.client_order_id,
                event_type="rejected",
                venue_order_id="",
                price=intent.limit_price,
                size=intent.size,
                ts=now,
                side=intent.side,
                action="open",
            )

        executable_price = min(0.99, max(0.01, self._mid_price + self._spread / 2.0))
        distance = abs(float(intent.limit_price) - executable_price)
        nonfill_prob = 1.0 / (1.0 + math.exp(-(distance - self._nonfill_midpoint) / 0.015))
        if intent.limit_price < executable_price and self._rng.random() < nonfill_prob:
            return OrderEvent(
                intent_id=intent.client_order_id,
                event_type="acked",
                venue_order_id=uuid.uuid4().hex[:12],
                price=0.0,
                size=0.0,
                ts=now,
                side=intent.side,
                action="open",
            )

        event_type = "filled"
        fill_size = intent.size
        if intent.size > intent.market_ref.min_size and self._rng.random() < 0.30:
            event_type = "partial"
            fill_size = max(intent.market_ref.min_size, round(intent.size * self._rng.uniform(0.50, 0.80), 4))

        return OrderEvent(
            intent_id=intent.client_order_id,
            event_type=event_type,  # type: ignore[arg-type]
            venue_order_id=uuid.uuid4().hex[:12],
            price=executable_price,
            size=fill_size,
            ts=now,
            side=intent.side,
            action="open",
        )
