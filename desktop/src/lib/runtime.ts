import { useAppStore } from '../store/app-store'

const browserFallback =
  import.meta.env.VITE_API_BASE_URL?.toString() ?? 'http://127.0.0.1:8000'

const BROWSER_API_RETRIES = 120
const BROWSER_API_MS = 500

/** Browser-only: wait for a manually run API (Tauri already blocks until the sidecar TCP port is open). */
export async function waitForApiReadyInBrowser(baseUrl: string) {
  for (let i = 0; i < BROWSER_API_RETRIES; i++) {
    try {
      const res = await fetch(`${baseUrl}/api/health`, { method: 'GET' })
      if (res.ok) {
        return
      }
    } catch {
      // connection refused
    }
    await new Promise((r) => setTimeout(r, BROWSER_API_MS))
  }
  throw new Error(
    'API did not become ready. Start it (e.g. uv run uvicorn api.server:app --host 127.0.0.1 --port 8000) or set VITE_API_BASE_URL.',
  )
}

export async function resolveApiBaseUrl() {
  const current = useAppStore.getState().apiBaseUrl
  if (current) {
    return current
  }

  let baseUrl: string
  let fromTauri = false
  try {
    const { invoke } = await import('@tauri-apps/api/core')
    baseUrl = await invoke<string>('api_base_url')
    fromTauri = true
  } catch {
    baseUrl = browserFallback
  }

  if (!fromTauri) {
    await waitForApiReadyInBrowser(baseUrl)
  }

  useAppStore.getState().setApiBaseUrl(baseUrl)
  return baseUrl
}
