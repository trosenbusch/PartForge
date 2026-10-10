import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { Braces } from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useFieldContext, Spinner } from '@/components/ui'
import { controlShell } from '@/components/ui/variants'
import { cn } from '@/lib/cn'
import { buildToken, parseTemplate, TEMPLATE_FORMATS, tokenAt, type TemplateFormatDef, type TemplateSegmentToken } from './templateTokens'

export interface TemplateField {
  /** Spaltenname (z. B. „Resistance“) */
  name: string
  /** Deutsche Bezeichnung */
  label?: string
  description?: string
  /** Feldart (quantity, enum, text …) – Formate gelten nur für technische Werte */
  kind?: string
  unit?: string | null
}

export type TemplateFormat = TemplateFormatDef

export interface TemplateTokenInputProps {
  value: string
  onValueChange: (value: string) => void
  fields: TemplateField[]
  formats?: TemplateFormat[]
  /** gerenderte Vorschau (z. B. vom Backend) */
  preview?: ReactNode
  previewLoading?: boolean
  /** entprellt bei jeder Änderung – zum Anfordern der Live-Vorschau */
  onPreviewRequest?: (value: string) => void
  debounceMs?: number
  placeholder?: string
  invalid?: boolean
  disabled?: boolean
  size?: 'sm' | 'md'
  id?: string
  'aria-label'?: string
  className?: string
}

interface Suggestion {
  key: string
  value: string
  label: string
  detail?: string
  hint?: string
}

const fold = (s: string, locale: string) => s.toLocaleLowerCase(locale)

let measureCtx: CanvasRenderingContext2D | null = null
function textWidth(text: string, font: string): number {
  if (!measureCtx) measureCtx = document.createElement('canvas').getContext('2d')
  if (!measureCtx) return text.length * 7
  measureCtx.font = font
  return measureCtx.measureText(text).width
}

