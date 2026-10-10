import { useI18n } from '@/lib/i18n'
import { PenTool, RotateCcw, X } from 'lucide-react'
import { useId } from 'react'
import { Link } from 'react-router'
import type { ConformRules } from '@/api/housestyle'
import type { LibraryFile } from '@/api/libraries'
import {
  Button,
  Card,
  ChipGroup,
  IconButton,
  ScrollArea,
  SegmentedControl,
  Separator,
  Skeleton,
  Tooltip,
} from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { LibraryPicker } from './LibraryPicker'
import {
  KIND_LABEL,
  SOURCE_LABEL,
  SOURCES,
  STYLE_PLACES,
  type Kind,
  type Selection,
  type Source,
  type StyleInfo,
} from './model'
import { RulesEditor } from './RulesEditor'

type KindChoice = 'both' | Kind

export interface SelectionPanelProps {
  selection: Selection
  onSelectionChange: (selection: Selection) => void
  rules: ConformRules
  /** gespeicherte Regeln werden noch geladen (Schalter noch nicht bedienbar) */
  rulesLoading: boolean
  onRulesChange: (rules: ConformRules) => void
  /** „Standard“ – `null`, solange die Regeln schon dem Standard entsprechen */
  onResetRules: (() => void) | null
  /** Entwurf weicht von den zuletzt angewendeten Regeln ab */
  rulesChanged: boolean
  style: StyleInfo | null
  files: LibraryFile[] | undefined
  filesLoading: boolean
  filesError: Error | null
  onRetryFiles: () => void
  /** Warum gerade nicht geprüft werden kann */
  problem: string | null
}

