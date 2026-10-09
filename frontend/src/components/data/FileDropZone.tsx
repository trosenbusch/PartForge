/**
 * Datei-Drop-Zone (react-dropzone) mit Varianten für Datenblätter (PDF, KI-Stil) und Tabellen (CSV/XLSX).
 * Die ganze Fläche ist ein Knopf (Klick, Enter, Leertaste öffnen die Dateiauswahl); beim Ziehen animiert der Rahmen,
 * falsche Dateitypen werden rot markiert und auf Deutsch erklärt. Das globale Datenblatt-Overlay ist unterdrückt,
 * solange die Zone sichtbar ist.
 *
 *   <FileDropZone variant="pdf" onFiles={(files) => startImport(files)} />   // KI-Analyse (Funken); KI aus/kein Schlüssel → neutral
 *   <FileDropZone variant="pdf" tone="neutral" onFiles={…} />               // PDF ablegen ohne KI-Bezug (z. B. Datenblatt anhängen)
 *   <FileDropZone variant="table" size="sm" onFiles={([file]) => preview(file)} multiple={false} />
 */
import { motion, useReducedMotion } from 'motion/react'
import { FilePlus2, FileSpreadsheet, FileText, Sparkles } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { useDropzone, type Accept, type FileError, type FileRejection } from 'react-dropzone'
import { useSettings } from '@/api/system'
import { useSuppressGlobalDrop } from '@/app/stores'
import { FORGE_STOPS, SPARK_STOPS, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes } from '@/lib/format'

export type FileDropVariant = 'pdf' | 'table' | 'csv' | 'xlsx'

const ACCEPT: Record<FileDropVariant, Accept> = {
  pdf: { 'application/pdf': ['.pdf'] },
  csv: { 'text/csv': ['.csv'], 'application/vnd.ms-excel': ['.csv'], 'text/plain': ['.csv'] },
  xlsx: {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    'application/vnd.ms-excel': ['.xls'],
  },
  table: {
    'text/csv': ['.csv'],
    'text/plain': ['.csv'],
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
    'application/vnd.ms-excel': ['.xls', '.csv'],
  },
}

const TYPES_LABEL: Record<FileDropVariant, string> = {
  pdf: 'PDF',
  csv: 'CSV',
  xlsx: 'Excel (XLSX)',
  table: 'CSV oder Excel (XLSX)',
}

const DEFAULT_TITLE: Record<FileDropVariant, string> = {
  pdf: 'Datenblatt hierher ziehen',
  csv: 'CSV-Datei hierher ziehen',
  xlsx: 'Excel-Datei hierher ziehen',
  table: 'Tabelle hierher ziehen',
}

const DEFAULT_DESCRIPTION: Record<FileDropVariant, string> = {
  pdf: 'Parameter, Pinbelegung und Gehäusemaße werden mit KI erkannt und als Bauteil-Vorschlag aufbereitet.',
  csv: 'Spalten werden automatisch den Feldern der Kategorie zugeordnet.',
  xlsx: 'Das erste Tabellenblatt wird gelesen; Spalten werden automatisch zugeordnet.',
  table: 'Spalten werden automatisch den Feldern der Kategorie zugeordnet – Vorschau vor dem Import.',
}

/** Datenblatt ohne KI (ausgeschaltet bzw. kein Schlüssel): nichts versprechen, was nicht passiert */
const NEUTRAL_PDF_DESCRIPTION =
  'Das PDF wird in der Bibliothek abgelegt und lässt sich durchsuchen und Bauteilen zuordnen – die Analyse mit KI ist derzeit nicht verfügbar.'

/**
 * `ai` = KI-Analyse (Funken-Stil, Cyan→Violett), `neutral` = gewöhnlicher Datei-Upload ohne KI-Versprechen,
 * `auto` = `ai`, solange die KI eingeschaltet und ein Schlüssel hinterlegt ist, sonst `neutral`
 */
export type FileDropTone = 'ai' | 'neutral' | 'auto'

