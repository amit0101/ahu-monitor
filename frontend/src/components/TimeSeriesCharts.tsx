// components/TimeSeriesCharts.tsx — Real-time multi-line charts with Recharts
//
// Shows two charts:
//   1. Return Fan: Vibration + Bearing Temp (primary fault indicators)
//   2. Filter Bank: ΔP + Airflow (secondary fault)
// Anomalous points are rendered as red dots.
// History data is populated by useHistoryPolling → Zustand store.

import { useMemo, useEffect, useRef } from 'react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, Dot,
} from 'recharts'
import { useTwinStore } from '../stores/useTwinStore'
import { useHistoryPolling } from '../hooks/useTwinApi'
import type { HistoryPoint } from '../types'

interface ChartConfig {
  title: string
  entityId: string
  series: Array<{
    sensorId: string
    label: string
    color: string
    yAxisId?: string
    unit: string
  }>
  warningLine?: { value: number; label: string; yAxisId?: string }
}

const CHARTS: ChartConfig[] = [
  {
    title: 'Supply Fan — Vibration & Motor Current',
    entityId: 'ahu-01.supplyFan',
    series: [
      { sensorId: 'ahu-01.supplyFan.vibration', label: 'Vibration', color: '#E84040', yAxisId: 'left',  unit: 'mm/s' },
      { sensorId: 'ahu-01.supplyFan.current',   label: 'Current',   color: '#0F7AC0', yAxisId: 'right', unit: 'A' },
    ],
    warningLine: { value: 5.0, label: 'ISO 10816 Limit', yAxisId: 'left' },
  },
  {
    title: 'Return Fan — Vibration & Bearing Temperature',
    entityId: 'ahu-01.returnFan',
    series: [
      { sensorId: 'ahu-01.returnFan.vibration',  label: 'Vibration', color: '#E84040', yAxisId: 'left',  unit: 'mm/s' },
      { sensorId: 'ahu-01.returnFan.bearingTemp', label: 'Brg Temp',  color: '#E8890C', yAxisId: 'right', unit: '°C' },
    ],
    warningLine: { value: 5.0, label: 'ISO 10816 Limit', yAxisId: 'left' },
  },
  {
    title: 'Filter Bank — Differential Pressure & Airflow',
    entityId: 'ahu-01.filterBank',
    series: [
      { sensorId: 'ahu-01.filterBank.pressureDiff', label: 'Filter ΔP', color: '#E8890C', yAxisId: 'left',  unit: 'Pa' },
      { sensorId: 'ahu-01.filterBank.airflow',       label: 'Airflow',   color: '#0F7AC0', yAxisId: 'right', unit: 'm³/h' },
    ],
    warningLine: { value: 250, label: 'Service Limit (250 Pa)', yAxisId: 'left' },
  },
]

// Entity IDs we need history for (derived from chart configs)
const HISTORY_ENTITY_IDS = [...new Set(CHARTS.map((c) => c.entityId))]

// Merge multiple sensor histories into one array keyed by sim_day
function mergeHistory(
  histories: Record<string, HistoryPoint[]>,
  sensorIds: string[],
  maxPoints = 200
): Array<Record<string, number | boolean>> {
  if (!sensorIds.length) return []

  const primaryId = sensorIds[0]
  const primary = (histories[primaryId] ?? []).slice(-maxPoints)
  if (primary.length === 0) return []

  return primary.map((pt, i) => {
    const row: Record<string, number | boolean> = { t: pt.t, anom: pt.anom }
    sensorIds.forEach((sid) => {
      const h = histories[sid] ?? []
      const offset = h.length - primary.length
      const val = h[offset + i]?.v
      if (val !== undefined) row[sid] = val
    })
    return row
  })
}

// Custom dot: red filled for anomalous points
function AnomalyDot(props: any) {
  const { cx, cy, payload } = props
  if (payload.anom) {
    return <Dot cx={cx} cy={cy} r={3} fill="#E84040" stroke="none" />
  }
  return <Dot cx={cx} cy={cy} r={0} fill="none" stroke="none" />
}

