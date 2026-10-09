import { ChevronRight, Monitor, Moon, Search, Sun } from 'lucide-react'
import { useEffect, useState, type RefObject } from 'react'
import { Link, useLocation } from 'react-router'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  Kbd,
  Tooltip,
} from '@/components/ui'
import type { ThemePreference } from '@/api/system'
import { cn } from '@/lib/cn'
import { navItemForPath } from '../nav'
import { PAGE_WIDTH_CLASS, useTopbar } from '../topbar'
import { useUi } from '../stores'
import { useTheme } from '../theme'

/**
 * Seitenkopf: sitzt **im** Scrollbereich (`<main>`) und klebt oben. Inhalt nutzt dieselbe Breite wie
 * <PageBody>, damit Titel und Inhalt bündig sind. Beim Scrollen erscheinen Haarlinie und Unschärfe.
 */
export function Topbar({ scrollRef }: { scrollRef: RefObject<HTMLElement | null> }) {
  const { pathname } = useLocation()
  const nav = navItemForPath(pathname)
  const meta = useTopbar((s) => s.meta)
  const width = useTopbar((s) => s.width)
  const flush = useTopbar((s) => s.flush)
  const pageHasHeading = useTopbar((s) => s.headings > 0)
  const setActionsEl = useTopbar((s) => s.setActionsEl)
  const openPalette = useUi((s) => s.setCommandPaletteOpen)
  const scrolled = useScrolled(scrollRef)

  const sectionLabel = nav?.label ?? 'PartForge'
  const hasTitle = Boolean(meta?.title && meta.title !== sectionLabel)
  const title = hasTitle ? meta?.title : sectionLabel
  const crumbs = hasTitle ? [{ label: sectionLabel, to: nav?.to ?? '/' }, ...(meta?.crumbs ?? [])] : []
  // Eine <h1> je Seite: der Topbar-Titel, außer die Seite hat eine eigene (PageHeader, Hero)
  const TitleTag = pageHasHeading ? 'p' : 'h1'
  const container = cn(
    'mx-auto flex h-full w-full items-center gap-4',
    PAGE_WIDTH_CLASS[width === 'narrow' ? 'default' : width],
    flush && width === 'full' ? 'px-6' : 'px-8',
  )

  return (
    <header
      data-scrolled={scrolled || undefined}
      className={cn(
        'sticky top-0 z-sticky h-(--pf-topbar-height) shrink-0 border-b border-transparent transition-[background-color,border-color,box-shadow] duration-200',
        'data-[scrolled]:border-line data-[scrolled]:bg-[color-mix(in_oklab,var(--pf-bg)_78%,transparent)] data-[scrolled]:shadow-[0_8px_24px_-18px_rgba(0,0,0,.5)] data-[scrolled]:backdrop-blur-xl',
      )}
    >
      <div className={container}>
        {/* Titelbereich */}
        <div className="flex min-w-0 flex-1 flex-col justify-center">
          <div className="flex min-w-0 items-center gap-1.5 text-sm">
            {crumbs.length > 0 && (
              <nav aria-label="Brotkrumen" className="flex min-w-0 shrink items-center">
                <ol className="flex min-w-0 items-center gap-1.5">
                  {crumbs.map((c) => (
                    <li key={`${c.label}-${c.to ?? ''}`} className="flex min-w-0 items-center gap-1.5">
                      {c.to ? (
                        <Link
                          to={c.to}
                          className="truncate rounded-sm font-medium text-fg-muted outline-none transition-colors hover:text-fg focus-ring"
                        >
                          {c.label}
                        </Link>
                      ) : (
                        <span className="truncate font-medium text-fg-muted">{c.label}</span>
                      )}
                      <ChevronRight aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
                    </li>
                  ))}
                </ol>
              </nav>
            )}
            <TitleTag className="truncate text-sm font-semibold tracking-[-0.01em] text-fg">{title}</TitleTag>
          </div>
          {meta?.subtitle && <p className="truncate text-xs leading-4 text-fg-subtle">{meta.subtitle}</p>}
        </div>

        {/* Seitenaktionen (Portal-Ziel für <PageActions>) */}
        <div ref={setActionsEl} className="flex shrink-0 items-center gap-2 empty:hidden" />

        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => openPalette(true)}
            aria-keyshortcuts="Control+K"
            className={cn(
              'group/search flex h-7 w-[248px] items-center gap-2 rounded-control border border-line-strong bg-surface-2/70 pl-2.5 pr-1 text-left text-xs text-fg-subtle',
              'shadow-[inset_0_1px_0_var(--pf-highlight)] outline-none transition-[background-color,border-color,color] duration-150',
              'hover:border-line-control hover:bg-surface-2 hover:text-fg-muted focus-ring',
            )}
          >
            <Search aria-hidden className="size-3.5 shrink-0" />
            {/* Name aus dem sichtbaren Text („Suchen oder Befehl ausführen“) – Kbd ist Zierde (aria-keyshortcuts) */}
            <span className="flex-1 truncate">
              Suchen oder Befehl<span aria-hidden> …</span>
              <span className="sr-only"> ausführen</span>
            </span>
            <Kbd hotkey="mod+k" size="xs" />
          </button>
          <ThemeMenu />
        </div>
      </div>
    </header>
  )
}

/** true, sobald der Bereich gescrollt ist (für Haarlinie/Unschärfe der Topbar). */
function useScrolled(ref: RefObject<HTMLElement | null>): boolean {
  const [scrolled, setScrolled] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => setScrolled(el.scrollTop > 2)
    update()
    el.addEventListener('scroll', update, { passive: true })
    return () => el.removeEventListener('scroll', update)
  }, [ref])
  return scrolled
}

const THEME_OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: 'dark', label: 'Dunkel', icon: Moon },
  { value: 'light', label: 'Hell', icon: Sun },
  { value: 'system', label: 'Wie System', icon: Monitor },
]

export function ThemeMenu({ size = 'sm' }: { size?: 'sm' | 'md' }) {
  const { theme, resolvedTheme, setTheme } = useTheme()
  const Icon = resolvedTheme === 'dark' ? Moon : Sun
  return (
    <DropdownMenu>
      <Tooltip content="Darstellung" side="bottom">
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size={size} iconOnly aria-label="Darstellung wählen">
            <Icon />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="min-w-[11rem]">
        <DropdownMenuLabel>Darstellung</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as ThemePreference)}>
          {THEME_OPTIONS.map((o) => (
            <DropdownMenuRadioItem key={o.value} value={o.value} icon={<o.icon />}>
              {o.label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
