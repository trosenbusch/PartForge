import { useI18n } from '@/lib/i18n'
import { Fragment } from 'react'
import { cn } from '@/lib/cn'

/**
 * Dateipfad als Text: Monospace, Umbruch nur an Pfadtrennern (`\` und `/`) statt mitten im Wort.
 *   <PathText path="C:\Program Files\Altium\AD25\X2.EXE" />
 */
export function PathText({ path, className }: { path: string; className?: string }) {
  useI18n()
  const parts = path.split(/(?<=[\\/])/)
  return (
    <span className={cn('mono [overflow-wrap:anywhere]', className)} title={path}>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part}
          {i < parts.length - 1 && <wbr />}
        </Fragment>
      ))}
    </span>
  )
}
