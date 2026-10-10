import { useI18n } from '@/lib/i18n'
import { Check, ChevronRight, Eye, TriangleAlert } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import type { VerifiedPart } from '@/api/altium'
import type { CategoryDef } from '@/api/library'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { isDescriptionParameter, parameterRows, type ParameterRow } from './model'

/** Comment, Beschreibung und die aufklappbare Parameterliste eines Bauteils (Zeile unter dem Ergebnis) */
export function PartTexts({ part: p, cat }: { part: VerifiedPart; cat: CategoryDef | undefined }) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const regionId = useId()
  const rows = useMemo(() => parameterRows(p), [p])
  if (!p.symbol_found) return null // Altium lieferte keinen Datensatz – nichts aus der Datenbank zu zeigen
  const descriptionDiff = (p.parameter_diffs ?? []).find((d) => isDescriptionParameter(d.parameter))
  const diffCount = rows.filter((r) => r.state === 'diff').length
  const checked = (p.parameters_checked ?? 0) > 0
  if (!p.comment && !p.description && !descriptionDiff && rows.length === 0) return null
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 flex-wrap items-start gap-x-6 gap-y-1 text-2xs leading-4">
        {p.comment && (
          <p className="flex min-w-0 items-center gap-1.5">
            <span className="text-fg-subtle">Comment</span>
            <span className="mono break-all font-medium text-fg">{p.comment}</span>
            {p.comment_visible === true && <VisibleMark />}
            {p.comment_visible === false && <span className="text-fg-subtle">{tr("(im Schaltplan ausgeblendet)")}</span>}
          </p>
        )}
        {(p.description || descriptionDiff) && (
          <p className="flex min-w-0 flex-[1_1_20rem] items-start gap-1.5">
            <span className="shrink-0 text-fg-subtle">{tr("Beschreibung")}</span>
            <span className="min-w-0 break-words">
              {descriptionDiff && <TriangleAlert aria-hidden className="mr-1 inline size-3 align-[-2px] text-warning" />}
              <span className={descriptionDiff ? 'text-warning-text' : 'text-fg-muted'}>{p.description || '–'}</span>
              {descriptionDiff && (
                <span className="text-fg-subtle">
                  {' '}
                  {tr("(in der Datenbank: ")}{descriptionDiff.database ? `„${descriptionDiff.database}“` : tr("leer")})
                </span>
              )}
            </span>
          </p>
        )}
        {rows.length > 0 && (
          <button
            type="button"
            aria-expanded={open}
            aria-controls={open ? regionId : undefined}
            onClick={() => setOpen((v) => !v)}
            className="flex shrink-0 items-center gap-1 rounded-sm font-medium text-fg-muted outline-none hover:text-fg focus-ring"
          >
            <ChevronRight aria-hidden className={cn('size-3 transition-transform duration-150', open && 'rotate-90')} />
            {plural(rows.length, 'Parameter', 'Parameter')}
            {checked ? (
              diffCount > 0 ? (
                <span className="text-warning-text">· {diffCount === 1 ? tr("1 weicht ab") : tr("{0} weichen ab", { "0": String(formatNumber(diffCount)) })}</span>
              ) : (
                <span className="font-normal text-fg-subtle">{tr("· wie in der Datenbank")}</span>
              )
            ) : (
              <span className="font-normal text-fg-subtle">{tr("· nicht verglichen")}</span>
            )}
          </button>
        )}
      </div>
      {open && <ParameterTable id={regionId} rows={rows} cat={cat} partNumber={p.part_number} />}
    </div>
  )
}

function VisibleMark() {
  const { t: tr } = useI18n()
  return (
    <span title={tr("Im Schaltplan sichtbar")} className="flex shrink-0">
      <Eye aria-hidden className="size-3 text-fg-subtle" />
      <span className="sr-only">{tr("(im Schaltplan sichtbar)")}</span>
    </span>
  )
}

function ParameterTable({ id, rows, cat, partNumber }: { id: string; rows: ParameterRow[]; cat: CategoryDef | undefined; partNumber: string }) {
  const { t: tr } = useI18n()
  const labels = useMemo(() => new Map((cat?.fields ?? []).map((f) => [f.column.trim().toLowerCase(), f.label] as const)), [cat])
  return (
    <div id={id} className="overflow-hidden rounded-control bg-surface-2/60">
      <table className="w-full table-fixed border-collapse text-left text-2xs leading-4">
        <caption className="sr-only">{tr("Parameter von ")}{partNumber} {tr(" in Altium, verglichen mit der Datenbank")}</caption>
        <thead>
          <tr className="text-fg-subtle">
            <th scope="col" className="w-[30%] px-3 py-1.5 font-medium">
              Parameter
            </th>
            <th scope="col" className="px-3 py-1.5 font-medium">
              {tr("In Altium")}</th>
            <th scope="col" className="w-[34%] px-3 py-1.5 font-medium">
              {tr("In der Datenbank")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const label = labels.get(r.name.trim().toLowerCase())
            return (
              <tr key={r.name} className={cn('border-t border-line/70 align-top', r.state === 'diff' && 'bg-warning/8')}>
                <th scope="row" className="min-w-0 px-3 py-1.5 font-normal text-fg">
                  <span className="flex min-w-0 items-center gap-1">
                    <span className="min-w-0 break-words">{r.name}</span>
                    {r.visible && <VisibleMark />}
                  </span>
                  {label && label !== r.name && <span className="block text-fg-subtle">{label}</span>}
                </th>
                <td
                  className={cn(
                    'min-w-0 break-words px-3 py-1.5',
                    r.altium === null ? 'text-fg-subtle' : r.state === 'diff' ? 'text-warning-text' : 'text-fg',
                  )}
                >
                  {r.altium ?? tr("fehlt")}
                </td>
                <td className="min-w-0 break-words px-3 py-1.5">
                  {r.state === 'same' ? (
                    <span className="flex items-center gap-1 text-fg-subtle">
                      <Check aria-hidden className="size-3 shrink-0 text-success" />
                      {tr("gleich")}</span>
                  ) : r.state === 'diff' ? (
                    <span className="flex items-start gap-1 text-warning-text">
                      <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0 text-warning" />
                      <span className="min-w-0">
                        <span className="sr-only">{tr("weicht ab: ")}</span>
                        {r.database === null ? tr("leer") : r.database}
                      </span>
                    </span>
                  ) : r.state === 'extra' ? (
                    <span className="text-fg-subtle">{tr("kein Datenbankfeld")}</span>
                  ) : (
                    <span className="text-fg-subtle">{tr("nicht verglichen")}</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
