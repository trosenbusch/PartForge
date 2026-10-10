import { useI18n } from '@/lib/i18n'
/**
 * Starke Bestätigung für unumkehrbare Aktionen (Kategorie löschen, Sicherung wiederherstellen): Der Nutzer tippt
 * ein Bestätigungswort ab. Fehler der Aktion erscheinen im Dialog, der dann offen bleibt.
 */
import { Check } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import { Button, Callout, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, Field, Input } from '@/components/ui'

export interface TypedConfirmProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: ReactNode
  description?: ReactNode
  icon?: ReactNode
  /** Inhalt zwischen Beschreibung und Eingabe (Auswirkungen, Hinweis auf Sicherung) */
  children?: ReactNode
  /** Abzutippender Text (Groß-/Kleinschreibung egal) */
  phrase: string
  confirmLabel: string
  /** Wirft bei Fehlern (Meldung erscheint im Dialog) */
  onConfirm: () => Promise<unknown>
  destructive?: boolean
}

export function TypedConfirm({
  open,
  onOpenChange,
  title,
  description,
  icon,
  children,
  phrase,
  confirmLabel,
  onConfirm,
  destructive = true,
}: TypedConfirmProps) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const matches = text.trim().toLocaleLowerCase('de-DE') === phrase.toLocaleLowerCase('de-DE')

  const close = (o: boolean) => {
    if (busy) return
    onOpenChange(o)
    if (!o) {
      setText('')
      setError(null)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!matches || busy) return
    setBusy(true)
    setError(null)
    try {
      await onConfirm()
      setBusy(false)
      setText('')
      onOpenChange(false)
    } catch (err) {
      setBusy(false)
      setError(errorMessage(err))
    }
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="md">
        <form onSubmit={(e) => void submit(e)} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader tone={destructive ? 'danger' : 'accent'} icon={icon} title={title} description={description} />
          <DialogBody className="flex flex-col gap-4">
            {children}
            <Field
              label={
                <>
                  {t("Zur Bestätigung")} <span className="mono rounded-sm bg-surface-3 px-1 py-px text-fg">{phrase}</span>  {t("eingeben")}</>
              }
            >
              <Input
                mono
                autoComplete="off"
                spellCheck={false}
                value={text}
                onChange={(e) => setText(e.target.value)}
                aria-label={t("Zur Bestätigung „{0}“ eingeben", { "0": phrase })}
                suffix={matches ? <Check aria-hidden className="text-success-text" /> : undefined}
              />
            </Field>
            {error && (
              <Callout tone="danger" title={t("Das hat nicht geklappt")} urgent>
                {error}
              </Callout>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => close(false)} disabled={busy}>
              {t("Abbrechen")}</Button>
            <Button type="submit" variant={destructive ? 'danger' : 'primary'} loading={busy} disabled={!matches}>
              {confirmLabel}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
