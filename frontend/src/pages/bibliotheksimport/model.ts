/**
 * Bibliotheksimport – reine Logik der Seite (ohne React): Dateiansichten, Filter, Zeilen des Dateibaums, der Importplan
 * (Vorschau dessen, was `run_import` im Backend tun wird) und die Nachbildung der Zielordner des Backends
 * (`partforge/altium/libimport.py`: `safe_folder_name`, `_target_rel`).
 *
 * Der Plan rechnet wie das Backend: Dateien in Scan-Reihenfolge; ein Name, der woanders registriert ist („Name
 * vergeben“), wird nie übernommen; ein Name, den eine **ausgewählte** frühere Datei schon übernimmt, ist doppelt; eine
 * Datei ohne übernehmbare Namen wird nicht kopiert; eine schon importierte, seither geänderte Datei nur mit „Ersetzen“.
 * Mit einem anderen Zielordner als dem vorgeschlagenen gelten schon importierte Namen als vergeben (sie stehen im
 * alten Ordner), und ob eine Zieldatei schon existiert, weiß erst das Backend.
 */
import type { ImportComponentState, ImportRunResult, ImportScan, ImportSourceComponent, ImportSourceFile } from '@/api/libimport'
import { plural } from '@/lib/format'

export type LibKind = ImportSourceFile['kind']
export type KindFilter = 'all' | LibKind

export const LIB_KINDS: readonly LibKind[] = ['schlib', 'pcblib']
export const COMPONENT_STATES: readonly ImportComponentState[] = ['new', 'imported', 'taken', 'duplicate']

/** Texte je Bibliotheksart */
export const KIND_TEXT = {
  schlib: {
    group: 'Symbolbibliotheken',
    one: 'Symbol',
    many: 'Symbole',
    countOne: 'Pin',
    countMany: 'Pins',
  },
  pcblib: {
    group: 'Footprint-Bibliotheken',
    one: 'Footprint',
    many: 'Footprints',
    countOne: 'Pad',
    countMany: 'Pads',
  },
} as const satisfies Record<LibKind, Record<string, string>>

/** Dateifilter des Dialogs „Bibliotheksdatei wählen“ (die Desktop-Brücke ergänzt „Alle Dateien“ selbst) */
export const SOURCE_FILE_FILTERS = ['Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)']

/** Endungen, die eine Quelle als Datei kennzeichnen */
const SOURCE_FILE_RE = /\.(schlib|pcblib|intlib|libpkg|zip)$/i

/** Ordner für den Ordnerdialog: bei einer Bibliotheksdatei ihr Ordner, sonst der Pfad selbst */
export function folderOf(path: string): string {
  const clean = cleanSourcePath(path)
  return SOURCE_FILE_RE.test(clean) ? splitRel(clean).folder.replace(/[\\/]+$/, '') : clean
}

// --------------------------------------------------------------------------- Pfade

const collator = new Intl.Collator('de', { numeric: true, sensitivity: 'base' })

/** Natürliche Sortierung („Lib2“ vor „Lib10“), ohne Rücksicht auf Groß/klein */
export function compareNatural(a: string, b: string): number {
  return collator.compare(a, b)
}

/** „Ordner\Unterordner\Datei.SchLib“ → Ordner (mit Trenner am Ende) und Dateiname; beide Trenner (`\` und `/`) */
export function splitRel(rel: string): { folder: string; name: string } {
  const i = Math.max(rel.lastIndexOf('\\'), rel.lastIndexOf('/'))
  return i < 0 ? { folder: '', name: rel } : { folder: rel.slice(0, i + 1), name: rel.slice(i + 1) }
}

/** Pfad als Vergleichsschlüssel (Windows: Groß/klein und `/`/`\` egal, ohne abschließenden Trenner) */
export function pathKey(path: string): string {
  return path.trim().replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
}

/** Eingabe bereinigen: Anführungszeichen (Explorer „Als Pfad kopieren“) und Leerraum am Rand */
export function cleanSourcePath(raw: string): string {
  return raw.trim().replace(/^"+|"+$/g, '').trim()
}

const isAbsolutePath = (path: string) => /^[a-z]:[\\/]/i.test(path) || /^\\\\[^\\]+\\[^\\]+/.test(path)

/** Grund, warum eine Quelle nicht eingelesen werden kann (vor der Anfrage) – sonst `null` */
export function sourceProblem(raw: string): string | null {
  const path = cleanSourcePath(raw)
  if (!path) return 'Bitte einen Ordner oder eine Bibliotheksdatei angeben.'
  if (!isAbsolutePath(path)) return 'Bitte den vollständigen Pfad angeben, z. B. C:\\Bibliotheken\\Hersteller.'
  if (/\.(svn)?dblib$/i.test(path)) {
    return 'Datenbankbibliotheken (.DbLib) lassen sich nicht übernehmen – ihre Bauteildaten liegen in einer Datenbank. Bitte den Ordner mit den SchLib- und PcbLib-Dateien wählen.'
  }
  return null
}

