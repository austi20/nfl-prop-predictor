import { create } from 'zustand'
import { persist } from 'zustand/middleware'

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
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
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
