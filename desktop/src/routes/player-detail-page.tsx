import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { AnalystPanel } from '../components/analyst-panel'
import { DistChart } from '../components/dist-chart'
import { EdgeBadge } from '../components/edge-badge'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { getPlayer } from '../lib/api'
import type { Pick, PlayerDetailResponse } from '../lib/types'

function resultColor(result: string | null | undefined) {
  if (result === 'win') return 'text-emerald-400'
  if (result === 'loss') return 'text-rose-400'
  return 'text-slate-400'
}

function StatTable({ games, stats }: { games: PlayerDetailResponse['recent_games']; stats: string[] }) {
  const cols = stats.slice(0, 6)
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10 text-left font-mono text-[11px] uppercase tracking-widest text-slate-400">
            <th className="pb-2 pr-4">Wk</th>
            <th className="pb-2 pr-4">Opp</th>
            {cols.map((s) => (
              <th key={s} className="pb-2 pr-4">
                {s.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {games.map((g) => (
            <tr key={`${g.season}-${g.week}`} className="border-b border-white/5 hover:bg-white/5">
              <td className="py-2 pr-4 font-mono text-slate-300">{g.week}</td>
              <td className="py-2 pr-4 text-slate-300">{g.opponent_team || '-'}</td>
              {cols.map((s) => (
                <td key={s} className="py-2 pr-4 font-mono text-slate-200">
                  {g.stats[s] != null ? g.stats[s].toFixed(1) : '-'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PickRow({ pick }: { pick: Pick }) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/5 px-4 py-3">
      <div className="flex items-center gap-3">
        <EdgeBadge edge={pick.selected_edge} side={pick.selected_side} />
        <div>
          <div className="text-sm font-medium text-slate-200">
            {pick.stat.replace(/_/g, ' ')} {pick.selected_side} {pick.line}
          </div>
          <div className="text-xs text-slate-400">
            Wk {pick.week} vs {pick.opponent_team}
          </div>
        </div>
      </div>
      <div className={`text-sm font-mono font-semibold ${resultColor(pick.result)}`}>
        {pick.result ?? '-'}
      </div>
    </div>
  )
}

export function PlayerDetailPage() {
  const { playerId } = useParams<{ playerId: string }>()
  const { data: player, isLoading } = useQuery({
    queryKey: ['player', playerId],
    queryFn: () => getPlayer(playerId!),
    enabled: !!playerId,
  })
  const [analystOpen, setAnalystOpen] = useState(false)

  if (isLoading || !player) {
    return (
      <div className="flex min-h-screen items-center justify-center text-slate-400">
        Loading player...
      </div>
    )
  }

  const topPick = player.replay_picks[0]

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div className="flex items-center justify-between">
        <Link
          to="/"
          className="flex items-center gap-2 text-sm text-slate-400 hover:text-slate-200"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Dashboard
        </Link>
        <button
          onClick={() => setAnalystOpen((v) => !v)}
          className="rounded-xl border border-emerald-400/30 bg-emerald-400/10 px-4 py-2 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-400/20"
          aria-label="Toggle analyst panel"
        >
          Ask Analyst
        </button>
      </div>

      <div>
        <div className="font-mono text-[11px] uppercase tracking-widest text-slate-400">
          {player.recent_team} • {player.position}
        </div>
        <h1 className="mt-1 text-2xl font-bold text-slate-50">
          {player.player_name || player.player_id}
        </h1>
      </div>

      {topPick && (
        <Card>
          <CardHeader>
            <CardTitle>Top Projection</CardTitle>
          </CardHeader>
          <CardContent>
            <DistChart distribution={topPick.distribution} line={topPick.line} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Game Log (last {player.recent_games.length})</CardTitle>
        </CardHeader>
        <CardContent>
          {player.recent_games.length > 0 ? (
            <StatTable games={player.recent_games} stats={player.supported_stats} />
          ) : (
            <p className="text-sm text-slate-400">No game log data available.</p>
          )}
        </CardContent>
      </Card>

      {player.replay_picks.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Replay Picks ({player.replay_picks.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {player.replay_picks.slice(0, 10).map((p, i) => (
              <PickRow key={`${p.game_id}-${p.stat}-${i}`} pick={p} />
            ))}
          </CardContent>
        </Card>
      )}

      {analystOpen && (
        <AnalystPanel
          context={{ player_id: player.player_id, stat: topPick?.stat, line: topPick?.line }}
          onClose={() => setAnalystOpen(false)}
        />
      )}
    </div>
  )
}
