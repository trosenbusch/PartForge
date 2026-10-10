import { useI18n } from '@/lib/i18n'
import type { ReactNode } from 'react'
import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'

/**
 * Fokussierbarer Auslöser für einen erklärenden Tooltip (Abzeichen, Warnsymbole, Kürzel) – per Tastatur erreichbar,
 * ohne eigene Aktion. `navItem` = Teil einer Tabellenzeile mit einem einzigen Tab-Stopp (nur mit den Pfeiltasten
 * erreichbar, siehe `useRowNavigation`).
 */
export function TipButton({
  tip,
  label,
  children,
  className,
  side,
  navItem,
}: {
  tip: ReactNode
  /** Barrierefreier Name, wenn der Inhalt nur ein Symbol ist */
  label?: string
  children: ReactNode
  className?: string
  side?: 'top' | 'right' | 'bottom' | 'left'
  navItem?: boolean
}) {
  useI18n()
  return (
    <Tooltip content={tip} side={side}>
      <button
        type="button"
        aria-label={label}
        tabIndex={navItem ? -1 : undefined}
        data-nav-item={navItem ? '' : undefined}
        className={cn('inline-flex shrink-0 cursor-default items-center rounded-full outline-none focus-ring', className)}
      >
        {children}
      </button>
    </Tooltip>
  )
}
