"""SQLite engine/session bootstrap for trading persistence.

KISS: `create_all` on first connect. Move to alembic migrations when the
schema starts churning (see docs/modernization_plan.md Phase 0 note).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.db.models import Base

SessionFactory = Callable[[], Session]


def make_session_factory(db_path: Path) -> SessionFactory:
    """Create the SQLite engine, ensure schema exists, return a session factory."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
