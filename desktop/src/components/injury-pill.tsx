type InjuryPillProps = {
  label?: string
}

export function InjuryPill({ label = 'No injury feed yet' }: InjuryPillProps) {
  return (
    <span className="inline-flex rounded-full border border-rose-300/20 bg-rose-400/10 px-3 py-1 text-xs font-medium text-rose-100">
      {label}
    </span>
  )
}
