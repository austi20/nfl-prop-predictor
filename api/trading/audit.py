from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def log_event(kind: str, payload: dict[str, Any], out_dir: Path = Path("docs/audit")) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"events-{date.today()}.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps({"kind": kind, **payload}, default=_default) + "\n")
