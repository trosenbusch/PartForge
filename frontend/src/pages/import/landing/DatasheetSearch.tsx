import { useMutation } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowRight, CircleAlert, CircleStop, ExternalLink, FileCheck2, FileScan, Globe, Search, Settings2, Sparkles, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router'
import { ApiError, cleanErrorText, errorMessage } from '@/api/client'
import {
  datasheetsApi,
  type AiStatus,
  type DatasheetSummary,
  type FindCandidate,
  type FindJobDetail,
  type FindResult,
} from '@/api/datasheets'
import { jobDetail, trackJob, useInlineJob, useJob } from '@/api/jobs'
import { useCancelJob, type Job } from '@/api/system'
import { Badge, Button, Callout, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes, formatNumbersInText, plural } from '@/lib/format'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { cleanJobError } from '../lib/analysis'
import { formatUsd, hostOf, runLabel } from '../lib/format'
import { AI_PROBLEM_TITLE, AI_SETTINGS_CODES, aiUnavailable, importPath } from '../lib/useImportActions'
import { useActiveImports } from '../store'

/** Höchstbetrag einer Suche (Backend: `min(max_cost_per_import_usd, find.FIND_MAX_COST_USD)`) */
const FIND_MAX_COST_USD = 0.5

const SOURCE_LABEL: Record<FindCandidate['source'], string> = {
  hersteller: 'Hersteller',
  distributor: 'Distributor',
  andere: 'Andere Quelle',
}

/** Ist der Link schon als Datenblatt in der Bibliothek (gleiche Hersteller-Adresse)? */
function knownDatasheet(c: FindCandidate, known: readonly DatasheetSummary[]): DatasheetSummary | null {
  const urls = new Set([c.url, c.final_url].filter((u): u is string => Boolean(u)).map((u) => u.replace(/\/+$/, '').toLowerCase()))
  return known.find((d) => d.source_url && urls.has(d.source_url.replace(/\/+$/, '').toLowerCase())) ?? null
}

export interface DatasheetSearchProps {
  aiReady: boolean
  aiStatus: AiStatus | undefined
  aiLoading: boolean
  /** Neuer Wert → Suchfeld fokussieren (Befehl „Datenblatt suchen …“, `/import?suche=…`) */
  focusKey?: string | null
  /** Vorbelegung des Suchfelds (`/import?suche=OPA656`) – startet nichts */
  initialQuery?: string | null
  /** Datenblätter der Bibliothek (gefundene Links, die schon da sind, öffnen statt laden) */
  known: readonly DatasheetSummary[]
  /** URL-Import eines Kandidaten starten (`searchJobId` rechnet die Suchkosten dem Datenblatt zu) */
  onImport: (url: string, searchJobId: string) => Promise<boolean>
  /** Ein Download wird gerade gestartet */
  importing: boolean
}

/**
 * „Datenblatt suchen“: Teilenummer (optional Hersteller) → Claude sucht das offizielle PDF im Web (Job
 * `datasheet-find`, höchstens 3 Suchen; braucht keine Bibliothek) → geprüfte Kandidaten (PDF ja/nein, Größe, Quelle)
 * → „Laden und analysieren“ startet den URL-Import des Links. Die letzte Suche bleibt für die Sitzung stehen.
 * Ohne KI (aus, kein Schlüssel) neutral und gesperrt – mit dem Weg zu Einstellungen › Allgemein › KI-Funktionen.
 */
