import { Check, ChevronRight } from 'lucide-react'
import { ContextMenu as Menu } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import type { Hotkey } from '@/lib/hotkeys'
import { MenuShortcut } from './DropdownMenu'
import {
  menuContentClass,
  menuIndicatorClass,
  menuItemClass,
  menuItemDangerClass,
  menuLabelClass,
  menuSeparatorClass,
} from './menuStyles'

export const ContextMenu = Menu.Root
export const ContextMenuTrigger = Menu.Trigger
export const ContextMenuGroup = Menu.Group
export const ContextMenuSub = Menu.Sub

export function ContextMenuContent({ className, collisionPadding = 10, ...props }: ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content collisionPadding={collisionPadding} className={cn(menuContentClass, className)} {...props} />
    </Menu.Portal>
  )
}

export interface ContextMenuItemProps extends ComponentProps<typeof Menu.Item> {
  icon?: ReactNode
  hotkey?: Hotkey
  destructive?: boolean
}

export function ContextMenuItem({ className, icon, hotkey, destructive, children, ...props }: ContextMenuItemProps) {
  return (
    <Menu.Item className={cn(menuItemClass, destructive && menuItemDangerClass, className)} {...props}>
      {icon}
      <span className="flex-1 truncate">{children}</span>
      {hotkey && <MenuShortcut hotkey={hotkey} />}
    </Menu.Item>
  )
}

export function ContextMenuCheckboxItem({ className, children, ...props }: ComponentProps<typeof Menu.CheckboxItem>) {
  return (
    <Menu.CheckboxItem className={cn(menuItemClass, className)} {...props}>
      <span className="flex-1 truncate">{children}</span>
      <Menu.ItemIndicator className={menuIndicatorClass}>
        <Check className="text-accent!" />
      </Menu.ItemIndicator>
    </Menu.CheckboxItem>
  )
}

export function ContextMenuLabel({ className, ...props }: ComponentProps<typeof Menu.Label>) {
  return <Menu.Label className={cn(menuLabelClass, className)} {...props} />
}

export function ContextMenuSeparator({ className, ...props }: ComponentProps<typeof Menu.Separator>) {
  return <Menu.Separator className={cn(menuSeparatorClass, className)} {...props} />
}

export function ContextMenuSubTrigger({
  className,
  icon,
  children,
  ...props
}: ComponentProps<typeof Menu.SubTrigger> & { icon?: ReactNode }) {
  return (
    <Menu.SubTrigger className={cn(menuItemClass, className)} {...props}>
      {icon}
      <span className="flex-1 truncate">{children}</span>
      <ChevronRight className="ml-auto size-3.5!" />
    </Menu.SubTrigger>
  )
}

export function ContextMenuSubContent({ className, ...props }: ComponentProps<typeof Menu.SubContent>) {
  return (
    <Menu.Portal>
      <Menu.SubContent className={cn(menuContentClass, className)} {...props} />
    </Menu.Portal>
  )
}
