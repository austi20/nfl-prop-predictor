import type { SlateResponse } from './types'
import { resolveApiBaseUrl } from './runtime'

async function request<T>(path: string, init?: RequestInit) {
  const baseUrl = await resolveApiBaseUrl()
  const response = await fetch(`${baseUrl}${path}`, {
    headers: {
      'Content-Type': 'application/json',
    },
    ...init,
  })

  if (!response.ok) {
    throw new Error(`Request failed for ${path}: ${response.status}`)
  }

  return (await response.json()) as T
}

export async function getSlate() {
  return request<SlateResponse>('/api/slate')
}
