from __future__ import annotations

from datetime import datetime

import pytest

from api.trading.paper_adapter import FakePaperAdapter
from api.trading.types import ExecutionIntent, MarketRef


def _market() -> MarketRef:
    return MarketRef(
        venue="kalshi",
        market_id="MKT-1",
        ticker="MKT-1",
        tick_size=0.01,
        min_size=1.0,
        yes_token="Y",
        no_token="N",
    )


def _intent(limit_price: float = 0.55, size: float = 10.0) -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig-1",
        market_ref=_market(),
        side="yes",
        limit_price=limit_price,
        size=size,
        edge=0.06,
        client_order_id="ord-1",
        expires_at=datetime(2025, 9, 1),
    )


@pytest.mark.anyio
async def test_submit_valid_returns_filled() -> None:
    adapter = FakePaperAdapter()
    event = await adapter.submit(_intent())
    assert event.event_type == "filled"
    assert event.price == pytest.approx(0.55)
    assert event.size == pytest.approx(10.0)


@pytest.mark.anyio
async def test_submit_price_above_one_returns_rejected() -> None:
    adapter = FakePaperAdapter()
    event = await adapter.submit(_intent(limit_price=1.5))
    assert event.event_type == "rejected"


@pytest.mark.anyio
async def test_submit_negative_price_returns_rejected() -> None:
    adapter = FakePaperAdapter()
    event = await adapter.submit(_intent(limit_price=-0.1))
    assert event.event_type == "rejected"


@pytest.mark.anyio
async def test_submit_zero_size_returns_rejected() -> None:
    adapter = FakePaperAdapter()
    event = await adapter.submit(_intent(size=0.0))
    assert event.event_type == "rejected"


@pytest.mark.anyio
async def test_cancel_returns_canceled() -> None:
    adapter = FakePaperAdapter()
    event = await adapter.cancel("venue-order-123")
    assert event.event_type == "canceled"


@pytest.mark.anyio
async def test_list_markets_returns_paper_venue() -> None:
    adapter = FakePaperAdapter()
    markets = await adapter.list_markets("passing_yards", "player-abc")
    assert len(markets) == 1
    assert markets[0].venue == "paper"


def test_kill_switch_trips() -> None:
    adapter = FakePaperAdapter()
    assert not adapter.is_tripped()
    adapter.trip("test reason")
    assert adapter.is_tripped()


def test_kill_switch_resets() -> None:
    adapter = FakePaperAdapter()
    adapter.trip("test")
    adapter.reset()
    assert not adapter.is_tripped()
