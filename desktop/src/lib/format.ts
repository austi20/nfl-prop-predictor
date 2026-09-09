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

/** Signed fixed-decimal number ("+1.2", "-0.4", "0.0"). */
export function signed(value: unknown, digits = 1, dash = DASH): string {
  if (!finite(value)) return dash
  const s = value.toFixed(digits)
  return value > 0 ? `+${s}` : s
}

/** Probability / rate as a percent. Accepts a 0..1 fraction. */
export function pct(value: unknown, digits = 1, dash = DASH): string {
  if (!finite(value)) return dash
  return `${(value * 100).toFixed(digits)}%`
}

/** Signed percent from a 0..1 fraction ("+6.2%"). */
export function signedPct(value: unknown, digits = 1, dash = DASH): string {
  if (!finite(value)) return dash
  const p = (value * 100).toFixed(digits)
  return value > 0 ? `+${p}%` : `${p}%`
}

/** American odds ("+120", "-110"). */
export function americanOdds(value: unknown, dash = DASH): string {
  if (!finite(value)) return dash
  const r = Math.round(value)
  return r > 0 ? `+${r}` : `${r}`
}

/** Units of stake / profit ("+1.250u", "-1.000u"). */
export function units(value: unknown, digits = 3, dash = DASH): string {
  if (!finite(value)) return dash
  const s = value.toFixed(digits)
  return `${value > 0 ? '+' : ''}${s}u`
}

/** Integer with thousands separators. */
export function count(value: unknown, dash = DASH): string {
  if (!finite(value)) return dash
  return Math.round(value).toLocaleString('en-US')
}

/** "passing_yards" -> "Passing yards". */
export function statLabel(stat: string): string {
  if (!stat) return DASH
  const s = stat.replace(/_/g, ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** "00-0036223 rushing_yards under | ..." -> "Rushing yards under | ..." */
export function parlayLabel(label: string): string {
  if (!label) return DASH
  return label.replace(/_/g, ' ')
}

export const emptyDash = DASH
