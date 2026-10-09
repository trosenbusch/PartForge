/**
 * Zoom und Verschieben für die 2D-Vorschauen (Symbol in mil, Footprint in mm).
 *
 * Bildschirm = Welt · scale + t, mit gespiegelter Y-Achse: sx = x·s + tx, sy = −y·s + ty.
 * - Mausrad zoomt am Mauszeiger (nicht-passiver Listener, damit die Seite nicht scrollt)
 * - Ziehen (linke oder mittlere Taste) verschiebt; erst ab 3 px Bewegung – Klicks auf Pins/Pads bleiben Klicks
 * - Doppelklick, „0“ oder „F“ passen ein; „+“/„−“ zoomen; Pfeiltasten verschieben (⇧ = weiter)
 * - Solange niemand zoomt/verschiebt, wird bei Größen- oder Inhaltsänderung automatisch eingepasst.
 *   Ein neuer `resetKey` (z. B. anderes Bauteil) setzt das zurück.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'
import { isEmptyBox, type Box, type Point } from '@/lib/geometry'

export interface ViewState {
  /** Pixel je Welteinheit */
  scale: number
  tx: number
  ty: number
}

export interface PanZoomOptions {
  /** Inhalt in Weltkoordinaten (Y nach oben); null = noch nichts zu zeigen */
  bbox: Box | null
  width: number
  height: number
  /** Rand beim Einpassen (px) */
  padding?: number
  /** Zusätzlich freizuhaltende Ränder (px), z. B. für Overlays oben/unten */
  insets?: Partial<Insets>
  /** Zoomgrenzen relativ zur eingepassten Ansicht */
  minZoom?: number
  maxZoom?: number
  /** Höchstmaßstab beim Einpassen (px je Einheit) – winzige Inhalte nicht riesig aufblasen */
  maxFitScale?: number
  /** Neuer Wert → Ansicht wieder automatisch einpassen (z. B. anderes Bauteil) */
  resetKey?: unknown
  enabled?: boolean
}

export interface PanZoom {
  view: ViewState
  /** Maßstab der eingepassten Ansicht */
  fitScale: number
  /** Zoom relativ zur eingepassten Ansicht (1 = 100 %) */
  zoom: number
  /** Nutzer hat gezoomt/verschoben (kein automatisches Einpassen mehr) */
  interacted: boolean
  panning: boolean
  fit: (animate?: boolean) => void
  zoomBy: (factor: number, anchor?: Point, animate?: boolean) => void
  panBy: (dx: number, dy: number) => void
  toWorld: (sx: number, sy: number) => Point
  toScreen: (x: number, y: number) => Point
  /** Auf das Interaktionselement legen */
  handlers: {
    onPointerDown: (e: PointerEvent<HTMLElement>) => void
    onPointerMove: (e: PointerEvent<HTMLElement>) => void
    onPointerUp: (e: PointerEvent<HTMLElement>) => void
    onPointerCancel: (e: PointerEvent<HTMLElement>) => void
    onDoubleClick: () => void
  }
  /** Tastatur (Pfeile, +/−, 0/F) – gibt true zurück, wenn die Taste verarbeitet wurde */
  handleKey: (e: KeyboardEvent<HTMLElement>) => boolean
  /** Ref-Callback für den nicht-passiven Mausrad-Listener */
  wheelRef: (el: HTMLElement | null) => void
  /** true direkt nach einem Ziehvorgang (Klick danach ignorieren) – mit `event.timeStamp` aufrufen */
  wasDrag: (timeStamp: number) => boolean
}

export interface Insets {
  top: number
  right: number
  bottom: number
  left: number
}

const NO_INSETS: Insets = { top: 0, right: 0, bottom: 0, left: 0 }

const DRAG_THRESHOLD = 3
const easeOut = (t: number) => 1 - (1 - t) ** 3

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
}

