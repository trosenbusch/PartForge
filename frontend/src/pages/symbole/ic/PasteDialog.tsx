/**
 * „Pinliste einfügen“: Tabelle aus Excel oder dem Datenblatt einfügen (Strg+V), Spalten werden erkannt
 * (Nummer, Name, Typ, Beschreibung …) und lassen sich je Spalte anders zuordnen („Nummer ⇄ Name“ für Tabellen,
 * deren Signalnamen wie Kugelnummern aussehen, z. B. PA0). Live-Vorschau der erkannten Pins mit Hinweisen;
 * ersetzen oder anhängen.
 */
import { ArrowLeftRight, ClipboardPaste, RotateCcw, TriangleAlert } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  SegmentedControl,
  Select,
  Textarea,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { ElectricalDot, OverbarName } from '../shared'
import {
  electricalShort,
  PASTE_COLUMN_LABEL,
  parsedToRow,
  parsePinTable,
  SEPARATOR_LABEL,
  type PasteColumn,
  type PinRow,
} from './pins'

export interface PasteDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Vorbelegter Text (z. B. Strg+V im Editor) */
  initialText?: string
  existing: readonly PinRow[]
  onApply: (rows: PinRow[], mode: 'replace' | 'append') => void
}

const PLACEHOLDER = `1\tVIN\tVersorgung
2\tGND\tMasse
3\tEN\tEingang
4\t/RESET\tAusgang, Open Drain`

const PREVIEW_LIMIT = 150
/** So viele Spalten lassen sich zuordnen (weitere werden ignoriert) */
const MAPPABLE_COLUMNS = 8
const IGNORE = 'ignorieren'
const COLUMN_OPTIONS: { value: PasteColumn | typeof IGNORE; label: string }[] = [
  ...(Object.keys(PASTE_COLUMN_LABEL) as PasteColumn[]).map((c) => ({ value: c, label: PASTE_COLUMN_LABEL[c] })),
  { value: IGNORE, label: 'Ignorieren' },
]

