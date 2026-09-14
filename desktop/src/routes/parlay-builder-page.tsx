import { Trash2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useMemo, useState } from 'react'

import { EdgeBadge } from '../components/edge-badge'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { buildParlays } from '../lib/api'
import { useAppStore } from '../store/app-store'
import type { ParlayBuildResponse, ParlayRow } from '../lib/types'

function fmt(n: number, sign = false) {
  return `${sign && n >= 0 ? '+' : ''}${n.toFixed(3)}`
}

function ParlayResultRow({ row }: { row: ParlayRow }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-slate-200">{row.parlay_label}</div>
          <div className="mt-0.5 font-mono text-xs text-slate-400">
            {row.legs} legs · joint p={row.joint_prob.toFixed(3)} · decimal odds{' '}
            {row.decimal_odds.toFixed(2)}
          </div>
        </div>
        <div className="text-right">
          <div
            className={`font-mono text-sm font-semibold ${
              row.expected_value_units >= 0 ? 'text-emerald-400' : 'text-rose-400'
            }`}
          >
            EV {fmt(row.expected_value_units, true)}u
          </div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">
            mean edge {fmt(row.mean_edge, true)}
          </div>
        </div>
      </div>
    </div>
  )
}

export function ParlayBuilderPage() {
  const cart = useAppStore((s) => s.parlayCart)
  const removeCartPick = useAppStore((s) => s.removeCartPick)
  const clearCart = useAppStore((s) => s.clearCart)

  const [legs, setLegs] = useState(2)
  const [stake, setStake] = useState(1.0)
  const [result, setResult] = useState<ParlayBuildResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const maxLegs = Math.max(2, cart.length)
  const effectiveLegs = Math.min(legs, maxLegs)

  const independentJointProb = useMemo(
    () => cart.reduce((p, pick) => p * pick.selected_prob, 1),
    [cart],
  )

  async function handleBuild() {
    if (cart.length < 2) return
    setLoading(true)
    setError(null)
    try {
      const res = await buildParlays(cart, effectiveLegs, stake)
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,rgba(16,185,129,0.22),transparent_34%),linear-gradient(180deg,#07111b_0%,#0c1724_100%)] text-slate-50">
      <div className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-4 py-6 sm:px-6 lg:py-8">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-white">Parlay Builder</h1>
          <p className="mt-2 text-sm text-slate-400">
            Add legs from the{' '}
            <Link to="/props" className="text-emerald-300 underline underline-offset-4">
              prop board
            </Link>
            , then price them together. Correlation between legs is not modeled -- the joint
            probability below is the independent product, an upper bound on the true parlay odds
            for same-game legs.
          </p>
        </div>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Slip ({cart.length})</CardTitle>
              {cart.length > 0 && (
                <button
                  onClick={clearCart}
                  className="text-xs text-slate-400 transition hover:text-rose-300"
                >
                  Clear all
                </button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {cart.length === 0 ? (
              <p className="text-sm text-slate-400">
                No legs selected yet. Head to the prop board and tap "Add to slip" on a few picks.
              </p>
            ) : (
              cart.map((p) => (
                <div
                  key={`${p.player_id}-${p.stat}-${p.line}-${p.selected_side}`}
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/5 px-4 py-3"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-slate-100">
                      {p.player_name || p.player_id}
                    </div>
                    <div className="mt-0.5 font-mono text-xs text-slate-400">
                      {p.stat.replaceAll('_', ' ')} {p.selected_side} {p.line} · {p.recent_team} vs{' '}
                      {p.opponent_team}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <EdgeBadge edge={p.selected_edge} side={p.selected_side} />
                    <button
                      onClick={() => removeCartPick(p)}
                      aria-label={`Remove ${p.player_name || p.player_id} from slip`}
                      className="text-slate-400 transition hover:text-rose-400"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              ))
            )}

            {cart.length >= 2 && (
              <div className="space-y-4 pt-2">
                <div className="grid grid-cols-2 gap-3 rounded-xl border border-white/10 bg-white/5 p-3 font-mono text-[11px] uppercase tracking-[0.14em] text-slate-400">
                  <div>
                    Independent joint prob
                    <div className="mt-1 text-base text-slate-100">
                      {(independentJointProb * 100).toFixed(1)}%
                    </div>
                  </div>
                  <div>
                    Legs selected
                    <div className="mt-1 text-base text-slate-100">{cart.length}</div>
                  </div>
                </div>

                <div className="flex items-center justify-between text-sm text-slate-300">
                  <label htmlFor="legs">Legs per parlay</label>
                  <input
                    id="legs"
                    type="number"
                    min={2}
                    max={maxLegs}
                    value={effectiveLegs}
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
                  {loading ? 'Pricing…' : 'Price parlay combinations'}
                </button>
                {error && <p className="text-xs text-rose-400">{error}</p>}
              </div>
            )}
          </CardContent>
        </Card>

        {result && (
          <Card>
            <CardHeader>
              <CardTitle>Ranked parlays ({result.parlays.length})</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {result.parlays.length === 0 ? (
                <p className="text-sm text-slate-400">
                  No combination of the selected legs cleared the parlay policy's edge floor.
                </p>
              ) : (
                result.parlays.map((row, i) => <ParlayResultRow key={i} row={row} />)
              )}
            </CardContent>
          </Card>
        )}
      </div>
    </main>
  )
}
