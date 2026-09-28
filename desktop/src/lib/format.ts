// Display formatting. Every value that reaches the DOM goes through one of
// these so a raw 9.97561, a NaN, or an undefined never renders.

const DASH = '—' // em dash for "no value"

function finite(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

/** Fixed-decimal number; `dash` for nullish / non-finite. */
export function num(value: unknown, digits = 1, dash = DASH): string {
  if (!finite(value)) return dash
  return value.toFixed(digits)
}

/** Probability / rate as a percent. Accepts a 0..1 fraction. */
export function pct(value: unknown, digits = 1, dash = DASH): string {
  if (!finite(value)) return dash
  return `${(value * 100).toFixed(digits)}%`
}

/** Units of stake / profit ("+1.250u", "-1.000u"). */
export function units(value: unknown, digits = 3, dash = DASH): string {
  if (!finite(value)) return dash
  const s = value.toFixed(digits)
  return `${value > 0 ? '+' : ''}${s}u`
}

/** "22% · 21.0+": chance of a boom and the points it takes. */
export function boomLabel(prob: unknown, cutoff: unknown): string {
  return `${pct(prob, 0)} · ${finite(cutoff) ? `${cutoff.toFixed(1)}+` : DASH}`
}

/** "25% · ≤7.0": chance of a bust and the points that make one. */
export function bustLabel(prob: unknown, cutoff: unknown): string {
  return `${pct(prob, 0)} · ${finite(cutoff) ? `≤${cutoff.toFixed(1)}` : DASH}`
}
