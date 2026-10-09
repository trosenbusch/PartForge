/**
 * Live-Vorschau des **ungespeicherten** Hausstils.
 *
 * Die Generator-Vorschauen (`/api/footprints/preview`, `/api/symbols/preview`) rechnen mit dem gespeicherten
 * Hausstil. Was sich exakt per Anfrage übergeben lässt, geht als Parameter mit (Dichte, F, P, Rundung,
 * Kupferabstand, Courtyard-Raster). Rein grafische Werte (Linienbreiten, Eckenradius, Pin‑1‑Punkt, Mittelkreuz,
 * Texthöhe, 3D, Symbolfarben, IC-Pinlänge) setzt diese Datei auf das Ergebnis – genau so, wie der Generator sie
 * verwendet (`partforge/footprints/builder.py`, `partforge/symbols/style.py`). Der Rest wird nach dem Speichern
 * exakt angezeigt; `pendingFootprintKeys`/`pendingSymbolKeys` nennen diese Einstellungen.
 *
 * Sobald das Backend `style` in der Anfrage berücksichtigt (Wunsch an das Backend; `usePreviews.ts` sendet ihn dann
 * mit), meldet es das über `calc.style` bzw. `spec.generator.style` – dann entfällt die Nachbildung automatisch.
 */
import type { FootprintStyle, SymbolStyle } from '@/api/system'
import type { FootprintSpec, SymbolSpec } from '@/lib/geometry'

const EPS = 1e-6
const near = (a: number, b: number) => Math.abs(a - b) < EPS
const roundDown = (v: number, step: number) => Math.floor(v / step + 1e-9) * step
const roundTo = (v: number, step: number) => Math.round(v / step) * step
const CROSS_WIDTH = 0.1

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

// --------------------------------------------------------------------------- Footprints

/** Werte, die als Anfrage-Parameter exakt in die Vorschau gehen */
export function footprintParamOverrides(saved: FootprintStyle, draft: FootprintStyle): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  if (draft.fab_tolerance !== saved.fab_tolerance) out.fab_tolerance = draft.fab_tolerance
  if (draft.placement_tolerance !== saved.placement_tolerance) out.placement_tolerance = draft.placement_tolerance
  if (draft.rounding !== saved.rounding) out.rounding = draft.rounding
  if (draft.min_copper_gap !== saved.min_copper_gap) out.min_copper_gap = draft.min_copper_gap
  if (draft.courtyard_grid !== saved.courtyard_grid) out.courtyard_grid = draft.courtyard_grid
  return out
}

/** Einstellungen, die erst nach dem Speichern exakt in der Vorschau erscheinen */
export const FOOTPRINT_PENDING: (keyof FootprintStyle)[] = ['silk_pad_clearance', 'exposed_pad_designator']

export function pendingFootprintKeys(saved: FootprintStyle, draft: FootprintStyle, honored: boolean): (keyof FootprintStyle)[] {
  if (honored) return []
  const keys = FOOTPRINT_PENDING.filter((k) => draft[k] !== saved[k])
  if (draft.generate_3d && !saved.generate_3d) keys.push('generate_3d')
  return keys
}

/** Hat das Backend den mitgesendeten Stil verwendet? (`calc.style`, sobald unterstützt) */
export function footprintStyleHonored(calc: unknown, draft: FootprintStyle): boolean {
  const style = (calc as { style?: unknown } | null | undefined)?.style
  return style !== undefined && same(style, draft)
}

interface CourtyardCalc {
  courtyard?: { width?: number; height?: number }
}

/**
 * Grafische Hausstil-Werte auf eine Footprint-Vorschau anwenden.
 * `silk` = welche Bestückungsdruck-Breite der Generator für dieses Gehäuse nutzt (Chips: „small“).
 */
