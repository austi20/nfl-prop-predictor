"""Future-game feature pipeline (Phase G.5).

Builds a single-row feature dict for an unplayed game so that `model.predict()`
can score it against the upcoming opponent rather than the latest historical row.

Approach: append a synthetic placeholder row (zeros for stat columns; correct
player_id / season / week / recent_team / opponent_team) to the historical
weekly frame, then run the position's existing `_build_features` over the
augmented frame. Because every rolling/lagging feature in `_build_features`
applies `shift(1)` before reducing, the placeholder's zeros never leak into
its own feature row — the resulting features reflect prior-week history for
the player and prior-week rolling context for the team / opponent.

This keeps the feature contract identical to training and avoids a parallel
implementation of rolling/lagging logic.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

_QB_STATS = ["passing_yards", "passing_tds", "interceptions", "completions"]
_RB_STATS = ["rushing_yards", "carries", "rushing_tds"]
_WR_TE_STATS = ["receptions", "receiving_yards", "receiving_tds"]


def _builder_for(position: str) -> tuple[Callable, list[str]]:
    """Return (builder_fn, accepted_positions) for a position group."""
    if position == "QB":
        from models.qb import _build_features as build_qb

        return build_qb, ["QB"]
    if position == "RB":
        from models.rb import _build_features as build_rb

        return build_rb, ["RB"]
    if position in ("WR", "TE"):
        from models.wr_te import _build_features as build_wr

        return build_wr, ["WR", "TE"]
    raise ValueError(f"Unsupported position: {position!r}")


def _placeholder_row(
    *,
    weekly: pd.DataFrame,
    player_id: str,
    season: int,
    week: int,
    position: str,
    recent_team: str,
    opponent_team: str,
    is_home: bool | None,
    weather: dict[str, Any] | None,
) -> dict[str, Any]:
    """Construct a stat-zero placeholder row matching weekly's schema."""
    row: dict[str, Any] = {col: 0.0 for col in weekly.columns}
    row["player_id"] = player_id
    row["season"] = int(season)
    row["week"] = int(week)
    row["position"] = position
    row["recent_team"] = recent_team
    row["opponent_team"] = opponent_team

    # Pull a player_name from history if available (purely cosmetic for the dict).
    name_match = weekly[weekly["player_id"] == player_id]
    if "player_name" in weekly.columns and not name_match.empty:
        row["player_name"] = name_match["player_name"].iloc[-1]

    if is_home is not None:
        row["is_home"] = 1.0 if is_home else 0.0

    if weather:
        for key, value in weather.items():
            if key in weekly.columns or key in {
                "temp_f",
                "wind_mph",
                "wind_dir_deg",
                "precip_in",
                "weather_code",
                "indoor",
            }:
                row[key] = value
    return row


def build_upcoming_row(
    player_id: str,
    season: int,
    week: int,
    *,
    position: str,
    opponent_team: str,
    recent_team: str,
    is_home: bool | None = None,
    weather: dict[str, Any] | None = None,
    weekly: pd.DataFrame | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Build a feature dict for an unplayed game.

    Args:
        player_id: Target player.
        season, week: Target (future or replay) game.
        position: One of "QB", "RB", "WR", "TE". Selects the feature builder.
        opponent_team: Defense the player will face this game.
        recent_team: Player's own team for this game.
        is_home: Optional override for the `is_home` flag (default 0.5 baseline).
        weather: Optional dict with any of {temp_f, wind_mph, wind_dir_deg,
            precip_in, weather_code, indoor}; passed through unchanged.
        weekly: Optional pre-loaded weekly frame. When None, calls
            `data.nflverse_loader.load_weekly_with_weather([season])`.
        force_refresh: Forwarded to the loader when `weekly` is None.

    Returns:
        Dict whose keys are a strict superset of the columns produced by the
        position's `_build_features`. Safe to feed to `model.predict(future_row=...)`.
    """
    if weekly is None:
        from data.nflverse_loader import load_weekly_with_weather

        weekly = load_weekly_with_weather([season], force_refresh=force_refresh)

    weekly = weekly.copy()
    builder, accepted_positions = _builder_for(position)

    # Filter to position's universe (matches what each model's fit() does).
    if "position" in weekly.columns:
        weekly = weekly[weekly["position"].isin(accepted_positions)].copy()

    placeholder = _placeholder_row(
        weekly=weekly,
        player_id=player_id,
        season=season,
        week=week,
        position=position,
        recent_team=recent_team,
        opponent_team=opponent_team,
        is_home=is_home,
        weather=weather,
    )

    # Drop any pre-existing row at the same (player, season, week) to keep the
    # placeholder authoritative — protects against rebuilding a row that already
    # has stats recorded.
    mask = ~(
        (weekly["player_id"] == player_id)
        & (weekly["season"] == int(season))
        & (weekly["week"] == int(week))
    )
    weekly = weekly[mask]

    augmented = pd.concat(
        [weekly, pd.DataFrame([placeholder])],
        ignore_index=True,
    )

    feat_df, _ = builder(augmented)

    target_mask = (
        (feat_df["player_id"] == player_id)
        & (feat_df["season"] == int(season))
        & (feat_df["week"] == int(week))
    )
    target = feat_df[target_mask]
    if target.empty:
        raise RuntimeError(
            "build_upcoming_row failed to locate placeholder row after feature build "
            f"(player_id={player_id!r}, season={season}, week={week})"
        )
    return target.iloc[-1].to_dict()
