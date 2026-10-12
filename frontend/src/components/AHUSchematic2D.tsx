// components/AHUSchematic2D.tsx — P&ID-style horizontal process flow diagram
//
// Coordinate philosophy:
//   - Y_TOP / Y_BOT are the ONLY source of truth for the duct walls.
//   - Duct walls drawn LAST so they always align with component edges.
//   - Health % labels live INSIDE each component block (not above the duct)
//     so there is no crowding between the return duct, damper actuator, and labels.
//   - viewBox height increased to 285 giving the return-air loop plenty of room.
//
// All colors reference CSS custom properties → light + dark theme compatible.

import { useTwinStore } from '../stores/useTwinStore'
import type { OperatingState } from '../types'

export interface AHUVizProps {
  view3D: boolean
  onToggleView: () => void
}

// ── Coordinate constants ───────────────────────────────────────────────────────
// Change these two lines to rescale the whole diagram.

const Y_TOP  = 128  // main supply duct top wall
const Y_BOT  = 240  // main supply duct bottom wall
const Y_CEN  = (Y_TOP + Y_BOT) / 2   // = 184
const D_H    = Y_BOT - Y_TOP          // = 112

const RET_Y  = 48   // return-air duct centerline y — generous gap from duct top
const RET_TH = 12   // return duct outer stroke width
const RET_IH = 6    // return duct inner (background) stroke width

// Component left edges + widths — all span Y_TOP → Y_BOT
const SEGS = {
  damper:     { id: 'ahu-01.damper',      x: 55,  w: 54,  label: 'Damper'       },
  filter:     { id: 'ahu-01.filterBank',  x: 114, w: 72,  label: 'Filter Bank'  },
  coolCoil:   { id: 'ahu-01.coolingCoil', x: 191, w: 82,  label: 'Cooling Coil' },
  heatCoil:   { id: 'ahu-01.heatingCoil', x: 278, w: 68,  label: 'Heating Coil' },
  supplyFan:  { id: 'ahu-01.supplyFan',   x: 351, w: 100, label: 'Supply Fan'   },
  returnFan:  { id: 'ahu-01.returnFan',   cx: 220, r: 24, label: 'Return Fan'   },
}

const DUCT_LEFT   = 55    // main duct left opening
const DUCT_RIGHT  = 451   // main duct right opening (351 + 100)
const FAN_CX      = 401   // supply fan circle center x (351 + 50)
const FAN_R       = 54    // fits within duct: 54 < D_H/2 = 56
const INLET_LEFT  = 18
const OUTLET_RIGHT = 508

// ── Health → colors ────────────────────────────────────────────────────────────

function stateC(state: OperatingState | undefined, health: number) {
  if (state === 'critical' || health < 0.4)
    return { main: 'var(--color-red)',   dim: 'var(--color-red-dim)'   }
  if (state === 'warning'  || health < 0.7)
    return { main: 'var(--color-amber)', dim: 'var(--color-amber-dim)' }
  return   { main: 'var(--color-green)', dim: 'var(--color-green-dim)' }
}

// ── Component symbols ──────────────────────────────────────────────────────────
// All symbols use Y_TOP/Y_BOT/D_H so they always fill the duct exactly.

// Damper: actuator housing above duct + pivot + 4 louver blades
function DamperSymbol({ x, w }: { x: number; w: number }) {
  const cx = x + w / 2
  const bladeCount = 4
  const bladeSpacing = (D_H - 24) / (bladeCount - 1)
  return (
    <g stroke="var(--color-text-dim)" fill="none" strokeLinecap="round" opacity={0.72}>
      {/* Actuator housing */}
      <rect x={cx - 10} y={Y_TOP - 26} width={20} height={18} rx={3}
        fill="var(--color-surface2)" stroke="var(--color-text-dim)" strokeWidth={1} />
      {/* Actuator stem */}
      <line x1={cx} y1={Y_TOP - 8} x2={cx} y2={Y_TOP} strokeWidth={1.5} />
      {/* Pivot shaft */}
      <line x1={cx} y1={Y_TOP + 4} x2={cx} y2={Y_BOT - 4}
        strokeWidth={1} strokeDasharray="4 4" opacity={0.35} />
      {/* Louver blades */}
      {Array.from({ length: bladeCount }, (_, i) => {
        const y = Y_TOP + 14 + i * bladeSpacing
        return (
          <line key={i}
            x1={x + 8} y1={y}
            x2={x + w - 8} y2={y + 8}
            strokeWidth={2.5} />
        )
      })}
    </g>
  )
}

