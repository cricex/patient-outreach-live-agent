import { useState } from 'react'
import { api } from '../api/client'

interface LoginScreenProps {
  onLogin: () => void
}

export function LoginScreen({ onLogin }: LoginScreenProps) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!password.trim()) return

    setLoading(true)
    setError(null)
    try {
      const result = await api.validatePassword(password)
      if (result.valid && result.token) {
        sessionStorage.setItem('authToken', result.token)
        onLogin()
      } else {
        setError('Invalid password')
      }
    } catch {
      setError('Connection failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex items-center justify-center bg-gray-950">
      <form onSubmit={handleSubmit} className="w-full max-w-sm px-6">
        <div className="text-center mb-8">
          <h1 className="text-xl font-semibold text-white">Live Voice Agent Studio</h1>
          <p className="text-sm text-blue-400 mt-1">Azure AI Foundry</p>
        </div>

        <div className="flex flex-col gap-3">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            className="w-full bg-gray-800 border border-gray-700 text-gray-100 rounded px-4 py-3 text-sm focus:outline-none focus:border-blue-500"
            autoFocus
          />

          <button
            type="submit"
            disabled={loading || !password.trim()}
            className="w-full px-4 py-3 bg-blue-600 text-white font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? 'Verifying...' : 'Enter'}
          </button>

          {error && (
            <p className="text-sm text-red-400 text-center">{error}</p>
          )}
        </div>
      </form>
    </div>
  )
}
