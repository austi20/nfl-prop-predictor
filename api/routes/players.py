from __future__ import annotations

from fastapi import APIRouter, Request

from api.schemas import PlayerDetailResponse
from api.services.evaluation_service import get_player_detail

router = APIRouter(tags=["players"])


@router.get("/players/{player_id}", response_model=PlayerDetailResponse)
def get_player(player_id: str, request: Request) -> PlayerDetailResponse:
    return get_player_detail(request.app.state.settings, player_id)
