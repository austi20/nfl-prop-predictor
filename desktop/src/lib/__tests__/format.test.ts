import { describe, expect, it } from 'vitest'

import { boomLabel, bustLabel } from '../format'

describe('boom/bust labels', () => {
  it('shows the chance and the point threshold', () => {
    expect(boomLabel(0.224, 21)).toBe('22% · 21.0+')
    expect(bustLabel(0.25, 7)).toBe('25% · ≤7.0')
  })

  it('dashes a missing threshold', () => {
    expect(boomLabel(0.2, undefined)).toBe('20% · —')
  })
})
