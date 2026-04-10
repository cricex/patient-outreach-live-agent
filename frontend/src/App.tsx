import { useState, useEffect } from 'react'
import { LoginScreen } from './components/LoginScreen'
import { PromptEditor } from './components/PromptEditor'
import { CallControls } from './components/CallControls'
import { DiagnosticsPanel } from './components/DiagnosticsPanel'
import { useDemoMode } from './hooks/useDemoMode'
import type { PromptSet } from './types'

function App() {
  const [authChecked, setAuthChecked] = useState(false)
  const [authRequired, setAuthRequired] = useState(true)
  const [authenticated, setAuthenticated] = useState(() => {
    return !!sessionStorage.getItem('authToken')
  })
  const [selectedScenario, setSelectedScenario] = useState<PromptSet | null>(null)
  const [scenarios, setScenarios] = useState<PromptSet[]>([])
  const [systemPrompt, setSystemPrompt] = useState('')
  const [callBrief, setCallBrief] = useState('')
  const { isDemoMode, mockScenarios } = useDemoMode()

  // Check if backend requires auth
  useEffect(() => {
    fetch('/auth/status')
      .then(r => r.json())
      .then(data => {
        setAuthRequired(data.auth_required)
        setAuthChecked(true)
      })
      .catch(() => {
        setAuthRequired(false)
        setAuthChecked(true)
      })
  }, [])

  function handlePromptChange(sp: string, cb: string) {
    setSystemPrompt(sp)
    setCallBrief(cb)
  }

  async function handleScenarioSelect(id: string) {
    if (!id) {
      setSelectedScenario(null)
      setSystemPrompt('')
      setCallBrief('')
      return
    }
    // Fetch fresh from API to ensure we have latest data
    try {
      const prompt = await fetch(`/api/prompts/${id}`).then(r => r.json())
      setSelectedScenario(prompt)
    } catch {
      const found = scenarios.find(s => s.id === id)
      if (found) setSelectedScenario(found)
    }
  }

  if (!authChecked) {
    return <div className="h-screen flex items-center justify-center bg-gray-950 text-gray-400">Loading...</div>
  }

  if (authRequired && !authenticated) {
    return <LoginScreen onLogin={() => setAuthenticated(true)} />
  }

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="shrink-0 border-b border-gray-800 bg-gray-900/80 backdrop-blur-sm">
        <div className="px-6 py-3 flex items-center">
          {/* Left: Brand */}
          <div className="shrink-0">
            <div className="text-sm font-semibold text-white tracking-tight">Live Voice Agent Studio</div>
            <div className="text-[10px] text-blue-400 uppercase tracking-widest font-medium">
              Azure AI Foundry
              {isDemoMode && (
                <span className="text-amber-400 font-mono ml-2">DEMO</span>
              )}
            </div>
          </div>

          {/* Right: Scenario selector */}
          <div className="ml-auto flex items-center gap-3">
            <label className="text-[10px] text-gray-500 uppercase tracking-widest">Scenario</label>
            <select
              value={selectedScenario?.id || ''}
              onChange={(e) => handleScenarioSelect(e.target.value)}
              className="bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500 min-w-[200px]"
            >
              <option value="">— New Scenario —</option>
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <span className="text-xs text-gray-600 font-mono">v2.0</span>
          </div>
        </div>
      </header>

      {/* Main: 60/40 split */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Prompt Configuration (60%) */}
        <div className="w-3/5 border-r border-gray-800 flex flex-col min-h-0">
          <div className="flex-1 px-5 py-4 overflow-y-auto">
            <PromptEditor
              onPromptChange={handlePromptChange}
              selectedScenario={selectedScenario}
              onScenarioChange={setSelectedScenario}
              onScenariosLoaded={setScenarios}
              demoScenarios={isDemoMode ? mockScenarios : null}
            />
          </div>
        </div>

        {/* Right: Dialer + Diagnostics (40%) */}
        <div className="w-2/5 flex flex-col min-h-0">
          {/* Top: Call Settings */}
          <div className="border-b border-gray-800 flex flex-col min-h-0">
            <div className="px-5 pt-4 pb-2 shrink-0">
              <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
                Call Settings
              </h2>
            </div>
            <div className="px-5 pb-4 overflow-y-auto">
              <CallControls systemPrompt={systemPrompt} callBrief={callBrief} />
            </div>
          </div>

          {/* Bottom: Diagnostics */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="px-5 pt-4 pb-2 shrink-0">
              <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
                Live Diagnostics
              </h2>
            </div>
            <div className="flex-1 px-5 pb-4 overflow-hidden">
              <DiagnosticsPanel callActive={true} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
