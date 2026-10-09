/**
 * Befehlsregister für die Befehlspalette (Strg+K) und globale Tastenkürzel.
 *
 * Seiten registrieren Befehle, solange sie gemountet sind:
 *
 *   useRegisterCommands([
 *     { id: 'parts.new', title: 'Neues Bauteil', group: 'Aktionen', icon: Plus, hotkey: 'mod+n',
 *       run: () => setDialogOpen(true) },
 *   ])
 *
 * Gleiche IDs überlagern sich: Es gilt die Registrierung der **zuletzt gemounteten** Komponente – auch wenn
 * eine früher gemountete (z. B. die Shell) ihre Liste später neu registriert. Beim Unmount wird der vorige
 * Eintrag wieder aktiv. So kann eine Seite z. B. den Standardbefehl „Neues Bauteil“ durch ihren Dialog ersetzen.
 *
 * Live-Suche (z. B. Bauteile) über Suchanbieter:
 *
 *   useRegisterSearchProvider({ id: 'parts', group: 'Bauteile', search: async (q, signal) => [...] })
 *
 * Strg+S der aktuellen Seite bzw. des offenen Dialogs (die Shell fängt das Kürzel immer ab):
 *
 *   useSaveHandler(save, { enabled: dirty, saveAs, modal })
 */
import type { ComponentType } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { NavigateFunction } from 'react-router'
import { create } from 'zustand'
import { matchesHotkey, parseHotkey } from '@/lib/hotkeys'

export type CommandIcon = ComponentType<{ className?: string; strokeWidth?: number }>

export interface CommandContext {
  navigate: NavigateFunction
  /** Befehlspalette schließen */
  close: () => void
}

export interface AppCommand {
  /** Eindeutige ID, z. B. 'parts.new' */
  id: string
  title: string
  subtitle?: string
  /** Gruppe in der Palette, z. B. 'Navigation', 'Aktionen', 'Bibliothek', 'Darstellung' */
  group?: string
  icon?: CommandIcon
  /** Zusätzliche Suchbegriffe */
  keywords?: string[]
  /** Globales Tastenkürzel, z. B. 'mod+n' (wird angezeigt und – solange registriert – ausgelöst) */
  hotkey?: string
  /** KI-Befehl (Funken-Stil) */
  ai?: boolean
  /**
   * Ziel des Befehls (z. B. Route '/serien'). Befehle mit gleichem Ziel erscheinen in den Suchergebnissen
   * nur einmal (der passendere gewinnt) – z. B. „Serie erzeugen“ und die Navigation „Serien-Assistent“.
   */
  target?: string
  /** Sichtbar/aktiv? (Standard: ja) */
  when?: () => boolean
  /**
   * Sichtbar, aber gerade nicht ausführbar: Rückgabe = deutscher Grund (erscheint in der Palette statt des
   * Untertitels, der Eintrag ist gedimmt und nicht wählbar; das Tastenkürzel wirkt nicht), sonst `false`/`null`.
   *
   *   disabled: () => (aiEnabled ? false : 'KI-Funktionen sind ausgeschaltet')
   */
  disabled?: () => string | false | null | undefined
  /** Sortierung innerhalb der Gruppe (höher = weiter oben) */
  priority?: number
  /** Palette nach Ausführung offen lassen */
  keepOpen?: boolean
  run: (ctx: CommandContext) => void | Promise<void>
}

export interface CommandSearchResult {
  id: string
  title: string
  subtitle?: string
  icon?: CommandIcon
  /** Rechtsbündiger Zusatz (z. B. Kategorie) */
  meta?: string
  /** Farbpunkt vor dem Zusatz (z. B. Kategorie-Farbe) */
  color?: string | null
  /**
   * Titel in Monospace (Standard: ja – Teilenummern, MPNs, Symbol-/Footprintnamen). `false` für Klartext
   * (Kategorien, Symboltypen, Einstellungen).
   */
  mono?: boolean
  run: (ctx: CommandContext) => void | Promise<void>
}

