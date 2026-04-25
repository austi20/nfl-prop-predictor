"""Stadium coordinate and roof-type table for weather backfill.

Authoritative split of fixed-dome / retractable / open-air venues, with lat/lon
and IANA tz for kickoff-hour resolution. Used by `scripts/backfill_weather.py`
to decide which games skip the Open-Meteo Archive call (indoor) vs. fetch
weather (outdoor or open-roof).

`data/nflverse_loader.py::DOME_TEAMS` conflates fixed and retractable in a
single set for back-compat. This module is the authoritative split; callers
that need to distinguish the two should import from here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stadium:
    lat: float
    lon: float
    altitude_ft: int
    is_fixed_dome: bool
    is_retractable: bool
    tz: str  # IANA timezone identifier


# Current 32 teams (as of 2025 season) plus legacy abbreviations for franchises
# that relocated within nflverse history: OAK -> LV in 2020, SD -> LAC in 2017,
# STL -> LAR in 2016. Coordinates point at the team's actual home stadium
# during the era the legacy abbreviation was in use, so weather backfill for
# pre-2020 OAK games hits the Oakland Coliseum, not Allegiant.
#
# SoFi Stadium (LAR/LAC) has a fixed translucent ETFE roof but open sides;
# wind and temperature affect play, so it is classified as outdoor for
# weather purposes (matching the existing DOME_TEAMS convention which
# excludes both LA teams).
STADIUMS: dict[str, Stadium] = {
    "ARI": Stadium(33.5276, -112.2626, 1132, False, True,  "America/Phoenix"),
    "ATL": Stadium(33.7553,  -84.4006, 1050, False, True,  "America/New_York"),
    "BAL": Stadium(39.2780,  -76.6227,   36, False, False, "America/New_York"),
    "BUF": Stadium(42.7738,  -78.7870,  614, False, False, "America/New_York"),
    "CAR": Stadium(35.2258,  -80.8528,  740, False, False, "America/New_York"),
    "CHI": Stadium(41.8623,  -87.6167,  596, False, False, "America/Chicago"),
    "CIN": Stadium(39.0954,  -84.5160,  482, False, False, "America/New_York"),
    "CLE": Stadium(41.5061,  -81.6995,  581, False, False, "America/New_York"),
    "DAL": Stadium(32.7473,  -97.0945,  600, False, True,  "America/Chicago"),
    "DEN": Stadium(39.7439, -105.0201, 5280, False, False, "America/Denver"),
    "DET": Stadium(42.3400,  -83.0456,  600, True,  False, "America/Detroit"),
    "GB":  Stadium(44.5013,  -88.0622,  640, False, False, "America/Chicago"),
    "HOU": Stadium(29.6847,  -95.4107,   49, False, True,  "America/Chicago"),
    "IND": Stadium(39.7601,  -86.1639,  717, False, True,  "America/Indiana/Indianapolis"),
    "JAX": Stadium(30.3239,  -81.6373,   16, False, False, "America/New_York"),
    "KC":  Stadium(39.0489,  -94.4839,  750, False, False, "America/Chicago"),
    "LAC": Stadium(33.9534, -118.3387,  102, False, False, "America/Los_Angeles"),
    "LAR": Stadium(33.9534, -118.3387,  102, False, False, "America/Los_Angeles"),
    "LV":  Stadium(36.0908, -115.1830, 2030, True,  False, "America/Los_Angeles"),
    "MIA": Stadium(25.9580,  -80.2389,    8, False, False, "America/New_York"),
    "MIN": Stadium(44.9737,  -93.2581,  830, True,  False, "America/Chicago"),
    "NE":  Stadium(42.0909,  -71.2643,  213, False, False, "America/New_York"),
    "NO":  Stadium(29.9508,  -90.0811,    5, True,  False, "America/Chicago"),
    "NYG": Stadium(40.8135,  -74.0745,   26, False, False, "America/New_York"),
    "NYJ": Stadium(40.8135,  -74.0745,   26, False, False, "America/New_York"),
    "PHI": Stadium(39.9008,  -75.1675,   39, False, False, "America/New_York"),
    "PIT": Stadium(40.4468,  -80.0158,  728, False, False, "America/New_York"),
    "SEA": Stadium(47.5952, -122.3316,    0, False, False, "America/Los_Angeles"),
    "SF":  Stadium(37.4030, -121.9700,   23, False, False, "America/Los_Angeles"),
    "TB":  Stadium(27.9759,  -82.5033,   36, False, False, "America/New_York"),
    "TEN": Stadium(36.1665,  -86.7713,  449, False, False, "America/Chicago"),
    "WAS": Stadium(38.9078,  -76.8645,  200, False, False, "America/New_York"),

    # Legacy abbreviations.
    "OAK": Stadium(37.7517, -122.2008,    0, False, False, "America/Los_Angeles"),  # Oakland Coliseum, 2018-2019
    "SD":  Stadium(32.7831, -117.1196,   67, False, False, "America/Los_Angeles"),  # SDCCU Stadium, through 2016
    "STL": Stadium(38.6328,  -90.1885,  466, True,  False, "America/Chicago"),      # Edward Jones Dome, through 2015
}

FIXED_DOME_TEAMS:  frozenset[str] = frozenset(t for t, s in STADIUMS.items() if s.is_fixed_dome)
RETRACTABLE_TEAMS: frozenset[str] = frozenset(t for t, s in STADIUMS.items() if s.is_retractable)


def is_indoor(team: str) -> bool:
    """True for fixed domes and retractable-roof venues.

    Retractables count as indoor for the weather-backfill skip decision because
    nflverse schedules do not record game-day roof state — assuming open would
    inject phantom outdoor weather into ~30% of those games.
    """
    s = STADIUMS[team]
    return s.is_fixed_dome or s.is_retractable
