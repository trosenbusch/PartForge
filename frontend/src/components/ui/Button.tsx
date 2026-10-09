import { Slot } from 'radix-ui'
import { useContext, type ComponentProps, type MouseEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { ariaKeyshortcuts, type Hotkey } from '@/lib/hotkeys'
import { ButtonDefaultsContext } from './buttonContext'
import { Spinner } from './Spinner'
import { Tooltip } from './Tooltip'
import { buttonVariants, type ButtonVariantProps } from './variants'

export interface ButtonProps extends ComponentProps<'button'>, ButtonVariantProps {
  /** Eigenes Element rendern (z. B. <Link>) – dann ohne Icons/Spinner; `disabled` wird als aria-disabled umgesetzt */
  asChild?: boolean
  /** Zeigt einen Spinner und deaktiviert den Button (aria-busy) */
  loading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

/**
 * Button. Varianten: primary (Forge-Verlauf, **eine** je Ansicht), secondary, outline, ghost, danger,
 * spark (nur KI-Aktionen), link. Größen: xs, sm, md, lg. `iconOnly` für quadratische Icon-Buttons (besser: <IconButton>).
 */
export function Button({
  className,
  variant,
  size,
  iconOnly,
  asChild,
  loading,
  leftIcon,
  rightIcon,
  disabled,
  children,
  type = 'button',
  onClick,
  ...props
}: ButtonProps) {
  const defaults = useContext(ButtonDefaultsContext)
  const effectiveSize = size ?? defaults.size ?? 'md'
  const classes = cn(buttonVariants({ variant, size: effectiveSize, iconOnly }), className)

  if (asChild) {
    // Links u. ä. kennen kein `disabled`: als aria-disabled umsetzen und Klicks/Fokus unterbinden.
    const blocked = Boolean(disabled || loading)
    return (
      <Slot.Root
        className={classes}
        {...props}
        aria-disabled={blocked || undefined}
        aria-busy={loading || undefined}
        data-disabled={blocked || undefined}
        tabIndex={blocked ? -1 : props.tabIndex}
        onClick={(e: MouseEvent<HTMLButtonElement>) => {
          if (blocked) {
            e.preventDefault()
            e.stopPropagation()
            return
          }
          onClick?.(e)
        }}
      >
        {children}
      </Slot.Root>
    )
  }

  const spinnerTone = variant === 'spark' ? 'spark' : 'current'
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      onClick={onClick}
      {...props}
    >
      {loading ? (
        <Spinner size={effectiveSize === 'lg' ? 18 : effectiveSize === 'sm' || effectiveSize === 'xs' ? 13 : 15} tone={spinnerTone} />
      ) : (
        leftIcon
      )}
      {iconOnly && loading ? null : children}
      {rightIcon}
    </button>
  )
}

export interface IconButtonProps extends Omit<ButtonProps, 'iconOnly' | 'leftIcon' | 'rightIcon' | 'children'> {
  /** Barrierefreie Beschriftung – wird auch als Tooltip angezeigt */
  label: string
  icon: ReactNode
  /** Tastenkürzel im Tooltip anzeigen (und als aria-keyshortcuts) */
  hotkey?: Hotkey
  tooltip?: boolean
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left'
}

/** Quadratischer Icon-Button mit Tooltip. Standard-Variante: ghost. */
export function IconButton({
  label,
  icon,
  hotkey,
  tooltip = true,
  tooltipSide = 'bottom',
  variant = 'ghost',
  ...props
}: IconButtonProps) {
  const button = (
    <Button
      aria-label={label}
      aria-keyshortcuts={hotkey ? ariaKeyshortcuts(hotkey) : undefined}
      variant={variant}
      iconOnly
      {...props}
    >
      {icon}
    </Button>
  )
  if (!tooltip) return button
  return (
    <Tooltip content={label} hotkey={hotkey} side={tooltipSide}>
      {button}
    </Tooltip>
  )
}
