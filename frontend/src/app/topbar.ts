import { useEffect } from 'react'
import { create } from 'zustand'

export interface PageCrumb {
  label: string
  /** Ziel (Link); ohne Ziel nur Text */
  to?: string
}

export interface PageMeta {
  title?: string
  subtitle?: string
  /** Zusätzliche Brotkrumen zwischen Bereich und Titel */
  crumbs?: PageCrumb[]
}

/** Inhaltsbreite der Seite – die Topbar übernimmt sie, damit Titel und Inhalt bündig sind. */
export type PageWidth = 'default' | 'narrow' | 'wide' | 'full'

interface TopbarState {
  meta: PageMeta | null
  actionsEl: HTMLElement | null
  /** Breite/Polsterung der aktuellen Seite (aus <PageBody>) */
  width: PageWidth
  flush: boolean
  /** > 0: Die Seite hat eine eigene <h1> (PageHeader, Hero) – die Topbar zeigt den Titel dann ohne Überschrift */
  headings: number
  setMeta: (meta: PageMeta | null) => void
  setActionsEl: (el: HTMLElement | null) => void
  setLayout: (width: PageWidth, flush: boolean) => void
}

/** Zustand der Topbar (Titel der aktuellen Seite, Portal-Ziel für Seitenaktionen, Layout, Überschrift). */
export const useTopbar = create<TopbarState>((set) => ({
  meta: null,
  actionsEl: null,
  width: 'default',
  flush: false,
  headings: 0,
  setMeta: (meta) => set({ meta }),
  setActionsEl: (actionsEl) => set({ actionsEl }),
  setLayout: (width, flush) => set({ width, flush }),
}))

/** Eigene Seitenüberschrift (h1) anmelden; gibt die Abmeldung zurück. */
export function claimPageHeading(): () => void {
  useTopbar.setState((s) => ({ headings: s.headings + 1 }))
  return () => useTopbar.setState((s) => ({ headings: Math.max(0, s.headings - 1) }))
}

/** Die Seite rendert eine eigene <h1> (z. B. Hero) – die Topbar verzichtet dann auf ihre Überschrift. */
export function usePageHeading(active = true): void {
  useEffect(() => (active ? claimPageHeading() : undefined), [active])
}

/** Max. Breite je Variante – von <PageBody> und der Topbar genutzt (bündige Kanten). */
export const PAGE_WIDTH_CLASS: Record<PageWidth, string> = {
  narrow: 'max-w-[960px]',
  default: 'max-w-[1400px]',
  wide: 'max-w-[1680px]',
  full: 'max-w-none',
}
