import { useRef, useEffect } from 'react'
import type { DiagnosticEvent } from '../types'

interface EventLogProps {
  events: DiagnosticEvent[]
}

const eventIcons: Record<string, string> = {
  'transcript.user': '🎤',
  'transcript.agent': '🤖',
  'audio.barge_in': '⚡',
  'vl.error': '❌',
  'call.started': '📞',
  'call.ended': '📴',
  'tool.call.started': '🔧',
  'tool.call.completed': '✅',
  'vl.session.ready': '🟢',
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function eventText(event: DiagnosticEvent): string {
  const d = event.data
  switch (event.type) {
    case 'transcript.user': return `User: "${d.text || ''}"`
    case 'transcript.agent': return `Agent: "${d.text || ''}"`
    case 'audio.barge_in': return 'Barge-in detected'
    case 'call.started': return `Call started → ${d.destination || d.call_id || ''}`
    case 'call.ended': return `Call ended: ${d.reason || ''}`
    case 'vl.error': return `Error: ${d.message || ''}`
    case 'vl.session.ready': return 'Voice Live session ready'
    case 'tool.call.started': return `Calling: ${d.name || 'function'}`
    case 'tool.call.completed': return `Result: ${d.name || 'function'}`
    default: return event.type
  }
}

export function EventLog({ events }: EventLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [events.length])

  return (
    <div className="h-full overflow-y-auto font-mono text-xs">
      {events.length === 0 ? (
        <div className="text-gray-600 text-center py-4">No events yet</div>
      ) : (
        events.map((ev, i) => (
          <div key={i} className="flex gap-2 py-0.5 px-2 hover:bg-gray-800/50">
            <span className="text-gray-500 shrink-0">{formatTs(ev.timestamp)}</span>
            <span className="shrink-0">{eventIcons[ev.type] || '•'}</span>
            <span className="text-gray-300 break-all">{eventText(ev)}</span>
          </div>
        ))
      )}
      <div ref={bottomRef} />
    </div>
  )
}
