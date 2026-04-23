from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.schemas import FantasyPredictionRequest, FantasyPredictionResponse
from api.services.fantasy_service import predict_fantasy

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
