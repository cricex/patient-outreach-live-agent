import { useState, useEffect } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { WaveformDisplay } from './WaveformDisplay'
import { EventLog } from './EventLog'
import { MetricsBar } from './MetricsBar'
import type { DiagnosticEvent, CallStatus } from '../types'

interface DiagnosticsPanelProps {
  callActive: boolean
}

export function DiagnosticsPanel({ callActive }: DiagnosticsPanelProps) {
  const [events, setEvents] = useState<DiagnosticEvent[]>([])
  const [callerLevel, setCallerLevel] = useState(0)
  const [agentLevel, setAgentLevel] = useState(0)
  const [framesIn, setFramesIn] = useState(0)
  const [framesOut, setFramesOut] = useState(0)
  const [elapsed, setElapsed] = useState(0)

  // Diagnostics WebSocket
  const { lastMessage: diagMsg } = useWebSocket('/ws/diagnostics', true)
  // Call status WebSocket
  const { lastMessage: statusMsg } = useWebSocket('/ws/call-status', true)

  // Process diagnostic events
  useEffect(() => {
    if (!diagMsg) return
    if (diagMsg.type === 'ping') return

    // History replay
    if (diagMsg.type === 'history' && Array.isArray(diagMsg.events)) {
      setEvents(diagMsg.events)
      return
    }

    const event = diagMsg as DiagnosticEvent

    // Update audio levels for waveform
    if (event.type === 'audio.inbound') {
      setCallerLevel(Math.min(1, (event.data.frames || 0) / 100))
    } else if (event.type === 'audio.outbound') {
      setAgentLevel(Math.min(1, (event.data.frames || 0) / 50))
    } else if (event.type === 'audio.barge_in') {
      setAgentLevel(0) // Visual feedback for interruption
    }

    // Add displayable events to log (skip raw audio metrics)
    const logTypes = [
      'transcript.user', 'transcript.agent', 'audio.barge_in',
      'call.started', 'call.ended', 'vl.session.ready', 'vl.error',
      'tool.call.started', 'tool.call.completed',
      'vl.session.started', 'vl.session.ended',
    ]
    if (logTypes.includes(event.type)) {
      setEvents(prev => [...prev.slice(-200), event])
    }
  }, [diagMsg])

  // Process call status
  useEffect(() => {
    if (!statusMsg) return
    const status = statusMsg as CallStatus
    if (status.media) {
      setFramesIn(status.media.inFrames || 0)
      setFramesOut(status.media.outFrames || 0)
    }
    if (status.call?.current?.duration_sec) {
      setElapsed(Math.floor(status.call.current.duration_sec))
    }
  }, [statusMsg])

  // Decay audio levels when no new data
  useEffect(() => {
    const interval = setInterval(() => {
      setCallerLevel(prev => prev * 0.85)
      setAgentLevel(prev => prev * 0.85)
    }, 100)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="flex flex-col h-full gap-2">
      <h2 className="text-xs font-medium text-gray-400 uppercase tracking-wide">Live Diagnostics</h2>

      {/* Waveform — ~45% */}
      <div className="h-[45%] min-h-[120px]">
        <WaveformDisplay
          callerLevel={callerLevel}
          agentLevel={agentLevel}
          active={callActive}
        />
      </div>

      {/* Metrics bar */}
      <MetricsBar framesIn={framesIn} framesOut={framesOut} elapsed={elapsed} />

      {/* Event log — remaining space */}
      <div className="flex-1 min-h-0 border border-gray-800 rounded bg-gray-900/50 overflow-hidden">
        <EventLog events={events} />
      </div>
    </div>
  )
}
