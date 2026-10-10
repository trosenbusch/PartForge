import { metadataLabel, t, useI18n } from '@/lib/i18n'
/**
 * Detailbereich rechts neben der Tabelle: Kopf (Kategorie, Freigabe als umschaltbare Statusmarke, Teilenummer,
 * Hersteller, Kennwerte, Beschreibung), Aktionen (Datenblatt öffnen bzw. hinzufügen, Duplizieren, Texte neu
 * erzeugen, Löschen), Vorschau (Symbol | Footprint | 3D), Parameter in Gruppen mit Sofort-Speichern und der
 * Änderungsverlauf. Esc (im Bereich) schließt. Gibt es das Bauteil nicht (veralteter Link), erklärt der Bereich das –
 * wurde es **gelöscht**, zeigt er wann und von wem, die Werte beim Löschen und „Wiederherstellen“ (aus der
 * Änderungshistorie, `POST /api/parts/{table}/restore`). So bleibt `/bauteile/<Tabelle>?pn=<Teilenummer>` auch nach dem
 * Ablauf des „Rückgängig“-Toasts der Weg zurück (Übersicht › Letzte Änderungen verlinkt dorthin).
 */
import { useQueryClient } from '@tanstack/react-query'
import {
  ArchiveRestore,
  Check,
  ChevronDown,
  Copy,
  CopyPlus,
  ExternalLink,
  History,
  MoreHorizontal,
  Plus,
  RefreshCw,
  Search,
  SlidersHorizontal,
  Trash2,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import type { CategoryDef } from '@/api/library'
import { invalidateParts, partsApi, partsKeys, PART_NUMBER, usePart, usePartHistory, type PartRow } from '@/api/parts'
import { useWorkspace } from '@/api/system'
import { statusTone } from '@/components/grid/cellFormat'
import {
  Badge,
  Button,
  Callout,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  IconButton,
  Skeleton,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui'
import { CategoryIcon } from '@/components/data/CategoryIcon'
import { cn } from '@/lib/cn'
import { formatRelativeTime } from '@/lib/format'
import { restoreParts } from '../model/actions'
import { DATASHEET, displayValue, RELEASE_TONES, STATUS } from '../model/fields'
import { openDatasheet } from '../model/links'
import { showChangeToast } from '../model/undo'
import { StatusDot } from '../components/StatusDot'
import { STATUS_DOT } from '../model/status'
import { HistoryTimeline } from './HistoryTimeline'
import { PartForm } from './PartForm'
import { PartPreview } from './PartPreview'

export interface PartDetailPanelProps {
  category: CategoryDef
  pn: string
  /** Zeile aus der Tabelle (sofort sichtbar, wird frisch geladen) */
  initialRow: PartRow | null
  onClose: () => void
  onSaved: (row: PartRow, previousPn: string) => void
  onDuplicate: (row: PartRow) => void
  onDelete: (row: PartRow) => void
  /** Feld fokussieren (Doppelklick auf einen Wert in der Tabelle) – neuer `nonce` = erneut */
  focusRequest?: { column: string; nonce: number } | null
}

/** Freigabestufen mit Erklärung (Reihenfolge = Ablauf) */
const RELEASE_STEPS: { value: string; description: string }[] = [
  { value: 'Entwurf', get description() { return t("In Arbeit – noch nicht geprüft") } },
  { value: 'Geprüft', get description() { return t("Werte geprüft, Freigabe steht aus") } },
  { value: 'Freigegeben', get description() { return t("Für neue Designs freigegeben") } },
  { value: 'Gesperrt', get description() { return t("Nicht mehr verwenden") } },
]

/** Höchstens so viele Kennwerte im Kopf */
const KEY_VALUES = 5

function CopyButton({ text, label }: { text: string; label: string }) {
  const { t } = useI18n()
  const [done, setDone] = useState(false)
  return (
    <IconButton
      size="xs"
      label={done ? t("Kopiert") : label}
      icon={done ? <Check className="text-success" /> : <Copy />}
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => {
            setDone(true)
            window.setTimeout(() => setDone(false), 1200)
          })
          .catch(() => toast.error(t("Kopieren nicht möglich")))
      }}
    />
  )
}

