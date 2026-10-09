import { Popover as PopoverPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'

export const Popover = PopoverPrimitive.Root
export const PopoverTrigger = PopoverPrimitive.Trigger
export const PopoverAnchor = PopoverPrimitive.Anchor
export const PopoverClose = PopoverPrimitive.Close

export interface PopoverContentProps extends ComponentProps<typeof PopoverPrimitive.Content> {
  /** Breite des Triggers übernehmen */
  matchTriggerWidth?: boolean
}

export function PopoverContent({
  className,
  align = 'center',
  sideOffset = 8,
  collisionPadding = 12,
  matchTriggerWidth,
  ...props
}: PopoverContentProps) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'pop-anim glass z-popover w-72 rounded-card p-3 text-fg outline-none',
          matchTriggerWidth && 'w-[var(--radix-popover-trigger-width)]',
          className,
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
}
