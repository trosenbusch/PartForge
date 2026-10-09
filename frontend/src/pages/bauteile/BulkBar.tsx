/**
 * Leiste für die Mehrfachauswahl (schwebt über der Tabelle): Anzahl, „Alle Treffer auswählen“, Bearbeiten,
 * Duplizieren, Exportieren, Löschen. Esc hebt die Auswahl auf.
 */
import { AnimatePresence, motion } from 'motion/react'
import { CopyPlus, Download, PencilLine, Trash2, X } from 'lucide-react'
import { useJobDock } from '@/app/stores'
import type { ReactNode } from 'react'
import { Button, Kbd, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'

export interface BulkBarProps {
  count: number
  total: number | null
  allMatching: boolean
  /** Alle geladenen Zeilen sind ausgewählt, es gibt aber mehr Treffer */
  canSelectAllMatching: boolean
  onSelectAllMatching: () => void
  onEdit: () => void
  onDuplicate: () => void
  onExport: () => void
  onDelete: () => void
  onClear: () => void
  /** Wenig Platz: Aktionen nur als Symbole (mit Tooltip) */
  compact?: boolean
}

export function BulkBar({
  count,
  total,
  allMatching,
  canSelectAllMatching,
  onSelectAllMatching,
  onEdit,
  onDuplicate,
  onExport,
  onDelete,
  onClear,
  compact = false,
}: BulkBarProps) {
  const shown = allMatching && total !== null ? total : count
  // Das Job-Dock der Shell liegt unten rechts – die Leiste weicht nach oben aus, solange es sichtbar ist
  const dockVisible = useJobDock((s) => s.visible)
  const dockHeight = useJobDock((s) => s.height)
  const bottom = dockVisible ? Math.max(16, dockHeight - 4) : 16
  return (
    <AnimatePresence>
      {shown > 0 && (
        <motion.div
          key="bulk"
          role="group"
          aria-label="Auswahl bearbeiten"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 12, scale: 0.98, transition: { duration: 0.14 } }}
          transition={{ type: 'spring', stiffness: 420, damping: 34 }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.stopPropagation()
              onClear()
            }
          }}
          style={{ bottom }}
          className="glass pointer-events-auto absolute left-1/2 z-sticky flex max-w-[calc(100%-2rem)] -translate-x-1/2 items-center gap-1 rounded-panel py-1.5 pl-3 pr-1.5 shadow-pop"
        >
          <span className="flex items-center gap-2 pr-2 text-ui" aria-live="polite">
            <span className="flex h-5 min-w-5 items-center justify-center rounded-full bg-gradient-forge px-1.5 text-2xs font-semibold tabular-nums text-on-accent">
              {formatNumber(shown)}
            </span>
            <span className="whitespace-nowrap font-medium text-fg">
              {allMatching ? (compact ? 'alle Treffer' : 'alle Treffer ausgewählt') : 'ausgewählt'}
            </span>
          </span>
          {canSelectAllMatching && !allMatching && total !== null && (
            <Button variant="link" size="sm" onClick={onSelectAllMatching} className="mr-1 whitespace-nowrap">
              {compact ? `Alle ${formatNumber(total)}` : `Alle ${formatNumber(total)} auswählen`}
            </Button>
          )}
          <span aria-hidden className="mx-1 h-5 w-px bg-line-strong" />
          <BarAction compact={compact} icon={<PencilLine />} label="Bearbeiten" onClick={onEdit} />
          <BarAction compact={compact} icon={<CopyPlus />} label="Duplizieren" onClick={onDuplicate} disabled={allMatching && shown > 200} />
          <BarAction compact={compact} icon={<Download />} label="Exportieren" onClick={onExport} />
          <BarAction compact={compact} icon={<Trash2 />} label="Löschen" onClick={onDelete} danger hotkey="delete" />
          <span aria-hidden className="mx-1 h-5 w-px bg-line-strong" />
          <Tooltip content={<span className="flex items-center gap-2">Auswahl aufheben <Kbd size="xs">Esc</Kbd></span>}>
            <Button variant="ghost" size="sm" iconOnly aria-label="Auswahl aufheben" onClick={onClear}>
              <X />
            </Button>
          </Tooltip>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function BarAction({
  compact,
  icon,
  label,
  onClick,
  disabled,
  danger,
  hotkey,
}: {
  compact: boolean
  icon: ReactNode
  label: string
  onClick: () => void
  disabled?: boolean
  danger?: boolean
  hotkey?: string
}) {
  const button = (
    <Button
      variant="ghost"
      size="sm"
      leftIcon={icon}
      iconOnly={compact}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className={cn(danger && 'text-danger-text hover:text-danger-text')}
    >
      {!compact && label}
    </Button>
  )
  return compact || hotkey ? (
    <Tooltip content={danger ? `${label} (Auswahl)` : label} hotkey={hotkey}>
      {button}
    </Tooltip>
  ) : (
    button
  )
}
