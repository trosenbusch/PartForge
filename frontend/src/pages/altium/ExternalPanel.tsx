/**
 * Externe Bibliotheken: vorhandene SchLib/PcbLib schreibgeschützt einbinden (Pfadfeld + nativer Dateidialog),
 * Symbole bzw. Footprints mit Vorschau durchsuchen und einzeln „verwenden“ (registrieren) – PartForge schreibt die
 * Dateien nie. „Bauteile“ meint hier wie überall die Datenbank-Bauteile; Inhalte einer Bibliothek heißen Einträge.
 */
import { useInfiniteQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { BookMarked, Check, CircuitBoard, FolderOpen, LibraryBig, Lock, Plus, Search, Shapes, Trash2, X } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import {
  librariesApi,
  librariesKeys,
  useAddExternalLibrary,
  useExternalLibraries,
  useRemoveExternalLibrary,
  useUseExternalComponent,
  type ExternalComponent,
  type ExternalLibrary,
  type PreviewTheme,
} from '@/api/libraries'
import { useTheme } from '@/app/theme'
import { LazyThumbnail } from '@/components/data'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardContent,
  CardHeader,
  confirm,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  EmptyState,
  Field,
  IconButton,
  Input,
  PathInput,
  PathText,
  Skeleton,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatNumber, plural } from '@/lib/format'
import { revealPath, useNativeBridge } from '@/lib/native'

const PAGE = 60

