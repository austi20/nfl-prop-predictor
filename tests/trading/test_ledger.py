from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from api.trading.ledger import InMemoryPortfolioLedger
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


def _intent(market_id: str = "MKT-1") -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig-1",
        market_ref=_market(market_id),
        side="yes",
        limit_price=0.55,
        size=10.0,
        edge=0.06,
        client_order_id="ord-1",
        expires_at=datetime(2025, 9, 1),
    )


def _event(event_type: str, price: float = 0.55, size: float = 10.0) -> OrderEvent:
    return OrderEvent(
        intent_id="ord-1",
        event_type=event_type,  # type: ignore[arg-type]
        venue_order_id="venue-1",
        price=price,
        size=size,
        ts=datetime(2025, 9, 1),
    )


def _ledger(tmp_path: Path) -> InMemoryPortfolioLedger:
    ledger = InMemoryPortfolioLedger(audit_dir=tmp_path / "audit", session_id="test")
    ledger.register_intent(_intent())
    return ledger


class TestFill:
    def test_buy_fill_creates_position(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        state = ledger.apply(_event("filled", price=0.55, size=10.0))
        assert ("MKT-1", "yes") in state.positions
        pos = state.positions[("MKT-1", "yes")]
        assert pos.size == 10.0
        assert pos.avg_price == pytest.approx(0.55)

    def test_fill_debits_cash(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.apply(_event("filled", price=0.55, size=10.0))
        assert ledger.snapshot().cash_balance == pytest.approx(-5.5)

    def test_partial_fill_accumulates(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.apply(_event("partial", price=0.50, size=5.0))
        ledger.apply(_event("partial", price=0.60, size=5.0))
        pos = ledger.snapshot().positions[("MKT-1", "yes")]
        assert pos.size == 10.0
        assert pos.avg_price == pytest.approx(0.55)

    def test_cancel_no_position_change(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        state_before = ledger.snapshot()
        ledger.apply(_event("canceled"))
        assert ledger.snapshot().positions == state_before.positions

    def test_rejected_no_position_change(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.apply(_event("rejected"))
        assert "MKT-1" not in ledger.snapshot().positions


class TestPersist:
    def test_persist_writes_json(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.apply(_event("filled"))
        path = ledger.persist()
        assert path.exists()
        import json
        data = json.loads(path.read_text())
        assert data["session_id"] == "test"
        assert "MKT-1:yes" in data["positions"]

    def test_mark_to_market_and_settle(self, tmp_path: Path) -> None:
        ledger = _ledger(tmp_path)
        ledger.apply(_event("filled", price=0.40, size=10.0))
        marked = ledger.mark_to_market({("MKT-1", "yes"): 0.55})
        assert marked.unrealized_pnl == pytest.approx(1.5)

        settled = ledger.settle("MKT-1", "yes")
        assert settled.realized_pnl == pytest.approx(6.0)
        assert ("MKT-1", "yes") not in settled.positions
