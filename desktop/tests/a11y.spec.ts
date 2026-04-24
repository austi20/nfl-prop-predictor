import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

const MOCK_SLATE = {
  season_label: '2024 Season',
  policy: {
    min_edge: 0.05,
    stake: 1,
    singles_evaluated_separately_from_parlays: true,
    same_game_penalty: 0.1,
    same_team_penalty: 0.05,
  },
  validation: {
    input_rows: 10,
    rows_after_filters: 10,
    rows_priced: 10,
    selected_rows: 5,
    applied_filters: {},
    unsupported_stats_seen: [],
    skipped_rows: {},
  },
  singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
  parlays: { n_parlays: 2, wins: 1, losses: 1, pushes: 0, staked_units: 2, profit_units: 0.2, roi: 0.1, win_rate: 0.5, avg_expected_value_units: 0.1 },
  baselines: {
    current_policy_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    no_threshold_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    top_edge_only_singles: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
    singles_plus_top_parlay_per_week: { n_bets: 5, wins: 3, losses: 2, pushes: 0, staked_units: 5, profit_units: 0.5, roi: 0.1, win_rate: 0.6 },
  },
  leaders: { stats: { best: null, worst: null }, books: { best: null, worst: null } },
  interpretation: 'Test interpretation text.',
  filter_metadata: {
    available_seasons: [2024],
    available_weeks: [1, 2],
    available_stats: ['passing_yards', 'rushing_yards'],
    available_books: ['DraftKings'],
    applied_filters: {},
  },
  top_picks: [],
  top_parlays: [],
  breakdowns: {},
  source: 'test',
}

const MOCK_PLAYER = {
  player_id: 'test-player',
  player_name: 'Test Player',
  position: 'QB',
  recent_team: 'KC',
  latest_season: 2024,
  latest_week: 1,
  supported_stats: ['passing_yards'],
  recent_games: [],
  replay_picks: [],
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/slate', (route) => route.fulfill({ json: MOCK_SLATE }))
  await page.route('**/api/players/**', (route) => route.fulfill({ json: MOCK_PLAYER }))
})

test('dashboard has no WCAG 2.2 AA violations', async ({ page }) => {
  await page.goto('/')
  await page.waitForSelector('h1')
  const results = await new AxeBuilder({ page }).withTags(['wcag22aa']).analyze()
  expect(results.violations).toEqual([])
})

test('player detail has no WCAG 2.2 AA violations', async ({ page }) => {
  await page.goto('/player/test-player')
  await page.waitForSelector('h1')
  const results = await new AxeBuilder({ page }).withTags(['wcag22aa']).analyze()
  expect(results.violations).toEqual([])
})

test('parlay builder has no WCAG 2.2 AA violations', async ({ page }) => {
  await page.goto('/parlays')
  await page.waitForSelector('h1')
  const results = await new AxeBuilder({ page }).withTags(['wcag22aa']).analyze()
  expect(results.violations).toEqual([])
})
