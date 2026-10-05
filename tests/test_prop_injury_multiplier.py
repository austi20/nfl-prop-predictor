from __future__ import annotations

import pandas as pd
import pytest

from api.schemas import PropEvaluationRequest
from api.services import evaluation_service as svc
from api.services import fantasy_service
from api.settings import AppSettings
from data import injuries


class _RecordingDist:
    """Remembers which line it was priced at."""

    mean = 15.0
    std = 4.0
    dist_type = "normal"

    def __init__(self):
        self.priced_at: list[float] = []

    def prob_over(self, line: float) -> float:
        self.priced_at.append(line)
        return 0.5


class _FakeModel:
    def __init__(self, dist):
        self._dist = dist

    def predict(self, **_kwargs):
        return {stat: self._dist for stat in svc.STAT_SPECS}


def _request(player_id: str, stat: str) -> PropEvaluationRequest:
    return PropEvaluationRequest(
        player_id=player_id, season=2026, week=5, stat=stat, line=14.0,
        over_odds=-110, under_odds=-110, opponent_team="SF",
    )


@pytest.fixture
def priced(monkeypatch):
    """Run evaluate_prop with stubbed models; return the line it priced at."""
    weekly = pd.DataFrame(columns=["player_id", "season", "week", "position"])
    monkeypatch.setattr(svc, "scoring_weekly", lambda settings, season: weekly)
    monkeypatch.setattr(
        injuries, "player_statuses", lambda season, week: {"hurt": ("questionable", "ESPN injury feed")}
    )

    def run(player_id: str, stat: str, fantasy_multiplier: float | None) -> float:
        glm_dist, fantasy_dist = _RecordingDist(), _RecordingDist()
        monkeypatch.setattr(svc, "_model_bundle", lambda *_a: {name: _FakeModel(glm_dist) for name in ("qb", "rb", "wr_te")})
        projection = None if fantasy_multiplier is None else (fantasy_dist, fantasy_multiplier)
        monkeypatch.setattr(fantasy_service, "prop_stat_projection", lambda settings, **_kw: projection)
        svc.evaluate_prop(AppSettings(use_future_row=False), _request(player_id, stat))
        return (glm_dist.priced_at + fantasy_dist.priced_at)[-1]

    return run


def test_volume_prop_gets_the_injury_haircut(priced):
    q = injuries.output_multiplier("questionable")
    assert priced("hurt", "carries", 1.0) == pytest.approx(14.0 / q)
    assert priced("healthy", "carries", 1.0) == pytest.approx(14.0)


def test_scoring_stat_is_not_scaled_twice(priced):
    # Fantasy multiplier already holds the injury factor.
    assert priced("hurt", "rushing_yards", 0.5) == pytest.approx(28.0)
    assert priced("hurt", "interceptions", 0.5) == pytest.approx(28.0)


def test_raw_glm_fallback_gets_the_injury_haircut(priced):
    q = injuries.output_multiplier("questionable")
    assert priced("hurt", "rushing_yards", None) == pytest.approx(14.0 / q)
