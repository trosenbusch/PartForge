import { t as tr } from '@/lib/i18n'
/**
 * Fußleiste des Assistenten (klebt unten im Inhaltsbereich): Zurück, Zusammenfassung der Auswahl, Primäraktion
 * „Weiter …“ (Strg+Enter).
 */
import { ArrowLeft, ArrowRight } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button, Kbd } from '@/components/ui'

export interface WizardFooterProps {
  onBack?: () => void
  backLabel?: string
  context?: ReactNode
  primary?: {
    label: string
    onClick: () => void
    disabled?: boolean
    loading?: boolean
    /** Grund, warum es nicht weitergeht (neben dem Knopf) */
    reason?: string | null
  }
}

export function WizardFooter({ onBack, backLabel = tr("Zurück"), context, primary }: WizardFooterProps) {
  return (
    <div className="sticky bottom-0 z-sticky -mx-8 mt-auto border-t border-line bg-[color-mix(in_oklab,var(--pf-bg)_84%,transparent)] py-3 pl-8 pr-[max(2rem,calc(var(--pf-dock-width,0px)+2rem))] backdrop-blur-xl transition-[padding] duration-200">
      <div className="flex min-h-9 items-center gap-3">
        <div className="w-28 shrink-0">
          {onBack && (
            <Button variant="ghost" leftIcon={<ArrowLeft />} onClick={onBack}>
              {backLabel}
            </Button>
          )}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-center gap-2 text-xs text-fg-muted">{context}</div>
        <div className="flex shrink-0 items-center justify-end gap-3">
          {primary?.reason && <span className="hidden whitespace-nowrap text-xs text-fg-subtle @[40rem]:inline">{primary.reason}</span>}
          {primary && (
            <>
              <Kbd hotkey="mod+enter" className="hidden @[48rem]:inline-flex" />
              <Button
                variant="primary"
                rightIcon={<ArrowRight />}
                onClick={primary.onClick}
                disabled={primary.disabled}
                loading={primary.loading}
                aria-keyshortcuts="Control+Enter"
              >
                {primary.label}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
