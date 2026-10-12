// utils/activeAlerts.ts — one alert per component: a newer alert supersedes older ones.
import type { Alert } from '../types'

export function getActiveAlerts(alerts: Alert[]): Alert[] {
  const latest = new Map<string, Alert>()
  for (const a of alerts) {
    if (a.acknowledged) continue
    const prev = latest.get(a.entity_id)
    if (!prev || a.sim_day > prev.sim_day || (a.sim_day === prev.sim_day && a.timestamp >= prev.timestamp)) {
      latest.set(a.entity_id, a)
    }
  }
  // Critical first, then newest first
  return [...latest.values()].sort(
    (x, y) => (Number(y.severity === 'critical') - Number(x.severity === 'critical')) || (y.sim_day - x.sim_day),
  )
}
