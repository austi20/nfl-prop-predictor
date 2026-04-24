import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import { ParlayBuilderPage } from '../parlay-builder-page'

const MOCK_PICK = {
  player_id: 'p1',
  player_name: 'QB One',
  position: 'QB',
  season: 2024,
  week: 1,
  stat: 'passing_yards',
  line: 250,
  book: 'DK',
  selected_side: 'over',
  selected_odds: -110,
  selected_book_implied_prob: 0.524,
  selected_fair_american: -120,
  selected_raw_prob: 0.58,
  selected_prob: 0.58,
  selected_edge: 0.06,
  game_id: 'g1',
  recent_team: 'KC',
  opponent_team: 'BUF',
}

const MOCK_SLATE = {
  season_label: '2024 Season',
  policy: { min_edge: 0.05, stake: 1, singles_evaluated_separately_from_parlays: true, same_game_penalty: 0.1, same_team_penalty: 0.05 },
  validation: { input_rows: 1, rows_after_filters: 1, rows_priced: 1, selected_rows: 1, applied_filters: {}, unsupported_stats_seen: [], skipped_rows: {} },
  singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.5, roi: 0.5, win_rate: 1 },
  parlays: { n_parlays: 0, wins: 0, losses: 0, pushes: 0, staked_units: 0, profit_units: 0, roi: 0, win_rate: 0, avg_expected_value_units: 0 },
  baselines: {
    current_policy_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.5, roi: 0.5, win_rate: 1 },
    no_threshold_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.5, roi: 0.5, win_rate: 1 },
    top_edge_only_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.5, roi: 0.5, win_rate: 1 },
    singles_plus_top_parlay_per_week: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.5, roi: 0.5, win_rate: 1 },
  },
  leaders: { stats: { best: null, worst: null }, books: { best: null, worst: null } },
  interpretation: '',
  filter_metadata: { available_seasons: [2024], available_weeks: [1], available_stats: ['passing_yards'], available_books: ['DK'], applied_filters: {} },
  top_picks: [MOCK_PICK, { ...MOCK_PICK, player_id: 'p2', player_name: 'RB Two', stat: 'rushing_yards', game_id: 'g2' }],
  top_parlays: [],
  breakdowns: {},
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

describe('ParlayBuilderPage', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSlate').mockResolvedValue(MOCK_SLATE as any)
  })

  afterEach(() => vi.restoreAllMocks())

  it('adds pick to cart on click', async () => {
    const user = userEvent.setup()
    render(<ParlayBuilderPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getByRole('button', { name: /QB One/i }))
    expect(screen.getByText('Cart (1)')).toBeInTheDocument()
  })

  it('removes pick from cart on second click', async () => {
    const user = userEvent.setup()
    render(<ParlayBuilderPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    const pickBtn = screen.getByRole('button', { name: /QB One/i })
    await user.click(pickBtn)
    await user.click(pickBtn)
    expect(screen.getByText('Cart (0)')).toBeInTheDocument()
  })

  it('calls buildParlays when Build button clicked with 2+ picks', async () => {
    const user = userEvent.setup()
    const buildSpy = vi.spyOn(api, 'buildParlays').mockResolvedValue({
      policy: MOCK_SLATE.policy as any,
      parlays: [],
      summary: { n_parlays: 0, wins: 0, losses: 0, pushes: 0, staked_units: 0, profit_units: 0, roi: 0, win_rate: 0, avg_expected_value_units: 0 },
    })
    render(<ParlayBuilderPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getByRole('button', { name: /QB One/i }))
    await user.click(screen.getByRole('button', { name: /RB Two/i }))
    await user.click(screen.getByRole('button', { name: /Build Parlays/i }))

    await waitFor(() => expect(buildSpy).toHaveBeenCalledOnce())
  })
})
