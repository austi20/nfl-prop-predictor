from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from api.trading.audit import log_event
from api.trading.types import ExecutionIntent, MarketRef, Signal


class KalshiMapper:
    """Kalshi-specific signal mapper scaffold.

    Returns None and logs an audit event on every call until in-season activation.
    Real ticker-matching logic replaces the body without changing the interface.
    """

    def map_signal(
        self,
        signal: Signal,
        markets: list[MarketRef],
        audit_dir: Path = Path("docs/audit"),
    ) -> ExecutionIntent | None:
        log_event(
            "mapping_skipped",
            {"venue": "kalshi", "reason": "scaffold", "pick_id": signal.pick_id},
            audit_dir,
        )
        return None


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
