from __future__ import annotations

import json
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["analyst"])

_SYSTEM = (
    "You are an NFL prop betting analyst. "
    "Answer concisely using the context provided. "
    "If you need data, call the appropriate tool."
)


class AnalystRequest(BaseModel):
    question: str
    player_id: str = ""
    stat: str = ""
    line: float | None = None


async def _stream_llm(base_url: str, request: AnalystRequest) -> AsyncIterator[str]:
    messages = [{"role": "system", "content": _SYSTEM}]
    if request.player_id or request.stat or request.line is not None:
        ctx_parts = []
        if request.player_id:
            ctx_parts.append(f"player_id={request.player_id}")
        if request.stat:
            ctx_parts.append(f"stat={request.stat}")
        if request.line is not None:
            ctx_parts.append(f"line={request.line}")
        messages.append({"role": "user", "content": f"Context: {', '.join(ctx_parts)}"})
    messages.append({"role": "user", "content": request.question})

    payload = {
        "model": "qwen",
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
        "max_tokens": 512,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream(
                "POST",
                f"{base_url}/v1/chat/completions",
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    yield f'data: {json.dumps({"event": "error", "error": f"LLM returned {resp.status_code}"})}\n\n'
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                        delta = chunk["choices"][0]["delta"]
                        token = delta.get("content") or ""
                        if token:
                            yield f'data: {json.dumps({"event": "token", "token": token})}\n\n'
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        except httpx.ConnectError:
            yield f'data: {json.dumps({"event": "error", "error": "LLM server not reachable. Start llama.cpp on port 8080."})}\n\n'
        except Exception as exc:  # noqa: BLE001
            yield f'data: {json.dumps({"event": "error", "error": str(exc)})}\n\n'

    yield f'data: {json.dumps({"event": "complete", "complete": True})}\n\n'


@router.post("/analyst/stream")
async def analyst_stream(payload: AnalystRequest, request: Request) -> StreamingResponse:
    settings = request.app.state.settings
    return StreamingResponse(
        _stream_llm(settings.llama_cpp_base_url, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
