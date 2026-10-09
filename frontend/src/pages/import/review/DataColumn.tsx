import { useReducedMotion } from 'motion/react'
import { Check, ChevronDown, PanelLeftOpen, PanelRightOpen, PencilLine, Undo2 } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  IconButton,
  Spinner,
} from '@/components/ui'
import { useElementSize } from '@/components/preview'
import { cn } from '@/lib/cn'
import { useHotkey } from '@/lib/hotkeys'
import { TipButton } from '../shared/TipButton'
import { useReviewUi, type DataSection } from '../store'
import { useReview } from './context'
import type { Readiness } from './readiness'
import { ChecklistSection } from './sections/ChecklistSection'
import { IdentitySection } from './sections/IdentitySection'
import { NotesSection } from './sections/NotesSection'
import { PackagesSection } from './sections/PackagesSection'
import { ParametersSection } from './sections/ParametersSection'
import { PinsSection } from './sections/PinsSection'
import { VariantsSection } from './sections/VariantsSection'

interface NavItem {
  id: DataSection
  label: string
  check?: boolean
}

const NAV: NavItem[] = [
  { id: 'identitaet', label: 'Identität' },
  { id: 'varianten', label: 'Varianten' },
  { id: 'parameter', label: 'Parameter' },
  { id: 'pins', label: 'Pins' },
  { id: 'gehaeuse', label: 'Gehäuse' },
  { id: 'hinweise', label: 'Hinweise' },
]
/** Gehäusezeichnung ohne Bauteil: nur Gehäuse und Hinweise */
const PACKAGE_NAV: NavItem[] = NAV.filter((n) => n.id === 'gehaeuse' || n.id === 'hinweise')

/** Spalte 2: extrahierte Daten in Abschnitten (klebende Navigation, Sprünge aus Fundstellen und Prüfliste). */
export function DataColumn({ state, pdfCollapsed }: { state: Readiness; pdfCollapsed: boolean }) {
  const { ds, edit, extractionOut, device, packageOnly, proposal } = useReview()
  const focus = useReviewUi((s) => s.focusSection)
  const previewCollapsed = useReviewUi((s) => s.previewCollapsed)
  const refusal = useReviewUi((s) => s.refusal)
  const reduce = useReducedMotion()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [active, setActive] = useState<DataSection>(packageOnly ? 'gehaeuse' : 'identitaet')
  // „Prüfen“ in der Navigation: offene Probleme/Punkte, eine Pinbelegungs-Entscheidung oder eine abgelehnte Übernahme
  const needsCheck =
    state.openBlockers.length > 0 ||
    state.reasons.length > 0 ||
    Boolean(proposal?.symbols.some((s) => s.taken_changes.length > 0)) ||
    Boolean(refusal)

  // Sprungziel aus Fundstellen, Prüfliste oder Übernahmeleiste
  useEffect(() => {
    if (!focus) return
    const el = scrollRef.current?.querySelector<HTMLElement>(`#sec-${focus.id}`)
    if (!el) return
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    el.querySelector<HTMLElement>('h2')?.setAttribute('tabindex', '-1')
    el.querySelector<HTMLElement>('h2')?.focus({ preventScroll: true })
  }, [focus, reduce])

  // aktiver Abschnitt (Navigation hervorheben)
  useEffect(() => {
    const root = scrollRef.current
    if (!root || typeof IntersectionObserver === 'undefined') return
    const io = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        const id = visible[0]?.target.getAttribute('data-section') as DataSection | null
        if (id && id !== 'pruefen') setActive(id)
      },
      { root, rootMargin: '0px 0px -65% 0px', threshold: 0 },
    )
    root.querySelectorAll('[data-section]').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [ds.id])

  // Strg+Z: letzte Korrektur zurücknehmen (in Eingabefeldern gilt das native Rückgängig)
  useHotkey('mod+z', () => edit.undo(), { enabled: edit.canUndo, allowInInputs: false })

  const nav = packageOnly ? PACKAGE_NAV : NAV
  const items: NavItem[] = needsCheck ? [{ id: 'pruefen', label: 'Prüfen', check: true }, ...nav] : nav

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-bg">
      <div className="flex h-10 shrink-0 items-center gap-1 border-b border-line pl-1.5 pr-2">
        {pdfCollapsed && (
          <IconButton
            size="sm"
            label="PDF-Seiten einblenden"
            icon={<PanelLeftOpen />}
            onClick={() => useReviewUi.getState().setPdfCollapsed(false)}
          />
        )}
        <SectionNav items={items} active={active} />
        <div className="flex shrink-0 items-center gap-1.5" aria-live="polite">
          {edit.saving ? (
            <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
              <Spinner size={12} />
              <span className="hidden @[30rem]:inline">Wird gespeichert …</span>
              <span className="sr-only @[30rem]:hidden">Wird gespeichert …</span>
            </span>
          ) : extractionOut.edited ? (
            <TipButton
              tip="Sie haben die Extraktion korrigiert – die Originalantwort von Claude bleibt im Datenblatt gespeichert."
              label="Korrigiert"
              className="gap-1 rounded-sm text-2xs text-fg-subtle"
            >
              {edit.count > 0 ? <Check aria-hidden className="size-3 text-success-text" /> : <PencilLine aria-hidden className="size-3" />}
              <span aria-hidden className="hidden @[38rem]:inline">
                Korrigiert
              </span>
            </TipButton>
          ) : null}
          {edit.canUndo && (
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<Undo2 />}
              onClick={edit.undo}
              aria-keyshortcuts="Control+Z"
              title={edit.lastLabel ? `Rückgängig: ${edit.lastLabel}` : undefined}
            >
              <span className="hidden @[34rem]:inline">Rückgängig</span>
              <span className="sr-only @[34rem]:hidden">Rückgängig</span>
            </Button>
          )}
          {previewCollapsed && (
            <IconButton
              size="sm"
              label="Vorschau einblenden"
              icon={<PanelRightOpen />}
              onClick={() => useReviewUi.getState().setPreviewCollapsed(false)}
            />
          )}
        </div>
      </div>
      <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-y-auto">
        <ChecklistSection state={state} />
        {!packageOnly && (
          <>
            <IdentitySection />
            {/* je Bauteil neu aufbauen (Auswahl der Pintabelle u. Ä. gehört zum Bauteil) */}
            <VariantsSection key={`v-${device.base_part}`} />
            <ParametersSection />
            <PinsSection key={`p-${device.base_part}`} />
          </>
        )}
        <PackagesSection />
        <NotesSection />
        <div aria-hidden className="h-24" />
      </div>
    </div>
  )
}

