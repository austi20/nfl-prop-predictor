import { useQuery } from '@tanstack/react-query'
import { Activity, BadgeDollarSign, LayoutPanelTop, ShieldCheck } from 'lucide-react'
import { useMemo, useState } from 'react'

import { GlossaryTooltip } from '../components/glossary-tooltip'
import { PlayerCard } from '../components/player-card'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { getSlate } from '../lib/api'
import type { BreakdownRow } from '../lib/types'

function metric(value: number, suffix = '') {
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}${suffix}`
}

function BreakdownTable({
  label,
  rows,
  valueKey,
}: {
  label: string
  rows: BreakdownRow[]
  valueKey: 'profit_units' | 'roi' | 'win_rate'
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {rows.map((row, index) => {
            const rowLabel =
              row.stat ??
              row.book ??
              (row.week ? `Week ${row.week}` : undefined) ??
              row.selected_side ??
              row.edge_bucket ??
              `Row ${index + 1}`

            return (
              <div
                key={`${label}-${rowLabel}-${index}`}
                className="flex items-center justify-between rounded-2xl border border-white/10 bg-white/5 px-4 py-3"
              >
                <div>
                  <div className="text-sm font-medium text-slate-100">{rowLabel}</div>
                  <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">
                    {row.n_bets} bets
                  </div>
                </div>
                <div className="font-mono text-sm text-emerald-200">
                  {valueKey === 'profit_units'
                    ? metric(row.profit_units, 'u')
                    : `${(row[valueKey] * 100).toFixed(1)}%`}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}

export function DashboardPage() {
  const { data: slate, isLoading } = useQuery({ queryKey: ['slate'], queryFn: getSlate })

  const availablePositions = useMemo(
    () => [...new Set((slate?.top_picks ?? []).map((p) => p.position).filter(Boolean))].sort(),
    [slate?.top_picks],
  )
  const availableStats = slate?.filter_metadata.available_stats ?? []

  const [selectedPositions, setSelectedPositions] = useState<string[]>([])
  const [minEdge, setMinEdge] = useState(0)
  const [selectedStats, setSelectedStats] = useState<string[]>([])

  const filteredPicks = useMemo(() => {
    return (slate?.top_picks ?? []).filter((pick) => {
      if (selectedPositions.length > 0 && !selectedPositions.includes(pick.position)) return false
      if (pick.selected_edge < minEdge) return false
      if (selectedStats.length > 0 && !selectedStats.includes(pick.stat)) return false
      return true
    })
  }, [slate?.top_picks, selectedPositions, minEdge, selectedStats])

  function toggleItem(list: string[], item: string, setter: (v: string[]) => void) {
    setter(list.includes(item) ? list.filter((x) => x !== item) : [...list, item])
  }

  if (isLoading || !slate) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        Loading slate...
      </div>
    )
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.22),transparent_34%),radial-gradient(circle_at_bottom_right,rgba(244,63,94,0.18),transparent_26%),linear-gradient(180deg,#07111b_0%,#0c1724_100%)] text-slate-50">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-8 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <section className="grid gap-5 lg:grid-cols-[1.4fr_0.6fr]">
          <Card tone="accent" className="overflow-hidden">
            <CardContent className="relative p-6 sm:p-8">
              <div className="absolute inset-y-0 right-0 hidden w-80 bg-[radial-gradient(circle_at_center,rgba(16,185,129,0.16),transparent_55%)] lg:block" />
              <div className="relative max-w-3xl">
                <div className="font-mono text-[11px] uppercase tracking-[0.26em] text-emerald-200/90">
                  {slate.season_label}
                </div>
                <h1 className="mt-4 max-w-2xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                  NFL Prop Workstation
                </h1>
                <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                  Props priced against 2018-2024 replay history. Edge is the gap between our model and the book's implied probability.
                </p>
                <p className="mt-4 max-w-2xl text-sm text-slate-400">{slate.interpretation}</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Filters</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <div>
                <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">Position</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {availablePositions.map((pos) => (
                    <button
                      key={pos}
                      onClick={() => toggleItem(selectedPositions, pos, setSelectedPositions)}
                      aria-pressed={selectedPositions.includes(pos)}
                      className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                        selectedPositions.includes(pos)
                          ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                          : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                      }`}
                    >
                      {pos}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">
                  <span>Min edge</span>
                  <span className="text-slate-300">{minEdge > 0 ? `+${(minEdge * 100).toFixed(0)}%` : 'Any'}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={0.3}
                  step={0.01}
                  value={minEdge}
                  onChange={(e) => setMinEdge(Number(e.target.value))}
                  aria-label="Minimum edge filter"
                  className="mt-2 w-full accent-emerald-400"
                />
              </div>
              <div>
                <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">Stats</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {availableStats.map((stat) => (
                    <button
                      key={stat}
                      onClick={() => toggleItem(selectedStats, stat, setSelectedStats)}
                      aria-pressed={selectedStats.includes(stat)}
                      className={`rounded-full border px-3 py-1 text-xs transition-colors ${
                        selectedStats.includes(stat)
                          ? 'border-emerald-400/50 bg-emerald-400/15 text-emerald-200'
                          : 'border-white/10 bg-white/5 text-slate-300 hover:bg-white/10'
                      }`}
                    >
                      {stat.replaceAll('_', ' ')}
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              id: 'singles-roi',
              icon: ShieldCheck,
              label: <GlossaryTooltip term="roi">Singles ROI</GlossaryTooltip>,
              value: `${(slate.singles.roi * 100).toFixed(1)}%`,
              detail: `${slate.singles.wins}-${slate.singles.losses} graded`,
            },
            {
              id: 'profit-units',
              icon: BadgeDollarSign,
              label: <GlossaryTooltip term="edge">Profit Units</GlossaryTooltip>,
              value: metric(slate.singles.profit_units, 'u'),
              detail: `${slate.singles.n_bets.toFixed(0)} tracked picks`,
            },
            {
              id: 'parlay-ev',
              icon: LayoutPanelTop,
              label: <GlossaryTooltip term="ev">Parlay EV</GlossaryTooltip>,
              value: metric(slate.parlays.avg_expected_value_units, 'u'),
              detail: `${slate.parlays.n_parlays.toFixed(0)} candidate parlays`,
            },
            {
              id: 'rows-priced',
              icon: Activity,
              label: 'Rows Priced',
              value: slate.validation.rows_priced.toString(),
              detail: `${slate.validation.selected_rows} selected`,
            },
          ].map((item) => (
            <Card key={item.id}>
              <CardContent className="p-5">
                <div className="flex items-center justify-between">
                  <item.icon className="h-5 w-5 text-emerald-300" />
                  <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">
                    {item.label}
                  </div>
                </div>
                <div className="mt-5 text-3xl font-semibold text-white">{item.value}</div>
                <p className="mt-2 text-sm text-slate-400">{item.detail}</p>
              </CardContent>
            </Card>
          ))}
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-6">
            <div>
              <h2 className="text-lg font-semibold text-white">Top Picks</h2>
              <p className="text-sm text-slate-400">Showing {filteredPicks.length} picks. Use the filters to narrow by position, stat, or edge.</p>
            </div>
            <div className="grid gap-4">
              {filteredPicks.map((pick) => (
                <PlayerCard key={`${pick.player_id}-${pick.stat}-${pick.line}`} pick={pick} />
              ))}
            </div>
          </div>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle>Top Parlays</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {slate.top_parlays.map((parlay) => (
                  <div
                    key={parlay.parlay_label}
                    className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3"
                  >
                    <div className="text-sm font-medium text-slate-100">{parlay.parlay_label}</div>
                    <div className="mt-2 flex items-center justify-between font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">
                      <span>EV {metric(parlay.expected_value_units, 'u')}</span>
                      <span>Joint {Math.round(parlay.joint_prob * 1000) / 10}%</span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <BreakdownTable
              label="Stat Breakdown"
              rows={slate.breakdowns.stat ?? []}
              valueKey="profit_units"
            />

            <BreakdownTable
              label="Week Breakdown"
              rows={slate.breakdowns.week ?? []}
              valueKey="roi"
            />
          </div>
        </section>
      </div>
    </main>
  )
}
