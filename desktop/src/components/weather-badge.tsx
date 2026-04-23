import { Cloud, CloudRain, Thermometer, Wind } from 'lucide-react'

export type WeatherInfo = {
  temp_f?: number
  wind_mph?: number
  precip_prob?: number
  condition?: string
}

type Props = {
  weather?: WeatherInfo | null
}

export function WeatherBadge({ weather }: Props) {
  if (!weather) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-100">
        <Cloud className="h-3 w-3" aria-hidden="true" />
        Weather N/A
      </span>
    )
  }

  const { temp_f, wind_mph, precip_prob } = weather

  const isRainy = (precip_prob ?? 0) > 40
  const isWindy = (wind_mph ?? 0) > 15

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-100"
      aria-label={`Weather: ${temp_f != null ? `${Math.round(temp_f)}°F` : ''} ${isWindy ? `${Math.round(wind_mph ?? 0)}mph wind` : ''} ${isRainy ? 'rain likely' : ''}`}
    >
      {isRainy ? (
        <CloudRain className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      ) : isWindy ? (
        <Wind className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      ) : (
        <Thermometer className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      )}
      {temp_f != null && <span>{Math.round(temp_f)}°</span>}
      {isWindy && <span>{Math.round(wind_mph ?? 0)}mph</span>}
      {isRainy && <span>Rain</span>}
      {!isWindy && !isRainy && temp_f == null && <span>Clear</span>}
    </span>
  )
}