export function PartDetailPanel({
  category,
  pn,
  initialRow,
  onClose,
  onSaved,
  onDuplicate,
  onDelete,
  focusRequest: externalFocus = null,
}: PartDetailPanelProps) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const root = useWorkspace().data?.root
  const part = usePart(category.table, pn, initialRow)
  const row = part.data ?? null
  const notFound = !row && part.error instanceof ApiError && part.error.status === 404
  // Verlauf auch für ein gelöschtes Bauteil (zeigt die Löschung und die Werte davor)
  const history = usePartHistory(category.table, pn, !part.isError || notFound)
  const [tab, setTab] = useState('details')
  const [status, setStatus] = useState<{ saving: boolean; savedAt: number | null }>({ saving: false, savedAt: null })
  const [focusRequest, setFocusRequest] = useState<{ column: string; nonce: number } | null>(externalFocus)
  // Fokuswunsch von außen (Doppelklick in der Tabelle) übernehmen – abgeleiteter Zustand statt Effekt
  const [seenFocus, setSeenFocus] = useState(externalFocus?.nonce ?? null)
  if (externalFocus && externalFocus.nonce !== seenFocus) {
    setSeenFocus(externalFocus.nonce)
    setTab('details')
    setFocusRequest(externalFocus)
  }
  const [releaseSaving, setReleaseSaving] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const deletion = notFound && history.data?.[0]?.action === 'delete' ? history.data[0] : null

  // Esc im Panel schließt es (Eingabefelder verwerfen mit Esc zuerst ihre Eingabe und stoppen das Ereignis)
  const asideRef = useRef<HTMLElement>(null)
  const closeRef = useRef(onClose)
  useEffect(() => {
    closeRef.current = onClose
  })
  useEffect(() => {
    const el = asideRef.current
    if (!el) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if ((e.target as HTMLElement).closest('input, textarea, [role="combobox"], [role="menu"]')) return
      e.preventDefault()
      closeRef.current()
    }
    el.addEventListener('keydown', onKey)
    return () => el.removeEventListener('keydown', onKey)
  }, [])

  const handleSaved = (next: PartRow, previousPn: string) => {
    const newPn = String(next[PART_NUMBER] ?? previousPn)
    qc.setQueryData(partsKeys.detail(category.table, newPn), next)
    void qc.invalidateQueries({ queryKey: partsKeys.history(category.table, newPn) })
    onSaved(next, previousPn)
  }

  const regenerate = async () => {
    try {
      const res = await partsApi.regenerateTexts(category.table, [pn])
      invalidateParts(qc, category.table, { counts: false })
      if (res.updated) showChangeToast(qc, category.table, res, t("Texte aus den Vorlagen erzeugt"), t("Wert, Kommentar und Beschreibung"))
      else toast.success(t("Texte entsprechen bereits den Vorlagen"), { description: t("Wert, Kommentar und Beschreibung") })
    } catch (err) {
      toast.error(t("Texte konnten nicht erzeugt werden"), { description: errorMessage(err) })
    }
  }

  const setRelease = async (value: string) => {
    if (!row || row[STATUS] === value) return
    setReleaseSaving(true)
    try {
      const res = await partsApi.update(category.table, pn, { [STATUS]: value })
      handleSaved(res.part, pn)
      toast.success(t("Freigabe: {1}", { 1: metadataLabel(value, t) }), { description: pn, duration: 2200 })
    } catch (err) {
      toast.error(t("Freigabe nicht geändert"), { description: errorMessage(err) })
    } finally {
      setReleaseSaving(false)
    }
  }

  const datasheet = row?.[DATASHEET] ?? ''
  const manufacturer = row?.Manufacturer ?? ''
  const mpn = row?.['Manufacturer Part Number'] ?? ''
  const description = row?.Description ?? ''
  const statusField = category.fields.find((f) => f.column === STATUS)
  const releaseOptions = statusField?.options.length
    ? statusField.options.map((value) => RELEASE_STEPS.find((s) => s.value === value) ?? { value, description: '' })
    : RELEASE_STEPS
  const keyValues = row
    ? category.fields
        .filter((f) => !f.common && row[f.column])
        .slice(0, KEY_VALUES)
        .map((f) => ({ label: metadataLabel(f.label, t), value: displayValue(f, row[f.column]) }))
    : []

  const restore = async () => {
    setRestoring(true)
    try {
      const restored = await restoreParts(qc, category.table, [pn])
      if (restored.length) {
        void part.refetch()
        void history.refetch()
      }
    } finally {
      setRestoring(false)
    }
  }

  if (notFound) {
    return (
      <aside
        ref={asideRef}
        aria-label={t("Bauteil {1}", { 1: pn })}
        data-pf-pane="detail"
        tabIndex={-1}
        className="flex h-full min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card outline-none"
      >
        <header className="flex shrink-0 items-center gap-2 border-b border-line px-4 py-3">
          <Badge variant="outline" className="gap-1.5 pl-1.5">
            <CategoryIcon name={category.icon} color={category.color} className="size-3.5" />
            {metadataLabel(category.label, t)}
          </Badge>
          <IconButton size="sm" label={t("Details schließen")} icon={<X />} onClick={onClose} className="ml-auto" />
        </header>
        {deletion ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
            <EmptyState
              size="sm"
              titleAs="h2"
              icon={<ArchiveRestore />}
              title={t("Bauteil gelöscht")}
              description={
                <>
                  <span className="mono text-fg">„{pn}“</span>  {t("wurde")} {formatRelativeTime(deletion.ts)}
                  {deletion.author ? t(" von {1}", { 1: deletion.author }) : ''}  {t("gelöscht. „Wiederherstellen“ holt es mit allen Werten aus dem Änderungsverlauf zurück.")}
                </>
              }
              actions={
                <>
                  <Button variant="secondary" size="sm" leftIcon={<ArchiveRestore />} loading={restoring} onClick={() => void restore()}>
                    {t("Wiederherstellen")}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={onClose}>
                    {t("Schließen")}
                  </Button>
                </>
              }
            />
            <section className="border-t border-line px-4 pb-20 pt-4">
              <h3 className="micro-label mb-3">{t("Verlauf")}</h3>
              <HistoryTimeline table={category.table} pn={pn} fields={category.fields} />
            </section>
          </div>
        ) : notFound && history.isPending ? (
          // erst den Verlauf abwarten (gelöscht oder nie vorhanden?) – kein Umspringen der Meldung
          <div className="flex min-h-0 flex-1 items-center justify-center">
            <Spinner size={18} label={t("Bauteil wird gesucht …")} />
          </div>
        ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto">
          <EmptyState
            size="sm"
            titleAs="h2"
            illustration="search-empty"
            title={t("Bauteil nicht gefunden")}
            description={
              <>
                <span className="mono text-fg">„{pn}“</span>  {t("gibt es in „")}{metadataLabel(category.label, t)}{t("“ nicht (mehr) – vielleicht wurde es gelöscht, umbenannt oder in eine andere Kategorie verschoben.")}
              </>
            }
            actions={
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  leftIcon={<Search />}
                  onClick={() => navigate(`/bauteile?suche=${encodeURIComponent(pn)}`)}
                >
                  {t("In allen Kategorien suchen")}
                </Button>
                <Button variant="ghost" size="sm" onClick={onClose}>
                  {t("Schließen")}
                </Button>
              </>
            }
          />
        </div>
        )}
      </aside>
    )
  }

  const release = row?.[STATUS] ?? null
  return (
    <aside
      ref={asideRef}
      aria-label={t("Bauteil {1}", { 1: pn })}
      data-pf-pane="detail"
      tabIndex={-1}
      className="flex h-full min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card outline-none"
    >
      {/* Kopf */}
      <header className="shrink-0 border-b border-line px-4 pb-3 pt-3">
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="gap-1.5 pl-1.5">
            <CategoryIcon name={category.icon} color={category.color} className="size-3.5" />
            {metadataLabel(category.label, t)}
          </Badge>
          {row && statusField && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  disabled={releaseSaving}
                  aria-label={t("Freigabe: {1} – ändern", { 1: release ? metadataLabel(release, t) : t('keine') })}
                  className="group/rel inline-flex h-6 items-center gap-1.5 rounded-full border border-line-strong px-2 text-xs font-medium outline-none transition-colors hover:border-line-control hover:bg-surface-2 focus-ring disabled:opacity-60"
                >
                  {releaseSaving ? (
                    <Spinner size={10} />
                  ) : (
                    <span aria-hidden className={cn('size-1.5 rounded-full', STATUS_DOT[statusTone(release ?? '', RELEASE_TONES)])} />
                  )}
                  <span className={cn(release ? 'text-fg' : 'text-fg-subtle')}>{release ? metadataLabel(release, t) : t("Freigabe")}</span>
                  <ChevronDown aria-hidden className="size-3 text-fg-subtle transition-transform group-data-[state=open]/rel:rotate-180" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-64">
                <DropdownMenuLabel>{t("Freigabe")}</DropdownMenuLabel>
                {releaseOptions.map((o) => (
                  <DropdownMenuItem
                    key={metadataLabel(o.value, t)}
                    icon={<span aria-hidden className={cn('size-2 rounded-full', STATUS_DOT[statusTone(o.value, RELEASE_TONES)])} />}
                    description={o.description || undefined}
                    onSelect={() => void setRelease(o.value)}
                    className={cn(o.value === release && 'bg-accent-soft/60')}
                  >
                    {metadataLabel(o.value, t)}
                    {o.value === release && <Check aria-label={t("aktuell")} className="ml-auto size-3.5 text-accent-text" />}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          )}
          {row?.Lifecycle && row.Lifecycle !== 'Aktiv' && <StatusDot value={row.Lifecycle} label={t("Lebenszyklus")} />}
          <span className="ml-auto flex items-center gap-0.5">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" iconOnly aria-label={t("Weitere Aktionen")}>
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem icon={<CopyPlus />} disabled={!row} onSelect={() => row && onDuplicate(row)}>
                  {t("Duplizieren …")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  icon={<RefreshCw />}
                  disabled={!row}
                  description={t("Wert, Kommentar, Beschreibung aus den Vorlagen")}
                  onSelect={() => void regenerate()}
                >
                  {t("Texte neu erzeugen")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem icon={<Trash2 />} destructive disabled={!row} onSelect={() => row && onDelete(row)} hotkey="delete">
                  {t("Löschen …")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <IconButton size="sm" label={t("Details schließen")} icon={<X />} onClick={onClose} />
          </span>
        </div>
        <div className="mt-2.5 flex min-w-0 items-center gap-1.5">
          <h2 className="mono min-w-0 truncate text-md font-semibold tracking-[-0.01em] text-fg" title={pn}>
            {pn}
          </h2>
          <CopyButton text={pn} label={t("Teilenummer kopieren")} />
        </div>
        <p className="mt-0.5 flex min-h-4 min-w-0 items-center gap-1.5 text-xs text-fg-muted">
          {row ? (
            <>
              <span className="truncate font-medium text-fg">{manufacturer || t("Hersteller fehlt")}</span>
              {mpn && mpn !== pn && (
                <>
                  <span aria-hidden className="text-fg-subtle">
                    ·
                  </span>
                  <span className="mono truncate">{mpn}</span>
                </>
              )}
            </>
          ) : part.isError ? null : (
            <Skeleton className="h-3 w-40" />
          )}
        </p>
        {keyValues.length > 0 && (
          <ul aria-label={t("Kennwerte")} className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            {keyValues.map((kv, i) => (
              <li key={kv.label} className="flex items-center gap-2" title={metadataLabel(kv.label, t)}>
                {i > 0 && (
                  <span aria-hidden className="text-fg-subtle">
                    ·
                  </span>
                )}
                <span className="sr-only">{metadataLabel(kv.label, t)}: </span>
                <span className="mono font-medium text-fg">{kv.value}</span>
              </li>
            ))}
          </ul>
        )}
        {description && <p className="mt-1.5 line-clamp-2 text-ui leading-snug text-fg-muted">{description}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {datasheet ? (
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<ExternalLink />}
              onClick={() =>
                void openDatasheet(datasheet, root).then((ok) => {
                  if (!ok) toast.info(t("Datenblatt liegt als Datei vor"), { description: t("{1} – im Desktop-Programm öffnen.", { 1: datasheet }) })
                })
              }
            >
              {t("Datenblatt")}
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              leftIcon={<Plus />}
              disabled={!row}
              onClick={() => {
                setTab('details')
                setFocusRequest({ column: DATASHEET, nonce: Date.now() })
              }}
            >
              {t("Datenblatt hinzufügen")}
            </Button>
          )}
          <Button variant="ghost" size="sm" leftIcon={<CopyPlus />} disabled={!row} onClick={() => row && onDuplicate(row)}>
            {t("Duplizieren")}
          </Button>
          <span className="ml-auto flex items-center gap-1.5 text-2xs text-fg-subtle" aria-live="polite">
            {status.saving ? (
              <>
                <Spinner size={11} tone="accent" />  {t("Speichert …")}
              </>
            ) : status.savedAt ? (
              <>
                <Check aria-hidden className="size-3 text-success" />  {t("Gespeichert ·")} {formatRelativeTime(status.savedAt)}
              </>
            ) : part.isFetching && row ? (
              <>
                <Spinner size={11} />  {t("Aktualisiert …")}
              </>
            ) : null}
          </span>
        </div>
      </header>

      <Tabs value={tab} onValueChange={setTab} className="min-h-0 flex-1">
        <TabsList aria-label={t("Bauteil")} className="shrink-0 px-2">
          <TabsTrigger value="details" icon={<SlidersHorizontal />} className="h-9 text-xs">
            Details
          </TabsTrigger>
          <TabsTrigger
            value="verlauf"
            icon={<History />}
            count={history.data ? history.data.length : undefined}
            className="h-9 text-xs"
          >
            {t("Verlauf")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="details" className="min-h-0 flex-1 overflow-y-auto data-[state=inactive]:hidden">
          {/* unten Platz lassen: das Job-Dock der Shell liegt über der rechten unteren Ecke */}
          <div className="flex flex-col gap-3 px-4 pb-20 pt-3">
            {row ? (
              <>
                <PartPreview row={row} designatorPrefix={category.prefix} />
                <PartForm key={pn} category={category} row={row} onSaved={handleSaved} onStatus={setStatus} focusRequest={focusRequest} />
              </>
            ) : part.isError ? (
              <Callout
                tone="danger"
                title={t("Bauteil konnte nicht geladen werden")}
                actions={
                  <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} onClick={() => void part.refetch()}>
                    {t("Erneut versuchen")}
                  </Button>
                }
              >
                {errorMessage(part.error)}
              </Callout>
            ) : (
              <div className="flex flex-col gap-3" aria-hidden>
                <Skeleton className="h-[272px] rounded-card" />
                {Array.from({ length: 6 }, (_, i) => (
                  <Skeleton key={i} className="h-7" />
                ))}
              </div>
            )}
          </div>
        </TabsContent>
        <TabsContent value="verlauf" className={cn('min-h-0 flex-1 overflow-y-auto px-4 py-4 data-[state=inactive]:hidden')}>
          <HistoryTimeline table={category.table} pn={pn} fields={category.fields} />
        </TabsContent>
      </Tabs>
    </aside>
  )
}
