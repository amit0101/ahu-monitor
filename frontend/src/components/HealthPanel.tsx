// components/HealthPanel.tsx — Component health bars with animated fill
//
// RUL chip lives INSIDE the health row at a fixed position — never pushes rows apart.
// Rows have a fixed height so vertical positions stay stable regardless of chip visibility.

import { useTwinStore } from '../stores/useTwinStore'
import type { OperatingState } from '../types'

const ENTITY_ORDER = [
  { id: 'ahu-01',             label: 'AHU Overall',  indent: 0 },
  { id: 'ahu-01.supplyFan',   label: 'Supply Fan',   indent: 1 },
  { id: 'ahu-01.returnFan',   label: 'Return Fan',   indent: 1 },
  { id: 'ahu-01.filterBank',  label: 'Filter Bank',  indent: 1 },
  { id: 'ahu-01.coolingCoil', label: 'Cooling Coil', indent: 1 },
  { id: 'ahu-01.heatingCoil', label: 'Heating Coil', indent: 1 },
  { id: 'ahu-01.damper',      label: 'Damper',       indent: 1 },
]

function stateColor(state: OperatingState | undefined, health: number): string {
  if (state === 'critical' || health < 0.4) return 'var(--color-red)'
  if (state === 'warning'  || health < 0.7) return 'var(--color-amber)'
  return 'var(--color-green)'
}

export default function HealthPanel() {
  const { snapshot, selectedEntityId, setSelectedEntityId } = useTwinStore()

  return (
    <div style={{
      padding: '12px 14px',
      height: '100%',
      overflowY: 'auto',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div className="panel-title" style={{ marginBottom: 8 }}>Component Health</div>

      {ENTITY_ORDER.map(({ id, label, indent }) => {
        const h      = snapshot?.health[id]
        const health = h?.health ?? 1.0
        const state  = h?.state
        const rul    = h?.rul_days
        const color  = stateColor(state, health)
        const isRoot = indent === 0
        const isSelected = selectedEntityId === id

        return (
          <div
            key={id}
            onClick={() => setSelectedEntityId(isSelected ? null : id)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              // Fixed height per row — RUL chip is inline, never shifts neighbours
              height: isRoot ? 32 : 28,
              padding: '0 6px',
              borderRadius: 6,
              cursor: 'pointer',
              background: isSelected ? 'var(--color-blue-dim)' : 'transparent',
              borderLeft: isSelected ? '2px solid var(--color-blue)' : '2px solid transparent',
              transition: 'background 0.15s, border-color 0.15s',
              marginLeft: indent * 10,
            }}
          >
            {/* Entity name — fixed width */}
            <div style={{
              width: 80,
              fontSize: isRoot ? 12 : 11,
              fontWeight: isRoot ? 600 : 400,
              color: isSelected ? 'var(--color-blue)' : isRoot ? 'var(--color-text)' : 'var(--color-text-dim)',
              flexShrink: 0,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {indent > 0 && <span style={{ color: 'var(--color-text-mute)', marginRight: 3 }}>↳</span>}
              {label}
            </div>

            {/* Health bar — takes remaining space */}
            <div style={{
              flex: 1,
              height: isRoot ? 6 : 4,
              background: 'var(--color-surface2)',
              borderRadius: 3,
              overflow: 'hidden',
              minWidth: 0,
            }}>
              <div style={{
                height: '100%',
                width: `${health * 100}%`,
                background: color,
                borderRadius: 3,
                transition: 'width 0.6s ease, background 0.4s ease',
                boxShadow: health < 0.7 ? `0 0 6px ${color}50` : 'none',
              }} />
            </div>

            {/* Percentage — fixed width */}
            <div style={{
              width: 32,
              textAlign: 'right',
              fontSize: isRoot ? 12 : 11,
              fontWeight: 600,
              color,
              flexShrink: 0,
            }}>
              {Math.round(health * 100)}%
            </div>

            {/* RUL chip — fixed width slot, empty string when no RUL to show.
                Stays in the layout always so other elements don't shift. */}
            <div style={{ width: 52, flexShrink: 0, textAlign: 'right' }}>
              {rul !== null && rul !== undefined && rul < 30 && (
                <span style={{
                  display: 'inline-block',
                  fontSize: 9,
                  fontWeight: 700,
                  color: rul < 15 ? 'var(--color-red)' : 'var(--color-amber)',
                  background: rul < 15 ? 'var(--color-red-dim)' : 'var(--color-amber-dim)',
                  borderRadius: 3,
                  padding: '1px 5px',
                  whiteSpace: 'nowrap',
                }}>
                  ⏱{Math.round(rul)}d
                </span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
