import { cn } from '../lib/utils'

type EdgeBadgeProps = {
  edge: number
  side: string
}

export function EdgeBadge({ edge, side }: EdgeBadgeProps) {
  const positive = edge >= 0.05
  return (
    <span
      className={cn(
        'inline-flex rounded-full px-3 py-1 text-xs font-semibold tracking-[0.18em] uppercase',
        positive ? 'bg-emerald-400/15 text-emerald-200' : 'bg-rose-400/15 text-rose-200',
      )}
    >
      {side} {Math.round(edge * 1000) / 10}%
    </span>
  )
}
