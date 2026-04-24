import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import type { IntentStatus } from '../../lib/types'
import { ExecutionPage } from '../execution-page'

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
  singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.1, roi: 0.1, win_rate: 1 },
  parlays: { n_parlays: 0, wins: 0, losses: 0, pushes: 0, staked_units: 0, profit_units: 0, roi: 0, win_rate: 0, avg_expected_value_units: 0 },
  baselines: {
    current_policy_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.1, roi: 0.1, win_rate: 1 },
    no_threshold_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.1, roi: 0.1, win_rate: 1 },
    top_edge_only_singles: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.1, roi: 0.1, win_rate: 1 },
    singles_plus_top_parlay_per_week: { n_bets: 1, wins: 1, losses: 0, pushes: 0, staked_units: 1, profit_units: 0.1, roi: 0.1, win_rate: 1 },
  },
  leaders: { stats: { best: null, worst: null }, books: { best: null, worst: null } },
  interpretation: '',
  filter_metadata: { available_seasons: [2024], available_weeks: [1], available_stats: ['passing_yards'], available_books: ['DK'], applied_filters: {} },
  top_picks: [MOCK_PICK],
  top_parlays: [],
  breakdowns: {},
  source: 'test',
}

const MOCK_INTENT: IntentStatus = {
  status: 'filled',
  intent_id: 'ord-abc',
  pick_id: 'p1-passing_yards-1',
  market_id: 'PAPER-P1-PASS',
  side: 'yes',
  limit_price: 0.58,
  size: 1,
  edge: 0.06,
} as any

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <QueryClientProvider client={qc}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

describe('ExecutionPage', () => {
  beforeEach(() => {
    vi.spyOn(api, 'getSlate').mockResolvedValue(MOCK_SLATE as any)
    vi.spyOn(api, 'getPortfolio').mockResolvedValue({ cash_balance: 0, realized_pnl: 0, unrealized_pnl: 0, positions: [] })
    vi.spyOn(api, 'streamExecutionEvents').mockResolvedValue(undefined)
    vi.spyOn(api, 'getExecutionEvents').mockResolvedValue([])
  })
  afterEach(() => vi.restoreAllMocks())

  it('always shows the paper mode banner', async () => {
    render(<ExecutionPage />, { wrapper })
    await waitFor(() => screen.getByText(/Paper mode — no real money/i))
    expect(screen.getByText(/Paper mode — no real money/i)).toBeInTheDocument()
  })

  it('renders pick from slate in queue', async () => {
    render(<ExecutionPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))
    expect(screen.getByText('QB One')).toBeInTheDocument()
  })

  it('shows submitted intent after submit', async () => {
    vi.spyOn(api, 'submitPicks').mockResolvedValue({ data: [MOCK_INTENT] } as any)
    const user = userEvent.setup()
    render(<ExecutionPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getByRole('button', { name: 'Submit' }))

    await waitFor(() => screen.getByText('filled'))
    expect(screen.getByText('filled')).toBeInTheDocument()
  })

  it('flips intent to canceled after cancel click', async () => {
    vi.spyOn(api, 'submitPicks').mockResolvedValue({ data: [{ ...MOCK_INTENT, status: 'submitted' }] } as any)
    vi.spyOn(api, 'cancelIntent').mockResolvedValue({ status: 'canceled', intent_id: 'ord-abc' })
    const user = userEvent.setup()
    render(<ExecutionPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))
    await user.click(screen.getByRole('button', { name: 'Submit' }))
    await waitFor(() => screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => screen.getByText('canceled'))
    expect(screen.getByText('canceled')).toBeInTheDocument()
  })

  it('shows KILLED on kill switch button after kill', async () => {
    vi.spyOn(api, 'killSwitch').mockResolvedValue({ killed: 0, reason: 'user_initiated' })
    const user = userEvent.setup()
    render(<ExecutionPage />, { wrapper })
    await waitFor(() => screen.getByText('KILL SWITCH'))
    await user.click(screen.getByText('KILL SWITCH').closest('button')!)
    await waitFor(() => screen.getByText('KILLED'))
    expect(screen.getByText('KILLED').closest('button')).toBeDisabled()
  })
})
