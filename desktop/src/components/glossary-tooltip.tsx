import { cva } from 'class-variance-authority'
import type { ReactNode } from 'react'

const GLOSSARY: Record<string, string> = {
  edge: "How much our model probability exceeds the book's implied probability. Positive = value.",
  roi: 'Return on investment. Profit units divided by total staked units, as a percentage.',
  ev: 'Expected value. Average profit per bet if the model is well-calibrated.',
  'implied probability': "The probability the book assigns to an outcome, derived from the odds.",
  'fair odds': 'American odds computed from our model probability, before any book margin.',
  vig: "The book's margin built into the odds, also called juice or overround.",
  'boom/bust': 'Boom = top-decile fantasy score; Bust = bottom-decile. Probabilities from our model distribution.',
  shrinkage: 'A Bayesian technique pulling player estimates toward the position average to reduce noise on small samples.',
}

const tooltipClass = cva(
  'pointer-events-none absolute z-20 hidden group-hover:block bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 rounded-lg border border-white/10 bg-slate-900 p-3 text-xs leading-5 text-slate-300 shadow-xl',
)

type Props = {
  term: string
  children: ReactNode
}

export function GlossaryTooltip({ term, children }: Props) {
  const definition = GLOSSARY[term.toLowerCase()]
  if (!definition) return <>{children}</>
  return (
    <span
      className="group relative cursor-help underline decoration-dotted decoration-slate-500 underline-offset-2"
      aria-describedby={`glossary-${term}`}
    >
      {children}
      <span id={`glossary-${term}`} role="tooltip" className={tooltipClass()}>
        <span className="mb-1 block font-semibold capitalize text-slate-100">{term}</span>
        {definition}
      </span>
    </span>
  )
}
