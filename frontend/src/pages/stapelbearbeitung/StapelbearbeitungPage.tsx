/**
 * Stapelbearbeitung: registrierte Symbole und Footprints der geöffneten Bibliothek in einem Arbeitsgang an den
 * Hausstil angleichen (nie externe Bibliotheken).
 *
 * Links „Auswahl und Regeln“ (klebt beim Scrollen), rechts der Bericht. „Prüfen“ (Job `housestyle.check`, liest nur)
 * zeigt je Bauteil, was sich ändern würde, je PcbLib die erkannten Lagenrollen (von Hand änderbar) und Abweichungen
 * des Lagen-Kopfs. „Anwenden“ (Job `libraries.conform`) schreibt verlustfrei auf Datensatzebene – was keine Regel
 * betrifft, bleibt Byte für Byte erhalten, Namen ändern sich nie –, sichert jede Datei vorher nach `Backups\lib` und
 * lässt sich rückgängig machen. Jede Änderung an Auswahl, Regeln, Rollen oder Hausstil nach einer Prüfung macht den
 * Bericht veraltet: „Anwenden“ erst nach erneutem Prüfen. Der Zustand gilt für die Sitzung (`store.ts`).
 *
 * Router-State (z. B. vom Bibliotheksimport): `{ libraries?: string[], names?: string[] }` → diese Bibliotheken bzw.
 * Bauteile mit Herkunft „Importiert“ auswählen und einmal prüfen. Der State wird danach gelöscht – Neuladen und Zurück
 * prüfen nicht erneut; die Adresse selbst löst nie etwas aus.
 */
