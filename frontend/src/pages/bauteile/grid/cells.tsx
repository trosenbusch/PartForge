import { useI18n } from '@/lib/i18n'
/**
 * Zellen der Bauteiltabelle, die über die geteilten Renderer hinausgehen: Teilenummer (mit „neu“-Markierung),
 * Datenblatt (URL oder Datei der Bibliothek), Bibliothekspfade („Im Explorer zeigen“), Ja/Nein und
 * der Kopf der Auswahlspalte (alle geladenen Zeilen wählen – die Infinite-Row-Model-Tabelle kennt kein „Alle“).
 */
import type { CustomCellRendererProps, CustomHeaderProps } from 'ag-grid-react'
import { Check, ExternalLink, FileText, FolderOpen, Minus } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { PartRow } from '@/api/parts'
import { useWorkspace } from '@/api/system'
import { linkLabel } from '@/components/grid/cellFormat'
import { cn } from '@/lib/cn'
import { baseName } from '@/lib/format'
import { revealPath, useNativeBridge } from '@/lib/native'
import { isHttpUrl, openDatasheet, pathLabel, resolveLibraryPath } from '../model/links'

const EMPTY = <span className="text-fg-subtle">–</span>

// --------------------------------------------------------------------------- Teilenummer

export interface PartNumberCellParams {
  /** Teilenummern, die gerade angelegt wurden (dezente Markierung) */
  isNew?: (pn: string) => boolean
}

export function PartNumberCell({ value, isNew }: CustomCellRendererProps<PartRow> & PartNumberCellParams) {
  const { t } = useI18n()
  if (value === null || value === undefined || value === '') return EMPTY
  const pn = String(value)
  return (
    <span className="pf-cell-inline min-w-0 gap-2">
      <span className="mono truncate font-medium text-fg">{pn}</span>
      {isNew?.(pn) && (
        <span className="shrink-0 rounded-full border border-accent/30 bg-accent-soft px-1.5 text-2xs font-medium leading-4 text-accent-text">
          {t("neu")}
        </span>
      )}
    </span>
  )
}

// --------------------------------------------------------------------------- Datenblatt / Pfad

export function DatasheetCell({ value }: CustomCellRendererProps<PartRow>) {
  const { t } = useI18n()
  const root = useWorkspace().data?.root
  const native = useNativeBridge()
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  if (isHttpUrl(text)) {
    return (
      <a
        href={text}
        target="_blank"
        rel="noreferrer noopener"
        tabIndex={-1}
        title={text}
        onClick={(e) => e.stopPropagation()}
        className="group/link pf-cell-inline min-w-0 gap-1.5 text-accent-text underline-offset-2 hover:underline"
      >
        <ExternalLink aria-hidden className="size-3.5 shrink-0 opacity-70 group-hover/link:opacity-100" />
        <span className="truncate">{linkLabel(text)}</span>
      </a>
    )
  }
  const label = baseName(text.replace(/\\/g, '/'))
  if (!native.canOpenPath) {
    return (
      <span title={text} className="pf-cell-inline min-w-0 gap-1.5 text-fg-muted">
        <FileText aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
        <span className="truncate">{label}</span>
      </span>
    )
  }
  return (
    <button
      type="button"
      tabIndex={-1}
      title={t("{1} – öffnen", { 1: text })}
      onClick={(e) => {
        e.stopPropagation()
        void openDatasheet(text, root)
      }}
      className="pf-cell-inline min-w-0 gap-1.5 text-accent-text hover:underline"
    >
      <FileText aria-hidden className="size-3.5 shrink-0 opacity-80" />
      <span className="truncate">{label}</span>
    </button>
  )
}

/**
 * Bibliothekspfad (Library Path, Footprint Path …): Klick bzw. Enter zeigt die Datei markiert im Explorer – außerhalb
 * des Desktop-Programms kopiert `revealPath` den Pfad (mit Hinweis).
 */