export function DatasheetSearch({ aiReady, aiStatus, aiLoading, focusKey, initialQuery, known, onImport, importing }: DatasheetSearchProps) {
  const uid = useId()
  const entry = useActiveImports((s) => s.search)
  const setSearch = useActiveImports((s) => s.setSearch)
  const [query, setQuery] = useState(() => initialQuery ?? entry?.query ?? '')
  const [maker, setMaker] = useState(() => (initialQuery ? '' : (entry?.manufacturer ?? '')))
  const [inputError, setInputError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const disabled = !aiReady

  useEffect(() => {
    if (focusKey && !disabled) inputRef.current?.focus()
  }, [focusKey, disabled])

  const start = useMutation({
    mutationFn: (input: { query: string; manufacturer: string | null }) => datasheetsApi.find(input),
    meta: { silentError: true }, // der Fehler steht an der Suche
    onSuccess: ({ job }, input) => {
      // die Suche zeigt Fortschritt und Ergebnis selbst – nicht in der Pille, kein Toast (verlässt man die Seite: Dock)
      trackJob(job, { dock: false, toast: false })
      setSearch({ jobId: job.id, query: input.query, manufacturer: input.manufacturer, startedAt: Date.now() })
    },
  })

  const { job, isActive, error: jobError } = useJob<FindResult>(entry?.jobId)
  useInlineJob(entry?.jobId)
  // nach einem Neustart gibt es den Job nicht mehr – die alte Suche still verwerfen
  useEffect(() => {
    if (entry && jobError instanceof ApiError && jobError.isNotFound) setSearch(null)
  }, [entry, jobError, setSearch])

  const cancel = useCancelJob()
  const running = start.isPending || isActive

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (disabled || running) return
    const q = query.trim()
    if (!q) {
      setInputError('Bitte eine Teilenummer eingeben, z. B. OPA656.')
      inputRef.current?.focus()
      return
    }
    setInputError(null)
    start.mutate({ query: q, manufacturer: maker.trim() || null })
  }

  const startError = start.error ? (aiUnavailable(start.error) ?? { code: null, message: cleanErrorText(errorMessage(start.error)) }) : null
  const limit = Math.min(aiStatus?.max_cost_per_import_usd ?? FIND_MAX_COST_USD, FIND_MAX_COST_USD)

  return (
    // Landmarke ist das Suchformular (role="search") – kein zusätzlicher Bereich mit demselben Namen
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={`${uid}-q`} className="text-xs font-medium text-fg-muted">
          Datenblatt suchen
        </label>
        {!disabled && (
          <span className="flex items-center gap-1 text-2xs text-fg-subtle">
            <Sparkles aria-hidden className="size-3 text-spark-a" />
            Claude sucht im Web
          </span>
        )}
      </div>
      <form role="search" aria-label="Datenblatt im Web suchen" onSubmit={submit} noValidate>
        <div
          className={cn(
            'group/search flex h-11 items-center gap-2 rounded-button pl-3 pr-1.5 transition-[box-shadow,background-color] duration-150',
            disabled
              ? 'border border-line-control bg-control opacity-75'
              : cn(
                  'spark-border-static [--spark-fill:var(--pf-control-bg)] shadow-[var(--pf-shadow-spark)]',
                  'has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-accent',
                  'has-[input:focus-visible]:[--spark-fill:var(--pf-control-bg-focus)]',
                ),
            inputError && 'outline-2 outline-offset-2 outline-danger',
          )}
        >
          <Search aria-hidden className={cn('size-4 shrink-0', disabled ? 'text-fg-subtle' : 'text-spark-a')} />
          <input
            ref={inputRef}
            id={`${uid}-q`}
            type="search"
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            placeholder="Teilenummer eingeben, z. B. OPA656"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              if (inputError) setInputError(null)
            }}
            aria-invalid={inputError ? true : undefined}
            aria-describedby={`${uid}-hint`}
            className="mono h-full min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:font-sans placeholder:tracking-normal placeholder:text-fg-subtle disabled:cursor-not-allowed [&::-webkit-search-cancel-button]:hidden"
          />
          <span aria-hidden className="hidden h-5 w-px shrink-0 bg-line-strong @[30rem]:block" />
          <input
            type="text"
            autoComplete="off"
            spellCheck={false}
            disabled={disabled}
            aria-label="Hersteller (optional)"
            title="Hersteller (optional) – hilft bei mehrdeutigen Teilenummern"
            placeholder="Hersteller"
            value={maker}
            onChange={(e) => setMaker(e.target.value)}
            className="hidden h-full w-24 min-w-0 bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle disabled:cursor-not-allowed @[30rem]:block @[40rem]:w-36"
          />
          <Button
            type="submit"
            size="sm"
            variant={disabled ? 'secondary' : 'spark'}
            leftIcon={<Sparkles />}
            loading={running}
            disabled={disabled}
            className="h-8"
          >
            Suchen
          </Button>
        </div>
      </form>
      <p id={`${uid}-hint`} className={cn('text-xs', inputError ? 'text-danger-text' : 'text-fg-subtle')} aria-live="polite">
        {inputError ??
          (disabled ? (
            aiLoading ? (
              'KI-Status wird geprüft …'
            ) : (
              <>
                {aiStatus?.enabled === false
                  ? 'Die Suche nutzt Claude – die KI ist ausgeschaltet:'
                  : 'Die Suche nutzt Claude – es fehlt ein API-Schlüssel:'}{' '}
                <Link
                  to={SETTINGS_PLACE.ai.to}
                  className="font-medium text-accent-text underline-offset-4 outline-none hover:underline focus-ring"
                >
                  {SETTINGS_PLACE.ai.label}
                </Link>
              </>
            )
          ) : (
            `Claude findet das offizielle PDF, PartForge prüft jeden Link · höchstens ${formatUsd(limit)} je Suche`
          ))}
      </p>

      {startError && (
        <Callout
          tone={startError.code && startError.code !== 'unknown' ? 'warning' : 'danger'}
          title={startError.code ? AI_PROBLEM_TITLE[startError.code] : 'Die Suche konnte nicht starten'}
          actions={
            startError.code && AI_SETTINGS_CODES.has(startError.code) ? (
              <Button asChild size="xs" variant="secondary">
                <Link to={SETTINGS_PLACE.ai.to}>
                  <Settings2 aria-hidden />
                  KI einrichten
                </Link>
              </Button>
            ) : undefined
          }
          className="mt-1"
        >
          {cleanErrorText(startError.message)}
        </Callout>
      )}

      <AnimatePresence initial={false}>
        {entry && job && (
          <SearchResults
            key={entry.jobId}
            jobId={entry.jobId}
            query={entry.query}
            job={job}
            running={isActive}
            known={known}
            importing={importing}
            onImport={onImport}
            onCancel={() => cancel.mutate(entry.jobId)}
            cancelling={cancel.isPending || Boolean(job.cancel_requested)}
            onClose={() => setSearch(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

function SearchResults({
  jobId,
  query,
  job,
  running,
  known,
  importing,
  onImport,
  onCancel,
  cancelling,
  onClose,
}: {
  jobId: string
  query: string
  job: Job<FindResult>
  running: boolean
  known: readonly DatasheetSummary[]
  importing: boolean
  onImport: (url: string, searchJobId: string) => Promise<boolean>
  onCancel: () => void
  cancelling: boolean
  onClose: () => void
}) {
  const reduce = useReducedMotion()
  const detail = jobDetail<FindJobDetail>(job)
  const result = job.status === 'done' ? job.result : null
  const candidates = result?.candidates ?? []
  const pdfs = candidates.filter((c) => c.is_pdf)
  const recommended = pdfs[0]?.url ?? null
  const [loadingUrl, setLoadingUrl] = useState<string | null>(null)
  const queries = detail.queries ?? result?.searches ?? []
  const cost = result?.cost_usd ?? detail.cost_usd ?? 0
  const checking = running && detail.step === 'check'

  const load = async (url: string) => {
    setLoadingUrl(url)
    const ok = await onImport(url, jobId)
    if (!ok) setLoadingUrl(null)
  }

  const status =
    job.status === 'failed'
      ? 'Die Suche ist fehlgeschlagen'
      : job.status === 'cancelled'
        ? 'Suche abgebrochen'
        : running
          ? checking
            ? `${plural(detail.candidates ?? 0, 'Link wird', 'Links werden')} geprüft …`
            : queries.length
              ? `Claude sucht: „${queries[queries.length - 1]}“ …`
              : 'Claude sucht das Datenblatt …'
          : candidates.length
            ? `${plural(candidates.length, 'Treffer', 'Treffer')} für „${query}“ · ${plural(pdfs.length, 'PDF', 'PDFs')}`
            : `Kein Datenblatt gefunden für „${query}“`

  return (
    <motion.div
      initial={reduce ? false : { opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduce ? { opacity: 0 } : { opacity: 0, y: -4 }}
      transition={{ duration: 0.18 }}
      role="region"
      aria-label={`Suchergebnisse für „${query}“`}
      aria-busy={running || undefined}
      className={cn(
        'mt-1.5 overflow-hidden rounded-card shadow-card',
        running ? 'spark-border [--spark-fill:var(--pf-surface)]' : 'border border-line bg-surface',
      )}
    >
      <div className="flex min-h-11 items-center gap-2.5 border-b border-line px-3.5 py-2">
        <span
          aria-hidden
          className={cn(
            'flex size-6 shrink-0 items-center justify-center rounded-md [&_svg]:size-3.5',
            job.status === 'failed'
              ? 'bg-danger/12 text-danger-text'
              : running
                ? 'bg-[color-mix(in_oklab,var(--pf-spark-b)_14%,transparent)] text-spark-text'
                : 'bg-surface-2 text-fg-muted',
          )}
        >
          {running ? <Spinner size={13} tone="spark" /> : job.status === 'failed' ? <CircleAlert /> : <Search />}
        </span>
        <div className="min-w-0 flex-1" aria-live="polite">
          <div className="truncate text-ui font-medium text-fg">{status}</div>
          <div className="truncate text-2xs text-fg-subtle">
            {[
              queries.length ? plural(queries.length, 'Websuche', 'Websuchen') : null,
              cost > 0 || !running ? formatUsd(cost) : null,
              runLabel(detail.model_label || result?.model_label) || null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </div>
        </div>
        {running ? (
          <Button size="xs" variant="ghost" leftIcon={<CircleStop />} loading={cancelling} onClick={onCancel}>
            {cancelling ? 'Wird abgebrochen …' : 'Abbrechen'}
          </Button>
        ) : (
          <Button size="xs" variant="ghost" iconOnly aria-label="Suchergebnisse schließen" onClick={onClose}>
            <X />
          </Button>
        )}
      </div>

      {job.status === 'failed' && (
        <p className="px-3.5 py-3 text-xs leading-relaxed text-danger-text" role="alert">
          {cleanErrorText(cleanJobError(job.error || job.message)) || 'Unbekannter Fehler.'}
        </p>
      )}

      {running && queries.length > 0 && (
        <ul aria-label="Suchanfragen von Claude" className="flex flex-col gap-1 px-3.5 py-2.5">
          {queries.map((q, i) => (
            <li key={`${q}-${i}`} className="flex items-center gap-2 text-xs text-fg-muted">
              <Globe aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
              <span className="mono min-w-0 truncate">{q}</span>
            </li>
          ))}
        </ul>
      )}

      {result && (
        <>
          {result.note && (
            <p className="flex items-start gap-2 border-b border-line bg-[linear-gradient(135deg,color-mix(in_oklab,var(--pf-spark-a)_5%,transparent),color-mix(in_oklab,var(--pf-spark-b)_7%,transparent))] px-3.5 py-2 text-xs leading-relaxed text-fg-muted">
              <Sparkles aria-hidden className="mt-0.5 size-3.5 shrink-0 text-spark-a" />
              <span>
                <span className="sr-only">Anmerkung von Claude: </span>
                {result.note}
              </span>
            </p>
          )}
          {candidates.length > 0 ? (
            <ul aria-label="Gefundene Datenblätter" className="divide-y divide-line">
              {candidates.map((c) => (
                <CandidateRow
                  key={c.url}
                  candidate={c}
                  recommended={c.url === recommended}
                  existing={knownDatasheet(c, known)}
                  loading={loadingUrl === c.url}
                  disabled={importing || (loadingUrl !== null && loadingUrl !== c.url)}
                  onLoad={() => void load(c.url)}
                />
              ))}
            </ul>
          ) : (
            <p className="px-3.5 py-3 text-xs leading-relaxed text-fg-muted">
              Claude hat kein passendes Datenblatt gefunden. Genauer suchen (mit Hersteller) – oder das PDF selbst ablegen bzw. seine
              Adresse unten eingeben.
            </p>
          )}
          {candidates.length > 0 && (
            <p className="border-t border-line px-3.5 py-2 text-2xs leading-4 text-fg-subtle">
              {formatNumbersInText(
                `Die Kosten der Suche (${formatUsd(result.cost_usd)}) werden dem Datenblatt zugerechnet, das Sie von hier laden.`,
              )}
            </p>
          )}
        </>
      )}
    </motion.div>
  )
}

function CandidateRow({
  candidate: c,
  recommended,
  existing,
  loading,
  disabled,
  onLoad,
}: {
  candidate: FindCandidate
  recommended: boolean
  existing: DatasheetSummary | null
  loading: boolean
  disabled: boolean
  onLoad: () => void
}) {
  const host = hostOf(c.final_url ?? c.url)
  const meta = [c.manufacturer || null, host, c.note || null].filter(Boolean) as string[]
  return (
    <li className="grid grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-3 px-3.5 py-2.5">
      <span
        aria-hidden
        className={cn(
          'flex size-7 items-center justify-center rounded-md border [&_svg]:size-3.5',
          c.is_pdf ? 'border-line-strong bg-surface-2 text-fg-muted' : 'border-dashed border-line-strong text-fg-subtle',
        )}
      >
        {c.is_pdf ? <FileCheck2 /> : <Globe />}
      </span>
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <span className="line-clamp-1 min-w-0 text-ui font-medium text-fg" title={c.title || c.url}>
            {c.title || c.url}
          </span>
          {c.source === 'hersteller' ? (
            <Badge variant="success" size="sm">
              Hersteller
            </Badge>
          ) : (
            <Badge variant="outline" size="sm">
              {SOURCE_LABEL[c.source]}
            </Badge>
          )}
          {c.is_pdf ? (
            <Badge variant="neutral" size="sm">
              PDF{c.size_bytes ? ` · ${formatBytes(c.size_bytes)}` : ''}
            </Badge>
          ) : (
            <Badge variant="warning" size="sm">
              {c.check || 'kein PDF'}
            </Badge>
          )}
          {recommended && !existing && (
            <Badge variant="spark" size="sm">
              <Sparkles />
              Empfohlen
            </Badge>
          )}
        </div>
        <div className="mt-0.5 line-clamp-1 text-2xs leading-4 text-fg-subtle" title={meta.join(' · ')}>
          {meta.join(' · ')}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {existing ? (
          <Button asChild size="sm" variant="secondary">
            <Link to={importPath(existing.id)} aria-label={`In der Bibliothek: „${c.title || host}“ öffnen`}>
              In der Bibliothek
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        ) : c.is_pdf ? (
          <Button
            size="sm"
            variant={recommended ? 'spark' : 'secondary'}
            leftIcon={<FileScan />}
            loading={loading}
            disabled={disabled}
            onClick={onLoad}
            aria-label={`Laden und analysieren: ${c.title || host}`}
          >
            Laden und analysieren
          </Button>
        ) : (
          <Button asChild size="sm" variant="ghost">
            <a href={c.url} target="_blank" rel="noopener noreferrer" aria-label={`Öffnen im Browser: ${c.title || host}`}>
              Öffnen
              <ExternalLink aria-hidden />
            </a>
          </Button>
        )}
      </div>
    </li>
  )
}
