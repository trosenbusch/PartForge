import { createContext, useContext } from 'react'

export interface FieldContextValue {
  id: string
  /**
   * ID des sichtbaren Labels – für Controls, die kein `<label for>` verstehen (Radiogruppen wie `SegmentedControl`,
   * Regler): `aria-labelledby={field.labelId}`
   */
  labelId?: string
  describedBy?: string
  invalid: boolean
  disabled?: boolean
  /** Pflichtfeld – Controls setzen `aria-required` */
  required?: boolean
}

/**
 * Verdrahtung Label ↔ Control. `<Field>` stellt ihn bereit; eigene Controls (z. B. ein Editor aus mehreren
 * Elementen) lesen ihn mit `useFieldContext()`. Zum Abschalten innerhalb eines Feldes (verschachtelte Controls,
 * die nicht das beschriftete Element sind): `<FieldContext.Provider value={null}>`.
 */
export const FieldContext = createContext<FieldContextValue | null>(null)

/** Von Input/Select/Combobox/Textarea/Switch/Checkbox/NumberInput genutzt: id, aria-describedby, invalid, required. */
export function useFieldContext(): FieldContextValue | null {
  return useContext(FieldContext)
}
