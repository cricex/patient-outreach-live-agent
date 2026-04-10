import { useState, useEffect } from 'react'
import { api } from '../api/client'
import type { PromptSet } from '../types'

interface PromptEditorProps {
  onPromptChange: (systemPrompt: string, callBrief: string) => void
  selectedScenario: PromptSet | null
  onScenarioChange: (scenario: PromptSet | null) => void
  demoScenarios?: PromptSet[] | null
}

export function PromptEditor({ onPromptChange, selectedScenario, onScenarioChange, demoScenarios }: PromptEditorProps) {
  const [scenarios, setScenarios] = useState<PromptSet[]>([])
  const [systemPrompt, setSystemPrompt] = useState('')
  const [callBrief, setCallBrief] = useState('')
  const [scenarioName, setScenarioName] = useState('')
  const [generating, setGenerating] = useState(false)
  const [showGenerate, setShowGenerate] = useState(false)
  const [generateInput, setGenerateInput] = useState('')
  const [saving, setSaving] = useState(false)

  // Load scenarios on mount
  useEffect(() => {
    loadScenarios()
  }, [])

  // Sync from selected scenario
  useEffect(() => {
    if (selectedScenario) {
      setSystemPrompt(selectedScenario.system_prompt)
      setCallBrief(selectedScenario.call_brief)
      setScenarioName(selectedScenario.name)
    }
  }, [selectedScenario])

  // Propagate changes up
  useEffect(() => {
    onPromptChange(systemPrompt, callBrief)
  }, [systemPrompt, callBrief])

  async function loadScenarios() {
    try {
      const list = await api.listPrompts() as PromptSet[]
      setScenarios(list)
      // Auto-select first if none selected
      if (!selectedScenario && list.length > 0) {
        onScenarioChange(list[0])
      }
    } catch (err) {
      // Fallback to demo scenarios if backend unavailable
      if (demoScenarios && demoScenarios.length > 0) {
        setScenarios(demoScenarios)
        if (!selectedScenario) {
          onScenarioChange(demoScenarios[0])
        }
      }
      console.error('Failed to load scenarios:', err)
    }
  }

  async function handleSelectScenario(id: string) {
    if (!id) {
      onScenarioChange(null)
      setSystemPrompt('')
      setCallBrief('')
      setScenarioName('')
      return
    }
    try {
      const prompt = await api.getPrompt(id) as PromptSet
      onScenarioChange(prompt)
    } catch (err) {
      console.error('Failed to load scenario:', err)
    }
  }

  async function handleGenerate() {
    if (!generateInput.trim()) return
    setGenerating(true)
    try {
      const result = await api.generatePrompt({ scenario: generateInput }) as { system_prompt: string; call_brief: string }
      setSystemPrompt(result.system_prompt)
      setCallBrief(result.call_brief)
      setShowGenerate(false)
      setGenerateInput('')
    } catch (err) {
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
      {/* Scenario selector */}
      <div>
        <select
          value={selectedScenario?.id || ''}
          onChange={(e) => handleSelectScenario(e.target.value)}
          className="w-full bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500"
        >
          <option value="">— New Scenario —</option>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>

      {/* Scenario name (editable) */}
      <input
        type="text"
        value={scenarioName}
        onChange={(e) => setScenarioName(e.target.value)}
        placeholder="Scenario name..."
        className="bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
      />

      {/* System Prompt */}
      <div className="flex-1 flex flex-col min-h-0">
        <label className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">System Prompt</label>
        <textarea
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 rounded p-3 font-mono text-xs resize-none focus:outline-none focus:border-blue-500 min-h-[200px]"
          placeholder="Enter system prompt..."
        />
      </div>

      {/* Generate with AI */}
      {showGenerate ? (
        <div className="flex gap-2">
          <input
            type="text"
            value={generateInput}
            onChange={(e) => setGenerateInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
            placeholder="Describe your scenario..."
            className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
            autoFocus
          />
          <button
            onClick={handleGenerate}
            disabled={generating}
            className="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-500 disabled:opacity-50"
          >
            {generating ? '...' : 'Go'}
          </button>
          <button
            onClick={() => setShowGenerate(false)}
            className="px-2 py-1.5 text-gray-400 text-sm hover:text-white"
          >
            ✕
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowGenerate(true)}
          className="self-start px-3 py-1.5 text-sm text-blue-400 hover:text-blue-300 transition-colors"
        >
          ✨ Generate with AI
        </button>
      )}

      {/* Call Brief */}
      <div className="flex-1 flex flex-col min-h-0">
        <label className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">Call Brief</label>
        <textarea
          value={callBrief}
          onChange={(e) => setCallBrief(e.target.value)}
          className="flex-1 bg-gray-800 border border-gray-700 text-gray-100 rounded p-3 font-mono text-xs resize-none focus:outline-none focus:border-blue-500 min-h-[150px]"
          placeholder="Enter call brief..."
        />
      </div>

      {/* Save / Delete */}
      <div className="flex items-center gap-3 pt-1">
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
