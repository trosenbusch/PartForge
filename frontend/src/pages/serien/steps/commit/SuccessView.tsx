import { localizeMessage, t as tr, useI18n } from '@/lib/i18n'
/**
 * Ergebnis nach dem Erzeugen – volle Breite wie die anderen Schritte, gleiche Gliederung wie der Fortschritt davor:
 * links schließt sich der Ring (Forge-Verlauf des UI-Kits) mit einem Funkenstoß (ohne Konfetti), daneben Überschrift
 * und die nächsten Schritte („In Tabelle anzeigen“, „Neue Serie“); bei ungeprüften Vorlagen der Prüfhinweis. Darunter
 * zählen die Zahlen hoch – neu, aktualisiert, übersprungen, ausgelassen (Konflikte/ungültig), Fehler, neue
 * Footprints –, dann die Details (Symbol, Altium, Sicherung, Hinweise, Fehler) und das Protokoll des Jobs.
 * Wurde wegen Fehlern nichts geschrieben, zeigt der Ring einen Fehler statt eines Häkchens; wurden Bauteile geschrieben,
 * aber Symbol/Footprints nicht in ihre Bibliotheksdateien (`library_problems`, z. B. Datei gesperrt oder kein
 * Bibliotheks-Writer) bzw. Zeilen abgelehnt, eine Warnung – mit den betroffenen Einträgen **außerhalb** des Protokolls und
 * dem Weg zur Behebung („Bibliotheksdateien synchronisieren“ bzw. „Bibliotheks-Writer einrichten“).
 */
import { motion, useReducedMotion } from 'motion/react'
import { ArrowRight, Check, ChevronDown, FileCog, FolderSync, Layers, PlugZap, RotateCw, ShieldCheck, TriangleAlert } from 'lucide-react'
import { useEffect, useId, useState, type ReactNode, type Ref } from 'react'
import { useNavigate } from 'react-router'
import { useAltiumStatus } from '@/api/altium'
import type { SeriesCommitResult, SeriesLibraryProblem, SeriesTemplate } from '@/api/series'
import { useSettings, type JobLogEntry } from '@/api/system'
import { ALTIUM_PATH, altiumActionState } from '@/app/navigation'
import { Button, Callout, CountUp, ProgressRing, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatDuration, formatNumber, formatNumbersInText, plural, pluralNoun } from '@/lib/format'
import { AltiumNextStep } from '@/pages/altium/AltiumNextStep'
import { altiumAfterWrite, writerLabel, type AfterWriteNotice } from '@/pages/altium/model'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { JobLog } from './JobLog'

/** Hinweis bei ungeprüften Vorlagen bzw. offener Lieferbarkeit (vor dem Start und im Ergebnis) */
export function TemplateTrustNote({
  verified,
  availabilityCertain,
  done,
  className,
}: {
  verified: boolean
  availabilityCertain: boolean
  /** nach dem Erzeugen (Vergangenheit) */
  done?: boolean
  className?: string
}) {
  const { t: tr } = useI18n()
  if (verified && availabilityCertain) return null
  const parts: string[] = []
  if (!verified) {
    parts.push(
      done
        ? tr("Codes und Werte dieser Serie sind nicht gegen das Datenblatt geprüft – die Bauteile vor der Freigabe kontrollieren.")
        : tr("Codes und Werte dieser Serie sind nicht gegen das Datenblatt geprüft – die Bauteile nach dem Erzeugen vor der Freigabe kontrollieren."),
    )
  }
  if (!availabilityCertain) {
    parts.push(tr('Nicht jede Teilenummer ist sicher lieferbar – vor der Bestellung beim Hersteller oder Distributor prüfen.'))
  }
  return (
    <Callout tone="warning" title={verified ? tr("Lieferbarkeit nicht geprüft") : tr("Ungeprüfte Vorlage")} className={className}>
      {parts.join(' ')}
    </Callout>
  )
}

