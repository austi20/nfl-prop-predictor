from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

# `api.server` builds the app at import time, which spawns the fantasy-slate and
# prop-board prewarm threads. Those do real Kalshi scans and real model fits, and
# the prop-board one holds a process-wide lock for as long as it runs -- so any
# test that touches the board races it and can get BoardBuilding. Set before the
# first AppSettings is constructed, which conftest import order guarantees.
os.environ.setdefault("NFL_APP_PREWARM_PROP_BOARD", "0")
os.environ.setdefault("NFL_APP_PREWARM_FANTASY_SLATE", "0")
os.environ.setdefault("NFL_APP_REFRESH_FEEDS_ON_START", "0")


@pytest.fixture
def tmp_path() -> Path:
    path = Path("tmp") / "test-artifacts" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()
