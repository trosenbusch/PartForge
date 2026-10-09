/**
 * Zustandsmodell der Altium-Seite (rein, ohne React): aus Altium-Status, Bibliotheksdateien, Prüfbericht und
 * Einstellungen entstehen die Glieder der Kette „Bauteile → DbLib → Bibliotheksdateien → Altium“, die Schlagzeile und
 * der nächste sinnvolle Schritt (die eine Primäraktion der Seite). Auch die Übersicht nutzt diese Ableitungen.
 *
 * Jedes Glied zeigt seinen Grund **im Text** (Detailzeile) – keine Erklärung nur im Tooltip.
 */
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
  const clean = text.replace(/\s+/g, ' ').trim()
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()} …` : clean
}

// --------------------------------------------------------------------------- DbLib

const REGENERATE_CODES = new Set(['missing', 'outdated', 'format', 'db_path', 'unreadable', 'parse'])
/** Befunde, die kein Neuschreiben behebt (Datenbank, Netzlaufwerk, Namen, Installation) */
const BLOCKING_CODES = new Set(['wal', 'network', 'db_missing', 'db_path_chars', 'file_name', 'build', 'library_ref', 'unsafe_name'])

/** Kurzer Grund je DbLib-Befund (Detailzeile des Glieds) */
const DBLIB_REASON: Record<string, string> = {
  missing: 'Datei fehlt im Bibliotheksordner',
  outdated: 'Kategorien oder Felder geändert',
  format: 'Nicht im Altium-Format gespeichert',
  db_path: 'Verweist auf eine andere Datenbank',
  unreadable: 'Datei nicht lesbar',
  parse: 'Auffälligkeit beim Lesen',
  wal: 'Datenbank nicht im WAL-Modus',
  network: 'Datenbank auf einem Netzlaufwerk',
  db_missing: 'Datenbankdatei fehlt',
  db_path_chars: 'Datenbankpfad für Altium ungeeignet',
  file_name: 'Ungültiger Dateiname',
  build: 'Soll-Stand unbekannt',
  library_ref: 'Tabelle ohne Spalte „Library Ref“',
  unsafe_name: 'Name für Altium ungeeignet',
  no_key: 'Kategorie ohne Schlüsselspalte',
  encoding: 'Zeichen außerhalb von Windows-1252',
  no_enabled_tables: 'Keine Tabelle für Altium aktiviert',
  open_in_editor: 'In Altium im Editor geöffnet',
}

/** Schlagzeile je DbLib-Fehler; `strip` = der Meldung den ersten Satzteil („… – “) nehmen, er wiederholt den Titel */
const DBLIB_PROBLEM: Record<string, { title: string; strip?: boolean }> = {
  missing: { title: 'Die DbLib fehlt' },
  unreadable: { title: 'Die DbLib ist nicht lesbar' },
  db_path: { title: 'Die DbLib verweist auf eine andere Datenbank' },
  wal: { title: 'Die Datenbank ist nicht im WAL-Modus', strip: true },
  network: { title: 'Die Datenbank liegt auf einem Netzlaufwerk', strip: true },
  db_missing: { title: 'Die Datenbankdatei fehlt' },
  db_path_chars: { title: 'Der Datenbankpfad ist für Altium ungeeignet' },
  file_name: { title: 'Der DbLib-Dateiname ist ungültig' },
  build: { title: 'Der Soll-Stand der DbLib ist unbekannt' },
  library_ref: { title: 'Eine Kategorie ist für Altium unvollständig' },
  unsafe_name: { title: 'Ein Name ist für die DbLib ungeeignet' },
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
    const inner = /\(([^)]+)\)/.exec(issue.message)?.[1]
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
    if (state.error) return { level: 'off', value: 'Nicht verfügbar', detail: shortReason(state.error) }
    return state.loaded
      ? { level: 'off', value: 'Unbekannt', detail: 'Keine Bibliothek geöffnet' }
      : { level: 'off', value: 'Wird geprüft …', detail: '' }
  }
  const tables = dblib.enabled_tables.length
  const facts = `${plural(tables, 'Tabelle', 'Tabellen')} · ${plural(dblib.field_maps, 'Feld', 'Felder')}`
  const errors = dblib.issues.filter((i) => i.severity === 'error' && i.code !== 'duplicates')
  if (!dblib.exists) {
    return { level: 'error', value: 'Fehlt', detail: `„${dblib.file_name}“ nicht im Bibliotheksordner`, issue: dblibIssue(dblib, 'missing'), fix: 'regenerate' }
  }
  const blocking = errors.find((i) => BLOCKING_CODES.has(i.code))
  if (blocking) return { level: 'error', value: 'Fehlerhaft', detail: reasonOf(blocking) ?? facts, issue: blocking }
  const fixable = errors.find((i) => REGENERATE_CODES.has(i.code))
  if (fixable) {
    return {
      level: 'error',
      value: fixable.code === 'db_path' ? 'Falsche Datenbank' : 'Fehlerhaft',
      detail: reasonOf(fixable) ?? facts,
      issue: fixable,
      fix: 'regenerate',
    }
  }
  if (!dblib.up_to_date) {
    const issue = dblibIssue(dblib, 'outdated', 'format')
    return { level: 'warn', value: 'Veraltet', detail: reasonOf(issue) ?? facts, issue, fix: 'regenerate' }
  }
  const warning = dblib.issues.find((i) => i.severity === 'warning' && !['moved_install', 'open_in_editor'].includes(i.code))
  if (warning) return { level: 'warn', value: 'Aktuell', detail: reasonOf(warning) ?? facts, issue: warning }
  return { level: 'ok', value: 'Aktuell', detail: facts }
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
  let value = 'Synchron'
  let detail = facts
  if (s.total === 0) {
    level = 'off'
    value = 'Noch keine Dateien'
    detail = 'entstehen mit den ersten Bauteilen'
  } else if (s.missingFiles) {
    level = 'error'
    value = s.missingFiles === 1 ? '1 Datei fehlt' : `${formatNumber(s.missingFiles)} Dateien fehlen`
    const names = files.filter((f) => !f.exists).map((f) => baseName(f.rel))
    detail = names.slice(0, 2).join(', ') + (names.length > 2 ? ' …' : '')
  } else if (s.damaged) {
    level = 'error'
    value = s.damaged === 1 ? '1 Datei beschädigt' : `${formatNumber(s.damaged)} Dateien beschädigt`
    const names = files.filter((f) => f.exists && f.unreadable).map((f) => baseName(f.rel))
    detail = `nicht lesbar: ${names.slice(0, 2).join(', ')}${names.length > 2 ? ' …' : ''}`
  } else if (s.errors) {
    level = 'error'
    value = plural(s.errors, 'Fehler', 'Fehler')
    detail = 'Schreiben fehlgeschlagen'
  } else if (s.pending) {
    level = 'warn'
    value = `${formatNumber(s.pending)} ausstehend`
    detail = 'warten auf das Schreiben'
  } else if (s.absent) {
    level = 'warn'
    value = plural(s.absent, 'Eintrag fehlt', 'Einträge fehlen')
    detail = 'registriert, aber nicht in der Datei'
  } else if (s.outside) {
    level = 'warn'
    value = `${formatNumber(s.outside)} außerhalb geändert`
    detail = 'z. B. in Altium gespeichert'
  } else if (s.links) {
    level = 'error'
    value = plural(s.links, 'Verweis ungültig', 'Verweise ungültig')
    detail = 'Bauteile verweisen auf Fehlendes'
  } else if (s.layersOff) {
    level = 'warn'
    value = 'Lagen abweichend'
    detail = plural(s.layersOff, 'PcbLib mit anderem Lagen-Kopf', 'PcbLibs mit anderem Lagen-Kopf')
  } else if (s.unreadable) {
    level = 'warn'
    value = `${formatNumber(s.unreadable)} nicht lesbar`
    detail = 'kein Bibliotheks-Writer oder Datei beschädigt'
  } else if (s.heights) {
    level = 'warn'
    value = plural(s.heights, 'Höhe fehlt', 'Höhen fehlen')
    detail = 'Footprints mit Bauhöhe 0 in der PcbLib'
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
  const rustLabel = `Bibliotheks-Writer${rust?.version ? ` ${rust.version}` : ''}`
  if (backend === 'altium') return { label: altium?.available ? 'Schreiben über Altium' : 'Altium nicht bereit', ok: Boolean(altium?.available) }
  if (backend === 'rust') return { label: rust?.available ? rustLabel : 'Bibliotheks-Writer fehlt', ok: Boolean(rust?.available) }
  if (rust?.available) return { label: rustLabel, ok: true }
  if (altium?.available) return { label: 'Schreiben über Altium', ok: true }
  return { label: 'Kein Bibliotheks-Writer', ok: false }
}

/** Was zu tun ist, wenn kein Bibliotheks-Writer bereit ist (ohne Schlusspunkt) */
export const WRITER_REMEDY = `den Pfad zu altium-designer-mcp.exe unter ${SETTINGS_PLACE.altium.label} eintragen oder Altium Designer starten`

/** Was fehlt, damit Bibliotheksdateien entstehen – Satz für Hinweise und Toasts (ohne Schlusspunkt) */
export const WRITER_MISSING_TEXT = `Ohne Bibliotheks-Writer entstehen keine SchLib-/PcbLib-Dateien – ${WRITER_REMEDY}`

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
  return { label: `${sqlite ? 'SQLite-ODBC-Treiber' : 'ODBC-Treiber'} herunterladen (${host})`, href }
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
  if (hint) return message.includes(hint) ? message : [message, hint].filter(Boolean).join(' ')
  if (/verschiebbar|offen/i.test(message)) return message
  const names = [...new Set((r.database_holders ?? []).map((h) => h.name.trim()).filter(Boolean))]
  const held = names.length
    ? `${names.join(', ')} ${names.length === 1 ? 'hält' : 'halten'} die Datenbank noch offen`
    : 'Ein anderes Programm hält die Datenbank noch offen'
  return [message, `Ordner erst danach verschiebbar – ${held}.`].filter(Boolean).join(' ')
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
      ? { level: 'off', value: 'Nicht verfügbar', detail: shortReason(error), short: 'Status nicht verfügbar', running: false, installed: null }
      : { level: 'off', value: 'Wird geprüft …', detail: '', short: 'Altium wird geprüft …', running: false, installed: null }
  }
  const installed = status.dblib?.installed_in_altium ?? null
  const duplicates = dblibIssue(status.dblib, 'duplicates')
  const moved = dblibIssue(status.dblib, 'moved_install')
  const replaceable = duplicatesReplaceable(status.dblib)
  if (!status.altium_exe) {
    return {
      level: 'warn',
      value: 'Nicht gefunden',
      detail: 'X2.EXE nicht gefunden',
      short: 'Altium nicht gefunden',
      fix: { action: 'settings', label: 'Pfad festlegen' },
      running: false,
      installed,
    }
  }
  const version = status.version ? ` · ${status.version}` : ''
  if (!status.altium_running) {
    return {
      level: duplicates || moved ? 'warn' : 'off',
      value: 'Nicht gestartet',
      detail: duplicates
        ? 'Gleichnamige DbLib installiert'
        : moved
          ? 'Alte Installation aus anderem Ordner'
          : status.version
            ? `Altium Designer ${status.version}`
            : 'Altium Designer',
      emphasis: duplicates || moved ? 'detail' : undefined,
      short: 'Altium nicht gestartet',
      running: false,
      installed,
    }
  }
  const running = { running: true, installed, short: `Altium läuft${version}` }
  if (status.bridge_wedged) {
    return { ...running, level: 'error', value: `Skript hängt${version}`, detail: 'In Altium Strg+F3 drücken', short: 'Altium-Skript hängt' }
  }
  if (status.refresh.running) {
    return { ...running, level: 'busy', value: `Läuft${version}`, detail: 'Wird gerade aktualisiert …' }
  }
  if (duplicates) {
    return {
      ...running,
      level: 'error',
      value: `Läuft${version}`,
      detail: 'Gleichnamige DbLib aktiv',
      emphasis: 'detail',
      fix: replaceable ? { action: 'installReplace', label: 'Ersetzen und installieren' } : undefined,
    }
  }
  if (moved) {
    return {
      ...running,
      level: 'warn',
      value: `Läuft${version}`,
      detail: 'Alte Installation aus anderem Ordner',
      emphasis: 'detail',
      fix: { action: 'installReplace', label: 'Ersetzen und installieren' },
    }
  }
  if (installed === null) {
    return {
      ...running,
      level: 'ok',
      value: `Läuft${version}`,
      detail: 'Installation ungeprüft',
      emphasis: 'detail',
      fix: { action: 'installState', label: 'Status prüfen' },
    }
  }
  if (!installed) {
    return {
      ...running,
      level: 'warn',
      value: `Läuft${version}`,
      detail: 'DbLib nicht installiert',
      emphasis: 'detail',
      fix: { action: 'install', label: 'Installieren' },
    }
  }
  if (status.refresh.last_error) {
    return {
      ...running,
      level: 'warn',
      value: `Läuft${version}`,
      detail: 'Aktualisieren fehlgeschlagen',
      emphasis: 'detail',
      fix: { action: 'refresh', label: 'Erneut aktualisieren' },
    }
  }
  const last = lastRefreshText(status)
  return { ...running, level: 'ok', value: `Läuft${version}`, detail: last ? `Installiert · aktualisiert ${last}` : 'Installiert' }
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
  next?: { action: 'install' | 'refresh' | 'page'; label: string }
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
  const file = dblib?.file_name ? `„${dblib.file_name}“` : 'dieser Bibliothek'
  const installed = dblib?.installed_in_altium ?? null
  const refreshNext = { action: 'refresh', label: 'In Altium aktualisieren' } as const
  if (status.bridge_wedged) {
    return { tone: 'error', text: 'Das Altium-Skript hängt – in Altium Designer Strg+F3 drücken, danach aktualisieren.', next: refreshNext }
  }
  if (!status.altium_running) {
    return {
      tone: 'off',
      text:
        installed === false
          ? `Altium Designer läuft nicht. Laut letzter Prüfung ist die DbLib ${file} dort nicht installiert – nach dem Start „In Altium installieren“ wählen.`
          : 'Altium Designer läuft nicht – beim nächsten Start sind die Bauteile in der DbLib.',
    }
  }
  if (dblibIssue(dblib, 'duplicates')) {
    return {
      tone: 'warn',
      text: installed
        ? `In Altium ist neben der DbLib ${file} eine gleichnamige weitere installiert – Altium verwendet die zuerst installierte.`
        : `Die DbLib ${file} ist in Altium nicht installiert, aber eine gleichnamige andere – die neuen Bauteile erscheinen dort nicht.`,
      next: { action: 'page', label: 'Zur Altium-Seite' },
    }
  }
  if (installed === false) {
    return {
      tone: 'warn',
      text: `Die DbLib ${file} ist in Altium nicht installiert – die neuen Bauteile erscheinen dort erst nach dem Installieren.`,
      next: { action: 'install', label: 'In Altium installieren' },
    }
  }
  // eine wartende Änderung mit Grund wurde übersprungen (z. B. Prüfung gescheitert) – sie kommt nicht von selbst
  const skipped = refresh.pending && Boolean(refresh.last_skip_reason)
  if (refresh.running || refresh.manual_pending || (refresh.pending && refresh.auto_refresh && !skipped)) {
    return {
      tone: 'busy',
      text: installed
        ? 'Altium Designer wird aktualisiert – die neuen Bauteile erscheinen gleich im Bauteilbrowser.'
        : 'Altium Designer wird aktualisiert – PartForge prüft dabei, ob die DbLib dort installiert ist.',
    }
  }
  if (installed && refresh.last_error) {
    return { tone: 'warn', text: 'Altium Designer konnte nicht aktualisiert werden – die neuen Bauteile fehlen dort evtl. noch.', next: refreshNext }
  }
  if (installed && refresh.auto_refresh && !skipped) {
    return { tone: 'ok', text: 'Altium Designer läuft – PartForge aktualisiert die Bibliothek dort automatisch.' }
  }
  return { tone: 'manual', text: 'Altium Designer läuft – die neuen Bauteile erscheinen nach dem Aktualisieren.', next: refreshNext }
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
  if (seconds < 55) return `etwa ${Math.max(5, Math.round(seconds / 5) * 5)} s`
  const minutes = Math.round(seconds / 60)
  return minutes < 90 ? `etwa ${formatNumber(Math.max(1, minutes))} min` : `etwa ${formatNumber(Math.round(minutes / 6) / 10)} h`
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
    ? `${kind} ${dbIssue.code === 'wal' ? 'ohne WAL' : dbIssue.code === 'network' ? 'auf Netzlaufwerk' : 'fehlt'}`
    : kind === 'SQLite'
      ? 'SQLite · WAL'
      : 'PostgreSQL'
  const partsText = partCount === undefined ? (input.dbFile ?? 'Datenbank') : plural(partCount, 'Bauteil', 'Bauteile')
  const errors = findings?.errors ?? 0
  const warnings = findings?.warnings ?? 0
  const empty = partCount === 0
  const findingsError = findings ? null : (input.findingsError ?? null)
  const partsNode: ChainNode = empty && !dbIssue
    ? { key: 'parts', label: 'Bauteile', value: 'Noch keine', detail: dbText, level: 'off' }
    : findingsError && !dbIssue
      ? {
          key: 'parts',
          label: 'Bauteile',
          value: partsText,
          detail: 'Prüfung nicht verfügbar',
          level: 'warn',
          emphasis: 'detail',
          fix: { action: 'check', label: 'Erneut prüfen' },
        }
      : {
        key: 'parts',
        label: 'Bauteile',
        value: dbIssue ? dbText : errors ? plural(errors, 'Fehler', 'Fehler') : warnings ? plural(warnings, 'Warnung', 'Warnungen') : partsText,
        detail: dbIssue || errors || warnings ? `${partsText} · ${dbText}` : dbText,
        level: dbIssue || errors ? 'error' : warnings ? 'warn' : status || statusError || findings ? 'ok' : 'off',
        fix: !dbIssue && (errors || warnings) ? { action: 'report', label: 'Zum Prüfbericht' } : undefined,
        }

  // --- Glied 2: DbLib (Altium liest sie über den ODBC-Treiber – fehlt er, ist das Glied nicht in Ordnung)
  const dblibNode: ChainNode =
    odbc && dblib.level !== 'error'
      ? {
          key: 'dblib',
          label: 'DbLib',
          value: dblib.value,
          detail: 'ODBC-Treiber fehlt – Altium kann die Datenbank nicht lesen',
          level: 'warn',
          emphasis: 'detail',
          fix: { action: 'odbc', label: 'ODBC testen' },
        }
      : {
          key: 'dblib',
          label: 'DbLib',
          value: dblib.value,
          detail: dblib.detail,
          level: dblib.level,
          fix: dblib.fix === 'regenerate' ? { action: 'regenerate', label: 'Neu erzeugen' } : undefined,
        }

  // --- Glied 3: Bibliotheksdateien
  const filesNode: ChainNode = filesError
    ? {
        key: 'files',
        label: 'Bibliotheksdateien',
        value: 'Nicht verfügbar',
        detail: shortReason(filesError),
        level: 'off',
        fix: { action: 'reload', label: 'Erneut versuchen' },
      }
    : {
        key: 'files',
        label: 'Bibliotheksdateien',
        value: filesSum?.value ?? 'Wird geprüft …',
        detail: filesSum?.detail ?? '',
        level: filesSum?.level ?? 'off',
        fix:
          filesSum && (filesSum.pending || filesSum.errors || filesSum.missingFiles)
            ? writerMissing
              ? { action: 'writer', label: 'Writer einrichten' }
              : { action: 'sync', label: 'Synchronisieren' }
            : filesSum?.damaged
              ? { action: 'report', label: 'Zum Prüfbericht' }
              : filesSum && (filesSum.absent || filesSum.outside)
              ? { action: 'scanSync', label: 'Prüfen und synchronisieren' }
              : filesSum?.links
                ? { action: 'report', label: 'Zum Prüfbericht' }
                : // nur, wenn das Glied die fehlenden Höhen auch nennt (Lagen/Lesbarkeit gehen in der Anzeige vor)
                  filesSum?.heightsRepairable && !filesSum.layersOff && !filesSum.unreadable
                  ? { action: 'repairHeights', label: 'Höhen nachtragen' }
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
        eyebrow: 'Status nicht verfügbar',
        title: 'Der Altium-Status konnte nicht gelesen werden',
        text: `${m.statusError.replace(/[.\s]+$/, '')}. PartForge fragt alle 15 Sekunden erneut nach.`,
        primary: 'reload',
      }
    }
    return { tone: 'neutral', eyebrow: 'Status', title: 'Verbindung wird geprüft …', text: 'PartForge liest den Zustand von DbLib, Bibliotheksdateien und Altium.', primary: null }
  }
  const dblibStatus = status.dblib
  const running = status.altium_running

  // 1. Skript hängt
  if (status.bridge_wedged) {
    const step = typeof status.bridge_wedged.last_step === 'string' ? ` (letzter Schritt: ${status.bridge_wedged.last_step})` : ''
    return {
      tone: 'danger',
      eyebrow: 'Altium reagiert nicht',
      title: 'Ein PartForge-Skript hängt in Altium',
      text: `Das letzte Skript wurde nicht beendet${step}. In Altium Strg+F3 drücken (Skript anhalten) und die Aktion danach erneut starten.`,
      primary: null,
    }
  }
  // 2. Gleichnamige DbLib
  const duplicates = dblibIssue(dblibStatus, 'duplicates')
  if (duplicates) {
    return {
      tone: 'danger',
      eyebrow: 'Gleichnamige DbLib',
      title: 'Altium kennt mehrere DbLibs mit diesem Namen',
      text: duplicates.message,
      primary: duplicatesReplaceable(dblibStatus) && running ? 'installReplace' : null,
    }
  }
  // 3. DbLib fehlerhaft
  if (dblib.level === 'error') {
    const code = dblib.issue?.code ?? ''
    const problem = DBLIB_PROBLEM[code]
    let text = dblib.issue?.message ?? 'Ohne gültige DbLib findet Altium keine Bauteile.'
    if (code === 'missing') {
      text = `Ohne „${dblibStatus?.file_name ?? 'DbLib'}“ findet Altium keine Bauteile. „DbLib neu erzeugen“ legt sie im Bibliotheksordner an.`
    } else if (problem?.strip && text.includes(' – ')) {
      const rest = text.slice(text.indexOf(' – ') + 3)
      text = rest.charAt(0).toUpperCase() + rest.slice(1)
    }
    return { tone: 'danger', eyebrow: 'DbLib', title: problem?.title ?? 'Die DbLib hat ein Problem', text, primary: dblib.fix ?? null }
  }
  // 4. DbLib veraltet
  if (dblib.value === 'Veraltet') {
    const followUp = running && status.refresh.auto_refresh ? ' – das laufende Altium liest ihn danach selbst ein' : ''
    return {
      tone: 'warning',
      eyebrow: 'DbLib',
      title: 'Die DbLib ist veraltet',
      text:
        dblib.issue?.code === 'format'
          ? 'Die Datei ist nicht im Altium-Format gespeichert (Windows-1252, CRLF, ohne BOM). „Neu erzeugen“ schreibt sie so, wie Altium sie erwartet.'
          : `${dblib.detail}. „Neu erzeugen“ schreibt den aktuellen Stand${followUp}.`,
      primary: 'regenerate',
    }
  }
  // 5. ODBC-Treiber fehlt: Altium kann die Datenbank nicht lesen – auch wenn DbLib und Dateien bereit sind
  if (m.odbc) {
    const sqlite = m.odbc.kind ? m.odbc.kind === 'sqlite' : /sqlite/i.test(m.odbc.driver)
    return {
      tone: 'warning',
      eyebrow: 'ODBC-Treiber',
      title: `Der ODBC-Treiber „${m.odbc.driver}“ fehlt`,
      text: `Altium liest die Bibliothek über ODBC – ohne den 64-Bit-Treiber findet Altium keine Bauteile, auch wenn DbLib und Bibliotheksdateien bereit sind. ${
        sqlite ? 'Den SQLite-ODBC-Treiber (sqliteodbc_w64) installieren' : 'Den 64-Bit-Treiber psqlODBC installieren'
      }, danach „ODBC testen“.`,
      primary: 'odbc',
      link: odbcDriverLink(m.odbc),
    }
  }
  // 6. Bibliotheksdateien fehlen oder scheitern – ohne Bibliotheks-Writer hilft „Synchronisieren“ nicht
  if (files && (files.missingFiles || files.errors)) {
    return {
      tone: 'danger',
      eyebrow: 'Bibliotheksdateien',
      title: files.missingFiles ? 'Bibliotheksdateien fehlen' : 'Einträge konnten nicht geschrieben werden',
      text: m.writerOk
        ? 'Altium findet betroffene Symbole und Footprints erst, wenn sie in den SchLib-/PcbLib-Dateien stehen. „Synchronisieren“ schreibt sie neu.'
        : `Altium findet betroffene Symbole und Footprints erst, wenn sie in den SchLib-/PcbLib-Dateien stehen. Dafür braucht PartForge einen Bibliotheks-Writer – ${WRITER_REMEDY}.`,
      primary: m.writerOk ? 'sync' : 'writer',
    }
  }
  // Leere Bibliothek: erst Bauteile anlegen
  if (m.empty) {
    return {
      tone: 'info',
      eyebrow: 'Erste Schritte',
      title: 'Noch keine Bauteile in der Bibliothek',
      text: 'Der Serien-Assistent legt eine ganze Widerstands- oder Kondensatorserie an – mit Symbolen und Footprints. DbLib und Bibliotheksdateien entstehen dabei automatisch.',
      primary: 'series',
    }
  }
  // 7. Altium läuft – Installation ungeprüft bzw. fehlt
  if (running && altium.installed === null) {
    return {
      tone: 'info',
      eyebrow: 'Altium läuft',
      title: 'Ist die DbLib in Altium installiert?',
      text: 'PartForge fragt Altium nur auf Wunsch – „Status prüfen“ liest die installierten Bibliotheken (dauert wenige Sekunden).',
      primary: 'installState',
    }
  }
  if (running && !altium.installed) {
    // nicht „noch nicht“: auch nach „Aus Altium deinstallieren“ zutreffend (E2E-Regression, Wortlaut)
    return {
      tone: 'warning',
      eyebrow: 'Altium läuft',
      title: 'Die DbLib ist in Altium nicht installiert',
      text: 'Nach dem Installieren stehen alle Bauteile im Components-Panel von Altium bereit und bleiben automatisch aktuell.',
      primary: 'install',
    }
  }
  // 8. Ausstehende bzw. fehlende Einträge in den Dateien
  if (files && files.pending) {
    return {
      tone: 'warning',
      eyebrow: 'Bibliotheksdateien',
      title: `${plural(files.pending, 'Eintrag wartet', 'Einträge warten')} auf das Schreiben`,
      text: m.writerOk
        ? 'Neue oder geänderte Symbole und Footprints stehen erst nach dem Synchronisieren in den SchLib-/PcbLib-Dateien.'
        : `${WRITER_MISSING_TEXT}.`,
      primary: m.writerOk ? 'sync' : 'writer',
    }
  }
  if (files && (files.absent || files.outside)) {
    return {
      tone: 'warning',
      eyebrow: 'Bibliotheksdateien',
      title: files.absent ? `${plural(files.absent, 'Eintrag fehlt', 'Einträge fehlen')} in den Dateien` : 'Dateien wurden außerhalb geändert',
      text: files.absent
        ? 'Registrierte Symbole oder Footprints stehen nicht mehr in ihren Dateien. „Prüfen und synchronisieren“ schreibt sie neu.'
        : 'Seit PartForges letztem Schreiben wurden Dateien geändert (z. B. in Altium gespeichert). PartForge schreibt dort nur noch geänderte Einträge.',
      primary: 'scanSync',
    }
  }
  // 9. Aktualisieren gescheitert
  if (running && altium.installed && status.refresh.last_error) {
    return {
      tone: 'warning',
      eyebrow: 'Aktualisierung',
      title: 'Altium zeigt evtl. nicht den aktuellen Stand',
      text: status.refresh.last_error,
      primary: 'refresh',
    }
  }
  // 10. Fehler im Prüfbericht
  if (m.reportErrors) {
    return {
      tone: 'danger',
      eyebrow: 'Prüfbericht',
      title: `${plural(m.reportErrors, 'Fehler', 'Fehler')} im Prüfbericht`,
      text: 'Je Befund nennt der Prüfbericht Ursache und Lösungsweg – und behebt mit einem Klick, was PartForge selbst beheben kann.',
      primary: 'report',
    }
  }
  // 11. Footprint-Höhen fehlen (vor dem Höhen-Patch geschriebene PcbLibs) – mit Ein-Klick-Korrektur
  if (files && files.heightsRepairable) {
    return {
      tone: 'warning',
      eyebrow: 'Bibliotheksdateien',
      title: `${plural(files.heights, 'Footprint', 'Footprints')} ohne Bauhöhe in der PcbLib`,
      text: 'Eine ältere PartForge-Version hat sie mit der Höhe 0 geschrieben – Altium kennt ihre Bauhöhe dann nicht (3D-Abstände, Höhenregeln). „Footprint-Höhen nachtragen“ schreibt sie mit ihrer Höhe neu.',
      primary: 'repairHeights',
    }
  }
  if (m.findingsError) {
    return {
      tone: 'warning',
      eyebrow: 'Prüfbericht',
      title: 'Die Bibliothek konnte nicht geprüft werden',
      text: `${m.findingsError.replace(/[.\s]+$/, '')}. Ohne Prüfung zeigt PartForge keine Fehler und Warnungen der Bauteile – „Erneut prüfen“ versucht es noch einmal.`,
      primary: 'check',
    }
  }
  if (!status.altium_exe) {
    return {
      tone: 'neutral',
      eyebrow: 'Altium Designer',
      title: 'Altium Designer wurde nicht gefunden',
      text: `DbLib und Bibliotheksdateien sind bereit. Für Installieren, Aktualisieren und Prüfen in Altium den Pfad zu X2.EXE unter ${SETTINGS_PLACE.altium.label} festlegen.`,
      primary: 'settings',
    }
  }
  if (!running) {
    return {
      tone: 'neutral',
      eyebrow: 'Bereit für Altium',
      title: 'Alles bereit – Altium ist nicht gestartet',
      text: 'DbLib und Bibliotheksdateien sind aktuell. Sobald Altium Designer läuft, lässt sich die DbLib installieren, aktualisieren und in Altium prüfen.',
      primary: null,
    }
  }
  if (status.refresh.pending || status.refresh.manual_pending) {
    // ohne automatische Aktualisierung wartet nichts – die Änderungen bleiben liegen, bis jemand aktualisiert
    if (!status.refresh.auto_refresh && !status.refresh.running && !status.refresh.manual_pending) {
      return {
        tone: 'info',
        eyebrow: 'Aktualisierung',
        title: 'Altium kennt noch nicht alle Änderungen',
        text: 'Die automatische Aktualisierung ist ausgeschaltet. „In Altium aktualisieren“ lässt Altium die Bibliothek neu lesen.',
        primary: 'refresh',
      }
    }
    return {
      tone: 'info',
      eyebrow: 'Aktualisierung',
      title: 'Änderungen werden an Altium übergeben …',
      text: 'PartForge wartet einen Moment, bis keine weiteren Änderungen folgen, und lässt Altium dann neu lesen.',
      primary: 'refresh',
    }
  }
  const last = lastRefreshText(status)
  return {
    tone: 'success',
    eyebrow: 'Alles verbunden',
    title: 'Altium sieht den aktuellen Stand',
    text: `Bauteile lassen sich direkt aus dem Components-Panel platzieren${last ? ` (zuletzt aktualisiert ${last})` : ''}. „In Altium prüfen“ lässt Altium jedes Bauteil auflösen – wie beim Platzieren.`,
    primary: 'verify',
  }
}

/** Warum eine Altium-Aktion gerade nicht geht (Tooltip am gesperrten Knopf) – `null` = Altium bereit */
export function altiumBlocker(status: AltiumStatus | undefined, statusError?: string | null): string | null {
  if (!status) return statusError ? 'Altium-Status nicht verfügbar – erst „Erneut versuchen“' : 'Altium-Status wird geprüft …'
  if (!status.altium_exe) return `Altium Designer nicht gefunden – Pfad zu X2.EXE unter ${SETTINGS_PLACE.altium.label} festlegen`
  if (!status.altium_running) return 'Altium Designer starten – Installieren, Aktualisieren und Prüfen brauchen ein laufendes Altium Designer'
  if (status.bridge_wedged) return 'Ein PartForge-Skript hängt in Altium – dort Strg+F3 drücken'
  return null
}
