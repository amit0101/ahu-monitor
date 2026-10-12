// stores/useTwinStore.ts — Zustand global state for the digital twin
//
// Single source of truth for:
//   - Live sensor snapshot (from WebSocket)
//   - Twin graph structure (from REST on load)
//   - Alerts + maintenance recommendations
//   - Simulation status
//   - UI state (selected entity)

import { create } from 'zustand'
import type {
  TwinGraph,
  LiveSnapshot,
  Alert,
  MaintenanceRecommendation,
  SimulationStatus,
  HealthSummaryItem,
  LiveSensorValue,
  HistoryPoint,
} from '../types'

interface TwinStore {
  // ── Twin structure (loaded once on mount) ──────────────────────────────────
  twinGraph: TwinGraph | null
  setTwinGraph: (graph: TwinGraph) => void

  // ── Live data (updated every WebSocket tick) ───────────────────────────────
  snapshot: LiveSnapshot | null
  setSnapshot: (snap: LiveSnapshot) => void

  // ── Derived accessors ──────────────────────────────────────────────────────
  getSensorValue: (sensorId: string) => LiveSensorValue | null
  getEntityHealth: (entityId: string) => HealthSummaryItem | null

  // ── Alerts ─────────────────────────────────────────────────────────────────
  alerts: Alert[]
  setAlerts: (alerts: Alert[]) => void
  addAlert: (alert: Alert) => void

  // ── Maintenance recommendations ────────────────────────────────────────────
  recommendations: MaintenanceRecommendation[]
  setRecommendations: (recs: MaintenanceRecommendation[]) => void

  // ── Simulation status ──────────────────────────────────────────────────────
  simStatus: SimulationStatus | null
  setSimStatus: (status: SimulationStatus) => void

  // ── UI state ───────────────────────────────────────────────────────────────
  selectedEntityId: string | null
  setSelectedEntityId: (id: string | null) => void

  // ── WebSocket connection state ─────────────────────────────────────────────
  wsConnected: boolean
  setWsConnected: (connected: boolean) => void

  // ── Sensor history (from REST polling, fed to charts) ──────────────────────
  histories: Record<string, HistoryPoint[]>
  setHistories: (h: Record<string, HistoryPoint[]>) => void
}

export const useTwinStore = create<TwinStore>((set, get) => ({
  // ── Twin structure ─────────────────────────────────────────────────────────
  twinGraph: null,
  setTwinGraph: (graph) => set({ twinGraph: graph }),

  // ── Live snapshot ──────────────────────────────────────────────────────────
  snapshot: null,
  setSnapshot: (snap) => set({ snapshot: snap }),

  // ── Derived ────────────────────────────────────────────────────────────────
  getSensorValue: (sensorId) => get().snapshot?.sensors[sensorId] ?? null,
  getEntityHealth: (entityId) => get().snapshot?.health[entityId] ?? null,

  // ── Alerts ─────────────────────────────────────────────────────────────────
  alerts: [],
  setAlerts: (alerts) => set({ alerts }),
  addAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts].slice(0, 100), // cap at 100
    })),

  // ── Maintenance ────────────────────────────────────────────────────────────
  recommendations: [],
  setRecommendations: (recs) => set({ recommendations: recs }),

  // ── Simulation ─────────────────────────────────────────────────────────────
  simStatus: null,
  setSimStatus: (status) => set({ simStatus: status }),

  // ── UI ─────────────────────────────────────────────────────────────────────
  selectedEntityId: null,
  setSelectedEntityId: (id) => set({ selectedEntityId: id }),

  // ── WebSocket ──────────────────────────────────────────────────────────────
  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),

  // ── Histories ──────────────────────────────────────────────────────────────
  histories: {},
  setHistories: (h) => set({ histories: h }),
}))
