import { metadataLabel, useI18n } from '@/lib/i18n'
/**
 * Darstellung der Tabelle: Zeilenhöhe und Spaltenwahl (Spalten nach Gruppen ein-/ausblenden, suchen, auf Standard
 * zurücksetzen – der Zustand wird gespeichert).
 */
import { Columns3, RotateCcw, Rows3, Rows4, Search } from 'lucide-react'
import { useMemo, useState, type RefObject } from 'react'
import type { CategoryDef } from '@/api/library'
import type { GridDensity } from '@/components/grid/theme'
import { Button, Checkbox, Popover, PopoverContent, PopoverTrigger, SegmentedControl, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { groupFields, PN } from '../model/fields'
import type { PartsGridHandle } from '../grid/PartsGrid'

export function ColumnChooser({
  category,
  grid,
  compact,
  density,
  onDensityChange,
}: {
  category: CategoryDef
  grid: RefObject<PartsGridHandle | null>
  compact?: boolean
  density: GridDensity
  onDensityChange: (density: GridDensity) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [visible, setVisible] = useState<Record<string, boolean>>({})
  const [query, setQuery] = useState('')
  const groups = useMemo(() => groupFields(category.fields, t), [category, t])
  const read = () => setVisible(Object.fromEntries((grid.current?.getColumns() ?? []).map((c) => [c.colId, c.visible])))
  const shown = Object.values(visible).filter(Boolean).length
  const q = query.trim().toLowerCase()

  const toggle = (column: string, on: boolean) => {
    grid.current?.setColumnVisible(column, on)
    setVisible((v) => ({ ...v, [column]: on }))
  }

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o) {
          read()
          setQuery('')
        }
      }}
    >
      <Tooltip content={t("Spalten ein- und ausblenden")} disabled={!compact}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="sm" leftIcon={<Columns3 />} aria-label={t("Spalten")} iconOnly={compact}>
            {!compact && t("Spalten")}
          </Button>
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent align="end" aria-label={t("Darstellung und Spalten")} className="w-80 p-0">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2.5">
          <span aria-hidden className="text-xs font-medium text-fg-muted">
            {t("Zeilenhöhe")}
          </span>
          <SegmentedControl<GridDensity>
            size="sm"
            aria-label={t("Zeilenhöhe")}
            value={density}
            onValueChange={onDensityChange}
            options={[
              { value: 'compact', icon: <Rows4 />, label: t("Kompakt") },
              { value: 'comfortable', icon: <Rows3 />, label: t("Komfortabel") },
            ]}
          />
        </div>
        <div className="flex items-center gap-2 border-b border-line px-3 py-2.5">
          <Search aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("Spalte suchen …")}
            aria-label={t("Spalte suchen")}
            className="h-6 min-w-0 flex-1 bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle"
          />
          <span className="text-2xs tabular-nums text-fg-subtle">{shown}  {t("sichtbar")}</span>
        </div>
        <div className="max-h-[min(24rem,60vh)] overflow-y-auto px-1.5 py-1.5">
          {groups.map((g) => {
            const fields = g.fields.filter((f) => !q || `${metadataLabel(f.label, t)} ${f.label} ${f.column}`.toLowerCase().includes(q))
            if (!fields.length) return null
            return (
              <div key={g.id} className="mb-1.5 last:mb-0">
                <div className="micro-label px-2 pb-1 pt-1.5">{metadataLabel(g.label, t)}</div>
                {fields.map((f) => {
                  const locked = f.column === PN
                  return (
                    <label
                      key={f.column}
                      className={cn(
                        'flex h-8 cursor-pointer items-center gap-2.5 rounded-control px-2 text-ui hover:bg-surface-2',
                        locked && 'cursor-default opacity-70',
                      )}
                    >
                      <Checkbox
                        checked={visible[f.column] ?? false}
                        disabled={locked}
                        onCheckedChange={(on) => toggle(f.column, on === true)}
                        aria-label={metadataLabel(f.label, t)}
                      />
                      <span className="min-w-0 flex-1 truncate text-fg">{metadataLabel(f.label, t)}</span>
                      {f.unit && <span className="mono text-2xs text-fg-subtle">{f.unit}</span>}
                      {f.system && <span className="text-2xs text-fg-subtle">System</span>}
                    </label>
                  )
                })}
              </div>
            )
          })}
        </div>
        <div className="flex items-center justify-between gap-2 border-t border-line bg-surface-2/40 px-3 py-2">
          <Button
            variant="ghost"
            size="xs"
            onClick={() => {
              for (const f of category.fields) if (!visible[f.column]) grid.current?.setColumnVisible(f.column, true)
              read()
            }}
          >
            {t("Alle einblenden")}
          </Button>
          <Button
            variant="ghost"
            size="xs"
            leftIcon={<RotateCcw />}
            onClick={() => {
              grid.current?.resetColumns()
              read()
            }}
          >
            {t("Standard wiederherstellen")}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}
