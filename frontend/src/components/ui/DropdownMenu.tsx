import { useI18n } from '@/lib/i18n'
import { Check, ChevronRight, Dot } from 'lucide-react'
import { DropdownMenu as Menu } from 'radix-ui'
import type { ComponentProps, ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { formatHotkey, type Hotkey } from '@/lib/hotkeys'
import {
  menuContentClass,
  menuIndicatorClass,
  menuItemClass,
  menuItemDangerClass,
  menuLabelClass,
  menuSeparatorClass,
} from './menuStyles'

export const DropdownMenu = Menu.Root
export const DropdownMenuTrigger = Menu.Trigger
export const DropdownMenuGroup = Menu.Group
export const DropdownMenuSub = Menu.Sub
export const DropdownMenuRadioGroup = Menu.RadioGroup

export function DropdownMenuContent({
  className,
  sideOffset = 6,
  collisionPadding = 10,
  ...props
}: ComponentProps<typeof Menu.Content>) {
  useI18n()
  return (
    <Menu.Portal>
      <Menu.Content
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(menuContentClass, className)}
        {...props}
      />
    </Menu.Portal>
  )
}

/** Tastenkürzel-Hinweis rechts in einem Menüeintrag */
export function MenuShortcut({ hotkey, children }: { hotkey?: Hotkey; children?: ReactNode }) {
  useI18n()
  return (
    <span className="ml-auto pl-6 text-2xs tracking-wide text-fg-subtle tabular-nums">
      {hotkey ? formatHotkey(hotkey) : children}
    </span>
  )
}

export interface DropdownMenuItemProps extends ComponentProps<typeof Menu.Item> {
  /**
   * Vor der Beschriftung – Icon oder eigenes Element (z. B. Farbpunkt `<span className="size-2 rounded-full" />`;
   * steht als eigenes Flex-Element, Größen greifen also auch bei `<span>`)
   */
  icon?: ReactNode
  hotkey?: Hotkey
  destructive?: boolean
  /** Zweite Zeile (klein, gedämpft) */
  description?: ReactNode
  /**
   * Rechts in der Zeile, mit Abstand zur Beschriftung (z. B. eine Anzahl). Die Beschriftung wird davor gekürzt, nie der
   * Zusatz. Zählt er für Screenreader mit, den Namen des Eintrags per `aria-label` ausschreiben („Widerstände,
   * 17 Bauteile“) – sonst liest der Browser „Widerstände17“.
   */
  trailing?: ReactNode
}

/**
 * Menüeintrag: `icon`, Beschriftung (`children`, nur Text – sie wird gekürzt) mit optionaler zweiter Zeile
 * (`description`), rechts `trailing` bzw. das Tastenkürzel. Mehrere Elemente gehören in diese Plätze, nicht in
 * `children` (dort stünden sie als Fließtext ohne Abstand).
 */
export function DropdownMenuItem({
  className,
  icon,
  hotkey,
  destructive,
  description,
  trailing,
  children,
  ...props
}: DropdownMenuItemProps) {
  useI18n()
  return (
    <Menu.Item
      className={cn(menuItemClass, description && 'h-auto py-1.5', destructive && menuItemDangerClass, className)}
      {...props}
    >
      {icon}
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{children}</span>
        {description && <span className="truncate text-2xs text-fg-subtle">{description}</span>}
      </span>
      {trailing != null && trailing !== false && (
        <span className="ml-auto shrink-0 text-2xs text-fg-subtle tabular-nums">{trailing}</span>
      )}
      {hotkey && <MenuShortcut hotkey={hotkey} />}
    </Menu.Item>
  )
}

export function DropdownMenuCheckboxItem({
  className,
  children,
  ...props
}: ComponentProps<typeof Menu.CheckboxItem>) {
  useI18n()
  return (
    <Menu.CheckboxItem className={cn(menuItemClass, 'pr-2', className)} {...props}>
      <span className="flex-1 truncate">{children}</span>
      <Menu.ItemIndicator className={menuIndicatorClass}>
        <Check className="text-accent!" />
      </Menu.ItemIndicator>
    </Menu.CheckboxItem>
  )
}

export function DropdownMenuRadioItem({
  className,
  children,
  icon,
  ...props
}: ComponentProps<typeof Menu.RadioItem> & { icon?: ReactNode }) {
  useI18n()
  return (
    <Menu.RadioItem className={cn(menuItemClass, className)} {...props}>
      {icon}
      <span className="flex-1 truncate">{children}</span>
      <Menu.ItemIndicator className={menuIndicatorClass}>
        <Dot className="size-6! text-accent!" strokeWidth={6} />
      </Menu.ItemIndicator>
    </Menu.RadioItem>
  )
}

export function DropdownMenuLabel({ className, ...props }: ComponentProps<typeof Menu.Label>) {
  useI18n()
  return <Menu.Label className={cn(menuLabelClass, className)} {...props} />
}

export function DropdownMenuSeparator({ className, ...props }: ComponentProps<typeof Menu.Separator>) {
  useI18n()
  return <Menu.Separator className={cn(menuSeparatorClass, className)} {...props} />
}

export function DropdownMenuSubTrigger({
  className,
  icon,
  children,
  ...props
}: ComponentProps<typeof Menu.SubTrigger> & { icon?: ReactNode }) {
  useI18n()
  return (
    <Menu.SubTrigger
      className={cn(menuItemClass, 'data-[state=open]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)]', className)}
      {...props}
    >
      {icon}
      <span className="flex-1 truncate">{children}</span>
      <ChevronRight className="ml-auto size-3.5!" />
    </Menu.SubTrigger>
  )
}

export function DropdownMenuSubContent({ className, ...props }: ComponentProps<typeof Menu.SubContent>) {
  useI18n()
  return (
    <Menu.Portal>
      <Menu.SubContent sideOffset={6} className={cn(menuContentClass, className)} {...props} />
    </Menu.Portal>
  )
}
