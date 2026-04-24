from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.server import create_app
from api.settings import AppSettings


def _settings() -> AppSettings:
    return AppSettings(
        docs_dir=Path("docs"),
        sample_props_path=Path("docs") / "synthetic_replay_props.csv",
    )


def _client() -> TestClient:
    return TestClient(create_app(_settings()))


def _mock_llama_stream(sse_lines: list[str]):
    """Build a mock httpx.AsyncClient context manager that yields given SSE lines."""

    async def aiter_lines():
        for line in sse_lines:
            yield line

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.aiter_lines = aiter_lines

    mock_stream_cm = AsyncMock()
    mock_stream_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_cm)

    mock_client_cm = AsyncMock()
    mock_client_cm.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_client_cm


def _parse_events(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw and raw != "[DONE]":
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return events


def test_tool_call_event_emitted():
    """A tool-call delta from llama.cpp produces a tool_call SSE frame."""
    tool_call_chunk = {
        "choices": [
            {
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "function": {
                                "name": "get_player_stats",
                                "arguments": '{"player_id": "xyz"}',
                            },
                        }
                    ]
                }
            }
        ]
    }
    lines = [f"data: {json.dumps(tool_call_chunk)}", "data: [DONE]"]

    with patch("api.routes.analyst.httpx.AsyncClient", return_value=_mock_llama_stream(lines)):
        resp = _client().post(
            "/api/analyst/stream",
            json={"question": "test"},
        )

    assert resp.status_code == 200
    events = _parse_events(resp.text)

    tool_call_events = [e for e in events if e.get("event") == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0]["name"] == "get_player_stats"
    assert tool_call_events[0]["args"] == '{"player_id": "xyz"}'
