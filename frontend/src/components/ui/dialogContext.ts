import { createContext, useContext, useEffect, useRef } from 'react'

export interface DialogContextValue {
  open: boolean
  setOpen: (open: boolean) => void
}

export const DialogContext = createContext<DialogContextValue>({ open: false, setOpen: () => {} })

/** Offen-Zustand des umgebenden <Dialog> (z. B. um ihn aus dem Inhalt heraus zu schließen). */
export function useDialog(): DialogContextValue {
  return useContext(DialogContext)
}

// --------------------------------------------------------------------------- Fokus zurückgeben

const OVERLAY = '[role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"]'

/** Zuletzt fokussiertes Element *außerhalb* von Overlays (Ziel, wenn ein Overlay ein anderes ablöst). */
let lastPageFocus: HTMLElement | null = null
if (typeof document !== 'undefined') {
  document.addEventListener(
    'focusin',
    (e) => {
      const t = e.target
      if (t instanceof HTMLElement && t !== document.body && !t.closest(OVERLAY)) lastPageFocus = t
    },
    true,
  )
}

/** Element, zu dem der Fokus nach dem Schließen eines Overlays zurückkehren soll. */
export function focusOrigin(): HTMLElement | null {
  const a = document.activeElement
  if (a instanceof HTMLElement && a !== document.body && !a.closest(OVERLAY)) return a
  // Fokus liegt in einem anderen (gerade schließenden) Overlay, z. B. der Befehlspalette → letzter Seitenfokus
  return lastPageFocus?.isConnected ? lastPageFocus : null
}

/**
 * Fokus nach dem Schließen an das zuvor fokussierte Element zurückgeben. Radix fokussiert sonst nur einen
 * <DialogTrigger> – Dialoge, die per Befehl/Store geöffnet werden, ließen den Fokus auf <body> fallen.
 */
export function useReturnFocus(open: boolean) {
  const previous = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (open) previous.current = focusOrigin()
  }, [open])
  return (event: Event) => {
    const target = previous.current
    previous.current = null
    if (target?.isConnected && !target.closest('[inert]')) {
      event.preventDefault()
      target.focus({ preventScroll: true })
    }
  }
}