export function TemplateTokenInput({
  value,
  onValueChange,
  fields,
  formats = TEMPLATE_FORMATS,
  preview,
  previewLoading,
  onPreviewRequest,
  debounceMs = 300,
  placeholder = tr("z. B. RES {Size} {Resistance} {Tolerance}"),
  invalid,
  disabled,
  size = 'md',
  id,
  'aria-label': ariaLabel,
  className,
}: TemplateTokenInputProps) {
  const { t: tr, locale } = useI18n()
  const field = useFieldContext()
  const uid = useId().replace(/:/g, '')
  const inputId = id ?? field?.id ?? `${uid}-input`
  const inputRef = useRef<HTMLInputElement>(null)
  const mirrorRef = useRef<HTMLDivElement>(null)
  const [caret, setCaret] = useState(0)
  const [open, setOpen] = useState(false)
  const [highlighted, setHighlighted] = useState(0)
  const [scrollLeft, setScrollLeft] = useState(0)

  const segments = useMemo(() => parseTemplate(value), [value])
  const known = useMemo(() => new Map(fields.map((f) => [fold(f.name, locale), f])), [fields, locale])
  const formatNames = useMemo(() => new Set(formats.map((f) => f.name)), [formats])
  // nur abgeschlossene Platzhalter prüfen (während des Tippens nicht rot werden)
  const unknownCount = segments.filter((s) => s.kind === 'token' && s.closed && s.name && !known.has(fold(s.name, locale))).length

  // ------------------------------------------------------------------ Vorschläge
  const token = tokenAt(segments, caret)
  const mode: 'field' | 'format' | null = token ? (token.colon !== null && caret > token.colon ? 'format' : 'field') : null
  const query = token
    ? mode === 'format'
      ? value.slice((token.colon ?? token.start) + 1, caret).trim()
      : value.slice(token.start + 1, Math.min(caret, token.colon ?? caret)).trim()
    : ''
  const suggestions: Suggestion[] = useMemo(() => {
    if (!mode) return []
    const q = fold(query, locale)
    if (mode === 'format') {
      return formats
        .filter((f) => !q || fold(f.name, locale).startsWith(q) || fold(f.label, locale).includes(q))
        .map((f) => ({ key: `f:${f.name}`, value: f.name, label: f.name, detail: f.label, hint: f.example }))
    }
    const scored = fields
      .map((f) => {
        const n = fold(f.name, locale)
        const l = fold(f.label ?? '', locale)
        const score = !q ? 1 : n.startsWith(q) ? 3 : l.startsWith(q) ? 2 : n.includes(q) || l.includes(q) ? 1 : 0
        return { f, score }
      })
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
    return scored.slice(0, 40).map(({ f }) => ({
      key: `c:${f.name}`,
      value: f.name,
      label: f.name,
      detail: f.label && f.label !== f.name ? f.label : undefined,
      hint: f.unit ?? undefined,
    }))
  }, [mode, query, fields, formats, locale])
  const listOpen = open && !disabled && suggestions.length > 0
  const activeIndex = Math.min(highlighted, Math.max(0, suggestions.length - 1))

  const syncCaret = () => {
    const el = inputRef.current
    if (!el) return
    setCaret(el.selectionStart ?? el.value.length)
    setScrollLeft(el.scrollLeft)
  }

  const accept = (s: Suggestion) => {
    if (!token) return
    const name = mode === 'format' ? token.name : s.value
    const format = mode === 'format' ? s.value : token.format
    const text = buildToken(name, format || null)
    const next = value.slice(0, token.start) + text + value.slice(token.end)
    const pos = token.start + text.length
    onValueChange(next)
    setOpen(false)
    requestAnimationFrame(() => {
      const el = inputRef.current
      if (!el) return
      el.focus()
      el.setSelectionRange(pos, pos)
      syncCaret()
    })
  }

  /** „{“ an der Schreibmarke einfügen und die Feldliste öffnen */
  const openAtCaret = () => {
    const el = inputRef.current
    if (!el || disabled) return
    const pos = el.selectionStart ?? value.length
    if (!tokenAt(segments, pos)) {
      const next = `${value.slice(0, pos)}{}${value.slice(pos)}`
      onValueChange(next)
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(pos + 1, pos + 1)
        syncCaret()
        setOpen(true)
        setHighlighted(0)
      })
      return
    }
    el.focus()
    setOpen(true)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === ' ') {
      e.preventDefault()
      openAtCaret()
      return
    }
    if (!listOpen) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHighlighted((h) => (h + 1) % suggestions.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHighlighted((h) => (h - 1 + suggestions.length) % suggestions.length)
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      e.preventDefault()
      accept(suggestions[activeIndex])
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      setOpen(false)
    }
  }

  // Liste beim Tippen von „{“ / „:“ öffnen
  const tokenKey = token ? `${token.start}:${mode}` : ''
  useEffect(() => {
    if (tokenKey && document.activeElement === inputRef.current) setOpen(true)
  }, [tokenKey, tr])

  // entprellte Vorschau
  const requestRef = useRef(onPreviewRequest)
  useEffect(() => {
    requestRef.current = onPreviewRequest
  })
  useEffect(() => {
    if (!requestRef.current) return
    const t = window.setTimeout(() => requestRef.current?.(value), debounceMs)
    return () => window.clearTimeout(t)
  }, [value, debounceMs, tr])

  // Spiegel-Ebene mit dem Eingabefeld mitscrollen
  useLayoutEffect(() => {
    if (mirrorRef.current) mirrorRef.current.scrollLeft = scrollLeft
  }, [scrollLeft, value, tr])

  // Position der Liste unter dem Platzhalter
  const [listLeft, setListLeft] = useState(0)
  const tokenStart = token?.start ?? -1
  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el || tokenStart < 0) return
    const cs = getComputedStyle(el)
    const font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`
    const x = textWidth(value.slice(0, tokenStart), font) - el.scrollLeft
    setListLeft(Math.max(0, Math.min(x, el.clientWidth - 240)))
  }, [tokenStart, value, tr])

  const listId = `${uid}-list`
  const optionId = (i: number) => `${uid}-opt-${i}`

  const renderMirror = () =>
    segments.map((s, i) => {
      if (s.kind === 'text') return <span key={i}>{s.text}</span>
      const t = s as TemplateSegmentToken
      const fieldKnown = t.name ? known.has(fold(t.name, locale)) : false
      const formatOk = !t.format || formatNames.has(t.format.toLowerCase())
      const tone = !t.name || !t.closed ? 'pending' : !fieldKnown ? 'unknown' : !formatOk ? 'format' : 'ok'
      const raw = value.slice(t.start, t.end)
      return (
        <span
          key={i}
          className={cn(
            'rounded-[4px] [box-decoration-break:clone]',
            tone === 'ok' && 'bg-accent-soft text-accent-text shadow-[0_0_0_1px_color-mix(in_oklab,var(--pf-accent)_28%,transparent)]',
            tone === 'pending' && 'bg-surface-3 text-fg-muted',
            tone === 'unknown' &&
              'bg-danger/10 text-danger-text underline decoration-danger/70 decoration-wavy underline-offset-[3px] shadow-[0_0_0_1px_color-mix(in_oklab,var(--pf-danger)_30%,transparent)]',
            tone === 'format' && 'bg-warning/10 text-warning-text shadow-[0_0_0_1px_color-mix(in_oklab,var(--pf-warning)_30%,transparent)]',
          )}
        >
          <span className="opacity-55">{'{'}</span>
          {raw.slice(1, t.closed ? -1 : undefined)}
          {t.closed && <span className="opacity-55">{'}'}</span>}
        </span>
      )
    })

  const textSize = size === 'sm' ? 'text-xs' : 'text-ui'
  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="relative">
        <div
          data-invalid={invalid || field?.invalid || unknownCount > 0 || undefined}
          data-disabled={disabled || undefined}
          className={cn(controlShell({ size }), 'relative gap-1 pr-1')}
        >
          <div className="relative h-full min-w-0 flex-1">
            {/* Spiegel mit Chips – gleiche Schrift und Abstände wie das Eingabefeld */}
            <div
              ref={mirrorRef}
              aria-hidden
              className={cn('mono pointer-events-none absolute inset-0 flex items-center overflow-hidden whitespace-pre text-fg', textSize)}
            >
              <span className="pr-8">{value ? renderMirror() : null}</span>
            </div>
            <input
              ref={inputRef}
              id={inputId}
              type="text"
              role="combobox"
              aria-label={ariaLabel}
              aria-autocomplete="list"
              aria-expanded={listOpen}
              aria-controls={listId}
              aria-activedescendant={listOpen ? optionId(activeIndex) : undefined}
              aria-invalid={invalid || field?.invalid || unknownCount > 0 || undefined}
              aria-describedby={[field?.describedBy, `${uid}-preview`].filter(Boolean).join(' ') || undefined}
              aria-required={field?.required || undefined}
              autoComplete="off"
              spellCheck={false}
              disabled={disabled ?? field?.disabled}
              value={value}
              placeholder={placeholder}
              onChange={(e) => {
                onValueChange(e.target.value)
                setHighlighted(0)
                requestAnimationFrame(syncCaret)
              }}
              onKeyDown={onKeyDown}
              onKeyUp={syncCaret}
              onClick={syncCaret}
              onSelect={syncCaret}
              onScroll={syncCaret}
              onFocus={syncCaret}
              onBlur={() => window.setTimeout(() => setOpen(false), 120)}
              className={cn(
                'mono relative h-full w-full min-w-0 bg-transparent text-transparent caret-fg outline-none selection:bg-accent/30',
                'placeholder:font-sans placeholder:tracking-normal placeholder:text-fg-subtle',
                textSize,
              )}
            />
          </div>
          <button
            type="button"
            tabIndex={-1}
            onMouseDown={(e) => e.preventDefault()}
            onClick={openAtCaret}
            disabled={disabled}
            title={tr("Feld einfügen (Strg+Leertaste)")}
            aria-label={tr("Feld einfügen")}
            className="flex size-6 shrink-0 items-center justify-center rounded-[6px] text-fg-subtle outline-none transition-colors hover:bg-surface-3 hover:text-fg [&_svg]:size-3.5"
          >
            <Braces aria-hidden />
          </button>
        </div>

        {listOpen && (
          <div
            id={listId}
            role="listbox"
            aria-label={mode === 'format' ? tr("Formate") : tr("Felder")}
            className="glass pop-anim absolute top-full z-popover mt-1.5 max-h-64 w-60 overflow-y-auto rounded-card p-1"
            style={{ left: listLeft }}
            data-state="open"
            data-side="bottom"
          >
            <div className="micro-label px-2 pb-1 pt-1.5">{mode === 'format' ? 'Format' : tr("Feld einfügen")}</div>
            {suggestions.map((s, i) => (
              <div
                key={s.key}
                id={optionId(i)}
                role="option"
                aria-selected={i === activeIndex}
                tabIndex={-1}
                onMouseDown={(e) => {
                  // Fokus bleibt im Eingabefeld
                  e.preventDefault()
                  accept(s)
                }}
                onMouseEnter={() => setHighlighted(i)}
                className={cn(
                  'flex cursor-pointer items-center gap-2 rounded-control px-2 py-1.5 text-ui',
                  i === activeIndex ? 'bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)] text-fg' : 'text-fg-muted',
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="mono block truncate text-xs text-fg">{s.label}</span>
                  {s.detail && <span className="block truncate text-2xs text-fg-subtle">{s.detail}</span>}
                </span>
                {s.hint && <span className="mono shrink-0 text-2xs text-fg-subtle">{s.hint}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div id={`${uid}-preview`} className="flex min-h-6 items-center gap-2 text-xs" aria-live="polite">
        <span className="micro-label shrink-0">{tr("Vorschau")}</span>
        {previewLoading ? (
          <Spinner size={12} tone="accent" />
        ) : preview !== undefined && preview !== null && preview !== '' ? (
          <span className="mono min-w-0 truncate text-fg">{preview}</span>
        ) : (
          <span className="text-fg-subtle">–</span>
        )}
        {unknownCount > 0 && (
          <span className="ml-auto shrink-0 text-danger-text">
            {unknownCount === 1 ? tr("1 unbekanntes Feld") : tr("{0} unbekannte Felder", { "0": String(unknownCount) })}
          </span>
        )}
      </div>
    </div>
  )
}
