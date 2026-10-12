// components/Header.tsx — Top navigation bar with proper sim state machine
//
// Sim states:
//   idle      → day 0, not running → [▶ Start]
//   running   → day > 0, running   → [⏸ Pause] [⚡ Inject Fault]
//   paused    → day > 0, not run   → [▶ Resume] [↺ Restart] [⚡ Inject Fault]
//   completed → day == total_days  → [↺ Restart]
//
// Lag-free controls:
//   All actions patch Zustand optimistically in the same JS tick as the click,
//   so phase & buttons re-render instantly. A `transitioning` flag dims the
//   active button + shows a brief spinner while the fetch round-trip completes.
//   Speed highlight is also optimistic — no local state needed.

import { useState, useRef, useEffect } from 'react'
import { useTwinStore } from '../stores/useTwinStore'
import { useSimControls } from '../hooks/useTwinApi'
import { flushWs } from '../hooks/useWebSocket'
import { getActiveAlerts } from '../utils/activeAlerts'
import type { Theme } from '../hooks/useTheme'

const SPEED_OPTIONS = [1, 10, 25, 50, 100]

// Start-day presets — labelled with the scenario milestone at that day
const START_DAY_OPTIONS: { day: number; label: string }[] = [
  { day: 0,  label: 'Day 0 · healthy baseline' },
  { day: 25, label: 'Day 25 · filter clogging' },
  { day: 40, label: 'Day 40 · bearing wear' },
  { day: 50, label: 'Day 50 · multi-fault' },
  { day: 60, label: 'Day 60 · coil fouling' },
  { day: 75, label: 'Day 75 · late stage' },
]

const MILESTONES = [
  { day: 20, label: 'filter fault onset' },
  { day: 35, label: 'bearing fault onset' },
  { day: 55, label: 'coil fault onset' },
]

const ico = { width: 12, height: 12, viewBox: '0 0 24 24', fill: 'currentColor', stroke: 'none' } as const
const IconPlay   = () => <svg {...ico}><path d="M6 4l14 8-14 8z" /></svg>
const IconPause  = () => <svg {...ico}><rect x="5" y="4" width="5" height="16" rx="1" /><rect x="14" y="4" width="5" height="16" rx="1" /></svg>
const IconStop   = () => <svg {...ico}><rect x="5" y="5" width="14" height="14" rx="2" /></svg>
const IconBolt   = () => <svg {...ico}><path d="M13 2L4 14h6l-1 8 9-12h-6z" /></svg>
const IconReplay = () => (
  <svg {...ico} fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" />
  </svg>
)

type SimPhase = 'idle' | 'running' | 'paused' | 'completed'

function getPhase(running: boolean, simDay: number, totalDays: number): SimPhase {
  if (simDay >= totalDays) return 'completed'
  if (running) return 'running'
  if (simDay > 0) return 'paused'
  return 'idle'
}

