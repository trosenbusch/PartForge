/**
 * ODBC-Verbindungstest als lesbarer Bericht: Ergebnis, Eckdaten (Treiber, Datenbank, Journalmodus, Sonderzeichen),
 * Befunde, je Tabelle Lesezeit und Schlüsselsuche sowie das vollständige Protokoll (kopierbar). Der Job endet mit seiner
 * Zusammenfassung als `job.message` („ODBC-Verbindung in Ordnung: 13 Tabellen, 1 Bauteil gelesen in 0,42 s.“) – sie ist
 * die Ergebniszeile hier und der Text des Toasts, wenn der Dialog vorher geschlossen wurde.
 */
import { AnimatePresence, motion } from 'motion/react'
import { Cable, ChevronRight, CircleAlert, CircleCheck, CircleX, ClipboardCopy, RotateCw } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import type { OdbcReport } from '@/api/altium'
import { jobCancelText, useJob } from '@/api/jobs'
import type { JobLogLevel } from '@/api/system'
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  PathText,
  ProgressBar,
  Spinner,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDecimal, formatNumber, formatNumbersInText, plural } from '@/lib/format'
import { SQLITE_ODBC_URL } from './settingsPlaces'
import { HeadlineLink, SeverityIcon } from './ui'

/** 0,0005 → „< 1 ms“, 0,048 → „48 ms“, 2,5 → „2,5 s“ */
const secs = (v: number | null | undefined) => {
  if (v === null || v === undefined) return '–'
  if (v < 0.001) return '< 1 ms'
  if (v < 1) return `${formatDecimal(v * 1000, v < 0.01 ? 1 : 0)} ms`
  return `${formatDecimal(v, 2)} s`
}

const LOG_TONE: Record<JobLogLevel, string> = {
  info: 'text-fg-muted',
  success: 'text-success-text',
  warn: 'text-warning-text',
  error: 'text-danger-text',
}

export interface OdbcDialogProps {
  jobId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onRetry: () => void
  retrying: boolean
}

