// three/AHUScene.tsx — React Three Fiber 3D AHU visualization
//
// Design philosophy: looks like a real commercial HVAC AHU unit.
//   - Painted steel sectioned enclosure (Carrier/Trane style)
//   - PBR materials (metalness + roughness) — no toy emissive colors
//   - Status indicator LEDs on each component (health → color), not whole-body tint
//   - Cylindrical fan housing with properly pitched blades
//   - Dense aluminium fin coil geometry
//   - Environment map ('warehouse') for industrial ambient reflections
//   - ContactShadows for ground depth
//   - OrbitControls with zoom enabled

import { useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import type { ThreeEvent } from '@react-three/fiber'
import { OrbitControls, Environment, ContactShadows } from '@react-three/drei'
import * as THREE from 'three'
import { useTwinStore } from '../stores/useTwinStore'
import type { OperatingState } from '../types'
import type { AHUVizProps } from '../components/AHUSchematic2D'

// ── Health → LED color (status indicator only) ────────────────────────────────

function ledColor(state: OperatingState | undefined, health: number): string {
  if (state === 'critical' || health < 0.4) return '#FF2A2A'
  if (state === 'warning'  || health < 0.7) return '#FF8C00'
  return '#00D46A'
}

// ── Shared material presets ────────────────────────────────────────────────────

const MAT = {
  steelDark:   { color: '#3E4A54', metalness: 0.72, roughness: 0.32 } as const,
  steelMid:    { color: '#4E5B66', metalness: 0.65, roughness: 0.38 } as const,
  steelLight:  { color: '#5C6A76', metalness: 0.60, roughness: 0.42 } as const,
  frameRail:   { color: '#2C3840', metalness: 0.80, roughness: 0.22 } as const,
  coilAlum:    { color: '#8A9EAA', metalness: 0.78, roughness: 0.28 } as const,
  coilCopper:  { color: '#9A7C62', metalness: 0.75, roughness: 0.32 } as const,
  filterMat:   { color: '#C8C0A8', metalness: 0.08, roughness: 0.88 } as const,
  damperBlade: { color: '#3A4850', metalness: 0.62, roughness: 0.38 } as const,
  fanBlade:    { color: '#5A6872', metalness: 0.70, roughness: 0.28 } as const,
  ductFlange:  { color: '#3A4550', metalness: 0.68, roughness: 0.35 } as const,
}

// ── Status LED indicator ───────────────────────────────────────────────────────

function StatusLED({ position, entityId }: {
  position: [number, number, number]
  entityId: string
}) {
  const { snapshot } = useTwinStore()
  const h = snapshot?.health[entityId]
  const color = ledColor(h?.state, h?.health ?? 1.0)
  const isHealthy = !h || h.state === 'normal'

  return (
    <group position={position}>
      {/* LED recess housing */}
      <mesh>
        <cylinderGeometry args={[0.028, 0.028, 0.012, 12]} />
        <meshStandardMaterial color="#1A2028" metalness={0.5} roughness={0.5} />
      </mesh>
      {/* LED bulb */}
      <mesh position={[0, 0.007, 0]}>
        <sphereGeometry args={[0.018, 10, 10]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={isHealthy ? 0.6 : 2.0}
          roughness={0.05}
          metalness={0}
        />
      </mesh>
    </group>
  )
}

// ── Fan assembly — cylindrical housing + swept blades ─────────────────────────

function FanAssembly({
  position,
  entityId,
  rpmSensorId,
  direction = 1,
}: {
  position: [number, number, number]
  entityId: string
  rpmSensorId?: string
  direction?: 1 | -1
}) {
  const bladeGroupRef = useRef<THREE.Group>(null)
  const { snapshot, selectedEntityId, setSelectedEntityId } = useTwinStore()
  const h = snapshot?.health[entityId]
  const health = h?.health ?? 1.0
  const isSelected = selectedEntityId === entityId

  // RPM-driven rotation
  const liveSensor = rpmSensorId ? snapshot?.sensors[rpmSensorId] : null
  const nominalRPM = 1450
  const rpmFraction = liveSensor
    ? Math.max(0.05, liveSensor.v / nominalRPM)
    : 0.3 + health * 0.7
  const rotSpeed = direction * rpmFraction * 4.5

  useFrame((_, delta) => {
    if (bladeGroupRef.current) bladeGroupRef.current.rotation.z += delta * rotSpeed
  })

  const bladeCount = 8
  const blades = useMemo(
    () => Array.from({ length: bladeCount }, (_, i) => (i / bladeCount) * Math.PI * 2),
    []
  )

  return (
    <group
      position={position}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        setSelectedEntityId(isSelected ? null : entityId)
      }}
    >
      {/* Cylindrical fan housing */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.34, 0.34, 0.08, 32, 1, true]} />
        <meshStandardMaterial {...MAT.steelDark} side={THREE.BackSide} />
      </mesh>
      {/* Housing ring front face */}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.34, 0.018, 8, 32]} />
        <meshStandardMaterial {...MAT.frameRail} />
      </mesh>
      {/* Housing ring back */}
      <mesh position={[0, 0, -0.08]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.34, 0.014, 8, 32]} />
        <meshStandardMaterial {...MAT.frameRail} />
      </mesh>

      {/* Motor housing (cylinder behind blades) */}
      <mesh position={[0, 0, -0.05]}>
        <cylinderGeometry args={[0.075, 0.09, 0.14, 16]} />
        <meshStandardMaterial {...MAT.steelMid} />
      </mesh>
      {/* Motor mounting struts */}
      {[0, Math.PI / 2, Math.PI, Math.PI * 1.5].map((angle, i) => (
        <mesh key={i}
          position={[Math.cos(angle) * 0.19, Math.sin(angle) * 0.19, -0.04]}
          rotation={[0, 0, angle]}
        >
          <boxGeometry args={[0.24, 0.012, 0.008]} />
          <meshStandardMaterial {...MAT.steelDark} />
        </mesh>
      ))}

      {/* Rotating blades */}
      <group ref={bladeGroupRef}>
        {blades.map((angle, i) => (
          <mesh
            key={i}
            position={[Math.cos(angle) * 0.22, Math.sin(angle) * 0.22, 0.005]}
            rotation={[0.32, 0, angle + Math.PI / 2]}   // 0.32 rad pitch ≈ 18° — realistic fan blade
          >
            <boxGeometry args={[0.22, 0.055, 0.008]} />
            <meshStandardMaterial {...MAT.fanBlade} />
          </mesh>
        ))}
        {/* Hub cap */}
        <mesh>
          <cylinderGeometry args={[0.07, 0.08, 0.04, 16]} />
          <meshStandardMaterial {...MAT.steelLight} />
        </mesh>
      </group>

      {/* Selection ring */}
      {isSelected && (
        <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0, 0.02]}>
          <torusGeometry args={[0.40, 0.012, 8, 48]} />
          <meshBasicMaterial color="#1E7FD4" transparent opacity={0.85} />
        </mesh>
      )}
    </group>
  )
}

