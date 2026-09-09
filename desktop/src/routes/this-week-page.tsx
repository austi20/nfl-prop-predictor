import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { Card, CardContent } from '../components/ui/card'
import { getFantasySlate } from '../lib/api'
import { num } from '../lib/format'
import type { FantasySlateEntry } from '../lib/types'

// The app has no season/week service yet; Week 1 of the 2026 season is the live
// slate. Bump SEASON here at the season rollover.
const SEASON = 2026
const WEEKS = Array.from({ length: 18 }, (_, i) => i + 1)
const POSITIONS = ['ALL', 'QB', 'RB', 'WR', 'TE'] as const
type PositionFilter = (typeof POSITIONS)[number]
type Scoring = 'full_ppr' | 'half_ppr'

const POS_TONE: Record<string, string> = {
  QB: 'bg-sky-400/15 text-sky-200 border-sky-400/30',
  RB: 'bg-emerald-400/15 text-emerald-200 border-emerald-400/30',
  WR: 'bg-amber-400/15 text-amber-200 border-amber-400/30',
  TE: 'bg-fuchsia-400/15 text-fuchsia-200 border-fuchsia-400/30',
}

function RangeBar({ entry }: { entry: FantasySlateEntry }) {
  // Floor and ceiling placed on a shared 0..40 PPR scale so rows compare visually.
  const scale = 40
  const lo = Math.max(0, Math.min(100, (entry.floor_points / scale) * 100))
  const hi = Math.max(0, Math.min(100, (entry.ceiling_points / scale) * 100))
  const mid = Math.max(0, Math.min(100, (entry.projected_points / scale) * 100))
  return (
    <div className="relative h-2 w-full rounded-full bg-white/10">
      <div
        className="absolute h-2 rounded-full bg-gradient-to-r from-rose-400/40 via-emerald-400/50 to-cyan-300/50"
        style={{ left: `${lo}%`, width: `${Math.max(2, hi - lo)}%` }}
      />
      <div
        className="absolute top-1/2 h-3 w-1 -translate-y-1/2 rounded-full bg-emerald-200"
        style={{ left: `${mid}%` }}
      />
    </div>
  )
}

