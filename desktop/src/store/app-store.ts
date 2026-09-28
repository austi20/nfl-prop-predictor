import { create } from 'zustand'

import type { Pick } from '../lib/types'

function pickKey(pick: Pick): string {
  return `${pick.player_id}:${pick.stat}:${pick.line}:${pick.selected_side}`
}

type AppState = {
  apiBaseUrl: string
  setApiBaseUrl: (apiBaseUrl: string) => void
  // Parlay slip: legs picked off the live prop board. Runtime-only (not
  // persisted) -- a Pick carries a full distribution + game context that goes
  // stale the moment the board rebuilds.
  parlayCart: Pick[]
  isInCart: (pick: Pick) => boolean
  toggleCartPick: (pick: Pick) => void
  removeCartPick: (pick: Pick) => void
  clearCart: () => void
}

export const useAppStore = create<AppState>()((set, get) => ({
  apiBaseUrl: '',
  setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
  parlayCart: [],
  isInCart: (pick) => get().parlayCart.some((p) => pickKey(p) === pickKey(pick)),
  toggleCartPick: (pick) =>
    set((state) => {
      const key = pickKey(pick)
      const exists = state.parlayCart.some((p) => pickKey(p) === key)
      return {
        parlayCart: exists
          ? state.parlayCart.filter((p) => pickKey(p) !== key)
          : [...state.parlayCart, pick],
      }
    }),
  removeCartPick: (pick) =>
    set((state) => ({ parlayCart: state.parlayCart.filter((p) => pickKey(p) !== pickKey(pick)) })),
  clearCart: () => set({ parlayCart: [] }),
}))
