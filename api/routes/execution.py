from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.schemas import NormalizedPick

router = APIRouter(tags=["execution"])


class SubmitPicksRequest(BaseModel):
    picks: list[NormalizedPick]


class CancelRequest(BaseModel):
    intent_id: str


class KillRequest(BaseModel):
    reason: str = "user_initiated"


@router.post("/execution/paper/submit")
async def submit_picks(payload: SubmitPicksRequest, request: Request) -> dict:
    svc = request.app.state.execution_service
    results = await svc.submit_picks(payload.picks)
    return {"success": True, "data": results}


@router.post("/execution/paper/cancel")
async def cancel_intent(payload: CancelRequest, request: Request) -> dict:
    svc = request.app.state.execution_service
    result = await svc.cancel(payload.intent_id)
    return {"success": True, "data": result}


@router.post("/execution/kill")
async def kill(payload: KillRequest, request: Request) -> dict:
    svc = request.app.state.execution_service
    canceled = await svc.trip_kill_switch(payload.reason)
    return {"success": True, "data": {"killed": canceled, "reason": payload.reason}}


@router.get("/execution/portfolio")
async def get_portfolio(request: Request) -> dict:
    svc = request.app.state.execution_service
    portfolio = svc.get_portfolio()
    return {
        "success": True,
        "data": {
            "cash_balance": portfolio.cash_balance,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "positions": [
                {
                    "market_id": k[0] if isinstance(k, tuple) else k,
                    "side": k[1] if isinstance(k, tuple) else p.side,
                    "size": p.size,
                    "avg_price": p.avg_price,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for k, p in portfolio.positions.items()
            ],
        },
    }


@router.get("/execution/events")
async def get_events(since: int = 0, request: Request = None) -> dict:  # type: ignore[assignment]
    svc = request.app.state.execution_service  # type: ignore[union-attr]
    return {"success": True, "data": svc.get_events(since)}


@router.get("/execution/events/stream")
async def events_stream(request: Request) -> StreamingResponse:
    svc = request.app.state.execution_service

    async def generate():
        cursor = len(svc._events)
        while True:
            if await request.is_disconnected():
                break
            new_events = svc.get_events(cursor)
            for evt in new_events:
                yield f"data: {json.dumps(evt)}\n\n"
            cursor += len(new_events)
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
