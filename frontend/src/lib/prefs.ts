/**
 * Kleine UI-Vorlieben (Theme, Seitenleiste) dauerhaft speichern.
 *
 * Das Desktop-Programm startet bei jedem Start auf einem **anderen Port** – localStorage gehört aber zum
 * Ursprung (Host + Port) und wäre jedes Mal leer. Cookies unterscheiden keine Ports: Ein Cookie auf
 * 127.0.0.1 überlebt also den Neustart. Deshalb wird in beide geschrieben und beim Lesen localStorage
 * (aktuelle Sitzung) vor dem Cookie (letzte Sitzung) bevorzugt.
 */
import type { StateStorage } from 'zustand/middleware'

const MAX_AGE = 60 * 60 * 24 * 400 // ~ 13 Monate (Obergrenze der Browser)

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const prefix = `${name}=`
  for (const part of document.cookie.split(';')) {
    const c = part.trim()
    if (c.startsWith(prefix)) {
      try {
        return decodeURIComponent(c.slice(prefix.length))
      } catch {
        return null
      }
    }
  }
  return null
}

function writeCookie(name: string, value: string | null): void {
  if (typeof document === 'undefined') return
  const v = value === null ? '' : encodeURIComponent(value)
  const age = value === null ? 0 : MAX_AGE
  document.cookie = `${name}=${v}; Max-Age=${age}; Path=/; SameSite=Strict`
}

export function readPref(name: string): string | null {
  try {
    const local = localStorage.getItem(name)
    if (local !== null) return local
  } catch {
    // Speicher gesperrt – Cookie versuchen
  }
  return readCookie(name)
}

export function writePref(name: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(name)
    else localStorage.setItem(name, value)
  } catch {
    // ignorieren – Cookie reicht
  }
  writeCookie(name, value)
}

/** zustand-`persist`-Speicher auf Basis von {@link readPref}/{@link writePref}. */
export const prefsStorage: StateStorage = {
  getItem: (name) => readPref(name),
  setItem: (name, value) => writePref(name, value),
  removeItem: (name) => writePref(name, null),
}
