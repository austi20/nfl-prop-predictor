"""DB-backed kill switch (NBABets v2 `TradingKillSwitch` pattern).

Singleton row in SQLite. Checked before any order submission; trippable and
resettable from the API so the desktop UI can wire start/stop/kill controls.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from api.db import SessionFactory
from api.db.models import TradingKillSwitch


class SqlKillSwitch:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sessions = session_factory

    def is_killed(self) -> bool:
        with self._sessions() as session:
            row = session.get(TradingKillSwitch, 1)
            return bool(row and (row.killed or row.flatten))

    def status(self) -> dict[str, Any]:
        with self._sessions() as session:
            row = session.get(TradingKillSwitch, 1)
            if row is None:
                return {"killed": False, "flatten": False, "reason": "", "set_at": None, "set_by": ""}
            return {
                "killed": row.killed,
                "flatten": row.flatten,
                "reason": row.reason,
                "set_at": row.set_at.isoformat() if row.set_at else None,
                "set_by": row.set_by,
            }

    def trip(self, reason: str, *, set_by: str = "api", flatten: bool = False) -> None:
        now = datetime.now(timezone.utc)
        with self._sessions() as session:
            row = session.get(TradingKillSwitch, 1)
            if row is None:
                row = TradingKillSwitch(id=1)
                session.add(row)
            row.killed = True
            row.flatten = flatten
            row.reason = reason
            row.set_at = now
            row.set_by = set_by
            session.commit()

    def reset(self, *, set_by: str = "api") -> None:
        now = datetime.now(timezone.utc)
        with self._sessions() as session:
            row = session.get(TradingKillSwitch, 1)
            if row is None:
                return
            row.killed = False
            row.flatten = False
            row.reason = ""
            row.set_at = now
            row.set_by = set_by
            session.commit()
