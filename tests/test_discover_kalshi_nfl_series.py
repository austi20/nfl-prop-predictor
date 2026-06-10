from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.discover_kalshi_nfl_series import (
    SeriesRecord,
    discover_nfl_series,
    write_series_json,
)


def _fake_response(status_code: int, payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_discover_filters_to_nfl_prefix() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = _fake_response(
        200,
        {
            "series": [
                {"ticker": "KXNFLPASSYDS", "title": "NFL Pass Yards"},
                {"ticker": "KXNBAPTS", "title": "NBA Points"},
                {"ticker": "KXNFLRUSHYDS", "title": "NFL Rush Yards"},
            ],
            "cursor": "",
        },
    )

    records = discover_nfl_series(
        http_client=fake_client,
        kalshi_client=MagicMock(auth_headers=MagicMock(return_value={})),
        prefix="KXNFL",
    )

    tickers = {r.ticker for r in records}
    assert tickers == {"KXNFLPASSYDS", "KXNFLRUSHYDS"}


def test_discover_follows_cursor_pagination() -> None:
    fake_client = MagicMock()
    fake_client.get.side_effect = [
        _fake_response(
            200,
            {
                "series": [{"ticker": "KXNFLA", "title": "A"}],
                "cursor": "PAGE2",
            },
        ),
        _fake_response(
            200,
            {
                "series": [{"ticker": "KXNFLB", "title": "B"}],
                "cursor": "",
            },
        ),
    ]

    records = discover_nfl_series(
        http_client=fake_client,
        kalshi_client=MagicMock(auth_headers=MagicMock(return_value={})),
        prefix="KXNFL",
    )

    assert [r.ticker for r in records] == ["KXNFLA", "KXNFLB"]
    assert fake_client.get.call_count == 2


def test_write_series_json_round_trip(tmp_path: Path) -> None:
    records = [
        SeriesRecord(ticker="KXNFLPASSYDS", title="NFL Pass Yards"),
        SeriesRecord(ticker="KXNFLRUSHYDS", title="NFL Rush Yards"),
    ]
    out = tmp_path / "kalshi_nfl_series.json"
    write_series_json(records, out)

    payload = json.loads(out.read_text())
    assert payload["count"] == 2
    assert payload["prefix"] == "KXNFL"
    assert {item["ticker"] for item in payload["series"]} == {
        "KXNFLPASSYDS",
        "KXNFLRUSHYDS",
    }


def test_discover_empty_response_is_ok() -> None:
    fake_client = MagicMock()
    fake_client.get.return_value = _fake_response(
        200, {"series": [], "cursor": ""}
    )
    records = discover_nfl_series(
        http_client=fake_client,
        kalshi_client=MagicMock(auth_headers=MagicMock(return_value={})),
        prefix="KXNFL",
    )
    assert records == []


def test_discover_raises_on_http_error() -> None:
    import httpx

    fake_client = MagicMock()
    failing = MagicMock()
    failing.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom", request=MagicMock(), response=MagicMock(status_code=500)
    )
    fake_client.get.return_value = failing

    with pytest.raises(httpx.HTTPStatusError):
        discover_nfl_series(
            http_client=fake_client,
            kalshi_client=MagicMock(auth_headers=MagicMock(return_value={})),
            prefix="KXNFL",
        )
