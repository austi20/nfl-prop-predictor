import { useAppStore } from '../store/app-store'

const browserFallback =
  import.meta.env.VITE_API_BASE_URL?.toString() ?? 'http://127.0.0.1:8000'

export async function resolveApiBaseUrl() {
  const current = useAppStore.getState().apiBaseUrl
  if (current) {
    return current
  }

  try {
    const { invoke } = await import('@tauri-apps/api/core')
    const apiBaseUrl = await invoke<string>('api_base_url')
    useAppStore.getState().setApiBaseUrl(apiBaseUrl)
    return apiBaseUrl
  } catch {
    useAppStore.getState().setApiBaseUrl(browserFallback)
    return browserFallback
  }
}
