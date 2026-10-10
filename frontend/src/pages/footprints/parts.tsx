import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Kleine Bausteine des Footprint-Moduls: Abschnittskopf, aufleuchtende Messwerte, Kopierknopf.
 */
import { Check, Copy } from 'lucide-react'
import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { IconButton } from '@/components/ui'
import { cn } from '@/lib/cn'

/** Mikro-Überschrift eines Abschnitts mit optionalen Aktionen rechts */
export function SectionLabel({
  children,
  icon,
  actions,
  id,
  as: Tag = 'h3',
  className,
}: {
  children: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  id?: string
  as?: 'h2' | 'h3' | 'h4'
  className?: string
}) {
  return (
    <div className={cn('flex min-h-6 items-center gap-2', className)}>
      {icon && <span aria-hidden className="flex text-fg-subtle [&_svg]:size-3.5">{icon}</span>}
      <Tag id={id} className="micro-label">
        {children}
      </Tag>
      {actions && <div className="ml-auto flex items-center gap-1">{actions}</div>}
    </div>
  )
}

/**
 * Messwert, der bei Änderung kurz aufleuchtet (Kupfer-Schimmer) – „sofortiges Feedback“ des Generators.
 * `value` bestimmt, wann geleuchtet wird (z. B. der formatierte Text).
 */
export function FlashValue({ value, children, className }: { value: string; children?: ReactNode; className?: string }) {
  const reduce = useReducedMotion()
  const [tick, setTick] = useState(0)
  const [prev, setPrev] = useState(value)
  if (prev !== value) {
    setPrev(value)
    setTick((t) => t + 1)
  }
  return (
    <span className={cn('relative inline-block rounded-sm', className)}>
      {tick > 0 && !reduce && (
        <motion.span
          key={tick}
          aria-hidden
          className="pointer-events-none absolute -inset-x-1 -inset-y-0.5 rounded-md bg-accent-soft"
          initial={{ opacity: 1 }}
          animate={{ opacity: 0 }}
          transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
        />
      )}
      <span className="relative">{children ?? value}</span>
    </span>
  )
}

/** Text in die Zwischenablage kopieren (Häkchen als Bestätigung) */
export function CopyButton({ text, label, className }: { text: string | null | undefined; label: string; className?: string }) {
  useI18n()
  const [done, setDone] = useState(false)
  useEffect(() => {
    if (!done) return
    const t = window.setTimeout(() => setDone(false), 1400)
    return () => window.clearTimeout(t)
  }, [done])
  return (
    <IconButton
      size="xs"
      label={done ? tr('Kopiert') : label}
      icon={done ? <Check className="text-success-text" /> : <Copy />}
      disabled={!text}
      className={className}
      onClick={async () => {
        if (!text) return
        try {
          await navigator.clipboard.writeText(text)
          setDone(true)
        } catch {
          toast.error(tr('Kopieren nicht möglich'), { description: tr('Die Zwischenablage ist in diesem Fenster gesperrt.') })
        }
      }}
    />
  )
}
