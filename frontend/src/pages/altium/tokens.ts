import { t as tr, tc } from '@/lib/i18n'
import {
  ArchiveRestore,
  Cable,
  FileCode2,
  FileCog,
  Layers,
  FolderSearch,
  FolderSync,
  ListChecks,
  PlugZap,
  Replace,
  RefreshCw,
  RotateCw,
  RulerDimensionLine,
  ScanSearch,
  SearchCheck,
  Settings2,
  ShieldCheck,
  SquareArrowOutUpRight,
  Unplug,
  Wrench,
  type LucideIcon,
} from 'lucide-react'
import type { IssueSeverity } from '@/api/altium'
import type { ActionKey, Level } from './model'

/** Beschriftung und Symbol je Aktion (Knöpfe, Menüs, Befehlspalette) */
export const ACTION_META: Record<ActionKey, { label: string; short: string; icon: LucideIcon }> = {
  regenerate: { get label() { return tr("DbLib neu erzeugen") }, get short() { return tr("Neu erzeugen") }, icon: RefreshCw },
  preview: { get label() { return tr("DbLib-Vorschau") }, get short() { return tr("Vorschau") }, icon: FileCode2 },
  odbc: { get label() { return tr("ODBC-Verbindung testen") }, get short() { return tr("ODBC testen") }, icon: Cable },
  sync: { get label() { return tr("Bibliotheksdateien synchronisieren") }, get short() { return tr("Synchronisieren") }, icon: FolderSync },
  scan: { get label() { return tr("Bibliotheksdateien prüfen") }, get short() { return tr("Dateien prüfen") }, icon: FolderSearch },
  scanSync: { get label() { return tr("Prüfen und synchronisieren") }, get short() { return tr("Prüfen und synchronisieren") }, icon: FolderSync },
  repairHeights: { get label() { return tr("Footprint-Höhen nachtragen") }, get short() { return tr("Höhen nachtragen") }, icon: RulerDimensionLine },
  restoreBackup: { get label() { return tr("Aus Sicherung wiederherstellen") }, get short() { return tr("Wiederherstellen") }, icon: ArchiveRestore },
  install: { get label() { return tr("In Altium installieren") }, get short() { return tr("Installieren") }, icon: PlugZap },
  installReplace: { get label() { return tr("Ersetzen und installieren") }, get short() { return tr("Ersetzen und installieren") }, icon: Replace },
  uninstall: { get label() { return tr("Aus Altium deinstallieren") }, get short() { return tr("Deinstallieren") }, icon: Unplug },
  installState: { get label() { return tr("Installationsstatus prüfen") }, get short() { return tr("Status prüfen") }, icon: SearchCheck },
  refresh: { get label() { return tr("In Altium aktualisieren") }, get short() { return tc('refresh', 'Aktualisieren') }, icon: RotateCw },
  refreshRebuild: { get label() { return tr("Aktualisieren mit Index-Neuaufbau") }, get short() { return tr("Index neu aufbauen") }, icon: RotateCw },
  verify: { get label() { return tr("Bibliothek in Altium prüfen") }, get short() { return tr("In Altium prüfen") }, icon: ScanSearch },
  open: { get label() { return tr("DbLib in Altium öffnen") }, get short() { return tr("In Altium öffnen") }, icon: SquareArrowOutUpRight },
  settings: { get label() { return tr("Altium-Einstellungen") }, get short() { return tr("Einstellungen") }, icon: Settings2 },
  writer: { get label() { return tr("Bibliotheks-Writer einrichten") }, get short() { return tr("Writer einrichten") }, icon: FileCog },
  report: { get label() { return tr("Prüfbericht ansehen") }, get short() { return tr("Prüfbericht") }, icon: ListChecks },
  check: { get label() { return tr("Bibliothek prüfen") }, get short() { return tr("Erneut prüfen") }, icon: ShieldCheck },
  normalize: { get label() { return tr("Werte vereinheitlichen") }, get short() { return tr("Vereinheitlichen") }, icon: Wrench },
  series: { get label() { return tr("Serie erzeugen") }, get short() { return tr("Serie erzeugen") }, icon: Layers },
  reload: { get label() { return tr("Erneut versuchen") }, get short() { return tr("Erneut versuchen") }, icon: RotateCw },
}

export const LEVEL_DOT: Record<Level, string> = {
  ok: 'bg-success shadow-[0_0_8px_color-mix(in_oklab,var(--pf-success)_70%,transparent)]',
  warn: 'bg-warning',
  error: 'bg-danger',
  off: 'bg-fg-subtle/70',
  busy: 'bg-accent',
}

export const LEVEL_TEXT: Record<Level, string> = {
  ok: 'text-fg',
  warn: 'text-warning-text',
  error: 'text-danger-text',
  off: 'text-fg-muted',
  busy: 'text-fg',
}

/** Zustand für Screenreader (der Punkt selbst ist dekorativ) */
export const LEVEL_LABEL: Record<Level, string> = {
  get ok() { return tr("in Ordnung") },
  get warn() { return tr("Hinweis") },
  error: 'Problem',
  get off() { return tr("inaktiv") },
  get busy() { return tr("läuft gerade") },
}

/** Grafikfarbe je Schwere (Ringe, Balken) */
export const SEVERITY_COLOR: Record<IssueSeverity, string> = {
  error: 'var(--pf-danger)',
  warning: 'var(--pf-warning)',
  info: 'var(--pf-info)',
}

export const SEVERITY_TEXT: Record<IssueSeverity, string> = {
  error: 'text-danger-text',
  warning: 'text-warning-text',
  info: 'text-info-text',
}
