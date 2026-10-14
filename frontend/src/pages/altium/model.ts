import { t as tr, localizeMessage } from '@/lib/i18n'
import {
  odbcDriverStatus,
  type AltiumStatus,
  type DbLibIssue,
  type DbLibStatus,
  type InstallJobResult,
  type OdbcDriverStatus,
  type VerifiedPart,
} from '@/api/altium'
import type { LibraryFile } from '@/api/libraries'
import type { LibraryBackend } from '@/api/system'
import { baseName, formatNumber, formatRelativeTime, plural, toMillis } from '@/lib/format'
import { SETTINGS_PLACE, SQLITE_ODBC_URL } from './settingsPlaces'

export type Level = 'ok' | 'warn' | 'error' | 'off' | 'busy'

/** Aktionen der Seite (Schlüssel für Knöpfe, Befehle und Ein-Klick-Behebungen) */
export type ActionKey =
  | 'regenerate'
  | 'preview'
  | 'odbc'
  | 'sync'
  | 'scan'
  | 'scanSync'
  /** Footprint-Höhen in die PcbLibs nachtragen (Prüfbericht, `footprint_height_missing`) */
  | 'repairHeights'
  /** Beschädigte Bibliotheksdatei aus Backups\lib zurückholen (Prüfbericht, `library_unreadable`) */
  | 'restoreBackup'
  | 'install'
  | 'installReplace'
  | 'uninstall'
  | 'installState'
  | 'refresh'
  | 'refreshRebuild'
  | 'verify'
  | 'open'
  /** Hängendes PartForge-Skript in Altium beenden (`EditScript:Stop`) und prüfen, ob Skripte wieder laufen */
  | 'stopScript'
  | 'settings'
  /** Bibliotheks-Writer einrichten (Einstellungen › Allgemein › Altium Designer) – ohne Writer entstehen keine Dateien */
  | 'writer'
  | 'report'
  /** Bibliothek prüfen (Prüfbericht neu erstellen) */
  | 'check'
  /** Werte vereinheitlichen (Prüfbericht) */
  | 'normalize'
  /** Serien-Assistent öffnen (leere Bibliothek) */
  | 'series'
  /** Status und Dateiliste neu laden (nach einem Fehler) */
  | 'reload'

/** Aktionen, die ein laufendes Altium brauchen */
export const NEEDS_ALTIUM: readonly ActionKey[] = [
  'installState',
  'install',
  'installReplace',
  'uninstall',
  'refresh',
  'refreshRebuild',
  'verify',
  'open',
  'stopScript',
]

export interface ChainNode {
  key: 'parts' | 'dblib' | 'files' | 'altium'
  label: string
  value: string
  /** Kennzahlen – oder bei Problemen der Grund (sichtbar, höchstens zwei Zeilen) */
  detail: string
  level: Level
  /** Behebung direkt am Glied (nur bei Problemen) */
  fix?: { action: ActionKey; label: string }
  /** Wo der Zustand sichtbar wird: im Wert (Standard) oder in der Detailzeile („Läuft“ bleibt neutral, „nicht installiert“ nicht) */
  emphasis?: 'value' | 'detail'
}

export type HeadlineTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral'

export interface Headline {
  tone: HeadlineTone
  eyebrow: string
  title: string
  text: string
  /** nächster Schritt = Primäraktion (höchstens eine je Ansicht) */
  primary: ActionKey | null
  /** Verweis nach außen (z. B. Download des ODBC-Treibers) – erscheint hinter dem Text */
  link?: { label: string; href: string }
}

