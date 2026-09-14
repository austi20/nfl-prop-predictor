// Start/sit tier chip. Colours run hot->cold across the six groups so the board
// reads at a glance: green = start, amber = flex dice-roll, red = bench.
const TIER_TONE: Record<string, string> = {
  start_no_doubt: 'bg-emerald-400/15 text-emerald-200 border-emerald-400/30',
  feels_good: 'bg-lime-400/15 text-lime-200 border-lime-400/30',
  w_flex: 'bg-amber-400/15 text-amber-200 border-amber-400/30',
  shaky_flex: 'bg-orange-400/15 text-orange-200 border-orange-400/30',
  avoid: 'bg-rose-400/15 text-rose-200 border-rose-400/30',
  do_not_play: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
}

export function TierBadge({ tier, label }: { tier: string; label: string }) {
  return (
    <span
      className={`rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase tracking-[0.08em] ${
        TIER_TONE[tier] ?? 'bg-white/10 text-slate-300 border-white/20'
      }`}
    >
      {label}
    </span>
  )
}
