import { t as tr } from '@/components/preview/i18n'
/**
 * Bemaßung für die Footprint-Vorschau: aus dem Rechenprotokoll des Generators (IPC-7351: Zmax, Gmin, Xmax,
 * Raster) bzw. – ohne Protokoll – aus den Pads abgeleitet. Ergebnis sind abstrakte Maßketten in mm; der Abstand zur
 * Kontur (in Pixeln) bestimmt erst die Leinwand.
 *
 * Maßlinien liegen immer **außerhalb der Kontur** aus Pads, Bestückungsdruck, Courtyard und Bestückungszeichnung –
 * Beschriftungen kreuzen so nie Linien des Footprints; die Hilfslinien führen von den Padkanten nach außen.
 */
import {
  boxAddBox,
  footprintBBox,
  formatMm,
  isEmptyBox,
  naturalCompare,
  padExtent,
  padLayer,
  type Box,
  type CanvasLayer,
  type FootprintCalc,
  type FootprintSpec,
  type LandCalc,
  type Pad,
} from '@/lib/geometry'

export interface DimensionLine {
  /** h = misst entlang X (waagerechte Maßlinie), v = entlang Y */
  orient: 'h' | 'v'
  /** Anfang/Ende entlang der gemessenen Achse (mm) */
  a: number
  b: number
  /** Kante des Objekts quer zur Maßlinie (mm) – Hilfslinien beginnen hier */
  edgeA: number
  edgeB: number
  /** Seite, auf die die Maßlinie versetzt wird: +1 = oben/rechts, −1 = unten/links */
  side: 1 | -1
  /** Bezugskante (mm), von der aus versetzt wird (äußerste Kontur auf dieser Seite) */
  base: number
  /** Staffelung (0 = nah an der Kontur) */
  level: number
  /** Kurzbeschriftung, z. B. „Z 6,90“ */
  label: string
  /** Langtext (Tooltip, Screenreader) */
  title: string
}

export interface DimensionCallout {
  /** Zielpunkt (mm) */
  x: number
  y: number
  label: string
  title: string
}

export interface FootprintDimensions {
  lines: DimensionLine[]
  callouts: DimensionCallout[]
  /** Kontur (mm), außerhalb der Maßlinien und Hinweise liegen: Pads + Bestückungsdruck + Courtyard + Bestückung */
  contour: Box | null
}

/** Lagen, deren Linien die Bemaßung nicht kreuzen soll (zusätzlich zu den Pads) */
const CONTOUR_LAYERS: CanvasLayer[] = [
  'top_copper',
  'bottom_copper',
  'multi_layer',
  'top_silk',
  'bottom_silk',
  'courtyard',
  'assembly',
]

/** Äußere Kontur des Footprints (mm) – Bezugskante der Maßlinien */
export function footprintContour(spec: FootprintSpec, calc: FootprintCalc | null): Box | null {
  const b = footprintBBox(spec, { layers: CONTOUR_LAYERS, bodies: false })
  if (calc?.courtyard) boxAddBox(b, calc.courtyard)
  return isEmptyBox(b) ? null : b
}

const EPS = 0.02

function smdPads(spec: FootprintSpec): Pad[] {
  return (spec.pads ?? []).filter((p) => padLayer(p) !== 'multi_layer' && !p.thermal)
}

function sortByDesignator(pads: Pad[]): Pad[] {
  return [...pads].sort((a, b) => naturalCompare(a.designator, b.designator))
}

/** Pads einer Anschlussreihe (Land) anhand des Mittenabstands */
function landPads(pads: Pad[], land: LandCalc): Pad[] {
  const center = land.pad_center
  const coord = (p: Pad) => (land.axis === 'x' ? p.x : p.y)
  if (center !== undefined) {
    const hit = pads.filter((p) => Math.abs(Math.abs(coord(p)) - center) < EPS + 0.001)
    if (hit.length) return hit
  }
  return pads
}

/** Kleinster positiver Abstand benachbarter Werte */
function minStep(values: number[]): number | null {
  const v = [...new Set(values.map((x) => Math.round(x * 1000) / 1000))].sort((a, b) => a - b)
  let best: number | null = null
  for (let i = 1; i < v.length; i++) {
    const d = v[i] - v[i - 1]
    if (d > 0.01 && (best === null || d < best)) best = d
  }
  return best
}

