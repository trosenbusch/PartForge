import { useQueryClient } from '@tanstack/react-query'
import { CircleAlert, CircleCheck, GitCompareArrows, Hammer, ListChecks, RefreshCw, ShieldAlert, TableProperties, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { cleanErrorText, errorMessage } from '@/api/client'
import { datasheetKeys, datasheetsApi, type CommitJobDetail, type CommitResult, type ProposalChoices } from '@/api/datasheets'
import { jobCancelText, jobDetail, trackJob, useInlineJob, useJob } from '@/api/jobs'
import type { Job } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { useUi } from '@/app/stores'
import { Button, ProgressRing, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { cleanJobError } from '../lib/analysis'
import { flushActiveInput } from '../shared/activeInput'
import { TipButton } from '../shared/TipButton'
import { sameBlocker, useReviewUi } from '../store'
import { useReview } from './context'
import type { Readiness } from './readiness'

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
 */
export function CommitBar({ state, gate }: { state: Readiness; gate: CommitGate }) {
  const { ds, proposal, proposalError, category, categories, setChoices, acknowledged } = useReview()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
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
    onDone: () => {
      useReviewUi.getState().setRefusal(null)
      navigate(`/import?ds=${encodeURIComponent(ds.id)}&ansicht=ergebnis`)
    },
    onFailed: (j) => {
      if (j.error_type === 'CommitRefused') onRefused(j)
      else setError(cleanErrorText(cleanJobError(j.error)) || 'Die Übernahme ist fehlgeschlagen.')
    },
    onCancelled: (j) => setError(jobCancelText(j)),
  })
  // Die Leiste zeigt den Job selbst (nicht in der Pille); verlässt man die Ansicht vorher, übernimmt das Dock
  useInlineJob(jobId)
  const busy = starting || isActive

  // abgelehnte Übernahme wegen neuer Probleme: erledigt, sobald alle bestätigt sind
  const refusalOpen =
    refusal?.kind === 'blockers' ? refusal.items.some((item) => !acknowledged.some((a) => sameBlocker(a, item))) : Boolean(refusal)
  const accept = state.confirmedBlockers.length > 0 && state.openBlockers.length === 0
  const open = state.openBlockers.length + state.reasons.length
  const syncedJson = JSON.stringify(gate.choices)
  const label = commitLabel(state)

  const start = useCallback(
    async (choices: ProposalChoices) => {
      if (!proposal) return
      setStarting(true)
      setError(null)
      useReviewUi.getState().setRefusal(null)
      try {
        const { job: started } = await datasheetsApi.commit(ds.id, {
          ...choices,
          accept_issues: state.confirmedBlockers,
          expected_fingerprint: proposal.fingerprint || null,
        })
        // Schlussmeldung des Backends („Angelegt: 2 Bauteile, 2 Symbole, 2 Footprints“) – kein eigener Text
        trackJob(started as Job<CommitResult>, { dock: false, toast: false })
        setJobId(started.id)
      } catch (e) {
        setError(cleanErrorText(errorMessage(e)))
      } finally {
        setStarting(false)
      }
    },
    [ds.id, proposal, state.confirmedBlockers],
  )

  // wartende Übernahme gilt nur, solange die Entscheidungen unverändert sind und der Vorschlag berechnet werden kann
  const waiting = queued !== null && !gate.failed && gate.readCurrent() === queued
  const fire = waiting && queued === syncedJson && gate.synced

  const requestCommit = () => {
    if (busy || waiting) return
    // Getipptes zuerst übernehmen (Strg+Enter im Feld), dann mit dem frischen Stand entscheiden
    flushActiveInput()
    const current = gate.readCurrent()
    if (current === syncedJson && gate.synced) {
      if (state.ready && proposal) void start(gate.choices)
      else if (open) useReviewUi.getState().showSection('pruefen')
      return
    }
    setError(null)
    setQueued(current)
  }

  // wartende Übernahme: erst, wenn der Vorschlag genau zu den Entscheidungen passt – sonst nichts anlegen
  useEffect(() => {
    if (!fire) return
    const t = setTimeout(() => {
      setQueued(null)
      if (state.ready && proposal) void start(gate.choices)
      else useReviewUi.getState().showSection('pruefen')
    }, 0)
    return () => clearTimeout(t)
  }, [fire, gate.choices, proposal, start, state.ready])
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
  // Befehlspalette („Bauteile anlegen“)
  useRegisterCommands([
    {
      id: 'import.commit',
      title: label,
      subtitle: 'Datenblatt-Import',
      group: 'Aktionen',
      icon: Hammer,
      hotkey: 'mod+enter',
      when: () => Boolean(proposal) && !busy && !state.allExist,
      run: () => requestCommit(),
    },
  ])

  const count = state.writeCount
  const stale = Boolean(proposal) && !gate.synced

  let status
  let actions = null
  if (busy) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="status">
        {job ? <ProgressRing value={job.progress} size={26} stroke={2.5} label="Übernahme" /> : <Spinner size={18} tone="accent" />}
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">{state.updateCount === count && count ? 'Wird aktualisiert …' : 'Wird angelegt …'}</div>
          <div className="truncate text-2xs text-fg-subtle">{job?.message || 'Symbole, Footprints und Bauteile werden geschrieben'}</div>
        </div>
      </div>
    )
  } else if (waiting) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="status">
        <Spinner size={18} tone="accent" />
        <div className="min-w-0">
          <div className="truncate text-ui font-medium text-fg">Vorschlag wird aktualisiert …</div>
          <div className="truncate text-2xs text-fg-subtle">Danach wird angelegt – sofern nichts Neues zu prüfen ist</div>
        </div>
      </div>
    )
  } else if (error) {
    status = (
      <div className="flex min-w-0 items-center gap-2.5" role="alert">
        <CircleAlert aria-hidden className="size-5 shrink-0 text-danger-text" />
        <div className="min-w-0">
          <div className="text-ui font-medium text-fg">Nicht angelegt</div>
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
              ? `Nicht angelegt – ${plural(refusal.items.length, 'neues Problem', 'neue Probleme')} bestätigen`
              : 'Nicht angelegt – der Vorschlag hat sich geändert'}
          </span>
          <span className="block truncate text-2xs text-fg-subtle">
            {blockers ? 'Es wurde nichts geschrieben · zur Prüfliste' : 'Es wurde nichts geschrieben · den neuen Stand prüfen und erneut anlegen'}
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
          <div className="truncate text-2xs text-fg-subtle">Ihre Änderung wird geprüft – Anlegen geht gleich wieder</div>
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
        {ds.committed.length > 0 && (
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
    const first = state.openBlockers[0] ?? state.reasons[0]?.text
    status = (
      <button
        type="button"
        onClick={() => useReviewUi.getState().showSection('pruefen')}
        className="flex w-full min-w-0 max-w-full items-center gap-2.5 rounded-control text-left outline-none focus-ring"
      >
        {state.openBlockers.length ? (
          <ShieldAlert aria-hidden className="size-5 shrink-0 text-warning-text" />
        ) : (
          <TriangleAlert aria-hidden className="size-5 shrink-0 text-warning-text" />
        )}
        <span className="min-w-0">
          <span className="block truncate text-ui font-medium text-fg">
            {state.openBlockers.length
              ? `${plural(state.openBlockers.length, 'Problem', 'Probleme')} bestätigen`
              : `${plural(state.reasons.length, 'Punkt', 'Punkte')} offen`}
          </span>
          <span className="block truncate text-2xs text-fg-subtle">{first}</span>
        </span>
      </button>
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
      {proposal && !busy && !state.allExist && (
        <dl className={cn('hidden shrink-0 items-center gap-4 text-xs @[44rem]:flex', stale && 'opacity-60')}>
          <Summary
            label="Bauteile"
            value={formatNumber(count)}
            detail={state.updateCount ? `${state.updateCount} aktualisiert` : state.existsCount ? `${state.existsCount} vorhanden` : undefined}
          />
          <Summary
            label="Symbole"
            value={formatNumber(proposal.symbols.length)}
            detail={state.pinChanges ? `${state.pinChanges} geändert` : state.symbolsNew ? `${state.symbolsNew} neu` : 'vorhanden'}
            warn={state.pinChanges > 0}
          />
          <Summary
            label="Footprints"
            value={formatNumber(proposal.footprints.length)}
            detail={state.footprintsNew ? `${state.footprintsNew} neu` : 'vorhanden'}
          />
        </dl>
      )}
      {actions ?? (
        <Button
          variant="primary"
          leftIcon={<Hammer />}
          loading={busy || waiting}
          disabled={!proposal || !state.ready || stale}
          aria-keyshortcuts="Control+Enter"
          title={stale ? 'Der Vorschlag wird gerade aktualisiert' : undefined}
          onClick={() => requestCommit()}
        >
          {label}
        </Button>
      )}
    </div>
  )
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