/** Spaltenzuordnung: Erkennung oder eigene Wahl (gilt, solange die Spaltenzahl gleich bleibt) */
function ColumnMapping({
  mapping,
  sample,
  custom,
  onChange,
  onReset,
}: {
  mapping: readonly (PasteColumn | null)[]
  sample: readonly string[]
  custom: boolean
  onChange: (next: (PasteColumn | null)[]) => void
  onReset: () => void
}) {
  const shown = mapping.slice(0, MAPPABLE_COLUMNS)
  const set = (i: number, value: PasteColumn | null) => {
    const next = shown.map((c, j) => (j !== i && value !== null && c === value ? null : c))
    next[i] = value
    onChange(next)
  }
  const di = shown.indexOf('designator')
  const ni = shown.indexOf('name')
  const swap = () => {
    if (di < 0 || ni < 0) return
    const next = [...shown]
    next[di] = 'name'
    next[ni] = 'designator'
    onChange(next)
  }
  return (
    <section aria-label="Spalten zuordnen" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-ui font-medium text-fg">Spalten</span>
        <span className="text-xs text-fg-muted">{custom ? 'eigene Zuordnung' : 'automatisch erkannt'}</span>
        <div className="ml-auto flex items-center gap-1">
          <Button size="xs" variant="ghost" leftIcon={<ArrowLeftRight />} disabled={di < 0 || ni < 0} onClick={swap}>
            Nummer ⇄ Name
          </Button>
          {custom && (
            <Button size="xs" variant="ghost" leftIcon={<RotateCcw />} onClick={onReset}>
              Erkennung
            </Button>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {shown.map((c, i) => (
          <div key={i} className="flex w-36 min-w-0 flex-col gap-1">
            <Select<PasteColumn | typeof IGNORE>
              size="sm"
              aria-label={`Spalte ${i + 1}${sample[i] ? ` (z. B. ${sample[i]})` : ''}`}
              value={c ?? IGNORE}
              onValueChange={(v) => set(i, v === IGNORE ? null : v)}
              prefix={<span className="mono text-2xs font-semibold text-fg-subtle">{i + 1}</span>}
              options={COLUMN_OPTIONS}
              className={cn(!c && 'text-fg-subtle')}
            />
            <span className="mono truncate px-1 text-2xs text-fg-subtle" title={sample[i]}>
              {sample[i] ? `„${sample[i]}“` : '–'}
            </span>
          </div>
        ))}
      </div>
    </section>
  )
}

function PasteDialogBody({ initialText, existing, onApply, onClose }: Omit<PasteDialogProps, 'open' | 'onOpenChange'> & { onClose: () => void }) {
  const [text, setText] = useState(initialText ?? '')
  const [convert, setConvert] = useState(true)
  const [mode, setMode] = useState<'replace' | 'append'>(existing.length ? 'append' : 'replace')
  const [custom, setCustom] = useState<{ count: number; mapping: (PasteColumn | null)[] } | null>(null)
  const detected = useMemo(() => parsePinTable(text, { convertActiveLow: convert }), [text, convert])
  // eigene Zuordnung nur, solange die eingefügte Tabelle gleich viele Spalten hat
  const customMapping = custom && custom.count === detected.columnCount ? custom.mapping : null
  const result = useMemo(
    () => (customMapping ? parsePinTable(text, { convertActiveLow: convert, mapping: customMapping }) : detected),
    [customMapping, detected, text, convert],
  )

  const duplicates = useMemo(() => {
    const seen = new Map<string, number>()
    const base = mode === 'append' ? existing.map((p) => p.designator.trim().toUpperCase()) : []
    for (const d of base) seen.set(d, (seen.get(d) ?? 0) + 1)
    for (const p of result.pins) seen.set(p.designator.toUpperCase(), (seen.get(p.designator.toUpperCase()) ?? 0) + 1)
    return [...seen.entries()].filter(([, n]) => n > 1).map(([d]) => d)
  }, [result.pins, existing, mode])

  const guessed = result.pins.filter((p) => p.electricalSource !== 'column').length
  const count = result.pins.length

  const readClipboard = async () => {
    try {
      const clip = await navigator.clipboard.readText()
      if (clip) setText(clip)
    } catch {
      // Zugriff verweigert – Strg+V im Textfeld funktioniert immer
    }
  }

  return (
    <>
      <DialogBody className="flex flex-col gap-4">
        <Field
          label="Tabelle"
          hint="Strg+V"
          help="Ohne Kopfzeile gilt: Nummer, Name, Typ, Beschreibung – die Zuordnung lässt sich darunter je Spalte ändern. „5, 6“ und „5–8“ ergeben mehrere Pins."
        >
          <Textarea
            mono
            rows={7}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={PLACEHOLDER}
            spellCheck={false}
            className="min-h-36 whitespace-pre text-xs leading-5"
          />
        </Field>
        {detected.columnCount > 1 && (
          <ColumnMapping
            mapping={result.mapping}
            sample={result.sample}
            custom={customMapping !== null}
            onChange={(mapping) => setCustom({ count: detected.columnCount, mapping })}
            onReset={() => setCustom(null)}
          />
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Checkbox
            checked={convert}
            onCheckedChange={(v) => setConvert(v === true)}
            label="Low-aktive Namen umwandeln"
            description="/RESET, RESET#, nRESET → Überstrich wie in Altium"
          />
          <Button size="sm" variant="ghost" leftIcon={<ClipboardPaste />} onClick={() => void readClipboard()}>
            Aus der Zwischenablage
          </Button>
        </div>

        {count > 0 && (
          <section aria-label="Erkannte Pins" className="overflow-hidden rounded-card border border-line">
            <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2/50 px-3 py-2 text-xs">
              <span className="font-semibold text-fg">{plural(count, 'Pin', 'Pins')} erkannt</span>
              <Badge size="sm">{SEPARATOR_LABEL[result.separator]}</Badge>
              {result.headerSkipped && <Badge size="sm">Kopfzeile erkannt</Badge>}
            </div>
            <div className="max-h-56 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="sticky top-0 bg-surface text-left text-2xs uppercase tracking-[0.06em] text-fg-subtle">
                  <tr>
                    <th scope="col" className="w-16 border-b border-line px-3 py-1.5 font-semibold">
                      Nr.
                    </th>
                    <th scope="col" className="border-b border-line px-3 py-1.5 font-semibold">
                      Name
                    </th>
                    <th scope="col" className="w-36 border-b border-line px-3 py-1.5 font-semibold">
                      Typ
                    </th>
                    <th scope="col" className="border-b border-line px-3 py-1.5 font-semibold">
                      Beschreibung
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {result.pins.slice(0, PREVIEW_LIMIT).map((p, i) => (
                    <tr key={`${p.designator}-${i}`} className={cn(duplicates.includes(p.designator.toUpperCase()) && 'bg-danger/8')}>
                      <td className="mono border-b border-line px-3 py-1 font-semibold text-fg">{p.designator}</td>
                      <td className="mono border-b border-line px-3 py-1 text-fg">
                        <OverbarName value={p.name} placeholder="–" />
                      </td>
                      <td className="border-b border-line px-3 py-1">
                        <span className={cn('flex items-center gap-1.5', p.electricalSource === 'column' ? 'text-fg' : 'text-fg-muted')}>
                          <ElectricalDot type={p.electrical} />
                          {electricalShort(p.electrical)}
                          {p.electricalSource === 'unknown' && <span className="text-warning-text">(„{p.rawType}“?)</span>}
                          {p.electricalSource === 'guess' && <span className="text-fg-subtle">· geschätzt</span>}
                        </span>
                      </td>
                      <td className="max-w-0 truncate border-b border-line px-3 py-1 text-fg-muted">{p.description || '–'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {count > PREVIEW_LIMIT && (
                <p className="px-3 py-2 text-2xs text-fg-subtle">… und {formatNumber(count - PREVIEW_LIMIT)} weitere</p>
              )}
            </div>
          </section>
        )}

        {(duplicates.length > 0 || result.ignoredLines.length > 0 || result.unknownTypes.length > 0) && (
          <ul className="space-y-1 text-xs text-fg-muted" aria-label="Hinweise zum Einfügen">
            {duplicates.length > 0 && (
              <li className="flex items-start gap-1.5 text-danger-text">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                Doppelte Pin-Nummern: {duplicates.slice(0, 10).join(', ')}
                {duplicates.length > 10 ? ' …' : ''} – bitte nach dem Übernehmen korrigieren.
              </li>
            )}
            {result.ignoredLines.length > 0 && (
              <li className="flex items-start gap-1.5">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning-text" />
                {result.ignoredLines.length === 1 ? 'Zeile' : 'Zeilen'} {result.ignoredLines.slice(0, 12).join(', ')}
                {result.ignoredLines.length > 12 ? ' …' : ''} ohne erkennbare Pin-Nummer übersprungen.
              </li>
            )}
            {result.unknownTypes.length > 0 && (
              <li className="flex items-start gap-1.5">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning-text" />
                Unbekannte Typen ({result.unknownTypes.slice(0, 6).map((t) => `„${t}“`).join(', ')}) – aus dem Namen geschätzt, sonst Passiv.
              </li>
            )}
          </ul>
        )}
        {count > 0 && guessed > 0 && !result.unknownTypes.length && !result.columns.includes('electrical') && (
          <p className="text-xs text-fg-subtle">Ohne Typ-Spalte: Versorgung und Masse werden am Namen erkannt, alle anderen Pins sind Passiv.</p>
        )}
      </DialogBody>
      <DialogFooter className="justify-between">
        {existing.length > 0 ? (
          <SegmentedControl
            size="sm"
            aria-label="Vorhandene Pins"
            value={mode}
            onValueChange={setMode}
            options={[
              { value: 'append', label: 'Anhängen' },
              { value: 'replace', label: `${formatNumber(existing.length)} ersetzen` },
            ]}
          />
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onClose}>
            Abbrechen
          </Button>
          <Button
            variant="primary"
            disabled={count === 0}
            onClick={() => {
              onApply(result.pins.map(parsedToRow), mode)
              onClose()
            }}
          >
            {count ? `${plural(count, 'Pin', 'Pins')} übernehmen` : 'Pins übernehmen'}
          </Button>
        </div>
      </DialogFooter>
    </>
  )
}

export function PasteDialog({ open, onOpenChange, initialText, existing, onApply }: PasteDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          icon={<ClipboardPaste />}
          title="Pinliste einfügen"
          description="Aus Excel, einer CSV-Datei oder der Pin-Tabelle eines Datenblatts kopieren und hier einfügen."
        />
        {open && (
          <PasteDialogBody key={initialText ?? ''} initialText={initialText} existing={existing} onApply={onApply} onClose={() => onOpenChange(false)} />
        )}
      </DialogContent>
    </Dialog>
  )
}
