export type InjuryStatus = 'Q' | 'D' | 'O' | 'IR' | 'PUP' | null

type Props = {
  status?: InjuryStatus
  detail?: string
}

const STATUS_CONFIG: Record<NonNullable<InjuryStatus>, { label: string; classes: string }> = {
  Q: {
    label: 'Questionable',
    classes: 'border-yellow-400/30 bg-yellow-400/10 text-yellow-200',
  },
  D: {
    label: 'Doubtful',
    classes: 'border-orange-400/30 bg-orange-400/10 text-orange-200',
  },
  O: {
    label: 'Out',
    classes: 'border-rose-400/30 bg-rose-400/10 text-rose-200',
  },
  IR: {
    label: 'IR',
    classes: 'border-rose-500/40 bg-rose-500/15 text-rose-100',
  },
  PUP: {
    label: 'PUP',
    classes: 'border-rose-500/40 bg-rose-500/15 text-rose-100',
  },
}

export function InjuryPill({ status, detail }: Props) {
  if (!status) {
    return (
      <span className="inline-flex rounded-full border border-emerald-300/20 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-200">
        Active
      </span>
    )
  }

  const cfg = STATUS_CONFIG[status]
  return (
    <span
      title={detail}
      aria-label={`Injury status: ${cfg.label}${detail ? ` - ${detail}` : ''}`}
      className={`inline-flex rounded-full border px-3 py-1 text-xs font-medium ${cfg.classes}`}
    >
      {status} - {cfg.label}
    </span>
  )
}
