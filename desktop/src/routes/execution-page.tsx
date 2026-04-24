import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import {
  cancelIntent,
  getPortfolio,
  getSlate,
  killSwitch,
  streamExecutionEvents,
  submitPicks,
} from '../lib/api'
import type { ExecutionEvent, IntentStatus, Pick, Portfolio } from '../lib/types'

function fmt(n: number) {
  return `${n >= 0 ? '+' : ''}${n.toFixed(3)}`
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === 'filled'
      ? 'text-emerald-400'
      : status === 'canceled'
        ? 'text-slate-500'
        : status === 'risk_rejected'
          ? 'text-amber-400'
          : 'text-red-400'
  return <span className={`font-mono text-xs uppercase ${color}`}>{status}</span>
}

const VENUES = [
  { id: 'paper', label: 'Paper', enabled: true },
  { id: 'kalshi_demo', label: 'Kalshi (Demo) — Coming preseason', enabled: false },
] as const

export function ExecutionPage() {
  const queryClient = useQueryClient()
  const { data: slate, isLoading } = useQuery({ queryKey: ['slate'], queryFn: getSlate })
  const [venue, setVenue] = useState<string>('paper')

  const [intents, setIntents] = useState<IntentStatus[]>([])
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null)
  const [events, setEvents] = useState<ExecutionEvent[]>([])
  const [isKilled, setIsKilled] = useState(false)
  const eventsTailRef = useRef<HTMLDivElement>(null)

  // Portfolio polling
  useEffect(() => {
    const poll = async () => {
      try {
        const p = await getPortfolio()
        setPortfolio(p)
      } catch {
        // ignore — sidecar may not be running
      }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => clearInterval(id)
  }, [])

  // Event tail via SSE
  useEffect(() => {
    const controller = new AbortController()
    void streamExecutionEvents((evt) => {
      setEvents((prev) => [...prev.slice(-99), evt])
    }, controller.signal)
    return () => controller.abort()
  }, [])

  // Auto-scroll event tail
  useEffect(() => {
    eventsTailRef.current?.scrollTo({ top: eventsTailRef.current.scrollHeight, behavior: 'smooth' })
  }, [events])

  const submitMutation = useMutation({
    mutationFn: (picks: Pick[]) => submitPicks(picks),
    onSuccess: (resp) => {
      const results = (resp as any)?.data ?? resp
      if (Array.isArray(results)) setIntents((prev) => [...prev, ...results])
      void queryClient.invalidateQueries({ queryKey: ['slate'] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (intentId: string) => cancelIntent(intentId),
    onSuccess: (_resp, intentId) => {
      setIntents((prev) =>
        prev.map((i) => (i.intent_id === intentId ? { ...i, status: 'canceled' } : i)),
      )
    },
  })

  const killMutation = useMutation({
    mutationFn: () => killSwitch('user_initiated'),
    onSuccess: () => {
      setIsKilled(true)
      setIntents((prev) => prev.map((i) => ({ ...i, status: 'canceled' })))
    },
  })

  function handleSubmitAll() {
    const picks = slate?.top_picks ?? []
    if (picks.length > 0) submitMutation.mutate(picks)
  }

  function handleSubmitPick(pick: Pick) {
    submitMutation.mutate([pick])
  }

  if (isLoading) {
    return <div className="p-8 text-slate-400">Loading slate...</div>
  }

  return (
    <div className="flex flex-col gap-0">
      {/* Paper mode banner */}
      <div className="flex items-center justify-between bg-emerald-700/90 px-6 py-2">
        <div className="flex items-center gap-4">
          <span className="text-sm font-semibold text-emerald-100">
            Paper mode — no real money
          </span>
          <select
            value={venue}
            onChange={(e) => setVenue(e.target.value)}
            className="rounded bg-emerald-800/70 px-2 py-0.5 text-xs text-emerald-100"
            aria-label="Venue selector"
          >
            {VENUES.map((v) => (
              <option key={v.id} value={v.id} disabled={!v.enabled}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <button
          onClick={() => killMutation.mutate()}
          disabled={isKilled || killMutation.isPending}
          className="rounded-md bg-red-600 px-4 py-1.5 text-sm font-bold text-white transition hover:bg-red-500 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Kill switch — cancel all open intents"
        >
          {isKilled ? 'KILLED' : 'KILL SWITCH'}
        </button>
      </div>

      <div className="grid min-h-[calc(100vh-7rem)] grid-cols-3 gap-0 divide-x divide-white/10">
        {/* LEFT: Pick queue */}
        <div className="flex flex-col gap-3 overflow-y-auto p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-400">
              Pick Queue
            </h2>
            <button
              onClick={handleSubmitAll}
              disabled={isKilled || submitMutation.isPending || !slate?.top_picks.length}
              className="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-500 disabled:opacity-40"
            >
              Submit All
            </button>
          </div>
          {slate?.top_picks.map((pick) => (
            <Card key={`${pick.player_id}-${pick.stat}-${pick.week}`} className="border-white/10 bg-white/5">
              <CardContent className="flex items-center justify-between p-3">
                <div>
                  <div className="text-sm font-medium text-slate-100">{pick.player_name}</div>
                  <div className="text-xs text-slate-400">
                    {pick.stat} {pick.selected_side} {pick.line} &nbsp;·&nbsp;
                    <span className="text-emerald-400">edge {(pick.selected_edge * 100).toFixed(1)}%</span>
                  </div>
                </div>
                <button
                  onClick={() => handleSubmitPick(pick)}
                  disabled={isKilled || submitMutation.isPending}
                  className="rounded bg-emerald-700 px-2 py-1 text-xs font-semibold text-white hover:bg-emerald-600 disabled:opacity-40"
                >
                  Submit
                </button>
              </CardContent>
            </Card>
          ))}
          {!slate?.top_picks.length && (
            <p className="text-sm text-slate-500">No picks on current slate.</p>
          )}
        </div>

        {/* MIDDLE: Intents / orders */}
        <div className="flex flex-col gap-3 overflow-y-auto p-4">
          <h2 className="text-sm font-semibold uppercase tracking-widest text-slate-400">
            Orders
          </h2>
          {intents.length === 0 && (
            <p className="text-sm text-slate-500">No orders yet. Submit picks from the queue.</p>
          )}
          {intents.map((intent, idx) => (
            <Card key={`${intent.intent_id}-${idx}`} className="border-white/10 bg-white/5">
              <CardContent className="p-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-mono text-xs text-slate-400">{intent.pick_id}</div>
                    <div className="text-xs text-slate-300">
                      {intent.side?.toUpperCase()} @ {intent.limit_price?.toFixed(3)} ×{' '}
                      {intent.size}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <StatusBadge status={intent.status} />
                    {!['filled', 'canceled', 'risk_rejected'].includes(intent.status) && (
                      <button
                        onClick={() => cancelMutation.mutate(intent.intent_id)}
                        disabled={cancelMutation.isPending}
                        className="rounded bg-red-800 px-2 py-0.5 text-xs text-white hover:bg-red-700"
                      >
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* RIGHT: Portfolio + event tail */}
        <div className="flex flex-col gap-4 p-4">
          <Card className="border-white/10 bg-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Portfolio</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-3 gap-2 text-center">
              <div>
                <div className="font-mono text-base text-slate-100">
                  {portfolio ? fmt(portfolio.cash_balance) : '--'}
                </div>
                <div className="text-xs text-slate-400">Cash</div>
              </div>
              <div>
                <div className="font-mono text-base text-slate-100">
                  {portfolio ? fmt(portfolio.realized_pnl) : '--'}
                </div>
                <div className="text-xs text-slate-400">Realized P&L</div>
              </div>
              <div>
                <div className="font-mono text-base text-slate-100">
                  {portfolio ? fmt(portfolio.unrealized_pnl) : '--'}
                </div>
                <div className="text-xs text-slate-400">Unrealized P&L</div>
              </div>
            </CardContent>
          </Card>

          <Card className="flex-1 border-white/10 bg-white/5">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Audit Event Tail</CardTitle>
            </CardHeader>
            <CardContent>
              <div
                ref={eventsTailRef}
                className="h-64 overflow-y-auto font-mono text-xs text-slate-300"
              >
              {events.length === 0 && (
                <span className="text-slate-500">Waiting for events...</span>
              )}
              {events.map((evt, idx) => (
                <div key={idx} className="border-b border-white/5 py-1">
                  <span className="text-slate-500">{evt.ts?.slice(11, 19)}</span>{' '}
                  <span className="text-emerald-400">{evt.kind}</span>{' '}
                  {evt.event_type && <span className="text-amber-300">{evt.event_type}</span>}{' '}
                  {evt.pick_id && <span className="text-slate-400">{evt.pick_id}</span>}
                  {evt.reason && <span className="text-red-400"> {evt.reason}</span>}
                </div>
              ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
