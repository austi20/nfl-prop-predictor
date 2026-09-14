import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

import * as api from '../../lib/api'
import { useAppStore } from '../../store/app-store'
import { ParlayBuilderPage } from '../parlay-builder-page'
import type { Pick } from '../../lib/types'

const MOCK_PICK: Pick = {
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
  selected_edge: 0.06,
  game_id: 'g1',
  recent_team: 'KC',
  opponent_team: 'BUF',
}

const MOCK_PICK_2: Pick = { ...MOCK_PICK, player_id: 'p2', player_name: 'RB Two', stat: 'rushing_yards', game_id: 'g2' }

function wrapper({ children }: { children: React.ReactNode }) {
  return <MemoryRouter>{children}</MemoryRouter>
}

describe('ParlayBuilderPage', () => {
  beforeEach(() => {
    useAppStore.getState().clearCart()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    useAppStore.getState().clearCart()
  })

  it('shows an empty state with no legs selected', () => {
    render(<ParlayBuilderPage />, { wrapper })
    expect(screen.getByText(/no legs selected yet/i)).toBeInTheDocument()
  })

  it('renders legs already in the slip and removes one on click', async () => {
    const user = userEvent.setup()
    useAppStore.getState().toggleCartPick(MOCK_PICK)
    useAppStore.getState().toggleCartPick(MOCK_PICK_2)

    render(<ParlayBuilderPage />, { wrapper })
    expect(screen.getByText('Slip (2)')).toBeInTheDocument()
    expect(screen.getByText('QB One')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /remove qb one from slip/i }))
    expect(screen.getByText('Slip (1)')).toBeInTheDocument()
    expect(screen.queryByText('QB One')).not.toBeInTheDocument()
  })

  it('calls buildParlays when the price button is clicked with 2+ legs', async () => {
    const user = userEvent.setup()
    useAppStore.getState().toggleCartPick(MOCK_PICK)
    useAppStore.getState().toggleCartPick(MOCK_PICK_2)

    const buildSpy = vi.spyOn(api, 'buildParlays').mockResolvedValue({
      policy: { min_edge: 0.05, stake: 1, singles_evaluated_separately_from_parlays: true, same_game_penalty: 0.1, same_team_penalty: 0.05 },
      parlays: [],
      summary: { n_parlays: 0, wins: 0, losses: 0, pushes: 0, staked_units: 0, profit_units: 0, roi: 0, win_rate: 0, avg_expected_value_units: 0 },
    })

    render(<ParlayBuilderPage />, { wrapper })
    await user.click(screen.getByRole('button', { name: /price parlay combinations/i }))

    await waitFor(() => expect(buildSpy).toHaveBeenCalledOnce())
    expect(buildSpy).toHaveBeenCalledWith([MOCK_PICK, MOCK_PICK_2], 2, 1.0)
  })

  it('clears the whole slip', async () => {
    const user = userEvent.setup()
    useAppStore.getState().toggleCartPick(MOCK_PICK)

    render(<ParlayBuilderPage />, { wrapper })
    await user.click(screen.getByRole('button', { name: /clear all/i }))

    expect(screen.getByText(/no legs selected yet/i)).toBeInTheDocument()
  })
})
