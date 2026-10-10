import { useI18n } from '@/lib/i18n'
import type { IOverlayParams } from 'ag-grid-community'
import type { ReactNode } from 'react'
import { EmptyState, Spinner, type IllustrationName } from '@/components/ui'

export interface GridEmptyState {
  title: ReactNode
  description?: ReactNode
  illustration?: IllustrationName
  /** Nächste Aktion(en), z. B. „Bauteil anlegen“ (secondary) */
  actions?: ReactNode
}

export interface GridOverlayParams {
  empty?: GridEmptyState
  noMatch?: GridEmptyState
  loadingText?: string
}

/** Ein Overlay für alle Fälle (AG Grid `overlayComponent`, Typ über `overlayType`) */
export function GridOverlay(props: IOverlayParams & GridOverlayParams) {
  const { t: tr } = useI18n()
  if (props.overlayType === 'noRows' || props.overlayType === 'noMatchingRows') {
    const state: GridEmptyState =
      props.overlayType === 'noRows'
        ? (props.empty ?? { title: tr("Keine Einträge"), description: tr("Hier ist noch nichts vorhanden."), illustration: 'no-parts' as const })
        : (props.noMatch ?? {
            title: tr("Keine Treffer"),
            description: tr("Kein Eintrag passt zu Suche oder Filter."),
            illustration: 'search-empty' as const,
          })
    return (
      <div className="pointer-events-auto">
        <EmptyState
          size="sm"
          illustration={state.illustration}
          title={state.title}
          description={state.description}
          actions={state.actions}
        />
      </div>
    )
  }
  return (
    <div
      role="status"
      className="pointer-events-auto flex items-center gap-2.5 rounded-full border border-line-strong bg-surface px-4 py-2 text-ui text-fg-muted shadow-raised"
    >
      <Spinner size={15} tone="accent" />
      {props.overlayType === 'exporting' ? tr("Export läuft …") : (props.loadingText ?? tr("Lädt …"))}
    </div>
  )
}
