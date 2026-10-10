import { useI18n } from '@/lib/i18n'
import { ArrowRight, Plus, X } from 'lucide-react'
import { Fragment, useId, useRef, useState, type ReactNode } from 'react'
import type { ConformRules } from '@/api/housestyle'
import { Button, IconButton, Input, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  cleanPrefix,
  cleanPrefixMap,
  FOOTPRINT_RULES,
  stableStringify,
  SYMBOL_RULES,
  type FootprintFlag,
  type Kind,
  type StyleInfo,
  type SymbolFlag,
} from './model'

export interface RulesEditorProps {
  rules: ConformRules
  onChange: (rules: ConformRules) => void
  /** Hausstil der Bibliothek (Werte in den Hilfetexten); `null` = noch nicht geladen */
  style: StyleInfo | null
  kinds: Kind[]
}

export function RulesEditor({ rules, onChange, style, kinds }: RulesEditorProps) {
  const { t: tr } = useI18n()
  const setSymbol = (key: SymbolFlag, on: boolean) => onChange({ ...rules, symbols: { ...rules.symbols, [key]: on } })
  const setFootprint = (key: FootprintFlag, on: boolean) =>
    onChange({ ...rules, footprints: { ...rules.footprints, [key]: on } })

  return (
    <>
      <RuleGroup title={tr("Symbole")} inactive={!kinds.includes('symbol')}>
        {SYMBOL_RULES.map((def) => (
          <Fragment key={def.key}>
            <Switch
              size="sm"
              label={def.label}
              description={def.help(style)}
              checked={rules.symbols[def.key]}
              onCheckedChange={(on) => setSymbol(def.key, on)}
            />
            {def.key === 'prefix' && (
              <PrefixMapEditor
                value={rules.symbols.prefix_map}
                disabled={!rules.symbols.prefix}
                onChange={(prefix_map) => onChange({ ...rules, symbols: { ...rules.symbols, prefix_map } })}
              />
            )}
          </Fragment>
        ))}
      </RuleGroup>
      <RuleGroup title="Footprints" inactive={!kinds.includes('footprint')}>
        {FOOTPRINT_RULES.map((def) =>
          def.parent ? (
            <div key={def.key} className="ml-1 border-l border-line pl-3">
              <Switch
                size="sm"
                label={def.label}
                description={def.help(style)}
                checked={rules.footprints[def.key]}
                disabled={!rules.footprints[def.parent]}
                onCheckedChange={(on) => setFootprint(def.key, on)}
              />
            </div>
          ) : (
            <Switch
              key={def.key}
              size="sm"
              label={def.label}
              description={def.help(style)}
              checked={rules.footprints[def.key]}
              onCheckedChange={(on) => setFootprint(def.key, on)}
            />
          ),
        )}
      </RuleGroup>
    </>
  )
}

function RuleGroup({ title, inactive, children }: { title: string; inactive: boolean; children: ReactNode }) {
  const { t: tr } = useI18n()
  const id = useId()
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h3 id={id} className="micro-label flex items-center gap-2">
        {title}
        {inactive && (
          <span className="font-normal normal-case tracking-normal text-fg-subtle">{tr("· nicht in der Auswahl")}</span>
        )}
      </h3>
      <div className={cn('flex flex-col gap-3 transition-opacity', inactive && 'opacity-60')}>{children}</div>
    </section>
  )
}

// --------------------------------------------------------------------------- Präfixe

interface Row {
  id: number
  from: string
  to: string
}

/** Spalten einer Zeile: alt → neu ✕ */
const PREFIX_GRID = 'grid grid-cols-[4.75rem_0.875rem_4.75rem_1.5rem] gap-x-1.5'

let rowSeq = 0
const makeRow = (from = '', to = ''): Row => ({ id: ++rowSeq, from, to })
const rowsFrom = (map: Record<string, string>) => Object.entries(map).map(([from, to]) => makeRow(from, to))
/** vollständige Zeilen als Zuordnung (doppelte: die letzte gilt – wie im Backend) */
const mapOf = (rows: Row[]) => Object.fromEntries(rows.filter((r) => r.from && r.to).map((r) => [r.from, r.to]))
const sameMap = (a: Record<string, string>, b: Record<string, string>) =>
  stableStringify(cleanPrefixMap(a)) === stableStringify(cleanPrefixMap(b))