/** Zeichen, die das Backend in Ordnernamen ersetzt (`_SAFE_SEGMENT_RE` plus Pfadtrenner) */
const UNSAFE_CHARS = '<>:"|?*\\/'

function stripDotsAndBlanks(text: string): string {
  return text.replace(/^[ .]+|[ .]+$/g, '')
}

/**
 * Ordnername wie im Backend (`safe_folder_name`): unzulässige Zeichen → „_“, Leerraum zusammengefasst, höchstens
 * 60 Zeichen, ohne Punkte/Leerzeichen am Rand; leer → „Import“.
 */
export function safeFolderName(name: string): string {
  let text = ''
  for (const ch of name) text += ch.charCodeAt(0) < 32 || UNSAFE_CHARS.includes(ch) ? '_' : ch
  text = stripDotsAndBlanks(text)
  text = stripDotsAndBlanks(text.replace(/\s+/g, ' ').slice(0, 60))
  return text || 'Import'
}

/** Zielordner eines Imports, z. B. `Symbols\Import\Celestial` */
export function importFolder(base: string, folder: string): string {
  return `${base.replace(/[\\/]+$/, '')}\\Import\\${folder}`
}

/**
 * Geplantes Ziel einer Datei für einen anderen Zielordner: Das Backend nennt es für den vorgeschlagenen Ordner
 * (`…\Import\<scan.name>\…`) – hier wird der Ordnerabschnitt ersetzt.
 */
export function retarget(target: string | null, from: string, to: string): string | null {
  if (!target || from.toLowerCase() === to.toLowerCase()) return target
  const parts = target.split(/[\\/]/)
  const i = parts.findIndex((p, k) => k > 0 && parts[k - 1].toLowerCase() === 'import' && p.toLowerCase() === from.toLowerCase())
  if (i < 0) return target
  parts[i] = to
  return parts.join('\\')
}

export const isSchLib = (rel: string) => /\.schlib$/i.test(rel)

// --------------------------------------------------------------------------- Dateiansichten

export interface FileView {
  file: ImportSourceFile
  /** Position im Scan (Reihenfolge des Backends – sie entscheidet bei doppelten Namen) */
  order: number
  name: string
  folder: string
  /** `rel` in Kleinbuchstaben (Suche) */
  search: string
  /** Namen in Kleinbuchstaben (Suche) – gleiche Reihenfolge wie `file.components` */
  names: string[]
  counts: Record<ImportComponentState, number>
  /** auswählbar (lesbar) */
  selectable: boolean
}

const emptyCounts = (): Record<ImportComponentState, number> => ({ new: 0, imported: 0, taken: 0, duplicate: 0 })

export interface ScanIndex {
  /** alle Dateien, je Art natürlich nach `rel` sortiert (erst Symbole, dann Footprints) */
  views: FileView[]
  byKind: Record<LibKind, FileView[]>
  /** Namen je Art und Zustand (Zähler der Filter) */
  stateCounts: Record<LibKind, Record<ImportComponentState, number>>
  /** nicht lesbare Dateien */
  unreadable: number
  /** Dateien, die standardmäßig ausgewählt sind (alle lesbaren) */
  defaultSelection: Set<string>
}

export function indexScan(scan: ImportScan): ScanIndex {
  const byKind: Record<LibKind, FileView[]> = { schlib: [], pcblib: [] }
  const stateCounts: Record<LibKind, Record<ImportComponentState, number>> = { schlib: emptyCounts(), pcblib: emptyCounts() }
  const defaultSelection = new Set<string>()
  let unreadable = 0
  scan.files.forEach((file, order) => {
    const { folder, name } = splitRel(file.rel)
    const counts = emptyCounts()
    for (const c of file.components) {
      counts[c.state] += 1
      stateCounts[file.kind][c.state] += 1
    }
    const selectable = !file.problem
    if (selectable) defaultSelection.add(file.rel)
    else unreadable += 1
    byKind[file.kind].push({
      file,
      order,
      name,
      folder,
      search: file.rel.toLowerCase(),
      names: file.components.map((c) => c.name.toLowerCase()),
      counts,
      selectable,
    })
  })
  for (const kind of LIB_KINDS) byKind[kind].sort((a, b) => compareNatural(a.file.rel, b.file.rel))
  return { views: [...byKind.schlib, ...byKind.pcblib], byKind, stateCounts, unreadable, defaultSelection }
}

