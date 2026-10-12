// components/SensorRow.tsx — Live sensor reading cards
//
// Shows 6 key sensor values for the currently selected entity.
// When no entity is selected, shows the default featured sensors.
// Each card animates on value change and color-codes by health.

import { useMemo } from 'react'
import { useTwinStore } from '../stores/useTwinStore'

interface SensorDef {
  id: string
  label: string
  unit: string
  decimals?: number
}

// Default sensors shown when nothing is selected
const DEFAULT_SENSORS: SensorDef[] = [
  { id: 'ahu-01.supplyFan.vibration',        label: 'SF Vibration',  unit: 'mm/s', decimals: 1 },
  { id: 'ahu-01.supplyFan.bearingTemp',       label: 'SF Brg Temp',   unit: '°C',   decimals: 1 },
  { id: 'ahu-01.supplyFan.current',           label: 'SF Current',    unit: 'A',    decimals: 1 },
  { id: 'ahu-01.filterBank.pressureDiff',     label: 'Filter ΔP',     unit: 'Pa',   decimals: 0 },
  { id: 'ahu-01.coolingCoil.dischargeTemp',   label: 'Discharge Air', unit: '°C',   decimals: 1 },
  { id: 'ahu-01.returnFan.vibration',         label: 'RF Vibration',  unit: 'mm/s', decimals: 1 },
]

// Sensor label map for well-known point IDs
const SENSOR_LABELS: Record<string, { label: string; unit: string; decimals?: number }> = {
  vibration:    { label: 'Vibration',    unit: 'mm/s', decimals: 1 },
  bearingTemp:  { label: 'Bearing Temp', unit: '°C',   decimals: 1 },
  current:      { label: 'Current',      unit: 'A',    decimals: 1 },
  acoustic:     { label: 'Acoustic SPL', unit: 'dBA',  decimals: 1 },
  speed:        { label: 'Speed',        unit: 'RPM',  decimals: 0 },
  pressureDiff: { label: 'Filter ΔP',   unit: 'Pa',   decimals: 0 },
  airflow:      { label: 'Airflow',      unit: 'm³/h', decimals: 0 },
  dischargeTemp:{ label: 'Discharge T',  unit: '°C',   decimals: 1 },
  supplyTemp:   { label: 'Supply Temp',  unit: '°C',   decimals: 1 },
  returnTemp:   { label: 'Return Temp',  unit: '°C',   decimals: 1 },
  mixedAirTemp: { label: 'Mixed Air T',  unit: '°C',   decimals: 1 },
  position:     { label: 'Position',     unit: '%',    decimals: 0 },
  effectiveness:{ label: 'Effectivenes', unit: '%',    decimals: 0 },
  deltaT:       { label: 'Coil ΔT',     unit: '°C',   decimals: 1 },
}

// ── Bell curve micro-chart ─────────────────────────────────────────────────────
// Renders a Gaussian distribution curve clipped to ±SIGMA_RANGE σ from the
// baseline mean, with a vertical indicator line for the current value.
const SIGMA_RANGE = 3.5
const W = 56
const H = 24

function BellCurve({
  mean, std, value, color,
}: { mean: number; std: number; value: number; color: string }) {
  if (!std || std <= 0) return null

  const lo = mean - SIGMA_RANGE * std
  const hi = mean + SIGMA_RANGE * std

  // Gaussian: f(x) = exp(-0.5 * ((x-mean)/std)^2)
  // Map x ∈ [lo,hi] → px ∈ [0,W], y ∈ [0,1] → px ∈ [H, 0] (flip Y)
  const toX = (x: number) => ((x - lo) / (hi - lo)) * W
  const toY = (v: number) => H - v * H   // v=1 → top, v=0 → bottom

  // Build the fill path (area under curve)
  const STEPS = 40
  const pts: string[] = []
  for (let i = 0; i <= STEPS; i++) {
    const x = lo + (i / STEPS) * (hi - lo)
    const z = (x - mean) / std
    const y = Math.exp(-0.5 * z * z)
    pts.push(`${toX(x).toFixed(1)},${toY(y).toFixed(1)}`)
  }
  const fillPath = `M ${toX(lo)},${H} L ${pts.join(' L ')} L ${toX(hi)},${H} Z`

  // Current value indicator — clamp to chart bounds so line stays visible
  const clampedValue = Math.max(lo, Math.min(hi, value))
  const lineX = toX(clampedValue).toFixed(1)
  const isOutside = value < lo || value > hi

  return (
    <svg
      width={W} height={H}
      style={{ display: 'block', overflow: 'visible' }}
      aria-hidden="true"
    >
      {/* Filled area */}
      <path d={fillPath} fill={color} fillOpacity={0.18} />
      {/* Curve outline */}
      <polyline
        points={pts.join(' ')}
        fill="none" stroke={color} strokeWidth={1.2} strokeOpacity={0.6}
      />
      {/* Current value line */}
      <line
        x1={lineX} y1={0} x2={lineX} y2={H}
        stroke={isOutside ? 'var(--color-red)' : color}
        strokeWidth={1.5}
        strokeOpacity={isOutside ? 0.9 : 0.85}
        strokeDasharray={isOutside ? '2 2' : undefined}
      />
    </svg>
  )
}

