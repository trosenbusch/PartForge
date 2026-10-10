import { useI18n } from '@/lib/i18n'
import { CircleCheck, CircleX, Info, TriangleAlert, X } from 'lucide-react'
import { Toaster as Sonner } from 'sonner'
import { Spinner } from './Spinner'

export interface ToasterProps {
  theme: 'dark' | 'light'
  /** Abstand nach unten (z. B. wenn das Job-Dock sichtbar ist) */
  offsetBottom?: number
}

/**
 * Sonner im Kupfer-Stil. Toasts auslösen mit:
 *   import { toast } from 'sonner'
 *   toast.success('Bibliothek erstellt', { description: '…' })
 */
export function Toaster({ theme, offsetBottom = 20 }: ToasterProps) {
  const { t } = useI18n()
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      offset={{ bottom: offsetBottom, right: 20 }}
      gap={10}
      visibleToasts={4}
      closeButton={false}
      duration={4500}
      containerAriaLabel={t('Benachrichtigungen')}
      icons={{
        success: <CircleCheck className="size-[18px] text-success" />,
        error: <CircleX className="size-[18px] text-danger" />,
        warning: <TriangleAlert className="size-[18px] text-warning" />,
        info: <Info className="size-[18px] text-info" />,
        loading: <Spinner size={16} tone="accent" />,
        close: <X className="size-3.5" />,
      }}
    />
  )
}