import { useQueryClient } from '@tanstack/react-query'
import { PaintbrushVertical, RefreshCw, ScanSearch, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { useHousestyleRules, useHousestyleUndo, type ConformRules, type LayerRoleName } from '@/api/housestyle'
import { librariesKeys, useLibraryFiles } from '@/api/libraries'
import { useWorkspace } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { Button, Card, confirm, Skeleton } from '@/components/ui'
import { formatDateTime, formatNumbersInText, plural } from '@/lib/format'
import { ApplyOutcome, JobProgress, UndoNotice, UndoOutcome } from './ActionPanels'
import {
  buildInput,
  checkKey,
  DEFAULT_SELECTION,
  defaultRulesKeepingRoles,
  describeSelection,
  incomingFromState,
  isDefaultRules,
  normalizeRules,
  reportStats,
  rulesKey,
  selectionProblem,
  SOURCES,
  withManualRole,
  type Selection,
  type StyleInfo,
} from './model'
import { ReportView } from './ReportView'
import { SelectionPanel } from './SelectionPanel'
import { CheckIssue, IntroState, NoComponentsState, ReportSkeleton } from './States'
import { updateBatchSession } from './store'
import { useBatchJobs } from './useBatchJobs'

const TITLE = 'Stapelbearbeitung'
const GRID =
  'grid grid-cols-1 items-start gap-5 @[44rem]:grid-cols-[18rem_minmax(0,1fr)] @[62rem]:grid-cols-[20rem_minmax(0,1fr)] @[80rem]:grid-cols-[22rem_minmax(0,1fr)]'

export default function StapelbearbeitungPage() {
  const root = useWorkspace().data?.root ?? null
  if (!root) {
    return (
      <PageBody>
        <PageTitle title={TITLE} />
        <div className={GRID} aria-busy="true" aria-label="Stapelbearbeitung wird geladen">
          <Skeleton className="h-[32rem] rounded-card" />
          <Skeleton className="h-80 rounded-card" />
        </div>
      </PageBody>
    )
  }
  // je Bibliothek ein eigener Stand – ein Wechsel baut die Seite neu auf
  return <BatchEditor key={root} root={root} />
}

function BatchEditor({ root }: { root: string }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const workspace = useWorkspace().data
  const style: StyleInfo | null = workspace?.settings ?? null
  const rulesQ = useHousestyleRules()
  const undoQ = useHousestyleUndo()
  const filesQ = useLibraryFiles()
  const jobs = useBatchJobs(root)
  const { session } = jobs

  // ------------------------------------------------------------------ Regeln und Anfrage

  // Entwurf – sonst die zuletzt angewendeten Regeln der Bibliothek – sonst Standard
  const savedRules = useMemo(() => normalizeRules(rulesQ.data ?? null), [rulesQ.data])
  const rules = session.rules ?? savedRules
  const rulesLoading = session.rules === null && rulesQ.isPending
  const rulesChanged = !rulesLoading && rulesKey(rules) !== rulesKey(savedRules)
  const setRules = (next: ConformRules) => updateBatchSession(root, { rules: next })
  const setSelection = (selection: Selection) => updateBatchSession(root, { selection })

  const input = useMemo(() => buildInput(session.selection, rules), [session.selection, rules])
  const key = useMemo(() => checkKey(input, style), [input, style])
  const problem = selectionProblem(session.selection, rules)

  const stored = jobs.report
  const stats = useMemo(() => (stored ? reportStats(stored.report) : null), [stored])
  const outdated = Boolean(stored && stored.key !== key)
  const undoInfo = undoQ.data ?? null
  const last = session.last
  const checkRunning = jobs.check.state === 'running'
  const checking = checkRunning || jobs.starting.check

  const checkBlocked = jobs.busy
    ? 'Ein Job der Stapelbearbeitung läuft gerade.'
    : rulesLoading
      ? 'Die Regeln werden noch geladen.'
      : problem
  const applyBlocked = jobs.busy
    ? 'Ein Job der Stapelbearbeitung läuft gerade.'
    : !stored || !stats
      ? 'Zuerst prüfen – „Anwenden“ ändert, was der Bericht zeigt.'
      : outdated
        ? 'Der Bericht ist veraltet – bitte erneut prüfen.'
        : !stats.pending
          ? 'Alles im Hausstil – nichts anzuwenden.'
          : stats.writeLibraries === 0
            ? 'Keine der Bibliotheken lässt sich ändern (nicht lesbar bzw. übersprungen).'
            : null

  // ------------------------------------------------------------------ Aktionen

  const onCheck = () => {
    if (checkBlocked) return
    jobs.startCheck(input, key)
  }

  const onApply = async () => {
    if (applyBlocked || !stored || !stats) return
    const libs = plural(stats.writeLibraries, 'Bibliothek', 'Bibliotheken')
    const lead =
      stats.writeComponents > 0
        ? `${plural(stats.writeComponents, 'Bauteil', 'Bauteile')} in ${libs} ${stats.writeComponents === 1 ? 'wird' : 'werden'} an den Hausstil angepasst.`
        : `In ${libs} wird der Lagen-Kopf an den Hausstil angepasst.`
    const ok = await confirm({
      title: 'Hausstil anwenden?',
      icon: <PaintbrushVertical />,
      confirmLabel: 'Anwenden',
      description: (
        <>
          {lead}
          {stats.writeComponents > 0 &&
            stats.headerLibraries > 0 &&
            ` Bei ${plural(stats.headerLibraries, 'Bibliothek', 'Bibliotheken')} wird außerdem der Lagen-Kopf erneuert.`}
          <span className="mt-2 block">
            Jede Datei wird vorher nach <span className="mono">Backups\lib</span> gesichert – die Stapelbearbeitung
            lässt sich rückgängig machen. Was keine Regel betrifft, bleibt unverändert; Namen ändern sich nie.
          </span>
          <span className="mt-2 block">
            Bibliotheken, die in Altium geöffnet und geändert sind, werden übersprungen
            {stats.refused > 0 ? ` (laut Bericht ${plural(stats.refused, 'Bibliothek', 'Bibliotheken')})` : ''}.
          </span>
          <span className="mt-2 block">PartForge merkt sich die Regeln für diese Bibliothek.</span>
        </>
      ),
    })
    if (!ok) return
    // genau das anwenden, was geprüft wurde (der Bericht ist nicht veraltet – Anfrage und Hausstil sind gleich)
    jobs.startApply(stored.input, { components: stats.writeComponents, libraries: stats.writeLibraries })
  }

  const onUndo = async () => {
    if (!undoInfo || jobs.busy) return
    const count = undoInfo.libraries?.length ?? 0
    const when = undoInfo.created ? ` vom ${formatDateTime(undoInfo.created)}` : ''
    const ok = await confirm({
      title: 'Stapelbearbeitung rückgängig machen?',
      icon: <Undo2 />,
      confirmLabel: 'Rückgängig machen',
      description: (
        <>
          {count === 1
            ? `Die Bibliothek der Stapelbearbeitung${when} bekommt ihre Sicherung zurück`
            : `Die ${plural(count, 'Bibliothek', 'Bibliotheken')} der Stapelbearbeitung${when} bekommen ihre Sicherungen zurück`}
          , die Einträge in PartForge ihren vorherigen Stand.
          <span className="mt-2 block">
            Bibliotheken, die seitdem geändert wurden, bleiben unverändert und werden übersprungen. Der jetzige Stand
            wird vorher ebenfalls gesichert.
          </span>
        </>
      ),
    })
    if (ok) jobs.startUndo()
  }

  const onRoleChange = (library: string, layer: string, role: LayerRoleName | null) =>
    setRules(withManualRole(rules, library, layer, role))

  // ------------------------------------------------------------------ Vorgabe per Router-State (einmal je Navigation)

  const rulesReady = !rulesLoading
  const handled = useRef<string | null>(null)
  const latest = useRef({ rules, style, busy: jobs.busy, startCheck: jobs.startCheck })
  useEffect(() => {
    latest.current = { rules, style, busy: jobs.busy, startCheck: jobs.startCheck }
  })
  useEffect(() => {
    const incoming = incomingFromState(location.state)
    if (!incoming || !rulesReady || handled.current === location.key) return
    handled.current = location.key
    const selection: Selection = {
      ...DEFAULT_SELECTION,
      sources: ['imported'],
      libraries: incoming.libraries,
      names: incoming.names,
    }
    updateBatchSession(root, { selection })
    // State löschen: Neuladen und Zurück prüfen nicht erneut
    navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
    const cur = latest.current
    if (cur.busy || selectionProblem(selection, cur.rules)) return
    const next = buildInput(selection, cur.rules)
    cur.startCheck(next, checkKey(next, cur.style))
  }, [location.state, location.key, location.pathname, location.search, rulesReady, navigate, root])

  // ------------------------------------------------------------------ Befehlspalette

  useRegisterCommands([
    {
      id: 'housestyle.check',
      title: stored || last ? 'Hausstil erneut prüfen' : 'Hausstil prüfen',
      subtitle: 'Stapelbearbeitung – zeigt, was sich ändern würde',
      group: 'Aktionen',
      icon: ScanSearch,
      keywords: ['stapelbearbeitung', 'hausstil', 'prüfen', 'symbole', 'footprints'],
      priority: 40,
      disabled: () => checkBlocked ?? false,
      run: onCheck,
    },
    {
      id: 'housestyle.apply',
      title: 'Hausstil anwenden',
      subtitle: 'Geprüfte Abweichungen angleichen – mit Sicherung und Rückgängig',
      group: 'Aktionen',
      icon: PaintbrushVertical,
      keywords: ['stapelbearbeitung', 'hausstil', 'anwenden', 'angleichen'],
      priority: 39,
      disabled: () => applyBlocked ?? false,
      run: () => void onApply(),
    },
    {
      id: 'housestyle.undo',
      title: 'Stapelbearbeitung rückgängig machen',
      subtitle: 'Letzte Stapelbearbeitung aus den Sicherungen wiederherstellen',
      group: 'Aktionen',
      icon: Undo2,
      keywords: ['hausstil', 'rückgängig', 'sicherung'],
      when: () => Boolean(undoInfo),
      disabled: () => (jobs.busy ? 'Ein Job der Stapelbearbeitung läuft gerade.' : false),
      run: () => void onUndo(),
    },
  ])

  // ------------------------------------------------------------------ Ansicht

  const files = filesQ.data
  const nothingRegistered = Boolean(files && files.every((f) => !f.exists || f.registered <= 0))
  const checkFailed =
    last === 'check' &&
    (jobs.check.state === 'failed' || jobs.check.state === 'cancelled' || jobs.check.state === 'unknown')
  const recheck = { onRecheck: onCheck, recheckBlocked: checkBlocked, recheckPending: jobs.starting.check }
  // eigene Rückgängig-Knöpfe haben die Ergebnisse von Anwenden/Rückgängig
  const showUndoNotice = Boolean(undoInfo) && last !== 'apply' && last !== 'undo'
  const allSources = SOURCES.every((s) => stored?.input.selection?.sources?.includes(s))
  const applying = jobs.starting.apply || jobs.apply.state === 'running'
  // eine Primäraktion: „Anwenden“, sobald es geht (bzw. läuft), sonst „Prüfen“
  const applyPrimary = applyBlocked === null || applying
  const recheckLabel = Boolean(stored) || last === 'apply' || last === 'undo'
  // Abschluss für Screenreader (die Seite zeigt das Ergebnis selbst, ohne Toast)
  const announcement =
    last === 'check' && stored && jobs.check.state === 'done'
      ? `Prüfung abgeschlossen. ${stored.report.message}`
      : last === 'apply' && jobs.applyResult
        ? jobs.applyResult.message
        : last === 'undo' && jobs.undoResult
          ? jobs.undoResult.message
          : ''

  return (
    // unten Platz für die Pille des Job-Docks, solange sie zu sehen ist
    <PageBody className="pb-[max(3rem,var(--pf-dock-reserve))]">
      <PageTitle title={TITLE} subtitle={describeSelection(input.selection)} />
      <PageActions>
        {undoInfo && (
          <Button
            variant="ghost"
            leftIcon={<Undo2 />}
            onClick={() => void onUndo()}
            disabled={jobs.busy}
            loading={jobs.starting.undo}
          >
            Rückgängig
          </Button>
        )}
        <Button
          variant={applyPrimary ? 'secondary' : 'primary'}
          leftIcon={recheckLabel ? <RefreshCw /> : <ScanSearch />}
          onClick={onCheck}
          disabled={Boolean(checkBlocked)}
          loading={checking}
        >
          {recheckLabel ? 'Erneut prüfen' : 'Prüfen'}
        </Button>
        <Button
          variant={applyPrimary ? 'primary' : 'secondary'}
          leftIcon={<PaintbrushVertical />}
          onClick={() => void onApply()}
          disabled={applyBlocked !== null}
          loading={applying}
        >
          Anwenden
        </Button>
      </PageActions>

      <div className={GRID}>
        <SelectionPanel
          selection={session.selection}
          onSelectionChange={setSelection}
          rules={rules}
          rulesLoading={rulesLoading}
          onRulesChange={setRules}
          onResetRules={isDefaultRules(rules) ? null : () => setRules(defaultRulesKeepingRoles(rules))}
          rulesChanged={rulesChanged}
          style={style}
          files={files}
          filesLoading={filesQ.isPending}
          filesError={filesQ.error}
          onRetryFiles={() => void qc.invalidateQueries({ queryKey: librariesKeys.files })}
          problem={problem}
        />

        <div className="flex min-w-0 flex-col gap-4">
          <p className="sr-only" aria-live="polite">
            {formatNumbersInText(announcement)}
          </p>
          {showUndoNotice && undoInfo && (
            <UndoNotice
              info={undoInfo}
              onUndo={() => void onUndo()}
              disabled={jobs.busy}
              pending={jobs.starting.undo}
            />
          )}

          {last === 'apply' && (
            <ApplyOutcome
              view={jobs.apply}
              plan={session.apply}
              result={jobs.applyResult}
              onUndo={undoInfo && !jobs.busy ? () => void onUndo() : null}
              {...recheck}
            />
          )}
          {last === 'undo' && <UndoOutcome view={jobs.undo} result={jobs.undoResult} {...recheck} />}

          {last === 'check' && checkRunning && (
            <JobProgress
              job={jobs.check.job}
              title="Hausstil wird geprüft"
              icon={<ScanSearch />}
              note="Liest nur – geändert wird dabei nichts."
              onCancel={jobs.cancelCheck}
              cancelling={jobs.cancelling}
            />
          )}
          {checkFailed && (
            <CheckIssue
              state={jobs.check.state}
              job={jobs.check.job}
              hasReport={Boolean(stored)}
              onCheck={onCheck}
              checkBlocked={checkBlocked}
              checkPending={jobs.starting.check}
            />
          )}

          {stored ? (
            <ReportView
              key={stored.jobId}
              stored={stored}
              outdated={outdated}
              refreshing={checkRunning}
              rules={rules}
              onRoleChange={onRoleChange}
              layers={style?.layers ?? null}
              onRecheck={onCheck}
              recheckBlocked={checkBlocked}
              recheckPending={jobs.starting.check}
              allSources={allSources}
              onWidenSources={() => setSelection({ ...session.selection, sources: [...SOURCES] })}
            />
          ) : last === 'check' && checkRunning ? (
            <ReportSkeleton />
          ) : last === null || checkFailed ? (
            nothingRegistered ? (
              <NoComponentsState />
            ) : (
              // nach einer abgebrochenen/gescheiterten ersten Prüfung steht „Erneut prüfen“ schon darüber
              <IntroState
                onCheck={onCheck}
                checkBlocked={checkBlocked}
                checkPending={jobs.starting.check}
                actions={!checkFailed}
              />
            )
          ) : null}

          {last === null && !stored && filesQ.isError && (
            <Card className="px-4 py-3 text-xs text-fg-muted">
              Die Bibliotheksdateien ließen sich nicht lesen – prüfen geht trotzdem; die Auswahl einzelner Bibliotheken
              ist dann nicht möglich.
            </Card>
          )}
        </div>
      </div>
    </PageBody>
  )
}