export default function SensorRow() {
  const { snapshot, twinGraph, selectedEntityId, setSelectedEntityId } = useTwinStore()

  // When an entity is selected, show that entity's sensors; else show defaults
  const sensors: SensorDef[] = useMemo(() => {
    if (!selectedEntityId || !twinGraph) return DEFAULT_SENSORS

    const entity = twinGraph.entities[selectedEntityId]
    if (!entity || !entity.points) return DEFAULT_SENSORS

    return Object.entries(entity.points).map(([pointId, point]) => {
      const key = pointId.split('.').pop() ?? pointId
      const meta = SENSOR_LABELS[key]
      return {
        id: pointId,
        label: meta?.label ?? key,
        unit: meta?.unit ?? point.unit ?? '',
        decimals: meta?.decimals ?? 1,
      }
    })
  }, [selectedEntityId, twinGraph])

  const entityName = selectedEntityId
    ? twinGraph?.entities[selectedEntityId]?.dis ?? selectedEntityId
    : null

  return (
    <div>
      {/* Entity context strip */}
      {entityName && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: '4px 14px',
          background: 'rgba(15, 122, 192, 0.07)',
          borderBottom: '1px solid rgba(15,122,192,0.15)',
          fontSize: 10,
        }}>
          <span style={{ color: 'var(--color-blue)', fontWeight: 600 }}>▶ {entityName}</span>
          <span style={{ color: 'var(--color-text-mute)' }}>— sensor detail view</span>
          <button
            className="btn"
            style={{ marginLeft: 'auto', fontSize: 9, padding: '1px 7px' }}
            onClick={() => setSelectedEntityId(null)}
          >
            ✕ clear
          </button>
        </div>
      )}

      <div style={{
        display: 'flex',
        gap: 8,
        padding: '10px 14px',
        background: 'var(--color-surface)',
        overflowX: 'auto',
      }}>
        {sensors.map((def) => {
          const live = snapshot?.sensors[def.id]
          const entityId = def.id.split('.').slice(0, 2).join('.')

          const isAnom = live?.anom ?? false
          const health = live?.health ?? 1.0
          const value = live?.v ?? null

          const entityData = twinGraph?.entities[entityId]
          const pointData = entityData?.points[def.id]
          const baselineMean = pointData?.baseline_mean ?? null
          const baselineStd  = pointData?.baseline_std  ?? null
          const deltaPct = (value !== null && baselineMean)
            ? ((value - baselineMean) / baselineMean) * 100 : null

          let borderColor = 'var(--color-border)'
          let valueColor  = 'var(--color-text)'
          let curveColor  = 'var(--color-green)'
          if (isAnom && health < 0.4) {
            borderColor = 'rgba(232,64,64,0.4)'
            valueColor  = 'var(--color-red)'
            curveColor  = 'var(--color-red)'
          } else if (isAnom || health < 0.7) {
            borderColor = 'rgba(232,137,12,0.35)'
            valueColor  = 'var(--color-amber)'
            curveColor  = 'var(--color-amber)'
          }

          return (
            <div
              key={def.id}
              style={{
                flex: '1 0 110px',
                background: 'var(--color-surface2)',
                border: `1px solid ${borderColor}`,
                borderRadius: 8,
                padding: '9px 12px 9px 12px',
                position: 'relative',
                transition: 'border-color 0s',
                minWidth: 110,
              }}
            >
              {/* Anomaly glow */}
              {isAnom && (
                <div style={{
                  position: 'absolute', inset: 0, borderRadius: 8,
                  boxShadow: health < 0.4
                    ? 'inset 0 0 0 1px rgba(232,64,64,0.2)'
                    : 'inset 0 0 0 1px rgba(232,137,12,0.15)',
                  pointerEvents: 'none',
                }} />
              )}

              <div className="label" style={{ marginBottom: 5 }}>{def.label}</div>

              {/* Value + bell curve row */}
              <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 4 }}>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 700, lineHeight: 1, color: valueColor }}>
                    {value !== null ? value.toFixed(def.decimals ?? 1) : '—'}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-dim)', marginTop: 2 }}>{def.unit}</div>
                </div>

                {value !== null && baselineMean !== null && baselineStd !== null && (
                  <BellCurve mean={baselineMean} std={baselineStd} value={value} color={curveColor} />
                )}
              </div>

              {/* Δ% badge — top right */}
              {deltaPct !== null && (
                <div style={{
                  position: 'absolute', top: 9, right: 10,
                  fontSize: 10,
                  color: Math.abs(deltaPct) < 5
                    ? 'var(--color-text-dim)'
                    : deltaPct > 0 ? 'var(--color-amber)' : 'var(--color-green)',
                }}>
                  {deltaPct > 0 ? '↑' : '↓'} {Math.abs(deltaPct).toFixed(0)}%
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
