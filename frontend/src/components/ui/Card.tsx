import { Slot } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { cardVariants, type CardVariantProps } from './variants'

export interface CardProps extends ComponentProps<'div'>, CardVariantProps {
  asChild?: boolean
}

export function Card({ className, variant, padding, asChild, children, ...props }: CardProps) {
  const Comp = asChild ? Slot.Root : 'div'
  return (
    <Comp className={cn(cardVariants({ variant, padding }), className)} {...props}>
      {variant === 'highlight' && !asChild && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-6 -top-px h-px bg-[linear-gradient(90deg,transparent,var(--pf-accent),transparent)]"
        />
      )}
      {children}
    </Comp>
  )
}

export interface CardHeaderProps extends Omit<ComponentProps<'div'>, 'title'> {
  title?: ReactNode
  description?: ReactNode
  /** Icon in einer kleinen Kachel links */
  icon?: ReactNode
  /** Aktionen rechts */
  actions?: ReactNode
  /** Mikro-Label über dem Titel */
  eyebrow?: ReactNode
  /** Überschriftenebene (Standard h2 – Karten liegen direkt unter der h1 der Seite) */
  titleAs?: 'h2' | 'h3' | 'h4'
}

export function CardHeader({
  title,
  description,
  icon,
  actions,
  eyebrow,
  titleAs: Title = 'h2',
  className,
  children,
  ...props
}: CardHeaderProps) {
  return (
    <div className={cn('flex items-start gap-3 px-4 pb-3 pt-4', className)} {...props}>
      {icon && (
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted [&_svg]:size-4"
        >
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1">
        {eyebrow && <div className="micro-label mb-0.5">{eyebrow}</div>}
        {title && <Title className="truncate text-sm font-semibold tracking-[-0.01em] text-fg">{title}</Title>}
        {description && <p className="mt-0.5 text-xs leading-snug text-fg-muted">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-1">{actions}</div>}
    </div>
  )
}

export function CardContent({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('px-4 pb-4', className)} {...props} />
}

export function CardFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn('flex items-center gap-2 rounded-b-card border-t border-line bg-surface-2/40 px-4 py-3', className)}
      {...props}
    />
  )
}
