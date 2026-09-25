from __future__ import annotations

import pandas as pd
import pytest

from data import injuries


@pytest.fixture(autouse=True)
def _clear_caches():
    injuries._season_report.cache_clear()
    injuries._espn_report.cache_clear()
    injuries._live_week.cache_clear()
    yield
    injuries._season_report.cache_clear()
    injuries._espn_report.cache_clear()
    injuries._live_week.cache_clear()


@pytest.mark.parametrize(
    "report, practice, note, expected",
    [
        ("Out", "Did Not Participate In Practice", "Knee", "out"),
        ("Injured Reserve", None, None, "out"),
        ("Doubtful", "Limited Participation in Practice", "Hamstring", "doubtful"),
        ("Questionable", "Full Participation in Practice", "Ankle", "questionable"),
        (None, "Did Not Participate In Practice", "Glute", "dnp_injured"),
        (None, "Did Not Participate In Practice", "Not injury related - resting player", "dnp_resting"),
        (None, "Limited Participation in Practice", "Concussion", "limited"),
        (None, "Full Participation in Practice", "Knee", "full"),
        (None, None, None, "not_reported"),
    ],
)
def test_report_row_classifies(report, practice, note, expected):
    assert injuries.classify(report, practice, note) == expected


def test_doubtful_is_treated_as_out():
    """Not one of 88 regulars listed doubtful played in 2022-2025."""
    assert injuries.output_multiplier("doubtful") == injuries.output_multiplier("out")
    assert injuries.output_multiplier("out") == injuries._OUT_FLOOR


def test_questionable_costs_a_real_share_of_output():
    # Plays 69% of the time and at ~84% of normal volume when he does.
    assert 0.5 < injuries.output_multiplier("questionable") < 0.65
    assert injuries.output_multiplier("not_reported") == 1.0


def test_questionable_stays_below_the_promotion_threshold():
    """A questionable starter plays more often than not, so his backup must not
    inherit the job."""
    assert injuries.absence_probability("Questionable") < injuries.ABSENCE_THRESHOLD
    assert injuries.absence_probability("Doubtful") >= injuries.ABSENCE_THRESHOLD
    assert injuries.absence_probability(None, "Did Not Participate In Practice", "Glute") >= injuries.ABSENCE_THRESHOLD


def _row(gsis, week, report=None, practice=None, note=None) -> dict:
    return {"gsis_id": gsis, "week": week, "report_status": report,
            "practice_status": practice, "practice_primary_injury": note}


def _patch(monkeypatch, frame: pd.DataFrame, espn: dict, live_week: int = 3):
    monkeypatch.setattr(injuries, "_season_report", lambda season, bucket: frame)
    monkeypatch.setattr(injuries, "_espn_report", lambda bucket: espn)
    monkeypatch.setattr(injuries, "_live_week", lambda season, bucket: live_week)


def test_only_this_weeks_rows_count(monkeypatch):
    """Last week's Questionable says nothing about Sunday."""
    frame = pd.DataFrame([_row("p1", 2, "Questionable")])
    _patch(monkeypatch, frame, {})

    assert injuries.player_statuses(2026, 3) == {}


def test_espn_designation_beats_a_practice_only_row(monkeypatch):
    frame = pd.DataFrame([_row("nacua", 3, None, "Did Not Participate In Practice", "Hip")])
    _patch(monkeypatch, frame, {"nacua": ("doubtful", "McVay: doubtful")})

    status, note = injuries.player_statuses(2026, 3)["nacua"]
    assert status == "doubtful"
    assert "McVay" in note


def test_the_more_severe_designation_wins(monkeypatch):
    frame = pd.DataFrame([_row("p1", 3, "Out")])
    _patch(monkeypatch, frame, {"p1": ("questionable", "stale")})

    assert injuries.player_statuses(2026, 3)["p1"][0] == "out"


def test_espn_only_applies_to_the_week_in_progress(monkeypatch):
    _patch(monkeypatch, pd.DataFrame(), {"p1": ("out", "")}, live_week=3)

    assert injuries.player_statuses(2026, 2) == {}
    assert injuries.player_statuses(2026, 3)["p1"][0] == "out"


def test_unavailable_selects_only_players_over_the_threshold(monkeypatch):
    frame = pd.DataFrame([
        _row("out", 3, "Out"),
        _row("dnp", 3, None, "Did Not Participate In Practice", "Glute"),
        _row("resting", 3, None, "Did Not Participate In Practice", "Not injury related - resting player"),
        _row("quest", 3, "Questionable"),
    ])
    _patch(monkeypatch, frame, {"doubt": ("doubtful", "")})

    assert injuries.unavailable(2026, 3) == frozenset({"out", "dnp", "doubt"})


def test_a_missing_report_leaves_everyone_available(monkeypatch):
    _patch(monkeypatch, pd.DataFrame(), {})

    assert injuries.unavailable(2026, 3) == frozenset()
    assert injuries.player_statuses(2026, 3) == {}


def test_espn_athlete_id_comes_from_the_player_card_link():
    entry = {"athlete": {"links": [{"href": "https://www.espn.com/nfl/player/_/id/4431611/caleb-williams"}]}}
    assert injuries._espn_athlete_id(entry) == "4431611"
    assert injuries._espn_athlete_id({"athlete": {}}) == ""
