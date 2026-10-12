// hooks/useTwinApi.ts — REST API hooks for twin data
//
// Fetches twin graph structure, alerts, maintenance recommendations,
// and simulation status. These are loaded on mount or polled at low frequency
// (the high-frequency live data comes via WebSocket).

import { useEffect, useCallback, useRef } from 'react'
import { useTwinStore } from '../stores/useTwinStore'
import { getApiUrl } from '../config'
import type { TwinGraph, Alert, MaintenanceRecommendation, SimulationStatus, HistoryPoint } from '../types'

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(getApiUrl(path))
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

// ── Load twin graph once on mount ─────────────────────────────────────────────

export function useTwinGraph() {
  const { setTwinGraph } = useTwinStore()

  useEffect(() => {
    apiFetch<TwinGraph>('/twin')
      .then(setTwinGraph)
      .catch(console.error)
  }, [setTwinGraph])
}

// ── Poll alerts every 5 seconds ───────────────────────────────────────────────

export function useAlerts(pollMs = 5000) {
  const { setAlerts } = useTwinStore()

  useEffect(() => {
    const load = () =>
      apiFetch<Alert[]>('/alerts').then(setAlerts).catch(console.error)
    load()
    const interval = setInterval(load, pollMs)
    return () => clearInterval(interval)
  }, [setAlerts, pollMs])
}

// ── Poll maintenance recommendations every 10 seconds ────────────────────────

export function useRecommendations(pollMs = 10000) {
  const { setRecommendations } = useTwinStore()

  useEffect(() => {
    const load = () =>
      apiFetch<MaintenanceRecommendation[]>('/maintenance')
        .then(setRecommendations)
        .catch(console.error)
    load()
    const interval = setInterval(load, pollMs)
    return () => clearInterval(interval)
  }, [setRecommendations, pollMs])
}

// ── Control/poll race guard ───────────────────────────────────────────────────
// Status polls that were issued before a control action (or are still in flight
// while one runs) carry stale data and would overwrite the optimistic UI, making
// sliders/buttons snap back. Drop any poll result that overlaps a control action.
let pendingControls = 0
let lastControlDoneAt = 0

async function trackControl<T>(fn: () => Promise<T>): Promise<T> {
  pendingControls++
  try { return await fn() } finally {
    pendingControls--
    lastControlDoneAt = Date.now()
  }
}

// ── Poll simulation status every 2 seconds ────────────────────────────────────

export function useSimStatus(pollMs = 2000) {
  const { setSimStatus } = useTwinStore()

  useEffect(() => {
    const load = () => {
      const issuedAt = Date.now()
      apiFetch<SimulationStatus>('/simulation/status')
        .then((st) => {
          if (pendingControls > 0 || issuedAt < lastControlDoneAt) return  // stale vs. a control action
          setSimStatus(st)
        })
        .catch(console.error)
    }
    load()
    const interval = setInterval(load, pollMs)
    return () => clearInterval(interval)
  }, [setSimStatus, pollMs])
}

// ── Simulation control actions ────────────────────────────────────────────────

// ── Optimistic sim-status patch ───────────────────────────────────────────────
// Immediately mutates the Zustand simStatus so the UI reflects the new phase
// in the same JS tick as the click. The backend fetch + refreshStatus() below
// act as reconciliation, not the source of the visual response.
function patchSimStatus(patch: Partial<SimulationStatus>) {
  const cur = useTwinStore.getState().simStatus
  if (cur) useTwinStore.getState().setSimStatus({ ...cur, ...patch })
}

export function useSimControls() {
  const { setSimStatus } = useTwinStore()

  const refreshStatus = useCallback(() => {
    apiFetch<SimulationStatus>('/simulation/status').then(setSimStatus).catch(console.error)
  }, [setSimStatus])

  /** Start fresh, fast-forwarding to startDay — optimistically flip to running immediately */
  const start = useCallback(async (startDay = 0) => {
    const total = useTwinStore.getState().simStatus?.total_days ?? 90
    patchSimStatus({ running: true, sim_day: startDay, progress_pct: (startDay / total) * 100 })
    await trackControl(() => fetch(getApiUrl('/simulation/start'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start_day: startDay }),
    }))
    refreshStatus()
  }, [refreshStatus])

  /** Pause at current day — optimistically flip to paused immediately */
  const pause = useCallback(async () => {
    patchSimStatus({ running: false })
    await trackControl(() => fetch(getApiUrl('/simulation/pause'), { method: 'POST' }))
    refreshStatus()
  }, [refreshStatus])

  /** Resume from current day — optimistically flip to running immediately */
  const resume = useCallback(async () => {
    patchSimStatus({ running: true })
    await trackControl(() => fetch(getApiUrl('/simulation/resume'), { method: 'POST' }))
    refreshStatus()
  }, [refreshStatus])

  /** Full reset back to day 0 — optimistically flip to idle immediately */
  const restart = useCallback(async () => {
    patchSimStatus({ running: false, sim_day: 0, progress_pct: 0 })
    await trackControl(() => fetch(getApiUrl('/simulation/stop'), { method: 'POST' }))
    refreshStatus()
  }, [refreshStatus])

  const setSpeed = useCallback(async (multiplier: number, signal?: AbortSignal) => {
    patchSimStatus({ speed_multiplier: multiplier })
    try {
      await fetch(getApiUrl('/simulation/speed'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ multiplier }),
        signal,
      })
    } catch {
      // AbortError or network error — next poll will reconcile if needed
    }
  }, [])

  const injectFault = useCallback(
    async (fault_mode: string, target_entity_id: string) => {
      await fetch(getApiUrl('/simulation/inject-fault'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fault_mode, target_entity_id }),
      })
    },
    []
  )

  return { start, pause, resume, restart, setSpeed, injectFault }
}

// ── History polling hook — feeds TimeSeriesCharts ─────────────────────────────
//
// Polls GET /api/twin/{entityId}/history for each entity ID in the list.
// Merges results into the Zustand histories map so charts update in real-time.
// Poll interval: every 2 seconds (charts show last 500 points).

export type HistoryMap = Record<string, HistoryPoint[]>

export function useHistoryPolling(
  entityIds: string[],
  pollMs = 2000,
) {
  const { setHistories } = useTwinStore()
  // Stable ref so the interval callback always sees latest entityIds
  const entityIdsRef = useRef(entityIds)
  entityIdsRef.current = entityIds

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      if (entityIdsRef.current.length === 0) return
      try {
        const results = await Promise.all(
          entityIdsRef.current.map((id) =>
            apiFetch<Record<string, HistoryPoint[]>>(`/history/${id}?max_points=300`)
              .catch(() => ({} as Record<string, HistoryPoint[]>))
          )
        )
        if (cancelled) return
        // Merge all entity results into a flat sensorId → points map
        const merged: HistoryMap = {}
        results.forEach((entityHistory) => {
          Object.assign(merged, entityHistory)
        })
        setHistories(merged)
      } catch {
        // Silently ignore — charts stay with stale data until backend is up
      }
    }

    load()
    const interval = setInterval(load, pollMs)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [setHistories, pollMs])
  // Note: entityIds array identity intentionally excluded — we use a ref instead
  // to avoid restarting the interval when content is the same.
}
