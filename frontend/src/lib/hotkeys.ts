import { t as tr } from '@/lib/i18n'
import { useEffect, useRef } from 'react'

/**
 * Tastenkürzel. Schreibweise: 'mod+k', 'alt+1', 'shift+delete', 'escape'.
 * `mod` = Strg (Windows/Linux) bzw. ⌘ (macOS).
 */
export type Hotkey = string

interface ParsedHotkey {
  key: string
  ctrl: boolean
  alt: boolean
  shift: boolean
  meta: boolean
}

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

const KEY_ALIASES: Record<string, string> = {
  esc: 'escape',
  del: 'delete',
  entf: 'delete',
  return: 'enter',
  space: ' ',
  up: 'arrowup',
  down: 'arrowdown',
  left: 'arrowleft',
  right: 'arrowright',
  plus: '+',
}

const cache = new Map<string, ParsedHotkey>()

export function parseHotkey(hotkey: Hotkey): ParsedHotkey {
  const cached = cache.get(hotkey)
  if (cached) return cached
  const parts = hotkey
    .toLowerCase()
    .split('+')
    .map((p) => p.trim())
  // „mod+plus“ bzw. „mod++“
  const rawKey = parts[parts.length - 1] === '' ? '+' : parts[parts.length - 1]
  const mods = new Set(parts.slice(0, -1))
  const parsed: ParsedHotkey = {
    key: KEY_ALIASES[rawKey] ?? rawKey,
    ctrl: mods.has('ctrl') || mods.has('strg') || (mods.has('mod') && !IS_MAC),
    meta: mods.has('meta') || mods.has('cmd') || (mods.has('mod') && IS_MAC),
    alt: mods.has('alt'),
    shift: mods.has('shift'),
  }
  cache.set(hotkey, parsed)
  return parsed
}

function eventKey(e: KeyboardEvent, wanted: string): boolean {
  // Ziffern über den physischen Code (Umschalt/AltGr ändern e.key). Nur die Zifferntasten der Hauptreihe:
  // Alt + Ziffernblock sind Windows-Alt-Codes (Alt+0177 = ±, Alt+234 = Ω) und dürfen nichts auslösen.
  if (/^[0-9]$/.test(wanted)) return e.code === `Digit${wanted}`
  return e.key.toLowerCase() === wanted
}

export function matchesHotkey(e: KeyboardEvent, hotkey: Hotkey): boolean {
  const h = parseHotkey(hotkey)
  if (e.ctrlKey !== h.ctrl || e.metaKey !== h.meta || e.altKey !== h.alt) return false
  // Umschalt nur prüfen, wenn es Teil des Kürzels ist oder die Taste kein Zeichen erzeugt
  if (h.shift !== e.shiftKey && (h.shift || h.key.length > 1 || /[a-z0-9]/.test(h.key))) return false
  return eventKey(e, h.key)
}

/** Kürzel nur mit Alt (ohne Strg/⌘) – in Eingabefeldern tabu (Windows-Alt-Codes, AltGr-Zeichen). */
export function isAltOnly(hotkey: Hotkey): boolean {
  const h = parseHotkey(hotkey)
  return h.alt && !h.ctrl && !h.meta
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type
    return !['checkbox', 'radio', 'button', 'submit', 'reset', 'range', 'color', 'file'].includes(type)
  }
  return target.closest('[role="textbox"], [role="combobox"]') !== null
}

const LABELS: Record<string, string> = {
  get mod() { return IS_MAC ? '⌘' : tr('Strg') },
  get ctrl() { return tr("Strg") },
  get strg() { return tr("Strg") },
  cmd: '⌘',
  meta: IS_MAC ? '⌘' : 'Win',
  alt: IS_MAC ? '⌥' : 'Alt',
  shift: '⇧',
  escape: 'Esc',
  esc: 'Esc',
  enter: '↵',
  get delete() { return tr("Entf") },
  get del() { return tr("Entf") },
  backspace: '⌫',
  arrowup: '↑',
  arrowdown: '↓',
  arrowleft: '←',
  arrowright: '→',
  up: '↑',
  down: '↓',
  get space() { return tr("Leertaste") },
  tab: 'Tab',
}

/** 'mod+shift+k' → ['Strg', '⇧', 'K'] */
export function hotkeyLabels(hotkey: Hotkey): string[] {
  return hotkey
    .split('+')
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean)
    .map((p) => LABELS[p] ?? (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)))
}

/** 'mod+k' → 'Strg+K' (für Tooltips und Screenreader-Texte) */
export function formatHotkey(hotkey: Hotkey): string {
  return hotkeyLabels(hotkey).join('+')
}

const ARIA_KEYS: Record<string, string> = {
  mod: IS_MAC ? 'Meta' : 'Control',
  ctrl: 'Control',
  strg: 'Control',
  cmd: 'Meta',
  meta: 'Meta',
  alt: 'Alt',
  shift: 'Shift',
  esc: 'Escape',
  escape: 'Escape',
  del: 'Delete',
  entf: 'Delete',
  delete: 'Delete',
  enter: 'Enter',
  return: 'Enter',
  space: 'Space',
  up: 'ArrowUp',
  down: 'ArrowDown',
  left: 'ArrowLeft',
  right: 'ArrowRight',
}

/** 'mod+k' → 'Control+K' – Wert für das Attribut `aria-keyshortcuts`. */
export function ariaKeyshortcuts(hotkey: Hotkey): string {
  return hotkey
    .split('+')
    .map((p) => p.trim().toLowerCase())
    .filter(Boolean)
    .map((p) => ARIA_KEYS[p] ?? (p.length === 1 ? p.toUpperCase() : p[0].toUpperCase() + p.slice(1)))
    .join('+')
}

export interface UseHotkeyOptions {
  enabled?: boolean
  /** Auch auslösen, wenn der Fokus in einem Eingabefeld liegt (Standard: nur mit Strg/⌘ – nie mit Alt allein). */
  allowInInputs?: boolean
  preventDefault?: boolean
  /** Ereignis in der Capture-Phase abfangen (vor Radix/cmdk). */
  capture?: boolean
}

/** Globales Tastenkürzel (window keydown). Der Handler darf sich bei jedem Render ändern. */
export function useHotkey(
  hotkey: Hotkey | Hotkey[],
  handler: (e: KeyboardEvent) => void,
  { enabled = true, allowInInputs, preventDefault = true, capture = false }: UseHotkeyOptions = {},
): void {
  const handlerRef = useRef(handler)
  useEffect(() => {
    handlerRef.current = handler
  })
  const keys = Array.isArray(hotkey) ? hotkey.join('|') : hotkey

  useEffect(() => {
    if (!enabled) return
    const list = keys.split('|')
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.isComposing || e.repeat) return
      const hit = list.find((k) => matchesHotkey(e, k))
      if (!hit) return
      const parsed = parseHotkey(hit)
      const hasModifier = parsed.ctrl || parsed.meta
      const inInput = isEditableTarget(e.target)
      if (inInput && !(allowInInputs ?? hasModifier)) return
      if (preventDefault) e.preventDefault()
      handlerRef.current(e)
    }
    window.addEventListener('keydown', onKeyDown, { capture })
    return () => window.removeEventListener('keydown', onKeyDown, { capture })
  }, [keys, enabled, allowInInputs, preventDefault, capture])
}
