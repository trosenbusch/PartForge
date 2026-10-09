import { ChevronDown, ScrollText } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import type { JobLogEntry } from '@/api/system'
import { cn } from '@/lib/cn'
import { formatClock } from '@/lib/format'

const LEVEL_CLASS: Record<JobLogEntry['level'], string> = {
  info: 'text-fg-muted',
  warn: 'text-warning-text',
  error: 'text-danger-text',
  success: 'text-success-text',
}

/** Aufklappbares Protokoll des Analyse-Jobs (deutsche Meldungen des Backends), folgt neuen Zeilen. */
export function JobLog({ log, defaultOpen = false, className }: { log: JobLogEntry[]; defaultOpen?: boolean; className?: string }) {
  const [open, setOpen] = useState(defaultOpen)
  const id = useId()
  const listRef = useRef<HTMLOListElement>(null)

  useEffect(() => {
    const el = listRef.current
    if (open && el) el.scrollTop = el.scrollHeight
  }, [open, log.length])

  return (
    <div className={cn('border-t border-line', className)}>
      <button
        type="button"
        aria-expanded={open}
        // nur auf das Protokoll verweisen, solange es da ist (zugeklappt wird es nicht gerendert)
        aria-controls={open ? `${id}-log` : undefined}
        onClick={() => setOpen((o) => !o)}
        className="flex h-10 w-full items-center gap-2 px-5 text-xs font-medium text-fg-muted outline-none transition-colors hover:text-fg focus-ring-inset"
      >
        <ScrollText aria-hidden className="size-3.5" />
        Protokoll
        <span className="rounded-full bg-surface-3 px-1.5 text-2xs tabular-nums leading-4 text-fg-subtle">{log.length}</span>
        <ChevronDown aria-hidden className={cn('ml-auto size-4 transition-transform duration-200', open && 'rotate-180')} />
      </button>
      {open && (
        <ol
          id={`${id}-log`}
          ref={listRef}
          aria-label="Protokoll der Analyse"
          className="max-h-44 overflow-y-auto border-t border-line bg-bg/40 px-5 py-2 font-mono text-2xs leading-5"
        >
          {log.length === 0 && <li className="text-fg-subtle">Noch keine Einträge.</li>}
          {log.map((l, i) => (
            <li key={i} className="flex gap-3">
              <span className="shrink-0 tabular-nums text-fg-subtle">{formatClock(l.ts)}</span>
              <span className={cn('min-w-0 break-words', LEVEL_CLASS[l.level])}>{l.text}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
