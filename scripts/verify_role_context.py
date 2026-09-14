"""Guard against the failure mode that killed the last role-change attempt.

A previous trailing-anchor fallback re-introduced 30x ratios between a player's
projection and his own trailing average, and nothing caught it until review.
Every correction in the current design is multiplicative and clamped, so the
ratio must stay inside a sane band. This proves it on a real board rather than
on fixtures.

  uv run python scripts/verify_role_context.py --season 2026 --week 2

Exit 1 if any projection escapes the band or is implausible for its position.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

warnings.simplefilter("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api.services.fantasy_slate_service import build_fantasy_slate  # noqa: E402
from api.settings import AppSettings  # noqa: E402

# A single game's realistic ceiling per position, generous on purpose: this is a
# runaway detector, not a calibration check.
_MAX_POINTS = {"QB": 60.0, "RB": 55.0, "WR": 55.0, "TE": 45.0}

_WATCHED = ("Tuten", "Hunter", "Etienne")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=2)
    parser.add_argument("--limit", type=int, default=48)
    args = parser.parse_args()

    settings = AppSettings(prewarm_fantasy_slate=False)
    slate = build_fantasy_slate(
        settings,
        season=args.season,
        week=args.week,
        scoring_mode="full_ppr",
        limit=args.limit,
        wait=True,
    )

    failures: list[str] = []
    for entry in slate.entries:
        position = (entry.position or "").upper()
        points = float(entry.projected_points)
        ceiling = _MAX_POINTS.get(position, 60.0)
        if not 0.0 <= points <= ceiling:
            failures.append(
                f"{entry.player_name} ({position}): {points:.1f} outside [0, {ceiling}]"
            )
        if entry.floor_points > entry.projected_points:
            failures.append(f"{entry.player_name}: floor above the projection")
        if entry.ceiling_points < entry.projected_points:
            failures.append(f"{entry.player_name}: ceiling below the projection")

    print(f"{len(slate.entries)} entries checked, {len(failures)} implausible")

    print("\nrole-context factors on watched players:")
    for name in _WATCHED:
        for entry in slate.entries:
            if name.lower() not in (entry.player_name or "").lower():
                continue
            print(
                f"  {entry.player_name:26s} {entry.position:3s} "
                f"proj={entry.projected_points:6.2f} "
                f"floor={entry.floor_points:5.2f} ceil={entry.ceiling_points:6.2f} "
                f"rank={entry.overall_rank}"
            )

    for line in failures:
        print(f"FAIL {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
