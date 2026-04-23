from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from api.server import create_app
from api.settings import AppSettings
from api.services.replay_service import load_replay_artifacts


def _settings() -> AppSettings:
    return AppSettings(
        docs_dir=Path("docs"),
        sample_props_path=Path("docs") / "sample_replay_props_2024.csv",
        default_train_years=tuple(range(2015, 2024)),
        default_replay_years=(2024,),
        default_max_parlay_candidates=10,
    )


def _client() -> TestClient:
    settings = _settings()
    load_replay_artifacts.cache_clear()
    return TestClient(create_app(settings))


def test_health_endpoint_reports_replay_status():
    client = _client()
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["replay_artifacts_available"] is True
    assert payload["sample_props_path"].endswith("sample_replay_props_2024.csv")


def test_slate_endpoint_returns_replay_backed_sections():
    client = _client()
    response = client.get("/api/slate")
    assert response.status_code == 200
    payload = response.json()
    assert payload["season_label"] == "2024"
    assert "policy" in payload
    assert "validation" in payload
    assert "singles" in payload
    assert "parlays" in payload
    assert payload["top_picks"]
    assert payload["top_parlays"]
    assert "week" in payload["breakdowns"]


def test_replay_summary_endpoint_returns_picks_and_breakdowns():
    client = _client()
    response = client.get("/api/replay/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["picks"]
    assert payload["parlay_rows"]
    assert "stat" in payload["breakdowns"]
    assert payload["validation"]["selected_rows"] >= 1


def test_player_detail_endpoint_returns_recent_games():
    client = _client()
    response = client.get("/api/players/00-0033873")
    assert response.status_code == 200
    payload = response.json()
    assert payload["player_id"] == "00-0033873"
    assert payload["player_name"] == "P.Mahomes"
    assert payload["recent_games"]


def test_prop_evaluation_endpoint_returns_normalized_pick():
    client = _client()
    response = client.post(
        "/api/props/evaluate",
        json={
            "player_id": "00-0033873",
            "season": 2024,
            "week": 10,
            "stat": "passing_tds",
            "line": 0.5,
            "over_odds": -180,
            "under_odds": 140,
            "opponent_team": "DEN",
            "book": "demo_book",
            "game_id": "2024_10_KC_DEN",
            "recent_team": "KC",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["pick"]["player_id"] == "00-0033873"
    assert payload["pick"]["distribution"]["dist_type"]
    assert payload["pick"]["over"]["side"] == "over"
    assert payload["selected_side"] in {"over", "under"}


def test_parlay_build_endpoint_reuses_pick_shape():
    client = _client()
    first = client.post(
        "/api/props/evaluate",
        json={
            "player_id": "00-0033873",
            "season": 2024,
            "week": 10,
            "stat": "passing_tds",
            "line": 0.5,
            "over_odds": -180,
            "under_odds": 140,
            "opponent_team": "DEN",
            "book": "demo_book",
            "game_id": "2024_10_KC_DEN",
            "recent_team": "KC",
        },
    ).json()["pick"]
    second = client.post(
        "/api/props/evaluate",
        json={
            "player_id": "00-0036223",
            "season": 2024,
            "week": 10,
            "stat": "carries",
            "line": 22.5,
            "over_odds": 125,
            "under_odds": -150,
            "opponent_team": "BUF",
            "book": "demo_book",
            "game_id": "2024_10_IND_BUF",
            "recent_team": "IND",
        },
    ).json()["pick"]

    response = client.post(
        "/api/parlays/build",
        json={
            "picks": [first, second],
            "legs": 2,
            "max_candidates": 5,
            "same_game_penalty": 0.97,
            "same_team_penalty": 0.985,
            "stake": 1.0,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["parlays"]
    assert payload["summary"]["n_parlays"] >= 1
