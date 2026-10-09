/**
 * Schwebende Speichern-Leiste + Schutz vor Datenverlust:
 * - erscheint, sobald etwas geändert ist („Verwerfen“ / „Speichern“, Strg+S),
 * - fragt beim Verlassen des Bereichs (Navigation in der App) nach: Speichern, Verwerfen oder bleiben,
 * - warnt beim Schließen/Neuladen des Fensters (beforeunload).
 * Strg+S läuft über `useSaveHandler` der Shell (die den Browser-Dialog „Seite speichern unter“ immer abfängt).
 *
 * Entwürfe einer Bibliothek (`root`) überleben keinen Bibliothekswechsel: Ist inzwischen eine andere Bibliothek
 * geöffnet, blockiert die Leiste keine Navigation mehr (es gibt nichts Sinnvolles zu speichern) und meldet beim
 * Abbau, dass die Änderungen verworfen wurden.
 */
import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { CircleAlert, Save } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useBlocker, type Location } from 'react-router'
import { toast } from 'sonner'
import { systemKeys, type WorkspaceInfo } from '@/api/system'
import { Button, Callout, Dialog, DialogContent, DialogFooter, DialogHeader, Kbd } from '@/components/ui'
import { useSaveHandler } from '@/app/commands'
import { useSaveBarSlot } from './saveBarSlot'

export interface UnsavedChangesProps {
  dirty: boolean
  saving: boolean
  /** true = gespeichert (Navigation wird fortgesetzt), false = fehlgeschlagen */
  onSave: () => Promise<boolean> | boolean
  onDiscard: () => void
  /** Was ungespeichert ist (z. B. „Hausstil“) – für Leiste und Rückfrage */
  label?: string
  /** Speichern gesperrt (ungültige Eingabe) – Grund erscheint in Leiste und Rückfrage */
  invalid?: string | null
  /** Welche Navigationen eine Rückfrage brauchen (Standard: anderer Pfad oder andere Suchparameter) */
  shouldBlock?: (current: Location, next: Location) => boolean
  /** Bibliothek (Ordner), zu der der Entwurf gehört – fehlt bei App-Einstellungen */
  root?: string | null
}

const defaultShouldBlock = (a: Location, b: Location) => a.pathname !== b.pathname || a.search !== b.search

