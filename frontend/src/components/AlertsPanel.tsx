// components/AlertsPanel.tsx — Active alerts with severity styling

import { useTwinStore } from '../stores/useTwinStore'
import type { Alert } from '../types'
import { getActiveAlerts } from '../utils/activeAlerts'

const FAULT_LABELS: Record<string, string> = {
  bearing_wear:    'Bearing Wear',
  belt_slippage:   'Belt Slippage',
  coil_fouling:    'Coil Fouling',
  filter_clogging: 'Filter Clogging',
  damper_failure:  'Damper Failure',
  none:            '',
}

function AlertItem({ alert }: { alert: Alert }) {
  const isCrit = alert.severity === 'critical'
  const color = isCrit ? 'var(--color-red)' : 'var(--color-amber)'
  const tint  = isCrit ? 'var(--color-red-dim)' : 'var(--color-amber-dim)'

  return (
    <div style={{
      padding: '7px 9px',
      borderRadius: 6,
      background: tint,
      border: `1px solid ${color}33`,
      borderLeft: `4px solid ${color}`,
      marginBottom: 6,
      animation: 'fadeIn 0.3s ease',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 3 }}>
        <span style={{
          flexShrink: 0, fontSize: 8, fontWeight: 800, letterSpacing: '0.07em',
          padding: '2px 6px', borderRadius: 3, textTransform: 'uppercase',
          background: isCrit ? color : 'transparent',
          color: isCrit ? '#fff' : color,
          border: `1px solid ${color}`,
        }}>
          {isCrit ? 'Critical' : 'Warning'}
        </span>
        <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {alert.title}
        </span>
      </div>
      <div style={{ fontSize: 10, color: 'var(--color-text-dim)', lineHeight: 1.4 }}>
        {alert.description}
      </div>
      <div style={{ fontSize: 9, color: 'var(--color-text-mute)', marginTop: 3 }}>
        Day {alert.sim_day.toFixed(0)}{alert.fault_mode && alert.fault_mode !== 'none' ? ` · ${FAULT_LABELS[alert.fault_mode] || alert.fault_mode}` : ''}
      </div>
    </div>
  )
}

export default function AlertsPanel() {
  const { alerts } = useTwinStore()
  // One alert per component (latest wins), critical first
  const active = getActiveAlerts(alerts)

  return (
    <div style={{ padding: '12px 12px', height: '100%', overflowY: 'auto' }}>
      <div className="panel-title">Active Alerts</div>

      {active.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--color-text-mute)', textAlign: 'center', paddingTop: 20 }}>
          ✓ No active alerts
        </div>
      ) : (
        active.map((alert) => <AlertItem key={alert.id} alert={alert} />)
      )}
    </div>
  )
}
