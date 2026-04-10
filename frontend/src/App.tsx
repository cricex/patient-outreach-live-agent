import { useState } from 'react'
import { PromptEditor } from './components/PromptEditor'
import { CallControls } from './components/CallControls'
import { DiagnosticsPanel } from './components/DiagnosticsPanel'
import type { PromptSet } from './types'

function App() {
  const [selectedScenario, setSelectedScenario] = useState<PromptSet | null>(null)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [callBrief, setCallBrief] = useState('')

  function handlePromptChange(sp: string, cb: string) {
    setSystemPrompt(sp)
    setCallBrief(cb)
  }

  return (
    <div className="h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="shrink-0 border-b border-gray-800 bg-gray-900">
        <div className="px-6 py-3 flex items-center justify-between">
          <span className="text-sm text-gray-400 font-medium">Voice Agent Studio</span>
          <h1 className="text-lg font-semibold text-white">
            {selectedScenario?.name || 'New Scenario'}
          </h1>
          <div className="w-32" /> {/* Spacer for balance */}
        </div>
      </header>

      {/* Main: 40/60 split */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Prompt Configuration (40%) */}
        <div className="w-2/5 border-r border-gray-800 p-4 overflow-y-auto">
          <PromptEditor
            onPromptChange={handlePromptChange}
            selectedScenario={selectedScenario}
            onScenarioChange={setSelectedScenario}
          />
        </div>

        {/* Right: Dialer + Diagnostics (60%) */}
        <div className="w-3/5 flex flex-col min-h-0">
          {/* Top: Call Controls (~35%) */}
          <div className="h-[35%] border-b border-gray-800 p-4 overflow-y-auto">
            <CallControls systemPrompt={systemPrompt} callBrief={callBrief} />
          </div>

          {/* Bottom: Diagnostics (~65%) */}
          <div className="flex-1 p-4 overflow-y-auto">
            <DiagnosticsPanel callActive={true} />
          </div>
        </div>
      </div>
    </div>
  )
}

export default App