// ── Coil assembly — dense aluminium fins + header pipes ───────────────────────

function CoilAssembly({
  position,
  size,
  entityId,
  isHeating = false,
}: {
  position: [number, number, number]
  size: [number, number, number]
  entityId: string
  isHeating?: boolean
}) {
  const { selectedEntityId, setSelectedEntityId } = useTwinStore()
  const isSelected = selectedEntityId === entityId
  const mat = isHeating ? MAT.coilCopper : MAT.coilAlum
  const finCount = 12
  const finSpacing = size[2] / finCount

  return (
    <group
      position={position}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        setSelectedEntityId(isSelected ? null : entityId)
      }}
    >
      {/* Fins — thin aluminium plates stacked along Z */}
      {Array.from({ length: finCount }, (_, i) => (
        <mesh key={i} position={[0, 0, -size[2] / 2 + i * finSpacing + finSpacing / 2]}>
          <boxGeometry args={[size[0] - 0.02, size[1] - 0.02, 0.004]} />
          <meshStandardMaterial {...mat} transparent opacity={0.82} />
        </mesh>
      ))}

      {/* Header pipes — horizontal tubes on left and right edges */}
      {[-size[0] / 2 + 0.025, size[0] / 2 - 0.025].map((x, i) => (
        <mesh key={i} position={[x, 0, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.022, 0.022, size[2], 10]} />
          <meshStandardMaterial {...mat} />
        </mesh>
      ))}

      {/* Frame border — very faint */}
      <mesh>
        <boxGeometry args={[size[0], size[1], size[2]]} />
        <meshStandardMaterial color="#2C3640" metalness={0.6} roughness={0.45} transparent opacity={0.06} />
      </mesh>

      {/* Selection — wireframe box clearly visible in open-frame scene */}
      {isSelected && (
        <mesh>
          <boxGeometry args={[size[0] + 0.04, size[1] + 0.04, size[2] + 0.04]} />
          <meshBasicMaterial color="#1E7FD4" wireframe />
        </mesh>
      )}
    </group>
  )
}

// ── Filter bank — frame with filter media visible ─────────────────────────────

