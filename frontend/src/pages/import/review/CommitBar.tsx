import { useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  CircleAlert,
  CircleCheck,
  CircuitBoard,
  GitCompareArrows,
  Hammer,
  ListChecks,
  RefreshCw,
  Save,
  ShieldAlert,
  Component as SymbolIcon,
  TableProperties,
  TriangleAlert,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { cleanErrorText, errorMessage } from '@/api/client'
import {
  datasheetKeys,
  datasheetsApi,
  type CommitJobDetail,
  type CommitResult,
  type CommitScope,
  type ProposalChoices,
} from '@/api/datasheets'
import { jobCancelText, jobDetail, trackJob, useInlineJob, useJob } from '@/api/jobs'
import type { Job } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { useUi } from '@/app/stores'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  ProgressRing,
  Spinner,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { cleanJobError } from '../lib/analysis'
import { flushActiveInput } from '../shared/activeInput'
import { TipButton } from '../shared/TipButton'
import { sameBlocker, useReviewUi } from '../store'
import { useReview } from './context'
import type { Readiness, ScopeReadiness } from './readiness'

/**
 * Stand des Vorschlags gegenüber den Entscheidungen: Angelegt wird nur, was der Benutzer gerade sieht.
 * `synced` = der sichtbare Vorschlag wurde genau aus `choices` berechnet (entprellt, geladen, keine Korrektur offen).
 */
export interface CommitGate {
  synced: boolean
  /** Entscheidungen, aus denen der sichtbare Vorschlag stammt (gehen unverändert an die Übernahme) */
  choices: ProposalChoices
  /** Aktuelle Entscheidungen frisch aus dem Speicher (JSON) – nach Strg+Enter in einem Eingabefeld */
  readCurrent: () => string
  /** Vorschlag konnte nicht berechnet werden */
  failed: boolean
}

const partLink = (table: string, pn: string) => `/bauteile/${encodeURIComponent(table)}?pn=${encodeURIComponent(pn)}`

function modalOpen(): boolean {
  return document.querySelector('[role="dialog"][aria-modal="true"][data-state="open"], [role="alertdialog"][data-state="open"]') !== null
}

/**
 * Übernahmeleiste: Zusammenfassung (Bauteile, Symbole, Footprints), offene Punkte und die Primäraktion
 * „Bauteile anlegen“ (Job). Gesendet werden genau die Entscheidungen des sichtbaren Vorschlags, dazu die bestätigten
 * Probleme als Texte (`accept_issues`) und sein Fingerabdruck (`expected_fingerprint`). Weicht der neu gebaute Vorschlag
 * ab oder kam ein Problem hinzu, lehnt das Backend ab (nichts geschrieben) – die Leiste und die Prüfliste zeigen dann,
 * was neu zu prüfen ist.
 *
 * „Einzeln speichern“ schreibt nur die Symbole (SchLib) oder nur die Footprints (PcbLib) des Vorschlags (`scope`), legt
 * keine Bauteile an und bleibt in der Prüfansicht – etwa das Symbol eines Datenblatts ohne Maßzeichnung. Bei einer
 * Gehäusezeichnung ohne Bauteil ist „Footprint speichern“ die Primäraktion.
 */
export function CommitBar({ state, gate }: { state: Readiness; gate: CommitGate }) {
  const { ds, proposal, proposalError, category, categories, setChoices, acknowledged } = useReview()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [jobScope, setJobScope] = useState<CommitScope>('part')
  const [error, setError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  /** Strg+Enter direkt nach einer Eingabe: anlegen, sobald der Vorschlag zu diesen Entscheidungen (JSON) passt */
  const [queued, setQueued] = useState<string | null>(null)
  const refusal = useReviewUi((s) => s.refusal)

  const onRefused = useCallback(
    (j: Job<CommitResult>) => {
      const detail = jobDetail<CommitJobDetail>(j)
      const message = cleanErrorText(cleanJobError(j.error)) || 'Die Übernahme wurde abgelehnt – es wurde nichts geschrieben.'
      const ui = useReviewUi.getState()
      // den Vorschlag neu laden: angezeigt wird der Stand, den die Übernahme vorgefunden hat
      void qc.invalidateQueries({ queryKey: datasheetKeys.proposalAll(ds.id) })
      if (detail.code === 'unconfirmed_blockers' && detail.unconfirmed_blockers?.length) {
        ui.setRefusal({ kind: 'blockers', items: detail.unconfirmed_blockers, message })
        ui.showSection('pruefen')
      } else if (detail.code === 'proposal_changed') {
        ui.setRefusal({ kind: 'changed', items: [], message })
        ui.showSection('pruefen')
      } else {
        ui.setRefusal({ kind: 'invalid', items: [], message })
        setError(message)
      }
    },
    [ds.id, qc],
  )

  const { job, isActive } = useJob<CommitResult>(jobId, {
    onDone: (j) => {
      useReviewUi.getState().setRefusal(null)
      if (j.result?.scope && j.result.scope !== 'part') {
        // nur Symbole/Footprints: in der Prüfansicht bleiben (der Toast nennt das Ergebnis), Vorschlag neu laden
        void qc.invalidateQueries({ queryKey: datasheetKeys.proposalAll(ds.id) })
        void qc.invalidateQueries({ queryKey: datasheetKeys.detail(ds.id) })
        void qc.invalidateQueries({ queryKey: datasheetKeys.list })
        void qc.invalidateQueries({ queryKey: datasheetKeys.symbols })
        void qc.invalidateQueries({ queryKey: datasheetKeys.footprints })
        setJobId(null)
        return
      }
      navigate(`/import?ds=${encodeURIComponent(ds.id)}&ansicht=ergebnis`)
    },
    onFailed: (j) => {
      if (j.error_type === 'CommitRefused') onRefused(j)
      else setError(cleanErrorText(cleanJobError(j.error)) || 'Die Übernahme ist fehlgeschlagen.')
    },
    onCancelled: (j) => setError(jobCancelText(j)),
  })
  // Die Leiste zeigt den Job selbst (nicht in der Pille); verlässt man die Ansicht vorher, übernimmt das Dock. Nur
  // Symbole/Footprints: die Prüfansicht bleibt stehen – ihr Ergebnis meldet ein Toast („Gespeichert: 1 Symbol · …“)
  useInlineJob(jobId, { toast: jobScope !== 'part' })
  const busy = starting || isActive

  // abgelehnte Übernahme wegen neuer Probleme: erledigt, sobald alle bestätigt sind
  const refusalOpen =
    refusal?.kind === 'blockers' ? refusal.items.some((item) => !acknowledged.some((a) => sameBlocker(a, item))) : Boolean(refusal)
  // Gehäusezeichnung ohne Bauteil: die Footprints sind die Übernahme
  const packageOnly = state.packageOnly
  const accept = packageOnly
    ? state.footprints.confirmedBlockers.length > 0 && state.footprints.openBlockers.length === 0
    : state.confirmedBlockers.length > 0 && state.openBlockers.length === 0
  const openBlockers = packageOnly ? state.footprints.openBlockers : state.openBlockers
  const open = openBlockers.length + state.reasons.length
  const ready = packageOnly ? state.footprints.ready : state.ready
  const syncedJson = JSON.stringify(gate.choices)
  const label = packageOnly ? footprintLabel(state.footprints) : commitLabel(state)

  const start = useCallback(
    async (choices: ProposalChoices, scope: CommitScope = 'part') => {
      if (!proposal) return
      setStarting(true)
      setError(null)
      setJobScope(scope)
      useReviewUi.getState().setRefusal(null)
      const confirmed =
        scope === 'part' ? state.confirmedBlockers : (scope === 'symbols' ? state.symbols : state.footprints).confirmedBlockers
      try {
        const { job: started } = await datasheetsApi.commit(ds.id, {
          ...choices,
          scope,
          accept_issues: confirmed,
          expected_fingerprint: proposal.fingerprint || null,
        })
        // Schlussmeldung des Backends („Angelegt: 2 Bauteile, 2 Symbole, 2 Footprints“) – kein eigener Text; nur
        // Symbole/Footprints: die Prüfansicht bleibt, ein Toast meldet „Gespeichert: 1 Symbol“ mit der Bibliotheksdatei
        trackJob(
          started as Job<CommitResult>,
          scope === 'part'
            ? { dock: false, toast: false }
            : { dock: false, toast: true, doneMessage: (j) => scopeDoneMessage(j), warnWhen: (j) => scopeProblem(j) },
        )
        setJobId(started.id)
      } catch (e) {
        setError(cleanErrorText(errorMessage(e)))
      } finally {
        setStarting(false)
      }
    },
    [ds.id, proposal, state.confirmedBlockers, state.symbols, state.footprints],
  )
  const primaryScope: CommitScope = packageOnly ? 'footprints' : 'part'

  // wartende Übernahme gilt nur, solange die Entscheidungen unverändert sind und der Vorschlag berechnet werden kann
  const waiting = queued !== null && !gate.failed && gate.readCurrent() === queued
  const fire = waiting && queued === syncedJson && gate.synced

  const requestCommit = () => {
    if (busy || waiting) return
    // Getipptes zuerst übernehmen (Strg+Enter im Feld), dann mit dem frischen Stand entscheiden
    flushActiveInput()
    const current = gate.readCurrent()
    if (current === syncedJson && gate.synced) {
      if (ready && proposal) void start(gate.choices, primaryScope)
      else if (open) useReviewUi.getState().showSection('pruefen')
      return
    }
    setError(null)
    setQueued(current)
  }

  /** „Nur Symbol/Footprint speichern“ – nur aus einem sichtbaren, aktuellen Vorschlag (das Menü ist sonst gesperrt) */
  const requestScope = (scope: 'symbols' | 'footprints') => {
    if (busy || waiting || !proposal) return
    flushActiveInput()
    if (gate.readCurrent() !== syncedJson || !gate.synced) return
    const readiness = scope === 'symbols' ? state.symbols : state.footprints
    if (readiness.ready) void start(gate.choices, scope)
    else useReviewUi.getState().showSection(readiness.section)
  }

  // wartende Übernahme: erst, wenn der Vorschlag genau zu den Entscheidungen passt – sonst nichts anlegen
  useEffect(() => {
    if (!fire) return
    const t = setTimeout(() => {
      setQueued(null)
      if (ready && proposal) void start(gate.choices, primaryScope)
      else useReviewUi.getState().showSection('pruefen')
    }, 0)
    return () => clearTimeout(t)
  }, [fire, gate.choices, proposal, start, ready, primaryScope])
  // ungültig gewordene Wartende (weiter geändert, Vorschlag fehlgeschlagen) verwerfen – nie später „von selbst“ anlegen
  useEffect(() => {
    if (queued === null || waiting) return
    const t = setTimeout(() => setQueued(null), 0)
    return () => clearTimeout(t)
  }, [queued, waiting])

  // Strg+Enter überall in der Prüfansicht – auch in Eingabefeldern und auf Auswahlfeldern (vor Radix abgefangen)
  useHotkey(
    'mod+enter',
    (e) => {
      if (modalOpen() || useUi.getState().commandPaletteOpen) return
      e.preventDefault()
      e.stopPropagation()
      requestCommit()
    },
    { capture: true, allowInInputs: true, preventDefault: false },
  )
  const done = packageOnly ? state.footprints.saved : state.allExist
  // Befehlspalette („Bauteile anlegen“, „Nur Symbol speichern“ …)
  useRegisterCommands([
    {
      id: 'import.commit',
      title: label,
      subtitle: 'Datenblatt-Import',
      group: 'Aktionen',
      icon: packageOnly ? Save : Hammer,
      hotkey: 'mod+enter',
      when: () => Boolean(proposal) && !busy && !done,
      run: () => requestCommit(),
    },
    {
      id: 'import.commit-symbols',
      title: 'Nur Symbol speichern',
      subtitle: 'Datenblatt-Import · ohne Bauteil, nur die SchLib',
      group: 'Aktionen',
      icon: SymbolIcon,
      when: () => Boolean(proposal) && !packageOnly && !busy && state.symbols.ready,
      run: () => requestScope('symbols'),
    },
    {
      id: 'import.commit-footprints',
      title: 'Nur Footprint speichern',
      subtitle: 'Datenblatt-Import · ohne Bauteil, nur die PcbLib',
      group: 'Aktionen',
      icon: CircuitBoard,
      when: () => Boolean(proposal) && !packageOnly && !busy && state.footprints.ready,
      run: () => requestScope('footprints'),
    },
  ])

  const count = state.writeCount
  const stale = Boolean(proposal) && !gate.synced
  const invalidSymbols = proposal?.symbols.filter((s) => !s.valid).length ?? 0
  const invalidFootprints = proposal?.footprints.filter((f) => !f.valid).length ?? 0
  const notDone = jobScope === 'part' ? 'Nicht angelegt' : 'Nicht gespeichert'

  let status
  let actions = null
  if (busy) {
    const scoped = jobScope !== 'part'
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="status">
        {job ? <ProgressRing value={job.progress} size={26} stroke={2.5} label="Übernahme" /> : <Spinner size={18} tone="accent" />}
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">
            {scoped
              ? jobScope === 'symbols'
                ? 'Symbol wird gespeichert …'
                : 'Footprint wird gespeichert …'
              : state.updateCount === count && count
                ? 'Wird aktualisiert …'
                : 'Wird angelegt …'}
          </div>
          <div className="truncate text-2xs text-fg-subtle">
            {job?.message ||
              (scoped
                ? `${jobScope === 'symbols' ? 'Symbolbibliothek (SchLib)' : 'Footprint-Bibliothek (PcbLib)'} wird geschrieben – ohne Bauteil`
                : 'Symbole, Footprints und Bauteile werden geschrieben')}
          </div>
        </div>
      </div>
    )
  } else if (waiting) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="status">
        <Spinner size={18} tone="accent" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">Vorschlag wird aktualisiert …</div>
          <div className="truncate text-2xs text-fg-subtle">
            {packageOnly ? 'Danach wird gespeichert' : 'Danach wird angelegt'} – sofern nichts Neues zu prüfen ist
          </div>
        </div>
      </div>
    )
  } else if (error) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="alert">
        <CircleAlert aria-hidden className="size-5 shrink-0 text-danger-text" />
        <div className="min-w-0">
          <div className="text-ui font-medium text-fg">{notDone}</div>
          <TipButton tip={error} className="block max-w-full truncate rounded-sm text-left text-2xs text-danger-text">
            {error}
          </TipButton>
        </div>
      </div>
    )
  } else if (refusal && refusalOpen && refusal.kind !== 'invalid') {
    // abgelehnt, nichts geschrieben: neue Probleme bzw. geänderter Vorschlag – zur Prüfliste
    const blockers = refusal.kind === 'blockers'
    status = (
      <button
        type="button"
        onClick={() => useReviewUi.getState().showSection('pruefen')}
        className="flex w-full min-w-0 max-w-full items-center gap-2.5 rounded-control text-left outline-none focus-ring"
      >
        {blockers ? (
          <ShieldAlert aria-hidden className="size-5 shrink-0 text-warning-text" />
        ) : (
          <GitCompareArrows aria-hidden className="size-5 shrink-0 text-warning-text" />
        )}
        <span className="min-w-0">
          <span className="block truncate text-ui font-medium text-fg">
            {blockers
              ? `${notDone} – ${plural(refusal.items.length, 'neues Problem', 'neue Probleme')} bestätigen`
              : `${notDone} – der Vorschlag hat sich geändert`}
          </span>
          <span className="block truncate text-2xs text-fg-subtle">
            {blockers
              ? 'Es wurde nichts geschrieben · zur Prüfliste'
              : `Es wurde nichts geschrieben · den neuen Stand prüfen und erneut ${jobScope === 'part' ? 'anlegen' : 'speichern'}`}
          </span>
        </span>
      </button>
    )
  } else if (!proposal && proposalError) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="alert">
        <CircleAlert aria-hidden className="size-5 shrink-0 text-danger-text" />
        <div className="min-w-0">
          <div className="text-ui font-medium text-fg">Kein Vorschlag möglich</div>
          <div className="truncate text-2xs text-danger-text">{errorMessage(proposalError)}</div>
        </div>
      </div>
    )
  } else if (!proposal) {
    status = (
      <div className="flex items-center gap-2.5 text-ui text-fg-muted" role="status">
        <Spinner size={16} tone="accent" />
        Vorschlag wird berechnet …
      </div>
    )
  } else if (stale) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="status">
        <Spinner size={18} tone="accent" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">Vorschlag wird aktualisiert …</div>
          <div className="truncate text-2xs text-fg-subtle">
            Ihre Änderung wird geprüft – {packageOnly ? 'Speichern' : 'Anlegen'} geht gleich wieder
          </div>
        </div>
      </div>
    )
  } else if (packageOnly && state.footprints.saved) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5">
        <CircleCheck aria-hidden className="size-5 shrink-0 text-success-text" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">
            Bereits gespeichert · {plural(state.footprints.total, 'Footprint', 'Footprints')}
          </div>
          <div className="truncate text-2xs text-fg-subtle">
            {proposal.footprints
              .map((f) => f.name)
              .filter(Boolean)
              .join(', ')}{' '}
            – im Datenblatt des Bauteils unter „Gehäuse“ übernehmen
          </div>
        </div>
      </div>
    )
  } else if (state.allExist) {
    const part = state.existingPart
    status = (
      <div className="flex min-w-0 items-center gap-2.5">
        <CircleCheck aria-hidden className="size-5 shrink-0 text-success-text" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">
            Bereits übernommen · {plural(state.existsCount, 'Bauteil', 'Bauteile')}
          </div>
          <div className="truncate text-2xs text-fg-subtle">
            Alle Bestellnummern sind schon in{' '}
            {part ? `„${categories.find((c) => c.table === part.table)?.label ?? part.table}“` : 'der Bibliothek'} angelegt
          </div>
        </div>
      </div>
    )
    actions = (
      <div className="flex shrink-0 items-center gap-1.5">
        {ds.committed.some((c) => c.scope === 'part') && (
          <Button asChild variant="ghost">
            <Link to={`/import?ds=${encodeURIComponent(ds.id)}&ansicht=ergebnis`}>
              <ListChecks aria-hidden />
              Ergebnis
            </Link>
          </Button>
        )}
        {part && (
          <Button asChild variant="secondary">
            <Link to={partLink(part.table, part.partNumber)}>
              <TableProperties aria-hidden />
              In der Bauteiltabelle
            </Link>
          </Button>
        )}
        <Button
          variant="secondary"
          leftIcon={<RefreshCw />}
          onClick={() => setChoices((c) => ({ ...c, mode: 'update' }))}
          title="Vorhandene Bauteile mit den Werten aus dem Datenblatt aktualisieren (Freigabe und eigene Links bleiben)"
        >
          Aktualisieren …
        </Button>
      </div>
    )
  } else if (open) {
    const first = openBlockers[0] ?? state.reasons[0]?.text
    const target = openBlockers.length ? 'pruefen' : (state.reasons[0]?.section ?? 'pruefen')
    status = (
      <button
        type="button"
        onClick={() => useReviewUi.getState().showSection(target)}
        className="flex w-full min-w-0 max-w-full items-center gap-2.5 rounded-control text-left outline-none focus-ring"
      >
        {openBlockers.length ? (
          <ShieldAlert aria-hidden className="size-5 shrink-0 text-warning-text" />
        ) : (
          <TriangleAlert aria-hidden className="size-5 shrink-0 text-warning-text" />
        )}
        <span className="min-w-0">
          <span className="block truncate text-ui font-medium text-fg">
            {openBlockers.length
              ? `${plural(openBlockers.length, 'Problem', 'Probleme')} bestätigen`
              : `${plural(state.reasons.length, 'Punkt', 'Punkte')} offen`}
          </span>
          <span className="block truncate text-2xs text-fg-subtle">{first}</span>
        </span>
      </button>
    )
  } else if (packageOnly) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5">
        <CircleCheck aria-hidden className="size-5 shrink-0 text-success-text" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">Bereit zum Speichern</div>
          <div className="truncate text-2xs text-fg-subtle">
            {accept ? `${plural(state.footprints.confirmedBlockers.length, 'Problem', 'Probleme')} bestätigt · ` : ''}
            {state.footprints.writes.join(', ')} → Footprint-Bibliothek (PcbLib), ohne Bauteil
          </div>
        </div>
      </div>
    )
  } else {
    status = (
      <div className="flex min-w-0 items-center gap-2.5">
        <CircleCheck aria-hidden className="size-5 shrink-0 text-success-text" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">{state.updateCount === count ? 'Bereit zum Aktualisieren' : 'Bereit zum Anlegen'}</div>
          <div className="truncate text-2xs text-fg-subtle">
            {accept ? `${plural(state.confirmedBlockers.length, 'Problem', 'Probleme')} bestätigt · ` : ''}in{' '}
            {category?.label ?? proposal.category_label ?? proposal.category}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      // rechts Platz für die Pille des Job-Docks (`--pf-dock-width`, 0px wenn ausgeblendet)
      className="@container relative flex h-14 shrink-0 items-center gap-4 border-t border-line-strong bg-bg-elev pl-4 pr-[max(1rem,var(--pf-dock-width))] shadow-[0_-8px_24px_-16px_rgba(0,0,0,.45)] transition-[padding] duration-200"
    >
      <div className="min-w-0 flex-1" aria-live="polite">
        {status}
      </div>
      {proposal && !busy && !done && (
        <dl className={cn('hidden shrink-0 items-center gap-4 text-xs @[44rem]:flex', stale && 'opacity-60')}>
          {!packageOnly && (
            <>
              <Summary
                label="Bauteile"
                value={formatNumber(count)}
                detail={state.updateCount ? `${state.updateCount} aktualisiert` : state.existsCount ? `${state.existsCount} vorhanden` : undefined}
              />
              <Summary
                label="Symbole"
                value={formatNumber(proposal.symbols.length)}
                detail={
                  invalidSymbols
                    ? `${invalidSymbols} ungültig`
                    : state.pinChanges
                      ? `${state.pinChanges} geändert`
                      : state.symbolsNew
                        ? `${state.symbolsNew} neu`
                        : 'vorhanden'
                }
                warn={state.pinChanges > 0 || invalidSymbols > 0}
              />
            </>
          )}
          <Summary
            label="Footprints"
            value={formatNumber(proposal.footprints.length)}
            detail={invalidFootprints ? `${invalidFootprints} ungültig` : state.footprintsNew ? `${state.footprintsNew} neu` : 'vorhanden'}
            warn={invalidFootprints > 0}
          />
        </dl>
      )}
      {actions ?? (
        <div className="flex shrink-0 items-center gap-2">
          {proposal && !packageOnly && <ScopeMenu state={state} disabled={busy || waiting || stale} onPick={requestScope} />}
          {!(packageOnly && done) && (
            <Button
              variant="primary"
              leftIcon={packageOnly ? <Save /> : <Hammer />}
              loading={busy || waiting}
              disabled={!proposal || !ready || stale}
              aria-keyshortcuts="Control+Enter"
              title={stale ? 'Der Vorschlag wird gerade aktualisiert' : undefined}
              onClick={() => requestCommit()}
            >
              {label}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * „Einzeln speichern“: nur die Symbole (SchLib) oder nur die Footprints (PcbLib) des Vorschlags, ohne Bauteil – z. B.
 * das Symbol eines Datenblatts, dessen Gehäusezeichnung in einem eigenen Dokument steht. Gesperrte Einträge nennen den
 * Grund.
 */
function ScopeMenu({
  state,
  disabled,
  onPick,
}: {
  state: Readiness
  disabled: boolean
  onPick: (scope: 'symbols' | 'footprints') => void
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="secondary" leftIcon={<Save />} rightIcon={<ChevronDown />} disabled={disabled}>
          <span className="hidden @[40rem]:inline">Einzeln speichern</span>
          <span className="sr-only @[40rem]:hidden">Einzeln speichern</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuLabel>Ohne Bauteil – nur in die Bibliothek</DropdownMenuLabel>
        <ScopeItem readiness={state.symbols} onPick={onPick} />
        <ScopeItem readiness={state.footprints} onPick={onPick} />
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ScopeItem({ readiness, onPick }: { readiness: ScopeReadiness; onPick: (scope: 'symbols' | 'footprints') => void }) {
  const symbols = readiness.scope === 'symbols'
  const noun = symbols ? 'Symbol' : 'Footprint'
  const file = symbols ? 'SchLib' : 'PcbLib'
  const count = readiness.writes.length
  const description = readiness.ready
    ? `${readiness.writes.join(', ')} → ${file}`
    : readiness.saved
      ? `Schon in der Bibliothek (${file})`
      : (readiness.reason ?? '')
  return (
    <DropdownMenuItem
      icon={symbols ? <SymbolIcon /> : <CircuitBoard />}
      disabled={!readiness.ready}
      description={description}
      onSelect={() => onPick(readiness.scope)}
    >
      {count > 1 ? `Nur ${formatNumber(count)} ${noun}s speichern` : `Nur ${noun} speichern`}
    </DropdownMenuItem>
  )
}

/** Toast nach „Nur … speichern“: „Gespeichert: 1 Symbol · Symbols\PF_Power.SchLib“ */
function scopeDoneMessage(j: Job<CommitResult>): string {
  const r = j.result
  const libraries = r?.libraries?.length ? ` · ${r.libraries.join(', ')}` : ''
  return `${r?.message || j.message || 'Gespeichert'}${libraries}`
}

/** Nicht geschriebene Symbole/Footprints → Warn-Toast statt Erfolg */
function scopeProblem(j: Job<CommitResult>): string | null {
  const errors = Object.entries(j.result?.errors ?? {})
  return errors.length ? errors.map(([name, message]) => `${name}: ${message}`).join(' · ') : null
}

function footprintLabel(footprints: ScopeReadiness): string {
  const count = footprints.writes.length || footprints.total
  return count > 1 ? `${formatNumber(count)} Footprints speichern` : 'Footprint speichern'
}

function commitLabel(state: Readiness): string {
  const count = state.writeCount
  if (!count) return 'Bauteile anlegen'
  const verb = state.updateCount === count ? 'aktualisieren' : state.updateCount ? 'übernehmen' : 'anlegen'
  return `${plural(count, 'Bauteil', 'Bauteile')} ${verb}`
}

function Summary({ label, value, detail, warn }: { label: string; value: string; detail?: string; warn?: boolean }) {
  return (
    <div className="flex flex-col items-end leading-tight">
      <dt className="text-2xs text-fg-subtle">{label}</dt>
      <dd className="flex items-baseline gap-1">
        <span className="mono font-semibold text-fg">{value}</span>
        {detail && <span className={cn('text-2xs', warn ? 'text-warning-text' : 'text-fg-subtle')}>{detail}</span>}
      </dd>
    </div>
  )
}
