from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"]
    app_name: str
    docs_dir: str
    sample_props_path: str
    replay_artifacts_available: bool
    default_replay_years: list[int]
    weather_source: str
    llama_cpp_base_url: str


class ReplayContext(BaseModel):
    replay_years: list[int] = Field(default_factory=list)
    weeks: list[int] = Field(default_factory=list)
    stats: list[str] = Field(default_factory=list)
    books: list[str] = Field(default_factory=list)
    calibrator_path: str = ""


class ReplayPolicy(BaseModel):
    min_edge: float
    min_ev: float | None = None
    stake: float
    singles_evaluated_separately_from_parlays: bool = True
    same_game_penalty: float
    same_team_penalty: float
    max_picks_per_week: int | None = None
    max_picks_per_player: int | None = None
    max_picks_per_game: int | None = None


class ReplaySkippedRows(BaseModel):
    unsupported_stat: int = 0
    missing_odds: int = 0
    missing_actual_outcome: int = 0
    no_selection_edge_threshold: int = 0
    no_bet: int = 0
    max_picks_per_week: int = 0
    max_picks_per_player: int = 0
    max_picks_per_game: int = 0


class ReplayValidation(BaseModel):
    input_rows: int = 0
    rows_after_filters: int = 0
    rows_priced: int = 0
    selected_rows: int = 0
    weather_archive_available: bool = False
    applied_filters: dict[str, Any] = Field(default_factory=dict)
    unsupported_stats_seen: list[str] = Field(default_factory=list)
    skipped_rows: ReplaySkippedRows = Field(default_factory=ReplaySkippedRows)


class TradeSummary(BaseModel):
    n_bets: float = 0.0
    wins: float = 0.0
    losses: float = 0.0
    pushes: float = 0.0
    staked_units: float = 0.0
    profit_units: float = 0.0
    roi: float = 0.0
    win_rate: float = 0.0


class ParlaySummary(BaseModel):
    n_parlays: float = 0.0
    wins: float = 0.0
    losses: float = 0.0
    pushes: float = 0.0
    staked_units: float = 0.0
    profit_units: float = 0.0
    roi: float = 0.0
    win_rate: float = 0.0
    avg_expected_value_units: float = 0.0


class ReplayBaselines(BaseModel):
    current_policy_singles: TradeSummary = Field(default_factory=TradeSummary)
    no_threshold_singles: TradeSummary = Field(default_factory=TradeSummary)
    top_edge_only_singles: TradeSummary = Field(default_factory=TradeSummary)
    singles_plus_top_parlay_per_week: TradeSummary = Field(default_factory=TradeSummary)


class LeaderSnapshot(BaseModel):
    profit_units: float
    roi: float
    n_bets: float
    stat: str | None = None
    book: str | None = None


class ReplayLeadersGroup(BaseModel):
    best: LeaderSnapshot | None = None
    worst: LeaderSnapshot | None = None


class ReplayLeaders(BaseModel):
    stats: ReplayLeadersGroup = Field(default_factory=ReplayLeadersGroup)
    books: ReplayLeadersGroup = Field(default_factory=ReplayLeadersGroup)


class FilterMetadata(BaseModel):
    available_seasons: list[int] = Field(default_factory=list)
    available_weeks: list[int] = Field(default_factory=list)
    available_stats: list[str] = Field(default_factory=list)
    available_books: list[str] = Field(default_factory=list)
    applied_filters: dict[str, Any] = Field(default_factory=dict)


class BreakdownRow(BaseModel):
    season: int | None = None
    week: int | None = None
    stat: str | None = None
    book: str | None = None
    selected_side: str | None = None
    edge_bucket: str | None = None
    n_bets: float = 0.0
    wins: float = 0.0
    losses: float = 0.0
    pushes: float = 0.0
    staked_units: float = 0.0
    profit_units: float = 0.0
    roi: float = 0.0
    win_rate: float = 0.0


class SidePrice(BaseModel):
    side: Literal["over", "under"]
    raw_prob: float
    calibrated_prob: float
    book_odds: float
    book_implied_prob: float
    market_no_vig_prob: float | None = None
    edge: float
    ev: float | None = None
    fair_american: float


class DistributionSummary(BaseModel):
    mean: float
    std: float
    dist_type: str


class WeatherSummary(BaseModel):
    temp_f: float | None = None
    wind_mph: float | None = None
    wind_dir_deg: float | None = None
    precip_in: float | None = None
    precip_prob: float | None = None
    weather_code: float | None = None
    indoor: bool | None = None


class FantasyComponent(BaseModel):
    stat: str
    mean: float
    weight: float
    projected_points: float
    adjustment_multiplier: float = 1.0
    dist_type: str = ""


class FantasyContextFactor(BaseModel):
    name: str
    label: str
    multiplier: float = 1.0
    applied: bool = False
    affected_stats: list[str] = Field(default_factory=list)
    reason: str = ""


class FantasySummary(BaseModel):
    projected_points: float
    median_points: float
    p10_points: float
    p90_points: float
    boom_probability: float
    bust_probability: float
    boom_cutoff: float
    bust_cutoff: float
    scoring_mode: Literal["full_ppr", "half_ppr"] = "full_ppr"
    components: list[FantasyComponent] = Field(default_factory=list)
    context_factors: list[FantasyContextFactor] = Field(default_factory=list)
    omitted_stats: list[str] = Field(default_factory=list)