export interface FileDropZoneProps {
  variant?: FileDropVariant
  /**
   * Stil und Texte: `ai` = Funken, „Loslassen zum Analysieren“; `neutral` = ohne KI-Versprechen. Standard bei `pdf`:
   * `auto` – neutral, sobald die KI ausgeschaltet oder kein Schlüssel hinterlegt ist; bei Tabellen `neutral`.
   */
  tone?: FileDropTone
  /** Akzeptierte Dateien (nach Typ- und Größenprüfung) */
  onFiles: (files: File[]) => void
  /** Abgelehnte Dateien (zusätzlich zur Anzeige in der Zone) */
  onReject?: (rejections: FileRejection[]) => void
  multiple?: boolean
  /** Höchstgröße in Byte (Standard: PDF 50 MB, Tabellen 20 MB) */
  maxSize?: number
  disabled?: boolean
  /** Verarbeitung läuft – Text statt Hinweis, Zone gesperrt */
  busy?: boolean | string
  size?: 'lg' | 'md' | 'sm'
  title?: ReactNode
  description?: ReactNode
  /** Eigene Typen statt der Variante – dazu `typesLabel` setzen, damit Hinweis und Fehlermeldung stimmen */
  accept?: Accept
  /**
   * Erlaubte Typen in Worten für Hinweiszeile und Ablehnung („CSV, Excel oder OpenDocument“).
   * Standard: aus der Variante („PDF“, „CSV oder Excel (XLSX)“ …).
   */
  typesLabel?: string
  /**
   * Hinweiszeile unter dem Titel (Standard: „PDF · bis 50 MB · mehrere Dateien möglich“) – eigener Text bzw.
   * `false` = keine Hinweiszeile.
   */
  hint?: ReactNode | false
  className?: string
}

const GERMAN: Record<string, (e: FileError, f: File, max?: number) => string> = {
  'file-invalid-type': (_e, f) => `„${f.name}“ hat ein nicht unterstütztes Format.`,
  'file-too-large': (_e, f, max) => `„${f.name}“ ist zu groß (${formatBytes(f.size)}${max ? `, höchstens ${formatBytes(max)}` : ''}).`,
  'file-too-small': (_e, f) => `„${f.name}“ ist leer.`,
  'too-many-files': () => 'Bitte nur eine Datei ablegen.',
}

