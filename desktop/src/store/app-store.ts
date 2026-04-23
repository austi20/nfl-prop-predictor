import { create } from 'zustand'

type AppState = {
  apiBaseUrl: string
  setApiBaseUrl: (apiBaseUrl: string) => void
}

export const useAppStore = create<AppState>((set) => ({
  apiBaseUrl: '',
  setApiBaseUrl: (apiBaseUrl) => set({ apiBaseUrl }),
}))
