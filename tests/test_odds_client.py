from __future__ import annotations

from unittest.mock import Mock

import pytest

from data.odds_client import OddsApiClient


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("THE_ODDS_API_KEY", raising=False)
    with pytest.raises(ValueError):
        OddsApiClient()


def test_historical_events_builds_expected_request(monkeypatch):
    response = Mock()
    response.json.return_value = {"data": []}
    response.raise_for_status.return_value = None

    session = Mock()
    session.get.return_value = response

    client = OddsApiClient(api_key="secret", session=session)
    payload = client.historical_events(
        sport="americanfootball_nfl",
        date="2025-09-07T17:00:00Z",
        event_ids=["evt1", "evt2"],
    )

    assert payload == {"data": []}
    session.get.assert_called_once()
    _, kwargs = session.get.call_args
    assert kwargs["params"]["apiKey"] == "secret"
    assert kwargs["params"]["eventIds"] == "evt1,evt2"


def test_historical_event_odds_builds_expected_request():
    response = Mock()
    response.json.return_value = {"data": {"id": "evt1"}}
    response.raise_for_status.return_value = None

    session = Mock()
    session.get.return_value = response

    client = OddsApiClient(api_key="secret", session=session)
    payload = client.historical_event_odds(
        sport="americanfootball_nfl",
        event_id="evt1",
        date="2025-09-07T17:00:00Z",
        markets=["player_pass_yds", "player_rush_yds"],
        bookmakers=["draftkings"],
    )

    assert payload == {"data": {"id": "evt1"}}
    _, kwargs = session.get.call_args
    assert kwargs["params"]["markets"] == "player_pass_yds,player_rush_yds"
    assert kwargs["params"]["bookmakers"] == "draftkings"