/** Fehlermeldung für eine Detailzeile kürzen (die volle Meldung steht in der Schlagzeile bzw. im Prüfbericht) */
function shortReason(text: string, max = 90): string {
  const clean = localizeMessage(text).replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()} …` : clean
}

// --------------------------------------------------------------------------- DbLib

const REGENERATE_CODES = new Set(['missing', 'outdated', 'format', 'db_path', 'unreadable', 'parse'])
/** Befunde, die kein Neuschreiben behebt (Datenbank, Netzlaufwerk, Namen, Installation) */
const BLOCKING_CODES = new Set(['wal', 'network', 'db_missing', 'db_path_chars', 'file_name', 'build', 'library_ref', 'unsafe_name'])

/** Kurzer Grund je DbLib-Befund (Detailzeile des Glieds) */
const DBLIB_REASON: Record<string, string> = {
  get missing() { return tr("Datei fehlt im Bibliotheksordner") },
  get outdated() { return tr("Kategorien oder Felder geändert") },
  get format() { return tr("Nicht im Altium-Format gespeichert") },
  get db_path() { return tr("Verweist auf eine andere Datenbank") },
  get unreadable() { return tr("Datei nicht lesbar") },
  get parse() { return tr("Auffälligkeit beim Lesen") },
  get wal() { return tr("Datenbank nicht im WAL-Modus") },
  get network() { return tr("Datenbank auf einem Netzlaufwerk") },
  get db_missing() { return tr("Datenbankdatei fehlt") },
  get db_path_chars() { return tr("Datenbankpfad für Altium ungeeignet") },
  get file_name() { return tr("Ungültiger Dateiname") },
  get build() { return tr("Soll-Stand unbekannt") },
  get library_ref() { return tr("Tabelle ohne Spalte „Library Ref“") },
  get unsafe_name() { return tr("Name für Altium ungeeignet") },
  get no_key() { return tr("Kategorie ohne Schlüsselspalte") },
  get encoding() { return tr("Zeichen außerhalb von Windows-1252") },
  get no_enabled_tables() { return tr("Keine Tabelle für Altium aktiviert") },
  get open_in_editor() { return tr("In Altium im Editor geöffnet") },
}

/** Schlagzeile je DbLib-Fehler; `strip` = der Meldung den ersten Satzteil („… – “) nehmen, er wiederholt den Titel */
const DBLIB_PROBLEM: Record<string, { title: string; strip?: boolean }> = {
  missing: { get title() { return tr("Die DbLib fehlt") } },
  unreadable: { get title() { return tr("Die DbLib ist nicht lesbar") } },
  db_path: { get title() { return tr("Die DbLib verweist auf eine andere Datenbank") } },
  wal: { get title() { return tr("Die Datenbank ist nicht im WAL-Modus") }, strip: true },
  network: { get title() { return tr("Die Datenbank liegt auf einem Netzlaufwerk") }, strip: true },
  db_missing: { get title() { return tr("Die Datenbankdatei fehlt") } },
  db_path_chars: { get title() { return tr("Der Datenbankpfad ist für Altium ungeeignet") } },
  file_name: { get title() { return tr("Der DbLib-Dateiname ist ungültig") } },
  build: { get title() { return tr("Der Soll-Stand der DbLib ist unbekannt") } },
  library_ref: { get title() { return tr("Eine Kategorie ist für Altium unvollständig") } },
  unsafe_name: { get title() { return tr("Ein Name ist für die DbLib ungeeignet") } },
}

export function dblibIssue(dblib: DbLibStatus | null | undefined, ...codes: string[]): DbLibIssue | undefined {
  return dblib?.issues.find((i) => codes.includes(i.code))
}

/** Dürfen gleichnamige Installationen ersetzt werden (alter Ordner derselben Bibliothek, Datei weg)? */
export function duplicatesReplaceable(dblib: DbLibStatus | null | undefined): boolean {
  if (dblibIssue(dblib, 'moved_install')) return true
  const kinds = Object.values(dblib?.install?.duplicate_kinds ?? {})
  return kinds.length > 0 && kinds.every((k) => k === 'same_database' || k === 'missing')
}

/** Grund aus einer Backend-Meldung: „Die DbLib ist veraltet (Kategorien … geändert). …“ → Klammerinhalt */
function reasonOf(issue: DbLibIssue | undefined): string | undefined {
  if (!issue) return undefined
  if (issue.code === 'outdated') {
    // from the localized message: „(Kategorien oder Felder wurden geändert)“ → „(categories or fields were changed)“
    const inner = /\(([^)]+)\)/.exec(localizeMessage(issue.message))?.[1]
    if (inner) return inner.charAt(0).toUpperCase() + inner.slice(1)
  }
  return DBLIB_REASON[issue.code] ?? shortReason(issue.message, 60)
}

export interface DblibSummary {
  level: Level
  value: string
  detail: string
  /** erster Befund, der das Problem erklärt */
  issue?: DbLibIssue
  fix?: ActionKey
}

export function summarizeDblib(
  dblib: DbLibStatus | null | undefined,
  state: { loaded: boolean; error?: string | null } = { loaded: true },
): DblibSummary {
  if (!dblib) {
    if (state.error) return { level: 'off', value: tr("Nicht verfügbar"), detail: shortReason(state.error) }
    return state.loaded
      ? { level: 'off', value: tr("Unbekannt"), detail: tr("Keine Bibliothek geöffnet") }
      : { level: 'off', value: tr("Wird geprüft …"), detail: '' }
  }
  const tables = dblib.enabled_tables.length
  const facts = `${plural(tables, tr("Tabelle"), tr("Tabellen"))} · ${plural(dblib.field_maps, tr("Feld"), tr("Felder"))}`
  const errors = dblib.issues.filter((i) => i.severity === 'error' && i.code !== 'duplicates')
  if (!dblib.exists) {
    return { level: 'error', value: tr("Fehlt"), detail: tr("„{0}“ nicht im Bibliotheksordner", { "0": String(dblib.file_name) }), issue: dblibIssue(dblib, 'missing'), fix: 'regenerate' }
  }
  const blocking = errors.find((i) => BLOCKING_CODES.has(i.code))
  if (blocking) return { level: 'error', value: tr("Fehlerhaft"), detail: reasonOf(blocking) ?? facts, issue: blocking }
  const fixable = errors.find((i) => REGENERATE_CODES.has(i.code))
  if (fixable) {
    return {
      level: 'error',
      value: fixable.code === 'db_path' ? tr("Falsche Datenbank") : tr("Fehlerhaft"),
      detail: reasonOf(fixable) ?? facts,
      issue: fixable,
      fix: 'regenerate',
    }
  }
  if (!dblib.up_to_date) {
    const issue = dblibIssue(dblib, 'outdated', 'format')
    return { level: 'warn', value: tr("Veraltet"), detail: reasonOf(issue) ?? facts, issue, fix: 'regenerate' }
  }
  const warning = dblib.issues.find((i) => i.severity === 'warning' && !['moved_install', 'open_in_editor'].includes(i.code))
  if (warning) return { level: 'warn', value: tr("Aktuell"), detail: reasonOf(warning) ?? facts, issue: warning }
  return { level: 'ok', value: tr("Aktuell"), detail: facts }
}

// --------------------------------------------------------------------------- Bibliotheksdateien

export interface FilesSummary {
  total: number
  schlib: number
  pcblib: number
  inSync: number
  pending: number
  errors: number
  /** registriert, aber nicht in der Datei */
  absent: number
  missingFiles: number
  /** außerhalb geändert (ohne beschädigte – die zählen unter `damaged`, wie `changed_outside` des Backends) */
  outside: number
  layersOff: number
  /** Inhalt nicht lesbar (beschädigt oder ohne Lesezugriff, d. h. ohne Bibliotheks-Writer) */
  unreadable: number
  /** davon beschädigt (`LibraryFileInfo.unreadable`) – Prüfbericht: „Aus Sicherung wiederherstellen“ */
  damaged: number
  /** Einträge (Symbole bzw. Footprints) in allen Dateien */
  components: number
  /** Bauteile, die auf eine fehlende Bibliothek bzw. einen fehlenden Eintrag verweisen (aus der Dateiprüfung) */
  links: number
  /** Footprints, deren PcbLib die Höhe 0 trägt (Dateiprüfung) – davon mit Ein-Klick-Korrektur */
  heights: number
  heightsRepairable: number
  level: Level
  value: string
  /** Grund (bei Problemen) bzw. Zusammensetzung */
  detail: string
}

export function summarizeFiles(
  files: LibraryFile[] | undefined,
  links = 0,
  heights: { total: number; repairable: number } = { total: 0, repairable: 0 },
): FilesSummary | null {
  if (!files) return null
  const sum = (fn: (f: LibraryFile) => number) => files.reduce((n, f) => n + fn(f), 0)
  const s = {
    total: files.length,
    schlib: files.filter((f) => f.kind === 'schlib').length,
    pcblib: files.filter((f) => f.kind === 'pcblib').length,
    inSync: files.filter((f) => f.in_sync).length,
    pending: sum((f) => f.pending),
    errors: sum((f) => f.errors),
    absent: sum((f) => (f.exists ? f.missing.length : 0)),
    missingFiles: files.filter((f) => !f.exists).length,
    outside: files.filter((f) => f.external_changes && !f.unreadable).length,
    layersOff: files.filter((f) => f.layers_ok === false).length,
    unreadable: files.filter((f) => f.exists && (f.unreadable || f.components === null)).length,
    damaged: files.filter((f) => f.exists && f.unreadable).length,
    components: sum((f) => f.components ?? 0),
    links,
    heights: heights.total,
    heightsRepairable: heights.repairable,
  }
  const facts = `${formatNumber(s.schlib)} SchLib · ${formatNumber(s.pcblib)} PcbLib`
  let level: Level = 'ok'
  let value = tr("Synchron")
  let detail = facts
  if (s.total === 0) {
    level = 'off'
    value = tr("Noch keine Dateien")
    detail = tr("entstehen mit den ersten Bauteilen")
  } else if (s.missingFiles) {
    level = 'error'
    value = s.missingFiles === 1 ? tr("1 Datei fehlt") : tr("{0} Dateien fehlen", { "0": String(formatNumber(s.missingFiles)) })
    const names = files.filter((f) => !f.exists).map((f) => baseName(f.rel))
    detail = names.slice(0, 2).join(', ') + (names.length > 2 ? ' …' : '')
  } else if (s.damaged) {
    level = 'error'
    value = s.damaged === 1 ? tr("1 Datei beschädigt") : tr("{0} Dateien beschädigt", { "0": String(formatNumber(s.damaged)) })
    const names = files.filter((f) => f.exists && f.unreadable).map((f) => baseName(f.rel))
    detail = tr("nicht lesbar: {0}{1}", { "0": String(names.slice(0, 2).join(', ')), "1": String(names.length > 2 ? ' …' : '') })
  } else if (s.errors) {
    level = 'error'
    value = plural(s.errors, tr("Fehler"), tr("Fehler"))
    detail = tr("Schreiben fehlgeschlagen")
  } else if (s.pending) {
    level = 'warn'
    value = tr("{0} ausstehend", { "0": String(formatNumber(s.pending)) })
    detail = tr("warten auf das Schreiben")
  } else if (s.absent) {
    level = 'warn'
    value = plural(s.absent, tr("Eintrag fehlt"), tr("Einträge fehlen"))
    detail = tr("registriert, aber nicht in der Datei")
  } else if (s.outside) {
    level = 'warn'
    value = tr("{0} außerhalb geändert", { "0": String(formatNumber(s.outside)) })
    detail = tr("z. B. in Altium gespeichert")
  } else if (s.links) {
    level = 'error'
    value = plural(s.links, tr("Verweis ungültig"), tr("Verweise ungültig"))
    detail = tr("Bauteile verweisen auf Fehlendes")
  } else if (s.layersOff) {
    level = 'warn'
    value = tr("Lagen abweichend")
    detail = plural(s.layersOff, tr("PcbLib mit anderem Lagen-Kopf"), tr("PcbLibs mit anderem Lagen-Kopf"))
  } else if (s.unreadable) {
    level = 'warn'
    value = tr("{0} nicht lesbar", { "0": String(formatNumber(s.unreadable)) })
    detail = tr("kein Bibliotheks-Writer oder Datei beschädigt")
  } else if (s.heights) {
    level = 'warn'
    value = plural(s.heights, tr("Höhe fehlt"), tr("Höhen fehlen"))
    detail = tr("Footprints mit Bauhöhe 0 in der PcbLib")
  }
  return { ...s, level, value, detail }
}

/**
 * Wer schreibt SchLib/PcbLib? („Bibliotheks-Writer 0.1.0“, „Schreiben über Altium“, „Kein Bibliotheks-Writer“) – die
 * Oberfläche nennt das Programm `altium-designer-mcp.exe` immer „Bibliotheks-Writer“ (den Dateinamen nur in Hilfetexten).
 */
export function writerLabel(status: AltiumStatus | undefined, backend: LibraryBackend | undefined): { label: string; ok: boolean } {
  const rust = status?.backends.find((b) => b.name === 'rust')
  const altium = status?.backends.find((b) => b.name === 'altium')
  const rustLabel = tr("Bibliotheks-Writer{0}", { "0": String(rust?.version ? ` ${rust.version}` : '') })
  if (backend === 'altium') return { label: altium?.available ? tr("Schreiben über Altium") : tr("Altium nicht bereit"), ok: Boolean(altium?.available) }
  if (backend === 'rust') return { label: rust?.available ? rustLabel : tr("Bibliotheks-Writer fehlt"), ok: Boolean(rust?.available) }
  if (rust?.available) return { label: rustLabel, ok: true }
  if (altium?.available) return { label: tr("Schreiben über Altium"), ok: true }
  return { label: tr("Kein Bibliotheks-Writer"), ok: false }
}

/** Was zu tun ist, wenn kein Bibliotheks-Writer bereit ist (ohne Schlusspunkt) */
export const writerRemedy = () => tr("den Pfad zu altium-designer-mcp.exe unter {0} eintragen oder Altium Designer starten", { "0": SETTINGS_PLACE.altium.label })

/** Was fehlt, damit Bibliotheksdateien entstehen – Satz für Hinweise und Toasts (ohne Schlusspunkt) */
export const writerMissingText = () => tr("Ohne Bibliotheks-Writer entstehen keine SchLib-/PcbLib-Dateien – {0}", { "0": writerRemedy() })

// --------------------------------------------------------------------------- ODBC-Treiber

/** Fehlt der ODBC-Treiber, über den Altium die Datenbank liest? (`null`: unbekannt bzw. installiert) */
export function missingOdbcDriver(status: AltiumStatus | undefined): OdbcDriverStatus | null {
  const odbc = odbcDriverStatus(status)
  return odbc && odbc.installed === false ? odbc : null
}

/** Download-Verweis für den fehlenden Treiber (Bezugsquelle des Backends, sonst SQLite: ch-werner.de) */
export function odbcDriverLink(odbc: OdbcDriverStatus): { label: string; href: string } | undefined {
  const sqlite = odbc.kind ? odbc.kind === 'sqlite' : /sqlite/i.test(odbc.driver)
  const href = odbc.download || (sqlite ? SQLITE_ODBC_URL : null)
  if (!href) return undefined
  let host = href
  try {
    host = new URL(href).host.replace(/^www\./, '')
  } catch {
    // keine gültige Adresse – dann der Text selbst
  }
  return { label: tr("{0} herunterladen ({1})", { "0": String(sqlite ? tr("SQLite-ODBC-Treiber") : tr("ODBC-Treiber")), "1": String(host) }), href }
}

// --------------------------------------------------------------------------- Deinstallieren

/** Programm, das die SQLite-Datenbank noch offen hält (Restart Manager, `routes_altium._database_release`) */
export interface DatabaseHolder {
  pid: number
  name: string
}

/** Ergebnis von „Aus Altium deinstallieren“ (`altium.uninstall`) – mit der Freigabe der Datenbank */
export interface UninstallResult extends InstallJobResult {
  /** `false` = ein Programm (meist Altium) hält die Datenbank noch offen; `null` = nicht feststellbar (PostgreSQL …) */
  database_released?: boolean | null
  database_holders?: DatabaseHolder[]
  /** Was vor dem Verschieben des Bibliotheksordners zu tun ist – zuerst die Behebung („Ordner erst in etwa …“) */
  database_hint?: string | null
}

/**
 * Hinweis eines beendeten „Aus Altium deinstallieren“ (E2EREG-2) – `warnWhen` des Jobs: hält ein Programm die
 * Datenbank noch offen (`database_released === false`), der **volle** Text der Schlussmeldung („Die DbLib wurde in
 * Altium deinstalliert. Ordner erst in etwa einer Minute verschiebbar – …“, passt ungekürzt in einen Toast); der Job
 * gilt dann als „Fertig mit Hinweisen“. Fehlt der Hinweis im Text (älteres Backend), entsteht er aus
 * `database_holders`. Sonst `null`.
 */
export function uninstallWarning(job: { message?: string | null; result?: UninstallResult | null }): string | null {
  const r = job.result
  if (!r || r.database_released !== false) return null
  const message = (job.message || r.message || '').trim()
  const hint = r.database_hint?.trim()
  if (hint) return message.includes(hint) ? localizeMessage(message) : [message, hint].filter(Boolean).map(localizeMessage).join(' ')
  if (/verschiebbar|offen/i.test(message)) return localizeMessage(message)
  const names = [...new Set((r.database_holders ?? []).map((h) => h.name.trim()).filter(Boolean))]
  const held = names.length
    ? tr("{0} {1} die Datenbank noch offen", { "0": String(names.join(', ')), "1": String(names.length === 1 ? tr("hält") : tr("halten")) })
    : tr("Ein anderes Programm hält die Datenbank noch offen")
  return [localizeMessage(message), tr("Ordner erst danach verschiebbar – {0}.", { "0": String(held) })].filter(Boolean).join(' ')
}

// --------------------------------------------------------------------------- Altium

/**
 * Hat die letzte Aktualisierung in Altium etwas bewirkt? Fand Altium keine installierte DbLib dieses Namens
 * (`last_result.matched` leer – „nichts zu aktualisieren“), war es kein Aktualisieren: kein „aktualisiert vor 2 Min.“.
 */
export function refreshedSomething(status: AltiumStatus | undefined): boolean {
  const refresh = status?.refresh
  if (!refresh?.last_refresh) return false
  const matched = (refresh.last_result as { matched?: unknown } | null | undefined)?.matched
  return !(Array.isArray(matched) && matched.length === 0)
}

export function lastRefreshText(status: AltiumStatus | undefined): string | null {
  const t = status?.refresh.last_refresh
  return t && refreshedSomething(status) ? formatRelativeTime(toMillis(t)) : null
}

export interface AltiumSummary {
  level: Level
  value: string
  detail: string
  /** Kurzform für Untertitel („Altium läuft · 26.10.1.5“, „Altium nicht gestartet“) */
  short: string
  emphasis?: 'value' | 'detail'
  fix?: { action: ActionKey; label: string }
  running: boolean
  installed: boolean | null
}

export function summarizeAltium(status: AltiumStatus | undefined, error?: string | null): AltiumSummary {
  if (!status) {
    return error
      ? { level: 'off', value: tr("Nicht verfügbar"), detail: shortReason(error), short: tr("Status nicht verfügbar"), running: false, installed: null }
      : { level: 'off', value: tr("Wird geprüft …"), detail: '', short: tr("Altium wird geprüft …"), running: false, installed: null }
  }
  const installed = status.dblib?.installed_in_altium ?? null
  const duplicates = dblibIssue(status.dblib, 'duplicates')
  const moved = dblibIssue(status.dblib, 'moved_install')
  const replaceable = duplicatesReplaceable(status.dblib)
  if (!status.altium_exe) {
    return {
      level: 'warn',
      value: tr("Nicht gefunden"),
      detail: tr("X2.EXE nicht gefunden"),
      short: tr("Altium nicht gefunden"),
      fix: { action: 'settings', label: tr("Pfad festlegen") },
      running: false,
      installed,
    }
  }
  const version = status.version ? ` · ${status.version}` : ''
  if (!status.altium_running) {
    return {
      level: duplicates || moved ? 'warn' : 'off',
      value: tr("Nicht gestartet"),
      detail: duplicates
        ? tr("Gleichnamige DbLib installiert")
        : moved
          ? tr("Alte Installation aus anderem Ordner")
          : status.version
            ? `Altium Designer ${status.version}`
            : 'Altium Designer',
      emphasis: duplicates || moved ? 'detail' : undefined,
      short: tr("Altium nicht gestartet"),
      running: false,
      installed,
    }
  }
  const running = { running: true, installed, short: tr("Altium läuft{0}", { "0": String(version) }) }
  if (status.bridge_wedged) {
    return {
      ...running,
      level: 'error',
      value: tr("Skript hängt{0}", { 0: String(version) }),
      detail: tr("Angehaltenes Skript beenden"),
      short: tr("Altium-Skript hängt"),
      fix: { action: 'stopScript', label: tr("Skript anhalten") },
    }
  }
  if (status.refresh.running) {
    return { ...running, level: 'busy', value: tr("Läuft{0}", { 0: String(version) }), detail: tr("Wird gerade aktualisiert …") }
  }
  if (duplicates) {
    return {
      ...running,
      level: 'error',
      value: tr("Läuft{0}", { 0: String(version) }),
      detail: tr("Gleichnamige DbLib aktiv"),
      emphasis: 'detail',
      fix: replaceable ? { action: 'installReplace', label: tr("Ersetzen und installieren") } : undefined,
    }
  }
  if (moved) {
    return {
      ...running,
      level: 'warn',
      value: tr("Läuft{0}", { 0: String(version) }),
      detail: tr("Alte Installation aus anderem Ordner"),
      emphasis: 'detail',
      fix: { action: 'installReplace', label: tr("Ersetzen und installieren") },
    }
  }
  if (installed === null) {
    return {
      ...running,
      level: 'ok',
      value: tr("Läuft{0}", { 0: String(version) }),
      detail: tr("Installation ungeprüft"),
      emphasis: 'detail',
      fix: { action: 'installState', label: tr("Status prüfen") },
    }
  }
  if (!installed) {
    return {
      ...running,
      level: 'warn',
      value: tr("Läuft{0}", { 0: String(version) }),
      detail: tr("DbLib nicht installiert"),
      emphasis: 'detail',
      fix: { action: 'install', label: tr("Installieren") },
    }
  }
  if (status.refresh.last_error) {
    return {
      ...running,
      level: 'warn',
      value: tr("Läuft{0}", { 0: String(version) }),
      detail: tr("Aktualisieren fehlgeschlagen"),
      emphasis: 'detail',
      fix: { action: 'refresh', label: tr("Erneut aktualisieren") },
    }
  }
  const last = lastRefreshText(status)
  return { ...running, level: 'ok', value: tr("Läuft{0}", { 0: String(version) }), detail: last ? tr("Installiert · aktualisiert {0}", { "0": String(last) }) : tr("Installiert") }
}

// --------------------------------------------------------------------------- Nach dem Anlegen neuer Bauteile

/** Was Altium Designer von gerade geschriebenen Bauteilen sieht (Zeile der Erfolgsansichten) */
export interface AfterWriteNotice {
  /**
   * ok = Altium wird automatisch aktualisiert · busy = Aktualisierung läuft bzw. folgt gleich · manual = erst nach
   * „In Altium aktualisieren“ · warn = so erscheinen die Bauteile nicht (DbLib nicht installiert, gleichnamige DbLib,
   * Aktualisieren gescheitert) · error = Skript hängt · off = Altium läuft nicht
   */
  tone: 'ok' | 'busy' | 'manual' | 'warn' | 'error' | 'off'
  text: string
  /** nächster Schritt: Aktion der Altium-Seite (`useAltiumActions`) bzw. die Seite selbst */
  next?: { action: 'install' | 'refresh' | 'stopScript' | 'page'; label: string }
}

/**
 * Zeile „Altium“ der Erfolgsansichten von Serien-Assistent und Datenblatt-Import – aus dem echten Zustand
 * (`GET /api/altium/status`): Ist **diese** DbLib in Altium installiert (`dblib.installed_in_altium`, gleichnamige
 * DbLibs)? Läuft bzw. folgt die automatische Aktualisierung, oder wurde sie übersprungen (`refresh.last_skip_reason` bei
 * wartender Änderung: ausgeschaltet, Prüfung gescheitert …)? Ohne Installation endet die Aktualisierung still („nicht
 * installiert – nichts zu aktualisieren“) – dann sagt die Zeile das und bietet „In Altium installieren“ an.
 */
export function altiumAfterWrite(status: AltiumStatus | undefined): AfterWriteNotice | null {
  if (!status) return null
  const { refresh, dblib } = status
  const file = dblib?.file_name ? `„${dblib.file_name}“` : tr("dieser Bibliothek")
  const installed = dblib?.installed_in_altium ?? null
  const refreshNext = { action: 'refresh', label: tr("In Altium aktualisieren") } as const
  if (status.bridge_wedged) {
    return {
      tone: 'error',
      text: tr("Das Altium-Skript hängt – erst das angehaltene Skript beenden, danach aktualisieren."),
      next: { action: 'stopScript', label: tr("Skript anhalten") },
    }
  }
  if (!status.altium_running) {
    return {
      tone: 'off',
      text:
        installed === false
          ? tr("Altium Designer läuft nicht. Laut letzter Prüfung ist die DbLib {0} dort nicht installiert – nach dem Start „In Altium installieren“ wählen.", { "0": String(file) })
          : tr("Altium Designer läuft nicht – beim nächsten Start sind die Bauteile in der DbLib."),
    }
  }
  if (dblibIssue(dblib, 'duplicates')) {
    return {
      tone: 'warn',
      text: installed
        ? tr("In Altium ist neben der DbLib {0} eine gleichnamige weitere installiert – Altium verwendet die zuerst installierte.", { "0": String(file) })
        : tr("Die DbLib {0} ist in Altium nicht installiert, aber eine gleichnamige andere – die neuen Bauteile erscheinen dort nicht.", { "0": String(file) }),
      next: { action: 'page', label: tr("Zur Altium-Seite") },
    }
  }
  if (installed === false) {
    return {
      tone: 'warn',
      text: tr("Die DbLib {0} ist in Altium nicht installiert – die neuen Bauteile erscheinen dort erst nach dem Installieren.", { "0": String(file) }),
      next: { action: 'install', label: tr("In Altium installieren") },
    }
  }
  // eine wartende Änderung mit Grund wurde übersprungen (z. B. Prüfung gescheitert) – sie kommt nicht von selbst
  const skipped = refresh.pending && Boolean(refresh.last_skip_reason)
  if (refresh.running || refresh.manual_pending || (refresh.pending && refresh.auto_refresh && !skipped)) {
    return {
      tone: 'busy',
      text: installed
        ? tr("Altium Designer wird aktualisiert – die neuen Bauteile erscheinen gleich im Bauteilbrowser.")
        : tr("Altium Designer wird aktualisiert – PartForge prüft dabei, ob die DbLib dort installiert ist."),
    }
  }
  if (installed && refresh.last_error) {
    return { tone: 'warn', text: tr("Altium Designer konnte nicht aktualisiert werden – die neuen Bauteile fehlen dort evtl. noch."), next: refreshNext }
  }
  if (installed && refresh.auto_refresh && !skipped) {
    return { tone: 'ok', text: tr("Altium Designer läuft – PartForge aktualisiert die Bibliothek dort automatisch.") }
  }
  return { tone: 'manual', text: tr("Altium Designer läuft – die neuen Bauteile erscheinen nach dem Aktualisieren."), next: refreshNext }
}

// --------------------------------------------------------------------------- Prüfung in Altium: Parameter

/** Zeile der Parameterliste eines in Altium geprüften Bauteils (E2EREG-3) */
export interface ParameterRow {
  name: string
  /** Wert in Altium (`null` = Altium liefert den Parameter nicht) */
  altium: string | null
  /** Wert in der Datenbank, nur bei Abweichung (`null` = Feld leer) */
  database: string | null
  /** same = wie in der Datenbank · diff = weicht ab · extra = kein Datenbankfeld · unchecked = nicht verglichen */
  state: 'same' | 'diff' | 'extra' | 'unchecked'
  /** im Schaltplan sichtbar */
  visible: boolean
}

const parameterKey = (name: string) => name.trim().toLowerCase()

/** „Description“ – Altiums [Description], steht in der Ergebniszeile, nicht in der Parameterliste */
export const isDescriptionParameter = (name: string) => parameterKey(name) === 'description'

/**
 * Parameterliste eines geprüften Bauteils (`partforge.altium.verify.compare_parameters`): Altiums Parameter in
 * Altiums Reihenfolge – gleich, abweichend (mit dem Wert der Datenbank) oder kein Datenbankfeld –, danach die
 * Datenbankfelder, die Altium nicht liefert. Ohne Vergleich (`parameters_checked` 0, älteres Ergebnis) „unchecked“.
 */
export function parameterRows(
  p: Pick<VerifiedPart, 'parameters' | 'parameter_diffs' | 'extra_parameters' | 'parameters_checked' | 'visible_parameters'>,
): ParameterRow[] {
  const diffs = new Map(
    (p.parameter_diffs ?? []).filter((d) => !isDescriptionParameter(d.parameter)).map((d) => [parameterKey(d.parameter), d] as const),
  )
  const extra = new Set((p.extra_parameters ?? []).map(parameterKey))
  const visible = new Set((p.visible_parameters ?? []).map(parameterKey))
  const rows: ParameterRow[] = Object.entries(p.parameters ?? {}).map(([name, value]) => {
    const diff = diffs.get(parameterKey(name))
    diffs.delete(parameterKey(name))
    return {
      name,
      altium: value.trim() ? value : null, // leer = wie nicht geliefert (AddMode 3)
      database: diff ? (diff.database ?? null) : null,
      state: diff ? 'diff' : extra.has(parameterKey(name)) ? 'extra' : (p.parameters_checked ?? 0) > 0 ? 'same' : 'unchecked',
      visible: visible.has(parameterKey(name)),
    }
  })
  for (const d of diffs.values()) {
    rows.push({ name: d.parameter, altium: d.altium ?? null, database: d.database ?? null, state: 'diff', visible: false })
  }
  return rows
}

/**
 * Geschätzte Dauer der Prüfung in Altium: Altium löst bis zu 50 Bauteile je Skriptlauf auf – etwa 1,6 s je Lauf plus
 * 67 ms je Bauteil, dazu rund 2,6 s Vorbereitung (Installationsstatus, Aktualisieren). Gemessen in `altium-e2e.md`
 * („Batch verification“): 45 Bauteile 7,5 s, 1000 Bauteile etwa 100 s.
 */
export function verifyEstimate(parts: number): string {
  const n = Math.max(1, parts)
  const seconds = 2.6 + Math.ceil(n / 50) * 1.6 + n * 0.067
  if (seconds < 55) return tr("etwa {0} s", { "0": String(Math.max(5, Math.round(seconds / 5) * 5)) })
  const minutes = Math.round(seconds / 60)
  return minutes < 90 ? tr("etwa {0} min", { "0": String(formatNumber(Math.max(1, minutes))) }) : tr("etwa {0} h", { "0": String(formatNumber(Math.round(minutes / 6) / 10)) })
}

/**
 * Größe der Stichprobe von „In Altium prüfen“ (`sample: 'spread'`): über alle für Altium aktivierten Kategorien
 * verteilt, anteilig zu ihrer Größe, mindestens ein Bauteil je Kategorie – deterministisch (dieselbe Bibliothek ergibt
 * dieselbe Stichprobe).
 */
export const VERIFY_SAMPLE = 20

/**
 * Wie viele Bauteile die Stichprobe tatsächlich umfasst (`partforge.altium.verify.sample_quotas`): alle, wenn es nicht
 * mehr als `limit` gibt; sonst `limit` – bei mehr Kategorien als `limit` eines je Kategorie (also mehr als `limit`).
 */
export function verifySampleSize(categorySizes: readonly number[], limit = VERIFY_SAMPLE): number {
  const filled = categorySizes.filter((n) => n > 0)
  const total = filled.reduce((a, b) => a + b, 0)
  if (total <= limit) return total
  return Math.max(limit, filled.length)
}

// --------------------------------------------------------------------------- Kette und Schlagzeile

export interface PageModel {
  nodes: ChainNode[]
  headline: Headline
  dblib: DblibSummary
  files: FilesSummary | null
  altium: AltiumSummary
}

export interface ModelInput {
  status: AltiumStatus | undefined
  /** Status konnte nicht gelesen werden (deutscher Grund) */
  statusError?: string | null
  files: LibraryFile[] | undefined
  /** Dateiliste konnte nicht gelesen werden */
  filesError?: string | null
  backend: LibraryBackend | undefined
  partCount: number | undefined
  dbKind: 'sqlite' | 'postgres' | undefined
  dbFile: string | undefined
  /** Fehler/Warnungen der Datenebene mit Bauteil (`partFindings`) – Glied „Bauteile“ */
  findings?: { errors: number; warnings: number } | null
  /** Prüfbericht konnte gar nicht erstellt werden (beide Prüfungen gescheitert) */
  findingsError?: string | null
  /** Fehler aller Prüfungen zusammen (Schlagzeile „Prüfbericht“) */
  reportErrors?: number
  /** Bauteile mit ungültigem Verweis auf Bibliothek bzw. Eintrag (Dateiprüfung) – Glied „Bibliotheksdateien“ */
  linkErrors?: number
  /** Footprints ohne Höhe in der PcbLib (Dateiprüfung) – davon mit Ein-Klick-Korrektur */
  heights?: { total: number; repairable: number }
}

export function buildModel(input: ModelInput): PageModel {
  const { status, files, backend, partCount, dbKind, findings } = input
  const statusError = status ? null : (input.statusError ?? null)
  const filesError = files ? null : (input.filesError ?? null)
  const dblibStatus = status?.dblib
  const dblib = summarizeDblib(dblibStatus, { loaded: Boolean(status), error: statusError })
  const filesSum = summarizeFiles(files, input.linkErrors ?? 0, input.heights)
  const altium = summarizeAltium(status, statusError)
  const writer = writerLabel(status, backend)
  /** Writer-Status bekannt und kein Writer bereit – „Synchronisieren“ schlüge fehl */
  const writerMissing = Boolean(status) && !writer.ok
  const odbc = missingOdbcDriver(status)

  // --- Glied 1: Bauteile (Datenbank + Befunde der Datenebene)
  const dbIssue = dblibIssue(dblibStatus, 'wal', 'network', 'db_missing')
  const kind = (dbKind ?? dblibStatus?.db_kind) === 'postgres' ? 'PostgreSQL' : 'SQLite'
  const dbText = dbIssue
    ? `${kind} ${dbIssue.code === 'wal' ? tr("ohne WAL") : dbIssue.code === 'network' ? tr("auf Netzlaufwerk") : tr("fehlt")}`
    : kind === 'SQLite'
      ? 'SQLite · WAL'
      : 'PostgreSQL'
  const partsText = partCount === undefined ? (input.dbFile ?? tr("Datenbank")) : plural(partCount, tr("Bauteil"), tr("Bauteile"))
  const errors = findings?.errors ?? 0
  const warnings = findings?.warnings ?? 0
  const empty = partCount === 0
  const findingsError = findings ? null : (input.findingsError ?? null)
  const partsNode: ChainNode = empty && !dbIssue
    ? { key: 'parts', label: tr("Bauteile"), value: tr("Noch keine"), detail: dbText, level: 'off' }
    : findingsError && !dbIssue
      ? {
          key: 'parts',
          label: tr("Bauteile"),
          value: partsText,
          detail: tr("Prüfung nicht verfügbar"),
          level: 'warn',
          emphasis: 'detail',
          fix: { action: 'check', label: tr("Erneut prüfen") },
        }
      : {
        key: 'parts',
        label: tr("Bauteile"),
        value: dbIssue ? dbText : errors ? plural(errors, tr("Fehler"), tr("Fehler")) : warnings ? plural(warnings, tr("Warnung"), tr("Warnungen")) : partsText,
        detail: dbIssue || errors || warnings ? `${partsText} · ${dbText}` : dbText,
        level: dbIssue || errors ? 'error' : warnings ? 'warn' : status || statusError || findings ? 'ok' : 'off',
        fix: !dbIssue && (errors || warnings) ? { action: 'report', label: tr("Zum Prüfbericht") } : undefined,
        }

  // --- Glied 2: DbLib (Altium liest sie über den ODBC-Treiber – fehlt er, ist das Glied nicht in Ordnung)
  const dblibNode: ChainNode =
    odbc && dblib.level !== 'error'
      ? {
          key: 'dblib',
          label: 'DbLib',
          value: dblib.value,
          detail: tr("ODBC-Treiber fehlt – Altium kann die Datenbank nicht lesen"),
          level: 'warn',
          emphasis: 'detail',
          fix: { action: 'odbc', label: tr("ODBC testen") },
        }
      : {
          key: 'dblib',
          label: 'DbLib',
          value: dblib.value,
          detail: dblib.detail,
          level: dblib.level,
          fix: dblib.fix === 'regenerate' ? { action: 'regenerate', label: tr("Neu erzeugen") } : undefined,
        }

  // --- Glied 3: Bibliotheksdateien
  const filesNode: ChainNode = filesError
    ? {
        key: 'files',
        label: tr("Bibliotheksdateien"),
        value: tr("Nicht verfügbar"),
        detail: shortReason(filesError),
        level: 'off',
        fix: { action: 'reload', label: tr("Erneut versuchen") },
      }
    : {
        key: 'files',
        label: tr("Bibliotheksdateien"),
        value: filesSum?.value ?? tr("Wird geprüft …"),
        detail: filesSum?.detail ?? '',
        level: filesSum?.level ?? 'off',
        fix:
          filesSum && (filesSum.pending || filesSum.errors || filesSum.missingFiles)
            ? writerMissing
              ? { action: 'writer', label: tr("Writer einrichten") }
              : { action: 'sync', label: tr("Synchronisieren") }
            : filesSum?.damaged
              ? { action: 'report', label: tr("Zum Prüfbericht") }
              : filesSum && (filesSum.absent || filesSum.outside)
              ? { action: 'scanSync', label: tr("Prüfen und synchronisieren") }
              : filesSum?.links
                ? { action: 'report', label: tr("Zum Prüfbericht") }
                : // nur, wenn das Glied die fehlenden Höhen auch nennt (Lagen/Lesbarkeit gehen in der Anzeige vor)
                  filesSum?.heightsRepairable && !filesSum.layersOff && !filesSum.unreadable
                  ? { action: 'repairHeights', label: tr("Höhen nachtragen") }
                  : undefined,
      }

  // --- Glied 4: Altium
  const altiumNode: ChainNode = {
    key: 'altium',
    label: 'Altium Designer',
    value: altium.value,
    detail: altium.detail,
    level: altium.level,
    fix: altium.fix,
    emphasis: altium.emphasis,
  }

  return {
    nodes: [partsNode, dblibNode, filesNode, altiumNode],
    headline: headline({
      status,
      statusError,
      dblib,
      files: filesSum,
      altium,
      writerOk: !writerMissing,
      odbc,
      reportErrors: input.reportErrors ?? 0,
      findingsError,
      empty,
    }),
    dblib,
    files: filesSum,
    altium,
  }
}

/**
 * Nächster Schritt – wo die Kette reißt, gewinnt die erste Bruchstelle: hängendes Skript, gleichnamige DbLib, DbLib
 * fehlerhaft oder veraltet, ODBC-Treiber fehlt, Dateien fehlen oder scheitern (ohne Bibliotheks-Writer: „Writer
 * einrichten“ statt „Synchronisieren“), (leere Bibliothek,) Altium läuft ohne geprüfte bzw. ohne Installation,
 * ausstehende Dateien, Aktualisieren gescheitert. Erst danach Fehler des Prüfberichts. „Alles bereit“ nur, wenn nichts
 * davon zutrifft.
 */
function headline(m: {
  status: AltiumStatus | undefined
  statusError: string | null
  dblib: DblibSummary
  files: FilesSummary | null
  altium: AltiumSummary
  writerOk: boolean
  /** fehlender ODBC-Treiber (sonst `null`) */
  odbc: OdbcDriverStatus | null
  reportErrors: number
  findingsError: string | null
  empty: boolean
}): Headline {
  const { status, dblib, files, altium } = m
  if (!status) {
    if (m.statusError) {
      return {
        tone: 'danger',
        eyebrow: tr("Status nicht verfügbar"),
        title: tr("Der Altium-Status konnte nicht gelesen werden"),
        text: tr("{0}. PartForge fragt alle 15 Sekunden erneut nach.", { "0": String(m.statusError.replace(/[.\s]+$/, '')) }),
        primary: 'reload',
      }
    }
    return { tone: 'neutral', eyebrow: 'Status', title: tr("Verbindung wird geprüft …"), text: tr("PartForge liest den Zustand von DbLib, Bibliotheksdateien und Altium."), primary: null }
  }
  const dblibStatus = status.dblib
  const running = status.altium_running

  // 1. Skript hängt
  if (status.bridge_wedged) {
    const step = typeof status.bridge_wedged.last_step === 'string' ? tr(" (letzter Schritt: {0})", { "0": String(status.bridge_wedged.last_step) }) : ''
    return {
      tone: 'danger',
      eyebrow: tr("Altium reagiert nicht"),
      title: tr("Ein PartForge-Skript hängt in Altium"),
      text: tr("Das letzte Skript wurde nicht beendet{0}. „Skript anhalten“ beendet es in Altium (ohne Tastatur oder Fenster) und prüft, ob Skripte wieder laufen – danach die Aktion erneut starten.", { "0": String(step) }),
      primary: running ? 'stopScript' : null,
    }
  }
  // 2. Gleichnamige DbLib
  const duplicates = dblibIssue(dblibStatus, 'duplicates')
  if (duplicates) {
    return {
      tone: 'danger',
      eyebrow: tr("Gleichnamige DbLib"),
      title: tr("Altium kennt mehrere DbLibs mit diesem Namen"),
      text: localizeMessage(duplicates.message),
      primary: duplicatesReplaceable(dblibStatus) && running ? 'installReplace' : null,
    }
  }
  // 3. DbLib fehlerhaft
  if (dblib.level === 'error') {
    const code = dblib.issue?.code ?? ''
    const problem = DBLIB_PROBLEM[code]
    let text = dblib.issue?.message ? localizeMessage(dblib.issue.message) : tr("Ohne gültige DbLib findet Altium keine Bauteile.")
    if (code === 'missing') {
      text = tr("Ohne „{0}“ findet Altium keine Bauteile. „DbLib neu erzeugen“ legt sie im Bibliotheksordner an.", { "0": String(dblibStatus?.file_name ?? 'DbLib') })
    } else if (problem?.strip && text.includes(' – ')) {
      const rest = text.slice(text.indexOf(' – ') + 3)
      text = rest.charAt(0).toUpperCase() + rest.slice(1)
    }
    return { tone: 'danger', eyebrow: 'DbLib', title: problem?.title ?? tr("Die DbLib hat ein Problem"), text, primary: dblib.fix ?? null }
  }
  // 4. DbLib veraltet
  if (dblib.level === 'warn' && dblib.fix === 'regenerate') {
    const followUp = running && status.refresh.auto_refresh ? tr(" – das laufende Altium liest ihn danach selbst ein") : ''
    return {
      tone: 'warning',
      eyebrow: 'DbLib',
      title: tr("Die DbLib ist veraltet"),
      text:
        dblib.issue?.code === 'format'
          ? tr("Die Datei ist nicht im Altium-Format gespeichert (Windows-1252, CRLF, ohne BOM). „Neu erzeugen“ schreibt sie so, wie Altium sie erwartet.")
          : tr("{0}. „Neu erzeugen“ schreibt den aktuellen Stand{1}.", { "0": String(dblib.detail), "1": String(followUp) }),
      primary: 'regenerate',
    }
  }
  // 5. ODBC-Treiber fehlt: Altium kann die Datenbank nicht lesen – auch wenn DbLib und Dateien bereit sind
  if (m.odbc) {
    const sqlite = m.odbc.kind ? m.odbc.kind === 'sqlite' : /sqlite/i.test(m.odbc.driver)
    return {
      tone: 'warning',
      eyebrow: tr("ODBC-Treiber"),
      title: tr("Der ODBC-Treiber „{0}“ fehlt", { "0": String(m.odbc.driver) }),
      text: tr("Altium liest die Bibliothek über ODBC – ohne den 64-Bit-Treiber findet Altium keine Bauteile, auch wenn DbLib und Bibliotheksdateien bereit sind. {0}, danach „ODBC testen“.", { "0": String(sqlite ? tr("Den SQLite-ODBC-Treiber (sqliteodbc_w64) installieren") : tr("Den 64-Bit-Treiber psqlODBC installieren")) }),
      primary: 'odbc',
      link: odbcDriverLink(m.odbc),
    }
  }
  // 6. Bibliotheksdateien fehlen oder scheitern – ohne Bibliotheks-Writer hilft „Synchronisieren“ nicht
  if (files && (files.missingFiles || files.errors)) {
    return {
      tone: 'danger',
      eyebrow: tr("Bibliotheksdateien"),
      title: files.missingFiles ? tr("Bibliotheksdateien fehlen") : tr("Einträge konnten nicht geschrieben werden"),
      text: m.writerOk
        ? tr("Altium findet betroffene Symbole und Footprints erst, wenn sie in den SchLib-/PcbLib-Dateien stehen. „Synchronisieren“ schreibt sie neu.")
        : tr("Altium findet betroffene Symbole und Footprints erst, wenn sie in den SchLib-/PcbLib-Dateien stehen. Dafür braucht PartForge einen Bibliotheks-Writer – {0}.", { "0": String(writerRemedy()) }),
      primary: m.writerOk ? 'sync' : 'writer',
    }
  }
  // Leere Bibliothek: erst Bauteile anlegen
  if (m.empty) {
    return {
      tone: 'info',
      eyebrow: tr("Erste Schritte"),
      title: tr("Noch keine Bauteile in der Bibliothek"),
      text: tr("Der Serien-Assistent legt eine ganze Widerstands- oder Kondensatorserie an – mit Symbolen und Footprints. DbLib und Bibliotheksdateien entstehen dabei automatisch."),
      primary: 'series',
    }
  }
  // 7. Altium läuft – Installation ungeprüft bzw. fehlt
  if (running && altium.installed === null) {
    return {
      tone: 'info',
      eyebrow: tr("Altium läuft"),
      title: tr("Ist die DbLib in Altium installiert?"),
      text: tr("PartForge fragt Altium nur auf Wunsch – „Status prüfen“ liest die installierten Bibliotheken (dauert wenige Sekunden)."),
      primary: 'installState',
    }
  }
  if (running && !altium.installed) {
    // nicht „noch nicht“: auch nach „Aus Altium deinstallieren“ zutreffend (E2E-Regression, Wortlaut)
    return {
      tone: 'warning',
      eyebrow: tr("Altium läuft"),
      title: tr("Die DbLib ist in Altium nicht installiert"),
      text: tr("Nach dem Installieren stehen alle Bauteile im Components-Panel von Altium bereit und bleiben automatisch aktuell."),
      primary: 'install',
    }
  }
  // 8. Ausstehende bzw. fehlende Einträge in den Dateien
  if (files && files.pending) {
    return {
      tone: 'warning',
      eyebrow: tr("Bibliotheksdateien"),
      title: tr("{0} auf das Schreiben", { "0": String(plural(files.pending, tr("Eintrag wartet"), tr("Einträge warten"))) }),
      text: m.writerOk
        ? tr("Neue oder geänderte Symbole und Footprints stehen erst nach dem Synchronisieren in den SchLib-/PcbLib-Dateien.")
        : `${writerMissingText()}.`,
      primary: m.writerOk ? 'sync' : 'writer',
    }
  }
  if (files && (files.absent || files.outside)) {
    return {
      tone: 'warning',
      eyebrow: tr("Bibliotheksdateien"),
      title: files.absent ? tr("{0} in den Dateien", { "0": String(plural(files.absent, tr("Eintrag fehlt"), tr("Einträge fehlen"))) }) : tr("Dateien wurden außerhalb geändert"),
      text: files.absent
        ? tr("Registrierte Symbole oder Footprints stehen nicht mehr in ihren Dateien. „Prüfen und synchronisieren“ schreibt sie neu.")
        : tr("Seit PartForges letztem Schreiben wurden Dateien geändert (z. B. in Altium gespeichert). PartForge schreibt dort nur noch geänderte Einträge."),
      primary: 'scanSync',
    }
  }
  // 9. Aktualisieren gescheitert
  if (running && altium.installed && status.refresh.last_error) {
    return {
      tone: 'warning',
      eyebrow: tr("Aktualisierung"),
      title: tr("Altium zeigt evtl. nicht den aktuellen Stand"),
      text: status.refresh.last_error,
      primary: 'refresh',
    }
  }
  // 10. Fehler im Prüfbericht
  if (m.reportErrors) {
    return {
      tone: 'danger',
      eyebrow: tr("Prüfbericht"),
      title: tr("{0} im Prüfbericht", { "0": String(plural(m.reportErrors, tr("Fehler"), tr("Fehler"))) }),
      text: tr("Je Befund nennt der Prüfbericht Ursache und Lösungsweg – und behebt mit einem Klick, was PartForge selbst beheben kann."),
      primary: 'report',
    }
  }
  // 11. Footprint-Höhen fehlen (vor dem Höhen-Patch geschriebene PcbLibs) – mit Ein-Klick-Korrektur
  if (files && files.heightsRepairable) {
    return {
      tone: 'warning',
      eyebrow: tr("Bibliotheksdateien"),
      title: tr("{0} ohne Bauhöhe in der PcbLib", { "0": String(plural(files.heights, 'Footprint', 'Footprints')) }),
      text: tr("Eine ältere PartForge-Version hat sie mit der Höhe 0 geschrieben – Altium kennt ihre Bauhöhe dann nicht (3D-Abstände, Höhenregeln). „Footprint-Höhen nachtragen“ schreibt sie mit ihrer Höhe neu."),
      primary: 'repairHeights',
    }
  }
  if (m.findingsError) {
    return {
      tone: 'warning',
      eyebrow: tr("Prüfbericht"),
      title: tr("Die Bibliothek konnte nicht geprüft werden"),
      text: tr("{0}. Ohne Prüfung zeigt PartForge keine Fehler und Warnungen der Bauteile – „Erneut prüfen“ versucht es noch einmal.", { "0": String(m.findingsError.replace(/[.\s]+$/, '')) }),
      primary: 'check',
    }
  }
  if (!status.altium_exe) {
    return {
      tone: 'neutral',
      eyebrow: 'Altium Designer',
      title: tr("Altium Designer wurde nicht gefunden"),
      text: tr("DbLib und Bibliotheksdateien sind bereit. Für Installieren, Aktualisieren und Prüfen in Altium den Pfad zu X2.EXE unter {0} festlegen.", { "0": String(SETTINGS_PLACE.altium.label) }),
      primary: 'settings',
    }
  }
  if (!running) {
    return {
      tone: 'neutral',
      eyebrow: tr("Bereit für Altium"),
      title: tr("Alles bereit – Altium ist nicht gestartet"),
      text: tr("DbLib und Bibliotheksdateien sind aktuell. Sobald Altium Designer läuft, lässt sich die DbLib installieren, aktualisieren und in Altium prüfen."),
      primary: null,
    }
  }
  if (status.refresh.pending || status.refresh.manual_pending) {
    // ohne automatische Aktualisierung wartet nichts – die Änderungen bleiben liegen, bis jemand aktualisiert
    if (!status.refresh.auto_refresh && !status.refresh.running && !status.refresh.manual_pending) {
      return {
        tone: 'info',
        eyebrow: tr("Aktualisierung"),
        title: tr("Altium kennt noch nicht alle Änderungen"),
        text: tr("Die automatische Aktualisierung ist ausgeschaltet. „In Altium aktualisieren“ lässt Altium die Bibliothek neu lesen."),
        primary: 'refresh',
      }
    }
    return {
      tone: 'info',
      eyebrow: tr("Aktualisierung"),
      title: tr("Änderungen werden an Altium übergeben …"),
      text: tr("PartForge wartet einen Moment, bis keine weiteren Änderungen folgen, und lässt Altium dann neu lesen."),
      primary: 'refresh',
    }
  }
  const last = lastRefreshText(status)
  return {
    tone: 'success',
    eyebrow: tr("Alles verbunden"),
    title: tr("Altium sieht den aktuellen Stand"),
    text: tr("Bauteile lassen sich direkt aus dem Components-Panel platzieren{0}. „In Altium prüfen“ lässt Altium jedes Bauteil auflösen – wie beim Platzieren.", { "0": String(last ? tr(" (zuletzt aktualisiert {0})", { 0: String(last) }) : '') }),
    primary: 'verify',
  }
}

/** Warum eine Altium-Aktion gerade nicht geht (Tooltip am gesperrten Knopf) – `null` = Altium bereit */
export function altiumBlocker(status: AltiumStatus | undefined, statusError?: string | null): string | null {
  if (!status) return statusError ? tr("Altium-Status nicht verfügbar – erst „Erneut versuchen“") : tr("Altium-Status wird geprüft …")
  if (!status.altium_exe) return tr("Altium Designer nicht gefunden – Pfad zu X2.EXE unter {0} festlegen", { "0": String(SETTINGS_PLACE.altium.label) })
  if (!status.altium_running) return tr("Altium Designer starten – Installieren, Aktualisieren und Prüfen brauchen ein laufendes Altium Designer")
  if (status.bridge_wedged) return tr("Ein PartForge-Skript hängt in Altium – erst „Skript anhalten“ wählen")
  return null
}
