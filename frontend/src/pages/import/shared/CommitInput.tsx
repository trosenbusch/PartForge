import { useI18n } from '@/lib/i18n'
import { useEffect, useRef, useState, type InputHTMLAttributes, type KeyboardEvent, type Ref } from 'react'
import { Input, type InputProps } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDecimal, parseDecimal } from '@/lib/format'
import { clearActiveFlush, setActiveFlush } from './activeInput'

/**
 * Eingabe, die erst beim Verlassen oder mit Enter übernimmt; Esc verwirft. Externe Änderungen erscheinen sofort.
 * `display`: Anzeige ohne Fokus (z. B. „0,8 mm“ für den gespeicherten Text „0.8mm“) – bearbeitet wird immer der Rohtext.
 */
function useCommitText(value: string, onCommit: (value: string) => void, display?: (value: string) => string) {
  const [draft, setDraft] = useState<string | null>(null)
  const cancelled = useRef(false)
  const latest = useRef({ draft, value, onCommit })
  useEffect(() => {
    latest.current = { draft, value, onCommit }
  })
  const flush = useRef(() => {
    const { draft: text, value: current, onCommit: commit } = latest.current
    if (text === null) return
    latest.current = { ...latest.current, draft: null }
    setDraft(null)
    if (text !== current) commit(text)
  })
  useEffect(() => {
    const own = flush.current
    return () => clearActiveFlush(own)
  }, [])
  return {
    value: draft ?? (display && value ? display(value) : value),
    onFocus: () => {
      cancelled.current = false
      setDraft(value)
      setActiveFlush(flush.current)
    },
    onChange: (text: string) => {
      latest.current = { ...latest.current, draft: text }
      setDraft(text)
    },
    onBlur: () => {
      clearActiveFlush(flush.current)
      const text = draft
      setDraft(null)
      if (!cancelled.current && text !== null && text !== value) onCommit(text)
      cancelled.current = false
    },
    onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => {
      // nur Enter ohne Strg/⌘/Alt übernimmt hier – Strg+Enter gehört „Bauteile anlegen“
      if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        e.preventDefault()
        e.currentTarget.blur()
      } else if (e.key === 'Escape') {
        cancelled.current = true
        e.currentTarget.blur()
      }
    },
  }
}

export interface CommitInputProps extends Omit<InputProps, 'value' | 'defaultValue' | 'onChange' | 'onBlur' | 'onFocus'> {
  value: string
  onCommit: (value: string) => void
  /** Anzeige ohne Fokus (formatiert) – beim Bearbeiten steht der Rohtext im Feld */
  display?: (value: string) => string
}

/** UI-Eingabefeld mit Übernahme beim Verlassen (Formulare der Prüfansicht). */
export function CommitInput({ value, onCommit, onKeyDown, display, ...props }: CommitInputProps) {
  useI18n()
  const c = useCommitText(value, onCommit, display)
  return (
    <Input
      {...props}
      value={c.value}
      onFocus={c.onFocus}
      onChange={(e) => c.onChange(e.target.value)}
      onBlur={c.onBlur}
      onKeyDown={(e) => {
        c.onKeyDown(e)
        onKeyDown?.(e)
      }}
    />
  )
}

export interface CellInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'value' | 'defaultValue' | 'onChange'> {
  value: string
  onCommit: (value: string) => void
  mono?: boolean
  invalid?: boolean
  ref?: Ref<HTMLInputElement>
}

/** Randlose Tabellenzelle zum Bearbeiten (Rahmen erst bei Hover/Fokus). */
export function CellInput({ value, onCommit, mono, invalid, className, onKeyDown, onBlur, onFocus, ref, ...props }: CellInputProps) {
  useI18n()
  const c = useCommitText(value, onCommit)
  return (
    <input
      {...props}
      ref={ref}
      value={c.value}
      onFocus={(e) => {
        c.onFocus()
        onFocus?.(e)
      }}
      onChange={(e) => c.onChange(e.target.value)}
      onBlur={(e) => {
        c.onBlur()
        onBlur?.(e)
      }}
      onKeyDown={(e) => {
        c.onKeyDown(e)
        onKeyDown?.(e)
      }}
      aria-invalid={invalid || undefined}
      spellCheck={false}
      autoComplete="off"
      className={cn(
        'h-7 w-full min-w-0 rounded-md border border-transparent bg-transparent px-1.5 text-xs text-fg outline-none transition-[background-color,border-color]',
        'placeholder:text-fg-subtle hover:border-line-strong hover:bg-control focus:border-accent focus:bg-control focus:shadow-[0_0_0_3px_var(--pf-accent-soft)]',
        mono && 'mono',
        invalid && 'border-danger/60',
        className,
      )}
    />
  )
}

export interface NumberCellProps extends Omit<CellInputProps, 'value' | 'onCommit'> {
  value: number | null | undefined
  onCommit: (value: number | null) => void
  digits?: number
}

/** Zahl in einer Tabellenzelle (deutsche Eingabe „0,95“, leer = keine Angabe). */
export function NumberCell({ value, onCommit, digits = 3, ...props }: NumberCellProps) {
  useI18n()
  const text = value === null || value === undefined ? '' : formatDecimal(value, digits)
  return (
    <CellInput
      {...props}
      mono
      inputMode="decimal"
      value={text}
      onCommit={(t) => {
        if (!t.trim()) return onCommit(null)
        const n = parseDecimal(t)
        if (n !== null) onCommit(n)
      }}
    />
  )
}
