/**
 * Modul „Footprints“: Generator (IPC-7351B, live) und Bibliothek (gespeicherte Footprints + Vorlagen-Katalog).
 *
 * Adressen: `/footprints` (Generator) · `/footprints?ansicht=bibliothek[&quelle=katalog][&fp=<Name>]` ·
 * `/footprints?familie=<Schlüssel oder Alias>&vorlage=<Vorlage>` (Generator mit Vorlage, z. B. aus anderen Modulen).
 */
import { DraftingCompass, LibraryBig, PenTool, RefreshCw } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useFootprintFamilies, type FootprintFamily, type FootprintPreset } from '@/api/footprints'
import { useLibraryStats } from '@/api/library'
import { useWorkspace } from '@/api/system'
import { useSaveHandler } from '@/app/commands'
import { PageBody, PageTitle } from '@/app/page'
import { useJobDock } from '@/app/stores'
import { Button, EmptyState, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from '@/components/ui'
import { formatNumber } from '@/lib/format'
import { GeneratorView } from './generator/GeneratorView'
import { useGenerator } from './generator/store'
import { useGeneratorUi } from './generator/uiPrefs'
import { ROUNDING_LABEL } from './lib/calc'
import { aliasFamily, familyShortLabel, normalizeTerm } from './lib/families'
import { formatDim } from './lib/params'
import { FootprintDetailDialog, type RegenerateHandler } from './library/FootprintDetailDialog'
import { LibraryView, type LibrarySource } from './library/LibraryView'

type View = 'generator' | 'bibliothek'

export default function FootprintsPage() {
  const [params, setParams] = useSearchParams()
  const view: View = params.get('ansicht') === 'bibliothek' ? 'bibliothek' : 'generator'
  const source: LibrarySource = params.get('quelle') === 'katalog' ? 'katalog' : 'bibliothek'
  const openName = params.get('fp')
  const familiesQ = useFootprintFamilies()
  const families = familiesQ.data
  const stats = useLibraryStats()
  const workspace = useWorkspace().data
  const style = workspace?.settings.footprint
  const family = useGenerator((s) => families?.find((f) => f.key === s.family) ?? null)

  // Platz für die Job-Pille unten rechts (geschlossenes Dock) – sonst verdeckt sie Messleiste und Protokoll
  const dockVisible = useJobDock((s) => s.visible)
  const dockOpen = useJobDock((s) => s.open)
  const dockHeight = useJobDock((s) => s.height)
  const bottomSpace = dockVisible && !dockOpen && dockHeight > 0 ? { paddingBottom: 20 + dockHeight + 8 } : undefined

  // Bibliothek erst beim ersten Besuch laden, danach gemountet lassen (Scroll-Position, Filter)
  const [libraryMounted, setLibraryMounted] = useState(view === 'bibliothek')
  if (view === 'bibliothek' && !libraryMounted) setLibraryMounted(true)

  const update = (change: (p: URLSearchParams) => void, replace = false) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        change(next)
        return next
      },
      { replace },
    )

  const setView = (v: View) =>
    update((p) => {
      if (v === 'generator') {
        p.delete('ansicht')
        p.delete('fp')
      } else p.set('ansicht', v)
    })

  // Deep-Link: Familie (Schlüssel oder Alias) + Vorlage im Generator öffnen
  const linkFamily = params.get('familie')
  const linkPreset = params.get('vorlage')
  useEffect(() => {
    if (!linkFamily || !families) return
    const f = families.find((x) => x.key === linkFamily) ?? aliasFamily(families, linkFamily)
    if (f) {
      const wanted = normalizeTerm(linkPreset ?? '')
      const preset = wanted ? (f.presets.find((p) => normalizeTerm(p.key) === wanted) ?? null) : null
      useGenerator.getState().selectFamily(f, preset)
      if (linkPreset && !preset) {
        toast.info(`Vorlage „${linkPreset}“ nicht gefunden`, {
          id: 'fp-deeplink',
          description: `${familyShortLabel(f)} ist geöffnet – bitte die passende Vorlage wählen.`,
        })
      }
    } else {
      toast.error('Gehäusefamilie unbekannt', { id: 'fp-deeplink', description: `„${linkFamily}“ gibt es im Generator nicht.` })
    }
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('familie')
        next.delete('vorlage')
        next.delete('ansicht')
        return next
      },
      { replace: true },
    )
  }, [linkFamily, linkPreset, families, setParams])

  const openInGenerator = (f: FootprintFamily, preset: FootprintPreset) => {
    useGenerator.getState().selectFamily(f, preset)
    setView('generator')
  }

  const regenerate: RegenerateHandler = (f, generator, { name }) => {
    useGenerator.getState().loadSnapshot(f, generator, {
      styleRounding: style?.rounding,
      label: 'Gespeicherte Parameter geladen',
      name,
      notice: name ? `Parameter von „${name}“ geladen – der eigene Name bleibt beim Speichern erhalten` : undefined,
    })
    setView('generator')
  }

  const newFootprint = () => {
    setView('generator')
    useGeneratorUi.getState().setPickerOpen(true)
  }

  // Strg+S in der Bibliothek: nichts zu speichern (Hinweis) – im Generator speichert der Befehl „footprints.save“
  const nothingToSave = () => {
    toast.info('Nichts zu speichern', {
      id: 'fp-save-hint',
      description: 'Die Bibliothek ist immer aktuell. Neue und geänderte Footprints speichert der Generator (Strg+S).',
    })
  }
  useSaveHandler(nothingToSave, { enabled: view === 'bibliothek', saveAs: nothingToSave })

  const libraryCount = stats.data?.footprints.total
  const presetCount = families?.reduce((n, f) => n + f.presets.length, 0)
  const shownSource = source
  const subtitle =
    view === 'generator'
      ? family
        ? `Generator · ${familyShortLabel(family)}`
        : 'Generator nach IPC-7351B'
      : shownSource === 'katalog'
        ? `Katalog · ${presetCount !== undefined ? `${formatNumber(presetCount)} Vorlagen` : 'Vorlagen'}`
        : libraryCount !== undefined
          ? `Bibliothek · ${formatNumber(libraryCount)} Footprints`
          : 'Bibliothek'

  return (
    <PageBody width="full" flush className="flex h-[calc(100dvh-var(--pf-topbar-height,3.5rem))] min-h-[40rem] flex-col">
      <PageTitle title="Footprints" subtitle={subtitle} />
      <Tabs value={view} onValueChange={(v) => setView(v as View)} className="min-h-0 flex-1">
        <div className="flex shrink-0 items-end gap-4 border-b border-line px-6">
          <TabsList aria-label="Ansicht" className="border-b-0">
            <TabsTrigger value="generator" icon={<DraftingCompass />}>
              Generator
            </TabsTrigger>
            <TabsTrigger
              value="bibliothek"
              icon={<LibraryBig />}
              count={libraryCount !== undefined ? formatNumber(libraryCount) : undefined}
            >
              Bibliothek
            </TabsTrigger>
          </TabsList>
          {view === 'generator' && style && (
            <div className="ml-auto hidden h-10 min-w-0 items-center gap-2 text-2xs text-fg-subtle xl:flex">
              <span className="micro-label">Hausstil</span>
              <span className="flex min-w-0 items-center gap-1.5">
                <StyleChip>{style.naming === 'ipc' ? 'IPC-Namen' : 'Hausnamen'}</StyleChip>
                <StyleChip>Rundung {ROUNDING_LABEL[style.rounding] ?? style.rounding}</StyleChip>
                <StyleChip>
                  F {formatDim(style.fab_tolerance)} · P {formatDim(style.placement_tolerance)}
                </StyleChip>
                <StyleChip>{style.generate_3d ? '3D an' : '3D aus'}</StyleChip>
              </span>
              <Tooltip content="Hausstil der Bibliothek bearbeiten">
                <Link
                  to="/einstellungen/hausstil"
                  aria-label="Hausstil bearbeiten"
                  className="flex size-6 items-center justify-center rounded-control text-fg-subtle outline-none transition-colors hover:bg-surface-2 hover:text-fg focus-ring"
                >
                  <PenTool aria-hidden className="size-3.5" />
                </Link>
              </Tooltip>
            </div>
          )}
        </div>

        {!families ? (
          familiesQ.isError ? (
            <div className="flex flex-1 items-center justify-center p-6">
              <EmptyState
                illustration="offline"
                titleAs="h2"
                title="Gehäusefamilien konnten nicht geladen werden"
                description={errorMessage(familiesQ.error)}
                actions={
                  <Button variant="secondary" leftIcon={<RefreshCw />} onClick={() => void familiesQ.refetch()}>
                    Erneut versuchen
                  </Button>
                }
              />
            </div>
          ) : (
            <PageSkeleton />
          )
        ) : (
          <>
            <TabsContent
              value="generator"
              forceMount
              tabIndex={-1}
              style={bottomSpace}
              className="min-h-0 flex-1 px-6 pb-5 pt-4 data-[state=inactive]:hidden"
            >
              <GeneratorView
                families={families}
                active={view === 'generator'}
                onShowLibrary={(name) =>
                  update((p) => {
                    p.set('ansicht', 'bibliothek')
                    p.delete('quelle')
                    if (name) p.set('fp', name)
                  })
                }
              />
            </TabsContent>
            <TabsContent
              value="bibliothek"
              forceMount={libraryMounted || undefined}
              tabIndex={-1}
              style={bottomSpace}
              className="min-h-0 flex-1 px-6 pb-5 pt-4 data-[state=inactive]:hidden"
            >
              {libraryMounted && (
                <LibraryView
                  families={families}
                  active={view === 'bibliothek'}
                  source={source}
                  onSourceChange={(s) =>
                    update(
                      (p) => {
                        if (s === 'katalog') p.set('quelle', 'katalog')
                        else p.delete('quelle')
                      },
                      true,
                    )
                  }
                  selected={openName}
                  onOpen={(name) => {
                    if (params.get('fp') !== name) update((p) => p.set('fp', name))
                  }}
                  onOpenPreset={openInGenerator}
                  onNew={newFootprint}
                />
              )}
            </TabsContent>
            <FootprintDetailDialog
              name={view === 'bibliothek' ? openName : null}
              families={families}
              onClose={() => update((p) => p.delete('fp'), true)}
              onRegenerate={regenerate}
            />
          </>
        )}
      </Tabs>
    </PageBody>
  )
}

