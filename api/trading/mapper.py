from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal

from api.trading.types import ExecutionIntent, MarketRef, Signal


class PickToIntentMapper:
    def __init__(self, order_ttl_hours: int = 1) -> None:
        self._order_ttl = timedelta(hours=order_ttl_hours)

    def map_signal(self, signal: Signal, markets: list[MarketRef]) -> ExecutionIntent | None:
        if not markets:
            return None
        market = markets[0]
        side: Literal["yes", "no"] = "yes" if signal.selected_side == "over" else "no"
        limit_price = max(0.01, min(0.99, round(signal.modeled_prob, 4)))
        return ExecutionIntent(
            signal_id=signal.pick_id,
            market_ref=market,
            side=side,
            limit_price=limit_price,
            size=1.0,
            edge=signal.edge,
            client_order_id=f"{signal.pick_id}-{uuid.uuid4().hex[:8]}",
            expires_at=signal.created_at + self._order_ttl,
        )
