from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas import ReplaySummaryResponse, SlateResponse
from api.services.replay_service import build_replay_summary_response, build_slate_response

router = APIRouter(tags=["slate"])


@router.get("/slate", response_model=SlateResponse)
def get_slate(request: Request) -> SlateResponse:
    return build_slate_response(request.app.state.settings)


@router.get("/replay/summary", response_model=ReplaySummaryResponse)
def get_replay_summary(request: Request) -> ReplaySummaryResponse:
    return build_replay_summary_response(request.app.state.settings)