function StyleChip({ children }: { children: ReactNode }) {
  return (
    <span className="mono whitespace-nowrap rounded-md border border-line bg-surface px-1.5 py-0.5 text-2xs text-fg-muted">
      {children}
    </span>
  )
}

/** Platzhalter beim Laden der Familien – gleiche Spaltenaufteilung wie der Generator (Container-Query) */
function PageSkeleton() {
  return (
    <div
      aria-hidden
      className="grid min-h-0 flex-1 grid-cols-[clamp(316px,34%,348px)_minmax(0,1fr)] gap-3 px-6 pb-5 pt-4 @[75.5rem]:grid-cols-[clamp(316px,28%,348px)_minmax(0,1fr)_clamp(272px,23%,300px)]"
    >
      <div className="flex flex-col gap-3 rounded-card border border-line bg-surface p-4">
        <Skeleton className="h-14" />
        <Skeleton className="h-3 w-20" />
        <div className="flex flex-col gap-1">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-6" />
          ))}
        </div>
        <Skeleton className="h-8" />
        {Array.from({ length: 8 }, (_, i) => (
          <Skeleton key={i} className="h-6" />
        ))}
      </div>
      <div className="rounded-card border border-line bg-canvas" />
      <div className="hidden flex-col gap-3 rounded-card border border-line bg-surface p-4 @[75.5rem]:flex">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-16" />
        <Skeleton className="h-24" />
      </div>
    </div>
  )
}
