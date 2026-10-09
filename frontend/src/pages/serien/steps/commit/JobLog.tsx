/**
 * Protokoll eines Jobs (letzte 200 Zeilen, folgt dem Ende, solange man nicht hochgescrollt hat). Die Zeilen kommen vom
 * Backend (jede Phase des Serien-Jobs ist eine Logzeile); `live` hängt den aktuellen Fortschritt als letzte, sich
 * ändernde Zeile an („Zeile 1.801 von 3.686 …“) – so zeigt das Protokoll vom Start an, was gerade passiert.
 * Mengen in Texten erscheinen deutsch gruppiert (`formatNumbersInText`). Bildlauf über die `ScrollArea` des UI-Kits
 * (Tab-Stopp nur, wenn das Protokoll überläuft). Screenreader hören die Abschnitte über die Ansage des Schritts – das
 * Protokoll selbst ist keine Live-Region (sonst käme jede Zeile doppelt).
 */
import { useEffect, useRef } from 'react'
import type { JobLogEntry } from '@/api/system'
import { ScrollArea, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatClock, formatNumbersInText } from '@/lib/format'

const LEVEL: Record<JobLogEntry['level'], { dot: string; text: string; label: string }> = {
  info: { dot: 'bg-fg-subtle', text: 'text-fg-muted', label: 'Info' },
  success: { dot: 'bg-success', text: 'text-fg', label: 'Erfolg' },
  warn: { dot: 'bg-warning', text: 'text-warning-text', label: 'Warnung' },
  error: { dot: 'bg-danger', text: 'text-danger-text', label: 'Fehler' },
}

export interface JobLogProps {
  entries: JobLogEntry[]
  /** aktueller Fortschritt (Statusmeldung des Jobs), solange er läuft – erscheint als letzte Zeile */
  live?: string | null
  /** Text ohne Einträge */
  emptyText?: string
  /** Rahmen (z. B. feste Höhe `h-56`) */
  className?: string
  /** Bildlaufbereich (z. B. Höchsthöhe `max-h-60`) */
  viewportClassName?: string
}

export function JobLog({ entries, live, emptyText = 'Noch keine Einträge …', className, viewportClassName }: JobLogProps) {
  const viewport = useRef<HTMLDivElement | null>(null)
  const stick = useRef(true)
  const liveText = live ? formatNumbersInText(live) : null
  useEffect(() => {
    const el = viewport.current
    if (!el) return
    const onScroll = () => {
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [])
  useEffect(() => {
    const el = viewport.current
    if (el && stick.current) el.scrollTop = el.scrollHeight
  }, [entries.length, liveText])
  return (
    <ScrollArea
      aria-label="Protokoll"
      viewportRef={viewport}
      className={cn('rounded-control border border-line bg-bg/60', className)}
      viewportClassName={viewportClassName}
    >
      <ol aria-label="Protokoll" className="flex flex-col gap-0.5 p-2">
        {entries.length === 0 && !liveText ? (
          <li className="px-1.5 py-1 text-2xs text-fg-subtle">{emptyText}</li>
        ) : (
          entries.slice(-200).map((e, i) => {
            const l = LEVEL[e.level] ?? LEVEL.info
            return (
              <li key={`${e.ts}-${i}`} className="flex items-start gap-2 rounded-sm px-1.5 py-0.5 text-2xs leading-4">
                <span className="mono shrink-0 tabular-nums text-fg-subtle">{formatClock(e.ts)}</span>
                <span aria-hidden className={cn('mt-1.5 size-1.5 shrink-0 rounded-full', l.dot)} />
                <span className="sr-only">{l.label}: </span>
                <span className={cn('min-w-0 break-words', l.text)}>{formatNumbersInText(e.text)}</span>
              </li>
            )
          })
        )}
        {liveText && (
          // ändert sich laufend – nicht vorlesen (die Ansage des Schritts nennt den Abschnitt)
          <li aria-hidden className="flex items-start gap-2 rounded-sm px-1.5 py-0.5 text-2xs leading-4">
            <span className="mono w-[8ch] shrink-0 text-fg-subtle">jetzt</span>
            <Spinner size={10} className="mt-[3px] shrink-0 text-accent" />
            <span className="min-w-0 break-words text-fg">{liveText}</span>
          </li>
        )}
      </ol>
    </ScrollArea>
  )
}
