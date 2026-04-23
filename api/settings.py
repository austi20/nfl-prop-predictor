from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from data.nflverse_loader import TRAIN_YEARS


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NFL_APP_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "NFL Prop Predictor API"
    api_prefix: str = "/api"
    host: str = "127.0.0.1"
    port: int = 8000

    docs_dir: Path = Field(default_factory=lambda: Path("docs"))
    cache_dir: Path = Field(default_factory=lambda: Path("cache"))
    model_dir: Path = Field(default_factory=lambda: Path("models"))
    sample_props_path: Path = Field(default_factory=lambda: Path("docs") / "synthetic_replay_props.csv")

    default_train_years: tuple[int, ...] = tuple(TRAIN_YEARS[:-1])
    default_replay_years: tuple[int, ...] = (2024,)
    default_min_edge: float = 0.05
    default_stake: float = 1.0
    default_same_game_penalty: float = 0.97
    default_same_team_penalty: float = 0.985
    default_parlay_legs: int = 2
    default_max_parlay_candidates: int = 10

    default_calibrator_path: str = ""
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    weather_source: str = "open-meteo"


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
