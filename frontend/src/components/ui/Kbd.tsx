import { useI18n } from '@/lib/i18n'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { formatHotkey, hotkeyLabels, type Hotkey } from '@/lib/hotkeys'

export interface KbdProps {
  /** Tastenkürzel in Hotkey-Schreibweise, z. B. 'mod+k' → „Strg K“ */
  hotkey?: Hotkey
  /** Alternativ einzelne Tasten */
  keys?: string[]
  children?: ReactNode
  size?: 'xs' | 'sm' | 'md'
  /** Für dunkle/farbige Hintergründe (z. B. im Primärbutton) */
  tone?: 'default' | 'inverse'
  /**
   * Standard: dekorativ (aria-hidden) – das Kürzel steckt bereits in `aria-keyshortcuts` des Controls
   * oder im umgebenden Text. `false` = für Screenreader als „Strg+K“ vorlesen.
   */
  decorative?: boolean
  className?: string
}

const keyClass = {
  xs: 'h-4 min-w-4 px-1 text-2xs rounded-sm',
  sm: 'h-5 min-w-5 px-1.5 text-2xs rounded-sm',
  md: 'h-6 min-w-6 px-1.5 text-xs rounded-md',
}

/** Tastenkappe(n): <Kbd hotkey="mod+k" /> oder <Kbd>Esc</Kbd> */
export function Kbd({ hotkey, keys, children, size = 'sm', tone = 'default', decorative = true, className }: KbdProps) {
  useI18n()
  const list = hotkey ? hotkeyLabels(hotkey) : keys
  const cap = cn(
    'inline-flex select-none items-center justify-center font-sans font-medium leading-none tabular-nums',
    keyClass[size],
    tone === 'default'
      ? 'border border-line-strong bg-surface-2 text-fg-muted shadow-[inset_0_-1px_0_var(--pf-line-strong)]'
      : 'bg-black/15 text-current',
  )
  const spoken = hotkey ? formatHotkey(hotkey) : list ? list.join('+') : null
  const caps = list ? (
    list.map((k, i) => (
      <kbd key={`${k}-${i}`} className={cap}>
        {k}
      </kbd>
    ))
  ) : (
    <kbd className={cap}>{children}</kbd>
  )
  return (
    <span className={cn('inline-flex items-center gap-0.5', className)} aria-hidden={decorative || undefined}>
      {decorative || !spoken ? caps : <span aria-hidden>{caps}</span>}
      {!decorative && spoken && <span className="sr-only">{spoken}</span>}
    </span>
  )
}
