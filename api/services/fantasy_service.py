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
from data.game_context import (
    LEAGUE_IMPLIED_POINTS,
    LEAGUE_POINTS_PER_GAME,
    coach_points_per_game,
    context_for,
)
from data.nflverse_loader import is_dome
from data.weather import load_forecast
from eval.calibration_pipeline import STAT_SPECS, spec_for
from eval.fantasy_calibration import (
    FantasyCalibration,
    OFFENSE_STACK_FACTORS,
    default_calibration,
    load_calibration,
)
from eval.fantasy_points import (
    SCORING_PROFILES,
    ScoringMode,
    project_fantasy_points,
    scoring_weights,
    stable_simulation_seed,
)
from models.base import StatDistribution

_RECEIVING_STATS = ("receptions", "receiving_yards", "receiving_tds")
_RUSH_STATS = ("rushing_yards", "rushing_tds")
_PASS_GAME_STATS = ("passing_yards", "passing_tds", *_RECEIVING_STATS)
_POSITIVE_SCORING_STATS = tuple(
    stat for stat, weight in SCORING_PROFILES["full_ppr"].items() if weight > 0
)
# _MODEL_STATS_BY_POSITION — which scoring stats have a GLM behind them — is
# defined just below _TRAILING_STATS_BY_POSITION, which it mirrors.


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

    normalized = position.upper().strip()
    wanted = _MODEL_STATS_BY_POSITION.get(normalized, ())
    if not wanted:
        return {}

    # Group by model first. Each `predict` returns every stat that model owns, so
    # calling it once per stat re-ran the same fit several times per player.
    by_model: dict[str, list[str]] = {}
    for stat in wanted:
        spec = spec_for(stat, normalized) or STAT_SPECS.get(stat)
        if spec is not None:
            by_model.setdefault(spec.model_name, []).append(stat)
    if not by_model:
        return {}

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

    distributions: dict[str, StatDistribution] = {}
    for model_name, stats in by_model.items():
        predicted = models[model_name].predict(
            player_id=player_id,
            season=season,
            week=week,
            opp_team=opponent_team,
            future_row=future_row,
        )
        for stat in stats:
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
# Every scoring stat now has a model behind it. This was previously a strict
# subset — an RB's receiving and a QB's rushing had no GLM at all and fell
# through to the trailing anchor alone, which is why the comment above describes
# the models as covering "a slice" of the scoring stats. They no longer do.
_MODEL_STATS_BY_POSITION: dict[str, tuple[str, ...]] = dict(_TRAILING_STATS_BY_POSITION)

_YARDAGE_STATS = frozenset({"passing_yards", "rushing_yards", "receiving_yards"})


@lru_cache(maxsize=4)
def _calibration(path: str) -> FantasyCalibration:
    return load_calibration(path or None)


def _settings_calibration(settings: AppSettings) -> FantasyCalibration:
    return _calibration(getattr(settings, "fantasy_calibration_path", "") or "")
_TRAILING_WINDOW = 8          # most recent games that inform the projection
_TRAILING_REGRESS_GAMES = 4.0  # pseudo-count pulling a thin sample to the baseline
_MODEL_BLEND_WEIGHT = 0.35     # how much the GLM mean moves a covered stat
_STAT_MEAN_LO, _STAT_MEAN_HI = 0.45, 1.7  # clamp band around the trailing mean
_YARD_CV, _COUNT_CV = 0.55, 0.85          # spread when the model gives no distribution


_BASELINE_CACHE: dict[tuple[int, ...], dict[tuple[str, str], float]] = {}


def _rank_lookup(weekly: pd.DataFrame) -> pd.DataFrame:
    """Normalized depth ranks covering the seasons present in `weekly`."""
    if "season" not in weekly.columns or not len(weekly):
        return pd.DataFrame()
    try:
        from data.depth_chart import rank_frame

        seasons = tuple(sorted(int(s) for s in weekly["season"].unique()))
        return rank_frame(seasons)
    except Exception:  # noqa: BLE001 - no depth data must degrade, not fail
        return pd.DataFrame()


def _seasons_span(weekly: pd.DataFrame, season: int | None = None) -> tuple[int, ...]:
    """The season tuple the depth-chart and draft caches are keyed on."""
    known = (
        {int(s) for s in weekly["season"].unique()}
        if "season" in weekly.columns and len(weekly)
        else set()
    )
    if season is not None:
        known.add(int(season))
    return tuple(sorted(known))


def _role_retention(
    rank_bucket: int | None,
    prior_bucket: int | None,
    calib: FantasyCalibration,
) -> float:
    """How much of the trailing sample still describes the player's current job.

    1.0 when the depth slot did not move (or is unknown), so the default path is
    numerically identical to the pre-depth-chart behavior. Each bucket of
    movement retains `role_change_retention` of the remaining weight.
    """
    if rank_bucket is None or prior_bucket is None or rank_bucket == prior_bucket:
        return 1.0
    return float(calib.role_change_retention ** abs(rank_bucket - prior_bucket))


def _form_weight_for(
    n: int,
    rank_bucket: int | None,
    prior_bucket: int | None,
    calib: FantasyCalibration,
) -> tuple[float, float]:
    """(form_weight, retention) for the trailing blend. Extracted so the eval
    backtest can recompute this exactly for a candidate calibration from cached
    raw ingredients, instead of re-deriving the formula a second time."""
    retention = _role_retention(rank_bucket, prior_bucket, calib)
    effective_n = n * retention
    form_weight = effective_n / (effective_n + _TRAILING_REGRESS_GAMES) if effective_n else 0.0
    return form_weight, retention


