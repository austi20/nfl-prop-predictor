from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass(frozen=True)
class Signal:
    pick_id: str
    player_id: str
    stat: str
    line: float
    selected_side: Literal["over", "under"]
    modeled_prob: float
    edge: float
    created_at: datetime


@dataclass(frozen=True)
class MarketRef:
    venue: str
    market_id: str
    ticker: str
    tick_size: float
    min_size: float
    yes_token: str
    no_token: str


@dataclass(frozen=True)
class ExecutionIntent:
    signal_id: str
    market_ref: MarketRef
    side: Literal["yes", "no"]
    limit_price: float
    size: float
    edge: float
    client_order_id: str
    expires_at: datetime


@dataclass(frozen=True)
class RiskDecision:
    intent_id: str
    approved: bool
    reason: str
    caps_snapshot: dict[str, float]


OrderEventType = Literal["submitted", "acked", "filled", "partial", "canceled", "rejected"]


@dataclass(frozen=True)
class OrderEvent:
    intent_id: str
    event_type: OrderEventType
    venue_order_id: str
    price: float
    size: float
    ts: datetime
    side: Literal["yes", "no"] = "yes"
    action: Literal["open", "close"] = "open"


@dataclass(frozen=True)
class Trade:
    market_id: str
    side: Literal["yes", "no"]
    open_event: OrderEvent
    close_event: OrderEvent
    realized_pnl: float


@dataclass(frozen=True)
class Position:
    market_id: str
    size: float
    avg_price: float
    unrealized_pnl: float
    side: Literal["yes", "no"] = "yes"


@dataclass
class PortfolioState:
    cash_balance: float
    positions: dict[tuple[str, Literal["yes", "no"]] | str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
