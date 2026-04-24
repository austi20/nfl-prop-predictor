import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useState } from 'react'

import { EdgeBadge } from '../components/edge-badge'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { buildParlays, getSlate } from '../lib/api'
import type { ParlayBuildResponse, ParlayRow, Pick } from '../lib/types'

function fmt(n: number, sign = false) {
  return `${sign && n >= 0 ? '+' : ''}${n.toFixed(3)}`
}

function ParlayResultRow({ row }: { row: ParlayRow }) {
  const won = row.result === 'win'
  const lost = row.result === 'loss'
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-slate-200">{row.parlay_label}</div>
          <div className="mt-0.5 font-mono text-xs text-slate-400">
            {row.legs} legs • joint p={row.joint_prob.toFixed(3)} • EV {fmt(row.expected_value_units, true)}u
          </div>
        </div>
        <div
          className={`text-sm font-semibold font-mono ${won ? 'text-emerald-400' : lost ? 'text-rose-400' : 'text-slate-400'}`}
        >
          {won ? `+${row.profit_units.toFixed(2)}u` : lost ? `${row.profit_units.toFixed(2)}u` : row.result}
        </div>
      </div>
    </div>
  )
}

export function ParlayBuilderPage() {
  const { data: slate, isLoading } = useQuery({ queryKey: ['slate'], queryFn: getSlate })
  const [cart, setCart] = useState<Pick[]>([])
  const [legs, setLegs] = useState(2)
  const [stake, setStake] = useState(1.0)
  const [result, setResult] = useState<ParlayBuildResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (isLoading || !slate) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        Loading builder...
      </div>
    )
  }

  const picks = slate.top_picks ?? []

  function togglePick(pick: Pick) {
    setCart((prev) =>
      prev.some((p) => p.game_id === pick.game_id && p.stat === pick.stat)
        ? prev.filter((p) => !(p.game_id === pick.game_id && p.stat === pick.stat))
        : [...prev, pick],
    )
    setResult(null)
  }

  async function handleBuild() {
    if (cart.length < 2) return
    setLoading(true)
    setError(null)
    try {
      const res = await buildParlays(cart, legs, stake)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-50">Parlay Builder</h1>
        <p className="mt-1 text-sm text-slate-400">Select picks to combine into parlays.</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <Card>
          <CardHeader>
            <CardTitle>Available Picks ({picks.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {picks.map((pick, i) => {
              const inCart = cart.some(
                (p) => p.game_id === pick.game_id && p.stat === pick.stat,
              )
              return (
                <button
                  key={`${pick.game_id}-${pick.stat}-${i}`}
                  onClick={() => togglePick(pick)}
                  aria-pressed={inCart}
                  className={`flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors ${
                    inCart
                      ? 'border-emerald-400/40 bg-emerald-400/10'
                      : 'border-white/10 bg-white/5 hover:bg-white/10'
                  }`}
                >
                  <div>
                    <div className="text-sm font-medium text-slate-200">
                      {pick.player_name || pick.player_id}
                    </div>
                    <div className="text-xs text-slate-400">
                      {pick.stat.replace(/_/g, ' ')} {pick.selected_side} {pick.line} • Wk {pick.week}
                    </div>
                  </div>
                  <EdgeBadge edge={pick.selected_edge} side={pick.selected_side} />
                </button>
              )
            })}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Cart ({cart.length})</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {cart.length === 0 && (
                <p className="text-sm text-slate-400">No picks selected.</p>
              )}
              {cart.map((p, i) => (
                <div
                  key={`${p.game_id}-${p.stat}-${i}`}
                  className="flex items-center justify-between rounded-xl border border-white/10 bg-white/5 px-3 py-2"
                >
                  <div className="text-xs text-slate-300">
                    {p.player_name || p.player_id} — {p.stat.replace(/_/g, ' ')} {p.selected_side} {p.line}
                  </div>
                  <button
                    onClick={() => togglePick(p)}
                    aria-label={`Remove ${p.player_name} from cart`}
                    className="ml-2 text-slate-400 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}

              {cart.length >= 2 && (
                <div className="space-y-3 pt-2">
                  <div className="flex items-center justify-between text-sm text-slate-300">
                    <label htmlFor="legs">Legs</label>
                    <input
                      id="legs"
                      type="number"
                      min={2}
                      max={cart.length}
                      value={legs}
                      onChange={(e) => setLegs(Number(e.target.value))}
                      className="w-16 rounded-lg border border-white/20 bg-slate-900 px-2 py-1 text-right font-mono text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                    />
                  </div>
                  <div className="flex items-center justify-between text-sm text-slate-300">
                    <label htmlFor="stake">Stake (units)</label>
                    <input
                      id="stake"
                      type="number"
                      min={0.1}
                      step={0.1}
                      value={stake}
                      onChange={(e) => setStake(Number(e.target.value))}
                      className="w-16 rounded-lg border border-white/20 bg-slate-900 px-2 py-1 text-right font-mono text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
                    />
                  </div>
                  <button
                    onClick={handleBuild}
                    disabled={loading}
                    className="w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-semibold text-slate-950 transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    {loading ? 'Building...' : 'Build Parlays'}
                  </button>
                  {error && <p className="text-xs text-rose-400">{error}</p>}
                </div>
              )}
            </CardContent>
          </Card>

          {result && (
            <Card>
              <CardHeader>
                <CardTitle>
                  Results ({result.parlays.length} parlays)
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex justify-between font-mono text-xs text-slate-400">
                  <span>ROI</span>
                  <span className={result.summary.roi >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    {fmt(result.summary.roi * 100, true)}%
                  </span>
                </div>
                <div className="flex justify-between font-mono text-xs text-slate-400">
                  <span>Win rate</span>
                  <span>{(result.summary.win_rate * 100).toFixed(1)}%</span>
                </div>
                <div className="mt-2 space-y-2">
                  {result.parlays.slice(0, 5).map((row, i) => (
                    <ParlayResultRow key={i} row={row} />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
