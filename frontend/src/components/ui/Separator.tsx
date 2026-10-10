import { useI18n } from '@/lib/i18n'
import { Separator as SeparatorPrimitive } from 'radix-ui'
import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'

export interface SeparatorProps extends ComponentProps<typeof SeparatorPrimitive.Root> {
  /** Mit Verlauf zu den Enden ausblenden */
  fade?: boolean
}

export function Separator({ className, orientation = 'horizontal', decorative = true, fade, ...props }: SeparatorProps) {
  useI18n()
  return (
    <SeparatorPrimitive.Root
      orientation={orientation}
      decorative={decorative}
      className={cn(
        'shrink-0',
        orientation === 'horizontal' ? 'h-px w-full' : 'h-full w-px',
        fade
          ? orientation === 'horizontal'
            ? 'bg-[linear-gradient(90deg,transparent,var(--pf-line-strong),transparent)]'
            : 'bg-[linear-gradient(180deg,transparent,var(--pf-line-strong),transparent)]'
          : 'bg-line',
        className,
      )}
      {...props}
    />
  )
}
