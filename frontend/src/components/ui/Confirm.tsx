import { useI18n } from '@/lib/i18n'
import { AnimatePresence, motion } from 'motion/react'
import { TriangleAlert } from 'lucide-react'
import { AlertDialog } from 'radix-ui'
import { useRef, useState } from 'react'
import { cn } from '@/lib/cn'
import { Button } from './Button'
import { useConfirmStore } from './confirmStore'
import { surfaceClass } from './Dialog'
import { useReturnFocus } from './dialogContext'

/**
 * Host für `confirm()`-Dialoge (Radix AlertDialog). Einmal in der App rendern (RootLayout erledigt das).
 * Bei destruktiven Aktionen liegt der Fokus auf „Abbrechen“ – Entf + Enter löscht also nicht versehentlich.
 */
export function ConfirmHost() {
  const { t: tr } = useI18n()
  const { current, open } = useConfirmStore()
  const [busy, setBusy] = useState(false)
  const confirmRef = useRef<HTMLButtonElement>(null)
  const returnFocus = useReturnFocus(open)

  const close = (ok: boolean) => {
    current?.resolve(ok)
    useConfirmStore.setState({ open: false })
  }

  const onConfirm = async () => {
    if (!current) return
    if (current.onConfirm) {
      setBusy(true)
      try {
        await current.onConfirm()
      } catch {
        setBusy(false)
        return // Fehler meldet der Aufrufer (Toast); Dialog bleibt offen
      }
      setBusy(false)
    }
    close(true)
  }

  const destructive = Boolean(current?.destructive)

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(o) => {
        if (!o && !busy) close(false)
      }}
    >
      <AnimatePresence>
        {open && current && (
          <AlertDialog.Portal forceMount>
            <AlertDialog.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-modal bg-overlay backdrop-blur-[3px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
              />
            </AlertDialog.Overlay>
            <div className="pointer-events-none fixed inset-0 z-modal flex items-start justify-center p-6 pt-[14vh]">
              <AlertDialog.Content
                asChild
                forceMount
                aria-modal="true"
                onOpenAutoFocus={(e) => {
                  // nicht destruktiv: Bestätigen vorauswählen; destruktiv: Radix-Standard (Abbrechen)
                  if (!destructive) {
                    e.preventDefault()
                    confirmRef.current?.focus({ preventScroll: true })
                  }
                }}
                onCloseAutoFocus={returnFocus}
              >
                <motion.div
                  className={cn(
                    'pointer-events-auto relative flex w-full max-w-sm flex-col overflow-hidden rounded-panel text-fg outline-none',
                    surfaceClass,
                  )}
                  initial={{ opacity: 0, y: 14, scale: 0.97 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.14 } }}
                  transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                >
                  <div className="flex items-start gap-3.5 px-6 pb-2 pt-6">
                    {(current.icon || destructive) && (
                      <span
                        aria-hidden
                        className={cn(
                          'flex size-10 shrink-0 items-center justify-center rounded-button border [&_svg]:size-5',
                          destructive
                            ? 'border-danger/25 bg-danger/10 text-danger-text'
                            : 'border-line-strong bg-surface-2 text-fg-muted',
                        )}
                      >
                        {current.icon ?? <TriangleAlert />}
                      </span>
                    )}
                    <div className="min-w-0 flex-1">
                      <AlertDialog.Title className="text-md font-semibold tracking-[-0.015em] text-fg">
                        {current.title}
                      </AlertDialog.Title>
                      {current.description && (
                        <AlertDialog.Description className="mt-1 text-ui leading-relaxed text-fg-muted">
                          {current.description}
                        </AlertDialog.Description>
                      )}
                    </div>
                  </div>
                  <div className="mt-3 flex items-center justify-end gap-2 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-6 py-3.5">
                    <AlertDialog.Cancel asChild>
                      <Button variant="ghost" disabled={busy}>
                        {current.cancelLabel ?? tr("Abbrechen")}
                      </Button>
                    </AlertDialog.Cancel>
                    <Button
                      ref={confirmRef}
                      variant={destructive ? 'danger' : 'primary'}
                      onClick={() => void onConfirm()}
                      loading={busy}
                    >
                      {current.confirmLabel ?? tr("Bestätigen")}
                    </Button>
                  </div>
                </motion.div>
              </AlertDialog.Content>
            </div>
          </AlertDialog.Portal>
        )}
      </AnimatePresence>
    </AlertDialog.Root>
  )
}
