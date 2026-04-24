import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import { DashboardPage } from '../dashboard-page'

const MOCK_SLATE = {
  season_label: '2024 Season',
  policy: { min_edge: 0.05, stake: 1, singles_evaluated_separately_from_parlays: true, same_game_penalty: 0.1, same_team_penalty: 0.05 },
  validation: { input_rows: 10, rows_after_filters: 10, rows_priced: 10, selected_rows: 5, applied_filters: {}, unsupported_stats_seen: [], skipped_rows: {} },
  singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
  parlays: { n_parlays: 2, wins: 1, losses: 1, pushes: 0, staked_units: 2, profit_units: 0.2, roi: 0.1, win_rate: 0.5, avg_expected_value_units: 0.1 },
  baselines: {
    current_policy_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    no_threshold_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    top_edge_only_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    singles_plus_top_parlay_per_week: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
  },
  leaders: { stats: { best: null, worst: null }, books: { best: null, worst: null } },
  interpretation: 'Test interpretation.',
  filter_metadata: { available_seasons: [2024], available_weeks: [1], available_stats: ['passing_yards', 'rushing_yards'], available_books: ['DK'], applied_filters: {} },
  top_picks: [
    { player_id: 'p1', player_name: 'QB One', position: 'QB', season: 2024, week: 1, stat: 'passing_yards', line: 250, book: 'DK', selected_side: 'over', selected_odds: -110, selected_book_implied_prob: 0.524, selected_fair_american: -120, selected_raw_prob: 0.58, selected_prob: 0.58, selected_edge: 0.06, game_id: 'g1', recent_team: 'KC', opponent_team: 'BUF' },
    { player_id: 'p2', player_name: 'RB Two', position: 'RB', season: 2024, week: 1, stat: 'rushing_yards', line: 75, book: 'DK', selected_side: 'over', selected_odds: -115, selected_book_implied_prob: 0.535, selected_fair_american: -130, selected_raw_prob: 0.61, selected_prob: 0.61, selected_edge: 0.075, game_id: 'g2', recent_team: 'SF', opponent_team: 'LAR' },
  ],
  top_parlays: [],
  breakdowns: { stat: [], week: [] },
  source: 'test',
}

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSlate').mockResolvedValue(MOCK_SLATE as any)
  })

  afterEach(() => vi.restoreAllMocks())

  it('renders both picks when no filters active', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => expect(screen.getByText('QB One')).toBeInTheDocument())
    expect(screen.getByText('RB Two')).toBeInTheDocument()
  })

  it('filters picks by position when QB button clicked', async () => {
    const user = userEvent.setup()
    render(<DashboardPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getByRole('button', { name: 'QB' }))

    expect(screen.getByText('QB One')).toBeInTheDocument()
    expect(screen.queryByText('RB Two')).not.toBeInTheDocument()
  })
})
