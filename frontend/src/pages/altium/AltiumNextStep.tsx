import { useI18n } from '@/lib/i18n'
import { ArrowRight } from 'lucide-react'
import { useNavigate } from 'react-router'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { AfterWriteNotice } from './model'
import { useAltiumActions } from './useAltiumActions'

/**
 * Nächster Schritt der Altium-Zeile in den Erfolgsansichten (Serie, Datenblatt-Import, `altiumAfterWrite`): dieselben
 * Aktionen wie auf der Altium-Seite – „In Altium installieren“ (Rückfrage bei gleichnamiger alter Installation),
 * „In Altium aktualisieren“ (Job-Dock, Abschluss-Toast) – bzw. „Zur Altium-Seite“. Ein Textknopf im Fließtext.
 */
export function AltiumNextStep({ next, className }: { next: NonNullable<AfterWriteNotice['next']>; className?: string }) {
  useI18n()
  const actions = useAltiumActions()
  const navigate = useNavigate()
  const pending =
    next.action === 'install'
      ? actions.pending.install || actions.pending.installReplace
      : next.action === 'refresh' && actions.pending.refresh
  return (
    <button
      type="button"
      disabled={pending}
      onClick={() => (next.action === 'page' ? navigate('/altium') : actions.run(next.action))}
      className={cn(
        'inline-flex items-center gap-1 rounded-sm font-medium text-accent-text underline-offset-2 outline-none hover:underline focus-ring disabled:cursor-default disabled:no-underline disabled:opacity-70',
        className,
      )}
    >
      {next.label}
      {pending ? <Spinner size={11} /> : <ArrowRight aria-hidden className="size-3" />}
    </button>
  )
}
