/**
 * Export-Menü: XLSX oder CSV der aktuellen Tabelle – Suche, Filter, Sortierung gelten; wahlweise nur die Auswahl
 * bzw. nur sichtbare Spalten. Die Ausführung übernimmt `useExport` (Speichern-Dialog bzw. Download; sehr große
 * Auswahl und Excel-Exporte über 5.000 Zeilen als Job in den Ordner „Exports“ – das Menü sagt es vorher).
 */
import { Download, FileSpreadsheet, FileText } from 'lucide-react'
import { useState } from 'react'
import type { ExportFormat } from '@/api/parts'
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { useNativeBridge } from '@/lib/native'
import { LARGE_XLSX_ROWS } from '../model/useExport'

export interface ExportMenuProps {
  total: number | null
  /** Anzahl ausgewählter Bauteile (0 = keine Auswahl) */
  selectionCount: number
  /** Alle Treffer ausgewählt – dann gilt ohnehin die ganze Abfrage */
  allMatching: boolean
  onExport: (format: ExportFormat, opts: { onlySelection: boolean; visibleOnly: boolean }) => void
  compact?: boolean
}

export function ExportMenu({ total, selectionCount, allMatching, onExport, compact }: ExportMenuProps) {
  const native = useNativeBridge()
  const [onlySelection, setOnlySelection] = useState(true)
  const [visibleOnly, setVisibleOnly] = useState(true)
  const useSelection = onlySelection && selectionCount > 0 && !allMatching
  const count = useSelection ? selectionCount : total
  const run = (format: ExportFormat) => onExport(format, { onlySelection: useSelection, visibleOnly })

  return (
    <DropdownMenu>
      <Tooltip content="Exportieren" disabled={!compact}>
        <DropdownMenuTrigger asChild>
          {/* Name = sichtbarer Text („Export“); nur als Symbolknopf trägt er eine eigene Beschriftung */}
          <Button variant="ghost" size="sm" leftIcon={<Download />} aria-label={compact ? 'Exportieren' : undefined} iconOnly={compact}>
            {!compact && 'Export'}
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel>{count === null ? 'Exportieren' : `${plural(count, 'Bauteil', 'Bauteile')} exportieren`}</DropdownMenuLabel>
        <DropdownMenuItem
          icon={<FileSpreadsheet />}
          description={
            count !== null && count > LARGE_XLSX_ROWS
              ? 'Läuft im Hintergrund · Datei im Ordner „Exports“ der Bibliothek'
              : native.canSaveFile
                ? 'Speichern unter … · mit Kopfzeile und Spaltenbreiten'
                : 'Mit Kopfzeile und Spaltenbreiten'
          }
          onSelect={() => run('xlsx')}
        >
          Excel-Datei (XLSX)
        </DropdownMenuItem>
        <DropdownMenuItem icon={<FileText />} description="Semikolon-getrennt, UTF‑8" onSelect={() => run('csv')}>
          CSV-Datei
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        {selectionCount > 0 && !allMatching && (
          <DropdownMenuCheckboxItem
            checked={onlySelection}
            onCheckedChange={(v) => setOnlySelection(v === true)}
            onSelect={(e) => e.preventDefault()}
          >
            Nur Auswahl ({formatNumber(selectionCount)})
          </DropdownMenuCheckboxItem>
        )}
        <DropdownMenuCheckboxItem checked={visibleOnly} onCheckedChange={(v) => setVisibleOnly(v === true)} onSelect={(e) => e.preventDefault()}>
          Nur sichtbare Spalten
        </DropdownMenuCheckboxItem>
        <p className="px-2 pb-1.5 pt-1 text-2xs leading-snug text-fg-subtle">Suche, Filter und Sortierung der Tabelle gelten auch für den Export.</p>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
