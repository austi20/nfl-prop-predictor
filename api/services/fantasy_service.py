from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from api.schemas import (
    FantasyContextFactor,
    FantasyPredictionRequest,
    FantasyPredictionResponse,
    FantasySummary,
)
from api.settings import AppSettings
from api.services.evaluation_service import _model_bundle, _weekly_cache
from data.nflverse_loader import is_dome
from eval.calibration_pipeline import STAT_SPECS
from eval.fantasy_points import (
    SCORING_PROFILES,
    ScoringMode,
    project_fantasy_points,
    scoring_weights,
    stable_simulation_seed,
)
from models.base import StatDistribution

_RECEIVING_STATS = ("receptions", "receiving_yards", "receiving_tds")
_POSITIVE_SCORING_STATS = tuple(
    stat for stat, weight in SCORING_PROFILES["full_ppr"].items() if weight > 0
)
_MODEL_STATS_BY_POSITION: dict[str, tuple[str, ...]] = {
    "QB": ("passing_yards", "passing_tds", "interceptions"),
    "RB": ("rushing_yards", "rushing_tds"),
    "WR": _RECEIVING_STATS,
    "TE": _RECEIVING_STATS,
}


def _as_scoring_mode(value: str) -> ScoringMode:
    if value not in SCORING_PROFILES:
        raise ValueError(f"Unsupported fantasy scoring mode: {value}")
    return value  # type: ignore[return-value]


def _fantasy_points_from_rows(rows: pd.DataFrame, scoring_mode: ScoringMode) -> pd.Series:
    weights = scoring_weights(scoring_mode)
    total = pd.Series(0.0, index=rows.index)
    for stat, weight in weights.items():
        if stat in rows.columns:
            total = total + rows[stat].fillna(0.0).astype(float) * weight
    return total


def _positive_stats_for_position(position: str) -> list[str]:
    normalized = position.upper().strip()
    if normalized == "QB":
        return ["passing_yards", "passing_tds", "rushing_yards", "rushing_tds"]
    if normalized == "RB":
        return ["rushing_yards", "rushing_tds", *_RECEIVING_STATS]
    if normalized in {"WR", "TE"}:
        return [*_RECEIVING_STATS, "rushing_yards", "rushing_tds"]
    return list(_POSITIVE_SCORING_STATS)


def _receiving_stats_for_position(position: str) -> list[str]:
    normalized = position.upper().strip()
    if normalized == "RB":
        return list(_RECEIVING_STATS)
    if normalized in {"WR", "TE"}:
        return list(_RECEIVING_STATS)
    return []


def _player_rows(weekly: pd.DataFrame, player_id: str) -> pd.DataFrame:
    if "player_id" not in weekly.columns:
        return pd.DataFrame()
    return weekly[weekly["player_id"].astype(str) == str(player_id)].copy()


def _identity_from_weekly(
    weekly: pd.DataFrame,
    request: FantasyPredictionRequest,
) -> dict[str, str]:
    player_rows = _player_rows(weekly, request.player_id)
    identity = {
        "player_name": "",
        "position": request.position.upper().strip(),
        "recent_team": request.recent_team,
        "opponent_team": request.opponent_team,
    }
    if player_rows.empty:
        return identity

    exact = player_rows[
        (player_rows["season"] == request.season)
        & (player_rows["week"] == request.week)
    ].copy()
    prior = player_rows[
        (player_rows["season"] < request.season)
        | (
            (player_rows["season"] == request.season)
            & (player_rows["week"] <= request.week)
        )
    ].copy()
    source = exact if not exact.empty else prior
    if source.empty:
        source = player_rows
    latest = source.sort_values(["season", "week"]).iloc[-1]

    identity["player_name"] = str(latest.get("player_name", ""))
    identity["position"] = identity["position"] or str(latest.get("position", "")).upper().strip()
    identity["recent_team"] = identity["recent_team"] or str(latest.get("recent_team", ""))
    identity["opponent_team"] = identity["opponent_team"] or str(latest.get("opponent_team", ""))
    return identity


