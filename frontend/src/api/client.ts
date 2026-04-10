const BASE = '' // Vite proxy handles routing

function getAuthToken(): string | null {
  return sessionStorage.getItem('authToken')
}

export function clearAuth() {
  sessionStorage.removeItem('authToken')
}

export async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getAuthToken()
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) headers['X-Auth-Token'] = token

  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers: { ...headers, ...(options?.headers as Record<string, string> || {}) },
  })

  if (res.status === 401) {
    clearAuth()
    window.location.reload()
    throw new Error('Authentication required')
  }

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  // Auth
  validatePassword: (password: string) =>
    fetchJSON<{ valid: boolean; token?: string }>('/auth/validate', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),

  // Call controls
  startCall: (body: any) =>
    fetchJSON('/call/start', { method: 'POST', body: JSON.stringify(body) }),
  hangup: () => fetchJSON('/call/hangup', { method: 'POST' }),
  getStatus: () => fetchJSON('/status'),

  // Prompt management
  listPrompts: () => fetchJSON<any[]>('/api/prompts'),
  getPrompt: (id: string) => fetchJSON(`/api/prompts/${id}`),
  savePrompt: (body: any) =>
    fetchJSON('/api/prompts', { method: 'POST', body: JSON.stringify(body) }),
  deletePrompt: (id: string) =>
    fetchJSON(`/api/prompts/${id}`, { method: 'DELETE' }),
  generatePrompt: (body: any) =>
    fetchJSON('/api/prompts/generate', { method: 'POST', body: JSON.stringify(body) }),
}
