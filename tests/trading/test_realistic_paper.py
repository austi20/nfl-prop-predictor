from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from api.trading.paper_adapter import RealisticPaperAdapter
from api.trading.types import ExecutionIntent, MarketRef


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


def _intent(limit_price: float, size: float = 10.0) -> ExecutionIntent:
    return ExecutionIntent(
        signal_id="sig",
        market_ref=_market(),
        side="yes",
        limit_price=limit_price,
        size=size,
        edge=0.10,
        client_order_id="ord",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=4),
    )


@pytest.mark.anyio
async def test_far_from_mid_limit_can_nonfill():
    adapter = RealisticPaperAdapter(rng=random.Random(1))
    event = await adapter.submit(_intent(limit_price=0.01))
    assert event.event_type == "acked"
    assert event.size == 0.0


@pytest.mark.anyio
async def test_fill_uses_executable_price_not_limit():
    adapter = RealisticPaperAdapter(rng=random.Random(5), mid_price=0.50, spread=0.02)
    event = await adapter.submit(_intent(limit_price=0.99, size=1.0))
    assert event.event_type == "filled"
    assert event.price == pytest.approx(0.51)
