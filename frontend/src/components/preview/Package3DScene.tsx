/**
 * 3D-Szene eines Footprints (three.js über @react-three/fiber) – wird von <Package3D> **lazy** geladen, damit three.js
 * nicht im Start-Bundle landet. Offline: keine HDR-/CDN-Dateien; Reflexionen kommen aus einer prozedural erzeugten
 * Raumumgebung (RoomEnvironment), dazu Umgebungs-, Halbkugel- und gerichtetes Licht und ContactShadows.
 *
 * Koordinaten: Footprint (x, y, z) in mm → three.js (x, z, −y); die Platinenoberseite liegt bei y = 0.
 */
import { ContactShadows, OrbitControls } from '@react-three/drei'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { useEffect, useId, useImperativeHandle, useMemo, useRef, useState, type KeyboardEvent, type Ref, type RefObject } from 'react'
import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { cn } from '@/lib/cn'
import {
  boxAdd,
  boxHeight,
  boxWidth,
  emptyBox,
  footprintBBox,
  formatMm,
  isEmptyBox,
  padLayer,
  padOutline,
  type Arc,
  type Body3D,
  type Box,
  type FootprintSpec,
  type Pad,
  type Point,
} from '@/lib/geometry'
import { CanvasBadge, CanvasKeyHint } from './CanvasChrome'
import type { CanvasHandle } from './types'

export interface Package3DSceneProps {
  spec: FootprintSpec
  autoRotate?: boolean
  onAutoRotateChange?: (on: boolean) => void
  /** Leiterplatte mit Pads und Bestückungsdruck zeigen */
  showBoard?: boolean
  showInfo?: boolean
  className?: string
  'aria-label'?: string
  /** WebGL-Kontext verloren (Treiber) → Rückfall anzeigen */
  onContextLost?: () => void
  ref?: Ref<CanvasHandle>
}

// --------------------------------------------------------------------------- Geometrie-Helfer

const COPPER_THICKNESS = 0.035
const SILK_THICKNESS = 0.015

function rotatePoints(pts: Point[], deg: number, dx: number, dy: number): Point[] {
  const r = (deg * Math.PI) / 180
  const c = Math.cos(r)
  const s = Math.sin(r)
  return pts.map((p) => ({ x: dx + p.x * c - p.y * s, y: dy + p.x * s + p.y * c }))
}

function shapeFrom(pts: Point[]): THREE.Shape {
  const shape = new THREE.Shape()
  pts.forEach((p, i) => (i === 0 ? shape.moveTo(p.x, p.y) : shape.lineTo(p.x, p.y)))
  shape.closePath()
  return shape
}

/** Bohrung (rund oder Langloch) als Pfad in Footprint-Koordinaten */
function holePath(pad: Pad): THREE.Path | null {
  if (!pad.hole) return null
  const r = pad.hole / 2
  const len = pad.hole_length ?? pad.hole
  const path = new THREE.Path()
  if (len <= pad.hole + 1e-9) {
    path.absarc(pad.x, pad.y, r, 0, Math.PI * 2, true)
    return path
  }
  const rot = (((pad.hole_rotation ?? ((pad.rotation ?? 0) + (pad.width >= pad.height ? 0 : 90))) * Math.PI) / 180) as number
  const half = len / 2 - r
  const ux = Math.cos(rot)
  const uy = Math.sin(rot)
  const ax = pad.x - ux * half
  const ay = pad.y - uy * half
  const bx = pad.x + ux * half
  const by = pad.y + uy * half
  path.absarc(bx, by, r, rot - Math.PI / 2, rot + Math.PI / 2, false)
  path.absarc(ax, ay, r, rot + Math.PI / 2, rot + (3 * Math.PI) / 2, false)
  path.closePath()
  return path
}

/** Linie mit runden Enden als Fläche (Bestückungsdruck) */
function strokeShape(x1: number, y1: number, x2: number, y2: number, width: number): THREE.Shape {
  const r = width / 2
  const a = Math.atan2(y2 - y1, x2 - x1)
  const shape = new THREE.Shape()
  shape.absarc(x2, y2, r, a - Math.PI / 2, a + Math.PI / 2, false)
  shape.absarc(x1, y1, r, a + Math.PI / 2, a + (3 * Math.PI) / 2, false)
  shape.closePath()
  return shape
}

