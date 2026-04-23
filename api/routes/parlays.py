from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas import ParlayBuildRequest, ParlayBuildResponse
from api.services.evaluation_service import build_parlays

router = APIRouter(tags=["parlays"])


@router.post("/parlays/build", response_model=ParlayBuildResponse)
def post_parlay_build(
    payload: ParlayBuildRequest,
    request: Request,
) -> ParlayBuildResponse:
    return build_parlays(request.app.state.settings, payload)
