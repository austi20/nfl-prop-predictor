from __future__ import annotations

import pandas as pd
import pytest

from data import injuries


@pytest.fixture(autouse=True)
def _clear_caches():
    injuries._season_report.cache_clear()
    injuries.absence_probabilities.cache_clear()
    yield
    injuries._season_report.cache_clear()
    injuries.absence_probabilities.cache_clear()


@pytest.mark.parametrize(
    "report, practice, note, expected",
    [
        ("Out", "Did Not Participate In Practice", "Knee", injuries._OUT),
        ("Doubtful", "Limited Participation in Practice", "Hamstring", injuries._DOUBTFUL),
        ("Questionable", "Full Participation in Practice", "Ankle", injuries._QUESTIONABLE),
        # No game status filed yet: practice is the only signal.
        (None, "Did Not Participate In Practice", "Glute", injuries._NO_STATUS_DNP_INJURED),
        (None, "Limited Participation in Practice", "Concussion", injuries._NO_STATUS_LIMITED),
        (None, "Full Participation in Practice", "Knee", injuries._NO_STATUS_FULL),
        (None, None, None, injuries._NOT_REPORTED),
    ],
)
def test_designation_maps_to_its_measured_rate(report, practice, note, expected):
    assert injuries.absence_probability(report, practice, note) == expected


def test_a_scheduled_rest_day_is_not_an_injury():
    """A veteran's day off misses 13% of the time, a real knock 59%. Collapsing
    the two would bench half the league's starters every Wednesday."""
    resting = injuries.absence_probability(
        None, "Did Not Participate In Practice", "Not injury related - resting player"
    )
    hurt = injuries.absence_probability(None, "Did Not Participate In Practice", "Glute")

    assert resting == injuries._NO_STATUS_DNP_RESTING
    assert hurt == injuries._NO_STATUS_DNP_INJURED
    assert resting < injuries.ABSENCE_THRESHOLD < hurt


def test_questionable_stays_below_the_promotion_threshold():
    """A questionable starter plays more often than not, so his backup must not
    inherit the job."""
    assert injuries.absence_probability("Questionable", None, None) < injuries.ABSENCE_THRESHOLD


def _report(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_unavailable_selects_only_players_over_the_threshold(monkeypatch):
    frame = _report(
        [
            {"gsis_id": "out", "week": 2, "report_status": "Out",
             "practice_status": None, "practice_primary_injury": None},
            {"gsis_id": "dnp", "week": 2, "report_status": None,
             "practice_status": "Did Not Participate In Practice",
             "practice_primary_injury": "Glute"},
            {"gsis_id": "resting", "week": 2, "report_status": None,
             "practice_status": "Did Not Participate In Practice",
             "practice_primary_injury": "Not injury related - resting player"},
            {"gsis_id": "quest", "week": 2, "report_status": "Questionable",
             "practice_status": None, "practice_primary_injury": None},
            {"gsis_id": "other_week", "week": 3, "report_status": "Out",
             "practice_status": None, "practice_primary_injury": None},
        ]
    )
    monkeypatch.setattr(injuries, "_season_report", lambda season: frame)
    injuries.absence_probabilities.cache_clear()

    assert injuries.unavailable(2026, 2) == frozenset({"out", "dnp"})


def test_a_missing_report_leaves_everyone_available(monkeypatch):
    monkeypatch.setattr(injuries, "_season_report", lambda season: pd.DataFrame())
    injuries.absence_probabilities.cache_clear()

    assert injuries.unavailable(2026, 2) == frozenset()
    assert injuries.absence_probabilities(2026, 2) == {}
