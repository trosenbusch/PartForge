import { Check, ChevronDown, ChevronUp } from 'lucide-react'
import { Select as SelectPrimitive } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'
import { controlShell } from './variants'

export interface SelectOption<V extends string = string> {
  value: V
  label: ReactNode
  /** Zweite Zeile in der Liste (nicht im Trigger) */
  description?: ReactNode
  icon?: ReactNode
  disabled?: boolean
  /** Rechtsbündiger Zusatz in der Liste, z. B. „empfohlen“ */
  badge?: ReactNode
}

export interface SelectGroupDef<V extends string = string> {
  label: string
  options: SelectOption<V>[]
}

export interface SelectProps<V extends string = string> {
  value?: V
  defaultValue?: V
  onValueChange?: (value: V) => void
  options?: SelectOption<V>[]
  /** Alternativ gruppierte Optionen */
  groups?: SelectGroupDef<V>[]
  placeholder?: string
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  invalid?: boolean
  id?: string
  name?: string
  className?: string
  contentClassName?: string
  'aria-label'?: string
  /** Icon links im Trigger */
  prefix?: ReactNode
}

export function Select<V extends string = string>({
  value,
  defaultValue,
  onValueChange,
  options,
  groups,
  placeholder = 'Auswählen …',
  size = 'md',
  disabled,
  invalid,
  id,
  name,
  className,
  contentClassName,
  prefix,
  'aria-label': ariaLabel,
}: SelectProps<V>) {
  const field = useFieldContext()
  const isInvalid = invalid ?? field?.invalid ?? false
  const allGroups: SelectGroupDef<V>[] = groups ?? [{ label: '', options: options ?? [] }]

  return (
    <SelectPrimitive.Root
      value={value}
      defaultValue={defaultValue}
      onValueChange={(v) => onValueChange?.(v as V)}
      disabled={disabled ?? field?.disabled}
      name={name}
    >
      <SelectPrimitive.Trigger
        id={id ?? field?.id}
        aria-label={ariaLabel}
        aria-invalid={isInvalid || undefined}
        aria-describedby={field?.describedBy}
        aria-required={field?.required || undefined}
        data-invalid={isInvalid || undefined}
        className={cn(
          controlShell({ size }),
          'justify-between text-left outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
          'data-[placeholder]:text-fg-subtle data-[state=open]:border-accent',
          'disabled:cursor-not-allowed disabled:opacity-55 [&>span]:truncate',
          className,
        )}
      >
        {prefix && (
          <span aria-hidden className="flex shrink-0 items-center text-fg-subtle [&_svg]:size-4">
            {prefix}
          </span>
        )}
        <span className="flex min-w-0 flex-1 items-center gap-2 [&_svg]:size-4">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon asChild>
          <ChevronDown className="size-4 shrink-0 text-fg-subtle transition-transform duration-200 group-data-[state=open]/control:rotate-180" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={6}
          collisionPadding={10}
          className={cn(
            'pop-anim glass z-popover min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-card text-fg',
            'max-h-[min(var(--radix-select-content-available-height),22rem)]',
            contentClassName,
          )}
        >
          <SelectPrimitive.ScrollUpButton className="flex h-6 items-center justify-center text-fg-muted">
            <ChevronUp className="size-4" />
          </SelectPrimitive.ScrollUpButton>
          <SelectPrimitive.Viewport className="p-1">
            {allGroups.map((group, gi) => (
              <SelectPrimitive.Group key={group.label || gi}>
                {group.label && (
                  <SelectPrimitive.Label className="micro-label px-2 pb-1 pt-2">{group.label}</SelectPrimitive.Label>
                )}
                {group.options.map((opt) => (
                  <SelectPrimitive.Item
                    key={opt.value}
                    value={opt.value}
                    disabled={opt.disabled}
                    className={cn(
                      'relative flex cursor-default select-none items-center gap-2.5 rounded-control py-1.5 pl-2 pr-8 text-ui outline-none',
                      'data-[highlighted]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)] data-[disabled]:opacity-45',
                      'data-[state=checked]:text-fg [&_svg]:size-4 [&_svg]:text-fg-muted',
                      opt.description ? 'min-h-11' : 'min-h-8',
                    )}
                  >
                    {opt.icon}
                    <span className="flex min-w-0 flex-1 flex-col">
                      <SelectPrimitive.ItemText>{opt.label}</SelectPrimitive.ItemText>
                      {opt.description && (
                        <span className="truncate text-2xs leading-4 text-fg-subtle">{opt.description}</span>
                      )}
                    </span>
                    {opt.badge && <span className="shrink-0">{opt.badge}</span>}
                    <SelectPrimitive.ItemIndicator className="absolute right-2 flex size-4 items-center justify-center">
                      <Check className="text-accent!" />
                    </SelectPrimitive.ItemIndicator>
                  </SelectPrimitive.Item>
                ))}
              </SelectPrimitive.Group>
            ))}
          </SelectPrimitive.Viewport>
          <SelectPrimitive.ScrollDownButton className="flex h-6 items-center justify-center text-fg-muted">
            <ChevronDown className="size-4" />
          </SelectPrimitive.ScrollDownButton>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}
