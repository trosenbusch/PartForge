import { motion } from 'motion/react'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface StepDef {
  id: string
  label: string
  description?: string
  icon?: ReactNode
}

export interface StepperProps {
  steps: StepDef[]
  /** Index des aktuellen Schritts */
  current: number
  /** Klick auf einen bereits erledigten Schritt (zurückspringen) */
  onStepClick?: (index: number) => void
  /** Beschreibungen ausblenden (kompakt) */
  compact?: boolean
  className?: string
}

/**
 * Assistenten-Schritte mit animierter Verbindungslinie.
 *
 * Breite: Jeder Schritt ist so breit wie Kreis + Beschriftung + kürzeste Linie (`flex-auto`); Platz darüber hinaus
 * bekommen die Linien zu gleichen Teilen. Wird es eng, schrumpfen zuerst die Linien bis auf ihre Mindestlänge – erst
 * danach wird eine Beschriftung gekürzt (früher waren alle Schritte gleich breit: lange Namen wie „Kategorie“ wurden
 * gekürzt, während neben kurzen noch lange Linien standen).
 */
export function Stepper({ steps, current, onStepClick, compact, className }: StepperProps) {
  return (
    <ol className={cn('flex w-full items-center', className)} aria-label="Fortschritt">
      {steps.map((step, i) => {
        const done = i < current
        const active = i === current
        const clickable = Boolean(onStepClick) && done
        const content = (
          <>
            <span
              className={cn(
                'relative flex size-8 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums transition-all duration-300',
                done && 'border-accent/30 bg-accent-soft text-accent',
                active &&
                  'border-transparent bg-gradient-forge text-on-accent shadow-[0_0_0_4px_var(--pf-accent-soft),0_6px_18px_-6px_var(--pf-ember-strong)]',
                !done && !active && 'border-line-strong bg-surface-2 text-fg-subtle',
              )}
            >
              {done ? (
                <motion.span initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 26 }}>
                  <Check className="size-4" strokeWidth={2.25} />
                </motion.span>
              ) : (
                (step.icon ?? i + 1)
              )}
            </span>
            <span className="flex min-w-0 flex-col text-left">
              <span
                className={cn(
                  'truncate text-ui font-medium transition-colors',
                  active ? 'text-fg' : done ? 'text-fg-muted' : 'text-fg-subtle',
                )}
              >
                {step.label}
              </span>
              {!compact && step.description && (
                <span className="truncate text-2xs text-fg-subtle">{step.description}</span>
              )}
            </span>
          </>
        )
        return (
          <li
            key={step.id}
            className={cn('flex min-w-0 items-center', i < steps.length - 1 && 'flex-auto')}
            aria-current={active ? 'step' : undefined}
          >
            {clickable ? (
              <button
                type="button"
                onClick={() => onStepClick?.(i)}
                className="flex min-w-0 items-center gap-3 rounded-button p-1 pr-2 outline-none transition-colors hover:bg-surface-2 focus-ring"
              >
                {content}
              </button>
            ) : (
              <div className="flex min-w-0 items-center gap-3 p-1 pr-2">{content}</div>
            )}
            {i < steps.length - 1 && (
              // kürzeste Linie 16 px (+ je 8 px Abstand): erst dann wird eine Beschriftung gekürzt
              <div aria-hidden className="relative mx-2 h-px min-w-4 flex-1 overflow-hidden rounded-full bg-line-strong">
                <motion.div
                  className="absolute inset-0 origin-left bg-gradient-forge"
                  initial={false}
                  animate={{ scaleX: done ? 1 : 0 }}
                  transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
                />
              </div>
            )}
          </li>
        )
      })}
    </ol>
  )
}
