import { useI18n } from '@/lib/i18n'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'
import { badgeVariants, type BadgeVariantProps } from './variants'

export interface BadgeProps extends ComponentProps<'span'>, BadgeVariantProps {
  /** Farbiger Punkt vor dem Text */
  dot?: boolean
  /** Punkt pulsiert (z. B. „läuft“) */
  pulse?: boolean
}

export function Badge({ className, variant, size, dot, pulse, children, ...props }: BadgeProps) {
  useI18n()
  return (
    <span className={cn(badgeVariants({ variant, size }), className)} {...props}>
      {dot && (
        <span aria-hidden className="relative flex size-1.5">
          {pulse && <span className="absolute inset-0 animate-ping rounded-full bg-current opacity-60" />}
          <span className="relative size-1.5 rounded-full bg-current" />
        </span>
      )}
      {children}
    </span>
  )
}
