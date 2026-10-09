/**
 * Karten als Radiogruppe (WAI-ARIA): Pfeiltasten wählen die nächste/vorige Karte, Pos1/Ende die erste/letzte,
 * Leertaste wählt, Enter wählt und bestätigt (z. B. „weiter“), Klick wählt (optional auch bestätigen).
 */
import { useCallback, useRef, type KeyboardEvent } from 'react'

export interface RadioCardsOptions {
  keys: string[]
  value: string | null
  onChange: (key: string) => void
  /** Enter, Doppelklick – bzw. Klick mit `activateOnClick` */
  onActivate?: (key: string) => void
  activateOnClick?: boolean
}

export function useRadioCards({ keys, value, onChange, onActivate, activateOnClick }: RadioCardsOptions) {
  const refs = useRef(new Map<string, HTMLElement>())
  const focusKey = value && keys.includes(value) ? value : keys[0]

  const focus = useCallback((key: string) => {
    refs.current.get(key)?.focus()
  }, [])
  /** DOM-Element einer Karte (z. B. zum Hinscrollen) */
  const element = useCallback((key: string) => refs.current.get(key), [])

  const radioProps = (key: string) => {
    const index = keys.indexOf(key)
    return {
      role: 'radio' as const,
      'aria-checked': key === value,
      tabIndex: key === focusKey ? 0 : -1,
      ref: (el: HTMLElement | null) => {
        if (el) refs.current.set(key, el)
        else refs.current.delete(key)
      },
      onClick: () => {
        onChange(key)
        if (activateOnClick) onActivate?.(key)
      },
      onDoubleClick: () => {
        if (!activateOnClick) onActivate?.(key)
      },
      onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
        let next: number | null = null
        if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (index + 1) % keys.length
        else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (index - 1 + keys.length) % keys.length
        else if (e.key === 'Home') next = 0
        else if (e.key === 'End') next = keys.length - 1
        if (next !== null) {
          e.preventDefault()
          const k = keys[next]
          onChange(k)
          focus(k)
          return
        }
        // Strg+Enter gehört der Seite („Weiter“) – sonst ginge es zwei Schritte vor
        if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.altKey && !e.shiftKey) {
          e.preventDefault()
          onChange(key)
          onActivate?.(key)
        } else if (e.key === ' ') {
          e.preventDefault()
          onChange(key)
        }
      },
    }
  }
  return { radioProps, focus, element }
}