type RingTone = 'success' | 'warning' | 'error'

/** Abschluss-Ring: Ring des UI-Kits (Forge-Verlauf, Warngelb bzw. Fehlerrot) zeichnet sich einmal, Funken stieben auf */
function ForgeCheck({ tone }: { tone: RingTone }) {
  const reduce = useReducedMotion()
  const error = tone === 'error'
  const warning = tone === 'warning'
  const [drawn, setDrawn] = useState(Boolean(reduce))
  useEffect(() => {
    if (drawn) return
    const frame = window.requestAnimationFrame(() => setDrawn(true))
    return () => window.cancelAnimationFrame(frame)
  }, [drawn])
  const sparks = Array.from({ length: 10 }, (_, i) => (i / 10) * Math.PI * 2 + 0.3)
  return (
    <div aria-hidden className="relative flex size-28 shrink-0 items-center justify-center">
      <motion.span
        className={cn(
          'absolute inset-0 rounded-full',
          error
            ? 'bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--pf-danger)_30%,transparent),transparent)]'
            : warning
              ? 'bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--pf-warning)_28%,transparent),transparent)]'
              : 'bg-[radial-gradient(closest-side,var(--pf-ember-strong),transparent)]',
        )}
        initial={reduce ? false : { opacity: 0, scale: 0.6 }}
        animate={{ opacity: [0, 1, 0.55], scale: [0.6, 1.25, 1.05] }}
        transition={{ duration: 1.1, ease: [0.16, 1, 0.3, 1] }}
      />
      {!reduce &&
        !error &&
        !warning &&
        sparks.map((a, i) => (
          <motion.span
            key={i}
            className="absolute size-1 rounded-full bg-accent shadow-[0_0_6px_var(--pf-accent-strong)]"
            initial={{ x: 0, y: 0, opacity: 0 }}
            animate={{ x: Math.cos(a) * 64, y: Math.sin(a) * 64, opacity: [0, 1, 0] }}
            transition={{ duration: 0.9, delay: 0.55 + (i % 3) * 0.04, ease: 'easeOut' }}
          />
        ))}
      <ProgressRing value={drawn ? 1 : 0.02} size={96} stroke={5} tone={error ? 'danger' : warning ? 'warning' : 'accent'} className="relative">
        <svg viewBox="0 0 96 96" className="size-24">
          {error || warning ? (
            <motion.path
              d="M48 29 v22 M48 64 v0.5"
              fill="none"
              stroke="var(--pf-fg)"
              strokeWidth="7"
              strokeLinecap="round"
              initial={reduce ? false : { opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.3, delay: 0.5 }}
            />
          ) : (
            <motion.path
              d="M32 49 l11 11 l22 -24"
              fill="none"
              stroke="var(--pf-fg)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeLinejoin="round"
              initial={reduce ? false : { pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ duration: 0.35, delay: 0.55, ease: 'easeOut' }}
            />
          )}
        </svg>
      </ProgressRing>
    </div>
  )
}

function Detail({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span aria-hidden className="mt-px flex size-4 shrink-0 items-center justify-center [&_svg]:size-3.5">
        {icon}
      </span>
      <span className="min-w-0 flex-1">{children}</span>
    </li>
  )
}

/** Symbol der Altium-Zeile je Zustand – „manual“ ohne grünes Häkchen: noch ist in Altium nichts zu sehen */
const ALTIUM_ICON: Record<AfterWriteNotice['tone'], ReactNode> = {
  ok: <Check className="text-success" />,
  busy: <Spinner size={14} className="text-fg-muted" />,
  manual: <RotateCw className="text-fg-subtle" />,
  warn: <TriangleAlert className="text-warning" />,
  error: <TriangleAlert className="text-danger" />,
  off: <PlugZap className="text-fg-subtle" />,
}

