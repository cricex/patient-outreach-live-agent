import { useState } from 'react'
import { PromptEditor } from './components/PromptEditor'
import { CallControls } from './components/CallControls'
import { DiagnosticsPanel } from './components/DiagnosticsPanel'
import { useDemoMode } from './hooks/useDemoMode'
import type { PromptSet } from './types'

function App() {
  const [selectedScenario, setSelectedScenario] = useState<PromptSet | null>(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [callBrief, setCallBrief] = useState('')
  const { isDemoMode, mockScenarios } = useDemoMode()

  function handlePromptChange(sp: string, cb: string) {
    setSystemPrompt(sp)
    setCallBrief(cb)
  }

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="shrink-0 border-b border-gray-800 bg-gray-900/80 backdrop-blur-sm">
        <div className="px-6 py-3 flex items-center">
          {/* Left: Brand */}
          <div className="w-1/4">
            <div className="text-sm font-semibold text-white tracking-tight">Live Voice Agent Studio</div>
            <div className="text-[10px] text-blue-400 uppercase tracking-widest font-medium">
              Azure AI Foundry
              {isDemoMode && (
                <span className="text-amber-400 font-mono ml-2">DEMO</span>
              )}
            </div>
          </div>

          {/* Center: Scenario title */}
          <div className="flex-1 text-center">
            <h1 className="text-xl font-bold text-white tracking-tight">
              {selectedScenario?.name || 'New Scenario'}
            </h1>
            {selectedScenario?.description && (
              <p className="text-xs text-gray-500 mt-0.5 max-w-md mx-auto truncate">
                {selectedScenario.description}
              </p>
            )}
          </div>

          {/* Right: Status area */}
          <div className="w-1/4 flex justify-end">
            <div className="text-xs text-gray-500 font-mono">
              v2.0
            </div>
          </div>
        </div>
      </header>

      {/* Main: 40/60 split */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Prompt Configuration (40%) */}
        <div className="w-2/5 border-r border-gray-800 flex flex-col min-h-0">
          <div className="px-5 pt-4 pb-2 shrink-0">
            <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
              Prompt Configuration
            </h2>
            <p className="text-[11px] text-gray-600 mt-0.5">
              Describe the scenario first, then generate or edit directly
            </p>
          </div>
          <div className="flex-1 px-5 pb-4 overflow-y-auto">
            <PromptEditor
              onPromptChange={handlePromptChange}
              selectedScenario={selectedScenario}
              onScenarioChange={setSelectedScenario}
              demoScenarios={isDemoMode ? mockScenarios : null}
            />
          </div>
        </div>

        {/* Right: Dialer + Diagnostics (60%) */}
        <div className="w-3/5 flex flex-col min-h-0">
          {/* Top: Call Settings */}
          <div className="border-b border-gray-800 flex flex-col min-h-0">
            <div className="px-5 pt-4 pb-2 shrink-0 flex items-center justify-between">
              <div>
                <h2 className="text-[11px] font-semibold text-gray-400 uppercase tracking-widest">
                  Call Settings
                </h2>
                <p className="text-[11px] text-gray-600 mt-0.5">
                  Configure telephony, simulation mode, and runtime model settings
                </p>
              </div>
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
              <p className="text-[11px] text-gray-600 mt-0.5">
                Realtime audio activity, transport metrics, and session events
              </p>
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
