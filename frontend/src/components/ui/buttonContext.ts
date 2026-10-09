import { createContext } from 'react'
import type { ButtonVariantProps } from './variants'

export interface ButtonDefaults {
  /** Standardgröße für Buttons ohne eigene `size` (z. B. „sm“ in der Topbar) */
  size?: ButtonVariantProps['size']
}

/** Vorgaben für alle Buttons darunter – `<PageActions>` setzt hier `size: 'sm'`. */
export const ButtonDefaultsContext = createContext<ButtonDefaults>({})
