"""Draft capital - the only signal separating two rookies with no NFL snaps.

A first-round running back listed RB1 and an undrafted free agent listed RB1
have identical NFL history (none) and identical depth rank. Draft position is
what the league itself believed about them, and it is the best available prior.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from data.nflverse_loader import load_draft_picks

# Round -> multiplier on the rank-conditioned baseline. Deliberately gentle: the
# depth slot already carries most of the signal, and draft position is a prior
# about talent, not a promise of usage.
_ROUND_MULTIPLIER = {1: 1.15, 2: 1.08, 3: 1.02, 4: 0.97, 5: 0.93, 6: 0.90, 7: 0.88}
_UNDRAFTED_MULTIPLIER = 0.85


def _picks_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    try:
        return load_draft_picks(list(seasons))
    except Exception:  # noqa: BLE001 - an unpublished class must not brick projections
        return pd.DataFrame(columns=["season", "round", "pick", "gsis_id"])


@lru_cache(maxsize=4096)
def draft_capital(gsis_id: str, seasons: tuple[int, ...]) -> tuple[int, int] | None:
    """(round, pick) for a drafted player, else None."""
    if not gsis_id:
        return None
    picks = _picks_frame(seasons)
    if picks.empty or "gsis_id" not in picks.columns:
        return None
    rows = picks[picks["gsis_id"].astype(str) == gsis_id]
    if rows.empty:
        return None
    row = rows.sort_values("season").iloc[-1]
    try:
        return int(row["round"]), int(row["pick"])
    except (TypeError, ValueError):
        return None


def capital_multiplier(capital: tuple[int, int] | None) -> float:
    """Scale a rookie's baseline projection by what the draft said about him."""
    if capital is None:
        return _UNDRAFTED_MULTIPLIER
    return _ROUND_MULTIPLIER.get(int(capital[0]), _UNDRAFTED_MULTIPLIER)
