/**
 * Aufbau einer Teilenummer: Segmente in Monospace mit farbiger Unterstreichung je Bedeutung (Baugröße, Wert, Codes);
 * Beschriftungen darunter (`labels`), Bedeutung im Tooltip. Ohne Segmente wird die Teilenummer schlicht gezeigt.
 * Screenreader hören die Teilenummer und ihre Bedeutung als einen Text. Segmente kommen vom Backend
 * (`TemplateSummary.example`) oder aus `splitMpn` – Werte wie „10kΩ“ erscheinen deutsch („10 kΩ“).
 */
import type { CSSProperties } from 'react'
import type { MpnSegment } from '@/api/series'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'

/** Bedeutung für die Anzeige: Werte deutsch („10kΩ“ → „10 kΩ“), Codetexte unverändert */
const meaningText = (s: MpnSegment): string | null => (s.meaning && s.kind === 'value' ? formatQuantityText(s.meaning) : s.meaning)

/** Farben der Segmente (Diagrammpalette ohne Kupfer – Kupfer bleibt Signalfarbe) */
const TINTS = ['var(--pf-chart-2)', 'var(--pf-chart-5)', 'var(--pf-chart-3)', 'var(--pf-chart-4)', 'var(--pf-chart-6)']

export interface MpnAnatomyProps {
  mpn: string
  segments: MpnSegment[] | null | undefined
  /** Beschriftung unter den Segmenten (`short` = Kurzformen für Karten) */
  labels?: boolean | 'short'
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function MpnAnatomy({ mpn, segments, labels = false, size = 'md', className }: MpnAnatomyProps) {
  const text = size === 'lg' ? 'text-h3' : size === 'md' ? 'text-md' : 'text-ui'
  if (!segments?.length) {
    return (
      <span className={cn('mono break-all font-medium tracking-[0.02em] text-fg', text, className)} translate="no">
        {mpn}
      </span>
    )
  }
  let codeIndex = 0
  const items = segments.map((s) => {
    let tint: string | null = null
    if (s.kind === 'size') tint = TINTS[0]
    else if (s.kind === 'value') tint = TINTS[1]
    else if (s.kind === 'code') tint = TINTS[2 + (codeIndex++ % 3)]
    return { s, tint }
  })
  const spoken = segments
    .filter((s) => s.kind !== 'literal')
    .map((s) => {
      const meaning = meaningText(s)
      return `${s.label} ${s.text}${meaning ? ` (${meaning})` : ''}`
    })
    .join(', ')
  return (
    <span className={cn('inline-flex max-w-full flex-wrap items-start gap-y-1.5', className)} translate="no">
      <span className="sr-only">{`${mpn} – ${spoken}`}</span>
      {items.map(({ s, tint }, i) => {
        const body = (
          <span
            aria-hidden
            className={cn('flex min-w-0 flex-col items-start', labels && s.kind !== 'literal' && 'pr-2')}
            style={tint ? ({ '--seg': tint } as CSSProperties) : undefined}
          >
            <span
              className={cn(
                'mono whitespace-pre border-b-2 pb-0.5 font-medium leading-tight tracking-[0.02em]',
                text,
                s.kind === 'literal'
                  ? 'border-transparent text-fg-muted'
                  : 'border-[color-mix(in_oklab,var(--seg)_78%,transparent)] text-fg',
              )}
            >
              {s.text}
            </span>
            {labels && (
              <span className="mt-1 h-3 whitespace-nowrap text-2xs leading-3 text-fg-subtle">
                {s.kind === 'literal' ? '' : labels === 'short' ? s.short : s.label}
              </span>
            )}
          </span>
        )
        if (s.kind === 'literal') return <span key={i}>{body}</span>
        return (
          <Tooltip
            key={i}
            content={
              <span>
                <span className="font-medium text-fg">{s.label}</span>
                <span className="mono text-fg-muted"> {s.text}</span>
                {s.meaning ? <span className="text-fg-muted"> · {meaningText(s)}</span> : null}
              </span>
            }
          >
            <span className="cursor-default">{body}</span>
          </Tooltip>
        )
      })}
    </span>
  )
}
