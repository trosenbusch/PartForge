import type { ReactNode } from 'react'
import { create } from 'zustand'

export interface ConfirmOptions {
  title: ReactNode
  description?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** Rote Bestätigung (Löschen etc.) */
  destructive?: boolean
  icon?: ReactNode
  /** Asynchrone Aktion – Dialog bleibt mit Spinner offen, bis sie fertig ist */
  onConfirm?: () => Promise<unknown> | unknown
}

interface ConfirmState {
  current: (ConfirmOptions & { resolve: (ok: boolean) => void }) | null
  open: boolean
}

export const useConfirmStore = create<ConfirmState>(() => ({ current: null, open: false }))

/**
 * Bestätigungsdialog per Promise (benötigt <ConfirmHost/> in der App-Shell – ist eingebaut):
 *   if (await confirm({ title: '3 Bauteile löschen?', destructive: true, confirmLabel: 'Löschen' })) …
 */
export function confirm(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    useConfirmStore.getState().current?.resolve(false)
    useConfirmStore.setState({ current: { ...options, resolve }, open: true })
  })
}

/** Hook-Variante (identisch zu `confirm`) */
export function useConfirm(): typeof confirm {
  return confirm
}
