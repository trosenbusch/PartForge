import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Modul „Symbole“ (/symbole): Ansichten „Generator“ (Standard) und „Bibliothek“.
 *
 * Adressen: `/symbole?ansicht=bibliothek` öffnet die Bibliothek, `/symbole?art=<typ>` wählt einen Symboltyp im
 * Generator (z. B. aus der Befehlspalette: Suchanbieter „Symboltypen“; unbekannte Typen werden gemeldet).
 */
import { Hammer, Library, PanelLeftClose, PanelLeftOpen, PenTool, Shapes } from 'lucide-react'
import { useCallback, useEffect } from 'react'
import { Link, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useSymbolKinds, useSymbolLibrary } from '@/api/symbols'
import { useWorkspace } from '@/api/system'
import { useRegisterCommands, useRegisterSearchProvider, useSaveHandler } from '@/app/commands'
import { PageBody, PageTitle } from '@/app/page'
import { useTheme } from '@/app/theme'
import { useElementSize } from '@/components/preview'
import { IconButton, Tabs, TabsContent, TabsList, TabsTrigger, Tooltip } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { GeneratorView } from './generator/GeneratorView'
import type { OpenResult } from './generator/load'
import { LibraryView } from './library/LibraryView'
import { IC_KIND, useGenerator, useLibraryFilters, useSymbolUiPrefs } from './store'

type View = 'generator' | 'library'

/** Ab dieser Breite bleibt die Symboltypen-Leiste im IC-Editor standardmäßig offen */
const IC_KINDS_OPEN_FROM = 1440

const fold = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')

