import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { createContext, useContext, useState, type ComponentProps, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { surfaceClass } from './Dialog'
import { useReturnFocus } from './dialogContext'

export interface DrawerProps {
  open?: boolean
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
  /**
   * false = Seite bleibt bedienbar (kein Overlay, kein Fokus-Fang, globale Kürzel bleiben aktiv), z. B. Detailpanel
   * neben der Tabelle. Ein nicht-modaler Drawer schließt **nicht** bei Klicks/Fokus außerhalb – nur über
   * Schließen-Button, Esc (bei Fokus im Panel) oder `onOpenChange`.
   */
  modal?: boolean
  children: ReactNode
}

const widths = {
  sm: 'w-[380px]',
  md: 'w-[480px]',
  lg: 'w-[640px]',
  xl: 'w-[860px]',
}

interface DrawerState {
  open: boolean
  modal: boolean
}

const DrawerContext = createContext<DrawerState>({ open: false, modal: true })

/**
 * Seitenpanel von rechts (Radix Dialog + Spring). Aufbau:
 * <Drawer open onOpenChange><DrawerContent size="md"><DrawerHeader …/><DrawerBody>…</DrawerBody><DrawerFooter>…</DrawerFooter></DrawerContent></Drawer>
 */
export function Drawer({ open, defaultOpen, onOpenChange, modal = true, children }: DrawerProps) {
  const [internal, setInternal] = useState(defaultOpen ?? false)
  const isOpen = open ?? internal
  return (
    <DialogPrimitive.Root
      open={isOpen}
      modal={modal}
      onOpenChange={(next) => {
        if (open === undefined) setInternal(next)
        onOpenChange?.(next)
      }}
    >
      <DrawerContext.Provider value={{ open: isOpen, modal }}>{children}</DrawerContext.Provider>
    </DialogPrimitive.Root>
  )
}

export const DrawerTrigger = DialogPrimitive.Trigger
export const DrawerClose = DialogPrimitive.Close

export interface DrawerContentProps extends Omit<ComponentProps<typeof DialogPrimitive.Content>, 'asChild' | 'forceMount'> {
  size?: keyof typeof widths
  hideClose?: boolean
}

export function DrawerContent({
  size = 'md',
  hideClose,
  className,
  children,
  onInteractOutside,
  onEscapeKeyDown,
  onCloseAutoFocus,
  ...props
}: DrawerContentProps) {
  const { open, modal } = useContext(DrawerContext)
  const returnFocus = useReturnFocus(open)
  return (
    <AnimatePresence>
      {open && (
        <DialogPrimitive.Portal forceMount>
          {modal && (
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-modal bg-overlay backdrop-blur-[2px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
              />
            </DialogPrimitive.Overlay>
          )}
          <DialogPrimitive.Content
            asChild
            forceMount
            aria-modal={modal ? 'true' : undefined}
            onInteractOutside={(e) => {
              onInteractOutside?.(e)
              // Nicht-modal: Klicks in die Tabelle o. ä. dürfen das Detailpanel nicht schließen
              if (!modal) e.preventDefault()
            }}
            onEscapeKeyDown={(e) => {
              onEscapeKeyDown?.(e)
              // Nicht-modal: Esc nur auswerten, wenn der Fokus im Panel liegt (sonst gehört Esc der Seite)
              if (!modal && !document.activeElement?.closest('[data-pf-drawer]')) e.preventDefault()
            }}
            onCloseAutoFocus={(e) => {
              onCloseAutoFocus?.(e)
              if (!e.defaultPrevented) returnFocus(e)
            }}
            {...props}
          >
            <motion.div
              data-pf-drawer=""
              className={cn(
                'fixed bottom-2 right-2 top-2 z-modal flex max-w-[calc(100vw-16px)] flex-col overflow-hidden rounded-panel text-fg outline-none',
                surfaceClass,
                widths[size],
                className,
              )}
              initial={{ x: '104%', opacity: 0.6 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '104%', opacity: 0.6 }}
              transition={{ type: 'spring', stiffness: 420, damping: 34 }}
            >
              {children}
              {!hideClose && (
                <DialogPrimitive.Close
                  aria-label="Schließen"
                  className="absolute right-3.5 top-3.5 flex size-7 items-center justify-center rounded-control text-fg-subtle outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-ring"
                >
                  <X className="size-4" />
                </DialogPrimitive.Close>
              )}
            </motion.div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      )}
    </AnimatePresence>
  )
}

export interface DrawerHeaderProps {
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  /** Zusätzliche Elemente (Badges, Tabs) unter dem Titel */
  children?: ReactNode
  className?: string
}

export function DrawerHeader({ title, description, icon, children, className }: DrawerHeaderProps) {
  return (
    <div className={cn('shrink-0 border-b border-line px-5 pb-4 pt-5 pr-14', className)}>
      <div className="flex items-start gap-3">
        {icon && (
          <span
            aria-hidden
            className="flex size-9 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted [&_svg]:size-[18px]"
          >
            {icon}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <DialogPrimitive.Title className="truncate text-md font-semibold tracking-[-0.015em] text-fg">
            {title}
          </DialogPrimitive.Title>
          {description && (
            <DialogPrimitive.Description className="mt-0.5 text-xs text-fg-muted">{description}</DialogPrimitive.Description>
          )}
        </div>
      </div>
      {children && <div className="mt-3">{children}</div>}
    </div>
  )
}

export function DrawerBody({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', className)} {...props} />
}

export function DrawerFooter({ className, ...props }: ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-end gap-2 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-5 py-3',
        className,
      )}
      {...props}
    />
  )
}