export interface CommandSearchProvider {
  id: string
  /** Gruppenüberschrift der Ergebnisse */
  group: string
  /** Mindestlänge der Eingabe (Standard 2) */
  minQueryLength?: number
  search: (query: string, signal: AbortSignal) => Promise<CommandSearchResult[]>
}

interface Entry<T> {
  token: number
  value: T
}

interface RegistryState {
  commands: Record<string, Entry<AppCommand>[]>
  providers: Record<string, Entry<CommandSearchProvider>[]>
}

const useRegistry = create<RegistryState>(() => ({ commands: {}, providers: {} }))
let tokenCounter = 0

/** Neues Registrierungs-Token (aufsteigend = später gemountet). */
export function nextRegistrationToken(): number {
  tokenCounter += 1
  return tokenCounter
}

function addEntries<T extends { id: string }>(
  record: Record<string, Entry<T>[]>,
  values: T[],
  token: number,
): Record<string, Entry<T>[]> {
  const next = { ...record }
  for (const v of values) {
    next[v.id] = [...(next[v.id] ?? []).filter((e) => e.token !== token), { token, value: v }].sort(
      (a, b) => a.token - b.token,
    )
  }
  return next
}

function removeEntries<T extends { id: string }>(
  record: Record<string, Entry<T>[]>,
  values: T[],
  token: number,
): Record<string, Entry<T>[]> {
  const next = { ...record }
  for (const v of values) {
    const list = (next[v.id] ?? []).filter((e) => e.token !== token)
    if (list.length) next[v.id] = list
    else delete next[v.id]
  }
  return next
}

/** Befehle registrieren (außerhalb von React). Gibt die Abmeldefunktion zurück. */
export function registerCommands(commands: AppCommand[], token = nextRegistrationToken()): () => void {
  useRegistry.setState((s) => ({ commands: addEntries(s.commands, commands, token) }))
  return () => useRegistry.setState((s) => ({ commands: removeEntries(s.commands, commands, token) }))
}

/** Suchanbieter registrieren (außerhalb von React). */
export function registerSearchProvider(provider: CommandSearchProvider, token = nextRegistrationToken()): () => void {
  useRegistry.setState((s) => ({ providers: addEntries(s.providers, [provider], token) }))
  return () => useRegistry.setState((s) => ({ providers: removeEntries(s.providers, [provider], token) }))
}

function signature(commands: AppCommand[]): string {
  return commands
    .map((c) =>
      [c.id, c.title, c.subtitle, c.group, c.hotkey, c.ai, c.priority, c.target, c.keepOpen, c.keywords?.join(',')].join('|'),
    )
    .join('§')
}

/**
 * Befehle registrieren, solange die Komponente gemountet ist.
 * `run`/`when` dürfen sich bei jedem Render ändern (es wird immer die aktuelle Fassung ausgeführt).
 * Das Token bleibt für die Lebensdauer der Komponente gleich – Neu-Registrierungen ändern die Rangfolge nicht.
 */
export function useRegisterCommands(commands: AppCommand[]): void {
  const [token] = useState(nextRegistrationToken)
  const latest = useRef(commands)
  useEffect(() => {
    latest.current = commands
  })
  const sig = signature(commands)
  useEffect(() => {
    const wrapped = latest.current.map<AppCommand>((c) => ({
      ...c,
      when: c.when ? () => latest.current.find((x) => x.id === c.id)?.when?.() ?? true : undefined,
      disabled: c.disabled ? () => latest.current.find((x) => x.id === c.id)?.disabled?.() ?? false : undefined,
      run: (ctx) => latest.current.find((x) => x.id === c.id)?.run(ctx),
    }))
    return registerCommands(wrapped, token)
  }, [sig, token])
}

