from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api.trading.types import ExecutionIntent, OrderEvent, PortfolioState, Position


class InMemoryPortfolioLedger:
    def __init__(self, audit_dir: Path, session_id: str | None = None) -> None:
        self._audit_dir = audit_dir
        self._session_id = session_id or uuid.uuid4().hex[:8]
        self._state = PortfolioState(cash_balance=0.0)
        self._intent_market: dict[str, str] = {}

    def register_intent(self, intent: ExecutionIntent) -> None:
        """Map client_order_id → market_id so fills can update the right position."""
        self._intent_market[intent.client_order_id] = intent.market_ref.market_id

    def apply(self, event: OrderEvent) -> PortfolioState:
        if event.event_type in ("filled", "partial"):
            market_id = self._intent_market.get(event.intent_id, event.intent_id)
            self._apply_fill(event, market_id)
        return self.snapshot()

    def snapshot(self) -> PortfolioState:
        return PortfolioState(
            cash_balance=self._state.cash_balance,
            positions=dict(self._state.positions),
            realized_pnl=self._state.realized_pnl,
            unrealized_pnl=self._state.unrealized_pnl,
        )

    def persist(self) -> Path:
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        path = self._audit_dir / f"portfolio-{self._session_id}.json"
        snap = self.snapshot()
        payload = {
            "session_id": self._session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "cash_balance": snap.cash_balance,
            "realized_pnl": snap.realized_pnl,
            "unrealized_pnl": snap.unrealized_pnl,
            "positions": {
                mid: {
                    "size": p.size,
                    "avg_price": p.avg_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for mid, p in snap.positions.items()
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    def _apply_fill(self, event: OrderEvent, market_id: str) -> None:
        existing = self._state.positions.get(market_id)
        if existing is None:
            new_pos = Position(
                market_id=market_id,
                size=event.size,
                avg_price=event.price,
                unrealized_pnl=0.0,
            )
        else:
            total_size = existing.size + event.size
            avg_price = (existing.size * existing.avg_price + event.size * event.price) / total_size
            new_pos = Position(
                market_id=market_id,
                size=total_size,
                avg_price=avg_price,
                unrealized_pnl=existing.unrealized_pnl,
            )
        self._state.positions[market_id] = new_pos
        self._state.cash_balance -= event.price * event.size