export default function SymbolePage() {
  useI18n()
  const [params, setParams] = useSearchParams()
  const view: View = params.get('ansicht') === 'bibliothek' ? 'library' : 'generator'
  const { resolvedTheme } = useTheme()
  const kinds = useSymbolKinds(resolvedTheme)
  const library = useSymbolLibrary()
  const style = useWorkspace().data?.settings.symbol
  const kindKey = useGenerator((s) => s.kind)
  const isIc = kindKey === IC_KIND
  const kindsCollapsedPref = useSymbolUiPrefs((s) => s.kindsCollapsed)
  const setPrefs = useSymbolUiPrefs((s) => s.set)
  const [rootRef, size] = useElementSize<HTMLDivElement>()

  const kindsCollapsed = isIc
    ? (kindsCollapsedPref.ic ?? (size.width > 0 && size.width < IC_KINDS_OPEN_FROM))
    : kindsCollapsedPref.standard
  const setKindsCollapsed = (collapsed: boolean) =>
    setPrefs({ kindsCollapsed: { ...kindsCollapsedPref, [isIc ? 'ic' : 'standard']: collapsed } })

  const setView = useCallback(
    (next: View) =>
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (next === 'library') p.set('ansicht', 'bibliothek')
          else p.delete('ansicht')
          return p
        },
        { replace: true },
      ),
    [setParams],
  )

  // ?art=<typ>: Symboltyp im Generator wählen – erst prüfen, wenn die Typen geladen sind (danach aus der Adresse entfernen)
  const art = params.get('art')
  const kindList = kinds.data
  const kindsFailed = Boolean(kinds.error)
  useEffect(() => {
    if (!art || (!kindList && !kindsFailed)) return
    const hit = kindList?.find((k) => k.key === art || fold(k.label) === fold(art))
    if (hit) useGenerator.getState().setKind(hit.key)
    else {
      toast.warning(tr('Symboltyp nicht gefunden'), {
        id: 'symbole-art',
        description: tr("„{value0}“ gibt es nicht – der Generator bleibt beim bisherigen Typ. Typen lassen sich links durchsuchen.", { value0: String(art) }),
      })
    }
    setParams(
      (prev) => {
        const p = new URLSearchParams(prev)
        p.delete('art')
        p.delete('ansicht')
        return p
      },
      { replace: true },
    )
  }, [art, kindList, kindsFailed, setParams])

  // Strg+S in der Bibliothek: nichts zu speichern (Hinweis). Im Generator speichert der Befehl „symbols.save“;
  // den Browser-Dialog „Seite speichern unter“ fängt die Shell immer ab.
  const nothingToSave = () => {
    toast.info(tr('Nichts zu speichern'), {
      id: 'symbole-save',
      description: tr('Die Bibliothek ist immer aktuell. Neue und geänderte Symbole speichert der Generator (Strg+S).'),
    })
  }
  useSaveHandler(nothingToSave, { enabled: view === 'library', saveAs: nothingToSave })

  const onEdit = useCallback(
    (result: OpenResult) => {
      setView('generator')
      if (result.note) toast.info(result.noteTitle ?? tr('Im Generator geöffnet'), { id: 'symbole-edit', description: result.note })
    },
    [setView],
  )

  useRegisterCommands([
    {
      id: 'symbols.view.generator',
      title: tr('Symbol-Generator'),
      subtitle: tr('Standardsymbole und IC-Symbole erzeugen'),
      group: 'Navigation',
      icon: Hammer,
      keywords: ['symbole', 'generator', 'erzeugen'],
      run: () => setView('generator'),
    },
    {
      id: 'symbols.view.library',
      title: tr('Symbolbibliothek'),
      subtitle: tr('Gespeicherte Symbole durchsuchen'),
      group: 'Navigation',
      icon: Library,
      keywords: ['symbole', 'bibliothek', 'schlib'],
      run: () => setView('library'),
    },
  ])

  useRegisterSearchProvider({
    id: 'symbol-kinds',
    group: 'Symboltypen',
    minQueryLength: 2,
    search: async (q) => {
      const terms = fold(q).split(/\s+/).filter(Boolean)
      return (kinds.data ?? [])
        .filter((k) => {
          const hay = fold([k.label, tr(k.label), k.key, k.default_name, k.group, tr(k.group)].join(' '))
          return terms.every((t) => hay.includes(t))
        })
        .slice(0, 6)
        .map((k) => ({
          id: `symbol-kind-${k.key}`,
          title: tr(k.label),
          mono: false,
          subtitle: k.default_name,
          meta: k.group,
          icon: Shapes,
          run: ({ navigate }) => navigate(`/symbole?art=${encodeURIComponent(k.key)}`),
        }))
    },
  })

  const libCount = library.data?.length
  const kindLabel = kinds.data?.find((k) => k.key === kindKey)?.label
  let subtitle: string | undefined
  if (view === 'library') {
    if (libCount !== undefined) subtitle = tr("{value0} in der Bibliothek", { value0: String(plural(libCount, tr('Symbol'), tr('Symbole'))) })
    else if (library.error) subtitle = tr('Bibliothek nicht geladen')
    else subtitle = tr('Bibliothek wird geladen …')
  } else if (kindLabel) subtitle = tr("Symboltyp: {value0}", { value0: tr(kindLabel) })

  const styleSummary = style
    ? [
        tr("Raster {value0} mil", { value0: String(style.grid) }),
        tr("Pins {value0}/{value1} mil", { value0: String(style.ic_pin_length), value1: String(style.discrete_pin_length) }),
        style.resistor_style === 'ansi' ? 'ANSI' : 'IEC',
        `Diode 1 = ${style.diode_pin1 === 'anode' ? 'A' : 'K'}`,
      ]
    : null

  return (
    <PageBody width="full" flush>
      <PageTitle title={view === 'library' ? tr('Symbolbibliothek') : tr('Symbol-Generator')} subtitle={subtitle} />
      <div ref={rootRef} className="flex h-[calc(100dvh-3.5rem)] min-h-0 flex-col">
        <Tabs value={view} onValueChange={(v) => setView(v as View)} className="min-h-0 flex-1">
          <div className="flex h-11 shrink-0 items-center gap-2 border-y border-line bg-[color-mix(in_oklab,var(--pf-bg-elev)_75%,transparent)] px-4">
            <span className="flex w-7 justify-center">
              {view === 'generator' && (
                <IconButton
                  size="sm"
                  label={kindsCollapsed ? tr('Symboltypen einblenden') : tr('Symboltypen ausblenden')}
                  icon={kindsCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
                  aria-expanded={!kindsCollapsed}
                  onClick={() => setKindsCollapsed(!kindsCollapsed)}
                />
              )}
            </span>
            <TabsList aria-label={tr("Ansicht")} className="h-11 border-b-0">
              <TabsTrigger value="generator" icon={<Hammer />} className="h-11">
                {tr("Generator")}
              </TabsTrigger>
              <TabsTrigger value="library" icon={<Library />} count={libCount !== undefined ? formatNumber(libCount) : undefined} className="h-11">
                {tr("Bibliothek")}
              </TabsTrigger>
            </TabsList>
            {view === 'generator' && styleSummary && (
              <Tooltip
                content={
                  <span>
                    {tr("Hausstil der Bibliothek: Raster")}{' '}{style?.grid} {tr("mil, Pinlänge IC")}{' '}{style?.ic_pin_length} {tr("mil und diskret")}{' '}
                    {style?.discrete_pin_length} {tr("mil, Widerstand")}{' '}{style?.resistor_style === 'ansi' ? tr('ANSI (Zickzack)') : tr('IEC (Rechteck)')}{tr(". Ändern unter Einstellungen › Hausstil; Diode Pin 1 =")}{' '}{style?.diode_pin1 === 'anode' ? tr('Anode') : tr('Kathode')} {tr("unter Einstellungen › Namensregeln.")}
                  </span>
                }
                side="bottom"
              >
                <Link
                  to="/einstellungen/hausstil?ansicht=symbole"
                  className="ml-auto flex h-7 min-w-0 items-center gap-1.5 rounded-control px-2 text-2xs text-fg-subtle outline-none transition-colors hover:bg-surface-2 hover:text-fg-muted focus-ring"
                >
                  <PenTool aria-hidden className="size-3.5 shrink-0" />
                  <span className="font-medium text-fg-muted">{tr("Hausstil")}</span>
                  <span className="mono hidden truncate @[56rem]:inline">{styleSummary.join(' · ')}</span>
                </Link>
              </Tooltip>
            )}
          </div>
          <TabsContent value="generator" className="min-h-0 flex-1 data-[state=inactive]:hidden">
            <GeneratorView
              kindsCollapsed={kindsCollapsed}
              onKindsCollapsedChange={setKindsCollapsed}
              compact={size.width > 0 && size.width < 1000}
              onShowInLibrary={(name) => {
                useLibraryFilters.getState().showSymbol(name)
                setView('library')
              }}
            />
          </TabsContent>
          <TabsContent value="library" className="min-h-0 flex-1 data-[state=inactive]:hidden">
            <LibraryView onEdit={onEdit} onNewSymbol={() => setView('generator')} />
          </TabsContent>
        </Tabs>
      </div>
    </PageBody>
  )
}
