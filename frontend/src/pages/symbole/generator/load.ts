import { t as tr } from '@/components/preview/i18n'
/**
 * Ein gespeichertes Symbol im Generator öffnen („Bearbeiten“ aus der Bibliothek): `spec.generator.request` wird
 * in den Generator-Zustand übernommen (Standardsymbol mit Parametern bzw. IC-Pinliste). Ein eigener Name kommt aus
 * `spec.generator.name` (vom Backend beim Speichern vermerkt) – erzeugte Namen bleiben leer und folgen dem Hausstil.
 * Symbole ohne Generator-Angaben (Datenblatt, Import) mit Pins werden als IC-Pinliste übernommen – Seiten aus der
 * Pinrichtung – und bekommen einen neuen Namen („… (IC)“), damit Speichern die Originalzeichnung nicht ersetzt.
 */
import type { IcPin, SymbolEntry, SymbolKindInfo } from '@/api/symbols'
import { baseName, plural } from '@/lib/format'
import type { SymbolSpec } from '@/lib/geometry'
import { fromIcPin } from '../ic/pins'
import { EMPTY_IC, IC_KIND, useGenerator, type IcOrder, type PartsMode } from '../store'
import { generatorName, generatorRequest, SIDE_OF_ORIENTATION, suggestFreeName } from '../util'

export interface OpenResult {
  ok: boolean
  kind?: string
  /** Überschrift und Hinweis für den Nutzer (z. B. „Als IC-Pinliste übernommen“) */
  noteTitle?: string
  note?: string
}

const ORDERS = new Set<IcOrder>(['name', 'designator', 'input'])
const str = (v: unknown): string => (typeof v === 'string' ? v : '')

/** Neuer Name für ein als Pinliste übernommenes Symbol: „NPN Import (IC)“ bzw. „… (IC) 2“, falls schon vergeben */
export function pinListName(name: string, entries: readonly SymbolEntry[] | undefined): string {
  const base = `${name.slice(0, 58).trim()} (IC)`
  const taken = entries?.some((e) => e.name.toLowerCase() === base.toLowerCase())
  return taken ? suggestFreeName(base, entries) : base
}

/** Ziel beim Speichern (Bibliotheksdatei, Verwendung) als Hinweis */
function targetNote(name: string, record: SymbolEntry | undefined): string | undefined {
  if (!record) return undefined
  const usage = record.usage ? tr(" – {value0} es", { value0: String(plural(record.usage, tr('Bauteil verwendet'), tr('Bauteile verwenden'))) }) : ''
  return tr("Speichern aktualisiert „{value0}“ in {value1}{value2}. Unter neuem Namen: Strg+⇧+S.", { value0: String(name), value1: String(baseName(record.library)), value2: String(usage) })
}

export function openSpecInGenerator(
  spec: SymbolSpec,
  kinds: readonly SymbolKindInfo[] | undefined,
  library: { record?: SymbolEntry; entries?: readonly SymbolEntry[] } = {},
): OpenResult {
  const store = useGenerator.getState()
  const req = generatorRequest(spec)
  const gen = (spec.generator ?? {}) as Record<string, unknown>
  const kindKey = typeof req?.kind === 'string' ? req.kind : null
  // Herkunft merken: Kopien („Speichern unter …“, Pinliste) landen in derselben SchLib wie das Original
  const origin = library.record ? { name: library.record.name, library: library.record.library } : null

  if (req && kindKey === IC_KIND) {
    const params = ((req.params as Record<string, unknown> | undefined) ?? (gen.params as Record<string, unknown> | undefined) ?? {}) as Record<
      string,
      unknown
    >
    const rawParts = params.parts
    const partsNum = Number(rawParts)
    const partsMode: PartsMode = rawParts === 'auto' ? 'auto' : Number.isFinite(partsNum) && partsNum > 1 ? 'fixed' : '1'
    const order = ORDERS.has(params.order as IcOrder) ? (params.order as IcOrder) : 'name'
    const pins = Array.isArray(req.pins) ? (req.pins as Partial<IcPin>[]) : []
    // IC-Symbole tragen im Editor immer einen Namen – ohne eigenen Namen den gespeicherten („IC 8-Pin“)
    const name = generatorName(spec) ?? spec.name
    store.loadIc({
      ...EMPTY_IC,
      name,
      description: str(req.description),
      prefix: str(req.designator_prefix),
      partsMode,
      partCount: partsMode === 'fixed' ? partsNum : 2,
      order,
      maxPinsPerSide: Number(params.max_pins_per_side) || 40,
      pins: pins.map((p) => fromIcPin(p)),
      origin,
    })
    return { ok: true, kind: IC_KIND, noteTitle: tr('Im Generator geöffnet'), note: targetNote(name, library.record) }
  }

  if (req && kindKey) {
    const kind = kinds?.find((k) => k.key === kindKey)
    if (kind) {
      const pins = kind.key === 'connector' && Array.isArray(req.pins) && req.pins.length ? (req.pins as IcPin[]) : undefined
      store.loadStandard(kind.key, ((req.params as Record<string, unknown> | undefined) ?? {}) as Record<string, unknown>, {
        prefix: str(req.designator_prefix),
        description: str(req.description),
        name: generatorName(spec) ?? '',
        pins,
        origin,
      })
      return { ok: true, kind: kind.key, noteTitle: tr('Im Generator geöffnet'), note: targetNote(spec.name, library.record) }
    }
  }

  // Ohne Generator-Angaben: Pins als IC-Pinliste übernehmen – unter neuem Namen (die Zeichnung bleibt erhalten)
  if (spec.pins?.length) {
    const name = pinListName(spec.name, library.entries)
    store.loadIc({
      ...EMPTY_IC,
      name,
      description: spec.description ?? '',
      prefix: spec.designator_prefix ?? '',
      // mehrteilige Originale bringen ihre Teile in der Spalte „Teil“ mit – „Ein Teil“ übernimmt sie unverändert
      partsMode: '1',
      order: 'input',
      origin,
      pins: spec.pins.map((p) =>
        fromIcPin({
          designator: p.designator,
          name: p.name ?? '',
          electrical: p.electrical,
          side: SIDE_OF_ORIENTATION[p.orientation],
          part: p.part ?? 1,
          hidden: p.hidden ?? false,
          group: p.group ?? null,
          description: p.description ?? null,
        }),
      ),
    })
    return {
      ok: true,
      kind: IC_KIND,
      noteTitle: tr('Als IC-Pinliste übernommen'),
      note: tr("„{value0}“ hat keine Generator-Angaben – seine Pins stehen jetzt in der Pinliste (Seiten wie im Original). Gespeichert wird als neues Kastensymbol „{value1}“; die Originalzeichnung bleibt erhalten.", { value0: String(spec.name), value1: String(name) }),
    }
  }
  return { ok: false }
}
