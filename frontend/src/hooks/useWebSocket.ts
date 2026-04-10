import { useEffect, useRef, useState, useCallback } from 'react'

export function useWebSocket(url: string, enabled: boolean = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const [lastMessage, setLastMessage] = useState<any>(null)

  const connect = useCallback(() => {
    if (!enabled) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}${url}`

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      // Auto-reconnect after 3s
      setTimeout(connect, 3000)
    }
    ws.onmessage = (event) => {
      try {
        setLastMessage(JSON.parse(event.data))
      } catch {
        setLastMessage(event.data)
      }
    }
  }, [url, enabled])

  useEffect(() => {
    connect()
    return () => {
      wsRef.current?.close()
    }
  }, [connect])

  return { connected, lastMessage, ws: wsRef.current }
}
