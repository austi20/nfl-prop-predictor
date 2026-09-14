from __future__ import annotations

from eval.fantasy_tiers import TIER_KEYS, TIER_LABELS, assign_tiers, starter_demand


def test_starter_demand_matches_a_12_team_league():
    assert starter_demand("QB") == 12
    assert starter_demand("RB") == 24
    assert starter_demand("WR") == 36
    assert starter_demand("TE") == 12
    assert starter_demand("FLEX") == 84
    assert starter_demand("ALL") == 96


def test_every_tier_key_has_a_label():
    assert set(TIER_LABELS) == set(TIER_KEYS)


def test_empty_list_tiers_to_nothing():
    assert assign_tiers([], 12) == []


def test_tiers_are_monotonic_and_start_at_the_top():
    points = [30.0 - i * 0.4 for i in range(40)]
    tiers = assign_tiers(points, starters=12)
    assert tiers[0] == "start_no_doubt"
    order = {key: i for i, key in enumerate(TIER_KEYS)}
    assert all(order[a] <= order[b] for a, b in zip(tiers, tiers[1:]))


def test_short_list_never_runs_past_the_end():
    tiers = assign_tiers([20.0, 18.0, 5.0], starters=24)
    assert len(tiers) == 3
    assert set(tiers) <= set(TIER_KEYS)


def test_boundary_snaps_to_a_real_scoring_gap():
    # 24 starters => the "feels good" cut wants rank 24, but the only drop-off
    # in the list is after rank 21. The cut should move there.
    points = [20.0 - i * 0.05 for i in range(21)] + [9.0 - i * 0.05 for i in range(19)]
    tiers = assign_tiers(points, starters=24)
    assert tiers[20] == "feels_good"
    assert tiers[21] != "feels_good"


def test_flat_list_falls_back_to_rank_boundaries():
    points = [10.0] * 40
    tiers = assign_tiers(points, starters=12)
    # No gaps anywhere, so cuts land on the nominal ranks (0.5x and 1.0x).
    assert tiers[5] == "start_no_doubt"
    assert tiers[6] == "feels_good"
    assert tiers[11] == "feels_good"
    assert tiers[12] == "w_flex"


def test_deep_list_reaches_the_bottom_tier():
    points = [30.0 - i * 0.25 for i in range(120)]
    assert assign_tiers(points, starters=12)[-1] == "do_not_play"
