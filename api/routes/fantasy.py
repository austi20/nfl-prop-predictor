from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas import FantasyPredictionRequest, FantasyPredictionResponse, FantasySlateResponse
from api.services.fantasy_service import predict_fantasy
from api.services.fantasy_slate_service import SlateBuilding, build_fantasy_slate

router = APIRouter(tags=["fantasy"])


@router.post("/fantasy/predict", response_model=FantasyPredictionResponse)
def post_fantasy_prediction(
    payload: FantasyPredictionRequest,
    request: Request,
) -> FantasyPredictionResponse:
    try:
        return predict_fantasy(request.app.state.settings, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/fantasy/slate/{season}", response_model=FantasySlateResponse)
def get_fantasy_slate(
    season: int,
    request: Request,
    week: int = Query(..., ge=1, le=22),
    scoring: Literal["full_ppr", "half_ppr"] = Query("full_ppr"),
    # 0 = whole board (every projectable starter on the slate); a positive
    # limit keeps the per-position budget slice.
    limit: int = Query(0, ge=0, le=300),
) -> FantasySlateResponse:
    try:
        return build_fantasy_slate(
            request.app.state.settings,
            season=season,
            week=week,
            scoring_mode=scoring,
            limit=limit,
        )
    except SlateBuilding:
        # A build (this key or another) is already running. Return a not-ready
        # body rather than blocking a threadpool thread; the client polls.
        return FantasySlateResponse(season=season, week=week, scoring_mode=scoring, ready=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"fantasy slate unavailable: {exc}") from exc