export function LibraryPathCell({ value, colDef }: CustomCellRendererProps<PartRow>) {
  const { t } = useI18n()
  const root = useWorkspace().data?.root
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  const label = baseName(text.replace(/\\/g, '/'))
  return (
    <button
      type="button"
      tabIndex={-1}
      title={t("{1} – im Explorer zeigen", { 1: text })}
      onClick={(e) => {
        e.stopPropagation()
        void revealPath(resolveLibraryPath(root, text), { what: pathLabel(colDef?.colId ?? '') })
      }}
      className="pf-cell-inline min-w-0 gap-1.5 hover:text-accent-text"
    >
      <FolderOpen aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
      <span className="truncate">{label}</span>
    </button>
  )
}

// --------------------------------------------------------------------------- Ja/Nein

const YES = new Set(['ja', 'yes', 'true', '1', 'wahr', 'x'])
const NO = new Set(['nein', 'no', 'false', '0', 'falsch'])

export function BoolCell({ value }: CustomCellRendererProps<PartRow>) {
  const { t } = useI18n()
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value).trim().toLowerCase()
  if (YES.has(text)) {
    return (
      <span className="pf-cell-inline gap-1.5 text-fg">
        <Check aria-hidden className="size-3.5 text-success" />
        {t("Ja")}
      </span>
    )
  }
  if (NO.has(text)) {
    return (
      <span className="pf-cell-inline gap-1.5 text-fg-muted">
        <Minus aria-hidden className="size-3.5 text-fg-subtle" />
        {t("Nein")}
      </span>
    )
  }
  return <span>{String(value)}</span>
}

// --------------------------------------------------------------------------- Kopf der Auswahlspalte

type CheckState = 'none' | 'some' | 'all'

function loadedSelectionState(api: CustomHeaderProps<PartRow>['api']): CheckState {
  let loaded = 0
  let selected = 0
  api.forEachNode((node) => {
    if (!node.data) return
    loaded += 1
    if (node.isSelected()) selected += 1
  })
  if (!selected) return 'none'
  return selected === loaded ? 'all' : 'some'
}

/**
 * „Alle auswählen“ für das Infinite Row Model (AG Grid bietet dort keine Kopf-Checkbox): wählt alle geladenen
 * Zeilen – die Leiste unten bietet danach „Alle Treffer auswählen“ an.
 */
export function SelectAllHeader({ api, eGridHeader }: CustomHeaderProps<PartRow>) {
  const { t } = useI18n()
  const [state, setState] = useState<CheckState>('none')
  const stateRef = useRef<CheckState>('none')
  useEffect(() => {
    stateRef.current = state
  }, [state])
  useEffect(() => {
    const update = () => setState(loadedSelectionState(api))
    update()
    api.addEventListener('selectionChanged', update)
    api.addEventListener('modelUpdated', update)
    return () => {
      if (api.isDestroyed()) return
      api.removeEventListener('selectionChanged', update)
      api.removeEventListener('modelUpdated', update)
    }
  }, [api])
  const toggle = useCallback(() => {
    const select = stateRef.current !== 'all'
    const nodes: Parameters<typeof api.setNodesSelected>[0]['nodes'] = []
    api.forEachNode((node) => {
      if (node.data) nodes.push(node)
    })
    api.setNodesSelected({ nodes, newValue: select, source: 'uiSelectAll' })
  }, [api])
  // Tastatur: Fokus liegt beim Navigieren auf der Kopfzelle – Leertaste/Enter schalten um
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' && e.key !== 'Enter') return
      e.preventDefault()
      toggle()
    }
    eGridHeader.addEventListener('keydown', onKey)
    eGridHeader.setAttribute('aria-label', t("Auswahl: alle geladenen Zeilen (Leertaste)"))
    return () => eGridHeader.removeEventListener('keydown', onKey)
  }, [eGridHeader, toggle, t])
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={state === 'all' ? true : state === 'some' ? 'mixed' : false}
      aria-label={t("Alle geladenen Zeilen auswählen")}
      tabIndex={-1}
      onClick={toggle}
      className={cn(
        'flex size-4 items-center justify-center rounded-sm border outline-none transition-colors focus-ring',
        state === 'none' ? 'border-line-control bg-control hover:border-line-control-hover' : 'border-transparent bg-accent text-on-accent',
      )}
    >
      {state === 'all' && <Check aria-hidden className="size-3" strokeWidth={3} />}
      {state === 'some' && <Minus aria-hidden className="size-3" strokeWidth={3} />}
    </button>
  )
}
