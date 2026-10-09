/**
 * Dialoge beim Speichern: „Speichern unter …“ (neuer Symbolname, mit Prüfung gegen die Bibliothek) und die Rückfrage
 * bei Konflikten (geänderte Pinbelegung, fremde Zeichnung gleichen Namens) mit drei Wegen: abbrechen, unter neuem
 * Namen speichern oder bewusst übernehmen.
 */
import { useQuery } from '@tanstack/react-query'
import { CircleAlert, LibraryBig, SaveAll, TriangleAlert } from 'lucide-react'
import { useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import type { SymbolEntry, SymbolSaveOut } from '@/api/symbols'
import { Badge, Button, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, Field, Input, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, plural } from '@/lib/format'
import type { DraftOrigin } from '../store'
import { symbolNameError, useDebouncedValue } from '../util'

// --------------------------------------------------------------------------- Speichern unter

export interface SaveAsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Vorschlag (z. B. „TPS54331 2“) */
  initialName: string
  /** Aktueller Name (darf nicht gleich bleiben) */
  currentName: string
  /** Einträge der Bibliothek (Namensprüfung); undefined = unbekannt */
  entries: readonly SymbolEntry[] | undefined
  /** Bibliothekssymbol, aus dem der Entwurf stammt (die Kopie kommt in dieselbe SchLib) */
  origin?: DraftOrigin | null
  /** Speicher-Probelauf für einen Namen (Ziel-SchLib, neu/vorhanden) – ohne gültigen Entwurf undefined */
  planFor?: (name: string, signal: AbortSignal) => Promise<SymbolSaveOut>
  onSubmit: (name: string) => void
}

