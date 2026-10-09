import {
  FileScan,
  FolderOpen,
  FolderPlus,
  FolderSearch,
  FolderSync,
  Layers,
  Library,
  ListChecks,
  LogOut,
  Microchip,
  Monitor,
  Moon,
  PanelLeft,
  PlugZap,
  Plus,
  RefreshCw,
  RotateCw,
  Search,
  Settings2,
  Shapes,
  ShieldCheck,
  Sparkles,
  Sun,
} from 'lucide-react'
import { useEffect } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { libraryApi } from '@/api/library'
import { useCloseWorkspace, useOpenWorkspace, useRecentWorkspaces, useSettings, useWorkspace } from '@/api/system'
import { baseName, shortenPath } from '@/lib/format'
import { isAltOnly, isEditableTarget, matchesHotkey, parseHotkey } from '@/lib/hotkeys'
import { revealPath } from '@/lib/native'
import { SETTINGS_PLACE } from '@/lib/settingsPlaces'
import {
  commandDisabledReason,
  dispatchSave,
  getCommands,
  saveKindOf,
  useRegisterCommands,
  useRegisterSearchProvider,
  type AppCommand,
} from '../commands'
import { NAV_ITEMS } from '../nav'
import { ALTIUM_PATH, altiumActionState } from '../navigation'
import { useJobDock, useUi } from '../stores'
import { useTheme } from '../theme'
import { confirmLibrarySwitch, switchCancelNote } from './librarySwitch'

/**
 * Ist gerade ein **modaler** Dialog offen? Dann keine globalen Kürzel (außer Strg+K).
 * Nicht-modale Panels (Drawer `modal={false}`, Popover) blockieren die Kürzel nicht.
 */
function modalOpen(): boolean {
  return (
    document.querySelector('[role="dialog"][aria-modal="true"][data-state="open"], [role="alertdialog"][data-state="open"]') !==
    null
  )
}