function arcShape(a: Arc): THREE.Shape {
  const span = ((((a.end ?? 360) - (a.start ?? 0)) % 360) + 360) % 360 || 360
  if (span >= 359.999 && a.width >= 2 * a.r - 1e-9) {
    const s = new THREE.Shape()
    s.absarc(a.cx, a.cy, a.r + a.width / 2, 0, Math.PI * 2, false)
    return s
  }
  const outer = a.r + a.width / 2
  const inner = Math.max(0, a.r - a.width / 2)
  const start = ((a.start ?? 0) * Math.PI) / 180
  const end = start + (span * Math.PI) / 180
  const s = new THREE.Shape()
  if (span >= 359.999) {
    s.absarc(a.cx, a.cy, outer, 0, Math.PI * 2, false)
    const hole = new THREE.Path()
    hole.absarc(a.cx, a.cy, inner, 0, Math.PI * 2, true)
    s.holes.push(hole)
    return s
  }
  s.absarc(a.cx, a.cy, outer, start, end, false)
  s.absarc(a.cx, a.cy, inner, end, start, true)
  s.closePath()
  return s
}

/** Geometrie in der XY-Ebene extrudieren und in die three.js-Lage (Y oben) drehen */
function extrude(shapes: THREE.Shape | THREE.Shape[], depth: number, bevel = 0, curveSegments = 10): THREE.BufferGeometry {
  const geo = new THREE.ExtrudeGeometry(shapes, {
    depth: Math.max(depth - bevel * 2, 1e-4),
    bevelEnabled: bevel > 0,
    bevelThickness: bevel,
    bevelSize: bevel,
    bevelOffset: -bevel,
    bevelSegments: 2,
    curveSegments,
  })
  geo.rotateX(-Math.PI / 2)
  if (bevel > 0) geo.translate(0, bevel, 0)
  return geo
}

function isMetal(color: string): boolean {
  const c = new THREE.Color(color)
  const hsl = { h: 0, s: 0, l: 0 }
  c.getHSL(hsl)
  return hsl.l > 0.62 && hsl.s < 0.25
}

interface BoardModel {
  box: Box
  thickness: number
  board: THREE.BufferGeometry
  padsTop: THREE.BufferGeometry | null
  padsBottom: THREE.BufferGeometry | null
  barrels: THREE.BufferGeometry | null
  silk: THREE.BufferGeometry | null
  bodies: { body: Body3D; geometry: THREE.BufferGeometry; position: [number, number, number]; metal: boolean }[]
  /** Kugel der Szene (Kamera einpassen) */
  center: THREE.Vector3
  radius: number
  height: number
  size: Box
}

