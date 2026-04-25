"""Tests for data/stadium_coords.py.

Fast tests check internal consistency, tz validity, and coverage against the
known set of NFL home teams 2018-2025. Slow tests (marked @pytest.mark.slow)
hit nfl_data_py for the actual schedule frame.
"""

from __future__ import annotations

import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.stadium_coords import (
    FIXED_DOME_TEAMS,
    RETRACTABLE_TEAMS,
    STADIUMS,
    Stadium,
    is_indoor,
)


# Every team abbreviation that appears as home_team in nflverse schedules
# 2018-2025. OAK 2018-2019, LV 2020+; LAR/LAC throughout (LA Rams have
# been LAR since 2016, Chargers LAC since 2017). SD/STL did not appear
# in this window but legacy keys exist for safety.
_HOME_TEAMS_2018_2025: frozenset[str] = frozenset({
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB",  "HOU", "IND", "JAX", "KC",  "LAC", "LAR", "LV",  "MIA",
    "MIN", "NE",  "NO",  "NYG", "NYJ", "OAK", "PHI", "PIT", "SEA", "SF",
    "TB",  "TEN", "WAS",
})


class TestSchema:
    def test_stadium_is_frozen(self):
        s = STADIUMS["KC"]
        with pytest.raises(Exception):  # FrozenInstanceError
            s.lat = 0.0  # type: ignore[misc]

    def test_all_keys_are_uppercase_short_codes(self):
        for team in STADIUMS:
            assert team.isupper()
            assert 2 <= len(team) <= 3

    def test_all_stadium_values_are_stadium_instances(self):
        assert all(isinstance(v, Stadium) for v in STADIUMS.values())


class TestCoordinates:
    def test_lat_lon_in_continental_us_range(self):
        for team, s in STADIUMS.items():
            assert 24.0 <= s.lat <= 49.0, f"{team} lat out of range: {s.lat}"
            assert -125.0 <= s.lon <= -66.0, f"{team} lon out of range: {s.lon}"

    def test_altitude_non_negative_and_realistic(self):
        for team, s in STADIUMS.items():
            assert 0 <= s.altitude_ft <= 6000, f"{team} altitude unrealistic: {s.altitude_ft}"

    def test_denver_is_mile_high(self):
        # Sanity check on the one altitude that materially affects passing.
        assert STADIUMS["DEN"].altitude_ft >= 5000


class TestTimeZones:
    def test_all_tz_strings_resolve(self):
        for team, s in STADIUMS.items():
            try:
                ZoneInfo(s.tz)
            except ZoneInfoNotFoundError:
                pytest.fail(f"{team} has invalid IANA tz: {s.tz!r}")

    def test_arizona_uses_phoenix_no_dst(self):
        assert STADIUMS["ARI"].tz == "America/Phoenix"

    def test_west_coast_teams_use_los_angeles(self):
        for team in ("LAR", "LAC", "SF", "SEA", "LV"):
            assert STADIUMS[team].tz == "America/Los_Angeles", f"{team} tz: {STADIUMS[team].tz}"


class TestRoofClassification:
    def test_fixed_dome_set_matches_dataclass_flags(self):
        derived = frozenset(t for t, s in STADIUMS.items() if s.is_fixed_dome)
        assert FIXED_DOME_TEAMS == derived

    def test_retractable_set_matches_dataclass_flags(self):
        derived = frozenset(t for t, s in STADIUMS.items() if s.is_retractable)
        assert RETRACTABLE_TEAMS == derived

    def test_no_team_is_both_fixed_and_retractable(self):
        for team, s in STADIUMS.items():
            assert not (s.is_fixed_dome and s.is_retractable), f"{team} cannot be both"

    def test_known_fixed_domes(self):
        # Always-closed roofs.
        for team in ("DET", "LV", "MIN", "NO"):
            assert STADIUMS[team].is_fixed_dome, f"{team} should be fixed dome"

    def test_known_retractables(self):
        # Open/close possible; treated as indoor for backfill.
        for team in ("ARI", "ATL", "DAL", "HOU", "IND"):
            assert STADIUMS[team].is_retractable, f"{team} should be retractable"

    def test_known_open_air(self):
        for team in ("BUF", "GB", "CHI", "KC", "NE", "NYG", "NYJ", "PHI", "SEA"):
            s = STADIUMS[team]
            assert not s.is_fixed_dome and not s.is_retractable, f"{team} should be outdoor"

    def test_sofi_treated_as_outdoor(self):
        # Fixed translucent roof but open sides; weather affects play.
        for team in ("LAR", "LAC"):
            s = STADIUMS[team]
            assert not s.is_fixed_dome
            assert not s.is_retractable


class TestIsIndoor:
    def test_indoor_true_for_fixed_domes(self):
        for team in FIXED_DOME_TEAMS:
            assert is_indoor(team) is True

    def test_indoor_true_for_retractables(self):
        for team in RETRACTABLE_TEAMS:
            assert is_indoor(team) is True

    def test_indoor_false_for_open_air(self):
        for team in ("BUF", "GB", "KC", "NE", "PHI", "PIT", "SEA"):
            assert is_indoor(team) is False

    def test_indoor_raises_on_unknown_team(self):
        with pytest.raises(KeyError):
            is_indoor("ZZZ")


class TestCoverage:
    def test_known_2018_2025_home_teams_have_entries(self):
        missing = _HOME_TEAMS_2018_2025 - set(STADIUMS.keys())
        assert not missing, f"Missing stadium entries: {sorted(missing)}"

    def test_includes_pre_2018_legacy_keys(self):
        # Legacy abbreviations for franchises that relocated within nflverse.
        # SD and STL are kept for safety when extending to pre-2018 backfills.
        for legacy in ("OAK", "SD", "STL"):
            assert legacy in STADIUMS, f"Legacy key {legacy} missing"


@pytest.mark.slow
def test_slow_actual_schedule_home_teams_covered():
    """Verifies every home_team in real 2018-2025 nflverse schedules has an entry."""
    from data.nflverse_loader import load_schedules

    df = load_schedules(list(range(2018, 2026)))
    actual = set(df["home_team"].dropna().unique())
    missing = actual - set(STADIUMS.keys())
    assert not missing, f"Real-schedule teams missing from STADIUMS: {sorted(missing)}"
