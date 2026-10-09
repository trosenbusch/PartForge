/**
 * AG-Grid-Theme „Forge“ (Theming-API v36, Quartz-Basis) – alle Farben als CSS-Variablen des Designsystems.
 * Dadurch folgt die Tabelle dem App-Theme ohne Neuaufbau (data-theme="dark|light" auf <html>).
 * Dichte: kompakt (32 px Zeilen); Werte-/MPN-Spalten mit `cellClass: 'pf-cell-mono'` bzw. `type: 'mono'`.
 */
import { iconSetQuartz, themeQuartz } from 'ag-grid-community'

const SANS = ['Inter Variable', 'Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'sans-serif']

export const forgeGridTheme = themeQuartz.withPart(iconSetQuartz({ strokeWidth: 1.75 })).withParams({
  browserColorScheme: 'inherit',
  fontFamily: SANS,
  headerFontFamily: SANS,
  fontSize: 13,
  dataFontSize: 13,
  headerFontSize: 12,
  headerFontWeight: 600,

  foregroundColor: 'var(--pf-fg)',
  textColor: 'var(--pf-fg)',
  subtleTextColor: 'var(--pf-fg-subtle)',
  backgroundColor: 'var(--pf-surface)',
  chromeBackgroundColor: 'var(--pf-surface)',
  headerBackgroundColor: 'color-mix(in oklab, var(--pf-surface-2) 60%, var(--pf-surface))',
  headerTextColor: 'var(--pf-fg-muted)',
  headerCellHoverBackgroundColor: 'color-mix(in oklab, var(--pf-fg) 5%, transparent)',
  headerColumnBorder: { color: 'var(--pf-line)' },
  headerColumnBorderHeight: '44%',
  headerColumnResizeHandleColor: 'var(--pf-line-strong)',
  headerRowBorder: { color: 'var(--pf-line-strong)' },

  borderColor: 'var(--pf-line)',
  rowBorder: { color: 'var(--pf-line)' },
  columnBorder: false,
  wrapperBorder: false,
  wrapperBorderRadius: 0,
  borderRadius: 8,

  accentColor: 'var(--pf-accent)',
  rowHoverColor: 'color-mix(in oklab, var(--pf-fg) 4.5%, transparent)',
  selectedRowBackgroundColor: 'var(--pf-accent-soft)',
  oddRowBackgroundColor: 'color-mix(in oklab, var(--pf-fg) 1.4%, transparent)',
  rangeSelectionBorderColor: 'var(--pf-accent)',
  rowLoadingSkeletonEffectColor: 'var(--pf-shimmer-b)',

  rowHeight: 32,
  headerHeight: 34,
  spacing: 6,
  cellHorizontalPadding: 12,
  iconSize: 14,
  iconColor: 'var(--pf-fg-subtle)',

  checkboxBorderRadius: 4,
  checkboxBorderWidth: 1,
  checkboxCheckedBackgroundColor: 'var(--pf-accent)',
  checkboxCheckedBorderColor: 'var(--pf-accent)',
  checkboxCheckedShapeColor: 'var(--pf-on-accent)',
  checkboxIndeterminateBackgroundColor: 'var(--pf-accent)',
  checkboxIndeterminateBorderColor: 'var(--pf-accent)',
  checkboxIndeterminateShapeColor: 'var(--pf-on-accent)',
  checkboxUncheckedBackgroundColor: 'var(--pf-control-bg)',
  checkboxUncheckedBorderColor: 'var(--pf-line-control)',

  inputBackgroundColor: 'var(--pf-control-bg)',
  inputBorder: { color: 'var(--pf-line-control)' },
  inputFocusBorder: { color: 'var(--pf-accent)' },
  inputFocusShadow: '0 0 0 3px var(--pf-accent-soft)',
  inputBorderRadius: 8,
  inputHeight: 28,
  inputTextColor: 'var(--pf-fg)',
  inputPlaceholderTextColor: 'var(--pf-fg-subtle)',
  inputIconColor: 'var(--pf-fg-subtle)',

  menuBackgroundColor: 'var(--pf-surface-2)',
  menuBorder: { color: 'var(--pf-line-strong)' },
  menuTextColor: 'var(--pf-fg)',
  menuShadow: 'var(--pf-shadow-pop)',
  menuSeparatorColor: 'var(--pf-line)',
  panelBackgroundColor: 'var(--pf-surface-2)',
  popupShadow: 'var(--pf-shadow-pop)',
  dropdownShadow: 'var(--pf-shadow-pop)',
  cardShadow: 'var(--pf-shadow-raised)',
  dialogBorder: { color: 'var(--pf-line-strong)' },
  modalOverlayBackgroundColor: 'var(--pf-overlay)',
  tooltipBackgroundColor: 'var(--pf-surface-3)',
  tooltipTextColor: 'var(--pf-fg)',
  tooltipBorder: { color: 'var(--pf-line-strong)' },
  focusShadow: '0 0 0 2px var(--pf-accent)',
  dragHandleColor: 'var(--pf-fg-subtle)',
  columnDragIndicatorColor: 'var(--pf-accent)',
  rowDragIndicatorColor: 'var(--pf-accent)',
  toggleButtonOnBackgroundColor: 'var(--pf-accent)',
  toggleButtonOffBackgroundColor: 'var(--pf-surface-3)',

  buttonBackgroundColor: 'var(--pf-surface-2)',
  buttonBorder: { color: 'var(--pf-line-strong)' },
  buttonBorderRadius: 8,
  buttonHoverBackgroundColor: 'var(--pf-surface-3)',
  buttonTextColor: 'var(--pf-fg)',
})

/** Höhen der Dichtestufen (px) */
export const GRID_DENSITY = {
  compact: { rowHeight: 32, headerHeight: 34 },
  comfortable: { rowHeight: 40, headerHeight: 38 },
} as const

export type GridDensity = keyof typeof GRID_DENSITY