export function UnsavedChanges({ dirty, saving, onSave, onDiscard, label, invalid, shouldBlock = defaultShouldBlock, root }: UnsavedChangesProps) {
  const qc = useQueryClient()
  /** Ist noch die Bibliothek geöffnet, zu der der Entwurf gehört? (liest den Cache – auch mitten im Wechsel aktuell) */
  const sameLibrary = () => root === undefined || (qc.getQueryData<WorkspaceInfo | null>(systemKeys.workspace)?.root ?? null) === root
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && sameLibrary() && shouldBlock(currentLocation, nextLocation))
  const [proceeding, setProceeding] = useState(false)

  // Beim Abbau nach einem Bibliothekswechsel: sagen, dass der Entwurf verworfen wurde
  const libraryName = root === undefined ? null : (qc.getQueryData<WorkspaceInfo | null>(systemKeys.workspace)?.name ?? null)
  const latest = useRef({ dirty, label, sameLibrary, libraryName })
  useEffect(() => {
    // Name nur merken, solange noch die eigene Bibliothek geöffnet ist (beim Abbau steht schon die neue im Cache)
    latest.current = { dirty, label, sameLibrary, libraryName: sameLibrary() ? libraryName : latest.current.libraryName }
  })
  useEffect(
    () => () => {
      const { dirty: wasDirty, label: what, sameLibrary: stillSame, libraryName: owner } = latest.current
      if (wasDirty && !stillSame()) {
        toast.warning('Ungespeicherte Änderungen verworfen', {
          id: 'settings-draft-discarded',
          description: `Die Änderungen${what ? ` in „${what}“` : ''} gehörten zur vorher geöffneten Bibliothek${owner ? ` „${owner}“` : ''}.`,
        })
      }
    },
    [],
  )

  const save = () => {
    if (!dirty || saving || invalid) return
    void onSave()
  }
  /** Strg+S: speichern – oder sagen, warum nicht (nichts geändert, ungültige Eingabe) */
  const saveFromHotkey = () => {
    if (saving) return
    if (!dirty) {
      toast.info('Nichts zu speichern', {
        id: 'settings-save-hint',
        description: `${label ? `„${label}“ ist` : 'Alles ist'} bereits gespeichert.`,
      })
      return
    }
    if (invalid) {
      toast.warning('Speichern nicht möglich', { id: 'settings-save-hint', description: invalid })
      return
    }
    void onSave()
  }
  // Strg+S speichert den Bereich – nicht, solange ein modaler Dialog offen ist (z. B. „Feld bearbeiten“); den
  // Browser-Dialog „Seite speichern unter“ fängt die Shell immer ab
  useSaveHandler(saveFromHotkey, { enabled: !saving })

  useEffect(() => {
    if (!dirty) return
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const blocked = blocker.state === 'blocked'
  const slot = useSaveBarSlot()

  const saveAndLeave = async () => {
    setProceeding(true)
    const ok = await onSave()
    setProceeding(false)
    if (ok) blocker.proceed?.()
    else blocker.reset?.()
  }

  const discardAndLeave = () => {
    onDiscard()
    blocker.proceed?.()
  }

  // Ansage für Screenreader: eine dauerhafte Live-Region (die Leiste selbst erscheint/verschwindet)
  const announcement = !dirty
    ? ''
    : invalid
      ? `Speichern nicht möglich: ${invalid}`
      : `Ungespeicherte Änderungen${label ? ` in „${label}“` : ''}. Strg+S speichert.`

  const saveBar = (
    <AnimatePresence>
      {dirty && (
        <motion.div
          className={slot ? 'flex justify-center' : 'pointer-events-none sticky bottom-5 z-sticky mt-2 flex justify-center'}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 16 }}
          transition={{ type: 'spring', stiffness: 420, damping: 34 }}
        >
          <div className="glass pointer-events-auto flex items-center gap-3 rounded-full py-1.5 pl-4 pr-1.5 shadow-pop">
            <span className="flex items-center gap-2 text-ui text-fg">
              <span aria-hidden className="size-2 rounded-full bg-accent shadow-[0_0_8px_var(--pf-accent)]" />
              {invalid ? (
                <span className="flex items-center gap-1.5 text-danger-text">
                  <CircleAlert aria-hidden className="size-3.5" />
                  {invalid}
                </span>
              ) : (
                <>
                  Ungespeicherte Änderungen
                  {label && <span className="text-fg-subtle">· {label}</span>}
                </>
              )}
            </span>
            <Button size="sm" variant="ghost" onClick={onDiscard} disabled={saving}>
              Verwerfen
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={save}
              loading={saving}
              disabled={Boolean(invalid)}
              aria-keyshortcuts="Control+S"
              rightIcon={<Kbd hotkey="mod+s" size="xs" tone="inverse" />}
            >
              Speichern
            </Button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )

  return (
    <>
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      {slot ? createPortal(saveBar, slot) : saveBar}

      <Dialog
        open={blocked}
        onOpenChange={(open) => {
          if (!open && !proceeding) blocker.reset?.()
        }}
      >
        <DialogContent size="sm">
          <DialogHeader
            tone="accent"
            icon={<Save />}
            title="Änderungen speichern?"
            description={
              <>
                {label ? <>„{label}“ hat</> : <>Es gibt</>} ungespeicherte Änderungen. Beim Verlassen ohne Speichern gehen
                sie verloren.
              </>
            }
          />
          {invalid && (
            <div className="px-6 pt-1">
              <Callout tone="danger" icon={<CircleAlert />} title="Speichern ist gerade nicht möglich">
                {invalid} Bleiben Sie hier, um das zu korrigieren, oder verwerfen Sie die Änderungen.
              </Callout>
            </div>
          )}
          <DialogFooter className="mt-3">
            <Button variant="ghost" onClick={() => blocker.reset?.()} disabled={proceeding}>
              Hierbleiben
            </Button>
            <Button variant="secondary" onClick={discardAndLeave} disabled={proceeding}>
              Verwerfen
            </Button>
            <Button
              variant="primary"
              onClick={() => void saveAndLeave()}
              loading={proceeding}
              disabled={Boolean(invalid)}
              title={invalid ?? undefined}
            >
              Speichern
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
