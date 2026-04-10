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
  const [showDiagnostics, setShowDiagnostics] = useState(false)

  const { lastMessage: diagMsg } = useWebSocket('/ws/diagnostics', true)
  const { lastMessage: statusMsg } = useWebSocket('/ws/call-status', true)

  useEffect(() => {
    if (!diagMsg) return
    if (diagMsg.type === 'ping') return

    if (diagMsg.type === 'history' && Array.isArray(diagMsg.events)) {
      setEvents(diagMsg.events)
      return
    }

    const event = diagMsg as DiagnosticEvent

    if (event.type === 'audio.inbound') {
      setCallerLevel(Math.min(1, (event.data.frames || 0) / 100))
    } else if (event.type === 'audio.outbound') {
      setAgentLevel(Math.min(1, (event.data.frames || 0) / 50))
    } else if (event.type === 'audio.barge_in') {
      setAgentLevel(0)
    }

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

  useEffect(() => {
    const interval = setInterval(() => {
      setCallerLevel(prev => prev * 0.85)
      setAgentLevel(prev => prev * 0.85)
    }, 100)
    return () => clearInterval(interval)
  }, [])

  return (
    <div className="relative h-full flex flex-col">
      {/* Waveform — always visible, fills the space */}
      <div className="flex-1 min-h-0 relative">
        <WaveformDisplay
          callerLevel={callerLevel}
          agentLevel={agentLevel}
          active={callActive}
        />

        {/* Toggle button — top right corner of waveform */}
        {!showDiagnostics && (
          <button
            onClick={() => setShowDiagnostics(true)}
            className="absolute top-2 right-2 px-2.5 py-1 text-[10px] font-medium text-gray-400 bg-gray-900/70 border border-gray-700 rounded hover:text-white hover:border-gray-500 transition-colors backdrop-blur-sm"
          >
            Show Diagnostics
          </button>
        )}

        {/* Diagnostics overlay */}
        {showDiagnostics && (
          <div className="absolute inset-0 bg-gray-950/85 backdrop-blur-sm rounded flex flex-col p-3 gap-2 overflow-hidden">
            {/* Close button */}
            <div className="flex items-center justify-between shrink-0">
              <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest">
                Diagnostics
              </span>
              <button
                onClick={() => setShowDiagnostics(false)}
                className="text-gray-500 hover:text-white text-sm transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Metrics */}
            <MetricsBar framesIn={framesIn} framesOut={framesOut} elapsed={elapsed} />

            {/* Event log — fills remaining space */}
            <div className="flex-1 min-h-0 border border-gray-800 rounded bg-gray-900/50 overflow-hidden">
              <EventLog events={events} />
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
