/**
 * Ziel für die Speichern-Leiste: Die Einstellungsseite stellt eine mittig ausgerichtete, klebende Fläche unter dem
 * Inhalt bereit (über die ganze Seitenbreite) – so liegt die Leiste nie unter dem Job-Dock rechts unten.
 */
import { createContext, useContext } from 'react'

export const SaveBarSlotContext = createContext<HTMLElement | null>(null)

export function useSaveBarSlot(): HTMLElement | null {
  return useContext(SaveBarSlotContext)
}
