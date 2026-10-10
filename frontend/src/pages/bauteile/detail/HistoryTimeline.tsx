import { metadataLabel, t, tc, useI18n } from '@/lib/i18n'
/**
 * Änderungsverlauf eines Bauteils (`GET /api/parts/{table}/{pn}/history`, neueste zuerst): wer, wann, welche
 * Felder von → nach. Anlegen/Import mit vielen Feldern ist eingeklappt.
 */
import { motion } from 'motion/react'
import { ArrowRight, ArchiveRestore, ChevronDown, FileUp, Layers, Pencil, Plus, Settings2, Trash2, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { FieldDef } from '@/api/library'
import { usePartHistory, type HistoryAction, type PartHistoryEntry } from '@/api/parts'
import { errorMessage } from '@/api/client'
import { Callout, EmptyState, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatRelativeTime, plural } from '@/lib/format'
import { displayValue } from '../model/fields'

const ACTION: Record<HistoryAction, { label: string; icon: LucideIcon; tone: string }> = {
  create: { get label() { return t("Angelegt") }, icon: Plus, tone: 'text-success-text' },
  import: { get label() { return t("Importiert") }, icon: FileUp, tone: 'text-info-text' },
  update: { get label() { return t("Geändert") }, icon: Pencil, tone: 'text-accent-text' },
  bulk_update: { get label() { return t("Massenbearbeitung") }, icon: Layers, tone: 'text-accent-text' },
  delete: { get label() { return t("Gelöscht") }, icon: Trash2, tone: 'text-danger-text' },
  schema: { get label() { return t("Kategorie geändert") }, icon: Settings2, tone: 'text-fg-muted' },
  restore: { get label() { return t("Wiederhergestellt") }, icon: ArchiveRestore, tone: 'text-success-text' },
}

/** Einträge mit allen Feldern (Anlegen, Import, Wiederherstellen, Löschen) – eingeklappt starten */
const FULL_SNAPSHOT = new Set<HistoryAction>(['create', 'import', 'restore', 'delete'])

const HIDDEN = new Set(['PF Modified', 'PF Author', 'PF Created'])
const COLLAPSE_AFTER = 4

interface Segment {
  text: string
  changed: boolean
}

/**
 * Wortweiser Vergleich langer Texte: gemeinsamer Anfang und gemeinsames Ende bleiben ruhig, nur der geänderte
 * Mittelteil wird hervorgehoben („RES 0603 10kΩ ±1% 0.1W“ → „… abc …“).
 */
function wordDiff(before: string, after: string): { before: Segment[]; after: Segment[] } {
  const a = before.split(/(\s+)/)
  const b = after.split(/(\s+)/)
  let start = 0
  while (start < a.length && start < b.length && a[start] === b[start]) start++
  let end = 0
  while (end < a.length - start && end < b.length - start && a[a.length - 1 - end] === b[b.length - 1 - end]) end++
  const seg = (parts: string[]): Segment[] =>
    [
      { text: parts.slice(0, start).join(''), changed: false },
      { text: parts.slice(start, parts.length - end).join(''), changed: true },
      { text: parts.slice(parts.length - end).join(''), changed: false },
    ].filter((s) => s.text !== '')
  return { before: seg(a), after: seg(b) }
}

function Change({
  field,
  column,
  before,
  after,
  snapshot = false,
}: {
  field?: FieldDef
  column: string
  before: unknown
  after: unknown
  /** Nur den Wert zeigen (Stand beim Löschen) – kein „vorher → geleert“ */
  snapshot?: boolean
}) {
  const { t } = useI18n()
  const fmt = (v: unknown) => (v === null || v === undefined || v === '' ? null : displayValue(field, String(v)))
  if (snapshot) {
    const value = fmt(before ?? after)
    return (
      <li className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-2 text-xs">
        <span className="truncate text-fg-muted" title={column}>
          {metadataLabel(field?.label ?? column, t)}
        </span>
        {value !== null ? <span className="mono min-w-0 break-words text-fg">{value}</span> : <span className="text-fg-subtle">–</span>}
      </li>
    )
  }
  const b = fmt(before)
  const a = fmt(after)
  // Lange Texte (Beschreibung): untereinander, umbrechend und mit hervorgehobener Änderung – nichts abschneiden
  const long = (b?.length ?? 0) + (a?.length ?? 0) > 30
  if (long && b !== null && a !== null) {
    const diff = wordDiff(b, a)
    return (
      <li className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-2 text-xs">
        <span className="truncate text-fg-muted" title={column}>
          {metadataLabel(field?.label ?? column, t)}
        </span>
        <span className="flex min-w-0 flex-col gap-0.5">
          <span className="mono break-words text-fg-subtle">
            <span className="sr-only">{t("vorher:")} </span>
            {diff.before.map((s, i) =>
              s.changed ? (
                <del key={i} className="rounded-sm bg-danger/10 px-0.5 text-danger-text decoration-danger/60">
                  {s.text}
                </del>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
          </span>
          <span className="mono break-words text-fg">
            <span className="sr-only">{t("nachher:")} </span>
            {diff.after.map((s, i) =>
              s.changed ? (
                <ins key={i} className="rounded-sm bg-success/12 px-0.5 text-success-text no-underline">
                  {s.text}
                </ins>
              ) : (
                <span key={i}>{s.text}</span>
              ),
            )}
          </span>
        </span>
      </li>
    )
  }
  return (
    <li className="grid grid-cols-[minmax(0,7.5rem)_minmax(0,1fr)] gap-2 text-xs">
      <span className="truncate text-fg-muted" title={column}>
        {metadataLabel(field?.label ?? column, t)}
      </span>
      <span className="flex min-w-0 flex-wrap items-center gap-1.5">
        {b !== null && (
          <>
            <span className="mono max-w-full break-words text-fg-subtle line-through decoration-fg-subtle/50">{b}</span>
            <ArrowRight aria-label={t("zu")} className="size-3 shrink-0 text-fg-subtle" />
          </>
        )}
        {a !== null ? <span className="mono max-w-full break-words text-fg">{a}</span> : <span className="italic text-fg-subtle">{t("geleert")}</span>}
      </span>
    </li>
  )
}

function Entry({ entry, fields, last }: { entry: PartHistoryEntry; fields: Map<string, FieldDef>; last: boolean }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const meta = ACTION[entry.action] ?? ACTION.update
  const Icon = meta.icon
  const changes = Object.entries(entry.changes ?? {}).filter(([col]) => !HIDDEN.has(col)) as [string, unknown][]
  const pairs = changes.map(([col, v]) => {
    const [before, after] = Array.isArray(v) ? v : [null, v]
    return { col, before, after }
  })
  const collapsible = pairs.length > COLLAPSE_AFTER
  const shown = collapsible && !open ? pairs.slice(0, FULL_SNAPSHOT.has(entry.action) ? 0 : COLLAPSE_AFTER) : pairs
  /** Löschen: die Werte zum Zeitpunkt des Löschens (nicht „Wert → geleert“ je Feld) */
  const snapshot = entry.action === 'delete'
  const hidden = pairs.length - shown.length
  return (
    <li className="relative flex gap-3 pb-4 last:pb-0">
      {!last && <span aria-hidden className="absolute bottom-0 left-[13px] top-7 w-px bg-line-strong" />}
      <span
        aria-hidden
        className={cn('relative z-sticky flex size-7 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-2 [&_svg]:size-3.5', meta.tone)}
      >
        <Icon />
      </span>
      <div className="min-w-0 flex-1 pt-1">
        <div className="flex flex-wrap items-baseline gap-x-1.5 text-ui">
          <span className="font-medium text-fg">{metadataLabel(meta.label, t)}</span>
          {entry.author && <span className="text-fg-muted">{tc('author', 'von')} {entry.author}</span>}
          <Tooltip content={formatDateTime(entry.ts)}>
            <time dateTime={entry.ts} className="ml-auto shrink-0 cursor-default text-2xs text-fg-subtle">
              {formatRelativeTime(entry.ts)}
            </time>
          </Tooltip>
        </div>
        {shown.length > 0 && (
          <div className="mt-1.5 rounded-control border border-line bg-surface-2/40 px-2.5 py-2">
            {snapshot && (
              <div aria-hidden className="micro-label pb-1">
                {t("Werte beim Löschen")}
              </div>
            )}
            <ul aria-label={snapshot ? t("Werte beim Löschen") : undefined} className="flex flex-col gap-1">
              {shown.map((p) => (
                <Change key={p.col} column={p.col} field={fields.get(p.col)} before={p.before} after={p.after} snapshot={snapshot} />
              ))}
            </ul>
          </div>
        )}
        {collapsible && (
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            className="mt-1 flex items-center gap-1 rounded-sm text-xs text-fg-muted outline-none hover:text-fg focus-ring"
          >
            <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
            {open
              ? t("Weniger anzeigen")
              : shown.length === 0
                ? t("{1} anzeigen{2}", { 1: snapshot ? t("Werte beim Löschen") : plural(hidden, t("Feld"), t("Felder")), 2: snapshot ? ` (${plural(hidden, t("Feld"), t("Felder"))})` : '' })
                : t("{1} anzeigen", { 1: plural(hidden, t("weiteres Feld"), t("weitere Felder")) })}
          </button>
        )}
      </div>
    </li>
  )
}

export function HistoryTimeline({ table, pn, fields }: { table: string; pn: string; fields: FieldDef[] }) {
  const { t } = useI18n()
  const history = usePartHistory(table, pn)
  const byColumn = new Map(fields.map((f) => [f.column, f]))
  if (history.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-hidden>
        {Array.from({ length: 3 }, (_, i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="size-7 rounded-full" />
            <div className="flex flex-1 flex-col gap-2 pt-1">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-10" />
            </div>
          </div>
        ))}
      </div>
    )
  }
  if (history.isError) return <Callout tone="danger" title={t("Verlauf nicht verfügbar")}>{errorMessage(history.error)}</Callout>
  const entries = history.data ?? []
  if (!entries.length) {
    return <EmptyState size="sm" icon={<Pencil />} title={t("Noch keine Änderungen")} description={t("Änderungen an diesem Bauteil erscheinen hier mit Bearbeiter und Zeitpunkt.")} />
  }
  return (
    <motion.ol initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2 }} aria-label={t("Änderungsverlauf")}>
      {entries.map((e, i) => (
        <Entry key={e.id} entry={e} fields={byColumn} last={i === entries.length - 1} />
      ))}
    </motion.ol>
  )
}
