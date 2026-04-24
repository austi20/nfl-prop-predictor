from __future__ import annotations

from datetime import datetime

import pytest

from api.trading.risk import StaticRiskEngine
from api.trading.types import ExecutionIntent, MarketRef, PortfolioState, Position


def _market(market_id: str = "MKT-1") -> MarketRef:
    return MarketRef(
        venue="kalshi",
        market_id=market_id,
        ticker=market_id,
        tick_size=0.01,
        min_size=1.0,
        yes_token="Y",
        no_token="N",
    )


def _intent(
    *,
    limit_price: float = 0.55,
    size: float = 10.0,
    edge: float = 0.05,
    market_id: str = "MKT-1",
) -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig-1",
        market_ref=_market(market_id),
        side="yes",
        limit_price=limit_price,
        size=size,
        edge=edge,
        client_order_id="ord-1",
        expires_at=datetime(2025, 9, 1),
    )


def _empty_portfolio() -> PortfolioState:
    return PortfolioState(cash_balance=1000.0)


class TestMaxNotionalPerOrder:
    def test_blocks_when_exceeded(self) -> None:
        engine = StaticRiskEngine(max_notional_per_order=50.0)
        decision = engine.evaluate(_intent(limit_price=0.6, size=100.0), _empty_portfolio())
        assert not decision.approved
        assert "notional" in decision.reason

    def test_approves_within_limit(self) -> None:
        engine = StaticRiskEngine(max_notional_per_order=100.0)
        decision = engine.evaluate(_intent(limit_price=0.5, size=10.0), _empty_portfolio())
        assert decision.approved


class TestMaxOpenNotionalPerMarket:
    def test_blocks_when_existing_position_plus_new_exceeds_cap(self) -> None:
        engine = StaticRiskEngine(max_open_notional_per_market=100.0)
        portfolio = PortfolioState(
            cash_balance=500.0,
            positions={"MKT-1": Position(market_id="MKT-1", size=90.0, avg_price=1.0, unrealized_pnl=0.0)},
        )
        decision = engine.evaluate(_intent(limit_price=0.5, size=20.0), portfolio)
        assert not decision.approved
        assert "open_notional" in decision.reason

    def test_approves_different_markets(self) -> None:
        engine = StaticRiskEngine(max_open_notional_per_market=100.0)
        portfolio = PortfolioState(
            cash_balance=500.0,
            positions={"MKT-2": Position(market_id="MKT-2", size=90.0, avg_price=1.0, unrealized_pnl=0.0)},
        )
        decision = engine.evaluate(_intent(limit_price=0.5, size=10.0, market_id="MKT-1"), portfolio)
        assert decision.approved


class TestDailyLossCap:
    def test_blocks_when_loss_exceeds_cap(self) -> None:
        engine = StaticRiskEngine(daily_loss_cap=50.0)
        portfolio = PortfolioState(cash_balance=0.0, realized_pnl=-55.0)
        decision = engine.evaluate(_intent(), portfolio)
        assert not decision.approved
        assert "daily_loss" in decision.reason

    def test_approves_when_under_cap(self) -> None:
        engine = StaticRiskEngine(daily_loss_cap=100.0)
        portfolio = PortfolioState(cash_balance=0.0, realized_pnl=-40.0)
        decision = engine.evaluate(_intent(), portfolio)
        assert decision.approved


class TestMinEdge:
    def test_blocks_low_edge(self) -> None:
        engine = StaticRiskEngine(min_edge=0.05)
        decision = engine.evaluate(_intent(edge=0.02), _empty_portfolio())
        assert not decision.approved
        assert "edge" in decision.reason

    def test_approves_sufficient_edge(self) -> None:
        engine = StaticRiskEngine(min_edge=0.05)
        decision = engine.evaluate(_intent(edge=0.06), _empty_portfolio())
        assert decision.approved


class TestRejectCooldown:
    def test_trips_kill_switch_after_n_rejects(self) -> None:
        engine = StaticRiskEngine(
            min_edge=0.10,
            reject_cooldown_n=3,
            reject_cooldown_seconds=60.0,
        )
        low_edge_intent = _intent(edge=0.01)
        portfolio = _empty_portfolio()

        for _ in range(3):
            engine.evaluate(low_edge_intent, portfolio)

        assert engine.is_tripped()

    def test_tripped_engine_blocks_all_intents(self) -> None:
        engine = StaticRiskEngine()
        engine.trip("manual")
        decision = engine.evaluate(_intent(), _empty_portfolio())
        assert not decision.approved
        assert "kill_switch" in decision.reason

    def test_caps_snapshot_present_on_reject(self) -> None:
        engine = StaticRiskEngine(min_edge=0.10)
        decision = engine.evaluate(_intent(edge=0.01), _empty_portfolio())
        assert "min_edge" in decision.caps_snapshot
