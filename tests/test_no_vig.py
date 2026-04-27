from __future__ import annotations

import pandas as pd
import pytest

from eval.no_vig import remove_vig_two_sided
from eval.prop_pricer import build_paper_trade_picks, price_two_sided_prop_decision


def test_multiplicative_no_vig_even_market():
    over, under = remove_vig_two_sided(-110, -110)
    assert over == pytest.approx(0.5)
    assert under == pytest.approx(0.5)


def test_multiplicative_no_vig_asymmetric_market():
    over, under = remove_vig_two_sided(-150, 130)
    raw_over = 150 / 250
    raw_under = 100 / 230
    total = raw_over + raw_under
    assert over == pytest.approx(raw_over / total)
    assert under == pytest.approx(raw_under / total)
    assert over + under == pytest.approx(1.0)


def test_additive_no_vig_sums_to_one():
    over, under = remove_vig_two_sided(-125, 105, method="additive")
    assert over + under == pytest.approx(1.0)


def test_shin_method_is_explicitly_deferred():
    with pytest.raises(NotImplementedError):
        remove_vig_two_sided(-110, -110, method="shin")


def test_decision_object_marks_no_bet_below_ev_threshold():
    decision = price_two_sided_prop_decision(
        raw_prob_over=0.51,
        over_odds=-110,
        under_odds=-110,
        min_ev=0.05,
    )
    assert decision.recommendation == "no_bet"
    assert decision.market_p_over_no_vig == pytest.approx(0.5)


def test_ev_ranking_can_differ_from_raw_edge_ranking():
    rows = pd.DataFrame([
        {
            "player_id": "p1",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 250.5,
            "raw_prob": 0.58,
            "actual_value": 260.0,
            "book": "test",
            "over_odds": -180,
            "under_odds": 150,
        },
        {
            "player_id": "p2",
            "season": 2024,
            "week": 1,
            "stat": "passing_yards",
            "line": 250.5,
            "raw_prob": 0.55,
            "actual_value": 260.0,
            "book": "test",
            "over_odds": 130,
            "under_odds": -150,
        },
    ])

    picks = build_paper_trade_picks(rows, min_ev=-1.0, max_picks_per_week=1)

    assert picks.iloc[0]["player_id"] == "p2"
    assert picks.iloc[0]["selected_ev"] > picks.iloc[0]["selected_edge"]
