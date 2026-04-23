import type { DistributionSummary } from '../lib/types'

type DistChartProps = {
  distribution?: DistributionSummary | null
  line: number
}

export function DistChart({ distribution, line }: DistChartProps) {
  if (!distribution) {
    return (
      <div className="rounded-2xl border border-dashed border-white/10 p-4 text-sm text-slate-400">
        Replay-backed cards do not yet carry full distribution payloads.
      </div>
    )
  }

  const min = Math.max(0, distribution.mean - distribution.std * 2)
  const max = distribution.mean + distribution.std * 2
  const meanPct = ((distribution.mean - min) / (max - min || 1)) * 100
  const linePct = ((line - min) / (max - min || 1)) * 100

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
      <div className="relative h-12 overflow-hidden rounded-full bg-[linear-gradient(90deg,rgba(248,250,252,0.06),rgba(16,185,129,0.16),rgba(248,250,252,0.06))]">
        <div
          className="absolute inset-y-2 w-1 rounded-full bg-cyan-300"
          style={{ left: `${meanPct}%` }}
          title="Mean"
        />
        <div
          className="absolute inset-y-0 w-0.5 bg-rose-300"
          style={{ left: `${linePct}%` }}
          title="Book line"
        />
      </div>
      <div className="mt-3 flex justify-between font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">
        <span>mean {distribution.mean.toFixed(1)}</span>
        <span>line {line.toFixed(1)}</span>
        <span>{distribution.dist_type}</span>
      </div>
    </div>
  )
}
