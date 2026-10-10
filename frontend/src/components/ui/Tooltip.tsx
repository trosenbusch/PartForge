import { useI18n } from '@/lib/i18n'
import { Tooltip as TooltipPrimitive } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import type { Hotkey } from '@/lib/hotkeys'
import { Kbd } from './Kbd'

export const TooltipProvider = TooltipPrimitive.Provider

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  side?: 'top' | 'right' | 'bottom' | 'left'
  align?: 'start' | 'center' | 'end'
  sideOffset?: number
  /** Tastenkürzel rechts im Tooltip */
  hotkey?: Hotkey
  delayDuration?: number
  disabled?: boolean
  className?: string
  open?: boolean
  onOpenChange?: (open: boolean) => void
}

/** Tooltip um ein einzelnes fokussierbares Kind-Element (asChild). */
export function Tooltip({
  content,
  children,
  side = 'top',
  align = 'center',
  sideOffset = 6,
  hotkey,
  delayDuration,
  disabled,
  className,
  open,
  onOpenChange,
}: TooltipProps) {
  useI18n()
  if (disabled || content === null || content === undefined || content === '') return <>{children}</>
  return (
    <TooltipPrimitive.Root delayDuration={delayDuration} open={open} onOpenChange={onOpenChange}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          align={align}
          sideOffset={sideOffset}
          collisionPadding={8}
          className={cn(
            'pop-anim z-tooltip flex max-w-72 items-center gap-2 rounded-control border border-line-strong bg-surface-3 px-2.5 py-1.5',
            'text-xs leading-snug text-fg shadow-pop',
            className,
          )}
        >
          <span className="min-w-0">{content}</span>
          {hotkey && <Kbd hotkey={hotkey} size="xs" />}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}
