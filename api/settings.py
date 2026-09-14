from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from data.nflverse_loader import TRAIN_YEARS, app_root, bundle_root

# Two roots so paths resolve no matter the process cwd, and so the packaged
# sidecar writes to a user-writable dir instead of read-only Program Files.
#   _ROOT   - writable: cache/, docs/ (telemetry, audit)   -> %LOCALAPPDATA% when frozen
#   _BUNDLE - read-only: models/ (bundled config artifacts) -> next to the exe when frozen
# In a source checkout both are the repo root.
_ROOT = app_root()
_BUNDLE = bundle_root()


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

    docs_dir: Path = Field(default_factory=lambda: _ROOT / "docs")
    cache_dir: Path = Field(default_factory=lambda: _ROOT / "cache")
    model_dir: Path = Field(default_factory=lambda: _BUNDLE / "models")
    sample_props_path: Path = Field(default_factory=lambda: _ROOT / "docs" / "synthetic_replay_props.csv")

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
    training_props_path: Path = Field(default_factory=lambda: _ROOT / "docs" / "training" / "synthetic_props_training.csv")
    llama_cpp_base_url: str = "http://127.0.0.1:8080"
    weather_source: str = "open-meteo"
    # Open-Meteo forecast for the fantasy weather multiplier (free, no key).
    # Independent of `use_weather`, which gates the GLM weather *features*.
    use_live_forecast: bool = True
    # Phase G.5: when True, scoring paths build a future_row via
    # data.upcoming.build_upcoming_row and pass it to model.predict() so the
    # opponent context matches the upcoming game rather than the latest
    # historical row. Enabled for the 2026 season once the cold-start guards
    # (is_home drop, prior-season shrinkage n, trailing-mean clamp) landed —
    # see docs/season_eve_2026_dryrun.md.
    use_future_row: bool = True
    # Phase H5 lock (v0.8c): default False. Cross-season Phase H walk-forward
    # evidence showed mean max_reliability_dev of 0.44-0.48 against synthetic
    # surrogate odds — high enough to motivate calibration, but the metric is
    # against synthetic labels, not real market lines, so a calibrator fit on
    # this data may not transfer. Recommendation: leave False until v0.9 ships
    # real captured Kalshi quotes (see plan.md Season-Start checklist), then
    # fit a calibrator on the held-out 2025 data plus first weeks of real
    # quotes. See docs/ModelingNotes.md "Phase H5 calibration deferral".
    use_calibration: bool = False
    # Build + cache the Week-1 fantasy board on startup (off-thread) so the
    # desktop app's landing view is instant instead of a multi-minute sim.
    # Tests and one-off scripts pass this False. Disable via
    # NFL_APP_PREWARM_FANTASY_SLATE=0.
    prewarm_fantasy_slate: bool = True
    # Anchor projections to the Kalshi coin-flip line where one is priced. Best
    # effort: coverage is thin and a market outage falls back to model priors.
    # Disable via NFL_APP_USE_MARKET_ANCHOR=0.
    use_market_anchor: bool = True
    # Process-pool size for the fantasy-slate player loop. 0 = auto
    # (~70% of cores). 1 disables the pool (serial). Env NFL_APP_FANTASY_SLATE_WORKERS.
    fantasy_slate_workers: int = 0

    # Tuned downstream-of-anchor projection parameters (eval/fantasy_calibration).
    # Points at the locked artifact; a missing file falls back to built-in
    # defaults inside load_calibration. Env NFL_APP_FANTASY_CALIBRATION_PATH.
    fantasy_calibration_path: str = str(_BUNDLE / "models" / "fantasy_calibration.json")

    # Build + cache the Week-1 prop board on startup (off-thread), same reason
    # as the fantasy slate prewarm -- it is a Kalshi scan plus a model call per
    # market. Disable via NFL_APP_PREWARM_PROP_BOARD=0.
    prewarm_prop_board: bool = True

    # Kalshi market data — refreshes the game-script total when a game's market
    # is priced (thin until near kickoff; falls back to the schedule line).
    # Reads the bare KALSHI_* names so the .pem/key can be shared with NBABets v2.
    kalshi_api_key_id: str = Field(
        default="", validation_alias=AliasChoices("KALSHI_API_KEY_ID", "NFL_APP_KALSHI_API_KEY_ID")
    )
    kalshi_private_key_path: str = Field(
        default="", validation_alias=AliasChoices("KALSHI_PRIVATE_KEY_PATH", "NFL_APP_KALSHI_PRIVATE_KEY_PATH")
    )
    kalshi_base_url: str = Field(
        default="https://api.elections.kalshi.com/trade-api/v2",
        validation_alias=AliasChoices("KALSHI_BASE_URL", "NFL_APP_KALSHI_BASE_URL"),
    )


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