export function ExternalPanel() {
  const bridge = useNativeBridge()
  const libs = useExternalLibraries()
  const add = useAddExternalLibrary()
  const remove = useRemoveExternalLibrary()
  const [path, setPath] = useState('')
  /** Prüfung erst nach Verlassen des Felds oder beim Absenden – nicht schon beim Tippen */
  const [touched, setTouched] = useState(false)
  const [browsing, setBrowsing] = useState<ExternalLibrary | null>(null)
  const trimmed = path.trim().replace(/^"|"$/g, '')
  const typeHint = trimmed && !/\.(schlib|pcblib)$/i.test(trimmed) ? 'Bitte eine .SchLib- oder .PcbLib-Datei wählen.' : null

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (!trimmed || typeHint) return
    add.mutate(trimmed, {
      onSuccess: (lib) => {
        toast.success(`„${lib.name}“ eingebunden`, { description: 'Schreibgeschützt – PartForge liest die Bauteile, ändert die Datei aber nie.' })
        setPath('')
        setTouched(false)
        add.reset()
        setBrowsing(lib)
      },
    })
  }

  const onRemove = async (lib: ExternalLibrary) => {
    const ok = await confirm({
      title: `„${lib.name}“ entfernen?`,
      description:
        lib.registered > 0
          ? `Die Bibliothek wird nicht mehr angeboten. ${plural(lib.registered, 'übernommener Eintrag bleibt', 'übernommene Einträge bleiben')} nutzbar – die Datei selbst bleibt unverändert.`
          : 'Die Bibliothek wird nicht mehr angeboten. Die Datei selbst bleibt unverändert.',
      confirmLabel: 'Entfernen',
      destructive: true,
    })
    if (!ok) return
    remove.mutate(lib.id, { onSuccess: () => toast.success(`„${lib.name}“ entfernt`) })
  }

  const list = libs.data ?? []
  return (
    <div className="grid grid-cols-1 gap-4 @[68rem]:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Einbinden */}
      <Card className="self-start">
        <CardHeader
          icon={<LibraryBig />}
          title="Bibliothek einbinden"
          titleAs="h3"
          description="Vorhandene Firmen- oder Hersteller-Bibliotheken nutzen, ohne sie zu kopieren."
        />
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Field
              label="SchLib- oder PcbLib-Datei"
              error={(touched ? typeHint : null) ?? (add.error ? errorMessage(add.error) : undefined)}
              help="Absoluter Pfad, z. B. auf einem Netzlaufwerk. Die Datei bleibt, wo sie ist."
            >
              {/* Verlassen des Felds (auch zum „Durchsuchen …“) zeigt eine falsche Endung an, Tippen noch nicht */}
              <div onBlur={() => setTouched(Boolean(trimmed))}>
                <PathInput
                  value={path}
                  onValueChange={(v) => {
                    setPath(v)
                    if (add.error) add.reset()
                    if (!v.trim()) setTouched(false)
                  }}
                  browse="file"
                  fileFilters={['Altium-Bibliotheken (*.SchLib;*.PcbLib)', 'Alle Dateien (*.*)']}
                  placeholder="C:\Bibliotheken\Firma_Passiv.SchLib"
                />
              </div>
            </Field>
            <div className="flex items-center justify-between gap-3">
              <p className="flex items-center gap-1.5 text-xs text-fg-subtle">
                <Lock aria-hidden className="size-3.5 shrink-0" />
                Schreibgeschützt eingebunden
              </p>
              <Button type="submit" variant="secondary" leftIcon={<Plus />} loading={add.isPending} disabled={!trimmed}>
                Einbinden
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* Eingebundene Bibliotheken */}
      <Card className="self-start">
        <CardHeader
          icon={<BookMarked />}
          title="Eingebundene Bibliotheken"
          titleAs="h3"
          description={
            libs.data
              ? list.length
                ? `${plural(list.length, 'Bibliothek', 'Bibliotheken')} · Symbole und Footprints per „Verwenden“ übernehmen`
                : 'Noch keine'
              : 'Wird geladen …'
          }
        />
        {libs.isPending ? (
          <CardContent className="flex flex-col gap-3">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </CardContent>
        ) : libs.isError ? (
          <CardContent>
            <Callout tone="danger" title="Liste nicht verfügbar">
              {errorMessage(libs.error)}
            </Callout>
          </CardContent>
        ) : list.length === 0 ? (
          <EmptyState
            size="sm"
            icon={<LibraryBig />}
            title="Keine externen Bibliotheken"
            titleAs="h4"
            description="Eingebundene Bibliotheken erscheinen hier – ihre Symbole und Footprints lassen sich ansehen und für eigene Bauteile verwenden."
          />
        ) : (
          <ul className="divide-y divide-line border-t border-line">
            {list.map((lib, i) => (
              <motion.li
                key={lib.id}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, delay: Math.min(i, 20) * 0.02 }}
                className="flex items-center gap-3 px-4 py-3"
              >
                <span
                  aria-hidden
                  className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted [&_svg]:size-4"
                >
                  {lib.kind === 'schlib' ? <Shapes /> : <CircuitBoard />}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                    <span className="truncate text-ui font-medium text-fg">{lib.name}</span>
                    {!lib.exists && (
                      <Badge variant="danger" dot>
                        Datei fehlt
                      </Badge>
                    )}
                    {lib.registered > 0 && <Badge variant="neutral">{formatNumber(lib.registered)} verwendet</Badge>}
                  </div>
                  <div className="mt-0.5 flex min-w-0 items-center gap-2 text-2xs text-fg-subtle">
                    <PathText path={lib.path} className="min-w-0 truncate" />
                  </div>
                  <div className="text-2xs text-fg-subtle">
                    {lib.kind === 'schlib' ? 'Symbole' : 'Footprints'} · eingebunden {formatDateTime(lib.added)}
                  </div>
                </div>
                <Button size="sm" variant="secondary" leftIcon={<Search />} disabled={!lib.exists} onClick={() => setBrowsing(lib)}>
                  {lib.kind === 'schlib' ? 'Symbole ansehen' : 'Footprints ansehen'}
                </Button>
                {/* Desktop: Explorer mit markierter Datei; Browser: Pfad kopieren (revealPath meldet es) */}
                <IconButton
                  size="sm"
                  label={bridge.canRevealPath || bridge.canOpenPath ? `${lib.name} im Explorer zeigen` : `Pfad von ${lib.name} kopieren`}
                  icon={<FolderOpen />}
                  disabled={!lib.exists}
                  onClick={() => void revealPath(lib.path, { what: 'Bibliotheksdatei' })}
                />
                <IconButton size="sm" label={`${lib.name} entfernen`} icon={<Trash2 />} onClick={() => void onRemove(lib)} />
              </motion.li>
            ))}
          </ul>
        )}
      </Card>

      <ComponentBrowser library={browsing} onClose={() => setBrowsing(null)} />
    </div>
  )
}

// --------------------------------------------------------------------------- Bauteil-Browser

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

