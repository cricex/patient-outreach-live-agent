import { useState, useEffect, useCallback } from 'react'
import type { PromptSet, DiagnosticEvent } from '../types'

const MOCK_SCENARIOS: PromptSet[] = [
  {
    id: 'colonoscopy-outreach',
    name: 'Colonoscopy Outreach',
    description: 'Preventive colonoscopy scheduling for patients with family history',
    system_prompt: 'BEGIN SYSTEM\nROLE: Scheduling assistant for Microsoft Health Clinic.\nGOAL: Help the patient schedule a colonoscopy.\nSTYLE: Warm, brief, natural. 8-18 words per turn.\nFLOW: greet → confirm identity → purpose → answer Qs → schedule → confirm → close.\nEND SYSTEM',
    call_brief: 'BEGIN CALL_BRIEF\nTOP_NEED: colonoscopy\nPRIORITY: urgent\nPATIENT_NAME: Charles\nTIMING: now\nWHY: Family history of colon cancer; screening overdue.\nEND CALL_BRIEF',
    voice: 'sage',
    model: 'gpt-realtime',
    target_phone_number: null,
    created_at: '2026-04-10T00:00:00Z',
    updated_at: '2026-04-10T00:00:00Z',
  },
  {
    id: 'prior-auth-neuro',
    name: 'Prior Auth — Neuro MRI',
    description: 'Provider office calling payer for prior authorization on brain MRI',
    system_prompt: 'BEGIN SYSTEM\nROLE: Prior Authorization Specialist for Central Texas Neuro Clinic.\nGOAL: Get MRI request accepted for review.\nSTYLE: Calm, efficient, cooperative. 1 sentence per turn.\nFLOW: greet → verify caller → provide member info → request details → clinical rationale → confirm documents → get reference number.\nEND SYSTEM',
    call_brief: 'BEGIN PRIOR_AUTH_BRIEF\nPAYER_NAME: Northlake Health Plan\nCALLER: Alex Morgan, Prior Auth Specialist\nPROVIDER: Priya Shah, MD — Neurology — NPI: 1548329107\nMEMBER: Jordan Rivera — DOB: April 12, 1981 — ID: NLH-84729361\nSERVICE: MRI Brain w/wo contrast — CPT: 70553\nICD-10: G43.719\nEND PRIOR_AUTH_BRIEF',
    voice: 'sage',
    model: 'gpt-realtime',
    target_phone_number: null,
    created_at: '2026-04-10T00:00:00Z',
    updated_at: '2026-04-10T00:00:00Z',
  },
]

const MOCK_EVENTS: DiagnosticEvent[] = [
  { type: 'call.started', timestamp: Date.now() / 1000 - 83, data: { call_id: 'demo-001', destination: '+15125551234' } },
  { type: 'vl.session.ready', timestamp: Date.now() / 1000 - 80, data: { session_id: 'vl-demo' } },
  { type: 'transcript.agent', timestamp: Date.now() / 1000 - 75, data: { text: 'Hi, is this Charles?' } },
  { type: 'transcript.user', timestamp: Date.now() / 1000 - 70, data: { text: 'Yes, this is Charles.' } },
  { type: 'transcript.agent', timestamp: Date.now() / 1000 - 65, data: { text: "Great. I'm calling from Microsoft Health Clinic about a colonoscopy you may be due for." } },
  { type: 'transcript.user', timestamp: Date.now() / 1000 - 55, data: { text: 'Oh right, my doctor mentioned that.' } },
  { type: 'transcript.agent', timestamp: Date.now() / 1000 - 50, data: { text: 'It checks the colon for polyps and helps prevent cancer. Can we look at times this week?' } },
  { type: 'transcript.user', timestamp: Date.now() / 1000 - 40, data: { text: 'Thursday works for me.' } },
  { type: 'transcript.agent', timestamp: Date.now() / 1000 - 35, data: { text: "Perfect, I'll set that up for Thursday at 1:40pm at Microsoft Health Clinic." } },
]

export function useDemoMode() {
  const [isDemoMode, setIsDemoMode] = useState(false)
  const [demoEvents, setDemoEvents] = useState<DiagnosticEvent[]>([])
  const [callerLevel, setCallerLevel] = useState(0)
  const [agentLevel, setAgentLevel] = useState(0)

  // Check if backend is available
  useEffect(() => {
    fetch('/health')
      .then(res => {
        if (!res.ok) setIsDemoMode(true)
      })
      .catch(() => setIsDemoMode(true))
  }, [])

  // Simulate waveform activity in demo mode
  useEffect(() => {
    if (!isDemoMode) return

    setDemoEvents(MOCK_EVENTS)

    const interval = setInterval(() => {
      // Simulate natural speech patterns with randomized amplitude
      const speaking = Math.random() > 0.3
      const level = speaking ? 0.2 + Math.random() * 0.6 : Math.random() * 0.05

      // Alternate between caller and agent
      const isAgent = Math.sin(Date.now() / 3000) > 0
      if (isAgent) {
        setAgentLevel(level)
        setCallerLevel(Math.random() * 0.05)
      } else {
        setCallerLevel(level)
        setAgentLevel(Math.random() * 0.05)
      }
    }, 80)

    return () => clearInterval(interval)
  }, [isDemoMode])

  const getScenarios = useCallback(() => {
    return isDemoMode ? MOCK_SCENARIOS : null
  }, [isDemoMode])

  return {
    isDemoMode,
    setIsDemoMode,
    mockScenarios: MOCK_SCENARIOS,
    demoEvents,
    callerLevel,
    agentLevel,
    getScenarios,
  }
}
