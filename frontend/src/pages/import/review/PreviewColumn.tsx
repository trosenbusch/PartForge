import { CircuitBoard, PanelRightClose, Component as SymbolIcon, TriangleAlert } from 'lucide-react'
import { errorMessage } from '@/api/client'
import { useLibrarySymbolNames, type SymbolChoice } from '@/api/datasheets'
import { PreviewPanel, useFootprintPreview } from '@/components/preview'
import { Badge, Combobox, IconButton, SegmentedControl, Select } from '@/components/ui'
import type { FootprintRequest } from '@/lib/geometry'
import { formatNumber } from '@/lib/format'
import { TipButton } from '../shared/TipButton'
import { useReviewUi } from '../store'
import { useReview } from './context'
import { willWrite } from './readiness'

const SOURCE_LABEL: Record<string, string> = {
  standard: 'Standardsymbol',
  ic: 'IC-Symbol aus der Pintabelle',
  existing: 'vorhandenes Symbol',
}

const SYMBOL_MODES: { value: SymbolChoice['mode']; label: string }[] = [
  { value: 'auto', label: 'Automatisch' },
  { value: 'standard', label: 'Standardsymbol' },
  { value: 'ic', label: 'IC aus Pintabelle' },
  { value: 'existing', label: 'Vorhandenes …' },
]

