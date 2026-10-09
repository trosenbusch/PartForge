/** Gemeinsame Typen der Vorschau-Leinwände. */

/** Steuerung einer Leinwand von außen (Werkzeugleiste der PreviewPanel, Tastenkürzel) */
export interface CanvasHandle {
  /** Inhalt einpassen (animiert) */
  fit: () => void
  zoomIn: () => void
  zoomOut: () => void
}

/** Darstellung der Symbol-Leinwand: „auto“ folgt dem App-Theme, „altium“ zeigt das Symbol wie im Schaltplan-Editor */
export type SymbolCanvasTheme = 'auto' | 'altium'

/** Tonalität der Overlays: „board“ = immer dunkel (Leiterplatte, 3D), „app“ = folgt dem Theme */
export type ChromeTone = 'board' | 'app'
