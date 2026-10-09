/** Darstellungs-Konstanten der Altium-Seite (Statusfarben, Beschriftungen) – auch von der Übersicht genutzt. */
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
  regenerate: { label: 'DbLib neu erzeugen', short: 'Neu erzeugen', icon: RefreshCw },
  preview: { label: 'DbLib-Vorschau', short: 'Vorschau', icon: FileCode2 },
  odbc: { label: 'ODBC-Verbindung testen', short: 'ODBC testen', icon: Cable },
  sync: { label: 'Bibliotheksdateien synchronisieren', short: 'Synchronisieren', icon: FolderSync },
  scan: { label: 'Bibliotheksdateien prüfen', short: 'Dateien prüfen', icon: FolderSearch },
  scanSync: { label: 'Prüfen und synchronisieren', short: 'Prüfen und synchronisieren', icon: FolderSync },
  repairHeights: { label: 'Footprint-Höhen nachtragen', short: 'Höhen nachtragen', icon: RulerDimensionLine },
  restoreBackup: { label: 'Aus Sicherung wiederherstellen', short: 'Wiederherstellen', icon: ArchiveRestore },
  install: { label: 'In Altium installieren', short: 'Installieren', icon: PlugZap },
  installReplace: { label: 'Ersetzen und installieren', short: 'Ersetzen und installieren', icon: Replace },
  uninstall: { label: 'Aus Altium deinstallieren', short: 'Deinstallieren', icon: Unplug },
  installState: { label: 'Installationsstatus prüfen', short: 'Status prüfen', icon: SearchCheck },
  refresh: { label: 'In Altium aktualisieren', short: 'Aktualisieren', icon: RotateCw },
  refreshRebuild: { label: 'Aktualisieren mit Index-Neuaufbau', short: 'Index neu aufbauen', icon: RotateCw },
  verify: { label: 'Bibliothek in Altium prüfen', short: 'In Altium prüfen', icon: ScanSearch },
  open: { label: 'DbLib in Altium öffnen', short: 'In Altium öffnen', icon: SquareArrowOutUpRight },
  settings: { label: 'Altium-Einstellungen', short: 'Einstellungen', icon: Settings2 },
  writer: { label: 'Bibliotheks-Writer einrichten', short: 'Writer einrichten', icon: FileCog },
  report: { label: 'Prüfbericht ansehen', short: 'Prüfbericht', icon: ListChecks },
  check: { label: 'Bibliothek prüfen', short: 'Erneut prüfen', icon: ShieldCheck },
  normalize: { label: 'Werte vereinheitlichen', short: 'Vereinheitlichen', icon: Wrench },
  series: { label: 'Serie erzeugen', short: 'Serie erzeugen', icon: Layers },
  reload: { label: 'Erneut versuchen', short: 'Erneut versuchen', icon: RotateCw },
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
  ok: 'in Ordnung',
  warn: 'Hinweis',
  error: 'Problem',
  off: 'inaktiv',
  busy: 'läuft gerade',
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