/** Animiertes Dokument (PDF) bzw. Tabellenblatt */
function DropIllustration({
  variant,
  spark,
  active,
  reject,
}: {
  variant: FileDropVariant
  /** KI-Stil (Funken-Verlauf, Scan-Strahl) */
  spark: boolean
  active: boolean
  reject: boolean
}) {
  const reduce = useReducedMotion()
  const gid = `dz${useId().replace(/:/g, '')}`
  const pdf = variant === 'pdf'
  const accent = reject ? 'var(--pf-danger)' : spark ? `url(#${gid}-spark)` : `url(#${gid}-forge)`
  return (
    <motion.svg
      viewBox="0 0 120 120"
      className="h-auto w-24 overflow-visible"
      aria-hidden
      animate={reduce ? undefined : active ? { y: -8, rotate: pdf ? -4 : 3, scale: 1.06 } : { y: 0, rotate: 0, scale: 1 }}
      transition={{ type: 'spring', stiffness: 300, damping: 18 }}
    >
      <defs>
        <linearGradient id={`${gid}-spark`} x1="0" y1="0" x2="1" y2="1">
          {SPARK_STOPS.map(([offset, color]) => (
            <stop key={offset} offset={offset} style={{ stopColor: color }} />
          ))}
        </linearGradient>
        <linearGradient id={`${gid}-forge`} x1="0" y1="0" x2="1" y2="1">
          {FORGE_STOPS.map(([offset, color]) => (
            <stop key={offset} offset={offset} style={{ stopColor: color }} />
          ))}
        </linearGradient>
        <clipPath id={`${gid}-page`}>
          <path d="M32 14h40l20 20v66a6 6 0 0 1-6 6H32a6 6 0 0 1-6-6V20a6 6 0 0 1 6-6z" />
        </clipPath>
      </defs>
      <ellipse cx="60" cy="112" rx="30" ry="4" fill="currentColor" opacity="0.08" />
      {/* zweites Blatt dahinter */}
      <path
        d="M40 8h36l18 18v62a6 6 0 0 1-6 6H40a6 6 0 0 1-6-6V14a6 6 0 0 1 6-6z"
        fill="var(--pf-surface-3)"
        stroke="var(--pf-line-strong)"
        strokeWidth="1.5"
        opacity="0.7"
        transform="translate(6 -2)"
      />
      <path
        d="M32 14h40l20 20v66a6 6 0 0 1-6 6H32a6 6 0 0 1-6-6V20a6 6 0 0 1 6-6z"
        fill="var(--pf-surface-2)"
        stroke="var(--pf-line-strong)"
        strokeWidth="1.5"
      />
      <path d="M72 14v14a6 6 0 0 0 6 6h14" fill="var(--pf-surface-3)" stroke="var(--pf-line-strong)" strokeWidth="1.5" />
      {pdf ? (
        <>
          <rect x="34" y="42" width="30" height="5" rx="2.5" fill={accent} />
          {[54, 62, 70, 78].map((y, i) => (
            <rect key={y} x="34" y={y} width={i % 2 ? 38 : 48} height="3.5" rx="1.75" fill="var(--pf-fg-subtle)" opacity="0.45" />
          ))}
          <rect x="34" y="88" width="20" height="9" rx="2" fill="none" stroke="var(--pf-fg-subtle)" strokeOpacity="0.5" />
          {/* Scan-Strahl während des Ziehens (nur KI-Analyse) */}
          {spark && active && !reject && !reduce && (
            <g clipPath={`url(#${gid}-page)`}>
              <motion.rect
                x="20"
                width="80"
                height="16"
                fill={`url(#${gid}-spark)`}
                opacity="0.35"
                initial={{ y: 20 }}
                animate={{ y: [20, 92, 20] }}
                transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
              />
            </g>
          )}
        </>
      ) : (
        <>
          <rect x="34" y="40" width="50" height="9" rx="2" fill={accent} opacity="0.9" />
          {[52, 61, 70, 79, 88].map((y) => (
            <g key={y}>
              <rect x="34" y={y} width="15" height="6" rx="1.5" fill="var(--pf-fg-subtle)" opacity="0.35" />
              <rect x="52" y={y} width="15" height="6" rx="1.5" fill="var(--pf-fg-subtle)" opacity="0.25" />
              <rect x="70" y={y} width="14" height="6" rx="1.5" fill="var(--pf-fg-subtle)" opacity="0.25" />
            </g>
          ))}
        </>
      )}
      {/* Abzeichen */}
      <g transform="translate(78 78)">
        <circle r="14" fill="var(--pf-bg-elev)" stroke={accent} strokeWidth="2" />
        {reject ? (
          <path d="M-5 -5 L5 5 M5 -5 L-5 5" stroke="var(--pf-danger)" strokeWidth="2.4" strokeLinecap="round" />
        ) : spark ? (
          <path d="M0 -7 Q1.6 -1.6 7 0 Q1.6 1.6 0 7 Q-1.6 1.6 -7 0 Q-1.6 -1.6 0 -7Z" fill={`url(#${gid}-spark)`} />
        ) : (
          <path d="M0 -6 V5 M-5 0 L0 5 L5 0" stroke={`url(#${gid}-forge)`} strokeWidth="2.4" strokeLinecap="round" fill="none" />
        )}
      </g>
    </motion.svg>
  )
}