// --------------------------------------------------------------------------- Filter und Baumzeilen

export interface TreeFilter {
  /** Suchtext in Kleinbuchstaben (Datei- und Bauteilnamen) */
  needle: string
  /** Zustände der Namen – leer = alle */
  states: readonly ImportComponentState[]
  kind: KindFilter
}

export interface VisibleFile {
  view: FileView
  /** sichtbare Bauteile (Indizes in `file.components`) */
  comps: number[]
  /** Treffer nur in Bauteilnamen → beim Suchen aufgeklappt zeigen */
  nameHit: boolean
}

export interface VisibleGroup {
  kind: LibKind
  files: VisibleFile[]
}

function visibleFile(view: FileView, f: TreeFilter): VisibleFile | null {
  const comps = view.file.components
  const fileHit = !f.needle || view.search.includes(f.needle)
  const out: number[] = []
  let nameHit = false
  for (let i = 0; i < comps.length; i++) {
    if (f.states.length && !f.states.includes(comps[i].state)) continue
    if (!fileHit) {
      if (!view.names[i].includes(f.needle)) continue
      nameHit = true
    }
    out.push(i)
  }
  if (!fileHit && !out.length) return null
  // mit Zustandsfilter nur Dateien, die solche Namen enthalten
  if (f.states.length && !out.length) return null
  return { view, comps: out, nameHit }
}

export function filterScan(index: ScanIndex, f: TreeFilter): VisibleGroup[] {
  return LIB_KINDS.filter((kind) => f.kind === 'all' || f.kind === kind)
    .map((kind) => ({
      kind,
      files: index.byKind[kind].map((v) => visibleFile(v, f)).filter((v): v is VisibleFile => v !== null),
    }))
    .filter((g) => g.files.length > 0)
}

interface RowBase {
  key: string
  /** Ebene im Baum (1 = Gruppe, 2 = Datei, 3 = Bauteil) */
  level: 1 | 2 | 3
  posinset: number
  setsize: number
  /** Schlüssel der übergeordneten Zeile */
  parent: string | null
}

export interface GroupRow extends RowBase {
  type: 'group'
  level: 1
  group: VisibleGroup
  expanded: boolean
}

export interface FileRow extends RowBase {
  type: 'file'
  level: 2
  item: VisibleFile
  expandable: boolean
  expanded: boolean
}

export interface ComponentRow extends RowBase {
  type: 'component'
  level: 3
  view: FileView
  component: ImportSourceComponent
}

export type TreeRow = GroupRow | FileRow | ComponentRow

export const groupKey = (kind: LibKind) => `g:${kind}`
export const fileKey = (rel: string) => `f:${rel}`
export const componentKey = (rel: string, name: string) => `c:${rel}\u0000${name}`

/** Flache Zeilenliste für die virtualisierte Liste (aufgeklappte Dateien mit ihren sichtbaren Bauteilen) */
export function buildRows(
  groups: VisibleGroup[],
  collapsedGroups: ReadonlySet<LibKind>,
  isExpanded: (item: VisibleFile) => boolean,
): TreeRow[] {
  const rows: TreeRow[] = []
  groups.forEach((group, gi) => {
    const gKey = groupKey(group.kind)
    const groupOpen = !collapsedGroups.has(group.kind)
    rows.push({ type: 'group', key: gKey, level: 1, posinset: gi + 1, setsize: groups.length, parent: null, group, expanded: groupOpen })
    if (!groupOpen) return
    group.files.forEach((item, fi) => {
      const fKey = fileKey(item.view.file.rel)
      const expandable = item.comps.length > 0
      const expanded = expandable && isExpanded(item)
      rows.push({
        type: 'file',
        key: fKey,
        level: 2,
        posinset: fi + 1,
        setsize: group.files.length,
        parent: gKey,
        item,
        expandable,
        expanded,
      })
      if (!expanded) return
      item.comps.forEach((ci, k) => {
        const component = item.view.file.components[ci]
        rows.push({
          type: 'component',
          key: componentKey(item.view.file.rel, component.name),
          level: 3,
          posinset: k + 1,
          setsize: item.comps.length,
          parent: fKey,
          view: item.view,
          component,
        })
      })
    })
  })
  return rows
}

// --------------------------------------------------------------------------- Importplan

/**
 * Was mit einer ausgewählten Datei geschieht: kopieren (neu), ersetzen (geändert + „Ersetzen“), auffrischen (schon
 * unverändert importiert – Namen werden neu registriert), bleibt (geändert, ohne „Ersetzen“ – übersprungen), keine
 * übernehmbaren Namen (übersprungen).
 */