/** Spalte 3: Live-Vorschau des Vorschlags – Symbol (mit Teilen), Footprint je Gehäuse (IPC ↔ Hersteller), 3D. */
export function PreviewColumn() {
  const { proposal, proposalFetching, proposalError, category, choices, setChoices } = useReview()
  const previewPackage = useReviewUi((s) => s.previewPackage)
  const setPreviewPackage = useReviewUi((s) => s.setPreviewPackage)
  const tab = useReviewUi((s) => s.previewTab)
  const setTab = useReviewUi((s) => s.setPreviewTab)
  const highlight = useReviewUi((s) => s.highlight)

  const footprints = proposal?.footprints ?? []
  const code = previewPackage && footprints.some((f) => f.package === previewPackage) ? previewPackage : (footprints[0]?.package ?? null)
  const fp = footprints.find((f) => f.package === code)
  const sym = (code ? proposal?.symbols.find((s) => s.packages.includes(code)) : undefined) ?? proposal?.symbols[0]
  const request = fp && fp.mode !== 'existing' && fp.request ? (fp.request as unknown as FootprintRequest) : null
  const calc = useFootprintPreview(request, { enabled: Boolean(request) })
  const variant = proposal?.variants.find((v) => v.package === code) ?? proposal?.variants[0]
  const pkgChoice = code ? choices.packages[code] : undefined
  const symChoice: SymbolChoice = (code ? choices.symbols[code] : undefined) ?? { mode: 'auto' }
  const hasManufacturer = Boolean(fp && (fp.mode === 'manufacturer' || fp.alternatives.some((a) => a.mode === 'manufacturer')))
  const library = useLibrarySymbolNames(symChoice.mode === 'existing')
  const error = proposalError ? errorMessage(proposalError) : null

  const setLand = (mode: 'ipc' | 'manufacturer') => {
    if (!code) return
    setChoices((c) => ({ ...c, packages: { ...c.packages, [code]: { ...(c.packages[code] ?? { footprint: 'ipc' }), footprint: mode } } }))
  }
  const setSymbol = (patch: Partial<SymbolChoice>) => {
    if (!code) return
    // eine Entscheidung gilt für alle Gehäuse, die sich dieses Symbol teilen
    const shared = sym?.packages.length ? sym.packages : [code]
    setChoices((c) => {
      const symbols = { ...c.symbols }
      for (const p of shared) symbols[p] = { ...(symbols[p] ?? { mode: 'auto' }), ...patch }
      return { ...c, symbols }
    })
  }

  // IPC ↔ Herstellerempfehlung: in der Footprint-Zeile (die Werkzeugleiste der Vorschau ist bei schmaler Spalte voll)
  const landToggle = hasManufacturer ? (
    <SegmentedControl
      size="sm"
      aria-label="Lötflächen"
      value={
        pkgChoice?.footprint === 'manufacturer' || (pkgChoice?.footprint !== 'ipc' && fp?.mode === 'manufacturer') ? 'manufacturer' : 'ipc'
      }
      onValueChange={(mode) => {
        setLand(mode)
        if (tab === 'symbol') setTab('footprint')
      }}
      options={[
        { value: 'ipc', label: 'IPC' },
        { value: 'manufacturer', label: 'Hersteller' },
      ]}
      className="shrink-0"
    />
  ) : null

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-bg-elev">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
        <h2 className="micro-label shrink-0">Vorschau</h2>
        {footprints.length > 1 &&
          (footprints.length <= 3 ? (
            <SegmentedControl
              size="sm"
              aria-label="Gehäuse in der Vorschau"
              value={code ?? ''}
              onValueChange={setPreviewPackage}
              options={footprints.map((f) => ({
                value: f.package,
                // schmal nur der Gehäusecode (DD, MS8), breit der volle Name
                label: (
                  <>
                    <span className="mono @[23rem]:hidden">{f.package}</span>
                    <span className="hidden @[23rem]:inline">{f.package_label || f.package}</span>
                  </>
                ),
                title: f.package_label || f.package,
              }))}
              className="ml-auto min-w-0"
            />
          ) : (
            <Select
              size="sm"
              aria-label="Gehäuse in der Vorschau"
              value={code ?? undefined}
              onValueChange={setPreviewPackage}
              options={footprints.map((f) => ({ value: f.package, label: f.package_label || f.package }))}
              className="ml-auto w-auto min-w-36"
            />
          ))}
        <IconButton
          size="sm"
          label="Vorschau ausblenden"
          icon={<PanelRightClose />}
          onClick={() => useReviewUi.getState().setPreviewCollapsed(true)}
          className={footprints.length > 1 ? 'shrink-0' : 'ml-auto shrink-0'}
        />
      </div>

      <PreviewPanel
        symbol={sym?.spec}
        footprint={fp?.spec}
        calc={calc.data?.calc}
        tab={tab}
        onTabChange={setTab}
        highlight={highlight}
        loading={proposalFetching || (!proposal && !error)}
        error={error}
        designator={`${category?.prefix || 'U'}?`}
        comment={variant?.values.Comment ?? variant?.mpn}
        emptyText={{
          symbol: 'Kein Symbol – Pintabelle oder Kategorie prüfen',
          footprint: 'Kein Footprint – Gehäuse prüfen',
          '3d': 'Kein 3D-Körper',
        }}
        title={[sym?.name, fp?.name].filter(Boolean).join(' · ') || 'Vorschau'}
        className="min-h-0 flex-1 rounded-none border-0 shadow-none"
      />

      {/* Symbol und Footprint des Gehäuses (Zeilen mit Auswahl – deshalb keine Definitionsliste) */}
      <div className="shrink-0 divide-y divide-line border-t border-line text-xs">
        <div className="flex min-w-0 items-center gap-2 px-3 py-2">
          <span className="flex shrink-0 items-center gap-1.5 text-fg-subtle">
            <SymbolIcon aria-hidden className="size-3.5" />
            <span className="sr-only @[24rem]:not-sr-only">Symbol</span>
          </span>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="mono min-w-0 truncate font-medium text-fg">{sym?.name ?? '–'}</span>
            {sym && <ItemBadge valid={sym.valid} exists={sym.exists} writes={willWrite(sym, choices.overwriteExisting)} changes={sym.pin_changes.length > 0} />}
            {sym && (
              <span className="hidden truncate text-2xs text-fg-subtle @[26rem]:inline">
                {SOURCE_LABEL[sym.source] ?? sym.source}
                {sym.part_count > 1 ? ` · ${sym.part_count} Teile` : ''} · {formatNumber(sym.pin_count)} Pins
              </span>
            )}
            {sym && sym.warnings.length > 0 && <WarnTip items={sym.warnings} />}
          </div>
          <Select
            size="sm"
            aria-label="Symbol wählen"
            value={symChoice.mode}
            onValueChange={(mode) => setSymbol({ mode, existing: mode === 'existing' ? symChoice.existing ?? null : null })}
            options={SYMBOL_MODES}
            className="h-7 w-auto shrink-0 gap-1 border-transparent bg-transparent px-1.5 text-2xs shadow-none hover:border-line-strong"
          />
        </div>
        {symChoice.mode === 'existing' && (
          <div className="px-3 py-2">
            <Combobox
              size="sm"
              mono
              aria-label="Vorhandenes Symbol"
              placeholder={library.isLoading ? 'Symbole werden geladen …' : 'Symbol aus der Bibliothek wählen …'}
              searchPlaceholder="Symbol suchen …"
              value={symChoice.existing ?? null}
              onValueChange={(v) => setSymbol({ existing: v })}
              options={(library.data ?? []).map((s) => ({
                value: s.name,
                label: s.name,
                description: `${s.pin_count} Pins${s.part_count > 1 ? ` · ${s.part_count} Teile` : ''}${s.usage ? ` · ${s.usage}× verwendet` : ''}`,
              }))}
            />
          </div>
        )}
        <div className="flex min-w-0 items-center gap-2 px-3 py-2">
          <span className="flex shrink-0 items-center gap-1.5 text-fg-subtle">
            <CircuitBoard aria-hidden className="size-3.5" />
            <span className="sr-only @[24rem]:not-sr-only">Footprint</span>
          </span>
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1">
            <span className="mono min-w-0 truncate font-medium text-fg">{fp?.name ?? '–'}</span>
            {fp && <ItemBadge valid={fp.valid} exists={fp.exists} writes={willWrite(fp, choices.overwriteExisting)} />}
            {fp && (
              <span className="hidden truncate text-2xs text-fg-subtle @[26rem]:inline">
                {fp.mode === 'manufacturer' ? 'Herstellerempfehlung' : fp.mode === 'existing' ? 'vorhanden' : 'IPC-7351B'}
                {fp.mode !== 'existing' && (pkgChoice?.density ?? fp.spec?.density) ? ` · ${pkgChoice?.density ?? fp.spec?.density}` : ''} ·{' '}
                {formatNumber(fp.pad_count)} Pads
              </span>
            )}
            {fp && fp.warnings.length > 0 && <WarnTip items={fp.warnings} />}
          </div>
          {landToggle}
        </div>
      </div>
    </div>
  )
}

function ItemBadge({ valid, exists, writes, changes }: { valid: boolean; exists: boolean; writes: boolean; changes?: boolean }) {
  if (!valid)
    return (
      <Badge variant="danger" size="sm">
        ungültig
      </Badge>
    )
  if (changes)
    return (
      <Badge variant="warning" size="sm">
        Pinbelegung neu
      </Badge>
    )
  if (!exists)
    return (
      <Badge variant="success" size="sm">
        neu
      </Badge>
    )
  return (
    <Badge size="sm" title={writes ? 'Registriert, wird beim Anlegen in die Bibliothek geschrieben' : undefined}>
      vorhanden
    </Badge>
  )
}

function WarnTip({ items }: { items: string[] }) {
  return (
    <TipButton
      tip={
        <ul className="flex max-w-80 flex-col gap-1">
          {items.slice(0, 6).map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      }
      label={`${items.length} Hinweise`}
      className="gap-0.5 rounded-sm text-2xs text-warning-text"
    >
      <TriangleAlert aria-hidden className="size-3" />
      {items.length}
    </TipButton>
  )
}