const MORE_WIDTH = 76
const GAP = 2

/**
 * Abschnittsnavigation: so viele Einträge wie Platz haben, der Rest im Menü „Mehr“ (der aktive Abschnitt steht dann
 * auf dem Menüknopf). „Prüfen“ bleibt immer sichtbar.
 */
function SectionNav({ items, active }: { items: NavItem[]; active: DataSection }) {
  const [navRef, nav] = useElementSize<HTMLElement>()
  const measureRef = useRef<HTMLDivElement>(null)
  const [widths, setWidths] = useState<number[]>([])
  const labels = items.map((i) => i.label).join('|')

  // Breite jedes Eintrags messen (unsichtbare Kopie) – neu, sobald die Schrift geladen ist
  useLayoutEffect(() => {
    const measure = () => {
      const el = measureRef.current
      if (!el) return
      const next = [...el.children].map((c) => Math.ceil((c as HTMLElement).getBoundingClientRect().width))
      setWidths((prev) => (prev.join() === next.join() ? prev : next))
    }
    measure()
    void document.fonts?.ready.then(measure)
  }, [labels])

  let visible = items.length
  if (nav.width > 0 && widths.length === items.length) {
    const total = widths.reduce((sum, w) => sum + w + GAP, 0)
    if (total > nav.width) {
      let used = 0
      visible = 0
      for (const w of widths) {
        if (used + w + GAP > nav.width - MORE_WIDTH) break
        used += w + GAP
        visible += 1
      }
      visible = Math.max(items[0]?.check ? 1 : 0, visible)
    }
  }
  const shown = items.slice(0, visible)
  const hidden = items.slice(visible)
  const activeHidden = hidden.find((i) => i.id === active)
  const jump = (id: DataSection) => useReviewUi.getState().showSection(id)

  return (
    <nav ref={navRef} aria-label="Abschnitte" className="relative flex min-w-0 flex-1 items-center gap-0.5 overflow-hidden">
      {/* Messkopie (unsichtbar, nicht bedienbar) */}
      <div ref={measureRef} aria-hidden className="pointer-events-none invisible absolute left-0 top-0 flex gap-0.5">
        {items.map((n) => (
          <span key={n.id} className={navItemClass(false, n.check)}>
            {n.check && <span className="size-1.5 rounded-full bg-warning" />}
            {n.label}
          </span>
        ))}
      </div>
      {shown.map((n) => (
        <button
          key={n.id}
          type="button"
          aria-current={active === n.id ? 'location' : undefined}
          onClick={() => jump(n.id)}
          className={navItemClass(active === n.id, n.check)}
        >
          {n.check && <span aria-hidden className="size-1.5 rounded-full bg-warning" />}
          {n.label}
        </button>
      ))}
      {hidden.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className={cn(navItemClass(Boolean(activeHidden)), 'gap-1 pr-1.5')}>
              {activeHidden ? activeHidden.label : 'Mehr'}
              {/* Name = sichtbarer Text plus Zweck (kein abweichendes aria-label) */}
              <span className="sr-only">{activeHidden ? ' (aktueller Abschnitt) – weitere Abschnitte' : ' Abschnitte'}</span>
              <ChevronDown aria-hidden className="size-3.5 text-fg-subtle" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-40">
            {hidden.map((n) => (
              <DropdownMenuItem key={n.id} onSelect={() => jump(n.id)}>
                <span className={cn(active === n.id && 'font-semibold text-fg')}>{n.label}</span>
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </nav>
  )
}

function navItemClass(current: boolean, check?: boolean): string {
  return cn(
    'flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-control px-1.5 text-xs font-medium outline-none transition-colors focus-ring',
    check
      ? 'text-warning-text hover:bg-warning/10'
      : current
        ? 'bg-surface-2 text-fg'
        : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
  )
}