function buildModel(spec: FootprintSpec, withBoard: boolean): BoardModel {
  const content = footprintBBox(spec, { bodies: true })
  const box = isEmptyBox(content) ? { x1: -1, y1: -1, x2: 1, y2: 1 } : content
  const w = boxWidth(box)
  const d = boxHeight(box)
  const margin = Math.max(1.0, Math.max(w, d) * 0.14)
  // dünne Platine: die Leiterplatte soll Bühne sein, nicht Hauptdarsteller
  const thickness = Math.min(1.6, Math.max(0.22, Math.max(w, d) * 0.09))
  const pads = spec.pads ?? []

  // Leiterplatte mit Bohrungen
  const bx1 = box.x1 - margin
  const by1 = box.y1 - margin
  const bx2 = box.x2 + margin
  const by2 = box.y2 + margin
  const cr = Math.min(0.8, (bx2 - bx1) * 0.06)
  const boardShape = new THREE.Shape()
  boardShape.moveTo(bx1 + cr, by1)
  boardShape.lineTo(bx2 - cr, by1)
  boardShape.absarc(bx2 - cr, by1 + cr, cr, -Math.PI / 2, 0, false)
  boardShape.lineTo(bx2, by2 - cr)
  boardShape.absarc(bx2 - cr, by2 - cr, cr, 0, Math.PI / 2, false)
  boardShape.lineTo(bx1 + cr, by2)
  boardShape.absarc(bx1 + cr, by2 - cr, cr, Math.PI / 2, Math.PI, false)
  boardShape.lineTo(bx1, by1 + cr)
  boardShape.absarc(bx1 + cr, by1 + cr, cr, Math.PI, (3 * Math.PI) / 2, false)
  for (const p of pads) {
    const h = holePath(p)
    if (h) boardShape.holes.push(h)
  }
  const board = extrude(boardShape, thickness, 0, 16)
  board.translate(0, -thickness, 0)

  // Kupfer-Pads (vergoldet), THT oben + unten + Hülse
  const top: THREE.BufferGeometry[] = []
  const bottom: THREE.BufferGeometry[] = []
  const barrels: THREE.BufferGeometry[] = []
  const cu = Math.max(COPPER_THICKNESS, Math.max(w, d) * 0.0035)
  for (const p of pads) {
    const outline = rotatePoints(padOutline(p, 8), p.rotation ?? 0, p.x, p.y)
    const shape = shapeFrom(outline)
    const hole = holePath(p)
    if (hole) shape.holes.push(hole)
    const layer = padLayer(p)
    if (layer === 'multi_layer' && p.plated === false) continue
    if (layer !== 'bottom_copper') top.push(extrude(shape, cu, 0, 12))
    if (layer !== 'top_copper') {
      const g = extrude(shape, cu, 0, 12)
      g.translate(0, -thickness - cu, 0)
      bottom.push(g)
    }
    if (layer === 'multi_layer' && p.hole && (p.hole_length ?? p.hole) <= p.hole + 1e-9) {
      const barrel = new THREE.CylinderGeometry(p.hole / 2, p.hole / 2, thickness, 24, 1, true)
      barrel.translate(p.x, -thickness / 2, -p.y)
      barrels.push(barrel)
    }
  }

  // Bestückungsdruck oben
  const silk: THREE.BufferGeometry[] = []
  for (const t of spec.tracks ?? []) {
    if (t.layer !== 'top_silk') continue
    if (Math.hypot(t.x2 - t.x1, t.y2 - t.y1) < 1e-6) continue
    silk.push(extrude(strokeShape(t.x1, t.y1, t.x2, t.y2, t.width), SILK_THICKNESS, 0, 6))
  }
  for (const a of spec.arcs ?? []) {
    if (a.layer !== 'top_silk') continue
    silk.push(extrude(arcShape(a), SILK_THICKNESS, 0, 24))
  }

  // 3D-Körper
  const bodies: BoardModel['bodies'] = []
  let height = 0
  const all = emptyBox()
  boxAdd(all, bx1, by1)
  boxAdd(all, bx2, by2)
  for (const body of spec.bodies ?? []) {
    if (body.outline.length < 3) continue
    const h = Math.max(body.z_top - body.z_bottom, 0.01)
    height = Math.max(height, body.z_top)
    const xs = body.outline.map((p) => p.x)
    const ys = body.outline.map((p) => p.y)
    const bw = Math.max(...xs) - Math.min(...xs)
    const bd = Math.max(...ys) - Math.min(...ys)
    const metal = isMetal(body.color ?? '#2B2B2B')
    if (/^ball/i.test(body.name ?? '')) {
      // BGA-Kugeln als (abgeflachte) Kugeln statt Prismen
      const cx = (Math.max(...xs) + Math.min(...xs)) / 2
      const cy = (Math.max(...ys) + Math.min(...ys)) / 2
      const geo = new THREE.SphereGeometry(0.5, 18, 12)
      geo.scale(bw, h, bd)
      bodies.push({ body, geometry: geo, position: [cx, body.z_bottom + h / 2, -cy], metal: true })
      continue
    }
    const bevel = Math.min(bw, bd) > 0.8 && h > 0.25 ? Math.min(0.06, h * 0.08, Math.min(bw, bd) * 0.05) : 0
    const geo = extrude(shapeFrom(body.outline), h, bevel, 24)
    bodies.push({ body, geometry: geo, position: [0, body.z_bottom, 0], metal })
  }

  const merge = (list: THREE.BufferGeometry[]) => {
    if (!list.length) return null
    const merged = mergeGeometries(list.map((g) => (g.index ? g.toNonIndexed() : g)), false)
    list.forEach((g) => g.dispose())
    return merged
  }

  const topY = Math.max(height, cu)
  const bottomY = withBoard ? -thickness : 0
  const center = new THREE.Vector3((all.x1 + all.x2) / 2, (topY + bottomY) / 2, -(all.y1 + all.y2) / 2)
  const radius = Math.hypot(boxWidth(all) / 2, boxHeight(all) / 2, (topY - bottomY) / 2)
  return {
    box: all,
    thickness,
    board,
    padsTop: merge(top),
    padsBottom: merge(bottom),
    barrels: merge(barrels),
    silk: merge(silk),
    bodies,
    center,
    radius,
    height,
    size: box,
  }
}

function disposeModel(m: BoardModel) {
  m.board.dispose()
  m.padsTop?.dispose()
  m.padsBottom?.dispose()
  m.barrels?.dispose()
  m.silk?.dispose()
  m.bodies.forEach((b) => b.geometry.dispose())
}

