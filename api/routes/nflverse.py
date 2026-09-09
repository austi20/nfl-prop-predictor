from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas import RosterResponse, ScheduleResponse
from api.services.nflverse_service import get_roster, get_schedule

router = APIRouter(tags=["nflverse"])


@router.get("/schedule/{season}", response_model=ScheduleResponse)
def get_schedule_route(
    season: int,
    week: int | None = Query(default=None, ge=1, le=22),
) -> ScheduleResponse:
    try:
        games = get_schedule(season, week)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"schedule unavailable: {exc}") from exc
    return ScheduleResponse(season=season, games=games)


@router.get("/roster/{season}", response_model=RosterResponse)
def get_roster_route(
    season: int,
    team: str | None = Query(default=None, max_length=4),
    position: str | None = Query(default=None, description="Comma-separated, e.g. RB,WR"),
    status: str = Query(default="ACT"),
    skill_only: bool = Query(default=False),
) -> RosterResponse:
    try:
        players, week = get_roster(
            season, team=team, position=position, status=status or None, skill_only=skill_only
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"roster unavailable: {exc}") from exc
    return RosterResponse(season=season, week=week, players=players)
