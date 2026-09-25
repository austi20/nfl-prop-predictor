import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { PlayerCard } from '../components/player-card'
import { Card, CardContent } from '../components/ui/card'
import { getPropBoard } from '../lib/api'
import { useCurrentWeek } from '../lib/use-current-week'
import { useAppStore } from '../store/app-store'
import type { Pick } from '../lib/types'

// The week comes from the schedule; only the season is pinned. Bump SEASON at
// the season rollover (this-week-page.tsx has the match).
const SEASON = 2026
const WEEKS = Array.from({ length: 18 }, (_, i) => i + 1)
const SIDES = ['ALL', 'OVER', 'UNDER'] as const
type SideFilter = (typeof SIDES)[number]
const SORTS = ['Best edge', 'Best EV', 'Highest probability'] as const
type SortOption = (typeof SORTS)[number]

function evOf(pick: Pick): number {
  const side = pick.selected_side === 'over' ? pick.over : pick.under
  return side?.ev ?? pick.selected_ev ?? 0
}

function sortPicks(picks: Pick[], sort: SortOption): Pick[] {
  const byEdge = (p: Pick) => p.selected_edge
  const byEv = evOf
  const byProb = (p: Pick) => p.selected_prob
  const key = sort === 'Best EV' ? byEv : sort === 'Highest probability' ? byProb : byEdge
  return [...picks].sort((a, b) => key(b) - key(a))
}

