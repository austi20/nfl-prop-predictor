type WeatherBadgeProps = {
  label?: string
}

export function WeatherBadge({ label = 'Weather in v0.5c' }: WeatherBadgeProps) {
  return (
    <span className="inline-flex rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-100">
      {label}
    </span>
  )
}