export function SelectionPanel({
  selection,
  onSelectionChange,
  rules,
  rulesLoading,
  onRulesChange,
  onResetRules,
  rulesChanged,
  style,
  files,
  filesLoading,
  filesError,
  onRetryFiles,
  problem,
}: SelectionPanelProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const titleId = `${uid}-title`
  const kindChoice: KindChoice = selection.kinds.length === 1 ? selection.kinds[0] : 'both'
  const set = (patch: Partial<Selection>) => onSelectionChange({ ...selection, ...patch })
  const names = selection.names ?? []

  return (
    <aside
      aria-labelledby={titleId}
      className="min-w-0 @[44rem]:sticky @[44rem]:top-[calc(var(--pf-topbar-height)+1rem)] @[44rem]:self-start"
    >
      <Card className="flex flex-col overflow-hidden">
        <div className="flex items-center gap-2 border-b border-line py-2.5 pl-4 pr-2.5">
          <h2 id={titleId} className="min-w-0 flex-1 text-sm font-semibold tracking-[-0.01em] text-fg">
            {tr("Auswahl und Regeln")}</h2>
          <Tooltip content={tr("Schalter und Präfixe auf die Standardwerte – eigene Lagenrollen bleiben")}>
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<RotateCcw />}
              disabled={!onResetRules || rulesLoading}
              onClick={() => onResetRules?.()}
            >
              {tr("Standardwerte")}
            </Button>
          </Tooltip>
        </div>

        {/* Inhalt bricht um statt seitlich zu wachsen (Radix legt sonst eine Tabelle um den Inhalt) */}
        <ScrollArea viewportClassName="@[44rem]:max-h-[calc(100dvh-var(--pf-topbar-height)-8rem)] [&>div]:block!">
          <div className="flex flex-col gap-5 px-4 py-4">
            {/* ---------------------------------------------------------- Auswahl */}
            <section aria-labelledby={`${uid}-sel`} className="flex flex-col gap-3.5">
              <h3 id={`${uid}-sel`} className="micro-label">
                {tr("Auswahl")}</h3>

              <div className="flex flex-col gap-1.5">
                <span id={`${uid}-kind`} className="text-xs font-medium text-fg">
                  {tr("Art")}</span>
                <SegmentedControl<KindChoice>
                  size="sm"
                  fullWidth
                  aria-labelledby={`${uid}-kind`}
                  value={kindChoice}
                  onValueChange={(v) => set({ kinds: v === 'both' ? ['symbol', 'footprint'] : [v] })}
                  options={[
                    { value: 'both', label: tr("Beide") },
                    { value: 'symbol', label: KIND_LABEL.symbol },
                    { value: 'footprint', label: KIND_LABEL.footprint },
                  ]}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-fg" aria-hidden>
                  {tr("Herkunft")}</span>
                <ChipGroup<Source>
                  size="sm"
                  aria-label={tr("Herkunft")}
                  value={selection.sources}
                  onValueChange={(sources) => set({ sources: SOURCES.filter((s) => sources.includes(s)) })}
                  options={SOURCES.map((s) => ({ value: s, label: SOURCE_LABEL[s] }))}
                />
                <p className="text-2xs leading-snug text-fg-subtle">
                  {tr("Externe Bibliotheken bleiben immer unberührt. Erzeugte Bauteile folgen dem Hausstil meist schon.")}</p>
              </div>

              <div className="flex flex-col gap-1.5">
                <span id={`${uid}-libs`} className="text-xs font-medium text-fg">
                  {tr("Bibliotheken")}</span>
                <LibraryPicker
                  labelId={`${uid}-libs`}
                  files={files}
                  loading={filesLoading}
                  error={filesError}
                  onRetry={onRetryFiles}
                  kinds={selection.kinds}
                  value={selection.libraries}
                  onChange={(libraries) => set({ libraries })}
                />
              </div>

              {names.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-medium text-fg">{tr("Einzelne Bauteile")}</span>
                  <div className="flex min-w-0 items-center gap-1 self-start rounded-full border border-accent/35 bg-accent-soft py-0.5 pl-2.5 pr-0.5 text-2xs font-medium text-accent-text">
                    {plural(names.length, tr("einzelnes Bauteil"), tr("einzelne Bauteile"))}
                    <IconButton
                      size="xs"
                      className="size-5 rounded-full text-accent-text"
                      label={tr("Einschränkung auf einzelne Bauteile aufheben")}
                      icon={<X />}
                      tooltip={false}
                      onClick={() => set({ names: null })}
                    />
                  </div>
                  <p className="mono text-2xs leading-snug text-fg-subtle [overflow-wrap:anywhere]">
                    {names.slice(0, 4).join(', ')}
                    {names.length > 4 && (
                      <span className="font-sans"> {tr(" und ")}{formatNumber(names.length - 4)} {' '}{tr("weitere")}</span>
                    )}
                  </p>
                </div>
              )}

              {problem && (
                <p
                  className="rounded-control border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-xs leading-snug text-warning-text"
                  aria-live="polite"
                >
                  {problem}
                </p>
              )}
            </section>

            <Separator />

            {/* ---------------------------------------------------------- Regeln */}
            {rulesLoading ? (
              <div className="flex flex-col gap-3" aria-busy="true" aria-label={tr("Regeln werden geladen")}>
                <Skeleton className="h-3 w-20" />
                {[0, 1, 2, 3, 4].map((i) => (
                  <div key={i} className="flex items-center gap-3">
                    <div className="flex flex-1 flex-col gap-1.5">
                      <Skeleton className="h-3.5 w-28" />
                      <Skeleton className="h-3 w-full" />
                    </div>
                    <Skeleton className="h-4 w-7 rounded-full" />
                  </div>
                ))}
              </div>
            ) : (
              <RulesEditor rules={rules} onChange={onRulesChange} style={style} kinds={selection.kinds} />
            )}

            <Separator />

            {/* ---------------------------------------------------------- Hausstil */}
            <section aria-labelledby={`${uid}-style`} className="flex flex-col gap-2">
              <h3 id={`${uid}-style`} className="micro-label">
                {tr("Hausstil")}</h3>
              <p className="text-xs leading-snug text-fg-muted">
                {tr("Die Regeln setzen den gespeicherten Hausstil dieser Bibliothek um – Schriften, Pinlängen, Linienbreiten und die Lagenzuordnung stehen in den Einstellungen.")}</p>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <Button asChild size="xs" variant="link">
                  <Link to={STYLE_PLACES.footprints.to}>
                    <PenTool aria-hidden />
                    {tr("Hausstil bearbeiten")}</Link>
                </Button>
                <span aria-hidden className="text-2xs text-fg-subtle">
                  ·
                </span>
                <Button asChild size="xs" variant="link">
                  <Link to={STYLE_PLACES.layers.to} aria-label={tr("Hausstil: Lagen bearbeiten")}>
                    {STYLE_PLACES.layers.label}
                  </Link>
                </Button>
                <span aria-hidden className="text-2xs text-fg-subtle">
                  ·
                </span>
                <Button asChild size="xs" variant="link">
                  <Link to={STYLE_PLACES.symbols.to} aria-label={tr("Hausstil: Symbole bearbeiten")}>
                    {STYLE_PLACES.symbols.label}
                  </Link>
                </Button>
              </div>
            </section>
          </div>
        </ScrollArea>

        <p className="border-t border-line px-4 py-2.5 text-2xs leading-snug text-fg-subtle" aria-live="polite">
          {rulesChanged
            ? tr("Regeln geändert – „Anwenden“ merkt sie sich für diese Bibliothek.")
            : tr("Beim Anwenden merkt sich PartForge die Regeln für diese Bibliothek.")}
        </p>
      </Card>
    </aside>
  )
}
