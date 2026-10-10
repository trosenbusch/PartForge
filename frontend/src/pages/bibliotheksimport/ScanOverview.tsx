/**
 * Übersicht eines eingelesenen Scans: Quelle, Zeitpunkt, Zähler (Dateien, Symbole, Footprints und die Zustände der
 * Namen) und die Hinweise des Backends (Datenbankbibliotheken, nicht lesbare integrierte Bibliotheken …).
 */
import { ChevronDown } from 'lucide-react'
import { useState } from 'react'
import type { ImportScan } from '@/api/libimport'
import { Badge, Button, Callout, Card, CountUp, PathText } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatRelativeTime, plural } from '@/lib/format'

/** So viele Hinweise stehen sofort da – weitere auf Wunsch */
const NOTES_SHOWN = 3

type Tone = 'success' | 'info' | 'warning' | 'danger'

const TONE_TEXT: Record<Tone, string> = {
  success: 'text-success-text',
  info: 'text-info-text',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
}

export function ScanOverview({ scan, unreadable }: { scan: ImportScan; unreadable: number }) {
  const counters: { label: string; value: number; tone?: Tone }[] = [
    { label: 'Dateien', value: scan.files.length },
    { label: 'Symbole', value: scan.symbols },
    { label: 'Footprints', value: scan.footprints },
    { label: 'neu', value: scan.new, tone: 'success' },
    { label: 'schon importiert', value: scan.imported, tone: 'info' },
    { label: 'Name vergeben', value: scan.taken, tone: 'warning' },
    { label: 'doppelt', value: scan.duplicates, tone: 'warning' },
  ]
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-1 px-4 pb-3 pt-3.5">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold tracking-[-0.01em] text-fg [overflow-wrap:anywhere]">{scan.name}</h2>
          <PathText path={scan.source} className="text-xs text-fg-muted" />
        </div>
        <div className="flex shrink-0 items-center gap-3 pt-0.5">
          {unreadable > 0 && (
            <Badge variant="danger" dot>
              {plural(unreadable, 'Datei nicht lesbar', 'Dateien nicht lesbar')}
            </Badge>
          )}
          <p className="text-xs text-fg-subtle">
            eingelesen{' '}
            <time dateTime={scan.created} title={formatDateTime(scan.created)}>
              {formatRelativeTime(scan.created)}
            </time>
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-7 divide-x divide-line border-t border-line">
        {counters.map((c) => (
          <div key={c.label} className="flex min-w-0 flex-col justify-between gap-0.5 px-4 py-2.5">
            <dt className="text-2xs leading-tight text-fg-subtle">{c.label}</dt>
            <dd className={cn('mono text-h3 font-semibold tabular-nums', c.value > 0 && c.tone ? TONE_TEXT[c.tone] : 'text-fg')}>
              <CountUp value={c.value} />
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  )
}

/** Hinweise des Scans – die ersten {@link NOTES_SHOWN} sofort, weitere auf Wunsch */
export function ScanNotes({ notes }: { notes: string[] }) {
  const [all, setAll] = useState(false)
  if (!notes.length) return null
  const shown = all ? notes : notes.slice(0, NOTES_SHOWN)
  const rest = notes.length - NOTES_SHOWN
  return (
    <div className="flex flex-col gap-2">
      {shown.map((note, i) => (
        <Callout key={`${i}:${note}`} tone={/datenbankbibliothek/i.test(note) ? 'info' : 'warning'}>
          {note}
        </Callout>
      ))}
      {rest > 0 && (
        <div>
          <Button
            size="xs"
            variant="ghost"
            rightIcon={<ChevronDown className={cn('transition-transform', all && 'rotate-180')} />}
            aria-expanded={all}
            onClick={() => setAll((v) => !v)}
          >
            {all ? 'Weniger Hinweise zeigen' : plural(rest, 'weiterer Hinweis', 'weitere Hinweise')}
          </Button>
        </div>
      )}
    </div>
  )
}