// Filter: cross-hatching, clipped to component bounds
function FilterSymbol({ x, w }: { x: number; w: number }) {
  const clipId = `fclip-${x}`
  const offsets = Array.from({ length: 22 }, (_, i) => i * 13 - 26)
  return (
    <g>
      <defs>
        <clipPath id={clipId}>
          <rect x={x + 5} y={Y_TOP + 8} width={w - 10} height={D_H - 16} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clipId})`} opacity={0.38}>
        {offsets.map((off, i) => (
          <line key={i}
            x1={x + off} y1={Y_BOT}
            x2={x + off + D_H} y2={Y_TOP}
            stroke="var(--color-text-dim)" strokeWidth={1.2} />
        ))}
      </g>
      <rect x={x + 5} y={Y_TOP + 8} width={w - 10} height={D_H - 16}
        fill="none" stroke="var(--color-text-dim)" strokeWidth={1} opacity={0.3} rx={2} />
    </g>
  )
}

// Coil: horizontal tubes + fin marks + header pipes
function CoilSymbol({ x, w, heating }: { x: number; w: number; heating?: boolean }) {
  const tubeColor = heating ? 'var(--color-amber)' : 'var(--color-blue)'
  const n = 4
  const gap = (D_H - 30) / (n - 1)  // evenly spaced with padding
  return (
    <g>
      {Array.from({ length: n }, (_, i) => {
        const ty = Y_TOP + 18 + i * gap
        const finStep = (w - 24) / 5
        return (
          <g key={i}>
            <line x1={x + 12} y1={ty} x2={x + w - 12} y2={ty}
              stroke={tubeColor} strokeWidth={2.5} strokeLinecap="round" opacity={0.75} />
            {Array.from({ length: 5 }, (_, j) => {
              const fx = x + 15 + j * finStep
              return (
                <line key={j} x1={fx} y1={ty - 8} x2={fx} y2={ty + 8}
                  stroke={tubeColor} strokeWidth={1} opacity={0.38} />
              )
            })}
          </g>
        )
      })}
      {/* Left/right header pipes */}
      <line x1={x + 12} y1={Y_TOP + 18} x2={x + 12} y2={Y_TOP + 18 + gap * (n - 1)}
        stroke={tubeColor} strokeWidth={2.5} strokeLinecap="round" opacity={0.5} />
      <line x1={x + w - 12} y1={Y_TOP + 18} x2={x + w - 12} y2={Y_TOP + 18 + gap * (n - 1)}
        stroke={tubeColor} strokeWidth={2.5} strokeLinecap="round" opacity={0.5} />
      {/* Heat marks for heating coil */}
      {heating && [-14, 0, 14].map((dx, i) => (
        <path key={i}
          d={`M ${x + w / 2 + dx} ${Y_BOT - 26}
              Q ${x + w / 2 + dx + 5} ${Y_BOT - 20}
                ${x + w / 2 + dx} ${Y_BOT - 14}
              Q ${x + w / 2 + dx - 5} ${Y_BOT - 8}
                ${x + w / 2 + dx} ${Y_BOT - 2}`}
          fill="none" stroke="var(--color-amber)"
          strokeWidth={1.5} strokeLinecap="round" opacity={0.65} />
      ))}
    </g>
  )
}

// Fan: swept blades + hub + health arc
function FanCircle({
  cx, cy, r, entityId,
}: { cx: number; cy: number; r: number; entityId: string }) {
  const { snapshot, selectedEntityId, setSelectedEntityId } = useTwinStore()
  const h = snapshot?.health[entityId]
  const colors = stateC(h?.state, h?.health ?? 1)
  const health = h?.health ?? 1
  const isSelected = selectedEntityId === entityId
  const bladeCount = 5

  return (
    <g onClick={() => setSelectedEntityId(isSelected ? null : entityId)} style={{ cursor: 'pointer' }}>
      {isSelected && (
        <circle cx={cx} cy={cy} r={r + 6}
          fill="none" stroke="var(--color-blue)"
          strokeWidth={2} strokeDasharray="6 3" opacity={0.9} />
      )}
      <circle cx={cx} cy={cy} r={r}
        fill={isSelected ? 'var(--color-blue-dim)' : colors.dim}
        stroke={colors.main} strokeWidth={isSelected ? 2 : 1.5} />
      {Array.from({ length: bladeCount }, (_, i) => {
        const a  = (i / bladeCount) * Math.PI * 2
        const a2 = a + 0.55
        const qx = cx + Math.cos(a + 0.28) * (r * 0.55)
        const qy = cy + Math.sin(a + 0.28) * (r * 0.55)
        return (
          <path key={i}
            d={`M ${cx + Math.cos(a) * 6} ${cy + Math.sin(a) * 6}
                Q ${qx} ${qy}
                  ${cx + Math.cos(a2) * (r - 7)} ${cy + Math.sin(a2) * (r - 7)}`}
            fill={colors.dim} stroke={colors.main} strokeWidth={1.2} />
        )
      })}
      {/* Hub */}
      <circle cx={cx} cy={cy} r={5.5} fill={colors.main} opacity={0.85} />
      {/* Health arc */}
      <circle cx={cx} cy={cy} r={r - 6}
        fill="none" stroke={colors.main} strokeWidth={4.5}
        strokeLinecap="round"
        strokeDasharray={`${2 * Math.PI * (r - 6) * health} ${2 * Math.PI * (r - 6)}`}
        transform={`rotate(-90 ${cx} ${cy})`}
        opacity={0.65} />
      {/* % label — same level as the other component labels, on a white pill */}
      <rect x={cx - 14} y={Y_BOT - 22} width={28} height={15} rx={3}
        fill="#fff" opacity={0.94} stroke="var(--color-border)" strokeWidth={0.5} />
      <text x={cx} y={Y_BOT - 11} textAnchor="middle" fontSize={11} fontWeight={700} fill={colors.main}>
        {Math.round(health * 100)}%
      </text>
    </g>
  )
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function AHUSchematic2D({ onToggleView }: AHUVizProps) {
  const { snapshot, selectedEntityId, setSelectedEntityId } = useTwinStore()

  function getH(id: string) {
    const h = snapshot?.health[id]
    return { health: h?.health ?? 1, state: h?.state, rul: h?.rul_days }
  }

  const ahuH  = getH('ahu-01')
  const ahuC  = stateC(ahuH.state, ahuH.health)
  const retH  = getH(SEGS.returnFan.id)
  const retC  = stateC(retH.state, retH.health)

  const mainSegs = [SEGS.damper, SEGS.filter, SEGS.coolCoil, SEGS.heatCoil, SEGS.supplyFan]

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

      {/* ── Header: toggle LEFT · title CENTER · health RIGHT ── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '7px 10px 5px', gap: 10, flexShrink: 0,
        borderBottom: '1px solid var(--color-border)',
      }}>
        {/* 2D / 3D pill */}
        <div style={{
          display: 'flex', gap: 2,
          background: 'var(--color-surface2)',
          border: '1px solid var(--color-border)',
          borderRadius: 6, padding: 2, flexShrink: 0,
        }}>
          {(['2D', '3D'] as const).map(label => {
            const active = label === '2D'
            return (
              <button key={label}
                onClick={() => { if (label === '3D') onToggleView() }}
                style={{
                  padding: '2px 10px', fontSize: 10, fontWeight: 700,
                  fontFamily: 'var(--font-sans)', border: 'none', borderRadius: 4,
                  cursor: label === '3D' ? 'pointer' : 'default',
                  letterSpacing: '0.04em', transition: 'all 150ms ease',
                  background: active ? 'var(--color-blue)' : 'transparent',
                  color:      active ? '#fff' : 'var(--color-text-mute)',
                }}
              >{label}</button>
            )
          })}
        </div>

        <span style={{
          flex: 1, fontSize: 10, fontWeight: 700,
          textTransform: 'uppercase', letterSpacing: '0.08em',
          color: 'var(--color-text-mute)',
        }}>AHU-01 Process Flow</span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{ fontSize: 10, color: 'var(--color-text-mute)' }}>System</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: ahuC.main }}>
            {Math.round(ahuH.health * 100)}%
          </span>
          <span style={{
            fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
            padding: '1px 6px', borderRadius: 3,
            background: ahuC.dim, color: ahuC.main,
          }}>
            {ahuH.state ?? 'normal'}
          </span>
        </div>
      </div>

      {/* ── SVG ── */}
      <svg
        viewBox="0 0 560 285"
        style={{ flex: 1, width: '100%' }}
        preserveAspectRatio="xMidYMid meet"
      >
        <defs>
          <marker id="arr" markerWidth="7" markerHeight="5" refX="6" refY="2.5" orient="auto">
            <polygon points="0 0, 7 2.5, 0 5" fill="var(--svg-arrow-color)" />
          </marker>
          <marker id="arr-ret" markerWidth="6" markerHeight="4" refX="5" refY="2" orient="auto">
            <polygon points="0 0, 6 2, 0 4" fill="var(--color-text-mute)" opacity="0.5" />
          </marker>
        </defs>

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 1 — Return duct channel (two parallel polylines)
            Outer stroke = duct walls. Inner stroke = background colour = hollow.
            ══════════════════════════════════════════════════════════════════ */}

        <polyline
          points={`${DUCT_RIGHT},${Y_CEN} 496,${Y_CEN} 496,${RET_Y} ${INLET_LEFT},${RET_Y} ${INLET_LEFT},${Y_CEN} ${DUCT_LEFT},${Y_CEN}`}
          fill="none"
          stroke="var(--svg-housing-stroke)"
          strokeWidth={RET_TH}
          strokeLinejoin="miter"
          strokeLinecap="square"
        />
        <polyline
          points={`${DUCT_RIGHT},${Y_CEN} 496,${Y_CEN} 496,${RET_Y} ${INLET_LEFT},${RET_Y} ${INLET_LEFT},${Y_CEN} ${DUCT_LEFT},${Y_CEN}`}
          fill="none"
          stroke="var(--color-bg)"
          strokeWidth={RET_IH}
          strokeLinejoin="miter"
          strokeLinecap="square"
        />

        {/* Return duct label — positioned RIGHT of the return fan */}
        <text x={370} y={RET_Y - 8} textAnchor="middle"
          fontSize={8} fill="var(--color-text-mute)" fontWeight={500} letterSpacing={0.5}>
          RETURN AIR
        </text>

        {/* Return flow direction arrows */}
        {/* Right side: outlet → up */}
        <polygon points={`496,${Y_CEN - 46} 492,${Y_CEN - 56} 500,${Y_CEN - 56}`}
          fill="var(--color-text-mute)" opacity={0.45} />
        {/* Top: going left (right of return fan) */}
        <polygon points={`400,${RET_Y - 3} 390,${RET_Y} 400,${RET_Y + 3}`}
          fill="var(--color-text-mute)" opacity={0.45} />
        {/* Left side: going down */}
        <polygon points={`${INLET_LEFT - 3},${Y_CEN - 50} ${INLET_LEFT},${Y_CEN - 40} ${INLET_LEFT + 3},${Y_CEN - 50}`}
          fill="var(--color-text-mute)" opacity={0.45} />

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 2 — Return fan (on the return duct top path)
            ══════════════════════════════════════════════════════════════════ */}

        <g onClick={() => setSelectedEntityId(
          selectedEntityId === SEGS.returnFan.id ? null : SEGS.returnFan.id
        )} style={{ cursor: 'pointer' }}>
          {selectedEntityId === SEGS.returnFan.id && (
            <circle cx={SEGS.returnFan.cx} cy={RET_Y} r={SEGS.returnFan.r + 5}
              fill="none" stroke="var(--color-blue)"
              strokeWidth={2} strokeDasharray="5 3" opacity={0.9} />
          )}
          <circle cx={SEGS.returnFan.cx} cy={RET_Y} r={SEGS.returnFan.r}
            fill={selectedEntityId === SEGS.returnFan.id ? 'var(--color-blue-dim)' : retC.dim}
            stroke={retC.main} strokeWidth={1.5} />
          <circle cx={SEGS.returnFan.cx} cy={RET_Y} r={4} fill={retC.main} opacity={0.8} />
          {Array.from({ length: 4 }, (_, i) => {
            const a  = (i / 4) * Math.PI * 2
            const a2 = a + 0.55
            return (
              <path key={i}
                d={`M ${SEGS.returnFan.cx + Math.cos(a) * 4} ${RET_Y + Math.sin(a) * 4}
                    Q ${SEGS.returnFan.cx + Math.cos(a + 0.28) * 14}
                      ${RET_Y + Math.sin(a + 0.28) * 14}
                      ${SEGS.returnFan.cx + Math.cos(a2) * (SEGS.returnFan.r - 5)}
                      ${RET_Y + Math.sin(a2) * (SEGS.returnFan.r - 5)}`}
                fill={retC.dim} stroke={retC.main} strokeWidth={1.2} />
            )
          })}
          {/* Health % inside circle */}
          <text x={SEGS.returnFan.cx} y={RET_Y + 4}
            textAnchor="middle" fontSize={9} fontWeight={700} fill={retC.main}>
            {Math.round(retH.health * 100)}%
          </text>
          {/* Label below circle */}
          <text x={SEGS.returnFan.cx} y={RET_Y + SEGS.returnFan.r + 12}
            textAnchor="middle" fontSize={8} fontWeight={600} fill="var(--color-text-dim)">
            Return Fan
          </text>
        </g>

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 3 — Main supply duct background fill
            ══════════════════════════════════════════════════════════════════ */}

        <rect x={DUCT_LEFT} y={Y_TOP} width={DUCT_RIGHT - DUCT_LEFT} height={D_H}
          fill="var(--svg-housing-fill)" />
        {/* Inlet stub */}
        <rect x={INLET_LEFT} y={Y_TOP} width={DUCT_LEFT - INLET_LEFT} height={D_H}
          fill="var(--svg-housing-fill)" />
        {/* Outlet stub */}
        <rect x={DUCT_RIGHT} y={Y_TOP} width={OUTLET_RIGHT - DUCT_RIGHT} height={D_H}
          fill="var(--svg-housing-fill)" />

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 4 — Component fills + symbols
            Health % is shown INSIDE each block (no above-duct labels)
            so there is nothing to overlap with the return duct / actuator.
            ══════════════════════════════════════════════════════════════════ */}

        {mainSegs.map(seg => {
          const isSupplyFan = seg === SEGS.supplyFan
          const { health, state, rul } = getH(seg.id)
          const colors = stateC(state, health)
          const isSelected = selectedEntityId === seg.id
          const pct = Math.round(health * 100)

          if (isSupplyFan) {
            return (
              <g key={seg.id}>
                <rect x={seg.x} y={Y_TOP} width={seg.w} height={D_H}
                  fill={isSelected ? 'var(--color-blue-dim)' : colors.dim} opacity={0.5} />
                <FanCircle cx={FAN_CX} cy={Y_CEN} r={FAN_R} entityId={seg.id} />
                {/* Name label below duct */}
                <text x={FAN_CX} y={Y_BOT + 16}
                  textAnchor="middle" fontSize={9} fontWeight={600} fill="var(--color-text-dim)">
                  {seg.label}
                </text>
                {/* RUL chip */}
                {rul !== null && rul !== undefined && rul < 60 && (
                  <g transform={`translate(${FAN_CX + FAN_R - 18}, ${Y_TOP + 7})`}>
                    <rect x={0} y={0} width={22} height={13} rx={3}
                      fill="var(--color-amber-dim)" stroke="var(--color-amber)" strokeWidth={0.5} />
                    <text x={11} y={10} textAnchor="middle" fontSize={8} fontWeight={700} fill="var(--color-amber)">
                      {Math.round(rul)}d
                    </text>
                  </g>
                )}
              </g>
            )
          }

          return (
            <g key={seg.id}
              onClick={() => setSelectedEntityId(isSelected ? null : seg.id)}
              style={{ cursor: 'pointer' }}
            >
              {/* Component fill */}
              <rect x={seg.x} y={Y_TOP} width={seg.w} height={D_H}
                fill={isSelected ? 'var(--color-blue-dim)' : colors.dim}
                style={{ transition: 'fill 0.35s ease' }} />

              {/* Status bar — 4px at the top of the block */}
              <rect x={seg.x} y={Y_TOP} width={seg.w} height={4}
                fill={colors.main} opacity={0.85} />

              {/* Symbol */}
              {seg === SEGS.damper   && <DamperSymbol x={seg.x} w={seg.w} />}
              {seg === SEGS.filter   && <FilterSymbol x={seg.x} w={seg.w} />}
              {seg === SEGS.coolCoil && <CoilSymbol   x={seg.x} w={seg.w} />}
              {seg === SEGS.heatCoil && <CoilSymbol   x={seg.x} w={seg.w} heating />}

              {/* Health % — inside block, bottom area, with subtle bg for legibility */}
              <rect x={seg.x + seg.w / 2 - 14} y={Y_BOT - 22} width={28} height={15} rx={3}
                fill="#fff" opacity={0.94} stroke="var(--color-border)" strokeWidth={0.5} />
              <text x={seg.x + seg.w / 2} y={Y_BOT - 11}
                textAnchor="middle" fontSize={11} fontWeight={700} fill={colors.main}>
                {pct}%
              </text>

              {/* Selection border */}
              {isSelected && (
                <rect x={seg.x} y={Y_TOP} width={seg.w} height={D_H}
                  fill="none" stroke="var(--color-blue)" strokeWidth={2.5} opacity={0.9} />
              )}

              {/* Name label below duct */}
              <text x={seg.x + seg.w / 2} y={Y_BOT + 16}
                textAnchor="middle" fontSize={9} fontWeight={600} fill="var(--color-text-dim)">
                {seg.label}
              </text>

              {/* RUL chip — top-right of block */}
              {rul !== null && rul !== undefined && rul < 60 && (
                <g transform={`translate(${seg.x + seg.w - 24}, ${Y_TOP + 7})`}>
                  <rect x={0} y={0} width={22} height={13} rx={3}
                    fill="var(--color-amber-dim)" stroke="var(--color-amber)" strokeWidth={0.5} />
                  <text x={11} y={10} textAnchor="middle" fontSize={8} fontWeight={700} fill="var(--color-amber)">
                    {Math.round(rul)}d
                  </text>
                </g>
              )}
            </g>
          )
        })}

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 5 — Duct walls (LAST, on top, guarantees pixel-perfect alignment)
            ══════════════════════════════════════════════════════════════════ */}

        {/* Top wall */}
        <line x1={INLET_LEFT} y1={Y_TOP} x2={OUTLET_RIGHT} y2={Y_TOP}
          stroke="var(--svg-housing-stroke)" strokeWidth={2} />
        {/* Bottom wall */}
        <line x1={INLET_LEFT} y1={Y_BOT} x2={OUTLET_RIGHT} y2={Y_BOT}
          stroke="var(--svg-housing-stroke)" strokeWidth={2} />
        {/* End caps */}
        <line x1={INLET_LEFT}   y1={Y_TOP} x2={INLET_LEFT}   y2={Y_BOT} stroke="var(--svg-housing-stroke)" strokeWidth={2} />
        <line x1={OUTLET_RIGHT} y1={Y_TOP} x2={OUTLET_RIGHT} y2={Y_BOT} stroke="var(--svg-housing-stroke)" strokeWidth={2} />
        {/* Component dividers (thin) */}
        {[114, 191, 278, 351].map(x => (
          <line key={x} x1={x} y1={Y_TOP} x2={x} y2={Y_BOT}
            stroke="var(--color-border)" strokeWidth={1} />
        ))}

        {/* ══════════════════════════════════════════════════════════════════
            LAYER 6 — Airflow arrows + edge labels
            ══════════════════════════════════════════════════════════════════ */}

        {/* Supply air flow arrows inside main duct (between components) */}
        {[80, 154, 244, 325].map(x => (
          <polygon key={x}
            points={`${x},${Y_CEN - 4} ${x + 11},${Y_CEN} ${x},${Y_CEN + 4}`}
            fill="var(--svg-arrow-color)" opacity={0.5} />
        ))}

        {/* Inlet label + arrow */}
        <line x1={INLET_LEFT + 4} y1={Y_CEN} x2={DUCT_LEFT - 6} y2={Y_CEN}
          stroke="var(--svg-arrow-color)" strokeWidth={1.5} markerEnd="url(#arr)" />
        <text x={INLET_LEFT + (DUCT_LEFT - INLET_LEFT) / 2} y={Y_CEN - 7}
          textAnchor="middle" fontSize={8} fontWeight={600} fill="var(--color-text-mute)">
          OA/RA
        </text>

        {/* Outlet label + arrow */}
        <line x1={DUCT_RIGHT + 4} y1={Y_CEN} x2={OUTLET_RIGHT - 8} y2={Y_CEN}
          stroke="var(--svg-arrow-color)" strokeWidth={1.5} markerEnd="url(#arr)" />
        <text x={OUTLET_RIGHT + 10} y={Y_CEN + 4}
          fontSize={9} fontWeight={700} fill="var(--color-green)" textAnchor="start">
          SA
        </text>

        {/* ══════════════════════════════════════════════════════════════════
            LEGEND
            ══════════════════════════════════════════════════════════════════ */}
        <g transform="translate(18, 265)">
          {[
            { color: 'var(--color-green)', label: 'Normal'   },
            { color: 'var(--color-amber)', label: 'Warning'  },
            { color: 'var(--color-red)',   label: 'Critical' },
          ].map(({ color, label }, i) => (
            <g key={label} transform={`translate(${i * 72}, 0)`}>
              <circle cx={5} cy={5} r={3.5} fill={color} />
              <text x={13} y={9} fontSize={8} fill="var(--color-text-mute)">{label}</text>
            </g>
          ))}
          <g transform="translate(220, 0)">
            <rect x={0} y={1} width={20} height={9} rx={2}
              fill="var(--color-amber-dim)" stroke="var(--color-amber)" strokeWidth={0.5} />
            <text x={10} y={9} textAnchor="middle" fontSize={7} fontWeight={700} fill="var(--color-amber)">Xd</text>
            <text x={24} y={9} fontSize={8} fill="var(--color-text-mute)">RUL remaining</text>
          </g>
        </g>
      </svg>
    </div>
  )
}
