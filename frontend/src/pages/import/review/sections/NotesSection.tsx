import { CircleAlert, Info, MessageSquareQuote, Sparkles, TriangleAlert } from 'lucide-react'
import type { ExtractionIssue } from '@/api/datasheets'
import { cn } from '@/lib/cn'
import { useReview } from '../context'
import { Section } from './Section'

const SEVERITY_ORDER: ExtractionIssue['severity'][] = ['error', 'warning', 'info']

/** Hinweise: Anmerkungen von Claude, Ergebnisse der automatischen Prüfung und Hinweise des Vorschlags. */
export function NotesSection() {
  const { extraction, device, proposal } = useReview()
  const issues = extraction.issues
    .filter((i) => !i.device || i.device === device.base_part)
    .sort((a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity))
  const proposalNotes = [
    ...(proposal?.warnings ?? []),
    ...(proposal?.symbols.flatMap((s) => s.warnings.map((w) => `Symbol ${s.name ?? ''}: ${w}`)) ?? []),
  ]
  const unique = [...new Set(proposalNotes)]
  const total = extraction.warnings.length + issues.length + unique.length

  return (
    <Section id="hinweise" title="Hinweise" icon={<MessageSquareQuote />} count={total}>
      {total === 0 ? (
        <p className="text-xs text-fg-muted">Keine Hinweise – Claude hat keine Unklarheiten gemeldet und die Prüfung ist ohne Befund.</p>
      ) : (
        <div className="flex flex-col gap-4">
          {extraction.warnings.length > 0 && (
            <div>
              <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-spark-text">
                <Sparkles aria-hidden className="size-3.5" />
                Anmerkungen von Claude
              </h3>
              <ul className="flex flex-col gap-1.5 rounded-card border border-spark-b/25 bg-[linear-gradient(135deg,color-mix(in_oklab,var(--pf-spark-a)_5%,transparent),color-mix(in_oklab,var(--pf-spark-b)_7%,transparent))] px-3 py-2.5">
                {extraction.warnings.map((w) => (
                  <li key={w} className="text-xs leading-relaxed text-fg-muted">
                    {w}
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-2xs text-fg-subtle">Im Original (englisch) – so, wie Claude die Unklarheiten im Datenblatt beschreibt.</p>
            </div>
          )}
          {issues.length > 0 && (
            <div>
              <h3 className="micro-label mb-1.5">Automatische Prüfung</h3>
              <ul className="flex flex-col gap-1">
                {issues.map((i) => (
                  <li key={`${i.code}-${i.message}`} className="flex items-start gap-2 text-xs leading-relaxed">
                    {i.severity === 'error' ? (
                      <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger-text" />
                    ) : i.severity === 'warning' ? (
                      <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning-text" />
                    ) : (
                      <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-info-text" />
                    )}
                    <span className={cn(i.severity === 'error' ? 'text-fg' : 'text-fg-muted')}>{i.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {unique.length > 0 && (
            <div>
              <h3 className="micro-label mb-1.5">Vorschlag</h3>
              <ul className="flex flex-col gap-1">
                {unique.map((w) => (
                  <li key={w} className="flex items-start gap-2 text-xs leading-relaxed text-fg-muted">
                    <span aria-hidden className="mt-[7px] size-1 shrink-0 rounded-full bg-fg-subtle" />
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}