function PrefixMapEditor({
  value,
  onChange,
  disabled,
}: {
  value: Record<string, string>
  onChange: (map: Record<string, string>) => void
  disabled: boolean
}) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const addRef = useRef<HTMLButtonElement>(null)
  const [rows, setRows] = useState<Row[]>(() => rowsFrom(value))
  // Änderung von außen („Standard“, gespeicherte Regeln geladen): Zeilen neu aufbauen – eigene Eingaben (auch halbe
  // Zeilen) bleiben, solange sie dieselbe Zuordnung ergeben
  const [synced, setSynced] = useState(value)
  if (value !== synced) {
    setSynced(value)
    if (!sameMap(mapOf(rows), value)) setRows(rowsFrom(value))
  }

  const commit = (next: Row[]) => {
    setRows(next)
    onChange(mapOf(next))
  }
  const add = () => {
    const row = makeRow()
    commit([...rows, row])
    requestAnimationFrame(() => document.getElementById(`${uid}-from-${row.id}`)?.focus())
  }
  const remove = (id: number) => {
    commit(rows.filter((r) => r.id !== id))
    requestAnimationFrame(() => addRef.current?.focus())
  }

  // Hinweise: doppelt (die letzte Zeile gilt), alt = neu (ändert nichts), unvollständig (wird ignoriert)
  const lastIndex = new Map(rows.map((r, i) => [r.from, i] as const))
  const checks = rows.map((r, i) => {
    const duplicate = Boolean(r.from) && lastIndex.get(r.from) !== i
    const same = Boolean(r.from) && r.from === r.to
    const note = duplicate
      ? tr("„{0}“ steht mehrfach – es gilt die letzte Zeile.", { "0": String(r.from) })
      : same
        ? tr("„{0} → {1}“ ändert nichts.", { "0": String(r.from), "1": String(r.to) })
        : Boolean(r.from) !== Boolean(r.to)
          ? tr("Unvollständige Zeile – wird nicht angewendet.")
          : null
    return { invalid: duplicate || same, note }
  })
  const shown = [...new Set(checks.map((c) => c.note).filter((n): n is string => n !== null))]

  return (
    <div
      role="group"
      aria-labelledby={`${uid}-title`}
      className={cn('ml-1 flex flex-col gap-1.5 border-l border-line pl-3', disabled && 'opacity-60')}
    >
      <span id={`${uid}-title`} className="text-xs font-medium text-fg">
        {tr("Präfixe ersetzen")}</span>
      {rows.length > 0 && (
        <span aria-hidden className={cn(PREFIX_GRID, '-mb-0.5 text-2xs text-fg-subtle')}>
          <span>{tr("alt")}</span>
          <span />
          <span>{tr("neu")}</span>
        </span>
      )}
      {rows.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {rows.map((r, i) => (
            <li key={r.id} className={cn(PREFIX_GRID, 'items-center')}>
              <Input
                id={`${uid}-from-${r.id}`}
                size="sm"
                mono
                value={r.from}
                maxLength={8}
                spellCheck={false}
                autoComplete="off"
                disabled={disabled}
                invalid={checks[i].invalid}
                aria-label={tr("Altes Präfix, Zeile {0}", { "0": String(i + 1) })}
                placeholder="IC"
                onChange={(e) =>
                  commit(rows.map((x) => (x.id === r.id ? { ...x, from: cleanPrefix(e.target.value) } : x)))
                }
              />
              <ArrowRight aria-hidden className="size-3.5 text-fg-subtle" />
              <Input
                size="sm"
                mono
                value={r.to}
                maxLength={8}
                spellCheck={false}
                autoComplete="off"
                disabled={disabled}
                aria-label={tr("Neues Präfix, Zeile {0}", { "0": String(i + 1) })}
                placeholder="U"
                onChange={(e) =>
                  commit(rows.map((x) => (x.id === r.id ? { ...x, to: cleanPrefix(e.target.value) } : x)))
                }
              />
              <IconButton
                size="xs"
                label={r.from ? tr("Präfix {0} entfernen", { "0": String(r.from) }) : tr("Zeile {0} entfernen", { "0": String(i + 1) })}
                icon={<X />}
                disabled={disabled}
                onClick={() => remove(r.id)}
              />
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-2xs text-fg-subtle">{tr("Keine Präfixe – Bezeichner bleiben unverändert.")}</p>
      )}
      {shown.length > 0 && (
        <ul className="flex flex-col gap-0.5 text-2xs leading-snug text-warning-text" aria-live="polite">
          {shown.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      <Button
        ref={addRef}
        size="xs"
        variant="ghost"
        leftIcon={<Plus />}
        className="self-start"
        disabled={disabled}
        onClick={add}
      >
        {tr("Präfix hinzufügen")}</Button>
    </div>
  )
}