function SingleChart({
  config,
  histories,
  isHighlighted,
}: {
  config: ChartConfig
  histories: Record<string, HistoryPoint[]>
  isHighlighted?: boolean
}) {
  const ref = useRef<HTMLDivElement>(null)

  // Scroll into view when this chart becomes highlighted
  useEffect(() => {
    if (isHighlighted && ref.current) {
      ref.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [isHighlighted])
  const merged = useMemo(
    () => mergeHistory(histories, config.series.map((s) => s.sensorId)),
    [histories, config.series]
  )

  const hasDualAxis = config.series.some((s) => s.yAxisId === 'right')
  const hasData = merged.length > 0

  return (
    <div
      ref={ref}
      style={{
        background: 'var(--color-surface)',
        border: isHighlighted
          ? '1px solid rgba(15,122,192,0.6)'
          : '1px solid var(--color-border)',
        boxShadow: isHighlighted ? '0 0 12px rgba(15,122,192,0.15)' : 'none',
        borderRadius: 10,
        padding: '12px 14px',
        flex: 1,
        transition: 'border-color 0.3s, box-shadow 0.3s',
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>{config.title}</span>
        <div style={{ display: 'flex', gap: 12 }}>
          {config.series.map((s) => (
            <div key={s.sensorId} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-text-dim)' }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: s.color }} />
              {s.label} ({s.unit})
            </div>
          ))}
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: 'var(--color-text-dim)' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#E84040' }} />
            Anomaly
          </div>
        </div>
      </div>

      {/* Chart or loading placeholder */}
      {!hasData ? (
        <div style={{
          height: 100,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--color-text-mute)',
          fontSize: 11,
          fontStyle: 'italic',
        }}>
          Waiting for data…
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={100}>
          <LineChart data={merged} margin={{ top: 4, right: hasDualAxis ? 40 : 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(15,122,192,0.08)" vertical={false} />
            <XAxis
              dataKey="t"
              tick={{ fontSize: 9, fill: 'var(--color-text-mute)' }}
              tickFormatter={(v) => `D${Math.floor(v)}`}
              tickLine={false}
              axisLine={{ stroke: 'var(--color-border)' }}
              interval="preserveStartEnd"
            />
            <YAxis
              yAxisId="left"
              tick={{ fontSize: 9, fill: 'var(--color-text-mute)' }}
              tickLine={false}
              axisLine={false}
              width={28}
            />
            {hasDualAxis && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 9, fill: 'var(--color-text-mute)' }}
                tickLine={false}
                axisLine={false}
                width={28}
              />
            )}
            <Tooltip
              contentStyle={{
                background: 'var(--color-surface2)',
                border: '1px solid var(--color-border)',
                borderRadius: 6,
                fontSize: 11,
              }}
              labelStyle={{ color: 'var(--color-text-dim)', marginBottom: 4 }}
              labelFormatter={(v) => `Day ${Number(v).toFixed(1)}`}
            />

            {config.warningLine && (
              <ReferenceLine
                yAxisId={config.warningLine.yAxisId ?? 'left'}
                y={config.warningLine.value}
                stroke="rgba(232,64,64,0.5)"
                strokeDasharray="4 3"
                label={{ value: config.warningLine.label, fill: 'rgba(232,64,64,0.6)', fontSize: 9, position: 'insideTopRight' }}
              />
            )}

            {config.series.map((s) => (
              <Line
                key={s.sensorId}
                yAxisId={s.yAxisId ?? 'left'}
                dataKey={s.sensorId}
                stroke={s.color}
                strokeWidth={1.5}
                dot={<AnomalyDot />}
                activeDot={{ r: 4, fill: s.color }}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}

export default function TimeSeriesCharts() {
  useHistoryPolling(HISTORY_ENTITY_IDS)
  const histories = useTwinStore((s) => s.histories)
  const selectedEntityId = useTwinStore((s) => s.selectedEntityId)

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
      padding: '10px 14px',
      height: '100%',
      overflowY: 'auto',
    }}>
      {CHARTS.map((config) => (
        <SingleChart
          key={config.entityId}
          config={config}
          histories={histories}
          isHighlighted={!!selectedEntityId && config.entityId === selectedEntityId}
        />
      ))}
    </div>
  )
}