function SlateRow({ rank, entry }: { rank: number; entry: FantasySlateEntry }) {
  return (
    <Link
      to={`/player/${encodeURIComponent(entry.player_id)}`}
      aria-label={`${rank}. ${entry.player_name || entry.player_id}, ${entry.position} ${entry.recent_team} vs ${entry.opponent_team}. Projected ${num(entry.projected_points)} points, range ${num(entry.floor_points)} to ${num(entry.ceiling_points)}.`}
      className="grid grid-cols-[2rem_1fr_auto] items-center gap-4 rounded-2xl border border-white/10 bg-white/5 px-4 py-3 transition-colors hover:border-emerald-400/30 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300 sm:grid-cols-[2rem_1.4fr_1.1fr_auto]"
    >
      <div className="font-mono text-sm text-slate-500">{rank}</div>

      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
              POS_TONE[entry.position] ?? 'bg-white/10 text-slate-300 border-white/20'
            }`}
          >
            {entry.position || '—'}
          </span>
          <span className="truncate text-sm font-semibold text-slate-50">
            {entry.player_name || entry.player_id}
          </span>
        </div>
        <div className="mt-1 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-400">
          {entry.recent_team} vs {entry.opponent_team}
          {entry.kickoff ? ` · ${entry.kickoff}` : ''}
        </div>
      </div>

      <div className="hidden flex-col gap-1 sm:flex">
        <RangeBar entry={entry} />
        <div className="flex justify-between font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">
          <span>flr {num(entry.floor_points)}</span>
          <span className="text-emerald-300">boom {Math.round(entry.boom_probability * 100)}%</span>
          <span>ceil {num(entry.ceiling_points)}</span>
        </div>
      </div>

      <div className="text-right">
        <div className="text-2xl font-semibold text-white">{num(entry.projected_points)}</div>
        <div className="font-mono text-[10px] uppercase tracking-[0.16em] text-slate-500">proj pts</div>
      </div>
    </Link>
  )
}

export function ThisWeekPage() {
  const [week, setWeek] = useState(1)
  const [scoring, setScoring] = useState<Scoring>('full_ppr')
  const [position, setPosition] = useState<PositionFilter>('ALL')

  const { data, isLoading, isError, error, isFetching } = useQuery({
    queryKey: ['fantasy-slate', SEASON, week, scoring],
    // limit matches the sidecar's startup prewarm key so the first open is a cache hit.
    queryFn: () => getFantasySlate({ season: SEASON, week, scoring, limit: 48 }),
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60,
    retry: 1,
  })

  const rows = useMemo(() => {
    const entries = data?.entries ?? []
    return position === 'ALL' ? entries : entries.filter((e) => e.position === position)
  }, [data?.entries, position])

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.22),transparent_34%),linear-gradient(180deg,#07111b_0%,#0c1724_100%)] text-slate-50">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-4 py-6 sm:px-6 lg:py-8">
        <Card tone="accent">
          <CardContent className="p-6 sm:p-8">
            <div className="font-mono text-[11px] uppercase tracking-[0.26em] text-emerald-200/90">
              {SEASON} season · fantasy
            </div>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
              Week {week} Fantasy Board
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
              Projected fantasy points for every startable skill player on the Week {week} slate.
              Recency-weighted player form, regressed to a positional baseline, with matchup, QB
              support, and injury context folded in. Tap a player for the full breakdown.
            </p>

            <div className="mt-5 flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-2 text-xs text-slate-400">
                <span className="font-mono uppercase tracking-[0.18em]">Week</span>
                <select
                  value={week}
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
                {(['full_ppr', 'half_ppr'] as Scoring[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setScoring(mode)}
                    aria-pressed={scoring === mode}
                    className={`px-3 py-1 text-xs transition-colors ${
                      scoring === mode
                        ? 'bg-emerald-400/20 text-emerald-100'
                        : 'bg-white/5 text-slate-400 hover:bg-white/10'
                    }`}
                  >
                    {mode === 'full_ppr' ? 'Full PPR' : 'Half PPR'}
                  </button>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                {POSITIONS.map((pos) => (
                  <button
                    key={pos}
                    onClick={() => setPosition(pos)}
                    aria-pressed={position === pos}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      position === pos
                        ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                    }`}
                  >
                    {pos}
                  </button>
                ))}
              </div>
            </div>

            {data && (
              <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">
                {data.games} games · {rows.length} shown · {data.players_considered} players ranked
                {isFetching ? ' · refreshing' : ''}
              </p>
            )}
          </CardContent>
        </Card>

        {isLoading && (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-300" />
              <div className="text-sm text-slate-300">Building Week {week} projections…</div>
              <div className="max-w-sm text-xs text-slate-500">
                The first load of a slate runs a full simulation for every player and can take a
                couple of minutes. It is cached after that.
              </div>
            </CardContent>
          </Card>
        )}

        {isError && (
          <Card>
            <CardContent className="p-6 text-sm text-rose-300">
              Could not load the slate: {(error as Error)?.message ?? 'unknown error'}
            </CardContent>
          </Card>
        )}

        {data && !isLoading && (
          <div className="flex flex-col gap-2">
            {rows.length === 0 ? (
              <Card>
                <CardContent className="p-6 text-sm text-slate-400">
                  No {position === 'ALL' ? '' : `${position} `}projections for this slate.
                </CardContent>
              </Card>
            ) : (
              rows.map((entry, i) => (
                <SlateRow key={entry.player_id} rank={i + 1} entry={entry} />
              ))
            )}
          </div>
        )}
      </div>
    </main>
  )
}
