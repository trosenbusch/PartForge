import { t as tr } from '@/lib/i18n'
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
    ? tr("„{0}“ wurde abgebrochen – Details im Job-Dock.", { "0": String(running[0].title) })
    : tr("{0} Jobs wurden abgebrochen – Details im Job-Dock.", { "0": String(formatNumber(running.length)) })
}

const TITLE: Record<LibrarySwitchKind, string> = {
  get switch() { return tr("Bibliothek wechseln?") },
  get create() { return tr("Neue Bibliothek anlegen und wechseln?") },
  get close() { return tr("Bibliothek schließen?") },
}

const CONFIRM: Record<LibrarySwitchKind, string> = {
  get switch() { return tr("Trotzdem wechseln") },
  get create() { return tr("Trotzdem anlegen") },
  get close() { return tr("Trotzdem schließen") },
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
  const more = running.length > 3 ? tr(" und {0} weitere", { "0": String(formatNumber(running.length - 3)) }) : ''
  const what =
    running.length === 1
      ? tr("{0} läuft noch und wird abgebrochen.", { "0": String(names[0]) })
      : tr("{0} Jobs laufen noch und werden abgebrochen: {1}{2}.", { "0": String(formatNumber(running.length)), "1": String(names.join(', ')), "2": String(more) })
  const kept = current ? tr(" Was schon geschrieben ist, bleibt in „{0}“ erhalten.", { "0": String(current) }) : ''
  return confirm({
    title: TITLE[kind],
    description: `${what}${kept}`,
    confirmLabel: CONFIRM[kind],
    cancelLabel: tr("Weiterlaufen lassen"),
    destructive: true,
  })
}