export default function Header({ theme, toggleTheme }: { theme: Theme; toggleTheme: () => void }) {
  const { simStatus, wsConnected, alerts, snapshot } = useTwinStore()
  const { start, pause, resume, restart, setSpeed, injectFault } = useSimControls()

  // ── Transitioning state ────────────────────────────────────────────────────
  // True only during the fetch round-trip after an action. Phase already flipped
  // optimistically, so `transitioning` only shows a brief confirming spinner.
  const [transitioning, setTransitioning] = useState(false)
  const [startDay, setStartDay] = useState(25)

  async function runAction(fn: () => Promise<void>) {
    setTransitioning(true)
    try { await fn() } finally { setTransitioning(false) }
  }

  // ── Derived state ──────────────────────────────────────────────────────────
  const activeAlerts  = getActiveAlerts(alerts)
  const criticalCount = activeAlerts.filter((a) => a.severity === 'critical').length

  const phase: SimPhase = simStatus
    ? getPhase(simStatus.running, simStatus.sim_day, simStatus.total_days)
    : 'idle'

  // ── Speed highlight — decoupled from simStatus poll ──────────────────
  // selectedSpeed is set ONLY by user clicks, never by the 2s poll.
  // This makes it immune to any race between concurrent requests or refreshStatus.
  const [selectedSpeed, setSelectedSpeed] = useState<number>(50)
  const speedInitialized = useRef(false)
  // Seed from the first status we receive (e.g. after page refresh)
  useEffect(() => {
    if (!speedInitialized.current && simStatus?.speed_multiplier) {
      setSelectedSpeed(simStatus.speed_multiplier)
      speedInitialized.current = true
    }
  }, [simStatus?.speed_multiplier])

  const speedAbortRef   = useRef<AbortController | null>(null)
  const speedChangingTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [speedChanging, setSpeedChanging] = useState(false)

  const handleSpeedClick = (s: number) => {
    setSelectedSpeed(s)                  // instant, never overridden
    setSpeedChanging(true)
    if (speedChangingTimer.current) clearTimeout(speedChangingTimer.current)
    speedChangingTimer.current = setTimeout(() => setSpeedChanging(false), 2500)
    speedAbortRef.current?.abort()       // cancel any in-flight speed POST
    const ctrl = new AbortController()
    speedAbortRef.current = ctrl
    setSpeed(s, ctrl.signal).catch(() => {}) // errors silently (AbortError expected)
    flushWs()   // close+reopen WS to discard buffered old-speed messages
  }

  // Clear speedChanging the moment the WS confirms the new speed has taken
  // effect on the backend. The 2.5s timer is a safety fallback only.
  useEffect(() => {
    if (speedChanging && snapshot?.speed_multiplier === selectedSpeed) {
      setSpeedChanging(false)
      if (speedChangingTimer.current) {
        clearTimeout(speedChangingTimer.current)
        speedChangingTimer.current = null
      }
    }
  }, [snapshot?.speed_multiplier, selectedSpeed, speedChanging])

  const [isJump, setIsJump] = useState(false)
  const [scrub, setScrub] = useState<number | null>(null)
  const maxDay = Math.max(1, (simStatus?.total_days ?? 90) - 1)
  const shownDay = scrub ?? (phase === 'idle' ? startDay : simStatus?.sim_day ?? 0)

  // Jump to any day at any time. Idle only selects the start day; otherwise the
  // engine restarts with a silent fast-forward and keeps running.
  function jumpTo(day: number) {
    setStartDay(day)
    if (phase === 'idle') return
    setIsJump(true)
    runAction(() => start(day))
  }
  function commitScrub() {
    if (scrub === null) return
    const d = scrub
    setScrub(null)
    jumpTo(d)
  }
  function onPrimary() {
    setIsJump(phase === 'idle' || phase === 'completed')
    if (phase === 'running') runAction(pause)
    else if (phase === 'paused') runAction(resume)
    else runAction(() => start(startDay))
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <header style={{
      display: 'flex',
      alignItems: 'center',
      height: 52,
      padding: '0 16px',
      background: 'var(--header-bg)',
      borderBottom: '1px solid var(--color-border)',
      backdropFilter: 'blur(12px)',
      flexShrink: 0,
      gap: 0,
      position: 'relative',
      zIndex: 10,
    }}>

      {/* ── Logo + asset badge ─────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        <div style={{
          width: 7, height: 7, borderRadius: '50%',
          background: wsConnected ? 'var(--color-green)' : 'var(--color-text-mute)',
          boxShadow: wsConnected ? '0 0 6px var(--color-green)' : 'none',
          animation: wsConnected ? 'pulse 2s ease-in-out infinite' : 'none',
          flexShrink: 0,
        }} />
        <span style={{ fontWeight: 800, fontSize: 14, color: 'var(--color-blue)', letterSpacing: '-0.02em' }}>
          aqueduct
        </span>
        <span style={{ color: 'var(--color-text-mute)', fontSize: 12, fontWeight: 400 }}>PdM</span>
        <div style={{
          background: 'var(--color-surface2)',
          border: '1px solid var(--color-border)',
          borderRadius: 5,
          padding: '2px 9px',
          fontSize: 11,
          color: 'var(--color-text-dim)',
          marginLeft: 4,
        }}>
          AHU-01 · Bldg A
        </div>
      </div>

      {/* ── Timeline scrubber — always visible, jump to any day at any time ── */}
      {simStatus && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, margin: '0 auto', minWidth: 0, padding: '0 12px',
        }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
            <span style={{ fontSize: 10, color: 'var(--color-text-mute)', letterSpacing: '0.05em', textTransform: 'uppercase' }}>Day</span>
            <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--color-blue)', fontVariantNumeric: 'tabular-nums', minWidth: 26 }}>
              {Math.floor(shownDay)}
            </span>
            <span style={{ fontSize: 11, color: 'var(--color-text-mute)' }}>/ {simStatus.total_days}</span>
          </div>

          <div style={{ position: 'relative', width: 150, height: 22, display: 'flex', alignItems: 'center' }}>
            <div style={{ position: 'absolute', left: 0, right: 0, height: 4, borderRadius: 2, background: 'var(--color-surface2)' }} />
            <div style={{
              position: 'absolute', left: 0, height: 4, borderRadius: 2,
              width: `${(shownDay / maxDay) * 100}%`,
              background: phase === 'paused' ? 'var(--color-amber)' : phase === 'completed' ? 'var(--color-green)' : 'var(--color-blue)',
              transition: scrub === null ? 'width 0.5s ease' : 'none',
            }} />
            {MILESTONES.map((m) => (
              <div key={m.day} title={`Day ${m.day} · ${m.label}`} style={{
                position: 'absolute', left: `${(m.day / maxDay) * 100}%`, top: 3, width: 2, height: 16,
                marginLeft: -1, borderRadius: 1, background: 'var(--color-text-mute)', opacity: 0.55, pointerEvents: 'none',
              }} />
            ))}
            <input
              type="range" className="day-scrubber"
              min={0} max={maxDay} step={1}
              value={Math.floor(shownDay)}
              disabled={transitioning}
              aria-label="Simulation day"
              onChange={(e) => setScrub(Number(e.target.value))}
              onPointerUp={commitScrub} onKeyUp={commitScrub} onBlur={commitScrub}
              style={{ position: 'absolute', inset: 0, width: '100%', margin: 0, background: 'transparent', cursor: 'pointer' }}
            />
          </div>

          <select
            value=""
            disabled={transitioning}
            aria-label="Jump to scenario milestone"
            onChange={(e) => { if (e.target.value !== '') jumpTo(Number(e.target.value)) }}
            style={{
              fontSize: 11, fontFamily: 'var(--font-sans)', borderRadius: 6,
              border: '1px solid var(--color-border)', background: 'var(--color-surface2)',
              color: 'var(--color-text)', cursor: 'pointer', width: 104,
              appearance: 'none', WebkitAppearance: 'none',
              padding: '3px 22px 3px 8px',
              backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' fill='none' stroke='%238a94a6' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E\")",
              backgroundRepeat: 'no-repeat', backgroundPosition: 'right 8px center',
            }}
          >
            <option value="">Jump to…</option>
            {START_DAY_OPTIONS.map((o) => (
              <option key={o.day} value={o.day}>{o.label}</option>
            ))}
          </select>

          <div style={{
            fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
            padding: '2px 7px', borderRadius: 4, minWidth: 54, textAlign: 'center',
            background: phase === 'idle' ? 'var(--color-surface2)' : phase === 'paused' ? 'rgba(232,137,12,0.12)' : 'rgba(23,166,115,0.12)',
            color: phase === 'idle' ? 'var(--color-text-mute)' : phase === 'paused' ? 'var(--color-amber)' : 'var(--color-green)',
          }}>
            {transitioning && isJump ? 'Seeking…' : phase === 'running' ? 'Live' : phase === 'paused' ? 'Paused' : phase === 'completed' ? 'Done' : 'Idle'}
          </div>
        </div>
      )}

      {/* ── Controls (right-aligned) ─────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>

        {(phase === 'running' || phase === 'paused') && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 3, marginRight: 4 }}>
            {SPEED_OPTIONS.map((s) => (
              <button
                key={s}
                className="btn"
                style={{
                  padding: '2px 6px', fontSize: 11, minWidth: 34,
                  position: 'relative',
                  ...(selectedSpeed === s ? {
                    background: 'var(--color-blue)', color: '#fff', borderColor: 'var(--color-blue)',
                    boxShadow: '0 0 8px rgba(15,122,192,0.4)',
                    opacity: speedChanging ? 0.65 : 1,
                  } : {}),
                }}
                onClick={() => handleSpeedClick(s)}
              >
                {s}×
                {selectedSpeed === s && speedChanging && (
                  <span style={{
                    display: 'inline-block', width: 4, height: 4, borderRadius: '50%',
                    background: 'rgba(255,255,255,0.9)', marginLeft: 3, verticalAlign: 'middle',
                    animation: 'pulse 0.8s ease-in-out infinite',
                  }} />
                )}
              </button>
            ))}
          </div>
        )}

        {/* Unified transport: primary play/pause, replay, reset */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            className={phase === 'running' ? 'btn' : 'btn btn-primary'}
            style={{ fontSize: 12, padding: '5px 12px', display: 'flex', alignItems: 'center', gap: 6, minWidth: 92, justifyContent: 'center', opacity: transitioning ? 0.65 : 1 }}
            disabled={transitioning}
            onClick={onPrimary}
            title={phase === 'running' ? 'Pause' : phase === 'paused' ? 'Resume' : phase === 'completed' ? `Replay from day ${startDay}` : `Start from day ${startDay}`}
          >
            {phase === 'running' ? <IconPause /> : <IconPlay />}
            {phase === 'running' ? 'Pause' : phase === 'paused' ? 'Resume' : phase === 'completed' ? 'Replay' : 'Start'}
          </button>
          {phase !== 'idle' && phase !== 'completed' && (
            <button className="btn" style={{ padding: '5px 8px', display: 'flex', alignItems: 'center', opacity: transitioning ? 0.65 : 1 }}
              disabled={transitioning} onClick={() => { setIsJump(true); runAction(() => start(startDay)) }}
              title={`Replay from day ${startDay}`} aria-label="Replay">
              <IconReplay />
            </button>
          )}
          {phase !== 'idle' && (
            <button className="btn" style={{ padding: '5px 8px', display: 'flex', alignItems: 'center', opacity: transitioning ? 0.65 : 1 }}
              disabled={transitioning} onClick={() => { setIsJump(false); runAction(restart) }}
              title="Stop and reset to idle (day 0)" aria-label="Reset">
              <IconStop />
            </button>
          )}
        </div>

        {(phase === 'running' || phase === 'paused') && (
          <button
            className="btn btn-danger"
            style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 5 }}
            onClick={() => injectFault('bearing_wear', 'ahu-01.supplyFan')}
            title="Inject bearing wear on Supply Fan"
          >
            <IconBolt /> Inject Fault
          </button>
        )}

        <div style={{ width: 1, height: 22, background: 'var(--color-border)' }} />

        {/* Alert badges */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {criticalCount > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--color-red)', animation: 'pulse 1s ease-in-out infinite' }} />
              <span style={{ fontSize: 11, color: 'var(--color-red)', fontWeight: 700 }}>
                {criticalCount} critical
              </span>
            </div>
          )}
          {activeAlerts.length === 0 && phase === 'running' && (
            <span style={{ fontSize: 10, color: 'var(--color-text-mute)' }}>✓ No alerts</span>
          )}
          {!wsConnected && (
            <span style={{ fontSize: 10, color: 'var(--color-amber)' }}>⚠ reconnecting…</span>
          )}
        </div>

        {/* ── Theme toggle ──────────────────────────────────────── */}
        <div style={{ width: 1, height: 22, background: 'var(--color-border)', marginLeft: 4 }} />
        <button
          onClick={toggleTheme}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          style={{
            background: 'none',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            width: 30,
            height: 26,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--color-text-dim)',
            transition: 'all 150ms ease',
            padding: 0,
            marginLeft: 6,
            flexShrink: 0,
          }}
        >
          {theme === 'dark' ? (
            // Sun icon (switch to light)
            <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
              <circle cx={12} cy={12} r={5} />
              <line x1={12} y1={1} x2={12} y2={3} />
              <line x1={12} y1={21} x2={12} y2={23} />
              <line x1={4.22} y1={4.22} x2={5.64} y2={5.64} />
              <line x1={18.36} y1={18.36} x2={19.78} y2={19.78} />
              <line x1={1} y1={12} x2={3} y2={12} />
              <line x1={21} y1={12} x2={23} y2={12} />
              <line x1={4.22} y1={19.78} x2={5.64} y2={18.36} />
              <line x1={18.36} y1={5.64} x2={19.78} y2={4.22} />
            </svg>
          ) : (
            // Moon icon (switch to dark)
            <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  )
}
