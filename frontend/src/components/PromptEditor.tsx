import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { PromptSet } from '../types'

interface PromptEditorProps {
  onPromptChange: (systemPrompt: string, callBrief: string) => void
  selectedScenario: PromptSet | null
  onScenarioChange: (scenario: PromptSet | null) => void
  onScenariosLoaded: (scenarios: PromptSet[]) => void
  demoScenarios?: PromptSet[] | null
}

export function PromptEditor({ onPromptChange, selectedScenario, onScenarioChange, onScenariosLoaded, demoScenarios }: PromptEditorProps) {
  const [systemPrompt, setSystemPrompt] = useState('')
  const [callBrief, setCallBrief] = useState('')
  const [scenarioName, setScenarioName] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generateInput, setGenerateInput] = useState('')
  const [generateError, setGenerateError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    loadScenarios()
  }, [])

  useEffect(() => {
    if (selectedScenario) {
      setSystemPrompt(selectedScenario.system_prompt)
      setCallBrief(selectedScenario.call_brief)
      setScenarioName(selectedScenario.name)
    } else {
      setSystemPrompt('')
      setCallBrief('')
      setScenarioName('')
    }
  }, [selectedScenario])

  useEffect(() => {
    onPromptChange(systemPrompt, callBrief)
  }, [systemPrompt, callBrief])

  async function loadScenarios() {
    try {
      const list = await api.listPrompts() as PromptSet[]
      onScenariosLoaded(list)
      if (!selectedScenario && list.length > 0) {
        onScenarioChange(list[0])
      }
    } catch (err) {
      if (demoScenarios && demoScenarios.length > 0) {
        onScenariosLoaded(demoScenarios)
        if (!selectedScenario) {
          onScenarioChange(demoScenarios[0])
        }
      }
      console.error('Failed to load scenarios:', err)
    }
  }

  async function handleGenerate() {
    if (!generateInput.trim()) return
    setGenerating(true)
    setGenerateError(null)
    try {
      const result = await api.generatePrompt({ scenario: generateInput }) as { system_prompt: string; call_brief: string }
      setSystemPrompt(result.system_prompt)
      setCallBrief(result.call_brief)
    } catch (err: any) {
      const msg = err?.message || 'Generation failed'
      setGenerateError(msg)
      console.error('Generate failed:', err)
    } finally {
      setGenerating(false)
    }
  }

  async function handleSave() {
    const name = scenarioName.trim() || 'Untitled Scenario'
    setSaving(true)
    try {
      const saved = await api.savePrompt({
        id: selectedScenario?.id || '',
        name,
        description: '',
        system_prompt: systemPrompt,
        call_brief: callBrief,
        voice: selectedScenario?.voice || null,
        model: selectedScenario?.model || null,
        target_phone_number: selectedScenario?.target_phone_number || null,
      }) as PromptSet
      onScenarioChange(saved)
      await loadScenarios()
    } catch (err) {
      console.error('Save failed:', err)
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!selectedScenario?.id) return
    if (!confirm(`Delete "${selectedScenario.name}"?`)) return
    try {
      await api.deletePrompt(selectedScenario.id)
      onScenarioChange(null)
      setSystemPrompt('')
      setCallBrief('')
      setScenarioName('')
      await loadScenarios()
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  return (
    <div className="flex flex-col h-full gap-3">
      {/* AI Scenario Generator — primary input */}
      <div className="shrink-0">
        <label className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1.5 block">
          Describe Your Scenario
        </label>
        <textarea
          value={generateInput}
          onChange={(e) => setGenerateInput(e.target.value)}
          placeholder={"Describe the use case in plain language and AI will generate the system prompt and call brief.\n\nExamples:\n• Patient outreach for overdue mammogram screening\n• Insurance prior authorization for MRI\n• Appointment reminder with rescheduling option\n• Debt collection follow-up call"}
          className="w-full bg-gray-800 border border-gray-700 text-gray-100 rounded p-3 text-sm resize-none focus:outline-none focus:border-blue-500 min-h-[100px]"
          rows={4}
        />
        <button
          onClick={handleGenerate}
          disabled={generating || !generateInput.trim()}
          className="mt-2 w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {generating ? '✨ Generating...' : '✨ Generate with AI'}
        </button>
        {generateError && (
          <p className="text-xs text-red-400 mt-1">{generateError}</p>
        )}
      </div>

      {/* Divider */}
      <div className="flex items-center gap-3 shrink-0">
        <div className="flex-1 h-px bg-gray-800" />
        <span className="text-[10px] text-gray-600 uppercase tracking-widest">or edit directly</span>
        <div className="flex-1 h-px bg-gray-800" />
      </div>

      {/* Scenario name */}
      <input
        type="text"
        value={scenarioName}
        onChange={(e) => setScenarioName(e.target.value)}
        placeholder="Scenario name..."
        className="bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500 shrink-0"
      />

      {/* System Prompt */}
      <div className="flex-1 flex flex-col min-h-0">
        <label className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">System Prompt</label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 rounded p-3 font-mono text-xs resize-none focus:outline-none focus:border-blue-500 min-h-[120px]"
          placeholder="System prompt defines the agent's behavior, tone, and rules..."
        />
      </div>

      {/* Call Brief */}
      <div className="flex-1 flex flex-col min-h-0">
        <label className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Call Brief</label>
        <textarea
          value={callBrief}
          onChange={(e) => setCallBrief(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 rounded p-3 font-mono text-xs resize-none focus:outline-none focus:border-blue-500 min-h-[100px]"
          placeholder="Call brief provides scenario-specific context: patient/customer details, reason for call, key data..."
        />
      </div>

      {/* Save / Delete */}
      <div className="flex items-center gap-3 shrink-0">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-1.5 bg-gray-700 text-gray-100 text-sm rounded hover:bg-gray-600 disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Scenario'}
        </button>
        {selectedScenario && (
          <button
            onClick={handleDelete}
            className="text-sm text-red-400 hover:text-red-300"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  )
}
