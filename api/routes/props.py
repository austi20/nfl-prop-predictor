from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from api.schemas import PropEvaluationRequest, PropEvaluationResponse
from api.services.evaluation_service import evaluate_prop

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
