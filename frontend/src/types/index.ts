// types/index.ts — Shared TypeScript interfaces mirroring the backend Pydantic models

export type OperatingState = 'normal' | 'warning' | 'critical' | 'fault' | 'maintenance' | 'offline'
export type FaultMode =
  | 'none'
  | 'bearing_wear'
  | 'belt_slippage'
  | 'coil_fouling'
  | 'filter_clogging'
  | 'damper_failure'
export type SensorKind =
  | 'vibration'
  | 'acoustic'
  | 'temperature'
  | 'current'
  | 'power'
  | 'pressure_diff'
  | 'airflow'
  | 'speed'

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthScore {
  value: number
  state: OperatingState
  dominant_fault: FaultMode
  fault_confidence: number
  rul_days: number | null
  failure_probability: number
  signal_breakdown: Record<string, number>
}

// ── Sensor point ──────────────────────────────────────────────────────────────

export interface SensorPointSummary {
  id: string
  dis: string
  kind: SensorKind
  tags: string[]
  signal_health: number
  current_value: number | null
  unit: string
  baseline_mean: number
  baseline_std: number
  is_anomalous: boolean
  anomaly_score: number
  timestamp: number | null
  sim_day: number | null
}

// ── Twin entity ───────────────────────────────────────────────────────────────

export interface TwinEntity {
  id: string
  dis: string
  tags: string[]
  parent_id: string | null
  health: HealthScore
  points: Record<string, SensorPointSummary>
  manufacturer: string
  install_date: string
}

export interface TwinGraph {
  root_id: string
  entities: Record<string, TwinEntity>
  edges: Record<string, string[]>
}

// ── Live WebSocket snapshot ───────────────────────────────────────────────────

export interface LiveSensorValue {
  v: number       // current value
  anom: boolean   // is anomalous
  score: number   // anomaly score 0→1
  health: number  // signal health 0→1
  day: number     // sim day
}

export interface HealthSummaryItem {
  health: number
  state: OperatingState
  fault: FaultMode
  rul_days: number | null
}

export interface LiveSnapshot {
  sim_day: number
  tick: number
  speed_multiplier: number
  sensors: Record<string, LiveSensorValue>
  health: Record<string, HealthSummaryItem>
}

// ── Alerts ────────────────────────────────────────────────────────────────────

export interface Alert {
  id: string
  entity_id: string
  entity_dis: string
  severity: OperatingState
  fault_mode: FaultMode
  title: string
  description: string
  sim_day: number
  timestamp: number
  acknowledged: boolean
}

// ── Maintenance ───────────────────────────────────────────────────────────────

export interface MaintenanceRecommendation {
  entity_id: string
  entity_dis: string
  fault_mode: FaultMode
  action: string
  rationale: string
  priority: 'critical' | 'high' | 'medium' | 'low'
  estimated_downtime_hours: number
  rul_days: number | null
  sim_day: number
}

// ── Simulation status ─────────────────────────────────────────────────────────

export interface SimulationStatus {
  running: boolean
  sim_day: number
  total_days: number
  progress_pct: number
  speed_multiplier: number
  tick_count: number
  fast_forwarding?: boolean   // backend is silently seeking to target_day
  target_day?: number
}

// ── Chart data ────────────────────────────────────────────────────────────────

export interface HistoryPoint {
  t: number    // sim day
  v: number    // value
  anom: boolean
}
