import { t, useI18n } from '@/lib/i18n'
import { FileScan, Globe } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent } from 'react'
import { Button, Input } from '@/components/ui'

/** „Aus URL laden“: Web-Adresse eines PDF (Hersteller-Link wird später zum Datenblatt-Link der Bauteile). */
export function UrlImport({
  onSubmit,
  aiReady,
  busy,
  focusKey = null,
}: {
  onSubmit: (url: string) => Promise<boolean>
  aiReady: boolean
  busy: boolean
  /** Neuer Wert → Eingabefeld fokussieren (Befehl „Datenblatt aus URL laden“) */
  focusKey?: string | null
}) {
  useI18n()
  const id = useId()
  const [url, setUrl] = useState('')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (focusKey) inputRef.current?.focus()
  }, [focusKey])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const value = url.trim()
    if (!/^https?:\/\/\S+\.\S+/i.test(value)) {
      setError(t("Bitte eine vollständige Web-Adresse angeben (beginnt mit http:// oder https://)."))
      return
    }
    setError(null)
    if (await onSubmit(value)) setUrl('')
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-1.5" noValidate>
      <label htmlFor={`${id}-url`} className="text-xs font-medium text-fg-muted">
        {t("Aus URL laden")}</label>
      <div className="flex items-center gap-2">
        <Input
          ref={inputRef}
          id={`${id}-url`}
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          placeholder="https://www.ti.com/lit/ds/symlink/opa656.pdf"
          prefix={<Globe />}
          value={url}
          invalid={Boolean(error)}
          aria-describedby={`${id}-hint`}
          onChange={(e) => {
            setUrl(e.target.value)
            if (error) setError(null)
          }}
          containerClassName="flex-1"
          mono
        />
        <Button
          type="submit"
          variant={aiReady ? 'spark' : 'secondary'}
          leftIcon={aiReady ? <FileScan /> : <Globe />}
          loading={busy}
          disabled={!url.trim()}
        >
          {aiReady ? t("Laden und analysieren") : t("Laden")}
        </Button>
      </div>
      <p id={`${id}-hint`} className={error ? 'text-xs text-danger-text' : 'text-xs text-fg-subtle'} aria-live="polite">
        {error ?? t("Die Hersteller-Adresse wird als Datenblatt-Link der neuen Bauteile übernommen.")}
      </p>
    </form>
  )
}
