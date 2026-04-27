import { Cloud, CloudRain, Home, Thermometer, Wind } from 'lucide-react'

export type WeatherInfo = {
  temp_f?: number | null
  wind_mph?: number | null
  precip_prob?: number | null
  precip_in?: number | null
  indoor?: boolean | null
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
        No current feed
      </span>
    )
  }

  const { temp_f, wind_mph, precip_prob, precip_in, indoor } = weather
  const isRainy = (precip_prob ?? 0) > 40 || (precip_in ?? 0) > 0
  const isWindy = (wind_mph ?? 0) > 15

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium text-cyan-100"
      aria-label={`Weather: ${indoor ? 'indoor' : ''} ${temp_f != null ? `${Math.round(temp_f)} degrees` : ''} ${wind_mph != null ? `${Math.round(wind_mph)}mph wind` : ''} ${isRainy ? 'precipitation' : ''}`}
    >
      {indoor ? (
        <Home className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      ) : isRainy ? (
        <CloudRain className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      ) : isWindy ? (
        <Wind className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      ) : (
        <Thermometer className="h-3 w-3 text-cyan-300" aria-hidden="true" />
      )}
      {indoor && <span>Dome</span>}
      {temp_f != null && <span>{Math.round(temp_f)} deg</span>}
      {wind_mph != null && !indoor && (
        <span className={isWindy ? 'text-rose-200' : undefined}>{Math.round(wind_mph)}mph</span>
      )}
      {isRainy && !indoor && <span>{precip_in != null ? `${precip_in.toFixed(2)}in` : 'Rain'}</span>}
      {!indoor && !isWindy && !isRainy && temp_f == null && <span>Clear</span>}
    </span>
  )
}
