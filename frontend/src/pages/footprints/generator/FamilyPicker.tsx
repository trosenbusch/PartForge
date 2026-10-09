/**
 * Auswahl der Gehäusefamilie: großer Auslöser (Glyphe, Name, Gruppe) und eine Befehlsliste (cmdk) mit Suche über
 * Familien, Vorlagen aller Familien und Aliase („SOIC“, „QFN“, „SMA“, „LFCSP“, „MLCC“ …). Ein genauer
 * Vorlagenschlüssel („DIP-8“) gewinnt vor dem Alias. Ein Alias der aktuellen Familie behält die Eingaben, solange
 * er denselben Gehäusetyp meint. Rechts zeigt eine Detailfläche die markierte Familie bzw. Vorlage.
 */
import { Command } from 'cmdk'
import { ArrowRight, ChevronsUpDown, CornerDownLeft, Search } from 'lucide-react'
import { Popover as PopoverPrimitive } from 'radix-ui'
import { useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { footprintsApi, type FootprintFamily, type FootprintPreset } from '@/api/footprints'
import { Kbd, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  aliasFamily as findAliasFamily,
  closestPreset,
  exactPreset,
  familyMatches,
  familyShortLabel,
  familySubtitle,
  groupFamilies,
  presetFactsText,
  presetMatches,
  presetSubtitle,
  presetValues,
  sameStrongSelectors,
} from '../lib/families'
import { normalizeParams, withoutDefaults, type ParamValues } from '../lib/params'
import { useGenerator } from './store'
import { PackageGlyph } from '../PackageGlyph'

export interface FamilyPick {
  preset?: FootprintPreset | null
  /** Eigene Werte (Alias ohne passende Vorlage) */
  values?: ParamValues
  /** Hinweis nach der Auswahl (z. B. „Alias LFCSP → QFN“) */
  note?: string
}

export interface FamilyPickerProps {
  families: FootprintFamily[]
  value: FootprintFamily | null
  onPick: (family: FootprintFamily, pick: FamilyPick) => void
  open: boolean
  onOpenChange: (open: boolean) => void
  className?: string
}

type Entry =
  | { kind: 'family'; id: string; family: FootprintFamily }
  | { kind: 'preset'; id: string; family: FootprintFamily; preset: FootprintPreset }
  | { kind: 'alias'; id: string; family: FootprintFamily; term: string }

const itemClass = cn(
  'group/item flex cursor-default select-none items-center gap-2.5 rounded-control px-2 py-1.5 text-ui outline-none',
  'data-[selected=true]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)] data-[disabled=true]:opacity-45',
)
const groupClass =
  '[&_[cmdk-group-heading]]:micro-label [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2.5'

export function FamilyPicker({ families, value, onPick, open, onOpenChange, className }: FamilyPickerProps) {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState<string>('')
  const [resolving, setResolving] = useState<string | null>(null)
  // Beim Öffnen (Klick oder Strg+F) mit leerer Suche auf der aktuellen Familie beginnen
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    setQuery('')
    setActive(open && value ? `f:${value.key}` : '')
  }
  const q = query.trim()

  const grouped = useMemo(() => groupFamilies(families), [families])

  const results = useMemo(() => {
    if (!q) return null
    const fam = families
      .map((f) => ({ f, s: familyMatches(f, q) }))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .map((x) => x.f)
    const pres = families
      .flatMap((f) => f.presets.map((p, i) => ({ f, p, i, s: presetMatches(p, q) })))
      .filter((x) => x.s > 0)
      .sort((a, b) => b.s - a.s)
      .slice(0, 30)
    return { families: fam, presets: pres }
  }, [families, q])

  // Genauer Vorlagenschlüssel („DIP-8“) vor Alias („dip8“); Alias nur, wenn er nicht der Familienschlüssel ist
  const exact = useMemo(() => (q ? exactPreset(families, q) : null), [families, q])
  const aliasHit = q && !exact ? findAliasFamily(families, q) : null
  const aliasFamily = aliasHit && aliasHit.key.toLowerCase() !== q.toLowerCase() ? aliasHit : null
  const aliasIsCurrent = Boolean(aliasFamily && value && aliasFamily.key === value.key)

  // Einträge nach ID (für die Detailfläche)
  const entries = useMemo(() => {
    const map = new Map<string, Entry>()
    for (const f of families) {
      map.set(`f:${f.key}`, { kind: 'family', id: `f:${f.key}`, family: f })
      f.presets.forEach((p, i) => map.set(`p:${f.key}:${i}`, { kind: 'preset', id: `p:${f.key}:${i}`, family: f, preset: p }))
    }
    if (aliasFamily) map.set(`a:${aliasFamily.key}`, { kind: 'alias', id: `a:${aliasFamily.key}`, family: aliasFamily, term: q })
    return map
  }, [families, aliasFamily, q])

  const activeEntry = entries.get(active) ?? (value ? entries.get(`f:${value.key}`) : undefined)

  const close = () => onOpenChange(false)

  const pickFamily = (f: FootprintFamily, preset?: FootprintPreset | null) => {
    onPick(f, { preset: preset ?? null })
    close()
  }

  /**
   * Alias über eine Vorschau auflösen: Familie + vom Alias festgelegte Werte → passende Vorlage. Meint der Alias die
   * aktuelle Familie mit demselben Gehäusetyp („soic“ bei SOIC-8), bleiben die Eingaben unverändert.
   */
  const pickAlias = async (f: FootprintFamily, term: string) => {
    setResolving(term)
    try {
      const preview = await footprintsApi.preview({ family: term, params: {}, density: 'N', with_3d: false })
      const gen = preview.spec.generator ?? {}
      const famKey = typeof gen.family === 'string' ? gen.family : f.key
      const family = families.find((x) => x.key === famKey) ?? f
      const resolved = normalizeParams(family.params, (gen.params as Record<string, unknown> | undefined) ?? {})
      const presetKey = typeof gen.preset === 'string' ? gen.preset : null
      const preset = family.presets.find((p) => p.key === presetKey) ?? closestPreset(family, resolved)
      const state = useGenerator.getState()
      const implied = preset ? presetValues(family, preset) : resolved
      if (value && family.key === value.key && sameStrongSelectors(implied, state.values)) {
        state.showNotice(`„${term}“ gehört zur aktuellen Familie – Ihre Eingaben bleiben erhalten.`)
      } else {
        const note = `„${term}“ ist ein Alias für ${familyShortLabel(family)}`
        if (preset) onPick(family, { preset, note })
        else onPick(family, { values: withoutDefaults(family.params, resolved), note })
      }
      close()
    } catch (error) {
      toast.error('Alias konnte nicht aufgelöst werden', { description: errorMessage(error) })
    } finally {
      setResolving(null)
    }
  }

  const presetsFirst = Boolean(
    exact ||
      (results && results.presets[0] && results.presets[0].s >= 4 && (results.families[0] ? familyMatches(results.families[0], q) < 4 : true)),
  )

  const familyItem = (f: FootprintFamily) => (
    <Command.Item key={f.key} value={`f:${f.key}`} onSelect={() => pickFamily(f)} className={itemClass}>
      <span className="flex size-7 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted group-data-[selected=true]/item:text-fg">
        <PackageGlyph family={f.key} className="size-[18px]" />
      </span>
      <span className="min-w-0 flex-1 truncate">{familyShortLabel(f)}</span>
      {value?.key === f.key && (
        <>
          <span aria-hidden className="size-1.5 shrink-0 rounded-full bg-accent shadow-[0_0_6px_var(--pf-glow-indicator)]" />
          <span className="sr-only">(gewählt)</span>
        </>
      )}
      <span className="mono shrink-0 text-2xs text-fg-subtle tabular-nums">{f.presets.length}</span>
    </Command.Item>
  )

  const presetsGroup = results && results.presets.length > 0 && (
    <Command.Group heading="Vorlagen" className={groupClass}>
      {results.presets.map(({ f, p, i }) => (
        <Command.Item key={`${f.key}:${i}`} value={`p:${f.key}:${i}`} onSelect={() => pickFamily(f, p)} className={itemClass}>
          <span className="flex size-7 shrink-0 items-center justify-center text-fg-subtle group-data-[selected=true]/item:text-fg-muted">
            <PackageGlyph family={f.key} className="size-4" />
          </span>
          <span className="mono min-w-0 shrink truncate text-xs font-semibold text-fg">{p.key}</span>
          <span className="min-w-0 flex-1 truncate text-2xs text-fg-subtle">{familyShortLabel(f)}</span>
        </Command.Item>
      ))}
    </Command.Group>
  )

  const familyHits = results ? results.families.filter((f) => f.key !== aliasFamily?.key) : []
  const familiesGroup = familyHits.length > 0 && (
    <Command.Group heading="Familien" className={groupClass}>
      {familyHits.map(familyItem)}
    </Command.Group>
  )

  return (
    <PopoverPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <PopoverPrimitive.Trigger asChild>
        <button
          type="button"
          aria-haspopup="dialog"
          aria-keyshortcuts="Control+F"
          className={cn(
            'group/trigger flex w-full items-center gap-3 rounded-button border border-line-control bg-control px-2.5 py-2 text-left outline-none',
            'shadow-[inset_0_1px_0_var(--pf-highlight)] transition-[border-color,background-color,box-shadow] duration-150',
            'hover:border-line-control-hover focus-ring data-[state=open]:border-accent data-[state=open]:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
            className,
          )}
        >
          <span className="flex size-10 shrink-0 items-center justify-center rounded-control border border-line bg-[radial-gradient(circle_at_30%_25%,var(--pf-surface-3),var(--pf-surface-2))] text-fg">
            <PackageGlyph family={value?.key} className="size-6" />
          </span>
          {/* Name = sichtbarer Text (Familie, Untertitel) – mit Hinweis für Screenreader, was der Knopf tut */}
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="line-clamp-2 text-sm font-semibold leading-tight tracking-[-0.01em] text-fg">
              {value && <span className="sr-only">Gehäusefamilie: </span>}
              {value ? familyShortLabel(value) : 'Gehäusefamilie wählen …'}
            </span>
            {value && <span className="truncate text-2xs leading-4 text-fg-subtle">{familySubtitle(value)}</span>}
            {value && <span className="sr-only"> – wechseln</span>}
          </span>
          <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-fg-subtle transition-colors group-hover/trigger:text-fg-muted" />
        </button>
      </PopoverPrimitive.Trigger>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={8}
          collisionPadding={12}
          aria-label="Gehäusefamilie wählen"
          className="pop-anim z-popover flex w-[min(700px,calc(100vw-2rem))] flex-col overflow-hidden rounded-card border border-line-strong bg-surface p-0 text-fg shadow-pop outline-none"
        >
          <Command
            label="Gehäusefamilien und Vorlagen"
            shouldFilter={false}
            loop
            vimBindings={false}
            value={active}
            onValueChange={setActive}
            className="flex min-h-0 flex-col"
          >
            <div className="flex items-center gap-2.5 border-b border-line px-3.5">
              <Search aria-hidden className="size-4 shrink-0 text-fg-subtle" />
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder="Familie, Vorlage oder Alias – SOIC, QFN-32, SMA, LFCSP, 0805 …"
                className="h-11 w-full bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle"
              />
              {resolving && <Spinner size={14} tone="accent" />}
              <Kbd keys={['Esc']} size="xs" />
            </div>
            <div className="grid h-[392px] min-h-0 grid-cols-[minmax(0,1fr)_280px]">
              <Command.List className="min-h-0 overflow-y-auto p-1.5 [scrollbar-gutter:stable]">
                <Command.Empty className="px-3 py-10 text-center text-xs text-fg-muted">
                  Keine Familie und keine Vorlage für „{q}“.
                </Command.Empty>
                {aliasFamily && (
                  <Command.Group heading="Alias" className={groupClass}>
                    <Command.Item
                      value={`a:${aliasFamily.key}`}
                      onSelect={() => void pickAlias(aliasFamily, q)}
                      disabled={resolving !== null}
                      className={itemClass}
                    >
                      <span className="flex size-7 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted">
                        <PackageGlyph family={aliasFamily.key} className="size-[18px]" />
                      </span>
                      <span className="mono shrink-0 text-xs font-semibold uppercase text-fg">{q}</span>
                      <ArrowRight aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
                      <span className="min-w-0 flex-1 truncate">{familyShortLabel(aliasFamily)}</span>
                      {aliasIsCurrent && <span className="shrink-0 text-2xs text-fg-subtle">aktuelle Familie</span>}
                    </Command.Item>
                  </Command.Group>
                )}
                {results ? (
                  presetsFirst ? (
                    <>
                      {presetsGroup}
                      {familiesGroup}
                    </>
                  ) : (
                    <>
                      {familiesGroup}
                      {presetsGroup}
                    </>
                  )
                ) : (
                  grouped.map(({ group, families: list }) => (
                    <Command.Group key={group} heading={group} className={groupClass}>
                      {list.map(familyItem)}
                    </Command.Group>
                  ))
                )}
              </Command.List>
              <aside aria-label="Details" className="min-h-0 overflow-y-auto border-l border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_45%,transparent)] p-4">
                {activeEntry ? (
                  <EntryDetails
                    entry={activeEntry}
                    current={value}
                    onPickPreset={(f, p) => pickFamily(f, p)}
                  />
                ) : (
                  <p className="text-xs text-fg-muted">Familie wählen – Vorlagen erscheinen hier.</p>
                )}
              </aside>
            </div>
            <div className="flex items-center gap-3 border-t border-line px-3.5 py-2 text-2xs text-fg-subtle">
              <span className="flex items-center gap-1">
                <Kbd keys={['↑', '↓']} size="xs" /> wählen
              </span>
              <span className="flex items-center gap-1">
                <CornerDownLeft aria-hidden className="size-3" /> übernehmen
              </span>
              <span className="flex items-center gap-1">
                <Kbd hotkey="mod+f" size="xs" /> öffnen
              </span>
              <span className="ml-auto truncate tabular-nums">
                {families.length} Familien · {families.reduce((a, f) => a + f.presets.length, 0)} Vorlagen
              </span>
            </div>
          </Command>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

function DetailHeader({ family, title, subtitle }: { family: FootprintFamily; title: ReactNode; subtitle: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <span className="flex size-12 shrink-0 items-center justify-center rounded-card border border-line bg-surface text-fg shadow-card">
        <PackageGlyph family={family.key} className="size-7" />
      </span>
      <div className="min-w-0 pt-0.5">
        <div className="text-ui font-semibold leading-snug text-fg">{title}</div>
        <div className="mt-0.5 text-2xs leading-4 text-fg-subtle">{subtitle}</div>
      </div>
    </div>
  )
}

function EntryDetails({
  entry,
  current,
  onPickPreset,
}: {
  entry: Entry
  current: FootprintFamily | null
  onPickPreset: (family: FootprintFamily, preset: FootprintPreset) => void
}) {
  const f = entry.family
  if (entry.kind === 'preset') {
    const p = entry.preset
    const facts = presetFactsText(f, p)
    return (
      <div className="flex flex-col gap-3">
        <DetailHeader family={f} title={<span className="mono">{p.key}</span>} subtitle={familyShortLabel(f)} />
        <p className="text-xs leading-relaxed text-fg-muted">{presetSubtitle(p)}</p>
        {facts && <p className="mono text-2xs text-fg-muted">{facts}</p>}
        {p.source && (
          <div>
            <div className="micro-label">Quelle</div>
            <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{p.source}</p>
          </div>
        )}
        <p className="flex items-center gap-1.5 text-2xs text-fg-subtle">
          <CornerDownLeft aria-hidden className="size-3" /> lädt Familie und Vorlage
        </p>
      </div>
    )
  }
  const shown = f.presets.slice(0, 14)
  return (
    <div className="flex flex-col gap-3">
      <DetailHeader
        family={f}
        title={familyShortLabel(f)}
        subtitle={
          <>
            {f.group}
            {f.ipc_table ? ` · IPC ${f.ipc_table}` : ''}
          </>
        }
      />
      {entry.kind === 'alias' && (
        <p className="rounded-control border border-line bg-surface px-2.5 py-1.5 text-2xs leading-4 text-fg-muted">
          <span className="mono font-semibold uppercase text-fg">{entry.term}</span> ist ein Alias dieser Familie.{' '}
          {current?.key === f.key
            ? 'Meint er denselben Gehäusetyp, bleiben Ihre Eingaben erhalten – sonst wird die passende Vorlage geladen (rückgängig mit Strg+Z).'
            : 'Die passende Vorlage wird geladen.'}
        </p>
      )}
      {f.description && <p className="text-xs leading-relaxed text-fg-muted">{f.description}</p>}
      {shown.length > 0 && (
        <div>
          <div className="micro-label mb-1.5">
            Vorlagen <span className="tabular-nums">({f.presets.length})</span>
          </div>
          <div className="flex flex-wrap gap-1">
            {shown.map((p) => (
              <button
                key={p.key}
                type="button"
                tabIndex={-1}
                onClick={() => onPickPreset(f, p)}
                title={p.label}
                className="mono h-6 rounded-md border border-line bg-surface px-1.5 text-2xs font-medium text-fg-muted outline-none transition-colors hover:border-line-strong hover:text-fg"
              >
                {p.key}
              </button>
            ))}
            {f.presets.length > shown.length && (
              <span className="flex h-6 items-center px-1 text-2xs text-fg-subtle">+{f.presets.length - shown.length} weitere</span>
            )}
          </div>
        </div>
      )}
      {current?.key === f.key && entry.kind === 'family' && (
        <p className="text-2xs text-fg-subtle">Aktuell gewählt – Ihre Eingaben bleiben erhalten.</p>
      )}
    </div>
  )
}