export type FileOutcome = 'copy' | 'replace' | 'refresh' | 'kept' | 'no-names'

export interface ImportPlan {
  /** ausgewählte lesbare Dateien */
  selected: number
  /** Dateien, die übernommen werden (kopiert, ersetzt oder aufgefrischt) */
  files: number
  copied: number
  unchanged: number
  symbols: number
  footprints: number
  /** Namen, die woanders registriert sind (mit anderem Zielordner auch schon importierte) */
  taken: number
  /** Namen, die eine ausgewählte frühere Datei schon übernimmt */
  duplicates: number
  /** Dateien ohne übernehmbare Namen */
  noNames: number
  /** geänderte Dateien, die ohne „Ersetzen“ bleiben */
  kept: number
  /** ausgewählte, seit dem letzten Import geänderte Dateien (für „Ersetzen“) */
  changed: number
  /** übernommene Footprints mit eingebettetem 3D-Modell bzw. ohne Angabe */
  with3d: number
  unknown3d: number
  outcome: Map<string, FileOutcome>
}

export interface PlanOptions {
  /** anderer Zielordner als `scan.name` */
  retargeted: boolean
  replace: boolean
}

export function planImport(scan: ImportScan, selected: ReadonlySet<string>, opts: PlanOptions): ImportPlan {
  const plan: ImportPlan = {
    selected: 0,
    files: 0,
    copied: 0,
    unchanged: 0,
    symbols: 0,
    footprints: 0,
    taken: 0,
    duplicates: 0,
    noNames: 0,
    kept: 0,
    changed: 0,
    with3d: 0,
    unknown3d: 0,
    outcome: new Map(),
  }
  const claimed = new Map<string, string>()
  for (const file of scan.files) {
    if (file.problem || !selected.has(file.rel)) continue
    plan.selected += 1
    const names: ImportSourceComponent[] = []
    let taken = 0
    let duplicates = 0
    for (const c of file.components) {
      if (c.state === 'taken' || (c.state === 'imported' && opts.retargeted)) {
        taken += 1
        continue
      }
      const owner = claimed.get(`${file.kind}|${c.name.toLowerCase()}`)
      if (owner !== undefined && owner !== file.rel) {
        duplicates += 1
        continue
      }
      names.push(c)
    }
    plan.taken += taken
    plan.duplicates += duplicates
    const exists = opts.retargeted ? 'no' : file.exists
    if (exists === 'different') plan.changed += 1
    if (!names.length) {
      plan.noNames += 1
      plan.outcome.set(file.rel, 'no-names')
      continue
    }
    if (exists === 'different' && !opts.replace) {
      plan.kept += 1
      plan.outcome.set(file.rel, 'kept')
      continue
    }
    const outcome: FileOutcome = exists === 'same' ? 'refresh' : exists === 'different' ? 'replace' : 'copy'
    plan.outcome.set(file.rel, outcome)
    plan.files += 1
    if (outcome === 'refresh') plan.unchanged += 1
    else plan.copied += 1
    for (const c of names) {
      claimed.set(`${file.kind}|${c.name.toLowerCase()}`, file.rel)
      if (file.kind === 'schlib') plan.symbols += 1
      else {
        plan.footprints += 1
        if (c.has_3d === true) plan.with3d += 1
        else if (c.has_3d == null) plan.unknown3d += 1
      }
    }
  }
  return plan
}

// --------------------------------------------------------------------------- Ergebnis

/**
 * Probleme im Ergebnis des Imports als ein Satz (Warn-Toast des Job-Docks, wenn die Seite den Import nicht mehr zeigt)
 * – `null` = ohne Befund. Die Standarderkennung des Docks kennt `conflicts` und `skipped` nicht.
 */
export function importProblem(result: ImportRunResult | null | undefined): string | null {
  if (!result) return null
  const parts: string[] = []
  if (result.errors.length) {
    const first = result.errors[0]
    parts.push(`${plural(result.errors.length, 'Fehler', 'Fehler')} – ${splitRel(first.rel).name}: ${first.message}`)
  }
  if (result.conflicts.length) parts.push(`${plural(result.conflicts.length, 'Name', 'Namen')} nicht übernommen (vergeben oder doppelt)`)
  if (result.skipped.length) parts.push(`${plural(result.skipped.length, 'Datei', 'Dateien')} übersprungen`)
  const conversion = result.conversion
  if (conversion && (conversion.errors.length || conversion.skipped.length)) {
    parts.push(`Angleichen an den Hausstil: ${plural(conversion.errors.length + conversion.skipped.length, 'Bibliothek', 'Bibliotheken')} nicht geändert`)
  }
  return parts.length ? parts.join(' · ') : null
}
