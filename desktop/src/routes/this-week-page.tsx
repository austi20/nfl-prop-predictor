import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { Card, CardContent } from '../components/ui/card'
import { TierBadge } from '../components/tier-badge'
import { getFantasySlate } from '../lib/api'
import { num } from '../lib/format'
import { useCurrentWeek } from '../lib/use-current-week'
import type { FantasySlateEntry, FantasySlateResponse } from '../lib/types'

// The week comes from the schedule; only the season is pinned. Bump SEASON at
// the season rollover (dashboard-page.tsx has the match).
const SEASON = 2026
const WEEKS = Array.from({ length: 18 }, (_, i) => i + 1)
const VIEWS = ['ALL', 'QB', 'RB', 'WR', 'TE', 'FLEX'] as const
type ViewFilter = (typeof VIEWS)[number]
type Scoring = 'full_ppr' | 'half_ppr'

const POS_TONE: Record<string, string> = {
  QB: 'bg-sky-400/15 text-sky-200 border-sky-400/30',
  RB: 'bg-emerald-400/15 text-emerald-200 border-emerald-400/30',
  WR: 'bg-amber-400/15 text-amber-200 border-amber-400/30',
  TE: 'bg-fuchsia-400/15 text-fuchsia-200 border-fuchsia-400/30',
}

