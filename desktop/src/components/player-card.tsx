import type { Pick } from '../lib/types'
import { ConfidenceBar } from './confidence-bar'
import { DistChart } from './dist-chart'
import { EdgeBadge } from './edge-badge'
import { InjuryPill } from './injury-pill'
import { WeatherBadge } from './weather-badge'

// weather/injury data will be populated in v0.5c when the analyst tools wire through
import { Card, CardContent } from './ui/card'

type PlayerCardProps = {
  pick: Pick
}

function fantasyPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

export function PlayerCard({ pick }: PlayerCardProps) {
  const fantasy = pick.fantasy

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-5 sm:p-6">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-slate-400">
              {pick.recent_team} vs {pick.opponent_team}
            </div>
            <h3 className="mt-2 text-lg font-semibold text-slate-50">{pick.player_name || pick.player_id}</h3>
            <p className="mt-1 text-sm text-slate-300">
              {pick.position || 'player'} • Week {pick.week} • {pick.stat.replaceAll('_', ' ')}
            </p>
          </div>
          <EdgeBadge edge={pick.selected_edge} side={pick.selected_side} />
        </div>
        <div className="mt-4 grid gap-4 md:grid-cols-[1.2fr_0.8fr]">
          <DistChart distribution={pick.distribution} line={pick.line} />
          <div className="space-y-4 rounded-2xl border border-white/10 bg-slate-950/50 p-4">
            <div className="flex items-center justify-between text-sm text-slate-200">
              <span>Book line</span>
              <span className="font-mono">{pick.line}</span>
            </div>
            <div className="flex items-center justify-between text-sm text-slate-200">
              <span>Selected odds</span>
              <span className="font-mono">{pick.selected_odds > 0 ? `+${pick.selected_odds}` : pick.selected_odds}</span>
            </div>
            {fantasy && (
              <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 p-3">
                <div className="flex items-center justify-between text-sm text-emerald-50">
                  <span>Fantasy projection</span>
                  <span className="font-mono text-lg font-semibold">{fantasy.projected_points.toFixed(1)}</span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-2 font-mono text-[11px] uppercase tracking-[0.16em]">
                  <div className="rounded-xl bg-slate-950/40 px-3 py-2 text-emerald-200">
                    Boom {fantasyPercent(fantasy.boom_probability)}
                  </div>
                  <div className="rounded-xl bg-slate-950/40 px-3 py-2 text-rose-200">
                    Bust {fantasyPercent(fantasy.bust_probability)}
                  </div>
                </div>
                <div className="mt-2 font-mono text-[10px] uppercase tracking-[0.16em] text-slate-400">
                  {fantasy.scoring_mode.replace('_', ' ')} | P10 {fantasy.p10_points.toFixed(1)} | P90{' '}
                  {fantasy.p90_points.toFixed(1)}
                </div>
              </div>
            )}
            <ConfidenceBar probability={pick.selected_prob} />
            <div className="flex flex-wrap gap-2">
              <WeatherBadge weather={null} />
              <InjuryPill status={null} />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
