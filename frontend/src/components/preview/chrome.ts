/** Overlay-Flächen der Vorschau-Leinwände (Ton: „board“ = immer dunkel, „app“ = folgt dem Theme). */
import type { ChromeTone } from './types'

/** Glas-Fläche für Overlays (auf der Leiterplatte immer dunkel) */
export const CHROME_SURFACE: Record<ChromeTone, string> = {
  board:
    'border border-white/10 bg-[rgba(13,17,24,0.82)] text-[#D5DBE6] shadow-[0_8px_24px_-10px_rgba(0,0,0,.8)] backdrop-blur-md',
  app: 'border border-line-strong bg-[color-mix(in_oklab,var(--pf-surface)_88%,transparent)] text-fg shadow-raised backdrop-blur-md',
}

/** Gedämpfter Text auf der Overlay-Fläche (≥ 4,5:1) */
export const CHROME_MUTED: Record<ChromeTone, string> = {
  board: 'text-[#9AA4B6]',
  app: 'text-fg-muted',
}