function computeFit(
  bbox: Box | null,
  width: number,
  height: number,
  padding: number,
  maxFitScale: number,
  insets: Insets,
): ViewState {
  // Insets nur nutzen, wenn danach genug Fläche bleibt (sehr kleine Leinwände: Overlays dürfen überlappen)
  const useInsets = width - insets.left - insets.right > 160 && height - insets.top - insets.bottom > 120
  const ins = useInsets ? insets : NO_INSETS
  const areaX = ins.left
  const areaY = ins.top
  const areaW = width - ins.left - ins.right
  const areaH = height - ins.top - ins.bottom
  if (!bbox || isEmptyBox(bbox) || width <= 0 || height <= 0) {
    return { scale: 1, tx: areaX + areaW / 2, ty: areaY + areaH / 2 }
  }
  const bw = Math.max(bbox.x2 - bbox.x1, 1e-6)
  const bh = Math.max(bbox.y2 - bbox.y1, 1e-6)
  const availW = Math.max(areaW - padding * 2, 24)
  const availH = Math.max(areaH - padding * 2, 24)
  const scale = Math.min(availW / bw, availH / bh, maxFitScale)
  const cx = (bbox.x1 + bbox.x2) / 2
  const cy = (bbox.y1 + bbox.y2) / 2
  return { scale, tx: areaX + areaW / 2 - cx * scale, ty: areaY + areaH / 2 + cy * scale }
}

