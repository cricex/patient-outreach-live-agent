import { useRef, useEffect } from 'react'

interface WaveformDisplayProps {
  callerLevel: number  // 0-1 RMS level
  agentLevel: number   // 0-1 RMS level
  active: boolean
}

export function WaveformDisplay({ callerLevel, agentLevel, active }: WaveformDisplayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const callerHistory = useRef<number[]>([])
  const agentHistory = useRef<number[]>([])
  const animRef = useRef<number>(0)

  useEffect(() => {
    if (!active) return

    callerHistory.current.push(callerLevel)
    agentHistory.current.push(agentLevel)

    // Keep last 200 samples
    const maxLen = 200
    if (callerHistory.current.length > maxLen) callerHistory.current.shift()
    if (agentHistory.current.length > maxLen) agentHistory.current.shift()
  }, [callerLevel, agentLevel, active])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    function draw() {
      if (!canvas || !ctx) return
      // Use CSS pixel dimensions (ctx is scaled by devicePixelRatio)
      const w = canvas.clientWidth
      const h = canvas.clientHeight
      const halfH = h / 2

      ctx.fillStyle = '#030712' // gray-950
      ctx.fillRect(0, 0, w, h)

      // Divider line
      ctx.strokeStyle = '#1f2937' // gray-800
      ctx.lineWidth = 1
      ctx.beginPath()
      ctx.moveTo(0, halfH)
      ctx.lineTo(w, halfH)
      ctx.stroke()

      const barWidth = 2
      const gap = 1
      const step = barWidth + gap
      const maxBars = Math.floor(w / step)

      // Caller waveform (top half, centered vertically)
      const callerData = callerHistory.current.slice(-maxBars)
      const callerCenterY = halfH / 2
      ctx.fillStyle = '#60a5fa' // blue-400
      for (let i = 0; i < callerData.length; i++) {
        const x = w - (callerData.length - i) * step
        const jitter = 0.9 + Math.random() * 0.2
        const barH = Math.max(1, callerData[i] * (halfH - 10) * jitter)
        const y = callerCenterY - barH / 2
        ctx.fillRect(x, y, barWidth, barH)
      }

      // Agent waveform (bottom half, centered vertically)
      const agentData = agentHistory.current.slice(-maxBars)
      const agentCenterY = halfH + halfH / 2
      ctx.fillStyle = '#4ade80' // green-400
      for (let i = 0; i < agentData.length; i++) {
        const x = w - (agentData.length - i) * step
        const jitter = 0.9 + Math.random() * 0.2
        const barH = Math.max(1, agentData[i] * (halfH - 10) * jitter)
        const y = agentCenterY - barH / 2
        ctx.fillRect(x, y, barWidth, barH)
      }

      // Labels
      ctx.fillStyle = '#6b7280' // gray-500
      ctx.font = '10px monospace'
      ctx.fillText('Caller', 8, 14)
      ctx.fillText('Agent', 8, halfH + 14)

      animRef.current = requestAnimationFrame(draw)
    }

    draw()
    return () => cancelAnimationFrame(animRef.current)
  }, [])

  // Handle canvas resize for sharp rendering on HiDPI displays
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const resizeObserver = new ResizeObserver(() => {
      canvas.width = canvas.clientWidth * window.devicePixelRatio
      canvas.height = canvas.clientHeight * window.devicePixelRatio
      const ctx = canvas.getContext('2d')
      if (ctx) ctx.scale(window.devicePixelRatio, window.devicePixelRatio)
    })
    resizeObserver.observe(canvas)
    // Initial size
    canvas.width = canvas.clientWidth * window.devicePixelRatio
    canvas.height = canvas.clientHeight * window.devicePixelRatio
    const ctx = canvas.getContext('2d')
    if (ctx) ctx.scale(window.devicePixelRatio, window.devicePixelRatio)

    return () => resizeObserver.disconnect()
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full rounded border border-gray-800 bg-gray-950"
      style={{ imageRendering: 'pixelated' }}
    />
  )
}
