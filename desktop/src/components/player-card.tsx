import type { Pick } from '../lib/types'
import { ConfidenceBar } from './confidence-bar'
import { DistChart } from './dist-chart'
import { EdgeBadge } from './edge-badge'
import { InjuryPill } from './injury-pill'
import { WeatherBadge } from './weather-badge'
import { Card, CardContent } from './ui/card'

type PlayerCardProps = {
  pick: Pick
}

export function PlayerCard({ pick }: PlayerCardProps) {
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
            <ConfidenceBar probability={pick.selected_prob} />
            <div className="flex flex-wrap gap-2">
              <WeatherBadge />
              <InjuryPill />
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
