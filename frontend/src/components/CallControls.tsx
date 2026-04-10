import { useState, useEffect } from 'react'
import { api } from '../api/client'
import { useWebSocket } from '../hooks/useWebSocket'
import type { CallStatus } from '../types'

interface CallControlsProps {
  systemPrompt: string
  callBrief: string
}

type CallState = 'idle' | 'connecting' | 'connected' | 'ended'

const DIALER_KEYS = [
  { digit: '1', letters: '' },
  { digit: '2', letters: 'ABC' },
  { digit: '3', letters: 'DEF' },
  { digit: '4', letters: 'GHI' },
  { digit: '5', letters: 'JKL' },
  { digit: '6', letters: 'MNO' },
  { digit: '7', letters: 'PQRS' },
  { digit: '8', letters: 'TUV' },
  { digit: '9', letters: 'WXYZ' },
  { digit: '*', letters: '' },
  { digit: '0', letters: '+' },
  { digit: '#', letters: '' },
]

export function CallControls({ systemPrompt, callBrief }: CallControlsProps) {
  const [phoneNumber, setPhoneNumber] = useState('')
  const [voice, setVoice] = useState('sage')
  const [model, setModel] = useState('gpt-realtime')
  const [simulate, setSimulate] = useState(false)
  const [callState, setCallState] = useState<CallState>('idle')
  const [, setCallId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)

  const { lastMessage } = useWebSocket('/ws/call-status', true)

  // Keyboard support: num row and numpad both work
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (isActive) return
      // Ignore if user is typing in another input/textarea
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return

      if (e.key >= '0' && e.key <= '9') {
        handleDialerPress(e.key)
      } else if (e.key === '+') {
        setPhoneNumber(prev => prev.startsWith('+') ? prev : '+' + prev)
      } else if (e.key === 'Backspace') {
        handleBackspace()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  })

  useEffect(() => {
    if (!lastMessage) return
    const status = lastMessage as CallStatus
    if (status.call?.current) {
      setCallState('connected')
      if (status.call.current.duration_sec) {
        setElapsed(Math.floor(status.call.current.duration_sec))
      }
    } else if (callState === 'connected') {
      setCallState('ended')
      setTimeout(() => setCallState('idle'), 3000)
    }
  }, [lastMessage])

  function handleDialerPress(digit: string) {
    if (isActive) return
    // Only allow digits and + for E.164 phone numbers
    if (digit === '*' || digit === '#') return
    if (digit === '0' && phoneNumber === '') {
      setPhoneNumber('+')
    } else {
      setPhoneNumber(prev => prev + digit)
    }
  }

  function handleBackspace() {
    if (isActive) return
    setPhoneNumber(prev => prev.slice(0, -1))
  }

  async function handleStart() {
    setError(null)
    setCallState('connecting')
    try {
      const result = await api.startCall({
        target_phone_number: phoneNumber || null,
        system_prompt: systemPrompt || null,
        call_brief: callBrief || null,
        simulate,
      }) as { call_id: string }
      setCallId(result.call_id)
      setCallState('connected')
      setElapsed(0)
    } catch (err: any) {
      setError(err.message || 'Call failed')
      setCallState('idle')
    }
  }

  async function handleHangup() {
    try {
      await api.hangup()
      setCallState('ended')
      setTimeout(() => setCallState('idle'), 3000)
    } catch (err: any) {
      setError(err.message || 'Hangup failed')
    }
  }

  function formatTime(sec: number): string {
    const m = Math.floor(sec / 60)
    const s = sec % 60
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }

  const statusColors: Record<CallState, string> = {
    idle: 'bg-gray-600',
    connecting: 'bg-yellow-500 animate-pulse',
    connected: 'bg-green-500',
    ended: 'bg-gray-500',
  }

  const isActive = callState === 'connected' || callState === 'connecting'

  return (
    <div className="flex gap-4 h-full">
      {/* Left: Dialer pad */}
      <div className="flex flex-col gap-1 shrink-0">
        <div className="grid grid-cols-3 gap-1">
          {DIALER_KEYS.map(({ digit, letters }) => (
            <button
              key={digit}
              onClick={() => handleDialerPress(digit)}
              disabled={isActive}
              className="w-16 h-14 rounded-lg bg-gray-800/60 border border-gray-700/50 hover:bg-gray-700/60 active:bg-gray-600/60 disabled:opacity-40 disabled:cursor-not-allowed transition-colors flex flex-col items-center justify-center"
            >
              <span className="text-lg font-semibold text-gray-100">{digit}</span>
              {letters && <span className="text-[9px] tracking-widest text-blue-400/70">{letters}</span>}
            </button>
          ))}
        </div>
        {/* Backspace */}
        <button
          onClick={handleBackspace}
          disabled={isActive || phoneNumber.length === 0}
          className="w-full h-8 rounded bg-gray-800/40 text-gray-500 hover:text-gray-300 text-xs disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          ← Clear
        </button>
      </div>

      {/* Right: Phone display + settings */}
      <div className="flex-1 flex flex-col gap-3 min-w-0">
        {/* Status bar */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {callState === 'connected' && (
              <span className="text-xs font-mono text-gray-300">{formatTime(elapsed)}</span>
            )}
            <span className={`inline-block w-2 h-2 rounded-full ${statusColors[callState]}`} />
            <span className="text-xs text-gray-400 capitalize">{callState}</span>
          </div>
        </div>

        {/* Phone display (read-only, fed by dialer) */}
        <div className="bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm font-mono text-gray-100 min-h-[36px] flex items-center">
          {phoneNumber || <span className="text-gray-600">Dial a number or leave blank for default</span>}
        </div>

        {/* Voice + Model row */}
        <div className="flex gap-2">
          <div className="flex-1">
            <label className="text-xs text-gray-500 mb-0.5 block">Voice</label>
            <select
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              disabled={isActive}
            >
              <option value="sage">sage</option>
              <option value="alloy">alloy</option>
              <option value="echo">echo</option>
              <option value="nova">nova</option>
              <option value="shimmer">shimmer</option>
              <option value="onyx">onyx</option>
              <option value="fable">fable</option>
            </select>
          </div>
          <div className="flex-1">
            <label className="text-xs text-gray-500 mb-0.5 block">Model</label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 text-gray-100 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-blue-500"
              disabled={isActive}
            >
              <option value="gpt-realtime">gpt-realtime</option>
              <option value="gpt-4o-realtime-preview">gpt-4o-realtime-preview</option>
            </select>
          </div>
        </div>

        {/* Simulate toggle */}
        <label className="flex items-center gap-2 cursor-pointer">
          <div
            onClick={() => !isActive && setSimulate(!simulate)}
            className={`relative w-9 h-5 rounded-full transition-colors ${
              simulate ? 'bg-blue-600' : 'bg-gray-600'
            } ${isActive ? 'opacity-50' : 'cursor-pointer'}`}
          >
            <div
              className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                simulate ? 'translate-x-4' : ''
              }`}
            />
          </div>
          <span className="text-sm text-gray-300">Simulate (no PSTN)</span>
        </label>

        {/* Action buttons */}
        <div className="flex gap-2 mt-auto">
          <button
            onClick={handleStart}
            disabled={isActive}
            className="flex-1 px-4 py-2.5 bg-green-600 text-white font-medium rounded hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {callState === 'connecting' ? 'Connecting...' : 'Start Call'}
          </button>
          <button
            onClick={handleHangup}
            disabled={callState !== 'connected'}
            className="px-4 py-2.5 bg-red-600/80 text-white font-medium rounded hover:bg-red-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            Hang Up
          </button>
        </div>

        {/* Error display */}
        {error && (
          <div className="text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">
            {error}
          </div>
        )}
      </div>
    </div>
  )
}