function FilterBank({ position, entityId }: {
  position: [number, number, number]
  entityId: string
}) {
  const { selectedEntityId, setSelectedEntityId } = useTwinStore()
  const isSelected = selectedEntityId === entityId
  const w = 0.3, h = 0.68, d = 0.42

  return (
    <group
      position={position}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        setSelectedEntityId(isSelected ? null : entityId)
      }}
    >
      {/* Outer frame */}
      <mesh>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial color="#2A3540" metalness={0.55} roughness={0.45} />
      </mesh>
      {/* Filter media — off-white fibrous material inside frame */}
      <mesh>
        <boxGeometry args={[w - 0.018, h - 0.018, d - 0.018]} />
        <meshStandardMaterial {...MAT.filterMat} />
      </mesh>
      {/* Diagonal support grid lines (front face) */}
      {[-0.12, 0, 0.12].map((y, i) => (
        <mesh key={i} position={[0, y, d / 2 - 0.004]}>
          <boxGeometry args={[w - 0.02, 0.008, 0.004]} />
          <meshStandardMaterial color="#3A4850" metalness={0.5} roughness={0.4} />
        </mesh>
      ))}

      {/* Selection — wireframe */}
      {isSelected && (
        <mesh>
          <boxGeometry args={[w + 0.05, h + 0.05, d + 0.05]} />
          <meshBasicMaterial color="#1E7FD4" wireframe />
        </mesh>
      )}
    </group>
  )
}

// ── Damper — frame with actuator-driven blades ────────────────────────────────

function Damper({ position, entityId }: {
  position: [number, number, number]
  entityId: string
}) {
  const { selectedEntityId, setSelectedEntityId } = useTwinStore()
  const isSelected = selectedEntityId === entityId
  const w = 0.14, h = 0.68, d = 0.4

  return (
    <group
      position={position}
      onClick={(e: ThreeEvent<MouseEvent>) => {
        e.stopPropagation()
        setSelectedEntityId(isSelected ? null : entityId)
      }}
    >
      {/* Frame */}
      <mesh>
        <boxGeometry args={[w, h, d]} />
        <meshStandardMaterial {...MAT.steelDark} />
      </mesh>
      {/* Damper blades — 4 horizontal blades */}
      {[-0.22, -0.08, 0.08, 0.22].map((y, i) => (
        <mesh key={i} position={[0, y, 0]} rotation={[0.18, 0, 0]}>
          <boxGeometry args={[w - 0.01, 0.04, d - 0.01]} />
          <meshStandardMaterial {...MAT.damperBlade} />
        </mesh>
      ))}
      {/* Actuator box on top */}
      <mesh position={[0, h / 2 + 0.04, 0]}>
        <boxGeometry args={[0.06, 0.06, 0.06]} />
        <meshStandardMaterial color="#2A3540" metalness={0.6} roughness={0.4} />
      </mesh>

      {/* Selection — wireframe */}
      {isSelected && (
        <mesh>
          <boxGeometry args={[w + 0.07, h + 0.07, d + 0.07]} />
          <meshBasicMaterial color="#1E7FD4" wireframe />
        </mesh>
      )}
    </group>
  )
}

// ── AHU enclosure — open structural skeleton (no body panels) ─────────────────
// Removing solid walls so all internal components are visible.
// Only structural rails, corner posts, duct flanges, and base legs remain.