export function FileDropZone({
  variant = 'pdf',
  tone,
  onFiles,
  onReject,
  multiple = true,
  maxSize,
  disabled,
  busy,
  size = 'lg',
  title,
  description,
  accept,
  typesLabel,
  hint: hintProp,
  className,
}: FileDropZoneProps) {
  useSuppressGlobalDrop(!disabled)
  const uid = useId().replace(/:/g, '')
  const limit = maxSize ?? (variant === 'pdf' ? 50 * 1024 * 1024 : 20 * 1024 * 1024)
  const locked = Boolean(disabled || busy)
  const { getRootProps, getInputProps, isDragActive, isDragAccept, isDragReject, fileRejections } = useDropzone({
    accept: accept ?? ACCEPT[variant],
    multiple,
    maxSize: limit,
    disabled: locked,
    getErrorMessage: (error, file) => GERMAN[error.code]?.(error, file, limit) ?? error.message,
    onDrop: (accepted, rejected) => {
      if (accepted.length) onFiles(accepted)
      if (rejected.length) onReject?.(rejected)
    },
  })

  const pdf = variant === 'pdf'
  // KI nutzbar? (Einstellungen sind im Cache – Seitenleiste; solange unbekannt: KI-Stil wie bisher)
  const settings = useSettings().data
  const aiUsable = settings ? settings.settings.ai.enabled && settings.ai_key_configured : true
  const resolvedTone = tone ?? (pdf ? 'auto' : 'neutral')
  /** KI-Stil (Funken) – nie, wenn die KI gar nicht analysieren kann */
  const spark = resolvedTone === 'ai' || (resolvedTone === 'auto' && aiUsable)
  const active = isDragActive && !isDragReject
  const reject = isDragReject
  const titleText = reject
    ? 'Dieser Dateityp wird nicht unterstützt'
    : active
      ? spark
        ? 'Loslassen zum Analysieren'
        : pdf
          ? 'Loslassen zum Hinzufügen'
          : 'Loslassen zum Importieren'
      : (title ?? DEFAULT_TITLE[variant])
  const busyText = typeof busy === 'string' ? busy : 'Wird verarbeitet …'
  const types = typesLabel ?? TYPES_LABEL[variant]
  const hint =
    hintProp === false
      ? null
      : (hintProp ?? `${types} · bis ${formatBytes(limit)}${multiple ? ' · mehrere Dateien möglich' : ''}`)
  const descriptionText = reject
    ? `Erlaubt: ${types}.`
    : (description ?? (pdf && !spark ? NEUTRAL_PDF_DESCRIPTION : DEFAULT_DESCRIPTION[variant]))
  const showDescription = size !== 'sm' && !busy
  const Icon = pdf ? FileText : FileSpreadsheet
  const ChipIcon = spark ? Sparkles : pdf ? FilePlus2 : FileSpreadsheet
  const describedBy = [showDescription ? `${uid}-desc` : null, hint !== null ? `${uid}-hint` : null].filter(Boolean).join(' ')

  const frame = (
    <svg aria-hidden className="pointer-events-none absolute inset-0 size-full overflow-visible">
      <defs>
        <linearGradient id={`${uid}-frame`} x1="0" y1="0" x2="1" y2="1">
          {(spark ? SPARK_STOPS : FORGE_STOPS).map(([offset, color]) => (
            <stop key={offset} offset={offset} style={{ stopColor: color }} />
          ))}
        </linearGradient>
      </defs>
      <rect
        x="1"
        y="1"
        rx={size === 'sm' ? 13 : 19}
        style={{ width: 'calc(100% - 2px)', height: 'calc(100% - 2px)' }}
        fill="none"
        stroke={reject ? 'var(--pf-danger)' : isDragAccept || active ? `url(#${uid}-frame)` : 'var(--pf-line-control)'}
        strokeOpacity={isDragActive ? 1 : 0.55}
        strokeWidth={isDragActive ? 2 : 1.5}
        strokeDasharray={size === 'sm' ? '6 6' : '8 8'}
        className={cn(isDragActive && 'animate-dash')}
      />
    </svg>
  )

  // Name = sichtbarer Titel (+ „oder klicken …“ nur für Screenreader), Beschreibung und Hinweis als Beschreibung –
  // kein aria-label, damit Sprachsteuerung den sichtbaren Titel trifft
  const root = getRootProps({
    role: 'button',
    'aria-describedby': describedBy || undefined,
    'aria-disabled': locked || undefined,
  })

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      {/* Dateiauswahl außerhalb des Knopfs (keine verschachtelten Bedienelemente) – der Knopf öffnet sie */}
      <input {...getInputProps()} />
      <div
        {...root}
        className={cn(
          'group/drop relative isolate flex cursor-pointer outline-none transition-[background-color,box-shadow] duration-200 focus-ring',
          size === 'sm'
            ? 'items-center gap-3 rounded-card px-3.5 py-3'
            : cn('flex-col items-center justify-center text-center', size === 'lg' ? 'gap-4 rounded-panel px-8 py-10' : 'gap-3 rounded-panel px-6 py-7'),
          isDragActive
            ? reject
              ? 'bg-danger/5'
              : spark
                ? 'bg-[color-mix(in_oklab,#818cf8_7%,transparent)] shadow-glow-spark'
                : 'bg-[var(--pf-ember-faint)] shadow-glow'
            : 'bg-surface-2/40 hover:bg-surface-2/80',
          locked && 'cursor-progress opacity-80',
        )}
      >
        {frame}
        {size !== 'sm' && (
          <div
            aria-hidden
            className={cn(
              'pointer-events-none absolute inset-0 -z-10 rounded-[inherit] opacity-0 transition-opacity duration-300',
              isDragActive && !reject && 'opacity-100',
              spark
                ? 'bg-[radial-gradient(closest-side,color-mix(in_oklab,#818cf8_16%,transparent),transparent)]'
                : 'bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]',
            )}
          />
        )}

        {size === 'sm' ? (
          <span
            aria-hidden
            className={cn(
              'flex size-9 shrink-0 items-center justify-center rounded-button border [&_svg]:size-[18px]',
              reject
                ? 'border-danger/30 bg-danger/10 text-danger-text'
                : spark
                  ? 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] text-spark-text'
                  : 'border-line-strong bg-surface-2 text-fg-muted',
            )}
          >
            {busy ? <Spinner size={16} tone={spark ? 'spark' : 'accent'} /> : <Icon />}
          </span>
        ) : busy ? (
          <div className="flex h-24 items-center justify-center">
            <Spinner size={36} tone={spark ? 'spark' : 'accent'} label={busyText} />
          </div>
        ) : (
          <DropIllustration variant={variant} spark={spark} active={isDragActive} reject={reject} />
        )}

        <div className={cn('min-w-0', size === 'sm' ? 'flex-1' : 'flex max-w-md flex-col items-center gap-1.5')}>
          <div
            className={cn(
              'font-semibold tracking-[-0.01em]',
              size === 'lg' ? 'text-md' : 'text-ui',
              reject ? 'text-danger-text' : 'text-fg',
            )}
          >
            {busy ? busyText : titleText}
            {!busy && <span className="sr-only"> – oder klicken, um Dateien auszuwählen</span>}
          </div>
          {showDescription && (
            <p id={`${uid}-desc`} aria-hidden className="text-ui leading-relaxed text-fg-muted">
              {descriptionText}
            </p>
          )}
          {hint !== null && (
            <p id={`${uid}-hint`} aria-hidden className={cn('text-xs text-fg-subtle', size === 'sm' ? 'mt-0.5 truncate' : 'mt-1')}>
              {size === 'sm' && reject ? `Erlaubt: ${types}` : hint}
            </p>
          )}
        </div>

        {!busy && (
          <span
            aria-hidden
            className={cn(
              'inline-flex h-7 shrink-0 items-center gap-1.5 rounded-control border px-2.5 text-xs font-medium shadow-[inset_0_1px_0_var(--pf-highlight)] transition-colors',
              spark
                ? 'spark-border-static text-fg [--spark-fill:var(--pf-surface-2)] group-hover/drop:[--spark-fill:var(--pf-surface-3)] [&_svg]:size-3.5 [&_svg]:text-spark-a'
                : 'border-line-strong bg-surface-2 text-fg group-hover/drop:bg-surface-3 [&_svg]:size-3.5',
              size !== 'sm' && 'mt-1',
            )}
          >
            <ChipIcon />
            Datei auswählen
          </span>
        )}
      </div>
      <div aria-live="polite" className="empty:hidden">
        {fileRejections.length > 0 && !isDragActive && (
          <ul className="flex flex-col gap-0.5 rounded-control border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger-text">
            {fileRejections.slice(0, 4).map((r) => (
              <li key={`${r.file.name}-${r.file.size}`}>{r.errors.map((e) => e.message).join(' ')}</li>
            ))}
            {fileRejections.length > 4 && <li>… und {fileRejections.length - 4} weitere</li>}
          </ul>
        )}
      </div>
    </div>
  )
}
