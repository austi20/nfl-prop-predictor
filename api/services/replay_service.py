from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from api.schemas import (
    BreakdownRow,
    FilterMetadata,
    NormalizedPick,
    ParlayRow,
    ReplaySummaryResponse,
    SlateResponse,
)
from api.settings import AppSettings
from api.services.fantasy_service import build_fantasy_summary
from data.nflverse_loader import load_weekly
from eval.replay_pipeline import run_replay, save_replay_report


_PLAYER_INFO_COLS = ["player_id", "player_name", "position", "recent_team"]


@dataclass(frozen=True)
class ReplayArtifacts:
    season_label: str
    summary_payload: dict[str, Any]
    picks: pd.DataFrame
    parlay_rows: pd.DataFrame
    breakdowns: dict[str, pd.DataFrame]
    source: str


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _safe_read_json(path: Path) -> Any:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_filter_metadata(
    picks: pd.DataFrame,
    summary_payload: dict[str, Any],
) -> FilterMetadata:
    return FilterMetadata(
        available_seasons=sorted({int(value) for value in picks.get("season", pd.Series(dtype=int)).dropna().tolist()}),
        available_weeks=sorted({int(value) for value in picks.get("week", pd.Series(dtype=int)).dropna().tolist()}),
        available_stats=sorted({str(value) for value in picks.get("stat", pd.Series(dtype=object)).dropna().tolist()}),
        available_books=sorted(
            {
                str(value)
                for value in picks.get("book", pd.Series(dtype=object)).dropna().tolist()
                if str(value).strip()
            }
        ),
        applied_filters=summary_payload.get("validation", {}).get("applied_filters", {}),
    )


def _normalize_breakdowns(breakdowns: dict[str, pd.DataFrame]) -> dict[str, list[BreakdownRow]]:
    normalized: dict[str, list[BreakdownRow]] = {}
    for name, frame in breakdowns.items():
        records = frame.to_dict("records") if not frame.empty else []
        normalized[name] = [BreakdownRow.model_validate(record) for record in records]
    return normalized


def _player_lookup_df(settings: AppSettings, seasons: list[int]) -> pd.DataFrame:
    years = sorted(set(list(settings.default_train_years) + seasons))
    weekly = load_weekly(years)
    player_df = weekly[_PLAYER_INFO_COLS].copy()
    return player_df.drop_duplicates(subset=["player_id"], keep="last")


def _enrich_picks(settings: AppSettings, picks: pd.DataFrame, seasons: list[int]) -> list[NormalizedPick]:
    if picks.empty:
        return []
    lookup = _player_lookup_df(settings, seasons)
    merged = picks.merge(lookup, how="left", on="player_id", suffixes=("", "_lookup"))
    if "player_name" not in merged.columns:
        merged["player_name"] = ""
    if "player_name_lookup" in merged.columns:
        merged["player_name"] = merged["player_name"].where(merged["player_name"].notna(), merged["player_name_lookup"])
    if "position" not in merged.columns:
        merged["position"] = ""
    merged["player_name"] = merged["player_name"].fillna("")
    merged["position"] = merged["position"].fillna("")
    records = merged.to_dict("records")
    return [NormalizedPick.model_validate(record) for record in records]


def _normalize_parlays(parlays: pd.DataFrame) -> list[ParlayRow]:
    if parlays.empty:
        return []
    return [ParlayRow.model_validate(record) for record in parlays.to_dict("records")]


def _attach_fantasy_summaries(
    settings: AppSettings,
    picks: list[NormalizedPick],
) -> list[NormalizedPick]:
    enriched: list[NormalizedPick] = []
    for pick in picks:
        try:
            fantasy = build_fantasy_summary(
                settings,
                player_id=pick.player_id,
                season=pick.season,
                week=pick.week,
                position=pick.position,
                recent_team=pick.recent_team,
                opponent_team=pick.opponent_team,
                game_id=pick.game_id,
                scoring_mode="full_ppr",
            )
            enriched.append(pick.model_copy(update={"fantasy": fantasy}))
        except ValueError:
            enriched.append(pick)
    return enriched


def _summary_files(settings: AppSettings) -> list[Path]:
    return sorted(settings.docs_dir.glob("paper_trade_summary_*.json"))


def _artifact_label_from_summary(path: Path) -> str:
    prefix = "paper_trade_summary_"
    suffix = ".json"
    name = path.name
    return name[len(prefix) : -len(suffix)]


def _load_artifacts_from_docs(settings: AppSettings) -> ReplayArtifacts | None:
    summaries = _summary_files(settings)
    if not summaries:
        return None

    summary_path = max(summaries, key=lambda path: path.stat().st_mtime)
    season_label = _artifact_label_from_summary(summary_path)
    summary_payload = _safe_read_json(summary_path)
    if summary_payload is None:
        return None

    picks = _safe_read_csv(settings.docs_dir / f"paper_trade_picks_{season_label}.csv")
    parlays = _safe_read_csv(settings.docs_dir / f"paper_trade_parlays_{season_label}.csv")

    breakdowns: dict[str, pd.DataFrame] = {}
    for name in ("season", "week", "stat", "book", "selected_side", "edge_bucket"):
        frame = _safe_read_csv(settings.docs_dir / f"paper_trade_breakdown_by_{name}_{season_label}.csv")
        breakdowns[name] = frame

    return ReplayArtifacts(
        season_label=season_label,
        summary_payload=summary_payload,
        picks=picks,
        parlay_rows=parlays,
        breakdowns=breakdowns,
        source="replay_artifacts",
    )