/** Suchanbieter registrieren, solange die Komponente gemountet ist. */
export function useRegisterSearchProvider(provider: CommandSearchProvider): void {
  const [token] = useState(nextRegistrationToken)
  const latest = useRef(provider)
  useEffect(() => {
    latest.current = provider
  })
  const { id, group, minQueryLength } = provider
  useEffect(
    () =>
      registerSearchProvider(
        {
          id,
          group,
          minQueryLength,
          search: (q, signal) => latest.current.search(q, signal),
        },
        token,
      ),
    [id, group, minQueryLength, token],
  )
}

function effective<T>(record: Record<string, Entry<T>[]>): T[] {
  return Object.values(record)
    .map((list) => list[list.length - 1]?.value)
    .filter((v): v is T => v !== undefined)
}

const byPriority = (a: AppCommand, b: AppCommand) => (b.priority ?? 0) - (a.priority ?? 0)

/** Alle aktiven Befehle (oberste Registrierung je ID, `when` beim Rendern ausgewertet). */
export function useCommands(): AppCommand[] {
  const record = useRegistry((s) => s.commands)
  const all = useMemo(() => effective(record).sort(byPriority), [record])
  return all.filter((c) => !c.when || c.when())
}

/** Aktive Suchanbieter – stabile Referenz, solange sich die Registrierungen nicht ändern. */
export function useSearchProviders(): CommandSearchProvider[] {
  const record = useRegistry((s) => s.providers)
  return useMemo(() => effective(record), [record])
}

/** Aktive Befehle außerhalb von React lesen (z. B. für Tastenkürzel). */
export function getCommands(): AppCommand[] {
  return effective(useRegistry.getState().commands).filter((c) => !c.when || c.when())
}

/** Grund, warum ein Befehl gerade nicht ausführbar ist (`disabled`), sonst `null`. */
export function commandDisabledReason(cmd: AppCommand): string | null {
  const reason = cmd.disabled?.()
  return typeof reason === 'string' && reason.trim() ? reason.trim() : null
}

/** Befehl per ID ausführen (nicht, solange er `disabled` ist). */
export function runCommand(id: string, ctx: CommandContext): boolean {
  const cmd = getCommands().find((c) => c.id === id)
  if (!cmd || commandDisabledReason(cmd)) return false
  void cmd.run(ctx)
  return true
}

// --------------------------------------------------------------------------- Speichern (Strg+S)

export type SaveKind = 'save' | 'saveAs'

export interface SaveHandlerOptions {
  /** Aktiv? (Standard: ja) – z. B. nur bei ungespeicherten Änderungen. Inaktive Handler werden übersprungen. */
  enabled?: boolean
  /** Strg+⇧+S („Speichern unter …“); ohne diese Option bleibt Strg+⇧+S für ältere Handler/Befehle frei */
  saveAs?: () => void | Promise<unknown>
  /**
   * Der Handler gehört zu einem **modalen Dialog** und gilt auch, solange ein modaler Dialog offen ist
   * (Standard: nein – Seiten-Handler speichern nicht hinter einem offenen Dialog).
   */
  modal?: boolean
}

interface SaveEntry {
  token: number
  run: () => void | Promise<unknown>
  saveAs?: () => void | Promise<unknown>
  enabled: boolean
  modal: boolean
}

const saveHandlers = new Map<number, SaveEntry>()

/** Speichern-Handler registrieren (außerhalb von React). Gibt die Abmeldefunktion zurück. */
export function registerSaveHandler(
  run: () => void | Promise<unknown>,
  options: SaveHandlerOptions = {},
  token = nextRegistrationToken(),
): () => void {
  saveHandlers.set(token, { token, run, saveAs: options.saveAs, enabled: options.enabled ?? true, modal: options.modal ?? false })
  return () => {
    saveHandlers.delete(token)
  }
}

/**
 * Strg+S (und Strg+⇧+S über `saveAs`) für die aktuelle Seite bzw. den offenen Dialog übernehmen, solange die
 * Komponente gemountet ist. Es gilt der **zuletzt gemountete** aktive Handler (wie bei Befehlen); Befehle mit
 * `hotkey: 'mod+s'` nehmen an derselben Rangfolge teil. Die Shell verhindert immer den Browser-Dialog
 * „Seite speichern unter“ – auch hinter modalen Dialogen und bei gehaltener Taste (dann ohne Aufruf).
 *
 *   useSaveHandler(save, { enabled: dirty && !saving })
 *   useSaveHandler(submit, { modal: true })        // im Dialog: speichert den Dialog, nicht die Seite dahinter
 */
