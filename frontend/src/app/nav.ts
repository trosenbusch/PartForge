import { t as tr } from '@/lib/i18n'
import {
  CircuitBoard,
  FileScan,
  FolderInput,
  Layers,
  LayoutDashboard,
  Microchip,
  PaintbrushVertical,
  PlugZap,
  Settings,
  Shapes,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  /** Kurzbeschreibung (Befehlspalette, Platzhalter) */
  description: string
  icon: LucideIcon
  hotkey: string
  group: 'Bibliothek' | 'Modelle' | 'System'
  /** KI-gestützter Bereich (Funken-Markierung) */
  ai?: boolean
  /** Benötigt eine geöffnete Bibliothek */
  requiresWorkspace: boolean
}

export const NAV_ITEMS: NavItem[] = [
  {
    to: '/',
    get label() { return tr("Übersicht") },
    get description() { return tr("Kennzahlen, Bibliotheksgesundheit und Schnellaktionen") },
    icon: LayoutDashboard,
    hotkey: 'alt+1',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/bauteile',
    get label() { return tr("Bauteile") },
    get description() { return tr("Alle Bauteile durchsuchen, filtern und bearbeiten") },
    icon: Microchip,
    hotkey: 'alt+2',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/serien',
    get label() { return tr("Serien-Assistent") },
    get description() { return tr("Komplette Bauteilserien in einem Rutsch anlegen") },
    icon: Layers,
    hotkey: 'alt+3',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/import',
    get label() { return tr("Datenblatt-Import") },
    get description() { return tr("Bauteile per KI aus PDF-Datenblättern erzeugen") },
    icon: FileScan,
    hotkey: 'alt+4',
    group: 'Bibliothek',
    ai: true,
    requiresWorkspace: true,
  },
  {
    to: '/bibliotheksimport',
    get label() { return tr("Bibliotheksimport") },
    get description() { return tr("Symbole und Footprints aus vorhandenen Altium-Bibliotheken übernehmen") },
    icon: FolderInput,
    hotkey: 'alt+9',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/symbole',
    get label() { return tr("Symbole") },
    get description() { return tr("Schaltplansymbole ansehen, erzeugen und bearbeiten") },
    icon: Shapes,
    hotkey: 'alt+5',
    group: 'Modelle',
    requiresWorkspace: true,
  },
  {
    to: '/footprints',
    label: 'Footprints',
    get description() { return tr("Footprints nach IPC-7351 generieren und verwalten") },
    icon: CircuitBoard,
    hotkey: 'alt+6',
    group: 'Modelle',
    requiresWorkspace: true,
  },
  {
    to: '/stapelbearbeitung',
    get label() { return tr("Stapelbearbeitung") },
    get description() { return tr("Symbole und Footprints in einem Arbeitsgang an den Hausstil angleichen") },
    icon: PaintbrushVertical,
    hotkey: 'alt+0',
    group: 'Modelle',
    requiresWorkspace: true,
  },
  {
    to: '/altium',
    label: 'Altium',
    get description() { return tr("DbLib erzeugen, Bibliothek prüfen und in Altium installieren") },
    icon: PlugZap,
    hotkey: 'alt+7',
    group: 'System',
    requiresWorkspace: true,
  },
  {
    to: '/einstellungen',
    get label() { return tr("Einstellungen") },
    get description() { return tr("KI, Altium, Bibliothek und Darstellung") },
    icon: Settings,
    hotkey: 'alt+8',
    group: 'System',
    requiresWorkspace: false,
  },
]

export const NAV_GROUPS: NavItem['group'][] = ['Bibliothek', 'Modelle', 'System']

/** Navigationspunkt zu einem Pfad (längster Präfix) */
export function navItemForPath(pathname: string): NavItem | undefined {
  if (pathname === '/' || pathname === '') return NAV_ITEMS[0]
  return NAV_ITEMS.filter((i) => i.to !== '/' && (pathname === i.to || pathname.startsWith(`${i.to}/`))).sort(
    (a, b) => b.to.length - a.to.length,
  )[0]
}