interface Extents {
  top: number
  bottom: number
  left: number
  right: number
}

function extents(pads: Pad[]): Extents {
  let top = -Infinity
  let bottom = Infinity
  let left = Infinity
  let right = -Infinity
  for (const p of pads) {
    const { ex, ey } = padExtent(p)
    top = Math.max(top, p.y + ey)
    bottom = Math.min(bottom, p.y - ey)
    left = Math.min(left, p.x - ex)
    right = Math.max(right, p.x + ex)
  }
  return { top, bottom, left, right }
}

const mm = (v: number) => formatMm(v, 2)

/** Rasterabstand innerhalb einer Reihe (Pads mit gleicher Quer-Koordinate) */
function rowPitch(pads: Pad[], along: 'x' | 'y'): { pitch: number; first: Pad; second: Pad } | null {
  if (pads.length < 2) return null
  const across = along === 'x' ? 'y' : 'x'
  // Reihe von Pin 1 (bzw. dem ersten Pad)
  const first = sortByDesignator(pads)[0]
  const row = pads.filter((p) => Math.abs(p[across] - first[across]) < EPS)
  if (row.length < 2) return null
  const sorted = [...row].sort((a, b) => a[along] - b[along])
  const pitch = minStep(sorted.map((p) => p[along]))
  if (pitch === null) return null
  // Nachbar von Pad 1 im Rasterabstand
  const second = sorted.find((p) => p !== first && Math.abs(Math.abs(p[along] - first[along]) - pitch) < EPS) ?? sorted[1]
  return { pitch, first, second }
}

/**
 * Maßketten für einen Footprint. Mit Rechenprotokoll (Generator) werden Zmax/Gmin/Xmax übernommen,
 * sonst aus den Pads bestimmt (Spannweite, Innenabstand, Raster).
 */
