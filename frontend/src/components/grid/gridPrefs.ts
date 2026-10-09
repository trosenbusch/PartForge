/**
 * Spaltenzustand (Reihenfolge, Breiten, ausgeblendete Spalten, Sortierung, Anheften) je Tabelle dauerhaft speichern.
 *
 * - localStorage `pf-grid:<schlüssel>` – vollständig (gilt, solange der Port gleich bleibt)
 * - Cookie-Pref `pf-grids` – kompakte Karte der **zuletzt benutzten** Tabellen, begrenzt auf ~3 KB, damit sie den
 *   Neustart (neuer Port) überlebt, ohne jede API-Anfrage mit großen Cookies zu belasten (LRU-Verdrängung).
 */
import type { GridState } from 'ag-grid-community'
import { readPref, writePref } from '@/lib/prefs'

interface CompactState {
  /** Spaltenreihenfolge */
  o?: string[]
  /** Breiten */
  w?: Record<string, number>
  /** ausgeblendet */
  h?: string[]
  /** Sortierung: [Spalte, 'a' | 'd'] */
  s?: [string, 'a' | 'd'][]
  /** angeheftet: [links, rechts] */
  p?: [string[], string[]]
}

const LOCAL_PREFIX = 'pf-grid:'
const MAP_KEY = 'pf-grids'
const MAP_LIMIT = 3000

function toCompact(state: GridState): CompactState {
  const c: CompactState = {}
  if (state.columnOrder?.orderedColIds?.length) c.o = state.columnOrder.orderedColIds
  const widths = state.columnSizing?.columnSizingModel?.filter((m) => typeof m.width === 'number' && !m.flex)
  if (widths?.length) c.w = Object.fromEntries(widths.map((m) => [m.colId, Math.round(m.width as number)]))
  if (state.columnVisibility?.hiddenColIds?.length) c.h = state.columnVisibility.hiddenColIds
  if (state.sort?.sortModel?.length) c.s = state.sort.sortModel.map((m) => [m.colId, m.sort === 'desc' ? 'd' : 'a'])
  const left = state.columnPinning?.leftColIds ?? []
  const right = state.columnPinning?.rightColIds ?? []
  if (left.length || right.length) c.p = [left, right]
  return c
}

function fromCompact(c: CompactState): GridState {
  const state: GridState = {}
  if (c.o?.length) state.columnOrder = { orderedColIds: c.o }
  if (c.w) state.columnSizing = { columnSizingModel: Object.entries(c.w).map(([colId, width]) => ({ colId, width })) }
  if (c.h?.length) state.columnVisibility = { hiddenColIds: c.h }
  if (c.s?.length) state.sort = { sortModel: c.s.map(([colId, d]) => ({ colId, sort: d === 'd' ? 'desc' : 'asc' })) }
  if (c.p) state.columnPinning = { leftColIds: c.p[0] ?? [], rightColIds: c.p[1] ?? [] }
  return state
}

type StoredMap = Record<string, [number, CompactState]>

function readMap(): StoredMap {
  try {
    const raw = readPref(MAP_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : null
    return parsed && typeof parsed === 'object' ? (parsed as StoredMap) : {}
  } catch {
    return {}
  }
}

/** Gespeicherten Spaltenzustand lesen (für `initialState`) */
export function loadGridState(key: string): GridState | undefined {
  try {
    const local = localStorage.getItem(LOCAL_PREFIX + key)
    if (local) return fromCompact(JSON.parse(local) as CompactState)
  } catch {
    // Speicher gesperrt – Cookie versuchen
  }
  const entry = readMap()[key]
  return entry ? fromCompact(entry[1]) : undefined
}

/** Spaltenzustand speichern (lokal vollständig, im Cookie begrenzt) */
export function saveGridState(key: string, state: GridState): void {
  const compact = toCompact(state)
  const json = JSON.stringify(compact)
  try {
    localStorage.setItem(LOCAL_PREFIX + key, json)
  } catch {
    // ignorieren
  }
  const map = readMap()
  map[key] = [Date.now(), compact]
  const keys = Object.keys(map).sort((a, b) => map[a][0] - map[b][0])
  // älteste Einträge verdrängen, bis die Karte klein genug ist
  while (keys.length > 1 && encodeURIComponent(JSON.stringify(map)).length > MAP_LIMIT) {
    const oldest = keys.shift()
    if (oldest && oldest !== key) delete map[oldest]
  }
  if (encodeURIComponent(JSON.stringify(map)).length > MAP_LIMIT) return // einzelne Tabelle zu groß: nur lokal
  writePref(MAP_KEY, JSON.stringify(map))
}

/** Gespeicherten Zustand verwerfen („Spalten zurücksetzen“) */
export function clearGridState(key: string): void {
  try {
    localStorage.removeItem(LOCAL_PREFIX + key)
  } catch {
    // ignorieren
  }
  const map = readMap()
  if (map[key]) {
    delete map[key]
    writePref(MAP_KEY, Object.keys(map).length ? JSON.stringify(map) : null)
  }
}
