from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from models.base import StatDistribution
from models.dist_family import compose_receptions_distribution
from models.wr_te import WRTEModel


def _make_receiver_fixture(seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, float | int | str]] = []
    teams = ["KC", "BUF", "SF", "DAL"]
    opps = ["DEN", "MIA", "SEA", "PHI"]

    for pid in range(4):
        for season in (2022, 2023):
            for week in range(1, 13):
                targets = rng.poisson(7 if pid % 2 == 0 else 4)
                targets = max(int(targets), 1)
                catch_rate = 0.72 if pid % 2 == 0 else 0.52
                receptions = rng.binomial(targets, catch_rate)
                rows.append(
                    {
                        "player_id": f"wr_{pid}",
                        "player_name": f"WR{pid}",
                        "position": "WR" if pid < 3 else "TE",
                        "season": season,
                        "week": week,
                        "recent_team": teams[pid],
                        "opponent_team": opps[pid],
                        "receptions": float(receptions),
                        "receiving_yards": float(max(receptions, 1) * rng.gamma(shape=2.2, scale=7.5)),
                        "receiving_tds": float(rng.binomial(1, 0.10 if receptions > 0 else 0.02)),
                        "targets": float(targets),
                        "target_share": float(rng.uniform(0.08, 0.30)),
                        "air_yards_share": float(rng.uniform(0.06, 0.28)),
                        "wopr": float(rng.uniform(0.08, 0.50)),
                        "receiving_epa": float(rng.normal(0.0, 2.0)),
                        "is_home": float(rng.integers(0, 2)),
                    }
                )
    return pd.DataFrame(rows)


def test_quantile_distribution_uses_empirical_lookup():
    dist = StatDistribution(
        mean=100.0,
        std=20.0,
        dist_type="quantile",
        quantiles={0.1: 70.0, 0.25: 85.0, 0.5: 100.0, 0.75: 115.0, 0.9: 130.0},
    )

    assert dist.prob_over(100.0) == pytest.approx(0.5, abs=0.05)


def test_count_aware_model_exposes_exact_zero_mass():
    weekly = _make_receiver_fixture()
    model = WRTEModel()
    model.fit([2022], weekly=weekly, dist_family="count_aware")

    pred = model.predict("wr_0", week=8, season=2023)
    td_dist = pred["receiving_tds"]
    zero_mass = 1.0 - td_dist.prob_over(0.0)

    assert td_dist.dist_type in {
        "poisson",
        "negative_binomial",
        "zero_inflated_poisson",
        "zero_inflated_negative_binomial",
    }
    assert 0.0 < zero_mass < 1.0


def test_decomposed_receptions_match_binomial_example():
    targets = StatDistribution.from_samples(np.full(20000, 2.0))
    dist = compose_receptions_distribution(
        targets,
        catch_rate_mean=0.5,
        concentration=1_000_000.0,
        seed_parts=("hand_example",),
        samples=20000,
    )

    assert dist.mean == pytest.approx(1.0, abs=0.05)
    assert dist.prob_over(1.5) == pytest.approx(0.25, abs=0.03)
