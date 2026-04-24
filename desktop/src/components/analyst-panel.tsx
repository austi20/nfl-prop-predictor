import { ChevronDown, ChevronRight, Send, X } from 'lucide-react'
import { useRef, useState } from 'react'

import { streamAnalyst } from '../lib/api'

type ToolCallChip = {
  id: string
  call: Record<string, unknown>
  open: boolean
}

type Props = {
  context?: { player_id?: string; stat?: string; line?: number }
  onClose?: () => void
}

export function AnalystPanel({ context = {}, onClose }: Props) {
  const [question, setQuestion] = useState('')
  const [tokens, setTokens] = useState('')
  const [chips, setChips] = useState<ToolCallChip[]>([])
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  async function submit() {
    if (!question.trim() || streaming) return
    setTokens('')
    setChips([])
    setError(null)
    setStreaming(true)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      await streamAnalyst(
        question,
        context,
        (token) => setTokens((prev) => prev + token),
        (call) =>
          setChips((prev) => [
            ...prev,
            { id: `${Date.now()}`, call, open: false },
          ]),
        ctrl.signal,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setError(e instanceof Error ? e.message : 'Stream failed')
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  function abort() {
    abortRef.current?.abort()
  }

  function toggleChip(id: string) {
    setChips((prev) =>
      prev.map((c) => (c.id === id ? { ...c, open: !c.open } : c)),
    )
  }

  return (
    <div
      role="complementary"
      aria-label="Analyst panel"
      className="rounded-2xl border border-white/10 bg-slate-950/80 p-5 backdrop-blur-sm"
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-mono text-xs font-bold uppercase tracking-widest text-emerald-300">
          Analyst
        </h2>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close analyst panel"
            className="rounded-lg p-1 text-slate-400 hover:text-slate-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {!question && !streaming && (
        <div className="mb-3 flex flex-wrap gap-2">
          {[
            'Explain this pick in plain English',
            'Why over instead of under?',
            'What would change this recommendation?',
          ].map((prompt) => (
            <button
              key={prompt}
              onClick={() => setQuestion(prompt)}
              className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200 transition-colors"
            >
              {prompt}
            </button>
          ))}
        </div>
      )}

      <div className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Ask about a pick, trend, or matchup..."
          aria-label="Analyst question"
          className="flex-1 rounded-xl border border-white/20 bg-slate-900 px-4 py-2.5 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400/50"
        />
        {streaming ? (
          <button
            onClick={abort}
            aria-label="Stop streaming"
            className="rounded-xl border border-rose-400/30 bg-rose-400/10 px-4 py-2.5 text-sm font-medium text-rose-300 hover:bg-rose-400/20"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={!question.trim()}
            aria-label="Send question"
            className="rounded-xl bg-emerald-500 px-4 py-2.5 text-slate-950 transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </div>

      {chips.length > 0 && (
        <div className="mt-3 space-y-1">
          {chips.map((chip) => (
            <div key={chip.id}>
              <button
                onClick={() => toggleChip(chip.id)}
                className="flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-left text-xs text-slate-400 hover:bg-white/10"
              >
                {chip.open ? (
                  <ChevronDown className="h-3 w-3" />
                ) : (
                  <ChevronRight className="h-3 w-3" />
                )}
                Tool call: {String(chip.call.name ?? 'unknown')}
              </button>
              {chip.open && (
                <pre className="mt-1 overflow-x-auto rounded-lg border border-white/10 bg-slate-900 p-3 text-[11px] text-slate-300">
                  {JSON.stringify(chip.call, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {(tokens || streaming) && (
        <div className="mt-4 min-h-[60px] rounded-xl border border-white/10 bg-slate-900 p-4 text-sm leading-7 text-slate-200">
          {tokens}
          {streaming && (
            <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-emerald-400" />
          )}
        </div>
      )}

      {error && <p className="mt-3 text-xs text-rose-400">{error}</p>}
    </div>
  )
}