function ComponentBrowser({ library, onClose }: { library: ExternalLibrary | null; onClose: () => void }) {
  const open = Boolean(library)
  const [shown, setShown] = useState<ExternalLibrary | null>(library)
  const [search, setSearch] = useState('')
  if (library && library !== shown) {
    setShown(library)
    setSearch('')
  }
  const lib = library ?? shown
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        size="xl"
        className="h-[min(760px,calc(100dvh-11vh-1.5rem))]"
        onEscapeKeyDown={(e) => {
          // Esc leert zuerst die Suche – erst ein zweites Esc schließt den Dialog
          if (search) {
            e.preventDefault()
            setSearch('')
          }
        }}
      >
        {lib && <BrowserBody library={lib} onClose={onClose} search={search} onSearch={setSearch} />}
      </DialogContent>
    </Dialog>
  )
}

function BrowserBody({
  library,
  onClose,
  search,
  onSearch: setSearch,
}: {
  library: ExternalLibrary
  onClose: () => void
  search: string
  onSearch: (value: string) => void
}) {
  const { resolvedTheme } = useTheme()
  const theme: PreviewTheme = library.kind === 'pcblib' ? 'dark' : resolvedTheme
  const unit = library.kind === 'schlib' ? (['Symbol', 'Symbole'] as const) : (['Footprint', 'Footprints'] as const)
  const q = useDebounced(search.trim(), 250)
  const use = useUseExternalComponent()
  const [usingName, setUsingName] = useState<string | null>(null)
  const [used, setUsed] = useState<Set<string>>(() => new Set())

  const query = useInfiniteQuery({
    queryKey: librariesKeys.externalComponents(library.id, q, theme),
    queryFn: ({ pageParam, signal }) =>
      librariesApi.externalComponents(library.id, { search: q, offset: pageParam, limit: PAGE, theme, previews: true }, signal),
    initialPageParam: 0,
    getNextPageParam: (last) => (last.offset + last.components.length < last.total ? last.offset + last.components.length : undefined),
    staleTime: 60_000,
    retry: false,
  })
  const items = query.data?.pages.flatMap((p) => p.components) ?? []
  const total = query.data?.pages[0]?.total

  const onUse = (c: ExternalComponent) => {
    setUsingName(c.name)
    use.mutate(
      { id: library.id, name: c.name },
      {
        onSuccess: () => {
          setUsed((s) => new Set(s).add(c.name.toLowerCase()))
          toast.success(`„${c.name}“ steht zur Verfügung`, {
            description:
              c.kind === 'symbol'
                ? `Bauteile verwenden es mit Symbol (Library Ref) = ${c.name}.`
                : `Bauteile verwenden ihn mit Footprint (Footprint Ref) = ${c.name}.`,
          })
        },
        onSettled: () => setUsingName(null),
      },
    )
  }

  return (
    <>
      <DialogHeader
        icon={library.kind === 'schlib' ? <Shapes /> : <CircuitBoard />}
        title={library.name}
        description={
          <span className="flex min-w-0 flex-col gap-0.5">
            <PathText path={library.path} className="text-xs" />
            <span className="text-xs text-fg-subtle">
              {library.kind === 'schlib' ? 'Symbolbibliothek' : 'Footprint-Bibliothek'} · schreibgeschützt eingebunden
            </span>
          </span>
        }
      />
      <div className="flex shrink-0 items-center gap-3 px-6 pb-3">
        <Input
          size="sm"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Name oder Beschreibung …"
          aria-label={`${unit[1]} durchsuchen`}
          prefix={<Search />}
          suffix={search ? <IconButton size="xs" label="Suche leeren" icon={<X />} onClick={() => setSearch('')} tooltip={false} /> : undefined}
          containerClassName="w-80 max-w-full"
        />
        <span className="text-xs text-fg-subtle" aria-live="polite">
          {total === undefined ? 'Wird gelesen …' : q ? `${plural(total, 'Treffer', 'Treffer')}` : plural(total, unit[0], unit[1])}
        </span>
      </div>
      <DialogBody className="border-t border-line pt-4">
        {query.isPending ? (
          <Grid>
            {Array.from({ length: 10 }, (_, i) => (
              <Skeleton key={i} className="h-[200px] rounded-card" />
            ))}
          </Grid>
        ) : query.isError ? (
          <Callout tone="danger" title="Bibliothek nicht lesbar">
            {errorMessage(query.error)}
          </Callout>
        ) : items.length === 0 ? (
          <EmptyState
            size="sm"
            illustration="search-empty"
            title={q ? 'Keine Treffer' : 'Die Bibliothek ist leer'}
            description={q ? `Kein Eintrag passt zu „${q}“.` : `Diese Datei enthält keine ${unit[1]}.`}
          />
        ) : (
          <>
            <Grid>
              {items.map((c) => (
                <ComponentCard
                  key={c.name}
                  component={c}
                  board={library.kind === 'pcblib'}
                  theme={theme}
                  libraryId={library.id}
                  used={c.registered && !c.conflict ? true : used.has(c.name.toLowerCase())}
                  busy={usingName === c.name}
                  onUse={() => onUse(c)}
                />
              ))}
            </Grid>
            {query.hasNextPage && (
              <div className="mt-4 flex justify-center">
                <Button size="sm" variant="secondary" loading={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
                  Weitere laden
                </Button>
              </div>
            )}
          </>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onClose}>
          Schließen
        </Button>
      </DialogFooter>
    </>
  )
}

function Grid({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-[repeat(auto-fill,minmax(10.5rem,1fr))] gap-3">{children}</div>
}

function ComponentCard({
  component: c,
  board,
  theme,
  libraryId,
  used,
  busy,
  onUse,
}: {
  component: ExternalComponent
  board: boolean
  theme: PreviewTheme
  libraryId: string
  used: boolean
  busy: boolean
  onUse: () => void
}) {
  const meta = [
    c.kind === 'symbol' ? (c.pin_count ? plural(c.pin_count, 'Pin', 'Pins') : null) : c.pin_count ? plural(c.pin_count, 'Pad', 'Pads') : null,
    c.part_count && c.part_count > 1 ? `${formatNumber(c.part_count)} Teile` : null,
    c.has_3d ? '3D' : null,
  ].filter(Boolean)
  return (
    <div className="group/card flex h-[200px] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card transition-[border-color,box-shadow] hover:border-line-strong hover:shadow-raised">
      <div className={cn('relative min-h-0 flex-1 overflow-hidden border-b', board ? 'border-white/5 bg-canvas' : 'dot-grid border-line bg-bg')}>
        {c.svg ? (
          <LazyThumbnail
            queryKey={['libraries', 'external-thumb', libraryId, c.name, theme]}
            loadSvg={() => Promise.resolve(c.svg ?? '')}
            alt={`Vorschau ${c.name}`}
          />
        ) : (
          <div className="flex size-full items-center justify-center text-2xs text-fg-subtle">keine Vorschau</div>
        )}
        {c.conflict && (
          <div aria-hidden className="absolute right-2 top-2">
            <Badge variant="warning">Name vergeben</Badge>
          </div>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-1 px-3 pb-2.5 pt-2">
        <div className="mono truncate text-xs font-semibold text-fg" title={c.name}>
          {c.name}
        </div>
        <div className="flex min-h-6 items-center gap-2">
          <div className="min-w-0 flex-1 truncate text-2xs text-fg-subtle" title={c.description ?? undefined}>
            {meta.join(' · ') || c.description || (c.kind === 'symbol' ? 'Symbol' : 'Footprint')}
          </div>
          {used ? (
            <span className="flex shrink-0 items-center gap-1 text-2xs font-medium text-success-text">
              <Check aria-hidden className="size-3.5" />
              Verwendet
            </span>
          ) : c.conflict ? (
            // Grund im Text statt im Tooltip: Altium unterscheidet Symbole/Footprints nur über den Namen
            <span className="shrink-0 text-right text-2xs leading-tight text-warning-text">
              {c.registered_source === 'external' ? 'in anderer Bibliothek' : 'schon registriert'}
              <span className="sr-only">: Der Name ist bereits vergeben – Altium unterscheidet nur über den Namen.</span>
            </span>
          ) : (
            <Button size="xs" variant="secondary" loading={busy} onClick={onUse} aria-label={`${c.name} verwenden`}>
              Verwenden
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}
