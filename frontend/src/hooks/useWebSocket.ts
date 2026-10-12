// hooks/useWebSocket.ts — Resilient WebSocket hook with auto-reconnect
//
// Connects to /ws/live and updates the Zustand store on every tick.
// Implements exponential backoff reconnection so the dashboard
// recovers automatically if the backend restarts.

import { useEffect, useRef, useCallback } from 'react'
import { useTwinStore } from '../stores/useTwinStore'
import { getWsUrl } from '../config'
import type { LiveSnapshot } from '../types'

const INITIAL_RETRY_MS = 1000
const MAX_RETRY_MS = 30000

// Module-level handle so Header can flush the WS buffer on speed change
// without needing prop-drilling or Zustand wiring.
let triggerFlush: (() => void) | null = null
export function flushWs() { triggerFlush?.() }

export function useWebSocket() {
  const { setSnapshot, setWsConnected } = useTwinStore()
  const wsRef = useRef<WebSocket | null>(null)
  const retryMs = useRef(INITIAL_RETRY_MS)
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmounted = useRef(false)
  const lastSnapshotAt = useRef(0)   // throttle: ms timestamp of last accepted snapshot

  const connect = useCallback(() => {
    if (unmounted.current) return

    const ws = new WebSocket(getWsUrl())
    wsRef.current = ws

    // Allow external flush-reconnect (e.g. after speed change)
    triggerFlush = () => ws.close(4000, 'flush')

    ws.onopen = () => {
      retryMs.current = INITIAL_RETRY_MS
      setWsConnected(true)
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        // Ignore keepalive pings
        if (data.cmd) return
        // Speed-adaptive throttle: use backend-reported speed to set the
        // minimum gap between snapshots. This immediately kills the buffered-
        // message burst after a speed decrease (e.g. 50× → 1×) — the first
        // message with speed=1 forces a 900 ms gap, draining in one step.
        // At higher speeds, the cap is 8 Hz (125 ms).
        const speed: number = data.speed_multiplier ?? 50
        const minGap = speed <= 2 ? 900 : 125   // 1× → ~1/s, higher → 8 Hz cap
        const now = Date.now()
        if (now - lastSnapshotAt.current < minGap) return
        lastSnapshotAt.current = now
        setSnapshot(data as LiveSnapshot)
      } catch {
        // Malformed message — ignore
      }
    }

    ws.onerror = () => {
      ws.close()
    }

    ws.onclose = (ev) => {
      triggerFlush = null
      setWsConnected(false)
      if (unmounted.current) return
      // Intentional flush (code 4000) → reconnect immediately, no backoff
      const delay = ev.code === 4000 ? 0 : retryMs.current
      if (ev.code !== 4000) retryMs.current = Math.min(retryMs.current * 2, MAX_RETRY_MS)
      retryTimer.current = setTimeout(() => connect(), delay)
    }
  }, [setSnapshot, setWsConnected])

  useEffect(() => {
    unmounted.current = false
    connect()

    // Keepalive ping every 25s
    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ cmd: 'ping' }))
      }
    }, 25000)

    return () => {
      unmounted.current = true
      clearInterval(pingInterval)
      if (retryTimer.current) clearTimeout(retryTimer.current)
      wsRef.current?.close()
    }
  }, [connect])
}

