from __future__ import annotations

from functools import lru_cache
from typing import Any

import pandas as pd

from api.schemas import (
    DistributionSummary,
    NormalizedPick,
    ParlayBuildRequest,
    ParlayBuildResponse,
    ParlayRow,
    ParlaySummary,
    PlayerDetailResponse,
    PlayerGameLog,
    PropEvaluationRequest,
    PropEvaluationResponse,
    ReplayPolicy,
    SidePrice,
)
from api.settings import AppSettings
from data.nflverse_loader import load_weekly
from eval.calibration_pipeline import STAT_SPECS
from eval.parlay_builder import build_parlay_candidates, summarize_parlays
from eval.prop_pricer import (
    PropCalibrator,
    american_profit,
    build_paper_trade_picks,
    price_two_sided_prop,
    settle_pick,
)
from models.qb import QBModel
from models.rb import RBModel
from models.wr_te import WRTEModel


def _fit_models(
    train_years: tuple[int, ...],
    eval_season: int,
    weekly: pd.DataFrame,
) -> dict[str, QBModel | RBModel | WRTEModel]:
    fit_years = sorted(set(train_years + (eval_season,)))
    weekly_window = weekly[weekly["season"].isin(fit_years)].copy()
    models: dict[str, QBModel | RBModel | WRTEModel] = {
        "qb": QBModel(),
        "rb": RBModel(),
        "wr_te": WRTEModel(),
    }
    for model in models.values():
        model.fit(list(train_years), weekly=weekly_window)
    return models


@lru_cache(maxsize=8)
def _weekly_cache(years: tuple[int, ...]) -> pd.DataFrame:
    return load_weekly(list(years))


@lru_cache(maxsize=8)
def _model_bundle(train_years: tuple[int, ...], eval_season: int) -> dict[str, QBModel | RBModel | WRTEModel]:
    years = tuple(sorted(set(train_years + (eval_season,))))
    weekly = _weekly_cache(years)
    return _fit_models(train_years, eval_season, weekly)


def _calibrator_from_request(settings: AppSettings, calibrator_path: str) -> PropCalibrator | None:
    path = calibrator_path or settings.default_calibrator_path
    if not path:
        return None
    try:
        return PropCalibrator.load(path)
    except FileNotFoundError:
        return None


def _side_model(raw: dict[str, float | str]) -> SidePrice:
    return SidePrice.model_validate(raw)


def evaluate_prop(settings: AppSettings, request: PropEvaluationRequest) -> PropEvaluationResponse:
    if request.stat not in STAT_SPECS:
        raise ValueError(f"Unsupported prop stat: {request.stat}")

    train_years = tuple(settings.default_train_years)
    weekly_years = tuple(sorted(set(train_years + (request.season,))))
    weekly = _weekly_cache(weekly_years)
    models = _model_bundle(train_years, request.season)

    spec = STAT_SPECS[request.stat]
    model = models[spec.model_name]
    future_row = None
    if settings.use_future_row:
        try:
            player_rows_for_future = weekly[weekly["player_id"].astype(str) == request.player_id].copy()
            source = player_rows_for_future.sort_values(["season", "week"]).iloc[-1]
            from data.upcoming import build_upcoming_row

            future_row = build_upcoming_row(
                player_id=request.player_id,
                season=request.season,
                week=request.week,
                position=str(source.get("position", "")),
                opponent_team=request.opponent_team,
                recent_team=request.recent_team or str(source.get("recent_team", "")),
                weekly=weekly,
            )
        except Exception:  # noqa: BLE001
            future_row = None
    distributions = model.predict(
        player_id=request.player_id,
        season=request.season,
        week=request.week,
        opp_team=request.opponent_team,
        future_row=future_row,
    )
    distribution = distributions[request.stat]

    calibrator = _calibrator_from_request(settings, request.calibrator_path)
    market = price_two_sided_prop(
        raw_prob_over=float(distribution.prob_over(request.line)),
        over_odds=request.over_odds,
        under_odds=request.under_odds,
        calibrator=calibrator,
    )
    over = _side_model(market["over"])
    under = _side_model(market["under"])
    selected = over if over.edge >= under.edge else under

    player_rows = weekly[
        (weekly["player_id"].astype(str) == request.player_id)
        & (weekly["season"] == request.season)
        & (weekly["week"] == request.week)
    ].copy()
    player_name = ""
    position = ""
    actual_value: float | None = None
    if not player_rows.empty:
        player_name = str(player_rows.iloc[0].get("player_name", ""))
        position = str(player_rows.iloc[0].get("position", ""))
        actual_raw = player_rows.iloc[0].get(spec.actual_column)
        if pd.notna(actual_raw):
            actual_value = float(actual_raw)

    result: str | None = None
    profit_units: float | None = None
    if actual_value is not None:
        result = settle_pick(actual_value=actual_value, line=request.line, side=selected.side)
        if result == "win":
            profit_units = american_profit(settings.default_stake, int(selected.book_odds))
        elif result == "loss":
            profit_units = -settings.default_stake
        else:
            profit_units = 0.0

    pick = NormalizedPick(
        player_id=request.player_id,
        player_name=player_name,
        position=position,
        season=request.season,
        week=request.week,
        stat=request.stat,
        line=request.line,
        actual_value=actual_value,
        book=request.book,
        selected_side=selected.side,
        selected_odds=int(selected.book_odds),
        selected_book_implied_prob=selected.book_implied_prob,
        selected_fair_american=selected.fair_american,
        selected_raw_prob=selected.raw_prob,
        selected_prob=selected.calibrated_prob,
        selected_edge=selected.edge,
        result=result,
        stake_units=settings.default_stake if actual_value is not None else None,
        profit_units=profit_units,
        game_id=request.game_id,
        recent_team=request.recent_team,
        opponent_team=request.opponent_team,
        over=over,
        under=under,
        distribution=DistributionSummary(
            mean=float(distribution.mean),
            std=float(distribution.std),
            dist_type=str(distribution.dist_type),
        ),
    )

    return PropEvaluationResponse(
        pick=pick,
        selected_side=pick.selected_side,
        selected_edge=pick.selected_edge,
        policy=ReplayPolicy(
            min_edge=settings.default_min_edge,
            stake=settings.default_stake,
            same_game_penalty=settings.default_same_game_penalty,
            same_team_penalty=settings.default_same_team_penalty,
        ),
    )


