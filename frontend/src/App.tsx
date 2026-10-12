// App.tsx — Root application component
//
// Layout (all CSS Grid — pixel-exact, no flex overflow surprises):
//
//   ┌──────────────────────────────────────────────────────────────┐
//   │  Header (52px)                                               │
//   ├────────────────────┬─────────────────────────────────────────┤
//   │  LEFT (420px)      │  RIGHT (1fr)                            │
//   │  ┌──────────────┐  │  ┌───────────────────────────────────┐  │
//   │  │ [2D ⇄ 3D]    │  │  │ Sensor cards (auto height)        │  │
//   │  │              │  │  └───────────────────────────────────┘  │
//   │  │ AHU Viz      │  │  ┌───────────────────────────────────┐  │
//   │  │ (300px)      │  │  │ Time series charts (1fr)          │  │
//   │  └──────────────┘  │  └───────────────────────────────────┘  │
//   │  ┌──────────────┐  │                                         │
//   │  │ Health bars  │  │                                         │
//   │  │ (1fr)        │  │                                         │
//   │  └──────────────┘  │                                         │
//   ├────────────────────┴─────────────────────────────────────────┤
//   │  BOTTOM (300px) — 3 equal columns                            │
//   │  [ Alerts ] | [ Maintenance / RUL ] | [ aQ Assistant ]       │
//   └──────────────────────────────────────────────────────────────┘

import { useState } from 'react'
import { useWebSocket } from './hooks/useWebSocket'
import { useTwinGraph, useAlerts, useRecommendations, useSimStatus } from './hooks/useTwinApi'
import { useTheme } from './hooks/useTheme'
import Header from './components/Header'
import SensorRow from './components/SensorRow'
import HealthPanel from './components/HealthPanel'
import TimeSeriesCharts from './components/TimeSeriesCharts'
import AlertsPanel from './components/AlertsPanel'
import MaintenancePanel from './components/MaintenancePanel'
import AQAssistant from './components/AQAssistant'
import AHUSchematic2D from './components/AHUSchematic2D'
import AHUScene from './three/AHUScene'
import './index.css'

const LEFT_W    = 500   // px — left column width
const BOTTOM_H  = 300   // px — bottom panel height (taller for breathing room)
const HEADER_H  = 52    // px — header

export default function App() {
  useWebSocket()
  useTwinGraph()
  useAlerts()
  useRecommendations()
  useSimStatus()

  const { theme, toggleTheme } = useTheme()
  const [view3D, setView3D] = useState(false)

  return (
    // Outer shell: header row + body row
    <div style={{
      display: 'grid',
      gridTemplateRows: `${HEADER_H}px 1fr`,
      height: '100vh',
      overflow: 'hidden',
    }}>
      <Header theme={theme} toggleTheme={toggleTheme} />

      {/* ── Body: left | right, each internally a grid ────────────────────── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: `${LEFT_W}px 1fr`,
        gridTemplateRows: '1fr',
        overflow: 'hidden',
        minHeight: 0,
      }}>

        {/* ── LEFT COLUMN ─────────────────────────────────────────────────── */}
        <div style={{
          display: 'grid',
          gridTemplateRows: '3fr 2fr',
          borderRight: '1px solid var(--color-border)',
          overflow: 'hidden',
        }}>

          {/* AHU Visualisation + toggle */}
          <div style={{ position: 'relative', borderBottom: '1px solid var(--color-border)', overflow: 'hidden' }}>

              {/* Visualisation — only one rendered at a time, toggle pill is inside each component */}
            <div style={{ width: '100%', height: '100%', overflow: 'hidden' }}>
              {view3D
                ? <AHUScene view3D={view3D} onToggleView={() => setView3D(false)} />
                : <AHUSchematic2D view3D={view3D} onToggleView={() => setView3D(true)} />
              }
            </div>
          </div>

          {/* Health bars */}
          <div style={{ overflow: 'hidden' }}>
            <HealthPanel />
          </div>
        </div>

        {/* ── RIGHT COLUMN ────────────────────────────────────────────────── */}
        <div style={{
          display: 'grid',
          gridTemplateRows: `auto 1fr ${BOTTOM_H}px`,
          overflow: 'hidden',
          minHeight: 0,
        }}>

          {/* Sensor cards */}
          <div style={{ borderBottom: '1px solid var(--color-border)', overflow: 'hidden' }}>
            <SensorRow />
          </div>

          {/* Time series charts */}
          <div style={{ overflow: 'hidden', minHeight: 0 }}>
            <TimeSeriesCharts />
          </div>

          {/* Bottom strip — always exactly BOTTOM_H px */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            borderTop: '1px solid var(--color-border)',
            overflow: 'hidden',
            minHeight: 0,
          }}>
            <div style={{ overflow: 'hidden', borderRight: '1px solid var(--color-border)' }}>
              <AlertsPanel />
            </div>
            <div style={{ overflow: 'hidden', borderRight: '1px solid var(--color-border)' }}>
              <MaintenancePanel />
            </div>
            <div style={{ overflow: 'hidden' }}>
              <AQAssistant />
            </div>
          </div>
        </div>

      </div>
    </div>
  )
}
