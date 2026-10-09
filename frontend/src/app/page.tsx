/**
 * Seiten-API der App-Shell:
 *
 *   <PageTitle title="Widerstände" subtitle="128 Bauteile" />   → Titel/Untertitel in der Topbar
 *   <PageActions><Button …/></PageActions>                       → Aktionen rechts in der Topbar (Portal, Größe „sm“)
 *   <PageBody>…</PageBody>                                        → Inhaltsbereich; die Topbar übernimmt Breite/Polsterung
 *   usePageHeading() aus '@/app/topbar'                           → eigene <h1> im Inhalt (Hero o. ä.) anmelden
 *
 * Ohne <PageTitle> zeigt die Topbar den Namen des Navigationspunkts. Der Topbar-Titel ist die <h1> der Seite –
 * außer die Seite meldet eine eigene an (PageHeader tut das automatisch).
 */
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ButtonDefaultsContext } from '@/components/ui/buttonContext'
import { cn } from '@/lib/cn'
import { PAGE_WIDTH_CLASS, useTopbar, type PageCrumb, type PageMeta, type PageWidth } from './topbar'

export type { PageCrumb, PageMeta, PageWidth } from './topbar'

/** Titel/Untertitel der aktuellen Seite in der Topbar setzen (solange gemountet). */
export function PageTitle({ title, subtitle, crumbs }: PageMeta) {
  const crumbKey = crumbs ? JSON.stringify(crumbs) : ''
  useEffect(() => {
    const parsed = crumbKey ? (JSON.parse(crumbKey) as PageCrumb[]) : undefined
    useTopbar.getState().setMeta({ title, subtitle, crumbs: parsed })
    return () => useTopbar.getState().setMeta(null)
  }, [title, subtitle, crumbKey])
  return null
}

const SM = { size: 'sm' } as const

/** Aktionen (Buttons) rechts in der Topbar platzieren. Buttons erhalten automatisch die Topbar-Größe „sm“. */
export function PageActions({ children }: { children: ReactNode }) {
  const el = useTopbar((s) => s.actionsEl)
  if (!el) return null
  return createPortal(<ButtonDefaultsContext.Provider value={SM}>{children}</ButtonDefaultsContext.Provider>, el)
}

export interface PageBodyProps {
  children: ReactNode
  /** default = 1400 px zentriert, narrow = 960 px, wide = 1680 px, full = volle Breite */
  width?: PageWidth
  /** Ohne Innenabstand (z. B. Tabellen-Seiten, die bis an den Rand reichen) */
  flush?: boolean
  className?: string
}

/** Standard-Inhaltsbereich einer Seite (Container für Container-Queries: `@container`). */
export function PageBody({ children, width = 'default', flush = false, className }: PageBodyProps) {
  useEffect(() => {
    useTopbar.getState().setLayout(width, flush)
    return () => useTopbar.getState().setLayout('default', false)
  }, [width, flush])
  return (
    <div className={cn('@container mx-auto w-full', PAGE_WIDTH_CLASS[width], !flush && 'px-8 pb-12 pt-6', className)}>
      {children}
    </div>
  )
}