def _predict_distributions(
    settings: AppSettings,
    player_id: str,
    season: int,
    week: int,
    opponent_team: str,
    position: str,
) -> dict[str, StatDistribution]:
    train_years = tuple(settings.default_train_years)
    models = _model_bundle(train_years, season)

    distributions: dict[str, StatDistribution] = {}
    for stat in _MODEL_STATS_BY_POSITION.get(position.upper().strip(), ()):
        spec = STAT_SPECS.get(stat)
        if spec is None:
            continue
        model = models[spec.model_name]
        predicted = model.predict(
            player_id=player_id,
            season=season,
            week=week,
            opp_team=opponent_team,
        )
        if stat in predicted:
            distributions[stat] = predicted[stat]
    return distributions


def _neutral_factor(
    name: str,
    label: str,
    reason: str,
    affected_stats: list[str] | None = None,
) -> FantasyContextFactor:
    return FantasyContextFactor(
        name=name,
        label=label,
        multiplier=1.0,
        applied=False,
        affected_stats=affected_stats or [],
        reason=reason,
    )


def _qb_support_factor(
    weekly: pd.DataFrame,
    *,
    season: int,
    week: int,
    team: str,
    position: str,
    scoring_mode: ScoringMode,
) -> FantasyContextFactor:
    affected_stats = _receiving_stats_for_position(position)
    if not affected_stats:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "QB support is only applied to RB/WR/TE receiving components.",
        )
    if not team:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "Team context unavailable, so QB support is neutral.",
            affected_stats,
        )

    prior = weekly[(weekly["season"] == season) & (weekly["week"] < week)].copy()
    if prior.empty or "position" not in prior.columns:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "No prior-season QB form is available before this week.",
            affected_stats,
        )

    qbs = prior[prior["position"].astype(str).str.upper() == "QB"].copy()
    team_qbs = qbs[qbs["recent_team"].astype(str) == team].copy() if "recent_team" in qbs.columns else pd.DataFrame()
    if team_qbs.empty or qbs.empty:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "No matching recent QB production found for this team.",
            affected_stats,
        )

    qbs["fantasy_points"] = _fantasy_points_from_rows(qbs, scoring_mode)
    team_qbs["fantasy_points"] = _fantasy_points_from_rows(team_qbs, scoring_mode)
    team_recent = (
        team_qbs.sort_values(["season", "week"])
        .groupby(["season", "week"], as_index=False)["fantasy_points"]
        .sum()
        .tail(4)["fantasy_points"]
    )
    baseline = qbs["fantasy_points"].mean()
    if team_recent.empty or baseline <= 0:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "QB baseline is unavailable, so receiving components stay neutral.",
            affected_stats,
        )

    ratio = float(team_recent.mean()) / float(baseline)
    multiplier = 1.0
    if ratio < 0.75:
        multiplier = 0.94
    elif ratio < 0.90:
        multiplier = 0.97
    elif ratio > 1.25:
        multiplier = 1.05
    elif ratio > 1.10:
        multiplier = 1.03

    if position.upper().strip() == "RB":
        multiplier = 1.0 + (multiplier - 1.0) * 0.5

    return FantasyContextFactor(
        name="qb_support",
        label="QB support",
        multiplier=multiplier,
        applied=multiplier != 1.0,
        affected_stats=affected_stats,
        reason=f"Team QB fantasy form is {ratio:.0%} of the league QB baseline over recent games.",
    )


