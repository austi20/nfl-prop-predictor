from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from api.trading.types import ExecutionIntent, OrderEvent, PortfolioState, Position

PositionKey = tuple[str, Literal["yes", "no"]]


class InMemoryPortfolioLedger:
    def __init__(self, audit_dir: Path, session_id: str | None = None) -> None:
        self._audit_dir = audit_dir
        self._session_id = session_id or uuid.uuid4().hex[:8]
        self._state = PortfolioState(cash_balance=0.0)
        self._intent_market: dict[str, PositionKey] = {}

    def register_intent(self, intent: ExecutionIntent) -> None:
        """Map client_order_id to the side-aware position key."""
        self._intent_market[intent.client_order_id] = (intent.market_ref.market_id, intent.side)

    def apply(self, event: OrderEvent) -> PortfolioState:
        if event.event_type in ("filled", "partial"):
            key = self._intent_market.get(event.intent_id, (event.intent_id, event.side))
            self._apply_fill(event, key)
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
            "schema_version": 2,
            "session_id": self._session_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "cash_balance": snap.cash_balance,
            "realized_pnl": snap.realized_pnl,
            "unrealized_pnl": snap.unrealized_pnl,
            "positions": {
                self._serialize_key(key): {
                    "market_id": p.market_id,
                    "side": p.side,
                    "size": p.size,
                    "avg_price": p.avg_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for key, p in snap.positions.items()
            },
        }
        path.write_text(json.dumps(payload, indent=2))
        return path

    def mark_to_market(self, prices: dict[PositionKey, float]) -> PortfolioState:
        unrealized = 0.0
        for key, mark in prices.items():
            existing = self._state.positions.get(key)
            if existing is None:
                continue
            pnl = (float(mark) - existing.avg_price) * existing.size
            self._state.positions[key] = Position(
                market_id=existing.market_id,
                size=existing.size,
                avg_price=existing.avg_price,
                unrealized_pnl=pnl,
                side=existing.side,
            )
            unrealized += pnl
        self._state.unrealized_pnl = unrealized
        return self.snapshot()

    def settle(self, market_id: str, outcome: Literal["yes", "no"]) -> PortfolioState:
        for side in ("yes", "no"):
            key: PositionKey = (market_id, side)
            existing = self._state.positions.pop(key, None)
            if existing is None:
                continue
            payout = 1.0 if side == outcome else 0.0
            self._state.realized_pnl += (payout - existing.avg_price) * existing.size
            self._state.cash_balance += payout * existing.size
        self._state.unrealized_pnl = sum(p.unrealized_pnl for p in self._state.positions.values())
        return self.snapshot()

    def _apply_fill(self, event: OrderEvent, key: PositionKey) -> None:
        market_id, side = key
        existing = self._state.positions.get(key)
        if event.action == "close":
            self._apply_close(event, key, existing)
            return

        if existing is None:
            new_pos = Position(
                market_id=market_id,
                size=event.size,
                avg_price=event.price,
                unrealized_pnl=0.0,
                side=side,
            )
        else:
            total_size = existing.size + event.size
            avg_price = (existing.size * existing.avg_price + event.size * event.price) / total_size
            new_pos = Position(
                market_id=market_id,
                size=total_size,
                avg_price=avg_price,
                unrealized_pnl=existing.unrealized_pnl,
                side=side,
            )
        self._state.positions[key] = new_pos
        self._state.cash_balance -= event.price * event.size

    def _apply_close(self, event: OrderEvent, key: PositionKey, existing: Position | None) -> None:
        if existing is None or event.size > existing.size:
            raise ValueError(f"Cannot close {event.size} contracts for missing or smaller position {key}")
        realized = (event.price - existing.avg_price) * event.size
        remaining = existing.size - event.size
        self._state.realized_pnl += realized
        self._state.cash_balance += event.price * event.size
        if remaining <= 1e-9:
            self._state.positions.pop(key, None)
            return
        self._state.positions[key] = Position(
            market_id=existing.market_id,
            size=remaining,
            avg_price=existing.avg_price,
            unrealized_pnl=existing.unrealized_pnl,
            side=existing.side,
        )

    @staticmethod
    def _serialize_key(key: PositionKey | str) -> str:
        if isinstance(key, tuple):
            return f"{key[0]}:{key[1]}"
        return str(key)