// --------------------------------------------------------------------------- Szene

function RoomEnvironmentMap() {
  const get = useThree((s) => s.get)
  useEffect(() => {
    const { gl, scene, invalidate } = get()
    const pmrem = new THREE.PMREMGenerator(gl)
    const room = new RoomEnvironment()
    const env = pmrem.fromScene(room, 0.04).texture
    scene.environment = env
    scene.environmentIntensity = 0.42
    invalidate()
    return () => {
      scene.environment = null
      env.dispose()
      room.dispose()
      pmrem.dispose()
    }
  }, [get])
  return null
}

interface RigApi {
  reset: (animate: boolean) => void
}

/** Kamera einpassen (schräg von vorn rechts oben) und auf Wunsch weich dorthin fahren */
function CameraRig({ model, rigRef }: { model: BoardModel; rigRef: RefObject<RigApi | null> }) {
  const get = useThree((s) => s.get)
  const fov = useThree((s) => (s.camera as THREE.PerspectiveCamera).fov)
  const hasControls = useThree((s) => Boolean(s.controls))
  const size = useThree((s) => s.size)
  const anim = useRef<{ from: THREE.Vector3; to: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; t0: number } | null>(null)

  const target = useMemo(() => {
    const vfov = ((fov || 30) * Math.PI) / 180
    const aspect = size.width / Math.max(size.height, 1)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect)
    const dist = (model.radius / Math.sin(Math.min(vfov, hfov) / 2)) * 1.02
    const az = (32 * Math.PI) / 180
    const el = (34 * Math.PI) / 180
    const dir = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el))
    return { position: model.center.clone().addScaledVector(dir, dist), target: model.center.clone(), dist }
  }, [fov, model, size.width, size.height])

  const apply = (animate: boolean) => {
    const { camera: cam, controls: ctl, invalidate } = get()
    const camera = cam as THREE.PerspectiveCamera
    const controls = ctl as unknown as OrbitControlsImpl | null
    if (!controls) return
    camera.near = Math.max(target.dist / 200, 0.01)
    camera.far = target.dist * 50
    camera.updateProjectionMatrix()
    controls.minDistance = target.dist * 0.12
    controls.maxDistance = target.dist * 5
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    if (!animate || reduce) {
      camera.position.copy(target.position)
      controls.target.copy(target.target)
      controls.update()
      invalidate()
      return
    }
    anim.current = {
      from: camera.position.clone(),
      to: target.position.clone(),
      fromT: controls.target.clone(),
      toT: target.target.clone(),
      t0: performance.now(),
    }
    invalidate()
  }

  // Neues Modell / neue Größe → einpassen (ohne Animation)
  const applyRef = useRef(apply)
  useEffect(() => {
    applyRef.current = apply
  })
  useEffect(() => {
    applyRef.current(false)
  }, [target, hasControls])

  useImperativeHandle(rigRef, () => ({ reset: (animate: boolean) => applyRef.current(animate) }), [])

  useFrame((state) => {
    const a = anim.current
    const controls = state.controls as unknown as OrbitControlsImpl | null
    const camera = state.camera
    if (!a || !controls) return
    const t = Math.min(1, (performance.now() - a.t0) / 520)
    const k = 1 - (1 - t) ** 3
    camera.position.lerpVectors(a.from, a.to, k)
    controls.target.lerpVectors(a.fromT, a.toT, k)
    controls.update()
    if (t >= 1) anim.current = null
    state.invalidate()
  })
  return null
}