// Which rank/tier fields a given view reads. ALL -> cumulative board, a single
// position -> that position's list, FLEX -> the RB/WR/TE flex pool.
function fieldsFor(view: ViewFilter): { rank: keyof FantasySlateEntry; tier: keyof FantasySlateEntry } {
  if (view === 'ALL') return { rank: 'overall_rank', tier: 'overall_tier' }
  if (view === 'FLEX') return { rank: 'flex_rank', tier: 'flex_tier' }
  return { rank: 'position_rank', tier: 'position_tier' }
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

// Out and Doubtful mean no start; everything else is a risk flag.
function InjuryBadge({ status }: { status: string }) {
  const severe = status === 'Out' || status === 'Doubtful'
  return (
    <span
      className={`shrink-0 rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase ${
        severe
          ? 'border-rose-400/40 bg-rose-500/15 text-rose-200'
          : 'border-amber-400/40 bg-amber-400/10 text-amber-200'
      }`}
    >
      {status}
    </span>
  )
}

function SlateRow({ rank, tier, entry }: { rank: number; tier: string; entry: FantasySlateEntry }) {
  return (
    <Link
      to={`/player/${encodeURIComponent(entry.player_id)}`}
      aria-label={`${rank}. ${entry.player_name || entry.player_id}, ${entry.position} ${entry.recent_team} vs ${entry.opponent_team}, ${tier}. Projected ${num(entry.projected_points)} points, range ${num(entry.floor_points)} to ${num(entry.ceiling_points)}.`}
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
          {entry.injury_status && <InjuryBadge status={entry.injury_status} />}
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

type TierGroup = { key: string; label: string; rows: FantasySlateEntry[] }

function groupByTier(
  rows: FantasySlateEntry[],
  view: ViewFilter,
  data: FantasySlateResponse,
): TierGroup[] {
  const { tier } = fieldsFor(view)
  const buckets = new Map<string, FantasySlateEntry[]>()
  for (const row of rows) {
    const key = (row[tier] as string) || 'do_not_play'
    const list = buckets.get(key) ?? []
    list.push(row)
    buckets.set(key, list)
  }
  return data.tier_order
    .filter((key) => buckets.has(key))
    .map((key) => ({ key, label: data.tier_labels[key] ?? key, rows: buckets.get(key)! }))
}

export function ThisWeekPage() {
  // Week follows the schedule until the user picks one, so the board opens on
  // the week actually being played rather than Week 1.
  const currentWeek = useCurrentWeek(SEASON)
  const [picked, setPicked] = useState<number | null>(null)
  const week = picked ?? currentWeek
  const setWeek = setPicked
  const [scoring, setScoring] = useState<Scoring>('full_ppr')
  const [view, setView] = useState<ViewFilter>('ALL')
  const [search, setSearch] = useState('')

  const { data, isError, error } = useQuery({
    queryKey: ['fantasy-slate', SEASON, week, scoring],
    // limit 0 asks for the whole board; matches the sidecar's prewarm key so
    // the first open is a cache hit.
    queryFn: ({ signal }) =>
      getFantasySlate({ season: SEASON, week: week!, scoring, limit: 0 }, signal),
    enabled: week != null,
    // Matches the sidecar cache age, so injury news shows on the next visit.
    staleTime: 1000 * 60 * 30,
    gcTime: 1000 * 60 * 60,
    // The board is one slow build per key. Never fan out: no retry, no refetch
    // on focus/reconnect. While the sidecar reports not-ready, poll every 8s.
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchInterval: (query) => (query.state.data && !query.state.data.ready ? 8000 : false),
  })

  const building = !data || !data.ready

  const groups = useMemo(() => {
    if (!data?.ready) return []
    const { rank } = fieldsFor(view)
    const q = search.trim().toLowerCase()
    let rows = data.entries
    if (view === 'FLEX') rows = rows.filter((e) => e.flex_rank != null)
    else if (view !== 'ALL') rows = rows.filter((e) => e.position === view)
    if (q) {
      rows = rows.filter(
        (e) =>
          e.player_name.toLowerCase().includes(q) ||
          e.recent_team.toLowerCase().includes(q) ||
          e.opponent_team.toLowerCase().includes(q),
      )
    }
    rows = [...rows].sort((a, b) => (a[rank] as number) - (b[rank] as number))
    return groupByTier(rows, view, data)
  }, [data, view, search])

  const shown = useMemo(() => groups.reduce((n, g) => n + g.rows.length, 0), [groups])
  const { rank: rankField } = fieldsFor(view)

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
              Projected fantasy points for every startable skill player on the Week {week} slate, cut
              into start/sit tiers against a 12-team league's starter demand. Switch the view for a
              per-position, flex, or cumulative ranking. Tap a player for the full breakdown.
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
                {VIEWS.map((v) => (
                  <button
                    key={v}
                    onClick={() => setView(v)}
                    aria-pressed={view === v}
                    className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                      view === v
                        ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                        : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                    }`}
                  >
                    {v === 'ALL' ? 'Cumulative' : v}
                  </button>
                ))}
              </div>

              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search player or team…"
                aria-label="Search players by name or team"
                className="min-w-[12rem] flex-1 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-300"
              />
            </div>

            {data?.ready && (
              <p className="mt-4 font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">
                {data.games} games · {shown} shown · {data.players_considered} players ranked
              </p>
            )}
          </CardContent>
        </Card>

        {building && !isError && (
          <Card>
            <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
              <div className="h-8 w-8 animate-spin rounded-full border-2 border-emerald-400/30 border-t-emerald-300" />
              <div className="text-sm text-slate-300">Building Week {week} projections…</div>
              <div className="max-w-sm text-xs text-slate-500">
                The first load of a slate runs a full simulation for every player and can take a
                couple of minutes. It is cached after that, and refreshes here automatically.
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

        {data?.ready && (
          <div className="flex flex-col gap-6">
            {shown === 0 ? (
              <Card>
                <CardContent className="p-6 text-sm text-slate-400">
                  {search.trim()
                    ? `No players match "${search.trim()}".`
                    : `No ${view === 'ALL' ? '' : `${view} `}projections for this slate.`}
                </CardContent>
              </Card>
            ) : (
              groups.map((group) => (
                <section key={group.key} className="flex flex-col gap-2">
                  <div className="flex items-center gap-3 px-1">
                    <TierBadge tier={group.key} label={group.label} />
                    <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">
                      {group.rows.length} player{group.rows.length === 1 ? '' : 's'}
                    </span>
                    <div className="h-px flex-1 bg-white/10" />
                  </div>
                  {group.rows.map((entry) => (
                    <SlateRow
                      key={entry.player_id}
                      rank={entry[rankField] as number}
                      tier={group.label}
                      entry={entry}
                    />
                  ))}
                </section>
              ))
            )}
          </div>
        )}
      </div>
    </main>
  )
}