def _position_group_factor(
    weekly: pd.DataFrame,
    *,
    season: int,
    week: int,
    team: str,
    position: str,
    scoring_mode: ScoringMode,
) -> FantasyContextFactor:
    normalized = position.upper().strip()
    affected_stats = _positive_stats_for_position(normalized)
    if not team or normalized not in {"QB", "RB", "WR", "TE"}:
        return _neutral_factor(
            "position_group_form",
            "Team position form",
            "Team or position context unavailable, so position-group form is neutral.",
            affected_stats,
        )

    prior = weekly[(weekly["season"] == season) & (weekly["week"] < week)].copy()
    if prior.empty or "position" not in prior.columns or "recent_team" not in prior.columns:
        return _neutral_factor(
            "position_group_form",
            "Team position form",
            "No prior position-group production is available before this week.",
            affected_stats,
        )

    position_rows = prior[prior["position"].astype(str).str.upper() == normalized].copy()
    team_rows = position_rows[position_rows["recent_team"].astype(str) == team].copy()
    if position_rows.empty or team_rows.empty:
        return _neutral_factor(
            "position_group_form",
            "Team position form",
            "No matching position-group production found for this team.",
            affected_stats,
        )

    position_rows["fantasy_points"] = _fantasy_points_from_rows(position_rows, scoring_mode)
    team_rows["fantasy_points"] = _fantasy_points_from_rows(team_rows, scoring_mode)
    team_recent = (
        team_rows.groupby(["season", "week"], as_index=False)["fantasy_points"]
        .sum()
        .sort_values(["season", "week"])
        .tail(4)["fantasy_points"]
    )
    league_weekly = position_rows.groupby(["recent_team", "season", "week"], as_index=False)["fantasy_points"].sum()
    baseline = league_weekly["fantasy_points"].mean()
    if team_recent.empty or baseline <= 0:
        return _neutral_factor(
            "position_group_form",
            "Team position form",
            "Position-group baseline is unavailable.",
            affected_stats,
        )

    ratio = float(team_recent.mean()) / float(baseline)
    multiplier = 1.0
    if ratio < 0.75:
        multiplier = 0.96
    elif ratio > 1.25:
        multiplier = 1.03

    return FantasyContextFactor(
        name="position_group_form",
        label="Team position form",
        multiplier=multiplier,
        applied=multiplier != 1.0,
        affected_stats=affected_stats,
        reason=f"Team {normalized} group production is {ratio:.0%} of the league team-position baseline.",
    )


@lru_cache(maxsize=8)
def _read_cached_injuries(cache_dir: str, season: int) -> pd.DataFrame:
    path = Path(cache_dir) / f"injuries_{season}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def _injury_factor(
    settings: AppSettings,
    *,
    player_id: str,
    season: int,
    week: int,
    position: str,
) -> FantasyContextFactor:
    affected_stats = _positive_stats_for_position(position)
    try:
        injuries = _read_cached_injuries(str(settings.cache_dir), season)
    except Exception:  # noqa: BLE001
        injuries = pd.DataFrame()

    if injuries.empty:
        return _neutral_factor(
            "injury_status",
            "Injury status",
            "No cached injury report is available, so injury impact is neutral.",
            affected_stats,
        )

    id_col = next(
        (col for col in ("player_id", "gsis_id", "player_gsis_id", "nfl_id") if col in injuries.columns),
        None,
    )
    if id_col is None:
        return _neutral_factor(
            "injury_status",
            "Injury status",
            "Cached injury data has no player identifier column.",
            affected_stats,
        )

    matches = injuries[injuries[id_col].astype(str) == str(player_id)].copy()
    if "season" in matches.columns:
        matches = matches[matches["season"].astype(int) == season]
    if "week" in matches.columns:
        matches = matches[matches["week"].astype(int) <= week]
    if matches.empty:
        return _neutral_factor(
            "injury_status",
            "Injury status",
            "No matching injury report found for this player.",
            affected_stats,
        )

    sort_cols = [col for col in ("season", "week") if col in matches.columns]
    latest = matches.sort_values(sort_cols).iloc[-1] if sort_cols else matches.iloc[-1]
    status_text = " ".join(
        str(latest.get(col, ""))
        for col in (
            "game_status",
            "report_status",
            "practice_status",
            "status",
            "injury_report_status",
        )
        if col in latest.index
    ).lower()

    multiplier = 1.0
    if "out" in status_text:
        multiplier = 0.20
    elif "doubtful" in status_text:
        multiplier = 0.55
    elif "questionable" in status_text:
        multiplier = 0.90
    elif "did not practice" in status_text or "limited" in status_text or "dnp" in status_text:
        multiplier = 0.94

    return FantasyContextFactor(
        name="injury_status",
        label="Injury status",
        multiplier=multiplier,
        applied=multiplier != 1.0,
        affected_stats=affected_stats,
        reason="Latest cached injury report was interpreted as neutral." if multiplier == 1.0 else f"Latest cached injury text: {status_text}",
    )


def _weather_factor(
    *,
    recent_team: str,
    opponent_team: str,
    position: str,
) -> FantasyContextFactor:
    affected_stats = _positive_stats_for_position(position)
    if is_dome(recent_team) or is_dome(opponent_team):
        return _neutral_factor(
            "weather",
            "Weather",
            "A dome or retractable-roof team is involved; weather impact is neutral until venue data is wired.",
            affected_stats,
        )
    return _neutral_factor(
        "weather",
        "Weather",
        "Outdoor weather readings are not wired yet, so weather impact is neutral.",
        affected_stats,
    )