/**
 * Was Altium Designer jetzt sieht (echter Zustand über /api/altium/status, `altiumAfterWrite`) – mit dem nächsten
 * Schritt als Aktion der Altium-Seite: installieren (DbLib nicht installiert), aktualisieren (von Hand) bzw. zur Seite.
 */
function AltiumLine() {
  const status = useAltiumStatus().data
  const notice = altiumAfterWrite(status)
  if (!notice) return null
  return (
    <Detail icon={ALTIUM_ICON[notice.tone]}>
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span>{notice.text}</span>
        {notice.next && <AltiumNextStep next={notice.next} />}
      </span>
    </Detail>
  )
}

function Tile({
  label,
  value,
  tone,
  hint,
  title,
}: {
  label: string
  value: number
  tone?: 'danger' | 'warning'
  hint?: ReactNode
  title?: string
}) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-4 py-3.5 @[64rem]:px-5" title={title}>
      <span className="micro-label truncate">{label}</span>
      <span
        className={cn(
          'mono text-metric font-semibold tracking-[-0.02em]',
          value === 0
            ? 'text-fg-subtle'
            : tone === 'danger'
              ? 'text-danger-text'
              : tone === 'warning'
                ? 'text-warning-text'
                : 'text-fg',
        )}
      >
        <CountUp value={value} />
      </span>
      {hint && <span className="truncate text-2xs text-fg-subtle">{hint}</span>}
    </div>
  )
}

export interface SuccessViewProps {
  result: SeriesCommitResult
  title: string
  /** Vorlage der Serie (Prüfstatus) – null, wenn inzwischen eine andere gewählt ist */
  template: Pick<SeriesTemplate, 'verified' | 'availability_certain'> | null
  categoryLabel: string
  /** Laufzeit in Sekunden */
  duration: number | null
  /** Protokoll des Jobs (Phasen, Hinweise, Schlussmeldung) */
  log: JobLogEntry[]
  onShowTable: () => void
  onNewSeries: () => void
  /** dieselbe Serie noch einmal erzeugen (nach gescheitertem Schreiben – schon Angelegtes wird übersprungen) */
  onRetry: () => void
  headingRef?: Ref<HTMLHeadingElement>
}

/** Art eines nicht geschriebenen Eintrags – aus `kind`, sonst aus der Dateiendung bzw. dem Symbol der Serie */
function problemKind(p: SeriesLibraryProblem, symbol: string | null): 'symbol' | 'footprint' {
  if (p.kind === 'symbol' || p.kind === 'footprint') return p.kind
  if (p.library && /\.schlib$/i.test(p.library)) return 'symbol'
  if (p.library && /\.pcblib$/i.test(p.library)) return 'footprint'
  return symbol && p.name.toLowerCase() === symbol.toLowerCase() ? 'symbol' : 'footprint'
}

/**
 * Was nicht in die Bibliotheksdateien kam: `library_problems` des Backends – bei älteren Backends ersatzweise die
 * Fehlerzeilen des Protokolls (Stufe `error`), damit ein gescheitertes Schreiben nie nur im zugeklappten Protokoll steht.
 */
function libraryIssues(r: SeriesCommitResult, log: JobLogEntry[]): { problems: SeriesLibraryProblem[]; logErrors: string[] } {
  const problems = (r.library_problems ?? []).filter((p) => p && typeof p.name === 'string')
  if (r.library_problems) return { problems, logErrors: [] }
  const errors = log.filter((l) => l.level === 'error')
  if (!errors.length) return { problems, logErrors: [] }
  // dazu die Hinweise zu einzelnen Symbolen/Footprints („Footprint RESC6332X70N: … nicht gesichert …“) – sie nennen Name und Grund
  const items = log.filter((l) => l.level === 'warn' && /^(?:Symbol|Footprint) [^:]+: /.test(l.text))
  return { problems, logErrors: [...errors, ...items].map((l) => l.text) }
}

