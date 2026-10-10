import { useI18n } from '@/lib/i18n'
/**
 * Einstellungen: App-weite Einstellungen (Allgemein: Profil, Darstellung, KI, Altium) und die Einstellungen der
 * geöffneten Bibliothek (Bibliothek, Kategorien und Felder, Namensregeln, Hausstil).
 *
 * Die Bereiche stehen als Reiterzeile über dem Inhalt – so bekommen Schema-Designer und Hausstil die volle Breite
 * (neben der App-Seitenleiste gibt es keine zweite Navigationsspalte).
 *
 * Jeder Bereich hält seine Eingaben als Entwurf, zeigt die Speichern-Leiste (Strg+S) und fragt beim Verlassen
 * nach (`UnsavedChanges`). Kategorien/Felder ändern das Datenbankschema dagegen sofort – mit Rückgängig.
 * Bibliotheksbereiche werden beim Bibliothekswechsel neu aufgebaut (Schlüssel = Bibliotheksordner): Ein Entwurf
 * landet nie in einer anderen Bibliothek.
 */
import { motion } from 'motion/react'
import { Database, FolderClosed, ListTree, PenTool, SlidersHorizontal, Type, type LucideIcon } from 'lucide-react'
import { lazy, Suspense, useRef, useState, type KeyboardEvent } from 'react'
import { NavLink, useParams } from 'react-router'
import { useWorkspace } from '@/api/system'
import { PageBody, PageTitle } from '@/app/page'
import { useJobDock } from '@/app/stores'
import { Card, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { AllgemeinSection } from './AllgemeinSection'
import { BibliothekSection } from './BibliothekSection'
import { SaveBarSlotContext } from './saveBarSlot'

const KategorienSection = lazy(() => import('./kategorien/KategorienSection'))
const NamensregelnSection = lazy(() => import('./NamensregelnSection'))
const HausstilSection = lazy(() => import('./hausstil/HausstilSection'))

// --------------------------------------------------------------------------- Abschnitte

type SectionId = 'allgemein' | 'bibliothek' | 'kategorien' | 'namensregeln' | 'hausstil'

interface SectionDef {
  id: SectionId
  label: string
  icon: LucideIcon
  description: string
  scope: 'app' | 'library'
  /** `form` = Formularbreite (56 rem), `full` = ganze Breite (Designer mit Vorschau, eigenes Raster) */
  layout: 'form' | 'full'
}

const SECTIONS: SectionDef[] = [
  { id: 'allgemein', label: 'Allgemein', icon: SlidersHorizontal, scope: 'app', layout: 'full', description: 'Profil, Darstellung, KI und Altium' },
  { id: 'bibliothek', label: 'Bibliothek', icon: Database, scope: 'library', layout: 'form', description: 'Pfade, Datenbank, Teilenummern, Sicherungen' },
  { id: 'kategorien', label: 'Kategorien und Felder', icon: ListTree, scope: 'library', layout: 'full', description: 'Schema-Designer' },
  { id: 'namensregeln', label: 'Namensregeln', icon: Type, scope: 'library', layout: 'form', description: 'Footprint- und Symbolnamen, Dioden' },
  { id: 'hausstil', label: 'Hausstil', icon: PenTool, scope: 'library', layout: 'full', description: 'Footprints, Lagen und Symbole' },
]

export default function EinstellungenPage() {
  const { t } = useI18n()
  const { section = 'allgemein' } = useParams()
  const current = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0]
  const root = useWorkspace().data?.root ?? null
  const [slot, setSlot] = useState<HTMLElement | null>(null)
  // Speichern-Leiste über dem Job-Dock halten (wie die Toasts)
  const dockHeight = useJobDock((s) => (s.visible ? s.height : 0))

  return (
    <PageBody>
      <PageTitle title={t(current.label)} />
      <SettingsNav current={current.id} />
      <div className={cn('@container mt-6 min-w-0', current.layout === 'form' && 'max-w-[56rem]')}>
        <motion.div
          key={current.id}
          initial={{ opacity: 0, y: 4 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.16, ease: [0.2, 0.8, 0.2, 1] }}
        >
          <SaveBarSlotContext.Provider value={slot}>
            <Suspense fallback={<SectionSkeleton />}>
              {/* Bibliotheksbereiche gehören zu genau einer Bibliothek → bei einem Wechsel neu aufbauen */}
              <SectionContent key={current.scope === 'library' ? `lib:${root ?? '-'}` : 'app'} id={current.id} />
            </Suspense>
          </SaveBarSlotContext.Provider>
        </motion.div>
      </div>
      {/* Ziel der Speichern-Leiste (UnsavedChanges) – mittig, klebt unten, weicht dem Job-Dock aus */}
      <div
        ref={setSlot}
        className="pointer-events-none sticky z-sticky mt-4 transition-[bottom] duration-200"
        style={{ bottom: dockHeight ? dockHeight + 32 : 20 }}
      />
    </PageBody>
  )
}

