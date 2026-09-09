from __future__ import annotations

import pytest

import data.news as news
from api.services.fantasy_service import _news_factor


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    news._team_headlines_bucketed.cache_clear()
    news._all_articles.cache_clear()
    yield
    news._team_headlines_bucketed.cache_clear()
    news._all_articles.cache_clear()


def _headlines(monkeypatch, mapping: dict[str, list[str]]):
    monkeypatch.setattr(
        "data.news.team_headlines",
        lambda team: tuple(mapping.get(team.upper(), [])),
    )


def test_neutral_without_headlines(monkeypatch):
    _headlines(monkeypatch, {})
    fac = _news_factor(team="KC", opponent_team="DEN", position="WR")
    assert not fac.applied and fac.name == "news"


def test_neutral_when_headlines_carry_no_signal(monkeypatch):
    _headlines(monkeypatch, {"KC": ["chiefs unveil new alternate uniforms for week 1."]})
    assert not _news_factor(team="KC", opponent_team="DEN", position="WR").applied


def test_own_offense_downgrade_on_qb_shakeup(monkeypatch):
    _headlines(monkeypatch, {"NYJ": [
        "kevin o'connell reveals the backup quarterback will start sunday.",
    ]})
    fac = _news_factor(team="NYJ", opponent_team="BUF", position="WR")
    assert fac.applied and fac.multiplier < 1.0 and "own-offense" in fac.reason


def test_opponent_defense_boost_on_dc_firing(monkeypatch):
    _headlines(monkeypatch, {"CAR": ["panthers fire defensive coordinator after blowout."]})
    fac = _news_factor(team="ATL", opponent_team="CAR", position="RB")
    assert fac.applied and fac.multiplier > 1.0 and "opponent defense" in fac.reason


def test_espn_article_team_extraction():
    art = {"categories": [{"team": {"abbreviation": "min"}}, {"type": "guid"}]}
    assert news._article_teams(art) == {"MIN"}
