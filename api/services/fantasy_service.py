from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from api.schemas import (
    FantasyContextFactor,
    FantasyPredictionRequest,
    FantasyPredictionResponse,
    FantasySummary,
)
from api.settings import AppSettings
from api.services.evaluation_service import _model_bundle, _weekly_cache, scoring_weekly
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
    recent_team: str = "",
) -> dict[str, StatDistribution]:
    train_years = tuple(settings.default_train_years)
    models = _model_bundle(train_years, season)

    distributions: dict[str, StatDistribution] = {}
    for stat in _MODEL_STATS_BY_POSITION.get(position.upper().strip(), ()):
        spec = STAT_SPECS.get(stat)
        if spec is None:
            continue
        model = models[spec.model_name]
        future_row = None
        if settings.use_future_row and recent_team:
            try:
                from api.services.evaluation_service import scoring_weekly

                weekly = scoring_weekly(settings, season)
                from data.upcoming import build_upcoming_row

                future_row = build_upcoming_row(
                    player_id=player_id,
                    season=season,
                    week=week,
                    position=position,
                    opponent_team=opponent_team,
                    recent_team=recent_team,
                    weekly=weekly,
                )
            except Exception:  # noqa: BLE001
                future_row = None
        predicted = model.predict(
            player_id=player_id,
            season=season,
            week=week,
            opp_team=opponent_team,
            future_row=future_row,
        )
        if stat in predicted:
            distributions[stat] = predicted[stat]
    return distributions


# ---------------------------------------------------------------------------
# Trailing-form fantasy projection
#
# The per-position GLMs only cover a slice of the scoring stats (RB: rushing
# only, QB: passing only), and their `future_row` point estimates regress hard
# toward the pooled positional mean — an elite goal-line back or a rushing QB
# comes out looking like a replacement player. For fantasy we instead anchor on
# the player's own recent per-game production for EVERY scoring stat, regressed
# toward a positional baseline by sample size, and fold the model in only
# lightly where it has a distribution. See docs/season_eve_2026_dryrun.md §7.
# ---------------------------------------------------------------------------

_TRAILING_STATS_BY_POSITION: dict[str, tuple[str, ...]] = {
    "QB": ("passing_yards", "passing_tds", "interceptions", "rushing_yards", "rushing_tds"),
    "RB": ("rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"),
    "WR": ("receptions", "receiving_yards", "receiving_tds", "rushing_yards", "rushing_tds"),
    "TE": ("receptions", "receiving_yards", "receiving_tds"),
}
_YARDAGE_STATS = frozenset({"passing_yards", "rushing_yards", "receiving_yards"})
_TRAILING_WINDOW = 8          # most recent games that inform the projection
_TRAILING_REGRESS_GAMES = 4.0  # pseudo-count pulling a thin sample to the baseline
_MODEL_BLEND_WEIGHT = 0.35     # how much the GLM mean moves a covered stat
_STAT_MEAN_LO, _STAT_MEAN_HI = 0.45, 1.7  # clamp band around the trailing mean
_YARD_CV, _COUNT_CV = 0.55, 0.85          # spread when the model gives no distribution


_BASELINE_CACHE: dict[tuple[int, ...], dict[tuple[str, str], float]] = {}


def _baselines_for(weekly: pd.DataFrame) -> dict[tuple[str, str], float]:
    """Per-(position, stat) league mean over the frame — the regression target.
    Cached on the frame's season span (the frame itself is content-stable per
    `scoring_weekly`'s own cache)."""
    if "season" not in weekly.columns or not len(weekly):
        return {}
    key = tuple(sorted(int(s) for s in weekly["season"].unique()))
    cached = _BASELINE_CACHE.get(key)
    if cached is not None:
        return cached
    out: dict[tuple[str, str], float] = {}
    if "position" in weekly.columns:
        pos_upper = weekly["position"].astype(str).str.upper()
        for position, stats in _TRAILING_STATS_BY_POSITION.items():
            rows = weekly[pos_upper == position]
            for stat in stats:
                out[(position, stat)] = (
                    float(rows[stat].fillna(0.0).mean())
                    if stat in rows.columns and len(rows) else 0.0
                )
    _BASELINE_CACHE[key] = out
    return out


def _trailing_fantasy_distributions(
    weekly: pd.DataFrame,
    *,
    player_id: str,
    season: int,
    week: int,
    position: str,
    model_distributions: dict[str, StatDistribution],
) -> dict[str, StatDistribution]:
    normalized = position.upper().strip()
    stats = _TRAILING_STATS_BY_POSITION.get(normalized)
    if not stats:
        return dict(model_distributions)

    baselines = _baselines_for(weekly)
    hist = _player_rows(weekly, player_id)
    if not hist.empty:
        hist = hist[
            (hist["season"] < season)
            | ((hist["season"] == season) & (hist["week"] < week))
        ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)

    n = len(hist)
    recency = np.linspace(0.5, 1.0, n) if n else np.array([])
    form_weight = n / (n + _TRAILING_REGRESS_GAMES) if n else 0.0

    distributions: dict[str, StatDistribution] = {}
    for stat in stats:
        base = float(baselines.get((normalized, stat), 0.0))
        if n and stat in hist.columns:
            recent = float(np.average(hist[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        else:
            recent = base
        trailing = form_weight * recent + (1.0 - form_weight) * base

        model_dist = model_distributions.get(stat)
        if model_dist is not None and model_dist.mean > 0:
            mean = (1.0 - _MODEL_BLEND_WEIGHT) * trailing + _MODEL_BLEND_WEIGHT * float(model_dist.mean)
        else:
            mean = trailing

        anchor = max(recent, base, 1e-6)
        mean = float(np.clip(mean, _STAT_MEAN_LO * anchor, _STAT_MEAN_HI * anchor))
        if mean <= 0:
            continue

        if model_dist is not None and model_dist.mean > 0 and model_dist.std > 0:
            distributions[stat] = StatDistribution(
                mean=mean,
                std=float(model_dist.std) * (mean / float(model_dist.mean)),
                dist_type=model_dist.dist_type,
            )
        elif stat in _YARDAGE_STATS:
            distributions[stat] = StatDistribution(mean=mean, std=max(_YARD_CV * mean, 1e-3), dist_type="gamma")
        else:
            distributions[stat] = StatDistribution(mean=mean, std=max(_COUNT_CV * mean, 1e-3), dist_type="poisson")

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
    # Every complete season through the one being scored — so a 2026 request
    # still sees 2024/2025 form (the configured window lags the calendar).
    weekly = scoring_weekly(settings, season)

    model_distributions = _predict_distributions(
        settings,
        player_id=player_id,
        season=season,
        week=week,
        opponent_team=opponent_team,
        position=normalized_position,
        recent_team=recent_team,
    )
    distributions = _trailing_fantasy_distributions(
        weekly,
        player_id=player_id,
        season=season,
        week=week,
        position=normalized_position,
        model_distributions=model_distributions,
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
    weekly = scoring_weekly(settings, request.season)
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
