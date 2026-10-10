import { useI18n } from '@/lib/i18n'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { useState, type ComponentProps, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { DialogContext, useDialog, useReturnFocus } from './dialogContext'

export interface DialogProps {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  modal?: boolean
  children: ReactNode
}

/** Dialog-Wurzel (kontrolliert oder unkontrolliert). Inhalte mit <DialogContent> animiert. */
export function Dialog({ open, defaultOpen, onOpenChange, modal = true, children }: DialogProps) {
  useI18n()
  const [internal, setInternal] = useState(defaultOpen ?? false)
  const isOpen = open ?? internal
  const setOpen = (next: boolean) => {
    if (open === undefined) setInternal(next)
    onOpenChange?.(next)
  }
  return (
    <DialogContext.Provider value={{ open: isOpen, setOpen }}>
      <DialogPrimitive.Root open={isOpen} onOpenChange={setOpen} modal={modal}>
        {children}
      </DialogPrimitive.Root>
    </DialogContext.Provider>
  )
}

export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

const sizes = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
  full: 'max-w-[min(1240px,calc(100vw-48px))] h-[calc(100dvh-48px)]',
}

export const surfaceClass =
  'border border-line-strong bg-[color-mix(in_oklab,var(--pf-surface)_96%,transparent)] shadow-pop backdrop-blur-xl'

export interface DialogContentProps extends Omit<ComponentProps<typeof DialogPrimitive.Content>, 'asChild' | 'forceMount'> {
  size?: keyof typeof sizes
  /** Schließen-Button oben rechts ausblenden */
  hideClose?: boolean
  /** Vertikal zentrieren statt im oberen Drittel */
  centered?: boolean
}

export function DialogContent({
  size = 'md',
  hideClose,
  centered,
  className,
  children,
  onCloseAutoFocus,
  ...props
}: DialogContentProps) {
  const { t: tr } = useI18n()
  const { open } = useDialog()
  const returnFocus = useReturnFocus(open)
  const isCentered = centered || size === 'full'
  return (
    <AnimatePresence>
      {open && (
        <DialogPrimitive.Portal forceMount>
          <DialogPrimitive.Overlay asChild forceMount>
            <motion.div
              className="fixed inset-0 z-modal bg-overlay backdrop-blur-[3px]"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            />
          </DialogPrimitive.Overlay>
          <div
            className={cn(
              'pointer-events-none fixed inset-0 z-modal flex justify-center p-6',
              isCentered ? 'items-center' : 'items-start pt-[11vh]',
            )}
          >
            <DialogPrimitive.Content
              asChild
              forceMount
              aria-modal="true"
              onCloseAutoFocus={(e) => {
                onCloseAutoFocus?.(e)
                if (!e.defaultPrevented) returnFocus(e)
              }}
              {...props}
            >
              <motion.div
                className={cn(
                  // Höhe begrenzen: Kopf/Fuß bleiben stehen, <DialogBody> scrollt
                  'pointer-events-auto relative flex w-full flex-col overflow-hidden rounded-panel text-fg outline-none',
                  isCentered ? 'max-h-[calc(100dvh-3rem)]' : 'max-h-[calc(100dvh-11vh-1.5rem)]',
                  surfaceClass,
                  sizes[size],
                  className,
                )}
                initial={{ opacity: 0, y: 14, scale: 0.97 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.14 } }}
                transition={{ type: 'spring', stiffness: 420, damping: 34 }}
              >
                <span
                  aria-hidden
                  className="pointer-events-none absolute inset-x-12 top-0 h-px bg-[linear-gradient(90deg,transparent,var(--pf-highlight),transparent)]"
                />
                {children}
                {!hideClose && (
                  <DialogPrimitive.Close
                    aria-label={tr("Schließen")}
                    className="absolute right-3.5 top-3.5 flex size-7 items-center justify-center rounded-control text-fg-subtle outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-ring"
                  >
                    <X className="size-4" />
                  </DialogPrimitive.Close>
                )}
              </motion.div>
            </DialogPrimitive.Content>
          </div>
        </DialogPrimitive.Portal>
      )}
    </AnimatePresence>
  )
}

export interface DialogHeaderProps {
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  /** Icon-Kachel: neutral (Standard), spark (KI), danger (Löschen), accent, success (Abschluss, z. B. „angelegt“) */
  tone?: 'accent' | 'spark' | 'danger' | 'neutral' | 'success'
  className?: string
  children?: ReactNode
}

const iconTone = {
  accent: 'border-accent/25 bg-accent-soft text-accent',
  spark: 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_14%,transparent)] text-spark-text',
  danger: 'border-danger/25 bg-danger/10 text-danger-text',
  neutral: 'border-line-strong bg-surface-2 text-fg-muted',
  success: 'border-success/25 bg-success/10 text-success-text',
}

export function DialogHeader({ title, description, icon, tone = 'neutral', className, children }: DialogHeaderProps) {
  useI18n()
  return (
    <div className={cn('flex shrink-0 items-start gap-3.5 px-6 pb-2 pt-6 pr-14', className)}>
      {icon && (
        <span
          aria-hidden
          className={cn('flex size-10 shrink-0 items-center justify-center rounded-button border [&_svg]:size-5', iconTone[tone])}
        >
          {icon}
        </span>
      )}
      <div className="min-w-0 flex-1">
        <DialogPrimitive.Title className="text-md font-semibold tracking-[-0.015em] text-fg">{title}</DialogPrimitive.Title>
        {/* Ohne Beschreibung keine (unsichtbare) Description – sonst würde der Titel doppelt vorgelesen */}
        {description && (
          <DialogPrimitive.Description className="mt-1 text-ui leading-relaxed text-fg-muted">
            {description}
          </DialogPrimitive.Description>
        )}
        {children}
      </div>
    </div>
  )
}

export function DialogBody({ className, ...props }: ComponentProps<'div'>) {
  useI18n()
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-6 py-4', className)} {...props} />
}

export function DialogFooter({ className, ...props }: ComponentProps<'div'>) {
  useI18n()
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-end gap-2 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-6 py-3.5',
        className,
      )}
      {...props}
    />
  )
}

export const DialogTitle = DialogPrimitive.Title
export const DialogDescription = DialogPrimitive.Description
