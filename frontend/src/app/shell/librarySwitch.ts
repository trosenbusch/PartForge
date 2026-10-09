/**
 * Vor einem Bibliothekswechsel (Öffnen, Anlegen, Schließen) fragen, wenn dabei Jobs abgebrochen würden: Das Backend
 * bricht die schreibenden Jobs der offenen Bibliothek ab (`partforge.jobs.library_switch`, `cancel_reason
 * "library_switch"`) – ohne Rückfrage verlöre z. B. eine laufende Serie still ihre restlichen Bauteile.
 *
 *   if (!(await confirmLibrarySwitch('switch'))) return
 *   openWs.mutate(path, …)
 */
import { queryClient } from '@/api/queryClient'
import { isJobActive, SWITCH_CANCELLED_JOB_KINDS, systemKeys, type Job, type WorkspaceInfo } from '@/api/system'
import { confirm } from '@/components/ui'
import { formatNumber } from '@/lib/format'

export type LibrarySwitchKind = 'switch' | 'create' | 'close'

/** Laufende Jobs, die ein Bibliothekswechsel jetzt abbrechen würde (aus der Jobliste des Job-Docks) */
export function jobsCancelledBySwitch(): Job[] {
  const seen = new Map<string, Job>()
  for (const [, list] of queryClient.getQueriesData<Job[]>({ queryKey: systemKeys.jobsAll })) {
    for (const job of list ?? []) {
      const known = seen.get(job.id)
      if (!known || job.version > known.version) seen.set(job.id, job)
    }
  }
  return [...seen.values()].filter((j) => isJobActive(j) && SWITCH_CANCELLED_JOB_KINDS.has(j.kind))
}

/**
 * Kurzer Satz für die Erfolgsmeldung des Wechsels („„Serie …“ wurde abgebrochen.“) – **vor** dem Wechsel abfragen; der
 * Toast des abgebrochenen Jobs kann unter „„B“ geöffnet“ liegen, so steht es auch obenauf. `null` = nichts abgebrochen.
 */
export function switchCancelNote(): string | null {
  const running = jobsCancelledBySwitch()
  if (!running.length) return null
  return running.length === 1
    ? `„${running[0].title}“ wurde abgebrochen – Details im Job-Dock.`
    : `${formatNumber(running.length)} Jobs wurden abgebrochen – Details im Job-Dock.`
}

const TITLE: Record<LibrarySwitchKind, string> = {
  switch: 'Bibliothek wechseln?',
  create: 'Neue Bibliothek anlegen und wechseln?',
  close: 'Bibliothek schließen?',
}

const CONFIRM: Record<LibrarySwitchKind, string> = {
  switch: 'Trotzdem wechseln',
  create: 'Trotzdem anlegen',
  close: 'Trotzdem schließen',
}

/**
 * `true`, wenn gewechselt werden darf: keine Jobs betroffen oder der Nutzer bestätigt den Abbruch. Destruktiv – der
 * Fokus startet auf „Weiterlaufen lassen“.
 */
export async function confirmLibrarySwitch(kind: LibrarySwitchKind): Promise<boolean> {
  const running = jobsCancelledBySwitch()
  if (!running.length) return true
  const current = queryClient.getQueryData<WorkspaceInfo | null>(systemKeys.workspace)?.name
  const names = running.slice(0, 3).map((j) => `„${j.title}“`)
  const more = running.length > 3 ? ` und ${formatNumber(running.length - 3)} weitere` : ''
  const what =
    running.length === 1
      ? `${names[0]} läuft noch und wird abgebrochen.`
      : `${formatNumber(running.length)} Jobs laufen noch und werden abgebrochen: ${names.join(', ')}${more}.`
  const kept = current ? ` Was schon geschrieben ist, bleibt in „${current}“ erhalten.` : ''
  return confirm({
    title: TITLE[kind],
    description: `${what}${kept}`,
    confirmLabel: CONFIRM[kind],
    cancelLabel: 'Weiterlaufen lassen',
    destructive: true,
  })
}