export function useSaveHandler(
  handler: (() => void | Promise<unknown>) | null | undefined,
  options: SaveHandlerOptions = {},
): void {
  const [token] = useState(nextRegistrationToken)
  const latest = useRef({ handler, options })
  useEffect(() => {
    latest.current = { handler, options }
  })
  const enabled = Boolean(handler) && (options.enabled ?? true)
  const hasSaveAs = Boolean(options.saveAs)
  const modal = options.modal ?? false
  useEffect(
    () =>
      registerSaveHandler(
        () => latest.current.handler?.(),
        { enabled, modal, saveAs: hasSaveAs ? () => latest.current.options.saveAs?.() : undefined },
        token,
      ),
    [enabled, hasSaveAs, modal, token],
  )
}

const SAVE_HOTKEY: Record<SaveKind, string> = { save: 'mod+s', saveAs: 'mod+shift+s' }

function sameHotkey(a: string, b: string): boolean {
  const x = parseHotkey(a)
  const y = parseHotkey(b)
  return x.key === y.key && x.ctrl === y.ctrl && x.meta === y.meta && x.alt === y.alt && x.shift === y.shift
}

function pickSaveTarget(kind: SaveKind, modal: boolean, ctx: CommandContext): (() => void | Promise<unknown>) | null {
  let best: { token: number; run: () => void | Promise<unknown> } | null = null
  for (const h of saveHandlers.values()) {
    if (!h.enabled || (modal && !h.modal)) continue
    const run = kind === 'save' ? h.run : h.saveAs
    if (run && (!best || h.token > best.token)) best = { token: h.token, run }
  }
  // Befehle mit Strg+S bzw. Strg+⇧+S (z. B. „symbols.save“) – nie hinter einem modalen Dialog
  if (!modal) {
    for (const list of Object.values(useRegistry.getState().commands)) {
      const entry = list[list.length - 1]
      const cmd = entry?.value
      if (!cmd?.hotkey || !sameHotkey(cmd.hotkey, SAVE_HOTKEY[kind]) || (cmd.when && !cmd.when())) continue
      if (!best || entry.token > best.token) best = { token: entry.token, run: () => cmd.run(ctx) }
    }
  }
  return best?.run ?? null
}

/** Ist für Strg+S (bzw. Strg+⇧+S) gerade etwas registriert – Handler oder Befehl? */
export function hasSaveTarget(kind: SaveKind = 'save', modal = false): boolean {
  return pickSaveTarget(kind, modal, { navigate: () => undefined, close: () => undefined }) !== null
}

/** Ist dieses Kürzel Strg+S bzw. Strg+⇧+S? (`null` = weder noch) */
export function saveKindOf(e: KeyboardEvent): SaveKind | null {
  if (matchesHotkey(e, SAVE_HOTKEY.save)) return 'save'
  if (matchesHotkey(e, SAVE_HOTKEY.saveAs)) return 'saveAs'
  return null
}

/**
 * Strg+S ausführen (von der Shell aufgerufen): oberster aktiver Handler bzw. Befehl. `modal` = ein modaler Dialog
 * ist offen (dann nur Handler mit `modal: true`). Liefert `false`, wenn nichts zu speichern ist.
 */
export function dispatchSave(kind: SaveKind, ctx: CommandContext, modal: boolean): boolean {
  const run = pickSaveTarget(kind, modal, ctx)
  if (!run) return false
  // Fehler meldet der Handler selbst (Toast/Inline) – hier nur als Hinweis protokollieren
  void Promise.resolve()
    .then(() => run())
    .catch((err: unknown) => console.warn('Speichern fehlgeschlagen', err))
  return true
}