/** Überschrift und Unterzeile je Ergebnis (`ring`: error = nichts geschrieben, warning = mit Fehlern/unvollständig) */
function outcome(r: SeriesCommitResult, categoryLabel: string, issues: { failed: boolean; pendingOnly: boolean }) {
  const written = r.created + r.updated
  const where = tr("Kategorie „{v0}“", { v0: categoryLabel })
  if (written === 0) {
    if (r.errors > 0) {
      return {
        headline: tr("Keine Bauteile geschrieben"),
        text: tr("{v0} ließen sich nicht speichern – Gründe unten.", { v0: plural(r.errors, tr("Bauteil"), tr("Bauteile")) }),
        ring: 'error' as RingTone,
      }
    }
    if (r.unchanged > 0 && r.skipped === 0) {
      // Modus „aktualisieren“, alles schon auf dem Stand
      return {
        headline: tr("Serie ist aktuell"),
        text: tr("{v0} geprüft – keines brauchte eine Änderung · {v1}", { v0: plural(r.unchanged, tr("Bauteil"), tr("Bauteile")), v1: where }),
        ring: (issues.failed ? 'warning' : 'success') as RingTone,
      }
    }
    if (r.skipped + r.unchanged > 0) {
      return {
        headline: tr("Nichts Neues zu erzeugen"),
        text: tr("Alle Bauteile der Serie sind schon in der {v0}.", { v0: where }),
        ring: (issues.failed ? 'warning' : 'success') as RingTone,
      }
    }
    return { headline: tr("Keine Bauteile angelegt"), text: tr("Die Auswahl ergab keine anlegbaren Bauteile."), ring: 'error' as RingTone }
  }
  const verb = r.created && r.updated ? tr("angelegt und aktualisiert") : r.created ? tr("angelegt") : tr("aktualisiert")
  return {
    headline:
      r.errors || (issues.failed && !issues.pendingOnly)
        ? tr("Serie mit Fehlern {v0}", { v0: verb })
        : issues.failed
          ? tr("Serie {v0} – Bibliotheksdateien ausstehend", { v0: verb })
          : tr("Serie {v0}", { v0: verb }),
    text: tr("{v0} in der {v1}", { v0: plural(written, tr("Bauteil"), tr("Bauteile")), v1: where }),
    ring: (r.errors || issues.failed ? 'warning' : 'success') as RingTone,
  }
}

/**
 * Nicht in die Bibliotheksdateien geschrieben – je Eintrag Datei, Grund und betroffene Bauteile, dazu der Weg zur
 * Behebung: gescheitert (`error`/`missing` – die Bauteile damit sind **nicht** angelegt) → Ursache beheben und „Serie
 * erneut erzeugen“; ausstehend (`pending` – Bauteile angelegt, kein Bibliotheks-Writer) → „Bibliotheksdateien
 * synchronisieren“ bzw. „Bibliotheks-Writer einrichten“. Ältere Backends ohne `library_problems`: die Fehlerzeilen des
 * Protokolls; die Bauteile sind dort angelegt, das Synchronisieren holt die Datei nach.
 */