function AHUHousing() {
  return (
    <>
      {/* ── Top rail ── */}
      <mesh position={[0.09, 0.44, 0]}>
        <boxGeometry args={[2.88, 0.030, 0.52]} />
        <meshStandardMaterial {...MAT.frameRail} />
      </mesh>

      {/* ── Bottom rail ── */}
      <mesh position={[0.09, -0.44, 0]}>
        <boxGeometry args={[2.88, 0.030, 0.52]} />
        <meshStandardMaterial {...MAT.frameRail} />
      </mesh>

      {/* ── Front horizontal rails (face-level) ── */}
      <mesh position={[0.09, 0.44, 0.27]}>
        <boxGeometry args={[2.88, 0.022, 0.014]} />
        <meshStandardMaterial {...MAT.steelDark} />
      </mesh>
      <mesh position={[0.09, -0.44, 0.27]}>
        <boxGeometry args={[2.88, 0.022, 0.014]} />
        <meshStandardMaterial {...MAT.steelDark} />
      </mesh>

      {/* ── Vertical corner posts ── */}
      {[-1.25, -0.65, 0.62, 1.42].map((x, i) => (
        <mesh key={i} position={[x, 0, 0]}>
          <boxGeometry args={[0.026, 0.90, 0.52]} />
          <meshStandardMaterial {...MAT.frameRail} />
        </mesh>
      ))}

      {/* ── Section divider posts (front edge only) ── */}
      {[-0.65, 0.62].map((x, i) => (
        <mesh key={i} position={[x, 0, 0.27]}>
          <boxGeometry args={[0.018, 0.90, 0.014]} />
          <meshStandardMaterial {...MAT.steelDark} />
        </mesh>
      ))}

      {/* ── Inlet duct flange (left) ── */}
      <mesh position={[-1.52, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.22, 0.22, 0.06, 20, 1, true]} />
        <meshStandardMaterial {...MAT.ductFlange} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[-1.55, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[0.22, 0.013, 8, 20]} />
        <meshStandardMaterial {...MAT.ductFlange} />
      </mesh>

      {/* ── Outlet duct flange (right) ── */}
      <mesh position={[1.68, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.22, 0.22, 0.06, 20, 1, true]} />
        <meshStandardMaterial {...MAT.ductFlange} side={THREE.DoubleSide} />
      </mesh>
      <mesh position={[1.71, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <torusGeometry args={[0.22, 0.013, 8, 20]} />
        <meshStandardMaterial {...MAT.ductFlange} />
      </mesh>

      {/* ── Base legs ── */}
      {[-0.9, 0.9].map((x, i) => (
        <group key={i} position={[x, -0.52, 0]}>
          <mesh position={[0, -0.07, 0]}>
            <boxGeometry args={[0.13, 0.14, 0.44]} />
            <meshStandardMaterial {...MAT.frameRail} />
          </mesh>
          {/* Foot pad */}
          <mesh position={[0, -0.155, 0]}>
            <boxGeometry args={[0.20, 0.022, 0.50]} />
            <meshStandardMaterial color="#1E2830" metalness={0.6} roughness={0.5} />
          </mesh>
        </group>
      ))}

      {/* ── Unit label on bottom front rail ── */}
      <mesh position={[0.09, -0.44, 0.28]}>
        <boxGeometry args={[0.28, 0.046, 0.003]} />
        <meshStandardMaterial color="#1A2830" metalness={0.3} roughness={0.7} />
      </mesh>
    </>
  )
}

// ── Status indicator panel (LEDs across top front edge) ───────────────────────

function StatusPanel() {
  const components = [
    { id: 'ahu-01.supplyFan',   x: -0.95 },
    { id: 'ahu-01.filterBank',  x: -0.28 },
    { id: 'ahu-01.coolingCoil', x:  0.08 },
    { id: 'ahu-01.heatingCoil', x:  0.42 },
    { id: 'ahu-01.damper',      x:  0.72 },
    { id: 'ahu-01.returnFan',   x:  1.12 },
  ]
  return (
    <>
      {components.map((c) => (
        <StatusLED key={c.id} position={[c.x, 0.39, 0.27]} entityId={c.id} />
      ))}
    </>
  )
}

// ── Full model ─────────────────────────────────────────────────────────────────

function AHUModel() {
  return (
    <group>
      <AHUHousing />
      <StatusPanel />

      {/* Supply Fan — left */}
      <FanAssembly
        position={[-0.94, 0, 0]}
        entityId="ahu-01.supplyFan"
        rpmSensorId="ahu-01.supplyFan.speed"
        direction={1}
      />

      {/* Filter Bank */}
      <FilterBank position={[-0.28, 0, 0]} entityId="ahu-01.filterBank" />

      {/* Cooling Coil */}
      <CoilAssembly
        position={[0.08, 0, 0]}
        size={[0.28, 0.68, 0.44]}
        entityId="ahu-01.coolingCoil"
        isHeating={false}
      />

      {/* Heating Coil */}
      <CoilAssembly
        position={[0.42, 0, 0]}
        size={[0.22, 0.68, 0.44]}
        entityId="ahu-01.heatingCoil"
        isHeating
      />

      {/* Damper */}
      <Damper position={[0.73, 0, 0]} entityId="ahu-01.damper" />

      {/* Return Fan — right */}
      <FanAssembly
        position={[1.12, 0, 0]}
        entityId="ahu-01.returnFan"
        rpmSensorId="ahu-01.returnFan.speed"
        direction={-1}
      />
    </group>
  )
}

// ── Selection spotlight —────────────────────────────────────────────
// Warm point light above the selected component — "spotlit" effect.

const ENTITY_POS: Record<string, [number, number, number]> = {
  'ahu-01.supplyFan':   [-0.94, 0, 0],
  'ahu-01.filterBank':  [-0.28, 0, 0],
  'ahu-01.coolingCoil': [ 0.08, 0, 0],
  'ahu-01.heatingCoil': [ 0.42, 0, 0],
  'ahu-01.damper':      [ 0.73, 0, 0],
  'ahu-01.returnFan':   [ 1.12, 0, 0],
}

function SelectionHighlight() {
  const { selectedEntityId } = useTwinStore()
  if (!selectedEntityId) return null
  const p = ENTITY_POS[selectedEntityId]
  if (!p) return null
  return (
    <pointLight
      position={[p[0], p[1] + 0.9, p[2] + 0.85]}
      intensity={3.5}
      distance={1.8}
      color="#FFE8B0"
    />
  )
}

// ── Canvas ─────────────────────────────────────────────────────────────────

export default function AHUScene({ onToggleView }: AHUVizProps) {
  const { snapshot } = useTwinStore()
  const ahuH = snapshot?.health['ahu-01']
  const health = ahuH?.health ?? 1
  const state  = ahuH?.state
  const pct    = Math.round(health * 100)
  const hColor = state === 'critical' || health < 0.4 ? 'var(--color-red)'
               : state === 'warning'  || health < 0.7 ? 'var(--color-amber)'
               : 'var(--color-green)'
  const hDim   = state === 'critical' || health < 0.4 ? 'var(--color-red-dim)'
               : state === 'warning'  || health < 0.7 ? 'var(--color-amber-dim)'
               : 'var(--color-green-dim)'

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>

      {/* ── Header — same style as AHUSchematic2D ── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '7px 10px 5px', gap: 10, flexShrink: 0,
        borderBottom: '1px solid var(--color-border)',
      }}>
        {/* 2D / 3D toggle pill */}
        <div style={{
          display: 'flex', gap: 2,
          background: 'var(--color-surface2)',
          border: '1px solid var(--color-border)',
          borderRadius: 6, padding: 2, flexShrink: 0,
        }}>
          {(['2D', '3D'] as const).map(label => {
            const active = label === '3D'   // this component is always 3D
            return (
              <button key={label}
                onClick={() => { if (label === '2D') onToggleView() }}
                style={{
                  padding: '2px 10px', fontSize: 10, fontWeight: 700,
                  fontFamily: 'var(--font-sans)', border: 'none', borderRadius: 4,
                  cursor: label === '2D' ? 'pointer' : 'default',
                  letterSpacing: '0.04em', transition: 'all 150ms ease',
                  background: active ? 'var(--color-blue)' : 'transparent',
                  color: active ? '#fff' : 'var(--color-text-mute)',
                }}
              >{label}</button>
            )
          })}
        </div>

        <span style={{
          flex: 1, fontSize: 10, fontWeight: 700,
          textTransform: 'uppercase', letterSpacing: '0.08em',
          color: 'var(--color-text-mute)',
        }}>AHU-01 3D View</span>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <span style={{ fontSize: 10, color: 'var(--color-text-mute)' }}>System</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: hColor }}>{pct}%</span>
          <span style={{
            fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
            padding: '1px 6px', borderRadius: 3,
            background: hDim, color: hColor,
          }}>{state ?? 'normal'}</span>
        </div>
      </div>

      {/* ── Canvas fills remaining height ── */}
      <div style={{ flex: 1, minHeight: 0 }}>

      <Canvas
        camera={{ position: [0.1, 0.9, 2.6], fov: 44 }}
        style={{ background: 'transparent', width: '100%', height: '100%' }}
        shadows
      >
      {/* Environment map — gives proper PBR ambient and reflections */}
      <Environment preset="warehouse" />

      {/* Minimal directional fill — environment handles most of it */}
      <ambientLight intensity={0.15} />
      <directionalLight
        position={[3, 5, 3]}
        intensity={0.6}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
        shadow-camera-near={0.5}
        shadow-camera-far={20}
        shadow-camera-left={-4}
        shadow-camera-right={4}
        shadow-camera-top={3}
        shadow-camera-bottom={-3}
      />
      {/* Cool back light for depth separation */}
      <directionalLight position={[-3, 1, -3]} intensity={0.18} color="#A0C4E0" />

        <AHUModel />
        <SelectionHighlight />

        {/* Ground shadow */}
        <ContactShadows
          position={[0, -0.62, 0]}
          opacity={0.38}
          scale={6}
          blur={2.2}
          far={1.5}
          color="#000820"
        />

        <OrbitControls
          enablePan={false}
          enableZoom
          minZoom={0.5}
          maxZoom={2}
          minDistance={1.4}
          maxDistance={5.0}
          autoRotate
          autoRotateSpeed={0.45}
          minPolarAngle={Math.PI / 6}
          maxPolarAngle={Math.PI / 2.1}
        />
      </Canvas>
      </div>
    </div>
  )
}
