interface MetricsBarProps {
  framesIn: number
  framesOut: number
  elapsed: number
}

export function MetricsBar({ framesIn, framesOut, elapsed }: MetricsBarProps) {
  const mins = Math.floor(elapsed / 60)
  const secs = elapsed % 60
  const time = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`

  return (
    <div className="flex items-center gap-4 px-3 py-1.5 bg-gray-900 rounded text-xs font-mono text-gray-400 border border-gray-800">
      <span>Frames In: <span className="text-gray-200">{framesIn.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span>Frames Out: <span className="text-gray-200">{framesOut.toLocaleString()}</span></span>
      <span className="text-gray-700">|</span>
      <span>Session: <span className="text-gray-200">{time}</span></span>
    </div>
  )
}
