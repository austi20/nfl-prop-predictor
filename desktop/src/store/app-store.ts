import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { Pick } from '../lib/types'

function pickKey(pick: Pick): string {
  return `${pick.player_id}:${pick.stat}:${pick.line}:${pick.selected_side}`
}

type AppState = {
  apiBaseUrl: string
  setApiBaseUrl: (apiBaseUrl: string) => void
  theme: 'dark' | 'light'
  minEdgeDefault: number
  defaultStatFilter: string[]
  simpleMode: boolean
  setTheme: (theme: 'dark' | 'light') => void
  setMinEdgeDefault: (v: number) => void
  setDefaultStatFilter: (v: string[]) => void
  setSimpleMode: (v: boolean) => void
  // Parlay slip: legs picked off the live prop board. Runtime-only (not
  // persisted) -- a Pick carries a full distribution + game context that goes
  // stale the moment the board rebuilds.
  parlayCart: Pick[]
  isInCart: (pick: Pick) => boolean
  toggleCartPick: (pick: Pick) => void
  removeCartPick: (pick: Pick) => void
  clearCart: () => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      apiBaseUrl: '',
      setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
      theme: 'dark',
      minEdgeDefault: 0,
      defaultStatFilter: [],
      simpleMode: false,
      setTheme: (theme) => set({ theme }),
      setMinEdgeDefault: (minEdgeDefault) => set({ minEdgeDefault }),
      setDefaultStatFilter: (defaultStatFilter) => set({ defaultStatFilter }),
      setSimpleMode: (simpleMode) => set({ simpleMode }),
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
    }),
    {
      name: 'nfl-prop-workstation:prefs',
      partialize: (state) => ({
        theme: state.theme,
        minEdgeDefault: state.minEdgeDefault,
        defaultStatFilter: state.defaultStatFilter,
        simpleMode: state.simpleMode,
      }),
    },
  ),
)
