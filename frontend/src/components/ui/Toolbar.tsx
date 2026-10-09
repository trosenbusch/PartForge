import { Toolbar as ToolbarPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'

/** Werkzeugleiste mit Pfeiltasten-Navigation (Radix Toolbar). */
export function Toolbar({ className, ...props }: ComponentProps<typeof ToolbarPrimitive.Root>) {
  return (
    <ToolbarPrimitive.Root
      className={cn(
        'flex min-h-10 items-center gap-1 rounded-button border border-line bg-surface p-1 shadow-card',
        className,
      )}
      {...props}
    />
  )
}

/** Button in der Toolbar: <ToolbarButton asChild><Button …/></ToolbarButton> */
export const ToolbarButton = ToolbarPrimitive.Button
export const ToolbarLink = ToolbarPrimitive.Link
export const ToolbarToggleGroup = ToolbarPrimitive.ToggleGroup
export const ToolbarToggleItem = ToolbarPrimitive.ToggleItem

export function ToolbarSeparator({ className, ...props }: ComponentProps<typeof ToolbarPrimitive.Separator>) {
  return <ToolbarPrimitive.Separator className={cn('mx-1 h-5 w-px bg-line-strong', className)} {...props} />
}

export function ToolbarGroup({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('flex items-center gap-1', className)} {...props} />
}

export function ToolbarSpacer() {
  return <div className="flex-1" />
}