function SceneContent({
  model,
  showBoard,
  autoRotate,
  controlsRef,
  rigRef,
}: {
  model: BoardModel
  showBoard: boolean
  autoRotate: boolean
  controlsRef: RefObject<OrbitControlsImpl | null>
  rigRef: RefObject<RigApi | null>
}) {
  const materials = useMemo(
    () => ({
      mask: new THREE.MeshPhysicalMaterial({ color: '#0C3022', roughness: 0.55, metalness: 0.02, clearcoat: 0.28, clearcoatRoughness: 0.45 }),
      core: new THREE.MeshStandardMaterial({ color: '#5F5A43', roughness: 0.92, metalness: 0 }),
      gold: new THREE.MeshStandardMaterial({ color: '#D9AE62', roughness: 0.26, metalness: 1 }),
      barrel: new THREE.MeshStandardMaterial({ color: '#C8964F', roughness: 0.35, metalness: 1, side: THREE.DoubleSide }),
      silk: new THREE.MeshStandardMaterial({ color: '#EEF1F5', roughness: 0.65, metalness: 0 }),
    }),
    [],
  )
  useEffect(() => () => Object.values(materials).forEach((m) => m.dispose()), [materials])

  const bodyMaterials = useMemo(
    () =>
      model.bodies.map(({ body, metal }) =>
        metal
          ? new THREE.MeshStandardMaterial({
              color: body.color ?? '#C9CDD2',
              roughness: 0.38,
              metalness: 0.85,
              transparent: (body.opacity ?? 1) < 1,
              opacity: body.opacity ?? 1,
            })
          : new THREE.MeshPhysicalMaterial({
              color: body.color ?? '#2B2B2B',
              roughness: 0.58,
              metalness: 0.02,
              clearcoat: 0.12,
              transparent: (body.opacity ?? 1) < 1,
              opacity: body.opacity ?? 1,
            }),
      ),
    [model],
  )
  useEffect(() => () => bodyMaterials.forEach((m) => m.dispose()), [bodyMaterials])

  const extent = Math.max(boxWidth(model.box), boxHeight(model.box))
  const lightDist = model.radius * 3
  return (
    <>
      <RoomEnvironmentMap />
      <ambientLight intensity={0.22} />
      <hemisphereLight args={['#E8EEFF', '#2A1A10', 0.55]} />
      <directionalLight
        position={[lightDist * 0.55, lightDist * 1.1, lightDist * 0.75]}
        intensity={2.3}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-radius={3}
        shadow-bias={-0.0002}
        shadow-normalBias={0.02}
        shadow-camera-left={-extent}
        shadow-camera-right={extent}
        shadow-camera-top={extent}
        shadow-camera-bottom={-extent}
        shadow-camera-near={0.1}
        shadow-camera-far={lightDist * 4}
      />
      {/* kühles Gegenlicht + warme „Glut“ von links vorn */}
      <directionalLight position={[-lightDist, lightDist * 0.5, -lightDist]} intensity={0.85} color="#9FB8FF" />
      <directionalLight position={[-lightDist * 0.8, lightDist * 0.25, lightDist * 0.6]} intensity={0.45} color="#FFB27A" />

      {showBoard && (
        <group>
          <mesh geometry={model.board} material={[materials.mask, materials.core]} receiveShadow dispose={null} />
          {model.padsTop && <mesh geometry={model.padsTop} material={materials.gold} receiveShadow dispose={null} />}
          {model.padsBottom && <mesh geometry={model.padsBottom} material={materials.gold} dispose={null} />}
          {model.barrels && <mesh geometry={model.barrels} material={materials.barrel} dispose={null} />}
          {model.silk && <mesh geometry={model.silk} material={materials.silk} receiveShadow dispose={null} />}
        </group>
      )}
      <group>
        {model.bodies.map((b, i) => (
          <mesh
            key={i}
            geometry={b.geometry}
            material={bodyMaterials[i]}
            position={b.position}
            castShadow
            receiveShadow
            dispose={null}
          />
        ))}
      </group>
      <ContactShadows
        key={`${model.radius.toFixed(3)}-${showBoard}`}
        position={[model.center.x, (showBoard ? -model.thickness : 0) - 0.02, model.center.z]}
        scale={extent * 2.6}
        blur={2.6}
        opacity={0.55}
        far={Math.max(model.radius * 1.5, 1)}
        resolution={512}
        frames={1}
        color="#000000"
      />
      <OrbitControls
        ref={controlsRef}
        makeDefault
        enableDamping
        dampingFactor={0.09}
        rotateSpeed={0.75}
        zoomSpeed={0.9}
        autoRotate={autoRotate}
        autoRotateSpeed={1.4}
      />
      <CameraRig model={model} rigRef={rigRef} />
    </>
  )
}

// --------------------------------------------------------------------------- Komponente