export function footprintDimensions(spec: FootprintSpec, calc: FootprintCalc | null): FootprintDimensions {
  const lines: DimensionLine[] = []
  const callouts: DimensionCallout[] = []
  const all = spec.pads ?? []
  if (!all.length) return { lines, callouts, contour: null }
  const padExt = extents(all)
  const contour = footprintContour(spec, calc)
  // Bezugskanten der Maßlinien: äußerste Kontur je Seite (nie auf Bestückungsdruck oder Courtyard)
  const ext: Extents = contour
    ? {
        top: Math.max(padExt.top, contour.y2),
        bottom: Math.min(padExt.bottom, contour.y1),
        left: Math.min(padExt.left, contour.x1),
        right: Math.max(padExt.right, contour.x2),
      }
    : padExt
  const smd = smdPads(spec)

  const lands = calc?.lands ?? []
  const xLand = lands.find((l) => l.axis === 'x')
  const yLand = lands.find((l) => l.axis === 'y')

  if (xLand) {
    const pads = landPads(smd, xLand)
    const e = extents(pads.length ? pads : all)
    lines.push({
      orient: 'h',
      a: -xLand.z / 2,
      b: xLand.z / 2,
      edgeA: e.top,
      edgeB: e.top,
      side: 1,
      base: ext.top,
      level: xLand.g > 0.01 ? 1 : 0,
      label: `Z ${mm(xLand.z)}`,
      title: tr("Zmax {value0} mm – Außenmaß über die Pads", { value0: String(mm(xLand.z)) }),
    })
    if (xLand.g > 0.01) {
      lines.push({
        orient: 'h',
        a: -xLand.g / 2,
        b: xLand.g / 2,
        edgeA: e.top,
        edgeB: e.top,
        side: 1,
        base: ext.top,
        level: 0,
        label: `G ${mm(xLand.g)}`,
        title: tr("Gmin {value0} mm – Innenabstand der Pads", { value0: String(mm(xLand.g)) }),
      })
    }
    // Padbreite (Xmax) rechts am obersten Pad der rechten Reihe
    const right = pads.filter((p) => p.x > 0).sort((a, b) => b.y - a.y)[0] ?? pads[0]
    if (right && !yLand) {
      lines.push({
        orient: 'v',
        a: right.y - xLand.x / 2,
        b: right.y + xLand.x / 2,
        edgeA: right.x + padExtent(right).ex,
        edgeB: right.x + padExtent(right).ex,
        side: 1,
        base: ext.right,
        level: 0,
        label: `X ${mm(xLand.x)}`,
        title: tr("Xmax {value0} mm – Padbreite", { value0: String(mm(xLand.x)) }),
      })
    }
    const pitch = rowPitch(pads, 'y')
    if (pitch) {
      lines.push({
        orient: 'v',
        a: Math.min(pitch.first.y, pitch.second.y),
        b: Math.max(pitch.first.y, pitch.second.y),
        edgeA: pitch.first.x - padExtent(pitch.first).ex,
        edgeB: pitch.second.x - padExtent(pitch.second).ex,
        side: -1,
        base: ext.left,
        level: 0,
        label: `e ${mm(pitch.pitch)}`,
        title: tr("Raster {value0} mm", { value0: String(mm(pitch.pitch)) }),
      })
    }
  }

  if (yLand) {
    const pads = landPads(smd, yLand)
    const e = extents(pads.length ? pads : all)
    lines.push({
      orient: 'v',
      a: -yLand.z / 2,
      b: yLand.z / 2,
      edgeA: e.right,
      edgeB: e.right,
      side: 1,
      base: ext.right,
      level: yLand.g > 0.01 ? 1 : 0,
      label: `Z ${mm(yLand.z)}`,
      title: tr("Zmax {value0} mm – Außenmaß über die Pads", { value0: String(mm(yLand.z)) }),
    })
    if (yLand.g > 0.01) {
      lines.push({
        orient: 'v',
        a: -yLand.g / 2,
        b: yLand.g / 2,
        edgeA: e.right,
        edgeB: e.right,
        side: 1,
        base: ext.right,
        level: 0,
        label: `G ${mm(yLand.g)}`,
        title: tr("Gmin {value0} mm – Innenabstand der Pads", { value0: String(mm(yLand.g)) }),
      })
    }
    if (!xLand) {
      const pitch = rowPitch(pads, 'x')
      if (pitch) {
        lines.push({
          orient: 'h',
          a: Math.min(pitch.first.x, pitch.second.x),
          b: Math.max(pitch.first.x, pitch.second.x),
          edgeA: pitch.first.y - padExtent(pitch.first).ey,
          edgeB: pitch.second.y - padExtent(pitch.second).ey,
          side: -1,
          base: ext.bottom,
          level: 0,
          label: `e ${mm(pitch.pitch)}`,
          title: tr("Raster {value0} mm", { value0: String(mm(pitch.pitch)) }),
        })
      }
    }
  }

  if (xLand && yLand) {
    // Padmaß als Hinweis an Pad 1 (zwei Achsen → keine weitere Maßkette)
    const p1 = sortByDesignator(landPads(smd, xLand))[0]
    if (p1) {
      callouts.push({
        x: p1.x - padExtent(p1).ex,
        y: p1.y + padExtent(p1).ey,
        label: `${mm(Math.max(p1.width, p1.height))} × ${mm(Math.min(p1.width, p1.height))}`,
        title: `Pad ${p1.designator}: ${mm(p1.width)} × ${mm(p1.height)} mm`,
      })
    }
  }

  // Durchsteckmontage: Raster + Bohrung/Pad
  const tht = all.filter((p) => padLayer(p) === 'multi_layer')
  if (!lands.length && tht.length) {
    const info = calc?.tht?.[0]
    const axis = info?.pitch_axis ?? (minStep(tht.map((p) => p.y)) !== null && tht.some((p) => p.x === tht[0].x) ? 'y' : 'x')
    const pitch = rowPitch(tht, axis)
    if (pitch) {
      if (axis === 'y') {
        lines.push({
          orient: 'v',
          a: Math.min(pitch.first.y, pitch.second.y),
          b: Math.max(pitch.first.y, pitch.second.y),
          edgeA: pitch.first.x - padExtent(pitch.first).ex,
          edgeB: pitch.second.x - padExtent(pitch.second).ex,
          side: -1,
          base: ext.left,
          level: 0,
          label: `e ${mm(pitch.pitch)}`,
          title: tr("Raster {value0} mm", { value0: String(mm(pitch.pitch)) }),
        })
      } else {
        lines.push({
          orient: 'h',
          a: Math.min(pitch.first.x, pitch.second.x),
          b: Math.max(pitch.first.x, pitch.second.x),
          edgeA: pitch.first.y + padExtent(pitch.first).ey,
          edgeB: pitch.second.y + padExtent(pitch.second).ey,
          side: 1,
          base: ext.top,
          level: 0,
          label: `e ${mm(pitch.pitch)}`,
          title: tr("Raster {value0} mm", { value0: String(mm(pitch.pitch)) }),
        })
      }
    }
    // Reihenabstand (DIP, zweireihige Stiftleisten)
    const across = axis === 'y' ? 'x' : 'y'
    const rows = [...new Set(tht.map((p) => Math.round(p[across] * 1000) / 1000))].sort((a, b) => a - b)
    if (rows.length === 2) {
      const span = rows[1] - rows[0]
      lines.push(
        across === 'x'
          ? {
              orient: 'h',
              a: rows[0],
              b: rows[1],
              edgeA: padExt.top,
              edgeB: padExt.top,
              side: 1,
              base: ext.top,
              level: 0,
              label: `${mm(span)}`,
              title: tr("Reihenabstand {value0} mm", { value0: String(mm(span)) }),
            }
          : {
              orient: 'v',
              a: rows[0],
              b: rows[1],
              edgeA: padExt.right,
              edgeB: padExt.right,
              side: 1,
              base: ext.right,
              level: 0,
              label: `${mm(span)}`,
              title: tr("Reihenabstand {value0} mm", { value0: String(mm(span)) }),
            },
      )
    }
    const p1 = sortByDesignator(tht)[0]
    if (p1?.hole) {
      const pad = Math.min(p1.width, p1.height)
      callouts.push({
        x: p1.x + padExtent(p1).ex * 0.7,
        y: p1.y + padExtent(p1).ey * 0.7,
        label: `Ø ${mm(p1.hole)} / ${mm(pad)}`,
        title: tr("Bohrung Ø {value0} mm, Pad {value1} mm", { value0: String(mm(p1.hole)), value1: String(mm(pad)) }),
      })
    }
  }

  // BGA bzw. Pads ohne Protokoll: Raster in beiden Richtungen + Gesamtspannweite
  if (!lands.length && !tht.length && smd.length >= 2) {
    const px = rowPitch(smd, 'x')
    const py = rowPitch(smd, 'y')
    if (px) {
      lines.push({
        orient: 'h',
        a: Math.min(px.first.x, px.second.x),
        b: Math.max(px.first.x, px.second.x),
        edgeA: px.first.y + padExtent(px.first).ey,
        edgeB: px.second.y + padExtent(px.second).ey,
        side: 1,
        base: ext.top,
        level: 0,
        label: `e ${mm(px.pitch)}`,
        title: tr("Raster {value0} mm", { value0: String(mm(px.pitch)) }),
      })
    }
    if (py) {
      lines.push({
        orient: 'v',
        a: Math.min(py.first.y, py.second.y),
        b: Math.max(py.first.y, py.second.y),
        edgeA: py.first.x - padExtent(py.first).ex,
        edgeB: py.second.x - padExtent(py.second).ex,
        side: -1,
        base: ext.left,
        level: 0,
        label: `e ${mm(py.pitch)}`,
        title: tr("Raster {value0} mm", { value0: String(mm(py.pitch)) }),
      })
    }
    if (!px || !py) {
      // Zweipolig ohne Protokoll: Außenmaß
      lines.push({
        orient: 'h',
        a: padExt.left,
        b: padExt.right,
        edgeA: padExt.top,
        edgeB: padExt.top,
        side: 1,
        base: ext.top,
        level: px ? 1 : 0,
        label: mm(padExt.right - padExt.left),
        title: tr("Außenmaß {value0} mm", { value0: String(mm(padExt.right - padExt.left)) }),
      })
    }
    const land = calc?.bga?.land
    const p1 = sortByDesignator(smd)[0]
    if (land && p1) {
      callouts.push({
        x: p1.x,
        y: p1.y,
        label: `Ø ${mm(land)}`,
        title: tr("Landefläche Ø {value0} mm{value1}", { value0: String(mm(land)), value1: String(calc?.bga?.ball ? tr(" (Kugel {value0} mm)", { value0: String(mm(calc.bga.ball)) }) : '') }),
      })
    }
  }

  return { lines, callouts, contour }
}
