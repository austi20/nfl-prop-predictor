import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import { DashboardPage } from '../dashboard-page'

const MOCK_BOARD = {
  season: 2026,
  week: 1,
  ready: true,
  games: 2,
  markets_considered: 40,
  stats: ['passing_yards', 'rushing_yards'],
  picks: [
    {
      player_id: 'p1',
      player_name: 'QB One',
      position: 'QB',
      season: 2026,
      week: 1,
      stat: 'passing_yards',
      line: 250,
      book: 'kalshi',
      selected_side: 'over',
      selected_odds: -110,
      selected_book_implied_prob: 0.524,
      selected_fair_american: -120,
      selected_raw_prob: 0.58,
      selected_prob: 0.58,
      selected_edge: 0.09,
      game_id: 'g1',
      recent_team: 'KC',
      opponent_team: 'BUF',
      weather: { temp_f: 42, wind_mph: 18, precip_in: 0, indoor: false },
      injury_status: 'Q',
      market_p_over_no_vig: 0.5,
      market_p_under_no_vig: 0.5,
      ev_over: 0.11,
      ev_under: -0.12,
      recommendation: 'over',
      confidence: 'high',
      top_drivers: ['wind 18mph'],
    },
    {
      player_id: 'p2',
      player_name: 'RB Two',
      position: 'RB',
      season: 2026,
      week: 1,
      stat: 'rushing_yards',
      line: 75,
      book: 'kalshi',
      selected_side: 'over',
      selected_odds: -115,
      selected_book_implied_prob: 0.535,
      selected_fair_american: -130,
      selected_raw_prob: 0.61,
      selected_prob: 0.61,
      selected_edge: 0.075,
      game_id: 'g2',
      recent_team: 'SF',
      opponent_team: 'LAR',
    },
  ],
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
    // The page reads the live week off the schedule before it asks for a board.
    vi.spyOn(api, 'getSchedule').mockResolvedValue({ season: 2026, current_week: 1 })
    vi.spyOn(api, 'getPropBoard').mockResolvedValue(MOCK_BOARD as any)
  })

  afterEach(() => vi.restoreAllMocks())

  it('renders both picks when no filters active', async () => {
    render(<DashboardPage />, { wrapper })
    await waitFor(() => expect(screen.getByText('QB One')).toBeInTheDocument())
    expect(screen.getByText('RB Two')).toBeInTheDocument()
  })

  it('filters picks by market when a stat chip is clicked', async () => {
    const user = userEvent.setup()
    render(<DashboardPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getByRole('button', { name: 'passing yards' }))

    expect(screen.getByText('QB One')).toBeInTheDocument()
    expect(screen.queryByText('RB Two')).not.toBeInTheDocument()
  })

  it('opens the decision drawer from a player card', async () => {
    const user = userEvent.setup()
    render(<DashboardPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    await user.click(screen.getAllByRole('button', { name: /why this bet/i })[0])

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText('Recommendation')).toBeInTheDocument()
    expect(screen.getByText('wind 18mph')).toBeInTheDocument()
  })

  it('adds a pick to the parlay slip', async () => {
    const user = userEvent.setup()
    render(<DashboardPage />, { wrapper })
    await waitFor(() => screen.getByText('QB One'))

    const addButtons = screen.getAllByRole('button', { name: /add to slip/i })
    await user.click(addButtons[0])

    expect(screen.getAllByRole('button', { name: /in slip/i })[0]).toBeInTheDocument()
  })
})
