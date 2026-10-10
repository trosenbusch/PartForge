import { t as translate, useI18n, getLocale } from '@/lib/i18n'
/** Kompakte Einstellungszeilen für den Hausstil: Beschriftung + Hilfe links, Wert rechts, Standardwert mit Zurücksetzen. */
import { Hourglass, RotateCcw } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { Button, Tooltip } from '@/components/ui'
import { FieldContext } from '@/components/ui/fieldContext'
import { cn } from '@/lib/cn'
import { DefaultHint } from '../components'
import { FixedNumberInput } from './FixedNumberInput'

export interface StyleRowProps {
  label: string
  help?: ReactNode
  children: ReactNode
  /** Standardwert-Hinweis (fehlt = keiner) */
  defaultText?: string
  isDefault?: boolean
  onReset?: () => void
  /** Wirkt erst nach dem Speichern in der Vorschau */
  pending?: boolean
  className?: string
}

export function StyleRow({ label, help, children, defaultText, isDefault = true, onReset, pending, className }: StyleRowProps) {
  useI18n()
  const id = `st-${useId().replace(/:/g, '')}`
  const helpId = help ? `${id}-help` : undefined
  return (
    <FieldContext.Provider value={{ id, describedBy: helpId, invalid: false }}>
      <div className={cn('@container py-3', className)}>
        <div className="grid gap-x-6 gap-y-2 @[26rem]:grid-cols-[minmax(0,1fr)_auto] @[26rem]:items-start">
          <div className="min-w-0 @[26rem]:pt-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <label htmlFor={id} className="text-ui font-medium text-fg">
                {label}
              </label>
              {pending && (
                <Tooltip content={translate("Die Vorschau zeigt diese Änderung nach dem Speichern exakt.")}>
                  <span className="inline-flex items-center gap-1 rounded-sm bg-surface-3 px-1.5 py-px text-2xs text-fg-muted">
                    <Hourglass aria-hidden className="size-3" />
                    {translate("nach dem Speichern")}</span>
                </Tooltip>
              )}
            </div>
            {help && (
              <p id={helpId} className="mt-0.5 text-xs leading-snug text-fg-muted">
                {help}
              </p>
            )}
          </div>
          <div className="flex flex-col items-start gap-1 @[26rem]:items-end">
            {children}
            {defaultText !== undefined && onReset && (
              <DefaultHint isDefault={isDefault} defaultText={defaultText} onReset={onReset} label={label} />
            )}
          </div>
        </div>
      </div>
    </FieldContext.Provider>
  )
}

const fixed = (v: number, decimals: number) =>
  v.toLocaleString(getLocale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals })

/** Zahl in Millimetern (oder anderer Einheit) mit Standardwert – feste Nachkommastellen (0,10 / 0,05 / 1,00 mm) */
export function NumberRow({
  label,
  help,
  value,
  defaultValue,
  onChange,
  min,
  max,
  step,
  decimals = 2,
  unit = 'mm',
  pending,
}: {
  label: string
  help?: ReactNode
  value: number
  defaultValue: number
  onChange: (v: number) => void
  min: number
  max: number
  step: number
  decimals?: number
  unit?: string
  pending?: boolean
}) {
  useI18n()
  return (
    <StyleRow
      label={label}
      help={help}
      pending={pending}
      isDefault={Math.abs(value - defaultValue) < 1e-9}
      defaultText={`${fixed(defaultValue, decimals)} ${unit}`}
      onReset={() => onChange(defaultValue)}
    >
      <FixedNumberInput
        value={value}
        onValueChange={onChange}
        min={min}
        max={max}
        step={step}
        decimals={decimals}
        unit={unit}
        className="w-32"
      />
    </StyleRow>
  )
}

/** Gruppe innerhalb der Hausstil-Karten – Überschrift ist die oberste Ebene des Reiters (`<h2>`) */
export function StyleGroup({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  useI18n()
  return (
    <section className="py-1">
      <div className="pb-1 pt-4">
        <h2 className="micro-label">{title}</h2>
        {description && <p className="mt-1 text-xs text-fg-subtle">{description}</p>}
      </div>
      <div className="divide-y divide-line">{children}</div>
    </section>
  )
}

/** „Alles auf Standard“ am Ende einer Hausstil-Karte (Änderung bleibt ein Entwurf bis zum Speichern) */
export function ResetAll({ disabled, onReset, label }: { disabled: boolean; onReset: () => void; label: string }) {
  useI18n()
  return (
    <div className="flex items-center justify-between gap-3 border-t border-line py-3">
      <span className="text-xs text-fg-subtle">{disabled ? translate("Alle Werte entsprechen dem Standard.") : translate("Einige Werte weichen vom Standard ab.")}</span>
      <Button size="sm" variant="ghost" leftIcon={<RotateCcw />} disabled={disabled} onClick={onReset}>
        {label}
      </Button>
    </div>
  )
}
