/**
 * Kontextmenü der Bauteiltabelle (Rechtsklick bzw. Kontextmenü-Taste/⇧F10 auf einer Zeile): Details, Wert der
 * angeklickten Zelle bearbeiten (wie F2), Datenblatt, Teilenummer kopieren, Duplizieren, Texte neu erzeugen, Löschen –
 * bei einer Mehrfachauswahl die Aktionen für die Auswahl. AG Grid Community hat kein eigenes Kontextmenü; die Zeile wird über `row-id` (= Teilenummer) bestimmt.
 * Auf Kopfzeile oder Leerraum öffnet sich nur etwas, wenn eine Auswahl besteht (dann deren Aktionen).
 */
import { Copy, CopyPlus, ExternalLink, PanelRight, Pencil, PencilLine, RefreshCw, Trash2 } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { PART_NUMBER, type PartRow } from '@/api/parts'
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuLabel,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui'
import { formatNumber } from '@/lib/format'
import { DATASHEET } from '../model/fields'

export interface RowContextMenuProps {
  children: ReactNode
  /** Zeile zu einem Element der Tabelle (null = Kopf, Leerraum, nicht geladen) */
  resolveRow: (target: HTMLElement) => PartRow | null
  /** Zelle zu einem Element der Tabelle (Spalte, Beschriftung, bearbeitbar) */
  resolveCell?: (target: HTMLElement) => { column: string; label: string; editable: boolean } | null
  /** Aktuelle Mehrfachauswahl (Teilenummern) und Anzahl (bei „alle Treffer“ die Trefferzahl) */
  selectedPns: ReadonlySet<string>
  selectionCount: number
  onOpen: (row: PartRow) => void
  /** Wert einer Zelle in der Tabelle bearbeiten (wie F2) */
  onEditCell?: (row: PartRow, column: string) => void
  onDatasheet: (row: PartRow) => void
  onDuplicate: (rows: PartRow[] | 'selection') => void
  onRegenerate: (row: PartRow) => void
  onBulkEdit: () => void
  onDelete: (rows: PartRow[] | 'selection') => void
}

export function RowContextMenu({
  children,
  resolveRow,
  resolveCell,
  selectedPns,
  selectionCount,
  onOpen,
  onEditCell,
  onDatasheet,
  onDuplicate,
  onRegenerate,
  onBulkEdit,
  onDelete,
}: RowContextMenuProps) {
  const [row, setRow] = useState<PartRow | null>(null)
  const [cell, setCell] = useState<{ column: string; label: string; editable: boolean } | null>(null)
  /** „… bearbeiten“ gewählt: der Editor startet erst, wenn das Menü zu ist – sonst holt das Menü den Fokus zurück */
  const pendingEdit = useRef<{ row: PartRow; column: string } | null>(null)
  const pn = row ? String(row[PART_NUMBER] ?? '') : ''
  const inSelection = Boolean(pn) && selectedPns.has(pn) && selectionCount > 1

  return (
    <ContextMenu>
      <ContextMenuTrigger
        asChild
        onContextMenu={(e) => {
          const hit = resolveRow(e.target as HTMLElement)
          // ohne Zeile und ohne Auswahl gibt es nichts anzubieten – kein leeres Menü
          if (!hit && selectionCount === 0) {
            e.preventDefault()
            return
          }
          setRow(hit)
          setCell(hit ? (resolveCell?.(e.target as HTMLElement) ?? null) : null)
        }}
      >
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent
        className="w-64"
        onCloseAutoFocus={(e) => {
          const edit = pendingEdit.current
          if (!edit || !onEditCell) return
          pendingEdit.current = null
          e.preventDefault() // Fokus nicht an die Tabelle zurückgeben – er gehört gleich dem Editor
          onEditCell(edit.row, edit.column)
        }}
      >
        {!row || inSelection ? (
          <>
            <ContextMenuLabel>{selectionCount === 1 ? '1 ausgewähltes Bauteil' : `${formatNumber(selectionCount)} ausgewählte Bauteile`}</ContextMenuLabel>
            <ContextMenuItem icon={<PencilLine />} onSelect={onBulkEdit}>
              Gemeinsam bearbeiten …
            </ContextMenuItem>
            <ContextMenuItem icon={<CopyPlus />} onSelect={() => onDuplicate('selection')}>
              Duplizieren …
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem icon={<Trash2 />} destructive hotkey="delete" onSelect={() => onDelete('selection')}>
              Auswahl löschen …
            </ContextMenuItem>
          </>
        ) : (
          <>
            <ContextMenuLabel className="mono normal-case tracking-normal">{pn}</ContextMenuLabel>
            <ContextMenuItem icon={<PanelRight />} hotkey="enter" onSelect={() => onOpen(row)}>
              Details öffnen
            </ContextMenuItem>
            {cell?.editable && onEditCell && (
              <ContextMenuItem icon={<Pencil />} hotkey="f2" onSelect={() => (pendingEdit.current = { row, column: cell.column })}>
                „{cell.label}“ bearbeiten
              </ContextMenuItem>
            )}
            <ContextMenuItem icon={<ExternalLink />} disabled={!row[DATASHEET]} onSelect={() => onDatasheet(row)}>
              Datenblatt öffnen
            </ContextMenuItem>
            <ContextMenuItem
              icon={<Copy />}
              onSelect={() => {
                void navigator.clipboard
                  ?.writeText(pn)
                  .then(() => toast.success('Teilenummer kopiert', { description: pn, duration: 1600 }))
                  .catch(() => toast.error('Kopieren nicht möglich'))
              }}
            >
              Teilenummer kopieren
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem icon={<CopyPlus />} onSelect={() => onDuplicate([row])}>
              Duplizieren …
            </ContextMenuItem>
            <ContextMenuItem icon={<RefreshCw />} onSelect={() => onRegenerate(row)}>
              Texte neu erzeugen
            </ContextMenuItem>
            <ContextMenuSeparator />
            <ContextMenuItem icon={<Trash2 />} destructive hotkey="delete" onSelect={() => onDelete([row])}>
              Löschen …
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  )
}
