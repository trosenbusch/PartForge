import { useI18n } from '@/lib/i18n'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'

/** Platzhalter mit Shimmer: <Skeleton className="h-4 w-32" /> */
export function Skeleton({ className, ...props }: ComponentProps<'div'>) {
  useI18n()
  return <div aria-hidden className={cn('shimmer rounded-control', className)} {...props} />
}

/** Mehrzeiliger Text-Platzhalter */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  useI18n()
  return (
    <div className={cn('flex flex-col gap-2', className)} aria-hidden>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className="h-3" style={{ width: `${i === lines - 1 ? 60 : 100 - i * 6}%` }} />
      ))}
    </div>
  )
}
