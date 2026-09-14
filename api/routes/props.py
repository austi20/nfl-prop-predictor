from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from api.schemas import PropBoardResponse, PropEvaluationRequest, PropEvaluationResponse
from api.services.evaluation_service import evaluate_prop
from api.services.prop_board_service import BoardBuilding, build_prop_board

router = APIRouter(tags=["props"])


@router.post("/props/evaluate", response_model=PropEvaluationResponse)
def post_prop_evaluation(
    payload: PropEvaluationRequest,
    request: Request,
) -> PropEvaluationResponse:
    try:
        return evaluate_prop(request.app.state.settings, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/props/board/{season}", response_model=PropBoardResponse)
def get_prop_board(
    season: int,
    request: Request,
    week: int = Query(..., ge=1, le=22),
    limit: int = Query(150, ge=0, le=400),
) -> PropBoardResponse:
    try:
        return build_prop_board(
            request.app.state.settings, season=season, week=week, limit=limit
        )
    except BoardBuilding:
        return PropBoardResponse(season=season, week=week, ready=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"prop board unavailable: {exc}") from exc
