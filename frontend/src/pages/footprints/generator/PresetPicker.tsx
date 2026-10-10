import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Vorlagen einer Familie als dichte Liste: je Zeile Schlüssel und Kennzahlen (Pins · Raster · Körper); die gewählte
 * Vorlage zeigt zusätzlich Bezeichnung und Datenquelle. Listbox mit Pfeiltasten: Solange nichts geändert ist, lädt
 * das Durchblättern die Vorlage sofort (Vorschau folgt live). Sind Werte angepasst, bewegen die Pfeile nur den Fokus
 * – Enter lädt (rückgängig mit Strg+Z). Facetten (Bauteilart/Gehäusetyp) und Suche bei vielen Vorlagen.
 */
import { Check, RotateCcw, Search, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import type { FootprintFamily, FootprintPreset } from '@/api/footprints'
import { Badge, Button, Kbd, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { facetLabel, presetFacet, presetFactsShort, presetFactsText, presetMatches, presetSubtitle } from '../lib/families'
import { SectionLabel } from '../parts'

/** Geschützter Bindestrich (U+2011) */
const NB_HYPHEN = String.fromCharCode(0x2011)

export interface PresetPickerProps {
  family: FootprintFamily
  presets: readonly FootprintPreset[]
  value: string | null
  /** Anzahl geänderter Werte gegenüber der Vorlage */
  changed: number
  onSelect: (preset: FootprintPreset) => void
  onReset: () => void
}

export function PresetPicker({ family, presets, value, changed, onSelect, onReset }: PresetPickerProps) {
  useI18n()
  const uid = useId()
  const facet = useLocalizedMemo(() => presetFacet(presets), [presets])
  const current = presets.find((p) => p.key === value) ?? null
  const currentFacet = facet && current ? String(current.params[facet.param] ?? '') : null
  // Facette folgt der gewählten Vorlage, bis der Nutzer selbst filtert
  const [facetChoice, setFacetChoice] = useState<{ family: string; value: string | null } | null>(null)
  const activeFacet = facetChoice?.family === family.key ? facetChoice.value : currentFacet
  const [query, setQuery] = useState('')
  const [queryFamily, setQueryFamily] = useState(family.key)
  if (queryFamily !== family.key) {
    setQueryFamily(family.key)
    setQuery('')
  }

  const visible = useLocalizedMemo(() => {
    let list = presets.slice()
    if (facet && activeFacet) list = list.filter((p) => String(p.params[facet.param] ?? '') === activeFacet)
    const q = query.trim()
    if (q) list = list.filter((p) => presetMatches(p, q) > 0)
    return list
  }, [presets, facet, activeFacet, query])

  const listRef = useRef<HTMLDivElement>(null)
  // Fokus-Ziel (roving tabindex) – unabhängig von der Auswahl, sobald Werte geändert sind
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const selectedIndex = visible.findIndex((p) => p.key === value)
  const focusedIndex = focusKey ? visible.findIndex((p) => p.key === focusKey) : -1
  const tabIndexTarget = focusedIndex >= 0 ? focusedIndex : selectedIndex >= 0 ? selectedIndex : 0

  // Gewählte Vorlage im Sichtbereich der Liste halten (ohne die Eingabespalte zu verschieben)
  useEffect(() => {
    const list = listRef.current
    const el = list?.querySelector<HTMLElement>('[aria-selected="true"]')
    if (!list || !el) return
    const lr = list.getBoundingClientRect()
    const er = el.getBoundingClientRect()
    if (er.top < lr.top) list.scrollTop -= lr.top - er.top + 4
    else if (er.bottom > lr.bottom) list.scrollTop += er.bottom - lr.bottom + 4
  }, [value, visible])

  const focusAt = (index: number) => {
    const preset = visible[index]
    if (!preset) return
    setFocusKey(preset.key)
    const el = listRef.current?.querySelectorAll<HTMLElement>('[role="option"]')[index]
    el?.focus({ preventScroll: true })
    el?.scrollIntoView({ block: 'nearest' })
    // Nichts geändert → nichts geht verloren: Auswahl folgt dem Fokus (live durchblättern)
    if (changed === 0) onSelect(preset)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLElement>, index: number) => {
    let next: number | null = null
    if (e.key === 'ArrowDown') next = index + 1
    else if (e.key === 'ArrowUp') next = index - 1
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = visible.length - 1
    else if (e.key === 'PageDown') next = index + 6
    else if (e.key === 'PageUp') next = index - 6
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      const preset = visible[index]
      if (preset) onSelect(preset)
      return
    }
    if (next === null) return
    e.preventDefault()
    focusAt(Math.max(0, Math.min(visible.length - 1, next)))
  }

  return (
    <section aria-labelledby="fp-presets-label" className="flex flex-col gap-2">
      <SectionLabel
        id="fp-presets-label"
        actions={
          presets.length > 8 ? (
            <label className="flex h-6 w-44 items-center gap-1.5 rounded-md border border-line-control bg-control px-1.5 transition-colors focus-within:border-accent hover:border-line-control-hover">
              <Search aria-hidden className="size-3 shrink-0 text-fg-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Escape' && query) {
                    e.stopPropagation()
                    setQuery('')
                  } else if (e.key === 'ArrowDown') {
                    e.preventDefault()
                    listRef.current?.querySelector<HTMLElement>('[role="option"][tabindex="0"]')?.focus()
                  }
                }}
                placeholder={tr("In {value0} Vorlagen suchen …", { value0: String(presets.length) })}
                aria-label={tr("Vorlagen durchsuchen")}
                className="h-full w-full min-w-0 bg-transparent text-2xs text-fg outline-none placeholder:text-fg-subtle"
              />
              {query && (
                <button type="button" aria-label={tr("Suche leeren")} onClick={() => setQuery('')} className="text-fg-subtle hover:text-fg">
                  <X className="size-3" />
                </button>
              )}
            </label>
          ) : (
            <span className="text-2xs tabular-nums text-fg-subtle">
              {presets.length} {presets.length === 1 ? tr('Vorlage') : tr('Vorlagen')}
            </span>
          )
        }
      >
        {tr("Vorlage")}
      </SectionLabel>

      {facet && (
        <div role="group" aria-label={tr("Vorlagen filtern")} className="flex flex-wrap gap-1">
          <FacetChip active={!activeFacet} onClick={() => setFacetChoice({ family: family.key, value: null })} label={tr("Alle Vorlagen")}>
            {tr("Alle")}
          </FacetChip>
          {facet.values.map((v) => (
            <FacetChip
              key={v.value}
              active={activeFacet === v.value}
              onClick={() => setFacetChoice({ family: family.key, value: v.value })}
              label={`${facetLabel(facet.param, v.value)} (${v.count} ${v.count === 1 ? tr('Vorlage') : tr('Vorlagen')})`}
            >
              {v.value}
            </FacetChip>
          ))}
        </div>
      )}

      {visible.length === 0 ? (
        <p className="rounded-control border border-dashed border-line-strong px-3 py-4 text-center text-xs text-fg-muted">
          {tr("Keine Vorlage passt")}{query ? tr(" zu „{value0}“", { value0: String(query) }) : ''}.
        </p>
      ) : (
        <div className="group/list flex flex-col gap-1">
          <div
            ref={listRef}
            role="listbox"
            aria-labelledby="fp-presets-label"
            aria-describedby={`${uid}-keys`}
            className="-mx-1 flex max-h-[13.5rem] flex-col gap-px overflow-y-auto px-1 py-0.5 [scrollbar-gutter:stable]"
          >
            {visible.map((p, i) => (
              <PresetRow
                key={p.key}
                family={family}
                preset={p}
                selected={p.key === value}
                changed={p.key === value ? changed : 0}
                tabIndex={i === tabIndexTarget ? 0 : -1}
                onClick={() => {
                  setFocusKey(p.key)
                  onSelect(p)
                }}
                onFocus={() => setFocusKey(p.key)}
                onKeyDown={(e) => onKeyDown(e, i)}
              />
            ))}
          </div>
          <p id={`${uid}-keys`} className="hidden items-center gap-1.5 text-2xs text-fg-subtle group-focus-within/list:flex">
            <Kbd keys={['↑', '↓']} size="xs" /> {tr("wählen ·")}<Kbd keys={['Enter']} size="xs" /> {tr("lädt die Vorlage")}
            {changed > 0 && <span className="text-fg-muted">{tr("· Strg+Z macht es rückgängig")}</span>}
          </p>
        </div>
      )}

      {changed > 0 && current && (
        <div className="flex items-center gap-2 text-2xs text-fg-muted">
          <span aria-hidden className="size-1.5 rounded-full bg-accent shadow-[0_0_6px_var(--pf-glow-indicator)]" />
          <span className="min-w-0 flex-1">
            {changed} {changed === 1 ? tr('Wert weicht') : tr('Werte weichen')} {tr("von „")}{current.key}{tr("“ ab")}
          </span>
          <Button variant="ghost" size="xs" leftIcon={<RotateCcw />} onClick={onReset}>
            {tr("Zurücksetzen")}
          </Button>
        </div>
      )}
    </section>
  )
}

