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
    min_ev: float = 0.02
    use_no_vig: bool = True
    max_props_per_player: int = 1
    max_props_per_game: int = 4
    correlation_penalty_enabled: bool = False
    default_stake: float = 1.0
    default_same_game_penalty: float = 0.97
    default_same_team_penalty: float = 0.985
    default_parlay_legs: int = 2
    default_max_parlay_candidates: int = 10

    risk_max_notional_per_order: float = 100.0
    risk_max_open_notional_per_market: float = 500.0
    risk_daily_loss_cap: float = 200.0
    risk_min_edge: float = 0.03
    risk_reject_cooldown_n: int = 3
    risk_reject_cooldown_seconds: float = 60.0
    use_realistic_paper: bool = True
    use_exposure_risk: bool = True
    entry_buffer_seconds: float = 7200.0
    max_yes_inventory_per_market: float = 100.0
    max_no_inventory_per_market: float = 100.0

    default_calibrator_path: str = ""
    training_props_path: Path = Field(default_factory=lambda: Path("docs") / "training" / "synthetic_props_training.csv")
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    weather_source: str = "open-meteo"
    use_live_forecast: bool = False
    # Phase G.5: when True, replay/scoring paths build a future_row via
    # data.upcoming.build_upcoming_row and pass it to model.predict() so the
    # opponent context matches the upcoming game rather than the latest
    # historical row. Default False until Phase H ablation evaluates it.
    use_future_row: bool = False


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