def _context_factors(
    settings: AppSettings,
    weekly: pd.DataFrame,
    *,
    player_id: str,
    season: int,
    week: int,
    position: str,
    recent_team: str,
    opponent_team: str,
    scoring_mode: ScoringMode,
) -> list[FantasyContextFactor]:
    return [
        _qb_support_factor(
            weekly,
            season=season,
            week=week,
            team=recent_team,
            position=position,
            scoring_mode=scoring_mode,
        ),
        _position_group_factor(
            weekly,
            season=season,
            week=week,
            team=recent_team,
            position=position,
            scoring_mode=scoring_mode,
        ),
        _injury_factor(
            settings,
            player_id=player_id,
            season=season,
            week=week,
            position=position,
        ),
        _weather_factor(
            recent_team=recent_team,
            opponent_team=opponent_team,
            position=position,
        ),
    ]


def _stat_multipliers(context_factors: list[FantasyContextFactor]) -> dict[str, float]:
    multipliers = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    for factor in context_factors:
        if not factor.applied:
            continue
        for stat in factor.affected_stats:
            if stat in multipliers:
                multipliers[stat] *= factor.multiplier
    return multipliers


def build_fantasy_summary(
    settings: AppSettings,
    *,
    player_id: str,
    season: int,
    week: int,
    position: str,
    recent_team: str,
    opponent_team: str,
    game_id: str = "",
    scoring_mode: str = "full_ppr",
) -> FantasySummary:
    mode = _as_scoring_mode(scoring_mode)
    normalized_position = position.upper().strip()
    train_years = tuple(settings.default_train_years)
    weekly_years = tuple(sorted(set(train_years + (season,))))
    weekly = _weekly_cache(weekly_years)

    distributions = _predict_distributions(
        settings,
        player_id=player_id,
        season=season,
        week=week,
        opponent_team=opponent_team,
        position=normalized_position,
    )
    factors = _context_factors(
        settings,
        weekly,
        player_id=player_id,
        season=season,
        week=week,
        position=normalized_position,
        recent_team=recent_team,
        opponent_team=opponent_team,
        scoring_mode=mode,
    )
    seed = stable_simulation_seed(player_id, season, week, mode)
    projection = project_fantasy_points(
        distributions,
        position=normalized_position,
        scoring_mode=mode,
        stat_multipliers=_stat_multipliers(factors),
        seed=seed,
    )
    return FantasySummary(
        projected_points=projection.projected_points,
        median_points=projection.median_points,
        p10_points=projection.p10_points,
        p90_points=projection.p90_points,
        boom_probability=projection.boom_probability,
        bust_probability=projection.bust_probability,
        boom_cutoff=projection.boom_cutoff,
        bust_cutoff=projection.bust_cutoff,
        scoring_mode=projection.scoring_mode,
        components=projection.components,
        context_factors=factors,
        omitted_stats=projection.omitted_stats,
    )


def predict_fantasy(
    settings: AppSettings,
    request: FantasyPredictionRequest,
) -> FantasyPredictionResponse:
    train_years = tuple(settings.default_train_years)
    weekly_years = tuple(sorted(set(train_years + (request.season,))))
    weekly = _weekly_cache(weekly_years)
    identity = _identity_from_weekly(weekly, request)
    position = identity["position"]
    if not position:
        raise ValueError("Fantasy position is required when player history is unavailable")

    summary = build_fantasy_summary(
        settings,
        player_id=request.player_id,
        season=request.season,
        week=request.week,
        position=position,
        recent_team=identity["recent_team"],
        opponent_team=identity["opponent_team"],
        game_id=request.game_id,
        scoring_mode=request.scoring_mode,
    )
    return FantasyPredictionResponse(
        player_id=request.player_id,
        player_name=identity["player_name"],
        position=position,
        season=request.season,
        week=request.week,
        recent_team=identity["recent_team"],
        opponent_team=identity["opponent_team"],
        game_id=request.game_id,
        **summary.model_dump(),
    )