function SaveAsForm({
  initialName,
  currentName,
  entries,
  origin,
  planFor,
  onSubmit,
  onCancel,
}: Omit<SaveAsDialogProps, 'open' | 'onOpenChange'> & { onCancel: () => void }) {
  const [name, setName] = useState(initialName)
  const [touched, setTouched] = useState(false)
  const formId = useId()
  const trimmed = name.trim()
  const existing = entries?.find((e) => e.name.toLowerCase() === trimmed.toLowerCase()) ?? null
  const error = !trimmed
    ? 'Bitte einen Namen eingeben.'
    : (symbolNameError(name) ??
      (trimmed.toLowerCase() === currentName.trim().toLowerCase() ? 'Das ist der aktuelle Name – „In Bibliothek speichern“ genügt.' : undefined))
  // Ziel der Kopie aus dem Probelauf des Backends (entprellt beim Tippen)
  const planName = useDebouncedValue(error ? '' : trimmed, 250)
  const plan = useQuery({
    queryKey: ['symbols', 'save-as-plan', planName, Boolean(planFor), origin?.library ?? ''] as const,
    queryFn: ({ signal }) => (planFor as NonNullable<typeof planFor>)(planName, signal),
    enabled: Boolean(planFor && planName),
    // je Öffnen frisch prüfen (Entwurf und Kategorie können sich seitdem geändert haben)
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
  const planPending = Boolean(planFor && trimmed && !error && (planName !== trimmed || plan.isFetching))

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setTouched(true)
    if (error) return
    onSubmit(trimmed)
  }

  return (
    <form id={formId} onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
      <DialogBody className="flex flex-col gap-3">
        <Field
          label="Neuer Symbolname"
          required
          error={touched || trimmed ? error : undefined}
          help={
            existing ? (
              <span className="text-warning-text">
                „{existing.name}“ gibt es schon in {baseName(existing.library)}
                {existing.usage ? ` (${plural(existing.usage, 'Bauteil', 'Bauteile')})` : ''} – es wird überschrieben.
              </span>
            ) : (
              'Erlaubt sind A–Z, a–z, 0–9, Leerzeichen und _ . - + ( ) – höchstens 64 Zeichen.'
            )
          }
        >
          <Input mono value={name} maxLength={64} onChange={(e) => setName(e.target.value)} onFocus={(e) => e.currentTarget.select()} />
        </Field>
        {planFor && (
          <div className="flex min-h-9 items-center gap-2.5 rounded-control border border-line bg-surface-2/50 px-3 py-2 text-xs" aria-live="polite">
            <LibraryBig aria-hidden className="size-4 shrink-0 text-fg-subtle" />
            <span className="shrink-0 text-fg-muted">Ziel</span>
            {error ? (
              <span className="text-fg-subtle">–</span>
            ) : planPending && !plan.data ? (
              <span className="flex items-center gap-1.5 text-fg-subtle">
                <Spinner size={11} /> wird geprüft …
              </span>
            ) : plan.error ? (
              <span className="min-w-0 text-danger-text">{errorMessage(plan.error)}</span>
            ) : plan.data?.library ? (
              <>
                <span className={cn('mono min-w-0 truncate font-medium text-fg', planPending && 'opacity-60')}>{baseName(plan.data.library)}</span>
                <Badge size="sm" variant={plan.data.new ? 'success' : 'warning'}>
                  {plan.data.new ? 'neu' : 'ersetzt'}
                </Badge>
                {origin && plan.data.new && baseName(plan.data.library).toLowerCase() === baseName(origin.library).toLowerCase() && (
                  <span className="min-w-0 truncate text-fg-subtle">wie „{origin.name}“</span>
                )}
              </>
            ) : (
              <span className="text-fg-subtle">–</span>
            )}
          </div>
        )}
        <p className="text-xs leading-relaxed text-fg-muted">
          Das bisherige Symbol bleibt unverändert. Der Entwurf arbeitet danach mit dem neuen Namen weiter.
        </p>
      </DialogBody>
      <DialogFooter>
        <Button type="button" variant="ghost" onClick={onCancel}>
          Abbrechen
        </Button>
        <Button type="submit" variant="primary" leftIcon={<SaveAll />}>
          Unter neuem Namen speichern
        </Button>
      </DialogFooter>
    </form>
  )
}

export function SaveAsDialog({ open, onOpenChange, ...props }: SaveAsDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader icon={<SaveAll />} title="Speichern unter …" description="Symbol unter einem neuen Namen in die Bibliothek schreiben." />
        {open && <SaveAsForm key={props.initialName} {...props} onCancel={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

// --------------------------------------------------------------------------- Konflikt-Rückfrage

export type ConflictChoice = 'cancel' | 'confirm' | 'saveAs'

export interface SaveConflict {
  title: string
  description: ReactNode
  /** Beschriftung der Übernahme („Neue Belegung übernehmen“, „Zeichnung ersetzen“) */
  confirmLabel: string
  /** Rot nur, wenn Bauteile betroffen sind */
  destructive: boolean
}

export function SaveConflictDialog({ conflict, onChoice }: { conflict: SaveConflict | null; onChoice: (choice: ConflictChoice) => void }) {
  // Inhalt während der Schließen-Animation behalten
  const [shown, setShown] = useState(conflict)
  if (conflict && conflict !== shown) setShown(conflict)
  const cancelRef = useRef<HTMLButtonElement>(null)
  return (
    <Dialog open={conflict !== null} onOpenChange={(open) => !open && onChoice('cancel')}>
      <DialogContent
        size="lg"
        onOpenAutoFocus={(e) => {
          // sicherer Standard: Fokus auf „Abbrechen“ (Enter übernimmt nichts versehentlich)
          if (cancelRef.current) {
            e.preventDefault()
            cancelRef.current.focus()
          }
        }}
      >
        <DialogHeader
          icon={shown?.destructive ? <TriangleAlert /> : <CircleAlert />}
          tone={shown?.destructive ? 'danger' : 'accent'}
          title={shown?.title ?? ''}
        />
        <DialogBody className="text-ui leading-relaxed text-fg-muted">{shown?.description}</DialogBody>
        <DialogFooter className="flex-wrap justify-between gap-y-2">
          <Button ref={cancelRef} variant="ghost" onClick={() => onChoice('cancel')}>
            Abbrechen
          </Button>
          <div className="flex flex-wrap items-center justify-end gap-2">
            <Button variant="secondary" leftIcon={<SaveAll />} onClick={() => onChoice('saveAs')}>
              Unter neuem Namen …
            </Button>
            <Button variant={shown?.destructive ? 'danger' : 'primary'} onClick={() => onChoice('confirm')}>
              {shown?.confirmLabel}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