export function DashboardPage() {
  // The live week wins until the user picks one. Kalshi settles a week's
  // markets once it is played, so opening on Week 1 shows an empty board.
  const currentWeek = useCurrentWeek(SEASON)
  const [picked, setPicked] = useState<number | null>(null)
  const week = picked ?? currentWeek
  const setWeek = setPicked
  const [stat, setStat] = useState('ALL')
  const [side, setSide] = useState<SideFilter>('ALL')
  const [sort, setSort] = useState<SortOption>('Best edge')
  const [minEdge, setMinEdge] = useState(0)
  const [search, setSearch] = useState('')

  const isInCart = useAppStore((s) => s.isInCart)
  const toggleCartPick = useAppStore((s) => s.toggleCartPick)
  const cartSize = useAppStore((s) => s.parlayCart.length)

  const { data, isError, error } = useQuery({
    queryKey: ['prop-board', SEASON, week],
    queryFn: ({ signal }) => getPropBoard({ season: SEASON, week: week!, limit: 200 }, signal),
    enabled: week != null,
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (query) => (query.state.data && !query.state.data.ready ? 8000 : false),
  })

  const building = !data || !data.ready

  const stats = data?.stats ?? []

  const picks = useMemo(() => {
    if (!data?.ready) return []
    const q = search.trim().toLowerCase()
    let rows = data.picks
    if (stat !== 'ALL') rows = rows.filter((p) => p.stat === stat)
    if (side !== 'ALL') rows = rows.filter((p) => p.selected_side === side.toLowerCase())
    if (minEdge > 0) rows = rows.filter((p) => p.selected_edge >= minEdge)
    if (q) {
      rows = rows.filter(
        (p) =>
          p.player_name.toLowerCase().includes(q) ||
          p.recent_team.toLowerCase().includes(q) ||
          p.opponent_team.toLowerCase().includes(q),
      )
    }
    return sortPicks(rows, sort)
  }, [data, stat, side, minEdge, search, sort])

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.22),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(244,63,94,0.18),transparent_26%),linear-gradient(180deg,#07111b_0%,#0c1724_100%)] text-slate-50">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 lg:py-8">
        <Card tone="accent">
          <CardContent className="p-6 sm:p-8">
            <div className="font-mono text-[11px] uppercase tracking-[0.26em] text-emerald-200/90">
              {SEASON} season · props
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              Week {week} Prop Board
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
              Kalshi only lists a ladder of yes/no strikes, not a single posted line, so each
              player's line here is the rung trading nearest a coin flip -- close enough to a
              book's number to grade edge against. Model probability vs. that no-vig market price
              is the edge.
            </p>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <span className="font-mono uppercase tracking-[0.18em]">Week</span>
                <select
                  value={week ?? ''}
                  onChange={(e) => setWeek(Number(e.target.value))}
                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-100"
                >
                  {WEEKS.map((w) => (
                    <option key={w} value={w} className="bg-slate-900">
                      {w}
                    </option>
                  ))}
                </select>
              </label>

              <div className="flex overflow-hidden rounded-lg border border-white/10">
                {SIDES.map((s) => (
                  <button
                    key={s}
                    onClick={() => setSide(s)}
                    aria-pressed={side === s}
                    className={`px-3 py-1 text-xs transition-colors ${
                      side === s
                        ? 'bg-emerald-400/20 text-emerald-100'
                        : 'bg-white/5 text-slate-400 hover:bg-white/10'
                    }`}
                  >
                    {s === 'ALL' ? 'Either side' : s.charAt(0) + s.slice(1).toLowerCase()}
                  </button>
                ))}
              </div>

              <label className="flex items-center gap-2 text-xs text-slate-400">
                <span className="font-mono uppercase tracking-[0.18em]">Sort</span>
                <select
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortOption)}
                  className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-sm text-slate-100"
                >
                  {SORTS.map((s) => (
                    <option key={s} value={s} className="bg-slate-900">
                      {s}
                    </option>
                  ))}
                </select>
              </label>

              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search player or team…"
                aria-label="Search props by player or team"
                className="min-w-[10rem] flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300"
              />
            </div>

            {stats.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button
                  onClick={() => setStat('ALL')}
                  aria-pressed={stat === 'ALL'}
                  className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                    stat === 'ALL'
                      ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                      : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                  }`}
                >
                  All markets
                </button>
                {stats.map((s) => (
                  <button
                    key={s}
                    onClick={() => setStat(s)}
                    aria-pressed={stat === s}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      stat === s
                        ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                    }`}
                  >
                    {s.replaceAll('_', ' ')}
                  </button>
                ))}
              </div>
            )}

            <div className="mt-4 flex items-center gap-3">
              <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Min edge</span>
              <input
                type="range"
                min={0}
                max={0.3}
                step={0.01}
                value={minEdge}
                onChange={(e) => setMinEdge(Number(e.target.value))}
                aria-label="Minimum edge filter"
                className="w-40 accent-emerald-400"
              />
              <span className="font-mono text-[11px] text-slate-300">
                {minEdge > 0 ? `+${(minEdge * 100).toFixed(0)}%` : 'Any'}
              </span>
            </div>

            {data?.ready && (
              <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">
                {data.games} games · {picks.length} shown · {data.markets_considered} markets scanned
                {cartSize > 0 ? ` · ${cartSize} in parlay slip` : ''}
              </p>
            )}
          </CardContent>
        </Card>

        {building && !isError && (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-300" />
              <div className="text-sm text-slate-300">Building the Week {week} prop board…</div>
              <div className="max-w-sm text-xs text-slate-500">
                Pulling every open Kalshi NFL player market, finding each player's near-coinflip
                line, and pricing it against the model. First load is the slow one; it is cached
                after that.
              </div>
            </CardContent>
          </Card>
        )}

        {isError && (
          <Card>
            <CardContent className="p-6 text-sm text-rose-300">
              Could not load the prop board: {(error as Error)?.message ?? 'unknown error'}
            </CardContent>
          </Card>
        )}

        {data?.ready && (
          <div className="grid gap-4">
            {picks.length === 0 ? (
              <Card>
                <CardContent className="p-6 text-sm text-slate-400">
                  {search.trim()
                    ? `No props match "${search.trim()}".`
                    : 'No Kalshi markets are trading near a coin flip for this slate yet -- check back closer to kickoff.'}
                </CardContent>
              </Card>
            ) : (
              picks.map((pick) => (
                <PlayerCard
                  key={`${pick.player_id}-${pick.stat}-${pick.line}-${pick.selected_side}`}
                  pick={pick}
                  selected={isInCart(pick)}
                  onToggleSelect={toggleCartPick}
                />
              ))
            )}
          </div>
        )}
      </div>
    </main>
  )
}