def _rookie_capital_multiplier(player_id: str, weekly: pd.DataFrame) -> float:
    """Draft-capital scale for a player with no NFL history. A first-round back
    and an undrafted one can sit in the same depth slot; this is what separates
    them when there is no other evidence."""
    try:
        from data.draft import capital_multiplier, draft_capital

        return capital_multiplier(draft_capital(player_id, _seasons_span(weekly)))
    except Exception:  # noqa: BLE001
        return 1.0


def _depth_ranks_for(
    weekly: pd.DataFrame, player_id: str, season: int, week: int
) -> tuple[int | None, int | None]:
    """(current slot, slot the trailing games were played in)."""
    try:
        from data.depth_chart import current_rank, prior_rank

        seasons = _seasons_span(weekly, season)
        return (
            current_rank(player_id, int(season), int(week), seasons),
            prior_rank(player_id, int(season), int(week), seasons),
        )
    except Exception:  # noqa: BLE001 - depth data is an enhancement, never a gate
        return (None, None)


def _baseline(
    baselines: dict[tuple[str, int | None, str], float],
    position: str,
    rank_bucket: int | None,
    stat: str,
) -> float:
    """Exact bucket -> position-wide -> 0.0. The middle rung is the old behavior,
    so a missing or unusable depth chart reproduces it exactly."""
    if rank_bucket is not None:
        hit = baselines.get((position, rank_bucket, stat))
        if hit is not None:
            return float(hit)
    return float(baselines.get((position, None, stat), 0.0))