export function applyFootprintStyle(
  spec: FootprintSpec,
  saved: FootprintStyle,
  draft: FootprintStyle,
  opts: { silk: 'small' | 'regular'; calc?: unknown },
): FootprintSpec {
  if (same(saved, draft)) return spec
  const savedSilk = opts.silk === 'small' ? saved.silk_width_small : saved.silk_width
  const draftSilk = opts.silk === 'small' ? draft.silk_width_small : draft.silk_width
  const isCross = (t: { x1: number; y1: number; x2: number; y2: number; width: number }) =>
    near(t.width, CROSS_WIDTH) &&
    ((near(t.y1, 0) && near(t.y2, 0) && near(t.x1, -t.x2)) || (near(t.x1, 0) && near(t.x2, 0) && near(t.y1, -t.y2)))

  const pads = (spec.pads ?? []).map((p) =>
    p.shape === 'roundrect' && p.corner_radius_pct !== draft.pad_corner_radius_pct
      ? { ...p, corner_radius_pct: draft.pad_corner_radius_pct }
      : p,
  )

  let tracks = (spec.tracks ?? []).map((t) => {
    if (t.layer === 'top_silk' && near(t.width, savedSilk)) return { ...t, width: draftSilk }
    if ((t.layer === 'assembly' || t.layer === 'component_outline') && near(t.width, saved.assembly_width)) return { ...t, width: draft.assembly_width }
    if (t.layer === 'courtyard' && near(t.width, saved.courtyard_width) && !isCross(t)) return { ...t, width: draft.courtyard_width }
    return t
  })
  // Mittelkreuz im Courtyard (das Kreuz auf „Bauteilmitte“ zeichnet der Generator immer)
  if (saved.center_cross && !draft.center_cross) {
    tracks = tracks.filter((t) => !(t.layer === 'courtyard' && isCross(t)))
  } else if (!saved.center_cross && draft.center_cross) {
    const ref = tracks.find((t) => t.layer === 'component_center' && near(t.y1, 0) && near(t.y2, 0))
    const half = ref ? Math.abs(ref.x2) : 0.5
    tracks = [
      ...tracks,
      { layer: 'courtyard', x1: -half, y1: 0, x2: half, y2: 0, width: CROSS_WIDTH },
      { layer: 'courtyard', x1: 0, y1: -half, x2: 0, y2: half, width: CROSS_WIDTH },
    ]
  }

  const arcs = (spec.arcs ?? []).map((a) => {
    if (a.layer !== 'top_silk') {
      if ((a.layer === 'assembly' || a.layer === 'component_outline') && near(a.width, saved.assembly_width)) return { ...a, width: draft.assembly_width }
      return a
    }
    const full = near(((a.end - a.start) % 360 + 360) % 360, 0) && !near(a.end, a.start)
    // Pin-1-Punkt: Vollkreis mit Breite 2r (gefüllte Scheibe)
    if (full && near(a.width, 2 * a.r) && near(a.r, saved.pin1_dot_radius)) {
      return { ...a, r: draft.pin1_dot_radius, width: 2 * draft.pin1_dot_radius }
    }
    return near(a.width, savedSilk) ? { ...a, width: draftSilk } : a
  })

  // Texthöhe wie FootprintBuilder.add_texts: min(Hausstil, max(0,3, 0,6 × kürzere Courtyard-Seite))
  const cy = (opts.calc as CourtyardCalc | undefined)?.courtyard
  const short = cy?.width && cy?.height ? Math.min(cy.width, cy.height) : null
  const texts = (spec.texts ?? []).map((t) => {
    if (t.layer !== 'designator' && t.layer !== 'comment') return t
    const h = short !== null ? Math.min(draft.text_height, Math.max(0.3, roundDown(0.6 * short, 0.05))) : (t.height * draft.text_height) / saved.text_height
    return { ...t, height: h, stroke: Math.max(0.05, roundTo(0.15 * h, 0.01)) }
  })

  return {
    ...spec,
    pads,
    tracks,
    arcs,
    texts,
    bodies: draft.generate_3d ? spec.bodies : [],
  }
}

// --------------------------------------------------------------------------- Symbole

/** Symbol-Hausstil, wie ihn das Backend in `SymbolSpec.generator.style` festhält */
const GENERATOR_KEYS = ['grid', 'ic_pin_length', 'discrete_pin_length', 'line_width', 'font', 'font_size', 'diode_pin1', 'resistor_style'] as const

export function symbolStyleHonored(spec: SymbolSpec | null | undefined, draft: SymbolStyle): boolean {
  const style = (spec?.generator as { style?: Record<string, unknown> } | null | undefined)?.style
  if (!style) return false
  return GENERATOR_KEYS.every((k) => style[k] === undefined || style[k] === draft[k])
}

/** Einstellungen, die erst nach dem Speichern exakt in der Symbolvorschau erscheinen */
export function pendingSymbolKeys(saved: SymbolStyle, draft: SymbolStyle, honored: boolean): (keyof SymbolStyle)[] {
  if (honored) return []
  const keys: (keyof SymbolStyle)[] = ['grid', 'discrete_pin_length', 'font', 'font_size', 'resistor_style']
  return keys.filter((k) => draft[k] !== saved[k])
}

const upper = (c: string | null | undefined) => (c ?? '').toUpperCase()

/** Farben, Linienbreite (diskret) und IC-Pinlänge des Entwurfs auf eine Symbolvorschau anwenden */
export function applySymbolStyle(spec: SymbolSpec, saved: SymbolStyle, draft: SymbolStyle, opts: { ic: boolean }): SymbolSpec {
  if (same(saved, draft)) return spec
  const map = (c: string | null | undefined): string | null | undefined => {
    const u = upper(c)
    if (!u) return c
    if (u === upper(saved.ic_line_color)) return draft.ic_line_color
    if (u === upper(saved.ic_fill_color)) return draft.ic_fill_color
    if (u === upper(saved.discrete_line_color)) return draft.discrete_line_color
    return c
  }
  const graphics = (spec.graphics ?? []).map((g) => {
    const discrete = upper(g.color) === upper(saved.discrete_line_color)
    return {
      ...g,
      color: map(g.color),
      fill_color: map(g.fill_color),
      line_width: discrete && g.line_width === saved.line_width ? draft.line_width : g.line_width,
    }
  }) as SymbolSpec['graphics']

  let pins = spec.pins
  if (opts.ic && draft.grid === saved.grid) {
    const grid = saved.grid || 100
    const savedLen = Math.min(1000, Math.max(grid, Math.round(saved.ic_pin_length / grid) * grid))
    const draftLen = Math.min(1000, Math.max(grid, Math.round(draft.ic_pin_length / grid) * grid))
    if (savedLen !== draftLen) pins = (spec.pins ?? []).map((p) => (p.length === savedLen ? { ...p, length: draftLen } : p))
  }
  return { ...spec, graphics, pins }
}
