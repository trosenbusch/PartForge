import { motion } from 'motion/react'
import { CircleDashed } from 'lucide-react'
import type { ReactNode } from 'react'
import { PageBody } from '@/app/page'
import { Badge, Card, EmptyState, PageHeader, type IllustrationName } from '@/components/ui'

export interface ModulePlaceholderProps {
  icon: ReactNode
  eyebrow?: string
  title: string
  description: string
  illustration?: IllustrationName
  /** Geplante Funktionen (Kurzliste) */
  features: { title: string; text: string }[]
  /** Aktionen im Leerzustand (höchstens eine Primäraktion je Ansicht) */
  actions?: ReactNode
  /** Zusätzlicher Inhalt unter dem Leerzustand */
  children?: ReactNode
  ai?: boolean
  /** Großen Seitenkopf zeigen (Standard). Tabellen-Seiten: false – Titel steht dann nur in der Topbar. */
  header?: boolean
  width?: 'default' | 'full'
}

/** Platzhalter für Module, die gerade entstehen (wird durch die echte Seite ersetzt). */
export function ModulePlaceholder({
  icon,
  eyebrow = 'Modul',
  title,
  description,
  illustration = 'forge',
  features,
  actions,
  children,
  ai,
  header = true,
  width = 'default',
}: ModulePlaceholderProps) {
  return (
    <PageBody width={width}>
      {header && (
        <PageHeader
          icon={icon}
          eyebrow={eyebrow}
          title={
            <span className="flex items-center gap-3">
              {title}
              {ai && (
                <Badge variant="spark" size="md">
                  KI-gestützt
                </Badge>
              )}
            </span>
          }
          description={description}
        />
      )}
      <Card className={header ? 'mt-7 overflow-hidden' : 'overflow-hidden'}>
        <EmptyState
          illustration={illustration}
          size="lg"
          titleAs="h2"
          title="Dieses Modul wird gerade geschmiedet"
          description={
            header
              ? 'Die Werkstatt ist eingerichtet – Funktionen und Daten folgen in Kürze. Alles Weitere erreichen Sie über die Navigation oder mit Strg+K.'
              : description
          }
          actions={actions}
        />
        <ul className="relative grid grid-cols-2 gap-px border-t border-line bg-line xl:grid-cols-4">
          {features.map((f, i) => (
            <motion.li
              key={f.title}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.06 + i * 0.02, duration: 0.25 }}
              className="flex gap-3 bg-surface p-4"
            >
              <CircleDashed aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-subtle" />
              <div className="min-w-0">
                <div className="text-ui font-medium text-fg">{f.title}</div>
                <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{f.text}</p>
              </div>
            </motion.li>
          ))}
        </ul>
      </Card>
      {children}
    </PageBody>
  )
}
