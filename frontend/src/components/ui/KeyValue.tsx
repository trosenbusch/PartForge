import { useI18n } from '@/lib/i18n'
import { Check, Copy } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { cn } from '@/lib/cn'

export interface KeyValueItem {
  label: ReactNode
  value: ReactNode
  /** Monospace-Wert (MPN, Pfad, Maß) */
  mono?: boolean
  /** Kopierbarer Text (zeigt Kopier-Button beim Hover) */
  copy?: string
  hint?: ReactNode
}

export interface KeyValueListProps {
  items: KeyValueItem[]
  /** Breite der Label-Spalte */
  labelWidth?: string
  dense?: boolean
  className?: string
}

function CopyButton({ text }: { text: string }) {
  const { t: tr } = useI18n()
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      aria-label={tr("Kopieren")}
      onClick={() => {
        void navigator.clipboard
          ?.writeText(text)
          .then(() => {
            setDone(true)
            setTimeout(() => setDone(false), 1200)
          })
          .catch(() => toast.error(tr("Kopieren nicht möglich")))
      }}
      className="ml-1 inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-fg-subtle opacity-0 outline-none transition-opacity hover:bg-surface-3 hover:text-fg focus-ring focus-visible:opacity-100 group-hover/kv:opacity-100"
    >
      {done ? <Check className="size-3 text-success" /> : <Copy className="size-3" />}
    </button>
  )
}

/** Beschriftete Werte als Definitionsliste. */
export function KeyValueList({ items, labelWidth = '9rem', dense, className }: KeyValueListProps) {
  useI18n()
  return (
    <dl
      className={cn('grid gap-x-4', dense ? 'gap-y-1.5' : 'gap-y-2.5', className)}
      style={{ gridTemplateColumns: `${labelWidth} minmax(0,1fr)` }}
    >
      {items.map((item, i) => (
        <div key={i} className="group/kv contents">
          <dt className="truncate pt-px text-xs text-fg-muted">{item.label}</dt>
          <dd className="flex min-w-0 items-start text-ui text-fg">
            <span className={cn('min-w-0 break-words', item.mono && 'mono text-xs')}>
              {item.value ?? <span className="text-fg-subtle">–</span>}
              {item.hint && <span className="ml-2 text-xs text-fg-subtle">{item.hint}</span>}
            </span>
            {item.copy && <CopyButton text={item.copy} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}
