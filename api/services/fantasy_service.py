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
_RUSH_STATS = ("rushing_yards", "rushing_tds")
_PASS_GAME_STATS = ("passing_yards", "passing_tds", *_RECEIVING_STATS)
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

    factors = [
        FantasyContextFactor(
            name="game_environment",
            label="Game environment",
            multiplier=volume,
            applied=abs(volume - 1.0) > 1e-3,
            affected_stats=positive,
            reason=f"Vegas implies {implied:.1f} team points ({env_ratio:.0%} of the {LEAGUE_IMPLIED_POINTS:.0f}-pt league average).",
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

        trend = usage_trend(player_id, int(season), int(week), seasons)
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
) -> list[FantasyContextFactor]:
    seasons = tuple(sorted({int(s) for s in weekly["season"].unique()} | {int(season)})) if "season" in weekly.columns else (int(season),)
    context = context_for(seasons, season=season, week=week, team=recent_team) if recent_team else None
    coach_ppg = coach_points_per_game(tuple(s for s in seasons if s < season) or seasons)
    if not game_id and recent_team:
        from data.game_context import game_id_for

        game_id = game_id_for(seasons, season=season, week=week, team=recent_team)

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
    return factors


# Injury "Out"/"Doubtful" are deliberate near-zeros; every other factor is a
# nudge. Clamp the *product* of the nudges so a stack of them can't run away.
_STAT_MULT_LO, _STAT_MULT_HI = 0.75, 1.25


def _stat_multipliers(context_factors: list[FantasyContextFactor]) -> dict[str, float]:
    multipliers = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    injury_hit = {stat: 1.0 for stat in _POSITIVE_SCORING_STATS}
    for factor in context_factors:
        if not factor.applied:
            continue
        target = injury_hit if factor.name == "injury_status" else multipliers
        for stat in factor.affected_stats:
            if stat in target:
                target[stat] *= factor.multiplier
    return {
        stat: float(np.clip(multipliers[stat], _STAT_MULT_LO, _STAT_MULT_HI)) * injury_hit[stat]
        for stat in multipliers
    }


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
        game_id=game_id,
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