class NormalizedPick(BaseModel):
    player_id: str
    player_name: str = ""
    position: str = ""
    season: int
    week: int
    stat: str
    line: float
    actual_value: float | None = None
    book: str = ""
    selected_side: str
    selected_odds: int
    selected_book_implied_prob: float
    selected_fair_american: float
    selected_raw_prob: float
    selected_prob: float
    selected_edge: float
    result: str | None = None
    stake_units: float | None = None
    profit_units: float | None = None
    game_id: str = ""
    recent_team: str = ""
    opponent_team: str = ""
    over: SidePrice | None = None
    under: SidePrice | None = None
    distribution: DistributionSummary | None = None
    weather: WeatherSummary | None = None
    injury_status: Literal["Q", "D", "O", "IR", "PUP"] | None = None
    model_p_over_calibrated: float | None = None
    model_p_under_calibrated: float | None = None
    market_p_over_no_vig: float | None = None
    market_p_under_no_vig: float | None = None
    ev_over: float | None = None
    ev_under: float | None = None
    selected_ev: float | None = None
    recommendation: Literal["over", "under", "no_bet"] | None = None
    confidence: Literal["high", "med", "low"] | None = None
    top_drivers: list[str] = Field(default_factory=list)
    fantasy: FantasySummary | None = None


class ParlayRow(BaseModel):
    season: int
    week: int
    legs: int
    parlay_label: str
    joint_prob: float
    decimal_odds: float
    expected_value_units: float
    same_game_penalty_applied: float
    mean_edge: float
    result: str
    stake_units: float
    profit_units: float
    books: str = ""


class ReplaySummaryResponse(BaseModel):
    season_label: str
    context: ReplayContext
    policy: ReplayPolicy
    validation: ReplayValidation
    singles: TradeSummary
    parlays: ParlaySummary
    baselines: ReplayBaselines
    leaders: ReplayLeaders
    interpretation: str
    filter_metadata: FilterMetadata
    picks: list[NormalizedPick] = Field(default_factory=list)
    parlay_rows: list[ParlayRow] = Field(default_factory=list)
    breakdowns: dict[str, list[BreakdownRow]] = Field(default_factory=dict)
    source: str = "replay_artifacts"


class SlateResponse(BaseModel):
    season_label: str
    policy: ReplayPolicy
    validation: ReplayValidation
    singles: TradeSummary
    parlays: ParlaySummary
    baselines: ReplayBaselines
    leaders: ReplayLeaders
    interpretation: str
    filter_metadata: FilterMetadata
    top_picks: list[NormalizedPick] = Field(default_factory=list)
    top_parlays: list[ParlayRow] = Field(default_factory=list)
    breakdowns: dict[str, list[BreakdownRow]] = Field(default_factory=dict)
    source: str = "replay_artifacts"


class PlayerGameLog(BaseModel):
    season: int
    week: int
    recent_team: str = ""
    opponent_team: str = ""
    stats: dict[str, float] = Field(default_factory=dict)


class PlayerDetailResponse(BaseModel):
    player_id: str
    player_name: str = ""
    position: str = ""
    recent_team: str = ""
    latest_season: int | None = None
    latest_week: int | None = None
    supported_stats: list[str] = Field(default_factory=list)
    recent_games: list[PlayerGameLog] = Field(default_factory=list)
    replay_picks: list[NormalizedPick] = Field(default_factory=list)


class PropEvaluationRequest(BaseModel):
    player_id: str
    season: int
    week: int
    stat: str
    line: float
    over_odds: int
    under_odds: int
    opponent_team: str
    book: str = ""
    game_id: str = ""
    recent_team: str = ""
    calibrator_path: str = ""


class PropEvaluationResponse(BaseModel):
    pick: NormalizedPick
    selected_side: str
    selected_edge: float
    policy: ReplayPolicy


class FantasyPredictionRequest(BaseModel):
    player_id: str
    season: int
    week: int
    position: str = ""
    opponent_team: str = ""
    recent_team: str = ""
    game_id: str = ""
    scoring_mode: Literal["full_ppr", "half_ppr"] = "full_ppr"


class FantasyPredictionResponse(FantasySummary):
    player_id: str
    player_name: str = ""
    position: str = ""
    season: int
    week: int
    recent_team: str = ""
    opponent_team: str = ""
    game_id: str = ""


class ParlayBuildRequest(BaseModel):
    picks: list[NormalizedPick] = Field(default_factory=list)
    legs: int = 2
    max_candidates: int = 10
    same_game_penalty: float = 0.97
    same_team_penalty: float = 0.985
    stake: float = 1.0


class ParlayBuildResponse(BaseModel):
    policy: ReplayPolicy
    parlays: list[ParlayRow] = Field(default_factory=list)
    summary: ParlaySummary = Field(default_factory=ParlaySummary)


class AnalystStreamEvent(BaseModel):
    event: Literal["status", "token", "tool_call", "complete", "error"]
    message: str = ""
    token: str = ""
    tool_call: dict[str, Any] | None = None
    complete: bool = False
    error: str = ""