/** Eingebaute Befehle (Navigation, Bibliothek, Darstellung), Bauteil-Schnellsuche und globale Tastenkürzel. */
export function ShellCommands() {
  const navigate = useNavigate()
  const workspace = useWorkspace().data
  const recent = useRecentWorkspaces().data
  const openWs = useOpenWorkspace()
  const closeWs = useCloseWorkspace()
  const { setTheme } = useTheme()
  const settings = useSettings().data
  const hasWs = Boolean(workspace)
  const needsWs = () => hasWs
  /** Datenblattsuche braucht die KI: Grund, warum sie gerade nicht geht (sonst `null`) */
  // kurz (die Zeile der Palette ist schmal) – wo man es ändert, steht im Befehl „KI-Funktionen einstellen“
  const aiUnavailable = !settings
    ? null
    : !settings.settings.ai.enabled
      ? 'KI-Funktionen sind ausgeschaltet'
      : !settings.ai_key_configured
        ? 'Kein Claude-API-Schlüssel hinterlegt'
        : null

  /** Bibliothek wechseln bzw. schließen – vorher fragen, wenn dabei laufende Jobs abgebrochen würden */
  const switchTo = async (path: string, go: (to: string) => void) => {
    if (!(await confirmLibrarySwitch('switch'))) return
    const note = switchCancelNote()
    openWs.mutate(path, {
      onSuccess: (info) => {
        toast.success(`„${info.name}“ geöffnet`, { description: note ?? undefined })
        go('/')
      },
      onError: (err) => toast.error('Bibliothek konnte nicht geöffnet werden', { description: errorMessage(err) }),
    })
  }
  const closeLibrary = async () => {
    if (!(await confirmLibrarySwitch('close'))) return
    const note = switchCancelNote()
    closeWs.mutate(undefined, { onSuccess: () => toast.success('Bibliothek geschlossen', { description: note ?? undefined }) })
  }

  const commands: AppCommand[] = [
    // --- Navigation
    ...NAV_ITEMS.map<AppCommand>((item) => ({
      id: `nav:${item.to}`,
      title: item.label,
      subtitle: item.description,
      group: 'Navigation',
      icon: item.icon,
      hotkey: item.hotkey,
      ai: item.ai,
      target: item.to,
      keywords: ['gehe zu', 'öffnen', 'seite'],
      when: item.requiresWorkspace ? needsWs : undefined,
      run: ({ navigate: go }) => go(item.to),
    })),
    // --- Aktionen (Seiten können diese IDs mit eigenen Implementierungen überlagern)
    {
      id: 'parts.new',
      title: 'Neues Bauteil',
      subtitle: 'Geführte Anlage mit Smart-Eingabe',
      group: 'Aktionen',
      icon: Plus,
      hotkey: 'mod+n',
      priority: 100,
      keywords: ['anlegen', 'erstellen', 'part'],
      when: needsWs,
      run: ({ navigate: go }) => go('/bauteile?neu=1'),
    },
    {
      id: 'series.new',
      title: 'Serie erzeugen',
      subtitle: 'Komplette Widerstands- oder Kondensatorserie im Serien-Assistenten',
      group: 'Aktionen',
      icon: Layers,
      priority: 90,
      target: '/serien',
      keywords: ['serien-assistent', 'e-reihe', 'e24', 'e96', 'widerstand', 'kondensator', 'erzeugen'],
      when: needsWs,
      run: ({ navigate: go }) => go('/serien'),
    },
    {
      id: 'import.datasheet',
      title: 'Datenblatt importieren',
      subtitle: 'PDF analysieren und Bauteil erzeugen',
      group: 'Aktionen',
      icon: FileScan,
      ai: true,
      priority: 80,
      target: '/import',
      keywords: ['pdf', 'ki', 'claude', 'extrahieren', 'datenblatt-import'],
      when: needsWs,
      run: ({ navigate: go }) => go('/import'),
    },
    {
      // global (auch außerhalb von /import): Seiten mit eigener Fassung überlagern ihn (gleiche ID)
      id: 'import.find',
      title: 'Datenblatt suchen …',
      subtitle: 'Claude sucht das PDF zur Teilenummer im Web',
      group: 'Aktionen',
      icon: Search,
      ai: true,
      priority: 75,
      target: '/import?suche=1',
      keywords: ['teilenummer', 'suche', 'web', 'internet', 'pdf finden', 'hersteller', 'claude', 'datenblattsuche'],
      when: needsWs,
      disabled: () => aiUnavailable,
      run: ({ navigate: go }) => go('/import?suche=1'),
    },
    {
      id: 'altium.regenerate',
      title: 'DbLib neu erzeugen',
      group: 'Aktionen',
      icon: RefreshCw,
      priority: 60,
      keywords: ['dblib', 'odbc', 'altium'],
      when: needsWs,
      // Aktion als Router-State – nie als ?aktion= in der Adresse (siehe altiumActionState)
      run: ({ navigate: go }) => go(ALTIUM_PATH, { state: altiumActionState('dblib') }),
    },
    {
      id: 'library.sync',
      title: 'Bibliotheksdateien synchronisieren',
      subtitle: 'Ausstehende Symbole und Footprints in SchLib/PcbLib schreiben',
      group: 'Aktionen',
      icon: FolderSync,
      priority: 55,
      keywords: ['schlib', 'pcblib', 'symbole', 'footprints', 'ausstehend'],
      when: needsWs,
      run: ({ navigate: go }) => go(ALTIUM_PATH, { state: altiumActionState('sync') }),
    },
    {
      id: 'library.check',
      title: 'Bibliothek prüfen',
      subtitle: 'Fehlende Symbole, Footprints und Felder finden',
      group: 'Aktionen',
      icon: ShieldCheck,
      priority: 50,
      keywords: ['validieren', 'prüfbericht', 'fehler'],
      when: needsWs,
      run: ({ navigate: go }) => go(ALTIUM_PATH, { state: altiumActionState('pruefen') }),
    },
    {
      id: 'altium.install',
      title: 'In Altium installieren',
      subtitle: 'DbLib in Altium Designer einbinden',
      group: 'Aktionen',
      icon: PlugZap,
      priority: 40,
      when: needsWs,
      run: ({ navigate: go }) => go(ALTIUM_PATH, { state: altiumActionState('installieren') }),
    },
    // --- Bibliothek
    {
      id: 'library.new',
      title: 'Neue Bibliothek anlegen …',
      group: 'Bibliothek',
      icon: FolderPlus,
      priority: 20,
      run: () => useUi.getState().setLibraryDialog('create'),
    },
    {
      id: 'library.open',
      title: 'Bibliothek öffnen …',
      group: 'Bibliothek',
      icon: FolderOpen,
      priority: 19,
      run: () => useUi.getState().setLibraryDialog('open'),
    },
    ...(recent ?? [])
      .filter((r) => r.exists && r.path !== workspace?.root)
      .slice(0, 5)
      .map<AppCommand>((r) => ({
        id: `library.recent:${r.path}`,
        title: `Wechseln zu „${r.name ?? baseName(r.path)}“`,
        subtitle: shortenPath(r.path, 44),
        group: 'Bibliothek',
        icon: Library,
        priority: 10,
        run: ({ navigate: go }) => switchTo(r.path, (to) => void go(to)),
      })),
    {
      id: 'library.reveal',
      title: 'Bibliotheksordner im Explorer zeigen',
      group: 'Bibliothek',
      icon: FolderSearch,
      keywords: ['ordner', 'explorer', 'pfad', 'datei'],
      when: needsWs,
      run: () => {
        if (workspace) void revealPath(workspace.root, { what: 'Bibliotheksordner' })
      },
    },
    {
      id: 'library.close',
      title: 'Bibliothek schließen',
      group: 'Bibliothek',
      icon: LogOut,
      when: needsWs,
      run: () => closeLibrary(),
    },
    // --- Darstellung
    {
      id: 'view.theme.dark',
      title: 'Darstellung: Dunkel',
      group: 'Darstellung',
      icon: Moon,
      keywords: ['theme', 'design', 'dark'],
      run: () => setTheme('dark'),
    },
    {
      id: 'view.theme.light',
      title: 'Darstellung: Hell',
      group: 'Darstellung',
      icon: Sun,
      keywords: ['theme', 'design', 'light'],
      run: () => setTheme('light'),
    },
    {
      id: 'view.theme.system',
      title: 'Darstellung: Wie System',
      group: 'Darstellung',
      icon: Monitor,
      keywords: ['theme', 'design', 'windows'],
      run: () => setTheme('system'),
    },
    {
      id: 'view.sidebar',
      title: 'Seitenleiste ein-/ausklappen',
      group: 'Darstellung',
      icon: PanelLeft,
      hotkey: 'mod+b',
      run: () => useUi.getState().toggleSidebar(),
    },
    // --- System
    {
      id: 'view.jobs',
      title: 'Hintergrundjobs anzeigen',
      group: 'System',
      icon: ListChecks,
      run: () => useJobDock.getState().setOpen(true),
    },
    {
      id: 'settings.ai',
      title: 'KI-Funktionen einstellen',
      subtitle: SETTINGS_PLACE.ai.label,
      group: 'System',
      icon: Sparkles,
      keywords: ['claude', 'api-schlüssel', 'schlüssel', 'modell', 'ki', 'einschalten'],
      run: ({ navigate: go }) => go(SETTINGS_PLACE.ai.to),
    },
    {
      id: 'settings.altium',
      title: 'Altium und Bibliotheks-Writer einstellen',
      subtitle: SETTINGS_PLACE.altium.label,
      group: 'System',
      icon: Settings2,
      keywords: ['writer', 'x2.exe', 'altium designer', 'pfad', 'schreibweg', 'altium-designer-mcp'],
      run: ({ navigate: go }) => go(SETTINGS_PLACE.altium.to),
    },
    // Komponenten-Galerie nur im Entwicklungsmodus anbieten (Route /ui-kit bleibt per URL erreichbar)
    ...(import.meta.env.DEV
      ? [
          {
            id: 'system.uikit',
            title: 'UI-Kit anzeigen',
            subtitle: 'Komponenten-Galerie des Designsystems',
            group: 'System',
            icon: Shapes,
            keywords: ['komponenten', 'design', 'galerie'],
            run: ({ navigate: go }) => go('/ui-kit'),
          } satisfies AppCommand,
        ]
      : []),
    {
      id: 'system.reload',
      title: 'Oberfläche neu laden',
      group: 'System',
      icon: RotateCw,
      run: () => window.location.reload(),
    },
  ]
  useRegisterCommands(commands)

  // --- Bauteil-Schnellsuche (Teilenummer, MPN, Beschreibung, Wert) – nur mit geöffneter Bibliothek
  useRegisterSearchProvider({
    id: 'parts',
    group: 'Bauteile',
    minQueryLength: hasWs ? 2 : 10_000,
    search: async (q, signal) => {
      if (!hasWs) return []
      const hits = await libraryApi.search(q, 8, signal)
      return hits.map((h) => ({
        id: `${h.table}:${h.part_number}`,
        title: h.mpn || h.part_number,
        subtitle: h.description ?? h.value ?? undefined,
        meta: h.label,
        color: h.color,
        icon: Microchip,
        run: ({ navigate: go }) => go(`/bauteile/${encodeURIComponent(h.table)}?pn=${encodeURIComponent(h.part_number)}`),
      }))
    },
  })

  // --- Strg+S / Strg+⇧+S: immer abfangen (sonst öffnet WebView2 „Seite speichern unter“) – auch hinter modalen
  // Dialogen und bei gehaltener Taste – und an den Speichern-Handler der Seite bzw. des Dialogs geben.
  // Capture-Phase: läuft vor allen Komponenten, ein `stopPropagation` irgendwo kann den Schutz nicht aushebeln.
  useEffect(() => {
    const onSaveKey = (e: KeyboardEvent) => {
      const kind = saveKindOf(e)
      if (!kind) return
      e.preventDefault()
      if (e.repeat || e.isComposing || useUi.getState().commandPaletteOpen) return
      dispatchSave(kind, { navigate, close: () => useUi.getState().setCommandPaletteOpen(false) }, modalOpen())
    }
    window.addEventListener('keydown', onSaveKey, { capture: true })
    return () => window.removeEventListener('keydown', onSaveKey, { capture: true })
  }, [navigate])

  // --- Globale Tastenkürzel
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.isComposing) return
      // Strg+K: Palette immer umschalten
      if (matchesHotkey(e, 'mod+k')) {
        e.preventDefault()
        useUi.getState().toggleCommandPalette()
        return
      }
      // Strg+S erledigt der Speichern-Verteiler oben (Befehle mit „mod+s“ eingeschlossen)
      if (saveKindOf(e)) return
      if (e.defaultPrevented || e.repeat || useUi.getState().commandPaletteOpen || modalOpen()) return
      const editable = isEditableTarget(e.target)
      for (const cmd of getCommands()) {
        if (!cmd.hotkey || !matchesHotkey(e, cmd.hotkey) || commandDisabledReason(cmd)) continue
        const h = parseHotkey(cmd.hotkey)
        // In Eingabefeldern nur Kürzel mit Strg/⌘ – Alt allein gehört dort den Alt-Codes (±, Ω, µ …)
        if (editable && (isAltOnly(cmd.hotkey) || !(h.ctrl || h.meta))) continue
        e.preventDefault()
        void cmd.run({ navigate, close: () => useUi.getState().setCommandPaletteOpen(false) })
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [navigate])

  return null
}
