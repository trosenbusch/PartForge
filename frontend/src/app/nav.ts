import {
  CircuitBoard,
  FileScan,
  Layers,
  LayoutDashboard,
  Microchip,
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
    label: 'Übersicht',
    description: 'Kennzahlen, Bibliotheksgesundheit und Schnellaktionen',
    icon: LayoutDashboard,
    hotkey: 'alt+1',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/bauteile',
    label: 'Bauteile',
    description: 'Alle Bauteile durchsuchen, filtern und bearbeiten',
    icon: Microchip,
    hotkey: 'alt+2',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/serien',
    label: 'Serien-Assistent',
    description: 'Komplette Bauteilserien in einem Rutsch anlegen',
    icon: Layers,
    hotkey: 'alt+3',
    group: 'Bibliothek',
    requiresWorkspace: true,
  },
  {
    to: '/import',
    label: 'Datenblatt-Import',
    description: 'Bauteile per KI aus PDF-Datenblättern erzeugen',
    icon: FileScan,
    hotkey: 'alt+4',
    group: 'Bibliothek',
    ai: true,
    requiresWorkspace: true,
  },
  {
    to: '/symbole',
    label: 'Symbole',
    description: 'Schaltplansymbole ansehen, erzeugen und bearbeiten',
    icon: Shapes,
    hotkey: 'alt+5',
    group: 'Modelle',
    requiresWorkspace: true,
  },
  {
    to: '/footprints',
    label: 'Footprints',
    description: 'Footprints nach IPC-7351 generieren und verwalten',
    icon: CircuitBoard,
    hotkey: 'alt+6',
    group: 'Modelle',
    requiresWorkspace: true,
  },
  {
    to: '/altium',
    label: 'Altium',
    description: 'DbLib erzeugen, Bibliothek prüfen und in Altium installieren',
    icon: PlugZap,
    hotkey: 'alt+7',
    group: 'System',
    requiresWorkspace: true,
  },
  {
    to: '/einstellungen',
    label: 'Einstellungen',
    description: 'KI, Altium, Bibliothek und Darstellung',
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