function SectionContent({ id }: { id: SectionId }) {
  switch (id) {
    case 'bibliothek':
      return <BibliothekSection />
    case 'kategorien':
      return <KategorienSection />
    case 'namensregeln':
      return <NamensregelnSection />
    case 'hausstil':
      return <HausstilSection />
    default:
      return <AllgemeinSection />
  }
}

function SectionSkeleton() {
  const { t } = useI18n()
  return (
    <div className="flex max-w-[56rem] flex-col gap-5" aria-busy="true" aria-label={t("Bereich wird geladen")}>
      {[0, 1].map((i) => (
        <Card key={i} padding="lg" className="flex flex-col gap-4">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-24 w-full" />
        </Card>
      ))}
    </div>
  )
}

// --------------------------------------------------------------------------- Navigation

function SettingsNav({ current }: { current: SectionId }) {
  const { t } = useI18n()
  const workspace = useWorkspace()
  const libraryName = workspace.data?.name ?? null
  const ref = useRef<HTMLElement>(null)

  // Pfeiltasten wechseln zwischen den Bereichen (Tab verlässt die Navigation wie gewohnt)
  const onKeyDown = (e: KeyboardEvent<HTMLAnchorElement>) => {
    const keys = ['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End']
    if (!keys.includes(e.key)) return
    const links = Array.from(ref.current?.querySelectorAll<HTMLAnchorElement>('a[data-section]') ?? [])
    const index = links.indexOf(document.activeElement as HTMLAnchorElement)
    if (index < 0) return
    e.preventDefault()
    const next =
      e.key === 'Home'
        ? 0
        : e.key === 'End'
          ? links.length - 1
          : e.key === 'ArrowDown' || e.key === 'ArrowRight'
            ? (index + 1) % links.length
            : (index - 1 + links.length) % links.length
    links[next]?.focus()
  }

  const link = (s: SectionDef) => {
    const active = s.id === current
    return (
      <NavLink
        key={s.id}
        data-section={s.id}
        to={s.id === 'allgemein' ? '/einstellungen' : `/einstellungen/${s.id}`}
        end
        aria-current={active ? 'page' : undefined}
        title={t(s.description)}
        onKeyDown={onKeyDown}
        className={cn(
          'group/sn relative isolate flex h-9 shrink-0 items-center gap-2 whitespace-nowrap rounded-button px-3 text-ui font-medium outline-none transition-colors focus-ring',
          active ? 'text-fg' : 'text-fg-muted hover:bg-surface-2/70 hover:text-fg',
        )}
      >
        {active && (
          <motion.span
            layoutId="settings-nav"
            aria-hidden
            className="absolute inset-0 -z-10 rounded-button border border-line bg-surface shadow-card"
            transition={{ type: 'spring', stiffness: 500, damping: 40 }}
          />
        )}
        <s.icon aria-hidden className={cn('size-4 shrink-0', active ? 'text-fg' : 'text-fg-subtle')} />
        {t(s.label)}
      </NavLink>
    )
  }

  return (
    <nav ref={ref} aria-label={t("Einstellungsbereiche")} className="@container">
      <div className="-mx-1 flex items-center gap-1 overflow-x-auto px-1 py-0.5 scrollbar-none">
        {SECTIONS.filter((s) => s.scope === 'app').map(link)}
        <span aria-hidden className="mx-2 h-5 w-px shrink-0 bg-line-strong" />
        <span className="sr-only">{t("Einstellungen der Bibliothek")} {libraryName ?? t("(keine geöffnet)")}:</span>
        {SECTIONS.filter((s) => s.scope === 'library').map(link)}
        <span
          aria-hidden
          title={libraryName ? t("Diese Bereiche gelten für die Bibliothek „{0}“", { "0": libraryName }) : t("Keine Bibliothek geöffnet")}
          className="ml-auto hidden min-w-0 shrink items-center gap-1.5 pl-4 text-xs text-fg-subtle @[52rem]:flex"
        >
          <FolderClosed className="size-3.5 shrink-0" />
          <span className="truncate">{libraryName ?? t("Keine Bibliothek geöffnet")}</span>
        </span>
      </div>
    </nav>
  )
}
