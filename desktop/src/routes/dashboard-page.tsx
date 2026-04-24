import { useQuery } from '@tanstack/react-query'
import { Activity, BadgeDollarSign, LayoutPanelTop, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'

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
                  replay-backed slate • step 5 v0.5a
                </div>
                <h1 className="mt-4 max-w-2xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">
                  NFL Prop Predictor
                </h1>
                <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                  The desktop layer stays thin here: this page is rendered directly from
                  <code className="mx-1 rounded bg-white/10 px-1.5 py-0.5 text-[0.85em]">/api/slate</code>
                  using Step 4 replay artifacts and the current pricing contract.
                </p>
                <p className="mt-4 max-w-2xl text-sm text-slate-400">{slate.interpretation}</p>
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Filters</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">Season</div>
                <div className="mt-2 text-lg text-slate-100">{slate.season_label}</div>
              </div>
              <div>
                <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">Stats</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {slate.filter_metadata.available_stats.map((stat) => (
                    <span
                      key={stat}
                      className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200"
                    >
                      {stat.replaceAll('_', ' ')}
                    </span>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[
            {
              icon: ShieldCheck,
              label: 'Singles ROI',
              value: `${(slate.singles.roi * 100).toFixed(1)}%`,
              detail: `${slate.singles.wins}-${slate.singles.losses} graded`,
            },
            {
              icon: BadgeDollarSign,
              label: 'Profit Units',
              value: metric(slate.singles.profit_units, 'u'),
              detail: `${slate.singles.n_bets.toFixed(0)} tracked picks`,
            },
            {
              icon: LayoutPanelTop,
              label: 'Parlay EV',
              value: metric(slate.parlays.avg_expected_value_units, 'u'),
              detail: `${slate.parlays.n_parlays.toFixed(0)} candidate parlays`,
            },
            {
              icon: Activity,
              label: 'Rows Priced',
              value: slate.validation.rows_priced.toString(),
              detail: `${slate.validation.selected_rows} selected`,
            },
          ].map((item) => (
            <Card key={item.label}>
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
              <p className="text-sm text-slate-400">Replay-backed cards with the existing Step 4 pricing fields.</p>
            </div>
            <div className="grid gap-4">
              {slate.top_picks.map((pick) => (
                <Link
                  key={`${pick.player_id}-${pick.stat}-${pick.line}`}
                  to={`/player/${encodeURIComponent(pick.player_id)}`}
                  className="block focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
                >
                  <PlayerCard pick={pick} />
                </Link>
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
