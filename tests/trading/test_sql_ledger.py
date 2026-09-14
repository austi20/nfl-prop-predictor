from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from api.db import make_session_factory
from api.trading.kill_switch import SqlKillSwitch
from api.trading.sql_ledger import SqlPortfolioLedger
from api.trading.types import ExecutionIntent, MarketRef, OrderEvent


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


def _intent(market_id: str = "MKT-1", order_id: str = "ord-1") -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig-1",
        market_ref=_market(market_id),
        side="yes",
        limit_price=0.55,
        size=10.0,
        edge=0.06,
        client_order_id=order_id,
        expires_at=datetime(2025, 9, 1),
    )


def _event(
    event_type: str,
    price: float = 0.55,
    size: float = 10.0,
    intent_id: str = "ord-1",
    action: str = "open",
) -> OrderEvent:
    return OrderEvent(
        intent_id=intent_id,
        event_type=event_type,  # type: ignore[arg-type]
        venue_order_id="venue-1",
        price=price,
        size=size,
        ts=datetime(2025, 9, 1),
        action=action,  # type: ignore[arg-type]
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "trading.db"


def _ledger(tmp_path: Path, db_path: Path) -> SqlPortfolioLedger:
    factory = make_session_factory(db_path)
    ledger = SqlPortfolioLedger(factory, audit_dir=tmp_path / "audit", session_id="test")
    ledger.register_intent(_intent())
    return ledger


class TestFillMath:
    def test_buy_fill_creates_position(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)
        state = ledger.apply(_event("filled", price=0.55, size=10.0))
        pos = state.positions[("MKT-1", "yes")]
        assert pos.size == 10.0
        assert pos.avg_price == pytest.approx(0.55)
        assert state.cash_balance == pytest.approx(-5.5)

    def test_close_realizes_pnl(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)
        ledger.apply(_event("filled", price=0.55, size=10.0))
        state = ledger.apply(_event("filled", price=0.70, size=10.0, action="close"))
        assert ("MKT-1", "yes") not in state.positions
        assert state.realized_pnl == pytest.approx(1.5)

    def test_settle_pays_out(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)
        ledger.apply(_event("filled", price=0.55, size=10.0))
        state = ledger.settle("MKT-1", "yes")
        assert state.realized_pnl == pytest.approx(4.5)
        assert state.cash_balance == pytest.approx(4.5)


class TestDurability:
    def test_state_survives_restart(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)
        ledger.apply(_event("filled", price=0.55, size=10.0))

        # New ledger instance over the same DB = process restart
        factory = make_session_factory(db_path)
        reborn = SqlPortfolioLedger(factory, audit_dir=tmp_path / "audit", session_id="test2")
        state = reborn.snapshot()
        pos = state.positions[("MKT-1", "yes")]
        assert pos.size == 10.0
        assert pos.avg_price == pytest.approx(0.55)
        assert state.cash_balance == pytest.approx(-5.5)

    def test_intent_map_survives_restart(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)

        factory = make_session_factory(db_path)
        reborn = SqlPortfolioLedger(factory, audit_dir=tmp_path / "audit", session_id="test2")
        # apply uses the restored intent map to find the side-aware key
        state = reborn.apply(_event("filled", price=0.55, size=10.0))
        assert ("MKT-1", "yes") in state.positions

    def test_settled_position_removed_from_db(self, tmp_path: Path, db_path: Path) -> None:
        ledger = _ledger(tmp_path, db_path)
        ledger.apply(_event("filled", price=0.55, size=10.0))
        ledger.settle("MKT-1", "yes")

        factory = make_session_factory(db_path)
        reborn = SqlPortfolioLedger(factory, audit_dir=tmp_path / "audit", session_id="test2")
        assert reborn.snapshot().positions == {}
        assert reborn.snapshot().realized_pnl == pytest.approx(4.5)


class TestKillSwitch:
    def test_default_not_killed(self, db_path: Path) -> None:
        ks = SqlKillSwitch(make_session_factory(db_path))
        assert ks.is_killed() is False

    def test_trip_and_reset(self, db_path: Path) -> None:
        ks = SqlKillSwitch(make_session_factory(db_path))
        ks.trip("manual", set_by="test")
        assert ks.is_killed() is True
        status = ks.status()
        assert status["reason"] == "manual"
        assert status["set_by"] == "test"
        ks.reset()
        assert ks.is_killed() is False

    def test_trip_survives_restart(self, db_path: Path) -> None:
        SqlKillSwitch(make_session_factory(db_path)).trip("manual")
        # fresh factory over same DB
        assert SqlKillSwitch(make_session_factory(db_path)).is_killed() is True
