from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from api.trading.risk import ExposureRiskEngine
from api.trading.types import ExecutionIntent, MarketRef, PortfolioState, Position


def _market() -> MarketRef:
    return MarketRef(
        venue="paper",
        market_id="MKT-1",
        ticker="MKT-1",
        tick_size=0.01,
        min_size=1.0,
        yes_token="Y",
        no_token="N",
    )


def _intent(*, side: str = "yes", limit_price: float = 0.40, size: float = 10.0, hours: float = 4.0) -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig",
        market_ref=_market(),
        side=side,  # type: ignore[arg-type]
        limit_price=limit_price,
        size=size,
        edge=0.10,
        client_order_id="ord",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=hours),
    )


def test_blocks_entries_inside_lock_buffer():
    engine = ExposureRiskEngine(entry_buffer_seconds=7200)
    decision = engine.evaluate(_intent(hours=1), PortfolioState(cash_balance=0.0))
    assert not decision.approved
    assert "entry_buffer" in decision.reason


def test_no_side_worst_case_uses_one_minus_price():
    engine = ExposureRiskEngine(max_notional_per_order=50.0, entry_buffer_seconds=0)
    decision = engine.evaluate(
        _intent(side="no", limit_price=0.20, size=100.0),
        PortfolioState(cash_balance=0.0),
    )
    assert not decision.approved
    assert "worst_case_loss" in decision.reason


def test_side_inventory_cap():
    engine = ExposureRiskEngine(max_yes_inventory_per_market=10.0, entry_buffer_seconds=0)
    portfolio = PortfolioState(
        cash_balance=0.0,
        positions={("MKT-1", "yes"): Position(market_id="MKT-1", side="yes", size=8.0, avg_price=0.5, unrealized_pnl=0.0)},
    )
    decision = engine.evaluate(_intent(size=3.0), portfolio)
    assert not decision.approved
    assert "yes_inventory" in decision.reason
