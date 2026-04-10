const BASE = '' // Vite proxy handles routing

export async function fetchJSON<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
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