export default function Package3DScene({
  spec,
  autoRotate = false,
  onAutoRotateChange,
  showBoard = true,
  showInfo = true,
  className,
  'aria-label': ariaLabel,
  onContextLost,
  ref,
}: Package3DSceneProps) {
  const uid = useId().replace(/:/g, '')
  const model = useMemo(() => buildModel(spec, showBoard), [spec, showBoard])
  useEffect(() => () => disposeModel(model), [model])
  const controlsRef = useRef<OrbitControlsImpl | null>(null)
  const rigRef = useRef<RigApi | null>(null)
  const [ready, setReady] = useState(false)

  /** Näher heran (factor > 1) bzw. weiter weg – OrbitControls.dollyIn(s) multipliziert den Abstand mit s */
  const dolly = (factor: number) => {
    const c = controlsRef.current
    if (!c || factor <= 0) return
    if (factor > 1) c.dollyIn(1 / factor)
    else c.dollyOut(factor)
    c.update()
  }

  useImperativeHandle(
    ref,
    () => ({
      fit: () => rigRef.current?.reset(true),
      zoomIn: () => dolly(1.25),
      zoomOut: () => dolly(1 / 1.25),
    }),
    [],
  )

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const c = controlsRef.current
    if (!c || e.altKey || e.ctrlKey || e.metaKey) return
    const step = (e.shiftKey ? 30 : 10) * (Math.PI / 180)
    let handled = true
    switch (e.key) {
      case 'ArrowLeft':
        c.setAzimuthalAngle(c.getAzimuthalAngle() - step)
        break
      case 'ArrowRight':
        c.setAzimuthalAngle(c.getAzimuthalAngle() + step)
        break
      case 'ArrowUp':
        c.setPolarAngle(Math.max(0.05, c.getPolarAngle() - step))
        break
      case 'ArrowDown':
        c.setPolarAngle(Math.min(Math.PI - 0.05, c.getPolarAngle() + step))
        break
      case '+':
      case '=':
        dolly(1.25)
        break
      case '-':
      case '_':
        dolly(1 / 1.25)
        break
      case '0':
      case 'r':
      case 'R':
        rigRef.current?.reset(true)
        break
      case ' ':
        onAutoRotateChange?.(!autoRotate)
        break
      default:
        handled = false
    }
    if (handled) {
      e.preventDefault()
      c.update()
    }
  }

  const size = model.size
  const label = ariaLabel ?? `3D-Ansicht ${spec.name}`
  return (
    // Leinwand-Widget mit eigener Tastatursteuerung (Drehen, Zoomen, Zurücksetzen) – role="application"
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="application"
      aria-roledescription="3D-Ansicht"
      aria-label={label}
      aria-describedby={`${uid}-help`}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      onKeyDown={onKeyDown}
      className={cn(
        'group/canvas relative isolate min-h-0 overflow-hidden outline-none',
        'bg-[radial-gradient(120%_90%_at_50%_35%,#121a26_0%,#080b10_55%,#05070a_100%)]',
        'focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset',
        className,
      )}
    >
      <Canvas
        className={cn('transition-opacity duration-500', ready ? 'opacity-100' : 'opacity-0')}
        frameloop="demand"
        shadows="percentage"
        dpr={[1, 2]}
        camera={{ fov: 30, position: [6, 5, 8], near: 0.01, far: 2000 }}
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance', preserveDrawingBuffer: false }}
        onCreated={(state) => {
          state.gl.toneMapping = THREE.ACESFilmicToneMapping
          state.gl.toneMappingExposure = 1.05
          state.gl.domElement.addEventListener('webglcontextlost', (ev) => {
            ev.preventDefault()
            onContextLost?.()
          })
          requestAnimationFrame(() => setReady(true))
        }}
      >
        <SceneContent model={model} showBoard={showBoard} autoRotate={autoRotate} controlsRef={controlsRef} rigRef={rigRef} />
      </Canvas>

      {showInfo && (
        <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[calc(100%-1.5rem)] items-center gap-2">
          <CanvasBadge tone="board">
            <span className="mono truncate font-medium text-[#EEF2F8]">{spec.name}</span>
            <span className="text-[#9AA4B6]">
              {formatMm(boxWidth(size))} × {formatMm(boxHeight(size))} × {formatMm(model.height)} mm
            </span>
          </CanvasBadge>
        </div>
      )}
      <CanvasKeyHint tone="board">Pfeiltasten drehen · +/− zoomen · 0 zurücksetzen · Leertaste dreht automatisch</CanvasKeyHint>
      <p id={`${uid}-help`} className="sr-only">
        {(spec.bodies ?? []).length} 3D-Körper, Höhe {formatMm(model.height)} Millimeter. Ziehen dreht, Mausrad zoomt,
        rechte Maustaste verschiebt. Pfeiltasten drehen, Plus und Minus zoomen, 0 setzt die Ansicht zurück, die Leertaste
        schaltet die automatische Drehung um.
      </p>
    </div>
  )
}
