import * as Dialog from '@radix-ui/react-dialog'
import { Info, X } from 'lucide-react'

import type { Pick } from '../lib/types'

type Props = {
  pick: Pick
}

function pct(value?: number | null) {
  if (value == null) return 'N/A'
  return `${(value * 100).toFixed(1)}%`
}

function units(value?: number | null) {
  if (value == null) return 'N/A'
  return `${value >= 0 ? '+' : ''}${value.toFixed(3)}u`
}

export function DecisionDrawer({ pick }: Props) {
  const confidence = pick.confidence ?? 'high'
  const drivers = pick.top_drivers?.length ? pick.top_drivers : ['Drivers pending Phase H coefficients']

  return (
    <Dialog.Root>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-emerald-300/25 bg-emerald-400/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-emerald-100 transition hover:bg-emerald-400/15"
        >
          <Info className="h-3.5 w-3.5" aria-hidden="true" />
          Why this bet
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-slate-950/70 backdrop-blur-sm" />
        <Dialog.Content className="fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col border-l border-white/10 bg-slate-950 p-6 text-slate-100 shadow-2xl">
          <div className="flex items-start justify-between gap-4">
            <div>
              <Dialog.Title className="text-lg font-semibold">
                {pick.player_name || pick.player_id}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-slate-400">
                {pick.stat.replaceAll('_', ' ')} {pick.selected_side} {pick.line}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="Close decision drawer"
                className="rounded-lg border border-white/10 p-2 text-slate-300 hover:bg-white/10"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </Dialog.Close>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3">
            <Metric label="Model over" value={pct(pick.model_p_over_calibrated ?? pick.over?.calibrated_prob)} />
            <Metric label="Market over" value={pct(pick.market_p_over_no_vig ?? pick.over?.market_no_vig_prob)} />
            <Metric label="Model under" value={pct(pick.model_p_under_calibrated ?? pick.under?.calibrated_prob)} />
            <Metric label="Market under" value={pct(pick.market_p_under_no_vig ?? pick.under?.market_no_vig_prob)} />
            <Metric label="EV over" value={units(pick.ev_over ?? pick.over?.ev)} />
            <Metric label="EV under" value={units(pick.ev_under ?? pick.under?.ev)} />
          </div>

          <div className="mt-6 rounded-xl border border-white/10 bg-white/5 p-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Recommendation</span>
              <span className="font-mono uppercase text-emerald-200">
                {pick.recommendation ?? pick.selected_side}
              </span>
            </div>
            <div className="mt-3 flex items-center justify-between text-sm">
              <span className="text-slate-400">Confidence</span>
              <span
                title={confidence === 'low' ? 'One or more context inputs is unavailable.' : 'Required context inputs are present.'}
                className="font-mono uppercase text-slate-100"
              >
                {confidence}
              </span>
            </div>
          </div>

          <div className="mt-6">
            <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-500">
              Drivers
            </div>
            <div className="mt-3 space-y-2">
              {drivers.slice(0, 3).map((driver) => (
                <div key={driver} className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200">
                  {driver}
                </div>
              ))}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 p-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 font-mono text-sm text-slate-100">{value}</div>
    </div>
  )
}
