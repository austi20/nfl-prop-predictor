from __future__ import annotations

from datetime import datetime

import pytest

from api.trading.mapper import PickToIntentMapper
from api.trading.types import MarketRef, Signal


class TestPickToIntentMapper:
    def _signal(self, side: str = "over", edge: float = 0.06) -> Signal:
        return Signal(
            pick_id="pick-1",
            player_id="player-1",
            stat="passing_yards",
            line=250.5,
            selected_side=side,  # type: ignore[arg-type]
            modeled_prob=0.58,
            edge=edge,
            created_at=datetime(2025, 9, 1, 12, 0),
        )

    def _markets(self) -> list[MarketRef]:
        return [
            MarketRef(
                venue="kalshi",
                market_id="MKT-1",
                ticker="MKT-1",
                tick_size=0.01,
                min_size=1.0,
                yes_token="Y",
                no_token="N",
            )
        ]

    def test_over_maps_to_yes(self) -> None:
        mapper = PickToIntentMapper()
        intent = mapper.map_signal(self._signal("over"), self._markets())
        assert intent is not None
        assert intent.side == "yes"

    def test_under_maps_to_no(self) -> None:
        mapper = PickToIntentMapper()
        intent = mapper.map_signal(self._signal("under"), self._markets())
        assert intent is not None
        assert intent.side == "no"

    def test_no_markets_returns_none(self) -> None:
        mapper = PickToIntentMapper()
        assert mapper.map_signal(self._signal(), []) is None

    def test_edge_propagated(self) -> None:
        mapper = PickToIntentMapper()
        intent = mapper.map_signal(self._signal(edge=0.09), self._markets())
        assert intent is not None
        assert intent.edge == pytest.approx(0.09)

    def test_limit_price_clamped(self) -> None:
        mapper = PickToIntentMapper()
        intent = mapper.map_signal(self._signal(), self._markets())
        assert intent is not None
        assert 0.01 <= intent.limit_price <= 0.99
