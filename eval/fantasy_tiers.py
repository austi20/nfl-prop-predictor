"""Start/sit tiers for a fantasy board.

A numbered list tells you Bijan is RB3; it does not tell you whether RB18 and
RB19 are the same decision. Tiers answer that: players are cut into six
start/sit groups whose boundaries are anchored on league starter demand and
then nudged to the nearest real drop-off in projected points, so a tier break
lands in a gap rather than between two players separated by 0.1 points.

Every ranked list on the board (each position, the flex pool, the cumulative
board) is tiered independently against its own starter demand.
"""
from __future__ import annotations

from collections.abc import Sequence

# The board is tiered for a standard 12-team league: QB/RB/RB/WR/WR/WR/TE/FLEX.
LEAGUE_TEAMS = 12
_STARTER_SLOTS: dict[str, int] = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
_FLEX_SLOTS = 1

TIER_KEYS: tuple[str, ...] = (
    "start_no_doubt",
    "feels_good",
    "w_flex",
    "shaky_flex",
    "avoid",
    "do_not_play",
)

TIER_LABELS: dict[str, str] = {
    "start_no_doubt": "Start no doubt",
    "feels_good": "Feels good",
    "w_flex": "W Flex",
    "shaky_flex": "Shakey Flex",
    "avoid": "Avoid",
    "do_not_play": "Do Not Play",
}

# Tier boundaries as a multiple of the list's starter demand. A 12-team league
# starts 24 RBs, so RB1-12 are locks, RB13-24 are starters, RB25-30 are flex
# plays, and it falls away from there.
_TIER_CUTS: tuple[tuple[float, str], ...] = (
    (0.50, "start_no_doubt"),
    (1.00, "feels_good"),
    (1.25, "w_flex"),
    (1.60, "shaky_flex"),
    (2.20, "avoid"),
)

# How far a boundary may slide to land on a scoring drop-off, as a fraction of
# starter demand. Wide enough to find a real gap, tight enough that a tier still
# means what its name says.
_SNAP_FRACTION = 0.15


def starter_demand(list_key: str) -> int:
    """Starting slots a 12-team league fills from this list."""
    key = list_key.upper()
    if key in _STARTER_SLOTS:
        return LEAGUE_TEAMS * _STARTER_SLOTS[key]
    if key == "FLEX":
        # RB/WR/TE compete for their own slots plus the flex spot.
        return LEAGUE_TEAMS * (_STARTER_SLOTS["RB"] + _STARTER_SLOTS["WR"] + _STARTER_SLOTS["TE"] + _FLEX_SLOTS)
    # Cumulative board: every startable slot in the league.
    return LEAGUE_TEAMS * (sum(_STARTER_SLOTS.values()) + _FLEX_SLOTS)


def _snap(boundary: int, points: Sequence[float], window: int, taken: int) -> int:
    """Slide ``boundary`` (a 1-based count of players above the cut) to the
    largest points drop within ``window``, never above the previous cut."""
    lo = max(taken + 1, boundary - window)
    hi = min(len(points) - 1, boundary + window)
    if hi < lo:
        return min(boundary, len(points))

    # A cut after k players sits in the gap between points[k-1] and points[k].
    def gap_at(k: int) -> float:
        return float(points[k - 1]) - float(points[k])

    # Start from the nominal rank and move only for a strictly deeper gap, so a
    # flat list keeps its rank-based boundaries.
    best = min(max(boundary, lo), hi)
    best_gap = gap_at(best)
    for k in range(lo, hi + 1):
        if gap_at(k) > best_gap:
            best, best_gap = k, gap_at(k)
    return best


def assign_tiers(points: Sequence[float], starters: int) -> list[str]:
    """Tier key per player for a list already sorted best-first."""
    n = len(points)
    if n == 0:
        return []
    starters = max(1, starters)
    window = max(1, round(starters * _SNAP_FRACTION))

    tiers = ["do_not_play"] * n
    taken = 0
    for ratio, key in _TIER_CUTS:
        if taken >= n:
            break
        boundary = _snap(round(starters * ratio), points, window, taken)
        boundary = min(max(boundary, taken), n)
        for i in range(taken, boundary):
            tiers[i] = key
        taken = boundary
    return tiers