def build_parlays(settings: AppSettings, request: ParlayBuildRequest) -> ParlayBuildResponse:
    frame = pd.DataFrame([pick.model_dump(exclude_none=True) for pick in request.picks])
    if frame.empty:
        parlays = pd.DataFrame()
    else:
        all_unsettled = "result" not in frame.columns or frame["result"].replace("", pd.NA).isna().all()
        parlays = build_parlay_candidates(
            frame,
            legs=request.legs,
            max_candidates=request.max_candidates,
            same_game_penalty=request.same_game_penalty,
            same_team_penalty=request.same_team_penalty,
            stake=request.stake,
        )
        if all_unsettled and not parlays.empty:
            parlays = parlays.copy()
            parlays["result"] = "unsettled"
            parlays["profit_units"] = 0.0

    summary = ParlaySummary.model_validate(summarize_parlays(parlays))
    return ParlayBuildResponse(
        policy=ReplayPolicy(
            min_edge=settings.default_min_edge,
            stake=request.stake,
            same_game_penalty=request.same_game_penalty,
            same_team_penalty=request.same_team_penalty,
        ),
        parlays=[ParlayRow.model_validate(record) for record in parlays.to_dict("records")] if not parlays.empty else [],
        summary=summary,
    )


def get_player_detail(settings: AppSettings, player_id: str) -> PlayerDetailResponse:
    years = tuple(sorted(set(settings.default_train_years + settings.default_replay_years)))
    weekly = _weekly_cache(years)
    player_rows = weekly[weekly["player_id"].astype(str) == player_id].copy()
    if player_rows.empty:
        return PlayerDetailResponse(player_id=player_id)

    player_rows = player_rows.sort_values(["season", "week"])
    latest = player_rows.iloc[-1]

    supported_actual_columns = {
        spec.actual_column
        for spec in STAT_SPECS.values()
        if spec.actual_column in player_rows.columns
    }
    recent_games = []
    for _, row in player_rows.tail(5).iterrows():
        stats = {
            column: float(row[column])
            for column in supported_actual_columns
            if pd.notna(row.get(column))
        }
        recent_games.append(
            PlayerGameLog(
                season=int(row["season"]),
                week=int(row["week"]),
                recent_team=str(row.get("recent_team", "")),
                opponent_team=str(row.get("opponent_team", "")),
                stats=stats,
            )
        )

    from api.services.replay_service import build_replay_summary_response

    summary = build_replay_summary_response(settings)
    replay_picks = [pick for pick in summary.picks if pick.player_id == player_id]

    return PlayerDetailResponse(
        player_id=player_id,
        player_name=str(latest.get("player_name", "")),
        position=str(latest.get("position", "")),
        recent_team=str(latest.get("recent_team", "")),
        latest_season=int(latest["season"]),
        latest_week=int(latest["week"]),
        supported_stats=sorted({spec.stat for spec in STAT_SPECS.values()}),
        recent_games=recent_games,
        replay_picks=replay_picks,
    )
