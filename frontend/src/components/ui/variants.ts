/** cva-Varianten des UI-Kits (getrennt von den Komponenten, damit Fast Refresh sauber bleibt). */
import { cva, type VariantProps } from 'class-variance-authority'

/**
 * Regel: **eine** Primäraktion (Forge-Verlauf) je Ansicht. Alles andere ist secondary/ghost.
 * `spark` ist KI-Aktionen vorbehalten (statischer Funkenrahmen, rotiert nur während `loading`).
 */
export const buttonVariants = cva(
  [
    'group/button relative inline-flex shrink-0 select-none items-center justify-center gap-2 whitespace-nowrap font-medium',
    'transition-[background-color,border-color,color,box-shadow,transform,filter,opacity] duration-150 ease-out',
    'focus-ring outline-none disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 aria-busy:cursor-progress',
    'active:scale-[.98] [&_svg]:pointer-events-none [&_svg]:shrink-0',
  ],
  {
    variants: {
      variant: {
        primary: [
          'bg-gradient-forge text-on-accent font-semibold sheen shadow-[var(--pf-shadow-primary)]',
          'hover:brightness-[1.06] hover:shadow-[var(--pf-shadow-primary-hover)]',
        ],
        secondary: [
          'border border-line-strong bg-surface-2 text-fg shadow-[inset_0_1px_0_var(--pf-highlight)]',
          'hover:border-line-control hover:bg-surface-3',
        ],
        outline: 'border border-line-strong bg-transparent text-fg hover:bg-surface-2',
        ghost: 'text-fg-muted hover:bg-surface-2 hover:text-fg data-[state=open]:bg-surface-2 data-[state=open]:text-fg',
        danger: 'border border-danger/35 bg-danger/10 text-danger-text hover:border-danger/55 hover:bg-danger/15',
        spark: [
          'spark-border-static aria-busy:spark-border text-fg [--spark-fill:var(--pf-surface-2)] hover:[--spark-fill:var(--pf-surface-3)]',
          'shadow-[var(--pf-shadow-spark)] hover:shadow-[var(--pf-shadow-spark-hover)]',
          '[&_svg]:text-spark-a',
        ],
        link: 'h-auto! px-0! text-accent-text underline-offset-4 hover:underline',
      },
      size: {
        xs: 'h-6 gap-1 rounded-control px-2 text-2xs [&_svg]:size-3',
        sm: 'h-7 gap-1.5 rounded-control px-2.5 text-xs [&_svg]:size-3.5',
        md: 'h-8.5 rounded-button px-3.5 text-ui [&_svg]:size-4',
        lg: 'h-10 rounded-button px-5 text-sm [&_svg]:size-[18px]',
      },
      iconOnly: {
        true: 'px-0',
        false: '',
      },
    },
    compoundVariants: [
      { iconOnly: true, size: 'xs', className: 'w-6 px-0' },
      { iconOnly: true, size: 'sm', className: 'w-7 px-0' },
      { iconOnly: true, size: 'md', className: 'w-8.5 px-0' },
      { iconOnly: true, size: 'lg', className: 'w-10 px-0' },
    ],
    defaultVariants: { variant: 'secondary', size: 'md', iconOnly: false },
  },
)

export type ButtonVariantProps = VariantProps<typeof buttonVariants>

export const badgeVariants = cva(
  'inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border font-medium leading-none [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        neutral: 'border-line bg-surface-3/70 text-fg-muted',
        outline: 'border-line-strong bg-transparent text-fg-muted',
        accent: 'border-accent/25 bg-accent-soft text-accent-text',
        success: 'border-success/25 bg-success/10 text-success-text',
        warning: 'border-warning/25 bg-warning/10 text-warning-text',
        danger: 'border-danger/25 bg-danger/10 text-danger-text',
        info: 'border-info/25 bg-info/10 text-info-text',
        spark:
          'border-spark-b/30 bg-[linear-gradient(135deg,color-mix(in_oklab,var(--pf-spark-a)_12%,transparent),color-mix(in_oklab,var(--pf-spark-b)_14%,transparent))] text-spark-text [&_svg]:text-spark-a',
      },
      size: {
        sm: 'h-5 px-2 text-2xs [&_svg]:size-3',
        md: 'h-6 px-2.5 text-xs [&_svg]:size-3.5',
      },
    },
    defaultVariants: { variant: 'neutral', size: 'sm' },
  },
)

export type BadgeVariantProps = VariantProps<typeof badgeVariants>

export const cardVariants = cva('relative rounded-card text-fg', {
  variants: {
    variant: {
      default: 'border border-line bg-surface shadow-card',
      /** Klickbare Karte: 1 px Lift beim Hover */
      interactive: [
        'border border-line bg-surface shadow-card transition-[transform,border-color,box-shadow] duration-200 ease-out',
        'hover:-translate-y-px hover:border-line-strong hover:shadow-raised focus-within:border-line-strong',
      ],
      glass: 'glass',
      /** KI-Inhalt: statischer Funken-Rahmen */
      spark: 'spark-border-static shadow-card',
      /** Hervorgehoben mit Kupfer-Linie am oberen Rand */
      highlight: 'border border-accent/25 bg-surface shadow-card',
      ghost: 'border border-dashed border-line-strong bg-transparent',
    },
    padding: {
      none: '',
      sm: 'p-3',
      md: 'p-4',
      lg: 'p-6',
    },
  },
  defaultVariants: { variant: 'default', padding: 'none' },
})

export type CardVariantProps = VariantProps<typeof cardVariants>

/**
 * Gemeinsame Hülle für Eingabefelder (auch von Select/Combobox-Triggern genutzt).
 * Füllung `bg-control` (dunkel: surface-2, hell: weiß), Rahmen `line-control` (≥ 3:1).
 */
export const controlShell = cva(
  [
    'group/control flex w-full min-w-0 items-center gap-2 border border-line-control bg-control text-fg',
    'shadow-[inset_0_1px_1px_rgba(0,0,0,.06)]',
    'transition-[border-color,box-shadow,background-color] duration-150',
    'hover:border-line-control-hover',
    'focus-within:border-accent focus-within:bg-control-focus focus-within:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
    'data-[invalid]:border-danger data-[invalid]:focus-within:shadow-[0_0_0_4px_color-mix(in_oklab,var(--pf-danger)_18%,transparent)]',
    'data-[disabled]:pointer-events-none data-[disabled]:opacity-55',
  ],
  {
    variants: {
      size: {
        sm: 'h-7 rounded-control px-2.5 text-xs',
        md: 'h-8.5 rounded-button px-3 text-sm',
        lg: 'h-10 rounded-button px-3.5 text-sm',
      },
    },
    defaultVariants: { size: 'md' },
  },
)
