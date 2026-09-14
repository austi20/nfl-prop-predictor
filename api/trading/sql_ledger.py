"""SQL-backed portfolio ledger (NBABets v2 `sql_ledger.py` pattern).

Drop-in replacement for `InMemoryPortfolioLedger`: same public interface,
same fill/close/settle math, but every mutation is committed to SQLite so
portfolio state survives restarts. State is loaded from the DB on init.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from sqlalchemy import select

from api.db import SessionFactory
from api.db.models import (
    TradingEventRow,
    TradingIntentRow,
    TradingPositionRow,
    TradingStateRow,
)
from api.trading.types import ExecutionIntent, OrderEvent, PortfolioState, Position

PositionKey = tuple[str, Literal["yes", "no"]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SqlPortfolioLedger:
    """Side-aware portfolio ledger persisted to SQLite."""

    def __init__(
        self,
        session_factory: SessionFactory,
        audit_dir: Path,
        session_id: str | None = None,
    ) -> None:
        self._sessions = session_factory
        self._audit_dir = audit_dir
        self._session_id = session_id or uuid.uuid4().hex[:8]
        self._state = PortfolioState(cash_balance=0.0)
        self._intent_market: dict[str, PositionKey] = {}
        self._load()

    # -- persistence -------------------------------------------------------

    def _load(self) -> None:
        with self._sessions() as session:
            row = session.get(TradingStateRow, 1)
            if row is not None:
                self._state.cash_balance = row.cash_balance
                self._state.realized_pnl = row.realized_pnl
                self._state.unrealized_pnl = row.unrealized_pnl
            for pos in session.scalars(select(TradingPositionRow)):
                side: Literal["yes", "no"] = "no" if pos.side == "no" else "yes"
                self._state.positions[(pos.market_id, side)] = Position(
                    market_id=pos.market_id,
                    size=pos.size,
                    avg_price=pos.avg_price,
                    unrealized_pnl=pos.unrealized_pnl,
                    side=side,
                )
            for intent in session.scalars(select(TradingIntentRow)):
                iside: Literal["yes", "no"] = "no" if intent.side == "no" else "yes"
                self._intent_market[intent.client_order_id] = (intent.market_id, iside)

    def _flush(self) -> None:
        """Write aggregates + full position set to the DB."""
        now = _now()
        with self._sessions() as session:
            row = session.get(TradingStateRow, 1)
            if row is None:
                row = TradingStateRow(id=1, updated_at=now)
                session.add(row)
            row.cash_balance = self._state.cash_balance
            row.realized_pnl = self._state.realized_pnl
            row.unrealized_pnl = self._state.unrealized_pnl
            row.updated_at = now

            existing = {(p.market_id, p.side): p for p in session.scalars(select(TradingPositionRow))}
            live_keys = set()
            for (market_id, side), pos in self._state.positions.items():
                live_keys.add((market_id, side))
                db_pos = existing.get((market_id, side))
                if db_pos is None:
                    db_pos = TradingPositionRow(market_id=market_id, side=side, updated_at=now)
                    session.add(db_pos)
                db_pos.size = pos.size
                db_pos.avg_price = pos.avg_price
                db_pos.unrealized_pnl = pos.unrealized_pnl
                db_pos.updated_at = now
            for key, db_pos in existing.items():
                if key not in live_keys:
                    session.delete(db_pos)
            session.commit()

    def _record_event(self, event: OrderEvent) -> None:
        with self._sessions() as session:
            session.add(
                TradingEventRow(
                    intent_id=event.intent_id,
                    event_type=event.event_type,
                    venue_order_id=event.venue_order_id,
                    price=event.price,
                    size=event.size,
                    side=event.side,
                    action=event.action,
                    ts=event.ts if event.ts.tzinfo else event.ts.replace(tzinfo=timezone.utc),
                )
            )
            session.commit()

    # -- ledger interface (mirrors InMemoryPortfolioLedger) -----------------

    def register_intent(self, intent: ExecutionIntent) -> None:
        key: PositionKey = (intent.market_ref.market_id, intent.side)
        self._intent_market[intent.client_order_id] = key
        with self._sessions() as session:
            if session.get(TradingIntentRow, intent.client_order_id) is None:
                session.add(
                    TradingIntentRow(
                        client_order_id=intent.client_order_id,
                        market_id=key[0],
                        side=key[1],
                        created_at=_now(),
                    )
                )
                session.commit()

    def apply(self, event: OrderEvent) -> PortfolioState:
        self._record_event(event)
        if event.event_type in ("filled", "partial"):
            key = self._intent_market.get(event.intent_id, (event.intent_id, event.side))
            self._apply_fill(event, key)
            self._flush()
        return self.snapshot()

    def snapshot(self) -> PortfolioState:
        return PortfolioState(
            cash_balance=self._state.cash_balance,
            positions=dict(self._state.positions),
            realized_pnl=self._state.realized_pnl,
            unrealized_pnl=self._state.unrealized_pnl,
        )

    def persist(self) -> Path:
        """State is already durable in SQLite; keep the JSON audit snapshot."""
        self._flush()
        self._audit_dir.mkdir(parents=True, exist_ok=True)
        path = self._audit_dir / f"portfolio-{self._session_id}.json"
        snap = self.snapshot()
        payload = {
            "schema_version": 2,
            "session_id": self._session_id,
            "ts": _now().isoformat(),
            "cash_balance": snap.cash_balance,
            "realized_pnl": snap.realized_pnl,
            "unrealized_pnl": snap.unrealized_pnl,
            "positions": {
                f"{k[0]}:{k[1]}" if isinstance(k, tuple) else str(k): {
                    "market_id": p.market_id,
                    "side": p.side,
                    "size": p.size,
                    "avg_price": p.avg_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for k, p in snap.positions.items()
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
        self._flush()
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
        self._flush()
        return self.snapshot()

    # -- fill math (identical to InMemoryPortfolioLedger) -------------------

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
