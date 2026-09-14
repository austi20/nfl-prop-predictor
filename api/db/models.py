"""SQLAlchemy models for durable trading state.

Ported from the NBABets v2 pattern (`app/db/models/trading.py`), adapted to
this repo's side-aware position keys and OrderEvent shape.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TradingStateRow(Base):
    """Singleton row holding portfolio-level aggregates."""

    __tablename__ = "trading_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_trading_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cash_balance: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingPositionRow(Base):
    __tablename__ = "trading_positions"

    market_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    side: Mapped[str] = mapped_column(String(8), primary_key=True)
    size: Mapped[float] = mapped_column(Float, default=0.0)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingIntentRow(Base):
    """Maps client_order_id -> side-aware position key (survives restart)."""

    __tablename__ = "trading_intents"

    client_order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    market_id: Mapped[str] = mapped_column(String(128))
    side: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingEventRow(Base):
    """Append-only order-event audit log."""

    __tablename__ = "trading_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intent_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(32))
    venue_order_id: Mapped[str] = mapped_column(String(128), default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    size: Mapped[float] = mapped_column(Float, default=0.0)
    side: Mapped[str] = mapped_column(String(8), default="yes")
    action: Mapped[str] = mapped_column(String(8), default="open")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TradingKillSwitch(Base):
    """Singleton kill switch, checked before any order submission."""

    __tablename__ = "trading_kill_switch"
    __table_args__ = (CheckConstraint("id = 1", name="ck_kill_switch_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    killed: Mapped[bool] = mapped_column(Boolean, default=False)
    flatten: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(255), default="")
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    set_by: Mapped[str] = mapped_column(String(64), default="")