def _baselines_for(weekly: pd.DataFrame) -> dict[tuple[str, int | None, str], float]:
    """Per-(position, depth-rank bucket, stat) league mean over the frame — the
    regression target. The ``None`` bucket is the position-wide mean every lookup
    falls back to.

    Conditioning on depth rank is what lets a promoted RB2 regress toward the RB1
    archetype instead of the average of every RB in the league, which is itself
    RB3-shaped.

    Cached on the frame's season span (the frame itself is content-stable per
    `scoring_weekly`'s own cache)."""
    if "season" not in weekly.columns or not len(weekly):
        return {}
    key = tuple(sorted(int(s) for s in weekly["season"].unique()))
    cached = _BASELINE_CACHE.get(key)
    if cached is not None:
        return cached

    out: dict[tuple[str, int | None, str], float] = {}
    if "position" not in weekly.columns:
        _BASELINE_CACHE[key] = out
        return out

    frame = weekly.copy()
    frame["_pos"] = frame["position"].astype(str).str.upper()

    ranks = _rank_lookup(weekly)
    if not ranks.empty and "player_id" in frame.columns:
        from data.depth_chart import bucket

        keyed = ranks.assign(
            _bucket=[
                bucket(r, p)
                for r, p in zip(ranks["rank"], ranks["position"], strict=False)
            ]
        )[["gsis_id", "season", "week", "_bucket"]].dropna(subset=["_bucket"])
        frame = frame.merge(
            keyed,
            left_on=["player_id", "season", "week"],
            right_on=["gsis_id", "season", "week"],
            how="left",
        )
    else:
        frame["_bucket"] = None

    for position, stats in _TRAILING_STATS_BY_POSITION.items():
        rows = frame[frame["_pos"] == position]
        ranked = rows.dropna(subset=["_bucket"]) if "_bucket" in rows.columns else rows.iloc[0:0]
        for stat in stats:
            if stat not in rows.columns:
                out[(position, None, stat)] = 0.0
                continue
            out[(position, None, stat)] = (
                float(rows[stat].fillna(0.0).mean()) if len(rows) else 0.0
            )
            for bucket_value, group in ranked.groupby("_bucket"):
                out[(position, int(bucket_value), stat)] = float(
                    group[stat].fillna(0.0).mean()
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
    calib: FantasyCalibration | None = None,
    depth_rank: int | None = None,
    prior_depth_rank: int | None = None,
    _raw_out: dict | None = None,
) -> dict[str, StatDistribution]:
    calib = calib or default_calibration()
    normalized = position.upper().strip()
    stats = _TRAILING_STATS_BY_POSITION.get(normalized)
    if not stats:
        return dict(model_distributions)

    from data.depth_chart import bucket as _rank_bucket

    rank_bucket = _rank_bucket(depth_rank, normalized)
    prior_bucket = _rank_bucket(prior_depth_rank, normalized)
    baselines = _baselines_for(weekly)
    hist = _player_rows(weekly, player_id)
    if not hist.empty:
        hist = hist[
            (hist["season"] < season)
            | ((hist["season"] == season) & (hist["week"] < week))
        ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)

    n = len(hist)
    recency = np.linspace(0.5, 1.0, n) if n else np.array([])
    # A promoted player's trailing games were played in a different job, so that
    # sample is partly measuring the wrong role. Discount its weight by how far
    # the slot moved; what it gives up flows to the rank-conditioned baseline for
    # the role he holds now. Unmoved roles keep the old weighting exactly.
    form_weight, retention = _form_weight_for(n, rank_bucket, prior_bucket, calib)
    # No NFL history at all: the depth slot and what the draft said about him is
    # the entire signal. `form_weight` is 0 here, so this scales the baseline.
    rookie_multiplier = 1.0 if n else _rookie_capital_multiplier(player_id, weekly)

    # Optional side-channel for the eval backtest: the raw per-row/per-stat
    # ingredients behind `trailing`, so scripts/tune_fantasy_calibration.py can
    # recompute this function's output exactly for a candidate calibration
    # without a second implementation of the blend math. No effect on any
    # caller that doesn't pass this in.
    if _raw_out is not None:
        _raw_out.update(
            n=n, rank_bucket=rank_bucket, prior_bucket=prior_bucket,
            rookie_multiplier=rookie_multiplier, recent={}, base={},
        )

    distributions: dict[str, StatDistribution] = {}
    for stat in stats:
        base = _baseline(baselines, normalized, rank_bucket, stat)
        if n and stat in hist.columns:
            recent = float(np.average(hist[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        else:
            recent = base
        if _raw_out is not None:
            _raw_out["recent"][stat] = recent
            _raw_out["base"][stat] = base
        trailing = (
            form_weight * recent + (1.0 - form_weight) * base if n else base * rookie_multiplier
        )

        cv = calib.yard_cv if stat in _YARDAGE_STATS else calib.count_cv
        if not n:
            cv *= calib.rookie_cv_inflation
        cv_floor = cv * calib.cv_floor_frac  # 0 at default -> no change to today's spread

        model_dist = model_distributions.get(stat)
        if model_dist is not None and model_dist.mean > 0:
            glm_bias = calib.glm_bias.get(f"{normalized}/{stat}", 1.0)
            model_mean = float(model_dist.mean) * glm_bias
            # The GLM reads the player's own rolling features, so on a role change
            # it is a second estimate of the same stale job. Discount it by the
            # same retention; the weight returns to the trailing term, which is
            # already leaning on the baseline for the role he holds now.
            glm_weight = calib.glm_blend_weight * retention
            mean = (1.0 - glm_weight) * trailing + glm_weight * model_mean
        else:
            mean = trailing

        anchor = max(recent, base, 1e-6)
        mean = float(np.clip(mean, calib.stat_mean_lo * anchor, calib.stat_mean_hi * anchor))
        if mean <= 0:
            continue

        if model_dist is not None and model_dist.mean > 0 and model_dist.std > 0:
            vinf = calib.glm_var_inflation.get(f"{normalized}/{stat}", 1.0)
            glm_std = float(model_dist.std) * (mean / float(model_dist.mean)) * vinf
            distributions[stat] = StatDistribution(
                mean=mean,
                std=max(glm_std, cv_floor * mean, 1e-3),
                dist_type=model_dist.dist_type,
            )
        elif stat in _YARDAGE_STATS:
            distributions[stat] = StatDistribution(mean=mean, std=max(cv * mean, 1e-3), dist_type="gamma")
        else:
            distributions[stat] = StatDistribution(mean=mean, std=max(cv * mean, 1e-3), dist_type="poisson")

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


def _rows_before(weekly: pd.DataFrame, season: int, week: int, *, recent_seasons: int = 2) -> pd.DataFrame:
    """Every row strictly before (season, week), spanning into prior seasons —
    so a Week-1 request still sees last year's form instead of nothing. Trimmed
    to the last ``recent_seasons`` distinct seasons present for stationarity."""
    if "season" not in weekly.columns or "week" not in weekly.columns:
        return weekly.iloc[0:0]
    before = weekly[
        (weekly["season"] < season)
        | ((weekly["season"] == season) & (weekly["week"] < week))
    ].copy()
    if before.empty:
        return before
    keep = sorted(before["season"].unique())[-recent_seasons:]
    return before[before["season"].isin(keep)]


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

    prior = _rows_before(weekly, season, week)
    if prior.empty or "position" not in prior.columns:
        return _neutral_factor(
            "qb_support",
            "QB support",
            "No prior QB form is available before this game.",
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


def _opponent_matchup_factor(
    weekly: pd.DataFrame,
    *,
    season: int,
    week: int,
    opponent_team: str,
    position: str,
    scoring_mode: ScoringMode,
) -> FantasyContextFactor:
    """Fantasy points this opponent allows to the position vs the league.

    The GLM already carries an opponent-defense feature, but only on the stats
    it covers and at ~35% blend weight. This applies the matchup to *every*
    scoring stat, half-strength.
    """
    normalized = position.upper().strip()
    positive = _positive_stats_for_position(normalized)
    if not opponent_team or normalized not in {"QB", "RB", "WR", "TE"}:
        return _neutral_factor(
            "opponent_matchup", "Opponent matchup",
            "Opponent or position unavailable.", positive,
        )
    prior = _rows_before(weekly, season, week)
    if prior.empty or not {"position", "opponent_team"}.issubset(prior.columns):
        return _neutral_factor(
            "opponent_matchup", "Opponent matchup",
            "No prior defense-allowed data before this game.", positive,
        )
    pos_rows = prior[prior["position"].astype(str).str.upper() == normalized].copy()
    if pos_rows.empty:
        return _neutral_factor(
            "opponent_matchup", "Opponent matchup", "No positional data.", positive,
        )
    pos_rows["fp"] = _fantasy_points_from_rows(pos_rows, scoring_mode)
    # points allowed to the position, per defense per game
    per_def_game = pos_rows.groupby(["opponent_team", "season", "week"], as_index=False)["fp"].sum()
    league_mean = per_def_game["fp"].mean()
    opp_games = per_def_game[per_def_game["opponent_team"].astype(str) == opponent_team]
    if opp_games.empty or league_mean <= 0:
        return _neutral_factor(
            "opponent_matchup", "Opponent matchup",
            f"No games found for {opponent_team}'s defense.", positive,
        )
    ratio = float(opp_games["fp"].mean()) / float(league_mean)
    multiplier = float(np.clip(1.0 + 0.5 * (ratio - 1.0), 0.88, 1.12))
    return FantasyContextFactor(
        name="opponent_matchup",
        label="Opponent matchup",
        multiplier=round(multiplier, 4),
        applied=abs(multiplier - 1.0) > 5e-3,
        affected_stats=positive,
        reason=f"{opponent_team} allows {opp_games['fp'].mean():.1f} fantasy pts/game to {normalized}s ({ratio:.0%} of league) over {len(opp_games)} games.",
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

    prior = _rows_before(weekly, season, week)
    if prior.empty or "position" not in prior.columns or "recent_team" not in prior.columns:
        return _neutral_factor(
            "position_group_form",
            "Team position form",
            "No prior position-group production is available before this game.",
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
    if path.exists():
        return pd.read_parquet(path)
    # Not cached yet (e.g. a fresh in-progress season) — fetch + cache once.
    try:
        from data.nflverse_loader import load_injuries

        return load_injuries([season])
    except Exception:  # noqa: BLE001
        return pd.DataFrame()


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

    def _field(*names: str) -> str:
        return " ".join(
            str(latest[c]) for c in names if c in latest.index and pd.notna(latest[c])
        ).strip().lower()

    game_status = _field("game_status", "report_status", "status", "injury_report_status")
    practice = _field("practice_status")

    multiplier = 1.0
    reason = "On the report but expected to play a normal workload."
    # Game-status designations are the reliable signal; practice-only is weaker
    # and dominant early in the week before the game report is filed.
    if any(w in game_status for w in ("out", "injured reserve", " ir")):
        multiplier, reason = 0.05, f"Ruled OUT ({game_status})."
    elif "doubtful" in game_status:
        multiplier, reason = 0.40, f"Doubtful ({game_status})."
    elif "questionable" in game_status:
        multiplier, reason = 0.92, f"Questionable ({game_status})."
    elif "did not participate" in practice or "dnp" in practice or "did not practice" in practice:
        multiplier, reason = 0.90, f"Did not practice ({practice}); no game status yet."
    elif "limited" in practice:
        multiplier, reason = 0.96, f"Limited in practice ({practice})."

    return FantasyContextFactor(
        name="injury_status",
        label="Injury status",
        multiplier=multiplier,
        applied=multiplier != 1.0,
        affected_stats=affected_stats,
        reason=reason,
    )


_SNOW_WEATHER_CODES = frozenset({71.0, 73.0, 75.0, 77.0, 85.0, 86.0})


def _weather_factors(
    *,
    game_id: str,
    recent_team: str,
    opponent_team: str,
    position: str,
) -> list[FantasyContextFactor]:
    """Open-Meteo forecast -> wind / precip / cold multipliers.

    Wind is the dominant fantasy weather effect (deep passing collapses ~15 mph+);
    heavy precip and hard cold shave passing a little and nudge rushing up.
    """
    positive = _positive_stats_for_position(position)
    wx = load_forecast(game_id) if game_id else None

    if wx is None:
        indoor_guess = is_dome(recent_team) or is_dome(opponent_team)
        return [
            _neutral_factor(
                "weather",
                "Weather",
                "Roof/dome — weather is not a factor." if indoor_guess
                else "No forecast available for this game yet; weather is neutral.",
                positive,
            )
        ]
    if wx.get("indoor"):
        return [_neutral_factor("weather", "Weather", "Indoor game — weather is not a factor.", positive)]

    wind = float(wx.get("wind_mph") or 0.0)
    precip = float(wx.get("precip_in") or 0.0)
    temp = wx.get("temp_f")
    code = float(wx.get("weather_code") or 0.0)

    pass_mult = 1.0
    run_mult = 1.0
    notes: list[str] = []
    if wind >= 25:
        pass_mult *= 0.86
        run_mult *= 1.03
        notes.append(f"{wind:.0f} mph wind")
    elif wind >= 20:
        pass_mult *= 0.91
        run_mult *= 1.02
        notes.append(f"{wind:.0f} mph wind")
    elif wind >= 15:
        pass_mult *= 0.96
        run_mult *= 1.01
        notes.append(f"{wind:.0f} mph wind")

    if precip >= 0.10 or code in _SNOW_WEATHER_CODES:
        pass_mult *= 0.95
        run_mult *= 1.02
        notes.append("snow" if code in _SNOW_WEATHER_CODES else f"{precip:.2f} in/hr precip")

    if temp is not None and float(temp) <= 20:
        pass_mult *= 0.97
        notes.append(f"{float(temp):.0f}F")

    if not notes:
        return [_neutral_factor(
            "weather", "Weather",
            f"Forecast is benign ({wind:.0f} mph wind, {precip:.2f} in precip).", positive,
        )]

    reason = ", ".join(notes)
    pass_stats = [s for s in _PASS_GAME_STATS if s in positive]
    run_stats = [s for s in _RUSH_STATS if s in positive]
    out: list[FantasyContextFactor] = []
    if pass_stats and abs(pass_mult - 1.0) > 1e-3:
        out.append(FantasyContextFactor(
            name="weather_pass", label="Weather (passing)", multiplier=round(pass_mult, 4),
            applied=True, affected_stats=pass_stats,
            reason=f"Forecast: {reason} — passing game trimmed.",
        ))
    if run_stats and abs(run_mult - 1.0) > 1e-3:
        out.append(FantasyContextFactor(
            name="weather_run", label="Weather (rushing)", multiplier=round(run_mult, 4),
            applied=True, affected_stats=run_stats,
            reason=f"Forecast: {reason} — rushing volume nudged up.",
        ))
    return out or [_neutral_factor("weather", "Weather", f"Forecast: {reason} (net neutral).", positive)]


_GAME_SCRIPT_SPREAD_CUTOFF = 4.0  # points; below this the pass/run tilt is neutral


def _game_script_factors(
    context: dict | None,
    *,
    position: str,
) -> list[FantasyContextFactor]:
    """Vegas-implied game environment + script from the closing line.

    - `game_environment`: scale every scoring stat by the team's implied points
      relative to the league average (a 28-point team is a richer environment
      than a 19-point team).
    - `game_script_run` / `game_script_pass`: a favourite runs more and passes
      less late; an underdog does the reverse. Only when the spread is >= 4.
    """
    positive = _positive_stats_for_position(position)
    if not context or context.get("team_implied") is None:
        return [
            _neutral_factor(
                "game_environment",
                "Game environment",
                "No Vegas line is posted for this game yet, so game script is neutral.",
                positive,
            )
        ]

    implied = float(context["team_implied"])
    env_ratio = implied / LEAGUE_IMPLIED_POINTS if LEAGUE_IMPLIED_POINTS else 1.0
    # Half-strength: the trailing anchor + GLM already carry some of this, and a
    # good offense is partly priced by the coaching factor too.
    volume = float(np.clip(1.0 + 0.25 * (env_ratio - 1.0), 0.90, 1.12))

    src = "Kalshi" if context.get("line_source") == "kalshi" else "Vegas"
    factors = [
        FantasyContextFactor(
            name="game_environment",
            label="Game environment",
            multiplier=volume,
            applied=abs(volume - 1.0) > 1e-3,
            affected_stats=positive,
            reason=f"{src} implies {implied:.1f} team points ({env_ratio:.0%} of the {LEAGUE_IMPLIED_POINTS:.0f}-pt league average).",
        )
    ]

    spread = context.get("team_spread")
    if spread is None or abs(float(spread)) < _GAME_SCRIPT_SPREAD_CUTOFF:
        return factors

    spread = float(spread)
    favourite = spread < 0  # team perspective: negative = favoured
    run_stats = [s for s in _RUSH_STATS if s in positive]
    pass_stats = [s for s in _PASS_GAME_STATS if s in positive]
    run_mult = 1.04 if favourite else 0.95
    pass_mult = 0.985 if favourite else 1.03
    side = "favoured" if favourite else "underdog"
    if run_stats:
        factors.append(
            FantasyContextFactor(
                name="game_script_run",
                label="Game script (run)",
                multiplier=run_mult,
                applied=True,
                affected_stats=run_stats,
                reason=f"Team is a {abs(spread):.1f}-pt {side}; positive/negative game script shifts rushing volume.",
            )
        )
    if pass_stats:
        factors.append(
            FantasyContextFactor(
                name="game_script_pass",
                label="Game script (pass)",
                multiplier=pass_mult,
                applied=True,
                affected_stats=pass_stats,
                reason=f"Team is a {abs(spread):.1f}-pt {side}; script shifts pass volume the other way.",
            )
        )
    return factors


def _usage_factor(
    *,
    player_id: str,
    season: int,
    week: int,
    position: str,
    seasons: tuple[int, ...],
) -> FantasyContextFactor:
    """Recent snap % / air-yards share vs the player's own baseline — corrects
    the trailing-8-game average when a role is trending up or down."""
    positive = _positive_stats_for_position(position)
    try:
        from data.usage import usage_trend

        # only completed seasons — snap/NGS files for an in-progress season 404
        completed = tuple(s for s in seasons if s < int(season)) or seasons
        trend = usage_trend(player_id, int(season), int(week), completed)
    except Exception:  # noqa: BLE001
        trend = None
    if not trend:
        return _neutral_factor(
            "usage_trend", "Usage trend",
            "Not enough snap/target history to detect a role change.", positive,
        )

    ratios: list[float] = []
    notes: list[str] = []
    if trend.get("snap_base", 0.0) > 0.15:
        r = trend["snap_recent"] / trend["snap_base"]
        ratios.append(r)
        notes.append(f"snaps {trend['snap_recent']:.0%} vs {trend['snap_base']:.0%}")
    if position.upper().strip() in {"WR", "TE", "RB"} and trend.get("ay_base", 0.0) > 0.05:
        r = trend["ay_recent"] / trend["ay_base"]
        ratios.append(r)
        notes.append(f"air-yards share {trend['ay_recent']:.0%} vs {trend['ay_base']:.0%}")
    if not ratios:
        return _neutral_factor(
            "usage_trend", "Usage trend", "Usage is stable.", positive,
        )

    trend_ratio = float(np.mean(ratios))
    if abs(trend_ratio - 1.0) < 0.08:
        return _neutral_factor(
            "usage_trend", "Usage trend",
            f"Role is steady ({', '.join(notes)}).", positive,
        )
    multiplier = float(np.clip(1.0 + 0.35 * (trend_ratio - 1.0), 0.85, 1.15))
    direction = "up" if trend_ratio > 1.0 else "down"
    return FantasyContextFactor(
        name="usage_trend",
        label="Usage trend",
        multiplier=round(multiplier, 4),
        applied=True,
        affected_stats=positive,
        reason=f"Role trending {direction}: {', '.join(notes)} — trailing average lags it.",
    )


def _depth_chart_ratio(
    baselines: dict[tuple[str, int | None, str], float],
    position: str,
    current_bucket: int | None,
    prior_bucket: int | None,
) -> float | None:
    """new-bucket-baseline / old-bucket-baseline on the position's headline
    volume stat, or None when there is nothing to price (unmoved, unknown, or a
    bucket with no baseline). Extracted so the eval backtest can recompute
    `_depth_chart_factor`'s multiplier for a candidate `depth_chart_damping`
    from this one cached number, rather than re-deriving the ratio itself."""
    if current_bucket is None or prior_bucket is None or current_bucket == prior_bucket:
        return None
    stat = _TRAILING_STATS_BY_POSITION.get(position, ("",))[0]
    new_base = _baseline(baselines, position, current_bucket, stat)
    old_base = _baseline(baselines, position, prior_bucket, stat)
    if old_base <= 0 or new_base <= 0:
        return None
    return new_base / old_base


def _depth_chart_factor(
    baselines: dict[tuple[str, int | None, str], float],
    *,
    position: str,
    current: int | None,
    prior: int | None,
    calib: FantasyCalibration,
) -> FantasyContextFactor:
    """The role change the trailing window cannot see.

    `usage_trend` only detects a move that happened *within* a season. An
    offseason promotion — the RB2 who is RB1 because the starter left — leaves
    no such trace, and the trailing average keeps projecting the old job.

    The magnitude is the empirical gap between the two depth buckets' own
    baselines, damped, never a hand-picked constant. That is what stops a
    promotion inventing a projection the data cannot support.
    """
    normalized = position.upper().strip()
    positive = _positive_stats_for_position(normalized)
    if current is None or prior is None:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            "Depth-chart rank unavailable for this player.", positive,
        )

    from data.depth_chart import bucket

    cur_b, prior_b = bucket(current, normalized), bucket(prior, normalized)
    if cur_b is None or prior_b is None or cur_b == prior_b:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            f"Still listed {normalized}{cur_b or current} — no role change.", positive,
        )

    ratio = _depth_chart_ratio(baselines, normalized, cur_b, prior_b)
    if ratio is None:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            "No baseline for one of the two depth slots.", positive,
        )

    multiplier = float(
        np.clip(
            1.0 + calib.depth_chart_damping * (ratio - 1.0),
            calib.context_clamp_lo,
            calib.context_clamp_hi,
        )
    )
    direction = "Promoted" if cur_b < prior_b else "Demoted"
    return FantasyContextFactor(
        name="depth_chart",
        label="Depth chart",
        multiplier=round(multiplier, 4),
        applied=abs(multiplier - 1.0) > 1e-3,
        affected_stats=positive,
        reason=(
            f"{direction}: {normalized}{prior_b} -> {normalized}{cur_b}. "
            f"The trailing average is still {normalized}{prior_b} usage."
        ),
    )


def _scale_to_market(
    dist: StatDistribution,
    strike: float,
    target_prob: float,
    lo: float,
    hi: float,
) -> float:
    """The scale factor that makes this distribution agree with the market.

    The market is not offering a point estimate — it is offering a probability,
    "P(stat >= strike) = target_prob". So rather than guessing at a median and
    matching means, solve for the multiplier that makes the model's own
    distribution family reproduce that probability at that strike.

    `prob_over` is monotone in the scale, so a bisection is exact and cheap. The
    search runs inside [lo, hi], which is what bounds the correction.
    """

    def prob_at(scale: float) -> float:
        return StatDistribution(
            mean=dist.mean * scale,
            std=dist.std * scale,
            dist_type=dist.dist_type,
            params=dict(dist.params),
        ).prob_over(strike)

    if prob_at(lo) >= target_prob:
        return lo
    if prob_at(hi) <= target_prob:
        return hi
    low, high = lo, hi
    for _ in range(24):
        mid = 0.5 * (low + high)
        if prob_at(mid) < target_prob:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


def _market_factors(
    distributions: dict[str, StatDistribution],
    lines: dict[str, list[float]],
    *,
    player_id: str,
    position: str,
    calib: FantasyCalibration,
) -> list[FantasyContextFactor]:
    """One factor per stat the market actually prices.

    A traded book has already absorbed the depth chart, the injury report and
    the beat news, so where a quote exists it outranks everything the model
    infers from history.
    """
    if not lines:
        return []
    from api.services.market_lines import market_quote

    out: list[FantasyContextFactor] = []
    for stat, dist in distributions.items():
        quote = market_quote(lines, player_id, stat)
        if quote is None or dist.mean <= 0 or dist.std <= 0:
            continue
        strike, prob = quote
        if not 0.02 < prob < 0.98:
            continue
        scale = _scale_to_market(
            dist, strike, prob, calib.market_clamp_lo, calib.market_clamp_hi
        )
        model_prob = dist.prob_over(strike)
        out.append(
            FantasyContextFactor(
                name="market",
                label="Market line",
                multiplier=round(float(scale), 4),
                applied=abs(scale - 1.0) > 1e-3,
                affected_stats=[stat],
                reason=(
                    f"Kalshi prices {stat.replace('_', ' ')} {strike:g}+ at "
                    f"{prob:.0%}; the model had it at {model_prob:.0%}."
                ),
            )
        )
    return out


def _resolve_role_precedence(
    factors: list[FantasyContextFactor],
) -> list[FantasyContextFactor]:
    """One role change, priced once.

    Precedence is market > depth chart > usage trend. A traded market already
    reflects the depth chart; the depth chart already reflects an offseason move
    that the within-season usage trend would otherwise double-count. Each tier
    strips the stats it covers from the tier below.
    """
    priced: set[str] = {
        stat
        for factor in factors
        if factor.name == "market" and factor.applied
        for stat in factor.affected_stats
    }
    depth = next((f for f in factors if f.name == "depth_chart"), None)
    depth_fires = depth is not None and depth.applied

    out: list[FantasyContextFactor] = []
    for factor in factors:
        if factor.name == "market":
            out.append(factor)
            continue
        if factor.name == "depth_chart" and factor.applied and priced:
            remaining = [s for s in factor.affected_stats if s not in priced]
            if not remaining:
                out.append(
                    _neutral_factor(
                        "depth_chart", "Depth chart",
                        "Role already priced by the market — superseded.",
                        list(factor.affected_stats),
                    )
                )
                continue
            factor = FantasyContextFactor(
                name=factor.name, label=factor.label, multiplier=factor.multiplier,
                applied=factor.applied, affected_stats=remaining, reason=factor.reason,
            )
        elif factor.name == "usage_trend" and factor.applied:
            # The depth chart covers every positive stat for the position, so when
            # it fires it supersedes the usage trend outright rather than per-stat.
            if depth_fires:
                out.append(
                    _neutral_factor(
                        "usage_trend", "Usage trend",
                        "Role move already priced by the depth chart — superseded.",
                        list(factor.affected_stats),
                    )
                )
                continue
            remaining = [s for s in factor.affected_stats if s not in priced]
            if not remaining:
                out.append(
                    _neutral_factor(
                        "usage_trend", "Usage trend",
                        "Role move already priced by the market — superseded.",
                        list(factor.affected_stats),
                    )
                )
                continue
            factor = FantasyContextFactor(
                name=factor.name, label=factor.label, multiplier=factor.multiplier,
                applied=factor.applied, affected_stats=remaining, reason=factor.reason,
            )
        out.append(factor)
    return out


def _coach_factor(
    context: dict | None,
    coach_ppg: dict[str, tuple[float, int]],
    *,
    position: str,
) -> FantasyContextFactor:
    """Offensive-system prior from the head coach's career points/game."""
    positive = _positive_stats_for_position(position)
    coach = (context or {}).get("coach", "")
    entry = coach_ppg.get(coach) if coach else None
    if not entry or entry[1] < 16:
        return _neutral_factor(
            "coaching",
            "Coaching / scheme",
            "Not enough head-coach history to form an offensive-system prior."
            if coach
            else "Head coach unknown for this game.",
            positive,
        )
    ppg, games = entry
    ratio = ppg / LEAGUE_POINTS_PER_GAME if LEAGUE_POINTS_PER_GAME else 1.0
    # Vegas already prices most offensive quality; only move for genuine
    # outliers (Joe Judge / Bruce Arians tier), and then only quarter-strength.
    if abs(ratio - 1.0) < 0.10:
        return _neutral_factor(
            "coaching",
            "Coaching / scheme",
            f"{coach} offenses are near league average ({ratio:.0%}); Vegas already reflects it.",
            positive,
        )
    multiplier = float(np.clip(1.0 + 0.25 * (ratio - 1.0), 0.96, 1.05))
    return FantasyContextFactor(
        name="coaching",
        label="Coaching / scheme",
        multiplier=multiplier,
        applied=abs(multiplier - 1.0) > 1e-3,
        affected_stats=positive,
        reason=f"{coach} offenses average {ppg:.1f} pts/game over {games} games ({ratio:.0%} of league) — outlier system.",
    )


# Headlines that, tagged to a team, move its whole offense. Deliberately short
# and high-confidence — player-level benchings are the injury / usage factors.
_NEWS_OFFENSE_DOWN_PHRASES = (
    "3rd-string", "third-string", "third string", "benched", "benching",
    "demoted", "backup quarterback will start", "named the starter over",
)
_NEWS_DEF_WEAK_PHRASES = (
    "secondary decimated", "without their top corner", "shorthanded secondary",
)
# (subject phrase, action words) — fires when both appear in the blob.
_NEWS_COORDINATOR_OUT = (
    ("offensive coordinator", ("fire", "fired", "fires", "out", "let go")),
)
_NEWS_DEF_COORDINATOR_OUT = (
    ("defensive coordinator", ("fire", "fired", "fires", "out", "let go")),
)


def _blob_matches_pair(blob: str, pairs: tuple[tuple[str, tuple[str, ...]], ...]) -> str:
    for subject, actions in pairs:
        if subject in blob and any(a in blob for a in actions):
            return f"{subject} {next(a for a in actions if a in blob)}"
    return ""


def _news_factor(*, team: str, opponent_team: str, position: str) -> FantasyContextFactor:
    """Fast keyword gate over the last hour of ESPN team headlines. Catches a
    mid-week scheme/QB shakeup the historical + injury factors can't see."""
    positive = _positive_stats_for_position(position)
    try:
        from data.news import team_headlines

        own = " || ".join(team_headlines(team)) if team else ""
        opp = " || ".join(team_headlines(opponent_team)) if opponent_team else ""
    except Exception:  # noqa: BLE001
        own = opp = ""
    if not own and not opp:
        return _neutral_factor(
            "news", "News", "No recent team headlines to gate on.", positive
        )

    multiplier = 1.0
    reasons: list[str] = []
    hit_down = next((p for p in _NEWS_OFFENSE_DOWN_PHRASES if p in own), "") or _blob_matches_pair(
        own, _NEWS_COORDINATOR_OUT
    )
    if hit_down:
        multiplier *= 0.96
        reasons.append(f"own-offense news: “{hit_down}”")
    hit_def = next((p for p in _NEWS_DEF_WEAK_PHRASES if p in opp), "") or _blob_matches_pair(
        opp, _NEWS_DEF_COORDINATOR_OUT
    )
    if hit_def:
        multiplier *= 1.03
        reasons.append(f"opponent defense news: “{hit_def}”")

    if not reasons:
        return _neutral_factor(
            "news", "News", "Recent headlines carry no scheme/role signal.", positive
        )
    return FantasyContextFactor(
        name="news",
        label="News",
        multiplier=round(multiplier, 4),
        applied=abs(multiplier - 1.0) > 1e-3,
        affected_stats=positive,
        reason="; ".join(reasons),
    )


def _rest_factor(context: dict | None, *, position: str) -> FantasyContextFactor:
    """Bye-week bump / short-week (Thursday) drag from the schedule rest days."""
    positive = _positive_stats_for_position(position)
    rest = (context or {}).get("rest")
    opp_rest = (context or {}).get("opp_rest")
    if rest is None:
        return _neutral_factor("rest", "Rest", "Rest days unavailable.", positive)
    rest = float(rest)
    multiplier = 1.0
    reason = "Normal week of rest."
    if rest >= 10:
        multiplier = 1.02
        reason = f"Coming off a bye ({rest:.0f} days), slight freshness bump."
    elif rest <= 4:
        multiplier = 0.98
        reason = f"Short week ({rest:.0f} days), slight drag."
    if opp_rest is not None and float(opp_rest) <= 4 < rest:
        multiplier *= 1.01  # opponent on a short week
        reason += " Opponent is on a short week."
    return FantasyContextFactor(
        name="rest",
        label="Rest",
        multiplier=round(multiplier, 4),
        applied=abs(multiplier - 1.0) > 1e-3,
        affected_stats=positive,
        reason=reason,
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
    game_id: str = "",
    calib: FantasyCalibration | None = None,  # accepted for signature stability; scaling is in _stat_multipliers
) -> list[FantasyContextFactor]:
    seasons = tuple(sorted({int(s) for s in weekly["season"].unique()} | {int(season)})) if "season" in weekly.columns else (int(season),)
    context = context_for(seasons, season=season, week=week, team=recent_team) if recent_team else None
    coach_ppg = coach_points_per_game(tuple(s for s in seasons if s < season) or seasons)
    if not game_id and recent_team:
        from data.game_context import game_id_for

        game_id = game_id_for(seasons, season=season, week=week, team=recent_team)

    try:
        from data.depth_chart import current_rank, prior_rank

        _depth_ranks = (
            current_rank(player_id, int(season), int(week), seasons),
            prior_rank(player_id, int(season), int(week), seasons),
        )
    except Exception:  # noqa: BLE001 - depth data is an enhancement, never a gate
        _depth_ranks = (None, None)

    factors: list[FantasyContextFactor] = [
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
        _opponent_matchup_factor(
            weekly,
            season=season,
            week=week,
            opponent_team=opponent_team,
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
        _usage_factor(
            player_id=player_id,
            season=season,
            week=week,
            position=position,
            seasons=seasons,
        ),
        _depth_chart_factor(
            _baselines_for(weekly),
            position=position,
            current=_depth_ranks[0],
            prior=_depth_ranks[1],
            calib=calib or default_calibration(),
        ),
        _news_factor(team=recent_team, opponent_team=opponent_team, position=position),
        _coach_factor(context, coach_ppg, position=position),
        _rest_factor(context, position=position),
    ]
    factors.extend(
        _weather_factors(
            game_id=game_id,
            recent_team=recent_team,
            opponent_team=opponent_team,
            position=position,
        )
    )
    factors.extend(_game_script_factors(context, position=position))
    return _resolve_role_precedence(factors)


# Injury "Out"/"Doubtful" are deliberate near-zeros; every other factor is a
# nudge. Clamp the *product* of the nudges so a stack of them can't run away.
# Defaults live in FantasyCalibration; these names kept for back-compat readers.
_STAT_MULT_LO, _STAT_MULT_HI = 0.78, 1.22

_OFFENSE_STACK_SET = frozenset(OFFENSE_STACK_FACTORS)


def _stat_multipliers(
    context_factors: list[FantasyContextFactor],
    calib: FantasyCalibration | None = None,
) -> dict[str, float]:
    calib = calib or default_calibration()
    multipliers = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    injury_hit = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    offense = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}  # jointly sub-capped
    # A traded market gets its own, wider band: it is a direct statement about
    # this stat, not a nudge, and folding it into the context clamp would throttle
    # the best information on the board down to +/-22%.
    market = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    for factor in context_factors:
        if not factor.applied:
            continue
        scaled = 1.0 + calib.strength(factor.name) * (factor.multiplier - 1.0)
        if factor.name == "injury_status":
            target = injury_hit
        elif factor.name == "market":
            target = market
        elif factor.name in _OFFENSE_STACK_SET:
            target = offense
        else:
            target = multipliers
        for stat in factor.affected_stats:
            if stat in target:
                target[stat] *= scaled
    out: dict[str, float] = {}
    for stat in multipliers:
        stack = min(offense[stat], calib.offense_stack_cap)
        combined = float(np.clip(multipliers[stat] * stack, calib.context_clamp_lo, calib.context_clamp_hi))
        market_scale = float(
            np.clip(market[stat], calib.market_clamp_lo, calib.market_clamp_hi)
        )
        out[stat] = combined * market_scale * injury_hit[stat]
    return out


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
    calib = _settings_calibration(settings)

    model_distributions = _predict_distributions(
        settings,
        player_id=player_id,
        season=season,
        week=week,
        opponent_team=opponent_team,
        position=normalized_position,
        recent_team=recent_team,
    )
    depth_rank, prior_depth_rank = _depth_ranks_for(weekly, player_id, season, week)
    distributions = _trailing_fantasy_distributions(
        weekly,
        player_id=player_id,
        season=season,
        week=week,
        position=normalized_position,
        model_distributions=model_distributions,
        calib=calib,
        depth_rank=depth_rank,
        prior_depth_rank=prior_depth_rank,
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
        game_id=game_id,
        calib=calib,
    )
    # The market is resolved after the distributions exist: fitting to a priced
    # probability needs the distribution family, not just a mean.
    if settings.use_market_anchor:
        from api.services.market_lines import player_stat_lines

        market = _market_factors(
            distributions,
            player_stat_lines(settings, season, week),
            player_id=player_id,
            position=normalized_position,
            calib=calib,
        )
        if market:
            factors = _resolve_role_precedence([*factors, *market])

    seed = stable_simulation_seed(player_id, season, week, mode)
    projection = project_fantasy_points(
        distributions,
        position=normalized_position,
        scoring_mode=mode,
        stat_multipliers=_stat_multipliers(factors, calib),
        seed=seed,
        calib=calib,
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
