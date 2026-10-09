import { motion, useReducedMotion } from 'motion/react'
import { Check, CircleAlert, Minus, TriangleAlert, X } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { StepInfo } from '../lib/analysis'

/**
 * Schritte der Analyse als vertikale Zeitleiste (aus `job.detail.steps`/`step`) – der aktive Schritt mit rotierendem
 * Funkenring. Wechsel und Abschluss sagt die Analyseansicht über ihre eigene Live-Region an.
 */
export function StepTimeline({ steps, live }: { steps: StepInfo[]; live: boolean }) {
  const reduce = useReducedMotion()
  return (
    <ol aria-label="Schritte der Analyse" className="relative flex flex-col">
      {steps.map((step, i) => {
        const last = i === steps.length - 1
        const doneLine = step.state === 'done' || step.state === 'warn'
        const stateText =
          step.state === 'done'
            ? 'erledigt'
            : step.state === 'warn'
              ? 'erledigt mit Hinweisen'
              : step.state === 'active'
                ? 'läuft'
                : step.state === 'error'
                  ? 'fehlgeschlagen'
                  : step.state === 'cancelled'
                    ? 'abgebrochen'
                    : 'ausstehend'
        return (
          <li key={step.key} className="relative flex gap-3.5 pb-5 last:pb-0" aria-current={step.state === 'active' ? 'step' : undefined}>
            {!last && (
              <span aria-hidden className="absolute bottom-0 left-[13px] top-7 w-px bg-line-strong">
                <motion.span
                  className="absolute inset-x-0 top-0 block bg-gradient-spark"
                  initial={false}
                  animate={{ height: doneLine ? '100%' : '0%' }}
                  transition={reduce ? { duration: 0 } : { duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                />
              </span>
            )}
            <StepDot state={step.state} index={i + 1} live={live} />
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-baseline gap-2">
                <span
                  className={cn(
                    'text-ui font-medium',
                    step.state === 'pending'
                      ? 'text-fg-subtle'
                      : step.state === 'error'
                        ? 'text-danger-text'
                        : step.state === 'cancelled'
                          ? 'text-fg-muted'
                          : 'text-fg',
                    step.state === 'active' && 'font-semibold',
                  )}
                >
                  {step.label}
                </span>
                <span className="sr-only">– {stateText}</span>
              </div>
              <p
                className={cn(
                  'mt-0.5 text-xs leading-snug',
                  step.state === 'active' ? 'text-spark-text' : step.detail ? 'text-fg-muted' : 'text-fg-subtle',
                )}
              >
                {step.state === 'active' && !step.detail
                  ? `${step.hint} …`
                  : step.state === 'cancelled'
                    ? 'Hier abgebrochen'
                    : (step.detail ?? step.hint)}
              </p>
              {step.notes.length > 0 && (
                <ul className="mt-1 flex flex-col gap-0.5">
                  {step.notes.slice(-3).map((n, k) => (
                    <li
                      key={k}
                      className={cn(
                        'flex items-start gap-1.5 text-2xs leading-4',
                        n.level === 'warn' ? 'text-warning-text' : n.level === 'error' ? 'text-danger-text' : 'text-fg-subtle',
                      )}
                    >
                      {n.level === 'warn' ? (
                        <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />
                      ) : n.level === 'error' ? (
                        <CircleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />
                      ) : (
                        <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-current" />
                      )}
                      <span className="line-clamp-2">{n.text}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function StepDot({ state, index, live }: { state: StepInfo['state']; index: number; live: boolean }) {
  if (state === 'active') {
    return (
      <span aria-hidden className="relative z-10 flex size-7 shrink-0 items-center justify-center">
        <span className={cn('absolute inset-0 rounded-full spark-border [--spark-fill:var(--pf-surface)]', !live && 'animate-none')} />
        <span className="relative size-2 rounded-full bg-gradient-spark shadow-[0_0_10px_color-mix(in_oklab,var(--pf-spark-b)_80%,transparent)]" />
      </span>
    )
  }
  return (
    <span
      aria-hidden
      className={cn(
        'relative z-10 flex size-7 shrink-0 items-center justify-center rounded-full border text-2xs font-semibold tabular-nums [&_svg]:size-3.5',
        state === 'done' && 'border-transparent bg-gradient-spark text-on-spark',
        state === 'warn' && 'border-warning/40 bg-warning/15 text-warning-text',
        state === 'error' && 'border-danger/40 bg-danger/12 text-danger-text',
        state === 'pending' && 'border-line-strong bg-surface text-fg-subtle',
        state === 'cancelled' && 'border-line-control bg-surface-3 text-fg-muted',
      )}
    >
      {state === 'done' ? (
        <Check />
      ) : state === 'warn' ? (
        <TriangleAlert />
      ) : state === 'error' ? (
        <X />
      ) : state === 'cancelled' ? (
        <Minus />
      ) : (
        index
      )}
    </span>
  )
}