def _generate_seed_replay(settings: AppSettings) -> ReplayArtifacts:
    replay_years = list(settings.default_replay_years)
    report = run_replay(
        props_path=settings.sample_props_path,
        train_years=list(settings.default_train_years),
        replay_years=replay_years,
        min_edge=settings.default_min_edge,
        stake=settings.default_stake,
        same_game_penalty=settings.default_same_game_penalty,
        same_team_penalty=settings.default_same_team_penalty,
        parlay_legs=settings.default_parlay_legs,
        max_parlay_candidates=settings.default_max_parlay_candidates,
    )
    season_label = "-".join(str(year) for year in replay_years)
    save_replay_report(report, settings.docs_dir, season_label)
    return ReplayArtifacts(
        season_label=season_label,
        summary_payload=report["summary_payload"],
        picks=report["picks"],
        parlay_rows=report["parlays"],
        breakdowns=report["breakdowns"],
        source="generated_from_sample_props",
    )


@lru_cache(maxsize=8)
def load_replay_artifacts(
    docs_dir: str,
    sample_props_path: str,
    train_years: tuple[int, ...],
    replay_years: tuple[int, ...],
    min_edge: float,
    stake: float,
    same_game_penalty: float,
    same_team_penalty: float,
    parlay_legs: int,
    max_parlay_candidates: int,
) -> ReplayArtifacts:
    settings = AppSettings(
        docs_dir=Path(docs_dir),
        sample_props_path=Path(sample_props_path),
        default_train_years=train_years,
        default_replay_years=replay_years,
        default_min_edge=min_edge,
        default_stake=stake,
        default_same_game_penalty=same_game_penalty,
        default_same_team_penalty=same_team_penalty,
        default_parlay_legs=parlay_legs,
        default_max_parlay_candidates=max_parlay_candidates,
    )
    artifacts = _load_artifacts_from_docs(settings)
    if artifacts is not None:
        return artifacts
    return _generate_seed_replay(settings)


def get_replay_artifacts(settings: AppSettings) -> ReplayArtifacts:
    return load_replay_artifacts(
        str(settings.docs_dir),
        str(settings.sample_props_path),
        tuple(settings.default_train_years),
        tuple(settings.default_replay_years),
        settings.default_min_edge,
        settings.default_stake,
        settings.default_same_game_penalty,
        settings.default_same_team_penalty,
        settings.default_parlay_legs,
        settings.default_max_parlay_candidates,
    )


def build_replay_summary_response(settings: AppSettings) -> ReplaySummaryResponse:
    artifacts = get_replay_artifacts(settings)
    summary_payload = artifacts.summary_payload
    seasons = summary_payload.get("context", {}).get("replay_years", list(settings.default_replay_years))
    filter_metadata = _build_filter_metadata(artifacts.picks, summary_payload)
    return ReplaySummaryResponse.model_validate(
        {
            **summary_payload,
            "filter_metadata": filter_metadata.model_dump(),
            "picks": [pick.model_dump() for pick in _enrich_picks(settings, artifacts.picks, seasons)],
            "parlay_rows": [row.model_dump() for row in _normalize_parlays(artifacts.parlay_rows)],
            "breakdowns": {
                name: [row.model_dump() for row in rows]
                for name, rows in _normalize_breakdowns(artifacts.breakdowns).items()
            },
            "source": artifacts.source,
        }
    )


def build_slate_response(settings: AppSettings) -> SlateResponse:
    summary = build_replay_summary_response(settings)
    breakdowns = {
        name: rows[:3]
        for name, rows in summary.breakdowns.items()
        if name in {"week", "stat", "book"}
    }
    top_picks = sorted(summary.picks, key=lambda pick: pick.selected_edge, reverse=True)[:8]
    top_picks = _attach_fantasy_summaries(settings, top_picks)
    top_parlays = sorted(summary.parlay_rows, key=lambda row: row.expected_value_units, reverse=True)[:5]
    return SlateResponse.model_validate(
        {
            "season_label": summary.season_label,
            "policy": summary.policy.model_dump(),
            "validation": summary.validation.model_dump(),
            "singles": summary.singles.model_dump(),
            "parlays": summary.parlays.model_dump(),
            "baselines": summary.baselines.model_dump(),
            "leaders": summary.leaders.model_dump(),
            "interpretation": summary.interpretation,
            "filter_metadata": summary.filter_metadata.model_dump(),
            "top_picks": [pick.model_dump() for pick in top_picks],
            "top_parlays": [parlay.model_dump() for parlay in top_parlays],
            "breakdowns": {
                name: [row.model_dump() for row in rows]
                for name, rows in breakdowns.items()
            },
            "source": summary.source,
        }
    )
