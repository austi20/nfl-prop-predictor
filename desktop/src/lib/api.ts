import type { ExecutionEvent, FantasyPredictionResponse, IntentStatus, Pick, PlayerDetailResponse, ParlayBuildResponse, Portfolio, SlateResponse } from './types'
import { resolveApiBaseUrl } from './runtime'

async function request<T>(path: string, init?: RequestInit) {
  const baseUrl = await resolveApiBaseUrl()
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...init,
  })

  if (!response.ok) {
    try {
      const body = await response.json()
      const message: string = body?.error?.message ?? `Request failed for ${path}: ${response.status}`
      const code: string = body?.error?.code ?? String(response.status)
      const err = Object.assign(new Error(message), { code })
      throw err
    } catch (e) {
      if (e instanceof SyntaxError) throw new Error(`Request failed for ${path}: ${response.status}`)
      throw e
    }
  }

  return (await response.json()) as T
}

export async function getSlate() {
  return request<SlateResponse>('/api/slate')
}

export async function getPlayer(playerId: string) {
  return request<PlayerDetailResponse>(`/api/players/${encodeURIComponent(playerId)}`)
}

export async function buildParlays(picks: Pick[], legs = 2, stake = 1.0) {
  return request<ParlayBuildResponse>('/api/parlays/build', {
    method: 'POST',
    body: JSON.stringify({ picks, legs, stake }),
  })
}

export async function predictFantasy(payload: {
  player_id: string
  season: number
  week: number
  position?: string
  opponent_team?: string
  recent_team?: string
  game_id?: string
  scoring_mode?: 'full_ppr' | 'half_ppr'
}) {
  return request<FantasyPredictionResponse>('/api/fantasy/predict', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export async function submitPicks(picks: Pick[]) {
  return request<IntentStatus[]>('/api/execution/paper/submit', {
    method: 'POST',
    body: JSON.stringify({ picks }),
  })
}

export async function cancelIntent(intentId: string) {
  return request<{ status: string; intent_id: string }>('/api/execution/paper/cancel', {
    method: 'POST',
    body: JSON.stringify({ intent_id: intentId }),
  })
}

export async function killSwitch(reason = 'user_initiated') {
  return request<{ killed: number; reason: string }>('/api/execution/kill', {
    method: 'POST',
    body: JSON.stringify({ reason }),
  })
}

export async function getPortfolio() {
  return request<Portfolio>('/api/execution/portfolio').then((r) => (r as any).data as Portfolio)
}

export async function getExecutionEvents(since = 0) {
  return request<{ success: boolean; data: ExecutionEvent[] }>(`/api/execution/events?since=${since}`).then(
    (r) => (r as any).data as ExecutionEvent[],
  )
}

export async function streamExecutionEvents(
  onEvent: (event: ExecutionEvent) => void,
  signal: AbortSignal,
) {
  const baseUrl = await resolveApiBaseUrl()
  const response = await fetch(`${baseUrl}/api/execution/events/stream`, { signal })
  if (!response.ok || !response.body) return

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      try {
        onEvent(JSON.parse(line.slice(5).trim()) as ExecutionEvent)
      } catch {
        // skip malformed frames
      }
    }
  }
}

export async function streamAnalyst(
  question: string,
  context: { player_id?: string; stat?: string; line?: number },
  onToken: (token: string) => void,
  onToolCall: (call: Record<string, unknown>) => void,
  signal: AbortSignal,
) {
  const baseUrl = await resolveApiBaseUrl()
  const response = await fetch(`${baseUrl}/api/analyst/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, ...context }),
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`Analyst stream failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      try {
        const evt = JSON.parse(line.slice(5).trim())
        if (evt.event === 'error') throw new Error((evt.error as string) || 'Stream error')
        if (evt.token) onToken(evt.token as string)
        if (evt.event === 'tool_call') onToolCall({ name: evt.name, args: evt.args })
      } catch (e) {
        if (!(e instanceof SyntaxError)) throw e
      }
    }
  }
}