function LibraryProblems({
  problems,
  logErrors,
  symbol,
  onShowLog,
  onRetry,
}: {
  problems: SeriesLibraryProblem[]
  logErrors: string[]
  symbol: string | null
  onShowLog: () => void
  onRetry: () => void
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const status = useAltiumStatus().data
  const backend = useSettings().data?.settings.altium.library_backend
  // Writer-Status unbekannt: Synchronisieren anbieten (das Backend meldet sich, falls doch keiner da ist)
  const writerOk = !status || writerLabel(status, backend).ok
  const failed = problems.filter((p) => p.status !== 'pending')
  const pending = problems.filter((p) => p.status === 'pending')
  const listed = failed.length ? failed : pending
  const symbols = listed.filter((p) => problemKind(p, symbol) === 'symbol').length
  const footprints = listed.length - symbols
  const what = [symbols ? plural(symbols, tr("Symbol"), tr("Symbole")) : null, footprints ? plural(footprints, tr("Footprint"), tr("Footprints")) : null]
    .filter(Boolean)
    .join(tr("und"))
  const title = failed.length
    ? tr("{v0} nicht in die Bibliotheksdateien geschrieben", { v0: what })
    : pending.length
      ? tr("{v0} noch nicht in die Bibliotheksdateien geschrieben", { v0: what })
      : tr("Beim Schreiben der Bibliotheksdateien gab es Fehler")
  const shown = [...failed, ...pending].slice(0, 6)
  // derselbe Grund bei allen (z. B. „Kein Bibliotheks-Writer verfügbar …“): einmal darunter statt an jedem Eintrag
  const reasons = [...new Set(shown.map((p) => p.message?.trim()).filter((m): m is string => Boolean(m)))]
  const sharedReason = shown.length > 1 && reasons.length === 1 ? reasons[0] : null
  const syncButton = writerOk ? (
    <Button
      size="sm"
      variant="secondary"
      leftIcon={<FolderSync />}
      onClick={() => navigate(ALTIUM_PATH, { state: altiumActionState('sync') })}
    >
      {tr("Bibliotheksdateien synchronisieren")}</Button>
  ) : (
    <Button size="sm" variant="secondary" leftIcon={<FileCog />} onClick={() => navigate(SETTINGS_PLACE.altium.to)}>
      {tr("Bibliotheks-Writer einrichten")}</Button>
  )
  return (
    <Callout
      tone={failed.length || logErrors.length ? 'danger' : 'warning'}
      title={title}
      actions={
        failed.length ? (
          <Button size="sm" variant="secondary" leftIcon={<RotateCw />} onClick={onRetry}>
            {tr("Serie erneut erzeugen")}</Button>
        ) : (
          <>
            {syncButton}
            {logErrors.length > 0 && (
              <Button size="sm" variant="ghost" onClick={onShowLog}>
                {tr("Protokoll zeigen")}</Button>
            )}
          </>
        )
      }
    >
      {shown.length > 0 && (
        <ul className="mb-1.5 flex flex-col gap-1">
          {shown.map((p) => (
            <li key={`${p.kind ?? ''}|${p.name}|${p.library ?? ''}`} className="text-xs leading-snug">
              <span className="text-fg-muted">{problemKind(p, symbol) === 'symbol' ? tr("Symbol") : tr("Footprint")}</span>{' '}
              <span className="mono font-medium text-fg">{p.name}</span>
              {p.library && <span className="text-fg-muted"> → {baseName(p.library)}</span>}
              {p.message && !sharedReason && <span className="text-fg-muted">: {formatNumbersInText(localizeMessage(p.message))}</span>}
              {p.parts ? (
                <span className={p.status === 'pending' ? 'text-fg-muted' : 'text-danger-text'}>
                  {' '}
                  ·{' '}
                  {p.status === 'pending'
                    ? tr("{v0} darauf", { v0: plural(p.parts, tr("Bauteil verweist"), tr("Bauteile verweisen")) })
                    : tr("{v0} nicht angelegt", { v0: plural(p.parts, tr("Bauteil"), tr("Bauteile")) })}
                </span>
              ) : null}
            </li>
          ))}
          {problems.length > shown.length && (
            <li className="text-xs text-fg-muted">{tr("… und")} {plural(problems.length - shown.length, tr("weiterer"), tr("weitere"))}</li>
          )}
        </ul>
      )}
      {sharedReason && (
        <p className="mb-1.5 text-xs leading-snug text-fg-muted">
          {sharedReason.includes('Grund:') ? '' : tr("Grund:")}
          {formatNumbersInText(localizeMessage(sharedReason))}
        </p>
      )}
      {logErrors.length > 0 && (
        <ul className="mb-1.5 flex flex-col gap-1">
          {logErrors.slice(0, 4).map((line, i) => (
            <li key={i} className="text-xs leading-snug text-fg">
              {formatNumbersInText(localizeMessage(line))}
            </li>
          ))}
        </ul>
      )}
      <span className="text-xs leading-snug">
        {failed.length
          ? tr("Bauteile damit sind nicht angelegt – Altium fände ihr Symbol bzw. ihren Footprint nicht. Ursache beheben (z. B. die Datei in Altium speichern und schließen), dann die Serie erneut erzeugen: Schon Angelegtes bleibt, es kommen nur die fehlenden Bauteile dazu.")
          : pending.length
            ? writerOk
              ? tr("Die Bauteile sind angelegt und verweisen darauf – Altium findet sie erst, wenn sie in der Datei stehen. „Bibliotheksdateien synchronisieren“ schreibt sie jetzt.")
              : tr("Die Bauteile sind angelegt und verweisen darauf – Altium findet sie erst, wenn sie in der Datei stehen.")
            : writerOk
              ? tr("Die Bauteile verweisen darauf – Altium findet sie erst, wenn sie in der Datei stehen. „Bibliotheksdateien synchronisieren“ holt das Schreiben nach (gesperrte Dateien vorher schließen).")
              : tr("Die Bauteile verweisen darauf – Altium findet sie erst, wenn sie in der Datei stehen. Dafür braucht PartForge einen Bibliotheks-Writer ({v0}) oder ein laufendes Altium Designer.", { v0: SETTINGS_PLACE.altium.label })}
      </span>
    </Callout>
  )
}

export function SuccessView({
  result: r,
  title,
  template,
  categoryLabel,
  duration,
  log,
  onShowTable,
  onNewSeries,
  onRetry,
  headingRef,
}: SuccessViewProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const [showErrors, setShowErrors] = useState(false)
  const [showLog, setShowLog] = useState(false)
  const errors = Object.entries(r.error_details)
  const { problems, logErrors } = libraryIssues(r, log)
  const issuesFailed = problems.length > 0 || logErrors.length > 0
  const pendingOnly = problems.length > 0 && problems.every((p) => p.status === 'pending')
  const { headline, text, ring } = outcome(r, categoryLabel, { failed: issuesFailed, pendingOnly })
  const left = r.conflicts + r.invalid
  const inTable = r.created + r.updated + r.unchanged + r.skipped > 0
  // Hinweise der Feldprüfung je Bauteil (z. B. Wert nicht in einer Auswahlliste) – gespeichert wurde trotzdem
  const partWarnings = Object.entries(r.part_warnings)
  const firstPartWarning = partWarnings.find(([, list]) => list.length > 0)
  // Hinweise, die nur wiederholen, was der Kasten „nicht geschrieben“ schon nennt, entfallen
  const problemNames = problems.map((p) => p.name.toLowerCase())
  const notes = [...r.pending, ...r.warnings].filter((n) => !problemNames.some((name) => n.toLowerCase().includes(name)))
  const failedFootprints = problems.filter((p) => problemKind(p, r.symbol) === 'footprint').length
  const showLogNow = () => {
    setShowLog(true)
    requestAnimationFrame(() => document.getElementById(`${uid}-log`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
  }
  return (
    <div className="@container relative overflow-hidden rounded-panel border border-line bg-surface shadow-raised">
      {/* Zusammenfassung des Backends („Serie erzeugt: 1.248 neu, …“) für Screenreader – die Kacheln zeigen dasselbe */}
      <p className="sr-only" role="status">
        {formatNumbersInText(localizeMessage(r.message))}
      </p>
      <div className="relative flex items-center gap-5 px-6 py-5">
        {/* Punktraster nur hinter dem Ring */}
        <div aria-hidden className="dot-grid pointer-events-none absolute inset-y-0 left-0 w-64 opacity-60 mask-radial" />
        <ForgeCheck tone={ring} />
        <div className="flex min-w-0 flex-1 flex-col gap-4 @[64rem]:flex-row @[64rem]:items-center">
          <div className="min-w-0 flex-1">
            <div className="micro-label line-clamp-1" title={title}>
              {title}
            </div>
            <h2 ref={headingRef} tabIndex={-1} className="mt-1 text-h2 font-semibold tracking-[-0.02em] text-fg outline-none">
              {headline}
            </h2>
            <p className="mt-1 max-w-3xl text-ui text-fg-muted">
              {text}
              {/* Dauer bleibt beim Umbruch beim letzten Wort */}
              {duration !== null ? `\u00a0·\u00a0${formatDuration(duration)}` : ''}
            </p>
          </div>
          {/* nächste Schritte gleich beim Ergebnis – auch in kleinen Fenstern ohne Scrollen sichtbar */}
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button variant={inTable ? 'secondary' : 'primary'} size="lg" leftIcon={<Layers />} onClick={onNewSeries}>
              {tr("Neue Serie")}</Button>
            {inTable && (
              <Button variant="primary" size="lg" rightIcon={<ArrowRight />} onClick={onShowTable}>
                {tr("In Tabelle anzeigen")}</Button>
            )}
          </div>
        </div>
      </div>
      {/* Nicht geschriebene Symbole/Footprints: Altium findet die Bauteile sonst nicht – nicht nur im Protokoll */}
      {issuesFailed && (
        <div className="relative px-6 pb-5">
          <LibraryProblems problems={problems} logErrors={logErrors} symbol={r.symbol} onShowLog={showLogNow} onRetry={onRetry} />
        </div>
      )}
      {/* Prüfstatus der Vorlage: wichtig für die Freigabe – nicht unter den Details verstecken */}
      {template && (!template.verified || !template.availability_certain) && (
        <div className="relative px-6 pb-5">
          <TemplateTrustNote verified={template.verified} availabilityCertain={template.availability_certain} done />
        </div>
      )}
      <div className="relative grid grid-cols-3 gap-px border-t border-line bg-line @[44rem]:grid-cols-6 [&>*]:bg-surface">
        <Tile label={tr("Neu")} value={r.created} hint={r.created ? tr("angelegt") : undefined} />
        <Tile label={tr("Aktualisiert")} value={r.updated} hint={r.unchanged ? tr("{v0} unverändert", { v0: formatNumber(r.unchanged) }) : undefined} />
        <Tile label={tr("Übersprungen")} value={r.skipped} hint={r.skipped ? tr("schon vorhanden") : undefined} />
        <Tile
          label={tr("Ausgelassen")}
          value={left}
          tone="warning"
          hint={
            left
              ? [r.conflicts ? plural(r.conflicts, tr("Konflikt"), tr("Konflikte")) : null, r.invalid ? tr("{v0} ungültig", { v0: formatNumber(r.invalid) }) : null]
                  .filter(Boolean)
                  .join(' · ')
              : undefined
          }
        />
        <Tile label={tr("Fehler")} value={r.errors} tone="danger" hint={r.errors ? tr("beim Schreiben") : undefined} />
        <Tile
          label={tr("Footprints")}
          value={r.footprints_created.length}
          tone={failedFootprints ? 'warning' : undefined}
          hint={
            failedFootprints
              ? tr("{v0} nicht geschrieben", { v0: formatNumber(failedFootprints) })
              : r.footprints_created.length
                ? tr("neu angelegt")
                : tr("alle vorhanden")
          }
          title={r.footprints_created.length ? r.footprints_created.join(', ') : undefined}
        />
      </div>
      <div className="relative grid grid-cols-1 gap-x-8 gap-y-2 border-t border-line px-6 py-4 text-xs text-fg-muted @[60rem]:grid-cols-2">
        <ul className="flex flex-col gap-2">
          {r.symbol && (
            <Detail
              icon={
                problems.some((p) => problemKind(p, r.symbol) === 'symbol') ? (
                  <TriangleAlert className="text-warning" />
                ) : (
                  <Check className="text-success" />
                )
              }
            >
              {tr("Symbol")} <span className="mono text-fg">{r.symbol}</span>{' '}
              {problems.some((p) => problemKind(p, r.symbol) === 'symbol')
                ? problems.some((p) => problemKind(p, r.symbol) === 'symbol' && p.status !== 'pending')
                  ? tr("nicht in die Bibliotheksdatei geschrieben")
                  : tr("noch nicht in die Bibliotheksdatei geschrieben (ausstehend)")
                : r.symbol_created
                  ? tr("neu angelegt")
                  : tr("verwendet (vorhanden)")}
            </Detail>
          )}
          <AltiumLine />
          {r.backup && (
            <Detail icon={<ShieldCheck className="text-success" />}>
              {tr("Sicherung vorher:")} <span className="mono break-all text-fg">{r.backup}</span>
            </Detail>
          )}
        </ul>
        {(notes.length > 0 || firstPartWarning || errors.length > 0) && (
          <ul className="flex flex-col gap-2">
            {notes.map((w) => (
              <Detail key={w} icon={<span className="size-1.5 rounded-full bg-warning" />}>
                {formatNumbersInText(localizeMessage(w))}
              </Detail>
            ))}
            {firstPartWarning && (
              <Detail icon={<span className="size-1.5 rounded-full bg-warning" />}>
                {partWarnings.length >= 100 ? tr("Mindestens 100") : formatNumber(partWarnings.length)}{' '}
                {pluralNoun(partWarnings.length, tr("Bauteil hat"), tr("Bauteile haben"))} {tr("Hinweise der Feldprüfung (gespeichert wurde trotzdem), z. B.")} <span className="mono text-fg">{firstPartWarning[0]}</span>: {localizeMessage(firstPartWarning[1][0])}
              </Detail>
            )}
            {errors.length > 0 && (
              <li>
                <button
                  type="button"
                  aria-expanded={showErrors}
                  aria-controls={`${uid}-errors`}
                  onClick={() => setShowErrors((v) => !v)}
                  className="rounded-sm font-medium text-danger-text underline-offset-2 outline-none hover:underline focus-ring"
                >
                  {showErrors ? tr("Fehler ausblenden") : tr("{v0} anzeigen", { v0: plural(errors.length, tr("Fehler"), tr("Fehler")) })}
                </button>
                {showErrors && (
                  <ul
                    id={`${uid}-errors`}
                    className="mt-2 flex max-h-48 flex-col gap-1 overflow-y-auto rounded-control border border-line bg-bg/60 p-2"
                  >
                    {errors.slice(0, 100).map(([pn, msg]) => (
                      <li key={pn} className="text-2xs">
                        <span className="mono text-fg">{pn}</span>: {localizeMessage(msg)}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            )}
          </ul>
        )}
      </div>
      {log.length > 0 && (
        <div className="relative border-t border-line px-6 py-3">
          <button
            type="button"
            aria-expanded={showLog}
            aria-controls={`${uid}-log`}
            onClick={() => setShowLog((v) => !v)}
            className="-mx-2 flex items-center gap-2 rounded-control px-2 py-1 text-xs font-medium text-fg-muted outline-none transition-colors hover:bg-surface-2 hover:text-fg focus-ring"
          >
            <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', showLog && 'rotate-180')} />
            {tr("Protokoll")}<span className="font-normal text-fg-subtle">{plural(log.length, tr("Eintrag"), tr("Einträge"))}</span>
          </button>
          {showLog && (
            <div id={`${uid}-log`} className="pb-1 pt-2">
              <JobLog entries={log} viewportClassName="max-h-60" />
            </div>
          )}
        </div>
      )}
    </div>
  )
}
