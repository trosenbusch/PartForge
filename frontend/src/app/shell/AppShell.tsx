import { motion } from 'motion/react'
import { useEffect, useLayoutEffect, useRef, useState, type RefObject } from 'react'
import { Navigate, Outlet, useLocation, useOutlet } from 'react-router'
import { useWorkspace } from '@/api/system'
import { navItemForPath } from '../nav'
import { useTopbar } from '../topbar'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

/** Hauptlayout: Sidebar links, rechts der Scrollbereich mit klebender Topbar und Seiteninhalt. */
export function AppShell() {
  const mainRef = useRef<HTMLElement>(null)
  return (
    <div className="flex h-screen w-full min-w-[1120px] overflow-hidden">
      <a
        href="#main"
        onClick={(e) => {
          // Fokus setzen, ohne „#main“ an die Adresse zu hängen
          e.preventDefault()
          mainRef.current?.focus({ preventScroll: true })
        }}
        className="fixed left-3 top-3 z-skip -translate-y-16 rounded-button bg-surface-3 px-3 py-2 text-ui text-fg shadow-pop transition-transform focus:translate-y-0"
      >
        Zum Inhalt springen
      </a>
      <Sidebar />
      <main
        id="main"
        ref={mainRef}
        tabIndex={-1}
        className="relative min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden outline-none [scrollbar-gutter:stable]"
      >
        <Topbar scrollRef={mainRef} />
        <PageTransition scrollRef={mainRef} />
      </main>
      <RouteAnnouncer />
    </div>
  )
}

/** Seitenwechsel: Fade + 6 px Slide (180 ms). Schlüssel = erster Pfadabschnitt (Unterseiten ohne Remount). */
function PageTransition({ scrollRef }: { scrollRef: RefObject<HTMLElement | null> }) {
  const { pathname } = useLocation()
  const outlet = useOutlet()
  const section = pathname.split('/')[1] || 'uebersicht'

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [section, scrollRef])

  return (
    <motion.div
      key={section}
      className="min-h-[calc(100%-var(--pf-topbar-height))]"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
    >
      {outlet}
    </motion.div>
  )
}

/** Sagt Seitenwechsel für Screenreader an („Bauteile – Widerstände“). */
function RouteAnnouncer() {
  const { pathname } = useLocation()
  const meta = useTopbar((s) => s.meta)
  const [message, setMessage] = useState('')
  const first = useRef(true)
  const label = navItemForPath(pathname)?.label ?? 'PartForge'
  const text = meta?.title && meta.title !== label ? `${label} – ${meta.title}` : label

  useEffect(() => {
    if (first.current) {
      first.current = false
      return
    }
    // kurz verzögert, damit der neue Seitentitel (PageTitle) schon gesetzt ist
    const t = setTimeout(() => setMessage(`Seite: ${text}`), 120)
    return () => clearTimeout(t)
  }, [pathname, text])

  useEffect(() => {
    document.title = text === 'PartForge' ? 'PartForge' : `${text} · PartForge`
  }, [text])

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {message}
    </div>
  )
}

/** Leitet auf /willkommen um, wenn keine Bibliothek geöffnet ist. */
export function WorkspaceGuard() {
  const workspace = useWorkspace().data
  const location = useLocation()
  if (workspace === null) return <Navigate to="/willkommen" replace state={{ from: location.pathname }} />
  return <Outlet />
}
