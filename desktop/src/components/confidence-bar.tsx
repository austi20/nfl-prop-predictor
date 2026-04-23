type ConfidenceBarProps = {
  probability: number
}

export function ConfidenceBar({ probability }: ConfidenceBarProps) {
  const width = Math.max(0, Math.min(100, probability * 100))
  return (
    <div className="flex flex-col gap-2">
      <div className="h-2 rounded-full bg-white/10">
        <div
          className="h-2 rounded-full bg-gradient-to-r from-emerald-500 via-emerald-300 to-cyan-300 transition-all duration-150"
          style={{ width: `${width}%` }}
        />
      </div>
      <div className="font-mono text-[11px] uppercase tracking-[0.18em] text-slate-400">
        model confidence {width.toFixed(1)}%
      </div>
    </div>
  )
}
