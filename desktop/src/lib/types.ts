export type ReplayPolicy = {
  min_edge: number
  stake: number
  singles_evaluated_separately_from_parlays: boolean
  same_game_penalty: number
  same_team_penalty: number
}

export type ReplayValidation = {
  input_rows: number
  rows_after_filters: number
  rows_priced: number
  selected_rows: number
  applied_filters: Record<string, unknown>
  unsupported_stats_seen: string[]
  skipped_rows: Record<string, number>
}

export type TradeSummary = {
  n_bets: number
  wins: number
  losses: number
  pushes: number
  staked_units: number
  profit_units: number
  roi: number
  win_rate: number
}

export type ParlaySummary = {
  n_parlays: number
  wins: number
  losses: number
  pushes: number
  staked_units: number
  profit_units: number
  roi: number
  win_rate: number
  avg_expected_value_units: number
}

export type BreakdownRow = {
  season?: number
  week?: number
  stat?: string
  book?: string
  selected_side?: string
  edge_bucket?: string
  n_bets: number
  wins: number
  losses: number
  pushes: number
  staked_units: number
  profit_units: number
  roi: number
  win_rate: number
}

export type SidePrice = {
  side: 'over' | 'under'
  raw_prob: number
  calibrated_prob: number
  book_odds: number
  book_implied_prob: number
  edge: number
  fair_american: number
}

export type DistributionSummary = {
  mean: number
  std: number
  dist_type: string
}

export type FantasyComponent = {
  stat: string
  mean: number
  weight: number
  projected_points: number
  adjustment_multiplier: number
  dist_type: string
}

export type FantasyContextFactor = {
  name: string
  label: string
  multiplier: number
  applied: boolean
  affected_stats: string[]
  reason: string
}

export type FantasySummary = {
  projected_points: number
  median_points: number
  p10_points: number
  p90_points: number
  boom_probability: number
  bust_probability: number
  boom_cutoff: number
  bust_cutoff: number
  scoring_mode: 'full_ppr' | 'half_ppr'
  components: FantasyComponent[]
  context_factors: FantasyContextFactor[]
  omitted_stats: string[]
}

export type Pick = {
  player_id: string
  player_name: string
  position: string
  season: number
  week: number
  stat: string
  line: number
  actual_value?: number | null
  book: string
  selected_side: string
  selected_odds: number
  selected_book_implied_prob: number
  selected_fair_american: number
  selected_raw_prob: number
  selected_prob: number
  selected_edge: number
  result?: string | null
  stake_units?: number | null
  profit_units?: number | null
  game_id: string
  recent_team: string
  opponent_team: string
  over?: SidePrice | null
  under?: SidePrice | null
  distribution?: DistributionSummary | null
  fantasy?: FantasySummary | null
}

export type ParlayRow = {
  season: number
  week: number
  legs: number
  parlay_label: string
  joint_prob: number
  decimal_odds: number
  expected_value_units: number
  same_game_penalty_applied: number
  mean_edge: number
  result: string
  stake_units: number
  profit_units: number
  books: string
}

export type PlayerGameLog = {
  season: number
  week: number
  recent_team: string
  opponent_team: string
  stats: Record<string, number>
}

export type PlayerDetailResponse = {
  player_id: string
  player_name: string
  position: string
  recent_team: string
  latest_season: number | null
  latest_week: number | null
  supported_stats: string[]
  recent_games: PlayerGameLog[]
  replay_picks: Pick[]
}

export type ParlayBuildResponse = {
  policy: ReplayPolicy
  parlays: ParlayRow[]
  summary: ParlaySummary
}

export type FantasyPredictionResponse = FantasySummary & {
  player_id: string
  player_name: string
  position: string
  season: number
  week: number
  recent_team: string
  opponent_team: string
  game_id: string
}

export type FilterMetadata = {
  available_seasons: number[]
  available_weeks: number[]
  available_stats: string[]
  available_books: string[]
  applied_filters: Record<string, unknown>
}

export type IntentStatus = {
  status: string
  intent_id: string
  pick_id: string
  market_id: string
  side: string
  limit_price: number
  size: number
  edge: number
}

export type Portfolio = {
  cash_balance: number
  realized_pnl: number
  unrealized_pnl: number
  positions: Array<{ market_id: string; size: number; avg_price: number; unrealized_pnl: number }>
}

export type ExecutionEvent = {
  kind: string
  ts: string
  intent_id?: string
  event_type?: string
  pick_id?: string
  market_id?: string
  reason?: string
  price?: number
  size?: number
}

export type SlateResponse = {
  season_label: string
  policy: ReplayPolicy
  validation: ReplayValidation
  singles: TradeSummary
  parlays: ParlaySummary
  baselines: {
    current_policy_singles: TradeSummary
    no_threshold_singles: TradeSummary
    top_edge_only_singles: TradeSummary
    singles_plus_top_parlay_per_week: TradeSummary
  }
  leaders: {
    stats: {
      best?: { stat?: string; profit_units: number; roi: number; n_bets: number } | null
      worst?: { stat?: string; profit_units: number; roi: number; n_bets: number } | null
    }
    books: {
      best?: { book?: string; profit_units: number; roi: number; n_bets: number } | null
      worst?: { book?: string; profit_units: number; roi: number; n_bets: number } | null
    }
  }
  interpretation: string
  filter_metadata: FilterMetadata
  top_picks: Pick[]
  top_parlays: ParlayRow[]
  breakdowns: Record<string, BreakdownRow[]>
  source: string
}
