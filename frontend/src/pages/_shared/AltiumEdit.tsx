/**
 * „In Altium bearbeiten“ in den Detaildialogen von Symbolen und Footprints:
 *
 * - {@link AltiumEditButton} (Fußleiste): öffnet die Bibliothek in Altium und zeigt das Bauteil dort; läuft schon eine
 *   Bearbeitung, holt derselbe Knopf es in Altium wieder nach vorn („In Altium zeigen“).
 * - {@link AltiumEditStatus} (Seitenleiste): solange PartForge die Datei beobachtet – „gespeichert, wird übernommen“,
 *   letzte Übernahme, Fehler; „Jetzt übernehmen“ und „Bearbeitung beenden“.
 * - `confirmReplaceAltiumVersion` (`./altiumEditRules`): Rückfrage, bevor „Bearbeiten“ oder „Neu generieren“ eine in
 *   Altium bearbeitete Fassung ersetzt (das Backend schreibt sie dann immer neu, auch bei gleicher Geometrie).
 */
import { CircleCheck, SquareArrowOutUpRight, TriangleAlert } from 'lucide-react'
import { useAltiumStatus } from '@/api/altium'
import {
  useAltiumEditSession,
  useCheckAltiumEdit,
  useEndAltiumEdit,
  useStartAltiumEdit,
  type AltiumEditKind,
} from '@/api/altiumEdit'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
import { Button, Callout, Spinner, Tooltip } from '@/components/ui'
import { formatDateTime, formatRelativeTime } from '@/lib/format'
import { altiumEditBlocker, type AltiumEditRecord } from './altiumEditRules'

export function AltiumEditButton({
  kind,
  rec,
  fileExists,
}: {
  kind: AltiumEditKind
  rec: AltiumEditRecord | null | undefined
  fileExists: boolean | undefined
}) {
  useI18n()
  const status = useAltiumStatus(Boolean(rec))
  const { session } = useAltiumEditSession(kind, rec?.name)
  const start = useStartAltiumEdit()
  if (!rec) return null
  const altium = status.data
  const blocker = altiumEditBlocker(rec, fileExists)
    ?? (altium && !altium.altium_exe ? tr('Altium Designer wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › Altium Designer eintragen.') : null)
    ?? (altium && !altium.altium_running ? tr('Altium Designer ist nicht gestartet.') : null)
  const enabled = !blocker
  const label = session ? tr('In Altium zeigen') : tr('In Altium bearbeiten')
  const hint = blocker
    ?? (session
      ? tr('„{0}“ in Altium wieder nach vorn holen – gespeicherte Änderungen übernimmt PartForge automatisch.', { 0: rec.name })
      : tr('Öffnet die Bibliothek in Altium Designer und zeigt „{0}“. Nach dem Speichern dort übernimmt PartForge die Änderungen automatisch.', { 0: rec.name }))
  return (
    <Tooltip content={hint}>
      <span tabIndex={enabled ? undefined : 0} className="rounded-button outline-none focus-ring">
        <Button
          variant="secondary"
          leftIcon={<SquareArrowOutUpRight />}
          disabled={!enabled}
          loading={start.isPending}
          onClick={() => start.mutate({ kind, name: rec.name })}
        >
          {label}
        </Button>
      </span>
    </Tooltip>
  )
}

export function AltiumEditStatus({ kind, name }: { kind: AltiumEditKind; name: string | null | undefined }) {
  useI18n()
  const { session } = useAltiumEditSession(kind, name)
  const check = useCheckAltiumEdit()
  const end = useEndAltiumEdit()
  if (!session) return null
  const busy = session.state === 'checking' || session.state === 'saved'
  const last = session.last_result
  const others = session.targets.filter((t) => t.toLocaleLowerCase('en') !== (name ?? '').toLocaleLowerCase('en'))
  const actions = (
    <span className="flex flex-col items-stretch gap-1.5">
      <Button size="xs" variant="secondary" loading={check.isPending} disabled={busy} onClick={() => check.mutate(session.id)}>
        {tr('Jetzt übernehmen')}
      </Button>
      <Button size="xs" variant="ghost" loading={end.isPending} onClick={() => end.mutate(session.id)}>
        {tr('Bearbeitung beenden')}
      </Button>
    </span>
  )
  if (session.state === 'error') {
    return (
      <Callout tone="warning" title={tr('Übernahme aus Altium fehlgeschlagen')} icon={<TriangleAlert />} actions={actions} live>
        {session.error ? localizeMessage(session.error) : tr('Die gespeicherte Bibliothek konnte nicht gelesen werden.')}{' '}
        {tr('PartForge versucht es nach dem nächsten Speichern erneut.')}
      </Callout>
    )
  }
  return (
    <Callout
      tone="info"
      title={busy ? tr('In Altium gespeichert') : tr('In Altium geöffnet')}
      icon={busy ? <Spinner size={14} /> : <SquareArrowOutUpRight />}
      actions={actions}
      live
    >
      <span className="block">
        {busy
          ? tr('Die Änderungen werden übernommen …')
          : tr('Nach dem Speichern in Altium (Strg+S) übernimmt PartForge die Änderungen automatisch.')}
      </span>
      {last && (
        <span className="mt-1 flex items-center gap-1 text-fg-subtle" title={formatDateTime(new Date(last.time))}>
          <CircleCheck aria-hidden className="size-3 shrink-0 text-success-text" />
          {tr('Zuletzt übernommen {0}', { 0: formatRelativeTime(new Date(last.time)) })}
        </span>
      )}
      {others.length > 0 && (
        <span className="mt-1 block text-fg-subtle">
          {tr('Ebenfalls in Altium geöffnet: {0}', { 0: others.join(', ') })}
        </span>
      )}
    </Callout>
  )
}

