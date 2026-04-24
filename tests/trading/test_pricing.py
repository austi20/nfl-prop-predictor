from __future__ import annotations

from datetime import datetime

import pytest

from api.trading.mapper import PickToIntentMapper
from api.trading.pricing import american_to_prob, prob_to_clob_price
from api.trading.types import MarketRef, Signal


class TestAmericanToProb:
    def test_minus_110(self) -> None:
        assert american_to_prob(-110) == pytest.approx(110 / 210, rel=1e-4)

    def test_plus_120(self) -> None:
        assert american_to_prob(120) == pytest.approx(100 / 220, rel=1e-4)

    def test_even_money(self) -> None:
        assert american_to_prob(100) == pytest.approx(0.5)

    def test_heavy_favorite(self) -> None:
        prob = american_to_prob(-300)
        assert prob == pytest.approx(300 / 400)

    def test_range_valid(self) -> None:
        for american in [-500, -200, -110, 100, 150, 300]:
            p = american_to_prob(american)
            assert 0.0 < p < 1.0


class TestProbToClobPrice:
    def test_clamps_below(self) -> None:
        assert prob_to_clob_price(0.0) == 0.01

    def test_clamps_above(self) -> None:
        assert prob_to_clob_price(1.0) == 0.99

    def test_passthrough_midrange(self) -> None:
        assert prob_to_clob_price(0.55) == pytest.approx(0.55)


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