function PresetRow({
  family,
  preset,
  selected,
  changed,
  tabIndex,
  onClick,
  onFocus,
  onKeyDown,
}: {
  family: FootprintFamily
  preset: FootprintPreset
  selected: boolean
  changed: number
  tabIndex: number
  onClick: () => void
  onFocus: () => void
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
}) {
  useI18n()
  const facts = presetFactsShort(family, preset)
  const subtitle = presetSubtitle(preset)
  const factsText = presetFactsText(family, preset)
  return (
    <Tooltip
      side="right"
      delayDuration={700}
      content={
        <span className="flex max-w-72 flex-col gap-0.5">
          <span className="font-medium">{tr(preset.label)}</span>
          {factsText && <span className="text-fg-muted">{factsText}</span>}
          {preset.source && <span className="text-fg-muted">{tr("Quelle:")}{' '}{preset.source}</span>}
        </span>
      }
    >
      <button
        type="button"
        role="option"
        aria-selected={selected}
        tabIndex={tabIndex}
        onClick={onClick}
        onFocus={onFocus}
        onKeyDown={onKeyDown}
        className={cn(
          'relative flex w-full min-w-0 shrink-0 flex-col items-stretch rounded-control border px-2 text-left outline-none',
          'transition-[border-color,background-color,box-shadow] duration-150 focus-visible:z-[1] focus-ring',
          selected
            ? 'border-accent/55 bg-[color-mix(in_oklab,var(--pf-accent)_8%,var(--pf-surface))] py-1.5 shadow-[0_0_0_1px_color-mix(in_oklab,var(--pf-accent)_20%,transparent),0_6px_18px_-12px_var(--pf-glow-indicator)]'
            : 'border-transparent py-1 hover:border-line hover:bg-surface-2',
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <span className="flex size-3.5 shrink-0 items-center justify-center">
            {selected ? (
              changed > 0 ? (
                <span aria-hidden className="size-1.5 rounded-full bg-accent shadow-[0_0_6px_var(--pf-glow-indicator)]" />
              ) : (
                <Check aria-hidden className="size-3.5 text-accent-text" />
              )
            ) : null}
          </span>
          <span className="mono shrink-0 text-xs font-semibold text-fg">{preset.key}</span>
          <span className={cn('mono min-w-0 flex-1 truncate text-right text-2xs tabular-nums', selected ? 'text-fg-muted' : 'text-fg-subtle')}>
            {facts}
          </span>
          {/* Name = sichtbarer Text; die ausgeschriebenen Maße zusätzlich für Screenreader */}
          {factsText && <span className="sr-only">, {factsText}</span>}
          {selected && changed > 0 && (
            <Badge variant="accent" size="sm" className="h-4 shrink-0 px-1.5">
              {tr("angepasst")}
            </Badge>
          )}
        </span>
        {selected && (preset.source || subtitle !== preset.key) && (
          // Nur bei der gewählten Vorlage: Datenquelle (sonst die Bezeichnung)
          <span className="mt-0.5 pl-[22px] text-2xs leading-4 text-fg-subtle">
            {/* geschützte Bindestriche: „SOT96‑1“ bricht nicht am Bindestrich */}
            {preset.source ? tr("Quelle: {value0}", { value0: String(preset.source.replace(/(\w)-(\w)/g, `$1${NB_HYPHEN}$2`)) }) : subtitle}
          </span>
        )}
      </button>
    </Tooltip>
  )
}

function FacetChip({ active, onClick, children, label }: { active: boolean; onClick: () => void; children: string; label: string }) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        aria-pressed={active}
        aria-label={label}
        onClick={onClick}
        className={cn(
          'mono h-6 rounded-md border px-1.5 text-2xs font-medium outline-none transition-colors focus-ring',
          active
            ? 'border-accent/45 bg-accent-soft text-accent-text'
            : 'border-line bg-surface text-fg-muted hover:border-line-strong hover:text-fg',
        )}
      >
        {children}
      </button>
    </Tooltip>
  )
}