export function usePanZoom({
  bbox,
  width,
  height,
  padding = 32,
  insets,
  minZoom = 0.2,
  maxZoom = 40,
  maxFitScale = Infinity,
  resetKey,
  enabled = true,
}: PanZoomOptions): PanZoom {
  // bbox als Wert vergleichen (neue Objekte mit gleichem Inhalt lösen kein erneutes Einpassen aus)
  const bx1 = bbox?.x1
  const by1 = bbox?.y1
  const bx2 = bbox?.x2
  const by2 = bbox?.y2
  const insTop = insets?.top ?? 0
  const insRight = insets?.right ?? 0
  const insBottom = insets?.bottom ?? 0
  const insLeft = insets?.left ?? 0
  const fitView = useMemo(
    () =>
      computeFit(
        bx1 === undefined || by1 === undefined || bx2 === undefined || by2 === undefined
          ? null
          : { x1: bx1, y1: by1, x2: bx2, y2: by2 },
        width,
        height,
        padding,
        maxFitScale,
        { top: insTop, right: insRight, bottom: insBottom, left: insLeft },
      ),
    [bx1, by1, bx2, by2, width, height, padding, maxFitScale, insTop, insRight, insBottom, insLeft],
  )
  // Ansicht des Nutzers; null = automatisch eingepasst (folgt Größe und Inhalt)
  const [userView, setUserView] = useState<ViewState | null>(null)
  const [panning, setPanning] = useState(false)
  // Neuer Inhalt (resetKey) → wieder automatisch einpassen (Anpassung während des Renderns, React-Muster)
  const [prevKey, setPrevKey] = useState(resetKey)
  if (prevKey !== resetKey) {
    setPrevKey(resetKey)
    setUserView(null)
  }
  const view = userView ?? fitView
  const interacted = userView !== null

  // Aktuelle Werte für Ereignisse zwischen zwei Renderdurchläufen (Mausrad, Ziehen, Animation)
  const viewRef = useRef(view)
  const fitRef = useRef(fitView)
  useLayoutEffect(() => {
    viewRef.current = view
    fitRef.current = fitView
  })
  const animRef = useRef(0)
  const dragRef = useRef<{ id: number; x: number; y: number; view: ViewState; active: boolean } | null>(null)
  const lastDragEnd = useRef(0)

  const setView = useCallback((next: ViewState | null) => {
    viewRef.current = next ?? fitRef.current
    setUserView(next)
  }, [])

  const stopAnim = () => cancelAnimationFrame(animRef.current)
  useLayoutEffect(() => stopAnim(), [resetKey])
  useEffect(() => () => stopAnim(), [])

  /** Weich zur Zielansicht; `end` = Zustand danach (null = wieder automatisch einpassen) */
  const animateTo = useCallback(
    (target: ViewState, animate: boolean, end: ViewState | null = target) => {
      stopAnim()
      const from = viewRef.current
      if (!animate || prefersReducedMotion()) {
        setView(end)
        return
      }
      const start = performance.now()
      const duration = 220
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / duration)
        if (t >= 1) {
          setView(end)
          return
        }
        const k = easeOut(t)
        // Maßstab logarithmisch interpolieren (gleichmäßiges Zoomgefühl), Bildmitte gleitet
        const scale = Math.exp(Math.log(from.scale) + (Math.log(target.scale) - Math.log(from.scale)) * k)
        const cx0 = (width / 2 - from.tx) / from.scale
        const cy0 = (height / 2 - from.ty) / from.scale
        const cx1 = (width / 2 - target.tx) / target.scale
        const cy1 = (height / 2 - target.ty) / target.scale
        const cx = cx0 + (cx1 - cx0) * k
        const cy = cy0 + (cy1 - cy0) * k
        setView({ scale, tx: width / 2 - cx * scale, ty: height / 2 - cy * scale })
        animRef.current = requestAnimationFrame(step)
      }
      animRef.current = requestAnimationFrame(step)
    },
    [setView, width, height],
  )

  const clampScale = useCallback(
    (scale: number) => {
      const lo = fitView.scale * minZoom
      const hi = fitView.scale * maxZoom
      return Math.min(hi, Math.max(lo, scale))
    },
    [fitView.scale, minZoom, maxZoom],
  )

  const zoomBy = useCallback(
    (factor: number, anchor?: Point, animate = false) => {
      const v = viewRef.current
      const scale = clampScale(v.scale * factor)
      if (scale === v.scale) return
      const ax = anchor?.x ?? width / 2
      const ay = anchor?.y ?? height / 2
      const wx = (ax - v.tx) / v.scale
      const wy = (ay - v.ty) / v.scale
      animateTo({ scale, tx: ax - wx * scale, ty: ay - wy * scale }, animate)
    },
    [animateTo, clampScale, width, height],
  )

  const panBy = useCallback(
    (dx: number, dy: number) => {
      stopAnim()
      const v = viewRef.current
      setView({ ...v, tx: v.tx + dx, ty: v.ty + dy })
    },
    [setView],
  )

  const fit = useCallback((animate = true) => animateTo(fitRef.current, animate, null), [animateTo])

  // ------------------------------------------------------------------ Mausrad (nicht passiv)
  const wheelNode = useRef<HTMLElement | null>(null)
  const zoomByRef = useRef(zoomBy)
  useEffect(() => {
    zoomByRef.current = zoomBy
  })
  const onWheel = useCallback(
    (e: WheelEvent) => {
      if (!enabled) return
      e.preventDefault()
      const el = wheelNode.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? rect.height : 1
      const delta = e.deltaY * unit
      // Strg + Rad bzw. Pinch auf dem Touchpad: feiner, aber stärker gewichtet
      const factor = Math.exp(-delta * (e.ctrlKey ? 0.008 : 0.0016))
      zoomByRef.current(factor, { x: e.clientX - rect.left, y: e.clientY - rect.top })
    },
    [enabled],
  )
  const wheelRef = useCallback(
    (el: HTMLElement | null) => {
      if (wheelNode.current) wheelNode.current.removeEventListener('wheel', onWheel)
      wheelNode.current = el
      if (el) el.addEventListener('wheel', onWheel, { passive: false })
    },
    [onWheel],
  )

  // ------------------------------------------------------------------ Ziehen
  const handlers = useMemo(
    () => ({
      onPointerDown: (e: PointerEvent<HTMLElement>) => {
        if (!enabled) return
        if (e.button !== 0 && e.button !== 1) return
        if (e.button === 1) e.preventDefault() // kein Autoscroll mit der mittleren Taste
        cancelAnimationFrame(animRef.current)
        dragRef.current = { id: e.pointerId, x: e.clientX, y: e.clientY, view: viewRef.current, active: false }
      },
      onPointerMove: (e: PointerEvent<HTMLElement>) => {
        const d = dragRef.current
        if (!d || d.id !== e.pointerId) return
        const dx = e.clientX - d.x
        const dy = e.clientY - d.y
        if (!d.active) {
          if (Math.hypot(dx, dy) < DRAG_THRESHOLD) return
          d.active = true
          setPanning(true)
          try {
            e.currentTarget.setPointerCapture(e.pointerId)
          } catch {
            // Zeiger schon weg – egal
          }
        }
        setView({ ...d.view, tx: d.view.tx + dx, ty: d.view.ty + dy })
      },
      onPointerUp: (e: PointerEvent<HTMLElement>) => {
        const d = dragRef.current
        if (!d || d.id !== e.pointerId) return
        if (d.active) {
          lastDragEnd.current = e.timeStamp
          try {
            e.currentTarget.releasePointerCapture(e.pointerId)
          } catch {
            // ignorieren
          }
        }
        dragRef.current = null
        setPanning(false)
      },
      onPointerCancel: () => {
        dragRef.current = null
        setPanning(false)
      },
      onDoubleClick: () => {
        if (enabled) fit(true)
      },
    }),
    [enabled, fit, setView],
  )

  const handleKey = useCallback(
    (e: KeyboardEvent<HTMLElement>): boolean => {
      if (!enabled || e.altKey || e.ctrlKey || e.metaKey) return false
      const step = e.shiftKey ? 160 : 40
      switch (e.key) {
        case 'ArrowLeft':
          panBy(step, 0)
          return true
        case 'ArrowRight':
          panBy(-step, 0)
          return true
        case 'ArrowUp':
          panBy(0, step)
          return true
        case 'ArrowDown':
          panBy(0, -step)
          return true
        case '+':
        case '=':
          zoomBy(1.4, undefined, true)
          return true
        case '-':
        case '_':
          zoomBy(1 / 1.4, undefined, true)
          return true
        case '0':
        case 'f':
        case 'F':
          fit(true)
          return true
        default:
          return false
      }
    },
    [enabled, fit, panBy, zoomBy],
  )

  // Umrechnung mit der gerenderten Ansicht (für Overlays im Render) …
  const toScreen = (x: number, y: number): Point => ({ x: x * view.scale + view.tx, y: -y * view.scale + view.ty })
  // … bzw. mit der neuesten Ansicht (für Ereignisse)
  const toWorld = useCallback((sx: number, sy: number): Point => {
    const v = viewRef.current
    return { x: (sx - v.tx) / v.scale, y: -(sy - v.ty) / v.scale }
  }, [])

  const wasDrag = useCallback((timeStamp: number) => timeStamp - lastDragEnd.current < 250, [])

  return {
    view,
    fitScale: fitView.scale,
    zoom: fitView.scale > 0 ? view.scale / fitView.scale : 1,
    interacted,
    panning,
    fit,
    zoomBy,
    panBy,
    toWorld,
    toScreen,
    handlers,
    handleKey,
    wheelRef,
    wasDrag,
  }
}

/** Maßstab in Stufen (≈ 19 %), damit Strichbreiten nicht bei jedem Mausrad-Schritt neu berechnet werden */
export function scaleBucket(scale: number): number {
  return 2 ** (Math.round(Math.log2(Math.max(scale, 1e-9)) * 4) / 4)
}

/** Passender Rasterabstand: kleinster Wert aus `steps`, der mindestens `minPx` Pixel breit ist */
export function gridStep(scale: number, steps: number[], minPx: number): number {
  for (const s of steps) if (s * scale >= minPx) return s
  return steps[steps.length - 1]
}