export function OdbcDialog({ jobId, open, onOpenChange, onRetry, retrying }: OdbcDialogProps) {
  const { job } = useJob<OdbcReport>(jobId)
  const report = job?.status === 'done' ? job.result : null
  const running = !job || job.status === 'queued' || job.status === 'running'
  /** Ergebnissatz des Jobs (= `report.summary`); ältere Jobs ohne Schlussmeldung: aus dem Bericht */
  const summary = report ? formatNumbersInText(job?.message || report.summary) : ''

  const copy = () => {
    if (!report) return
    const head = [`ODBC-Verbindungstest – ${summary}`, `Treiber: ${report.driver} ${report.driver_version ?? ''}`.trim(), `Datenbank: ${report.database ?? '–'}`, '']
    const lines = job?.log.length ? job.log.map((l) => l.text) : report.lines
    void navigator.clipboard
      ?.writeText([...head, ...lines].join('\n'))
      .then(() => toast.success('Bericht kopiert'))
      .catch(() => toast.error('Kopieren nicht möglich'))
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        <DialogHeader
          icon={<Cable />}
          title="ODBC-Verbindungstest"
          description="Liest die Datenbank genau wie Altium – mit dem 64-Bit-ODBC-Treiber und denselben Verbindungsattributen wie in der DbLib."
        />
        <DialogBody className="flex flex-col gap-5">
          {running && (
            <div className="flex items-center gap-4 rounded-card border border-line bg-surface-2/50 px-4 py-4" aria-live="polite">
              <Spinner size={22} tone="accent" />
              <div className="min-w-0 flex-1">
                <div className="text-ui font-medium text-fg">{job?.message || 'Verbindung wird aufgebaut …'}</div>
                <ProgressBar className="mt-2" value={job?.progress ?? 0} live label="Fortschritt des ODBC-Tests" hideLabel />
              </div>
            </div>
          )}
          {job?.status === 'failed' && (
            <Callout tone="danger" title="Der Test konnte nicht ausgeführt werden" urgent>
              {job.error}
            </Callout>
          )}
          {job?.status === 'cancelled' && (
            <Callout tone="neutral" title="Test abgebrochen">
              {jobCancelText(job)}
            </Callout>
          )}
          {report && <Report report={report} summary={summary} log={job?.log ?? []} />}
        </DialogBody>
        <DialogFooter className="justify-between">
          <Button variant="ghost" leftIcon={<ClipboardCopy />} onClick={copy} disabled={!report}>
            Bericht kopieren
          </Button>
          <div className="flex items-center gap-2">
            <Button variant="secondary" leftIcon={<RotateCw />} onClick={onRetry} loading={retrying || (running && Boolean(job))}>
              Erneut testen
            </Button>
            <Button variant="primary" onClick={() => onOpenChange(false)}>
              Schließen
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Report({ report: r, summary, log }: { report: OdbcReport; summary: string; log: { level: JobLogLevel; text: string }[] }) {
  const [showLog, setShowLog] = useState(false)
  const failedTables = r.tables.filter((t) => !t.ok)
  const rows = r.tables.reduce((n, t) => n + (t.rows ?? 0), 0)
  const facts: { label: string; value: ReactNode; ok?: boolean | null }[] = [
    {
      label: 'Treiber',
      value: r.driver_installed ? (
        <>
          {r.driver} <span className="mono text-fg-muted">{r.driver_version}</span>
          <span className="text-fg-subtle"> · {r.python_bits} Bit</span>
        </>
      ) : (
        `${r.driver} – nicht installiert`
      ),
      ok: r.driver_installed,
    },
    {
      label: 'Verbindung',
      value: r.connected ? `hergestellt in ${secs(r.connect_seconds)}${r.dbms_version ? ` · ${r.kind === 'sqlite' ? 'SQLite' : 'PostgreSQL'} ${r.dbms_version}` : ''}` : 'fehlgeschlagen',
      ok: r.connected,
    },
    ...(r.kind === 'sqlite'
      ? [
          {
            label: 'Journalmodus',
            value: r.journal_mode ? `${r.journal_mode.toUpperCase()}${r.wal_ok ? ' – Altium und PartForge arbeiten gleichzeitig' : ' – PartForge kann nicht speichern, solange Altium liest'}` : '–',
            ok: r.wal_ok,
          },
        ]
      : []),
    {
      label: 'Sonderzeichen',
      value: r.unicode_ok === null ? 'nicht geprüft' : r.unicode_ok ? 'Ω, µ, ± und Umlaute kommen unverändert an' : 'werden verfälscht',
      ok: r.unicode_ok,
    },
    // ohne Verbindung wurde nichts gelesen – kein grünes Häkchen für „0 Tabellen“
    r.connected
      ? {
          label: 'Gelesen',
          value: `${plural(r.tables.length, 'Tabelle', 'Tabellen')} · ${plural(rows, 'Bauteil', 'Bauteile')} in ${secs(r.total_seconds)}`,
          ok: failedTables.length === 0,
        }
      : { label: 'Gelesen', value: 'nichts – keine Verbindung', ok: null },
  ]
  // Befunde, die der Ergebniskasten schon nennt („ODBC-Test fehlgeschlagen: <erster Fehler>“), nicht doppelt zeigen
  const issues = r.issues.filter((i) => !summary.includes(i.message))
  return (
    <>
      {/* Ergebnis */}
      <div
        className={cn(
          'flex items-start gap-3.5 rounded-card border px-4 py-3.5',
          r.ok ? 'border-success/25 bg-success/8' : 'border-danger/30 bg-danger/8',
        )}
        role="status"
      >
        {r.ok ? (
          <CircleCheck aria-hidden className="mt-0.5 size-5 shrink-0 text-success-text" />
        ) : (
          <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0 text-danger-text" />
        )}
        <div className="min-w-0">
          <div className="text-ui font-semibold text-fg">{r.ok ? 'Altium kann die Datenbank lesen' : 'Altium kann die Datenbank so nicht lesen'}</div>
          <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{summary}</p>
          {!r.driver_installed && r.kind === 'sqlite' && (
            <HeadlineLink link={{ label: 'SQLite-ODBC-Treiber herunterladen (ch-werner.de)', href: SQLITE_ODBC_URL }} className="mt-1.5" />
          )}
        </div>
      </div>

      {/* Eckdaten */}
      <dl className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-x-4 gap-y-2.5">
        <dt className="pt-px text-xs text-fg-muted">Datenbank</dt>
        <dd className="min-w-0 text-ui text-fg">
          {r.database ? <PathText path={r.database} className="mono text-xs" /> : '–'}
        </dd>
        {facts.map((f) => (
          <div key={f.label} className="contents">
            <dt className="pt-px text-xs text-fg-muted">{f.label}</dt>
            <dd className="flex min-w-0 items-start gap-2 text-ui text-fg">
              {f.ok === true && <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success-text" />}
              {f.ok === false && <CircleX aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger-text" />}
              <span className="min-w-0">{f.value}</span>
            </dd>
          </div>
        ))}
      </dl>

      {/* Befunde */}
      {issues.length > 0 && (
        <ul className="flex flex-col gap-2">
          {issues.map((i, n) => (
            <li key={n} className="flex items-start gap-2.5 rounded-control border border-line bg-surface-2/50 px-3 py-2 text-xs leading-relaxed text-fg">
              <SeverityIcon severity={i.severity} className="mt-0.5 size-3.5" />
              {i.message}
            </li>
          ))}
        </ul>
      )}

      {!r.driver_installed && r.available_drivers.length > 0 && (
        <Callout tone="info" title="Installierte 64-Bit-ODBC-Treiber">
          {r.available_drivers.join(' · ')}
        </Callout>
      )}

      {/* Tabellen */}
      {r.tables.length > 0 && (
        <section aria-labelledby="odbc-tables">
          <h3 id="odbc-tables" className="micro-label mb-2">
            Tabellen
          </h3>
          <div className="overflow-hidden rounded-card border border-line">
            <table className="w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-line bg-surface-2/50 text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
                  <th scope="col" className="py-2 pl-3 pr-2">Kategorie</th>
                  <th scope="col" className="px-2 py-2 text-right">Bauteile</th>
                  <th scope="col" className="px-2 py-2 text-right">Spalten</th>
                  <th scope="col" className="px-2 py-2 text-right">Lesen</th>
                  <th scope="col" className="px-2 py-2 text-right">Schlüssel</th>
                  <th scope="col" className="py-2 pl-2 pr-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {r.tables.map((t) => (
                  <tr key={t.table} className="align-top">
                    <td className="py-1.5 pl-3 pr-2">
                      <div className="text-xs font-medium text-fg">{t.label ?? t.table}</div>
                      {t.label && <div className="mono text-2xs text-fg-subtle">{t.table}</div>}
                    </td>
                    <td className="mono px-2 py-1.5 text-right text-xs text-fg">{t.rows === null ? '–' : formatNumber(t.rows)}</td>
                    <td className="mono px-2 py-1.5 text-right text-xs text-fg-muted">{t.columns === null ? '–' : formatNumber(t.columns)}</td>
                    <td className="mono px-2 py-1.5 text-right text-xs text-fg-muted">{secs(t.seconds)}</td>
                    <td className="mono px-2 py-1.5 text-right text-xs text-fg-muted">
                      {t.lookup_ok === null ? '–' : t.lookup_ok ? secs(t.lookup_seconds) : 'Fehler'}
                    </td>
                    <td className="py-1.5 pl-2 pr-3">
                      {t.ok ? (
                        <Badge variant="success" dot>
                          Lesbar
                        </Badge>
                      ) : (
                        <span className="flex flex-col gap-0.5">
                          <Badge variant="danger" dot className="self-start">
                            {t.found ? 'Problem' : 'Fehlt'}
                          </Badge>
                          {t.error && <span className="text-2xs text-danger-text">{t.error}</span>}
                          {t.missing_columns.length > 0 && (
                            <span className="text-2xs text-fg-muted">Spalten fehlen: {t.missing_columns.join(', ')}</span>
                          )}
                          {Object.keys(t.sized_columns).length > 0 && (
                            <span className="text-2xs text-fg-muted">
                              Begrenzte Spalten: {Object.entries(t.sized_columns).map(([c, n]) => `${c} (${n})`).join(', ')}
                            </span>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Protokoll */}
      <section>
        <button
          type="button"
          aria-expanded={showLog}
          aria-controls="odbc-log"
          onClick={() => setShowLog((v) => !v)}
          className="flex items-center gap-1.5 rounded-control text-xs font-medium text-fg-muted outline-none hover:text-fg focus-ring"
        >
          <ChevronRight aria-hidden className={cn('size-3.5 transition-transform duration-200', showLog && 'rotate-90')} />
          Protokoll ({formatNumber(log.length || r.lines.length)} Zeilen)
        </button>
        <AnimatePresence initial={false}>
          {showLog && (
            <motion.ol
              id="odbc-log"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="mt-2 overflow-hidden rounded-control border border-line bg-canvas/40 px-3 py-2 font-mono text-2xs leading-relaxed light:bg-surface-2/60"
            >
              {(log.length ? log : r.lines.map((text) => ({ level: 'info' as JobLogLevel, text }))).map((l, i) => (
                <li key={i} className={cn('whitespace-pre-wrap', LOG_TONE[l.level])}>
                  {l.text}
                </li>
              ))}
            </motion.ol>
          )}
        </AnimatePresence>
      </section>
    </>
  )
}
