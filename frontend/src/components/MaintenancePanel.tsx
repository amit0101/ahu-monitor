// components/MaintenancePanel.tsx — RUL gauge + maintenance recommendations
//
// "Collecting baseline data…" only shows once (before any RUL value ever appears).
// Once the gauge shows a value, it stays stable — never reverts to the placeholder.
// Uses a ref to latch the first non-null value.

import { useRef } from 'react'
import { useTwinStore } from '../stores/useTwinStore'
import type { MaintenanceRecommendation } from '../types'

const PRIORITY_COLORS: Record<string, string> = {
  critical: 'var(--color-red)',
  high:     'var(--color-amber)',
  medium:   '#a0c4e0',
  low:      'var(--color-text-dim)',
}

// SVG arc gauge for failure probability / RUL
function RiskGauge({ value, label, subLabel }: { value: number; label: string; subLabel: string }) {
  const r = 24
  const circ = 2 * Math.PI * r
  const offset = circ * (1 - Math.max(0, Math.min(1, value)))
  const color = value > 0.7 ? 'var(--color-red)' : value > 0.4 ? 'var(--color-amber)' : 'var(--color-green)'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <svg width={56} height={56} viewBox="0 0 56 56" style={{ flexShrink: 0 }}>
        {/* Track */}
        <circle cx={28} cy={28} r={r} fill="none" stroke="var(--color-surface2)" strokeWidth={5} />
        {/* Value arc */}
        <circle
          cx={28} cy={28} r={r}
          fill="none" stroke={color} strokeWidth={5}
          strokeDasharray={circ}
          strokeDashoffset={offset}
          strokeLinecap="round"
          transform="rotate(-90 28 28)"
          style={{ transition: 'stroke-dashoffset 0.8s ease, stroke 0.4s ease' }}
        />
        {/* Center % label */}
        <text x={28} y={32} textAnchor="middle" fill={color} fontSize={11} fontWeight={700}>
          {Math.round(value * 100)}%
        </text>
      </svg>
      <div>
        <div style={{ fontSize: 9, color: 'var(--color-text-mute)', marginBottom: 2 }}>Worst component</div>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--color-text-dim)', marginBottom: 2 }}>{subLabel}</div>
        <div style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{label}</div>
        <div style={{ fontSize: 9, color: 'var(--color-text-mute)', marginTop: 2 }}>est. remaining life</div>
      </div>
    </div>
  )
}

function RecCard({ rec }: { rec: MaintenanceRecommendation }) {
  const prioColor = PRIORITY_COLORS[rec.priority] ?? 'var(--color-text-dim)'
  return (
    <div style={{
      background: 'var(--color-surface2)',
      border: `1px solid ${prioColor}30`,
      borderLeft: `3px solid ${prioColor}`,
      borderRadius: 6,
      padding: '6px 9px',
      marginBottom: 5,
    }}>
      <div style={{ fontSize: 11, fontWeight: 600, color: prioColor, marginBottom: 2 }}>
        {rec.action}
      </div>
      <div style={{ fontSize: 10, color: 'var(--color-text-dim)', lineHeight: 1.4 }}>
        {rec.rationale}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center' }}>
        <span style={{
          fontSize: 9, fontWeight: 700,
          background: `${prioColor}20`,
          color: prioColor,
          borderRadius: 3, padding: '1px 6px',
          textTransform: 'uppercase',
        }}>
          {rec.priority}
        </span>
        {rec.rul_days !== null && rec.rul_days !== undefined && (
          <span style={{ fontSize: 9, color: 'var(--color-text-mute)' }}>
            ~{Math.round(rec.rul_days)}d window · {rec.estimated_downtime_hours}h downtime
          </span>
        )}
      </div>
    </div>
  )
}

export default function MaintenancePanel() {
  const { recommendations, snapshot } = useTwinStore()

  // Find worst entity by lowest RUL
  const worstEntry = Object.entries(snapshot?.health ?? {})
    .filter(([, h]) => h.rul_days !== null && h.rul_days !== undefined)
    .sort(([, a], [, b]) => (a.rul_days ?? 999) - (b.rul_days ?? 999))[0]

  const rulDays     = worstEntry?.[1].rul_days ?? null
  // Failure probability = 1 - health (health 1.0 = perfectly healthy, 0 = failed)
  const failureProb = worstEntry ? (1 - worstEntry[1].health) : 0
  const worstLabel  = worstEntry
    ? worstEntry[0].split('.').slice(1).join(' › ') || 'AHU'
    : ''

  // Latch: once we've seen a non-null RUL, keep showing the gauge.
  // This prevents the "Collecting…" text from reappearing if health briefly
  // oscillates back above the warning threshold between ticks.
  const latchedRef = useRef<{ rul: number; label: string; prob: number } | null>(null)
  if (rulDays !== null) {
    latchedRef.current = { rul: rulDays, label: worstLabel, prob: failureProb }
  }
  const display = latchedRef.current

  return (
    <div style={{ padding: '12px 12px', height: '100%', overflowY: 'auto' }}>
      <div className="panel-title">Predicted Failure Risk</div>

      {/* RUL gauge — stable once first value appears */}
      <div style={{ marginBottom: 10 }}>
        {display ? (
          <RiskGauge
            value={display.prob}
            label={`~${Math.round(display.rul)}d`}
            subLabel={display.label}
          />
        ) : (
          // Only shows before any component has ever degraded
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '6px 0',
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: '50%',
              border: '5px solid var(--color-surface2)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0,
            }}>
              <div style={{ fontSize: 9, color: 'var(--color-text-mute)', textAlign: 'center', lineHeight: 1.3 }}>
                —
              </div>
            </div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--color-text-dim)', fontWeight: 500 }}>Baseline phase</div>
              <div style={{ fontSize: 10, color: 'var(--color-text-mute)', marginTop: 2, lineHeight: 1.4 }}>
                RUL computed after<br/>degradation detected
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: 'var(--color-border)', margin: '8px 0' }} />

      {/* Maintenance recommendations */}
      <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--color-text-mute)', marginBottom: 6 }}>
        Recommended Actions
      </div>
      {recommendations.length === 0 ? (
        <div style={{ fontSize: 11, color: 'var(--color-text-mute)' }}>
          No actions required
        </div>
      ) : (
        recommendations.slice(0, 3).map((rec, i) => (
          <RecCard key={`${rec.entity_id}-${i}`} rec={rec} />
        ))
      )}
    </div>
  )
}
