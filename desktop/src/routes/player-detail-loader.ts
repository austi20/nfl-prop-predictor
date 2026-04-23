import type { LoaderFunctionArgs } from 'react-router-dom'
import { getPlayer } from '../lib/api'

export async function playerDetailLoader({ params }: LoaderFunctionArgs) {
  const playerId = params.playerId
  if (!playerId) throw new Error('Missing playerId')
  return getPlayer(playerId)
}
