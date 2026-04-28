"""Download and cache nflverse tables used for training, weather joins, and synthetic props.

Run from repo root:
  uv run python scripts/prefetch_training_cache.py

Uses parquet under cache/; skips re-download while files are fresher than 24h unless --force.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from data.nflverse_loader import (
    load_injuries,
    load_schedules,
    load_weekly,
    load_weekly_with_weather,
)

# Trailing-window props need the season before the earliest target year.
WEEKLY_YEARS = list(range(2014, 2026))  # 2014–2025
SCHEDULE_YEARS = list(range(2018, 2026))  # aligns with weather backfill default
INJURY_YEARS = list(range(2015, 2026))
WEATHER_JOIN_YEARS = list(range(2015, 2026))


def main() -> None:
    parser = argparse.ArgumentParser(description="Prefetch nflverse parquet caches.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh caches even if younger than 24h",
    )
    args = parser.parse_args()
    fr = args.force

    print("load_weekly", WEEKLY_YEARS)
    wk = load_weekly(WEEKLY_YEARS, force_refresh=fr)
    print(f"  rows={len(wk):,} -> {wk['season'].min()}-{wk['season'].max()}")

    print("load_schedules", SCHEDULE_YEARS)
    sch = load_schedules(SCHEDULE_YEARS, force_refresh=fr)
    print(f"  rows={len(sch):,}")

    print("load_injuries", INJURY_YEARS)
    inj = load_injuries(INJURY_YEARS, force_refresh=fr)
    print(f"  rows={len(inj):,}")

    print("load_weekly_with_weather", WEATHER_JOIN_YEARS, "(requires cache/weather_archive.parquet for outdoor columns)")
    wkw = load_weekly_with_weather(WEATHER_JOIN_YEARS, force_refresh=fr)
    print(f"  rows={len(wkw):,}")

    print("Done.")


if __name__ == "__main__":
    main()
