import { FolderSearch } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { pickFile, pickFolder, useNativeBridge } from '@/lib/native'
import { Button } from './Button'
import { Input } from './Input'

export interface PathInputProps {
  value: string
  onValueChange: (value: string) => void
  placeholder?: string
  /** Icon links im Feld */
  prefix?: ReactNode
  /** Status rechts im Feld (z. B. ✓ gefunden) */
  suffix?: ReactNode
  /** „Durchsuchen …“ anbieten, sobald das Desktop-Fenster einen Dateidialog bereitstellt */
  browse?: 'folder' | 'file'
  /** Dateifilter für den Dateidialog, z. B. ['Programme (*.exe)'] */
  fileFilters?: string[]
  disabled?: boolean
  invalid?: boolean
  size?: 'sm' | 'md' | 'lg'
  id?: string
  className?: string
  'aria-label'?: string
}

/**
 * Pfadfeld: zeigt ohne Fokus das **Ende** des Pfads (Dateiname statt Laufwerk), Monospace, ohne
 * Rechtschreibprüfung. Mit `browse` erscheint „Durchsuchen …“, sobald pywebview einen Dialog anbietet.
 */
export function PathInput({
  value,
  onValueChange,
  placeholder,
  prefix,
  suffix,
  browse,
  fileFilters,
  disabled,
  invalid,
  size = 'md',
  id,
  className,
  'aria-label': ariaLabel,
}: PathInputProps) {
  const ref = useRef<HTMLInputElement>(null)
  const bridge = useNativeBridge()
  const canBrowse = browse === 'folder' ? bridge.canPickFolder : browse === 'file' ? bridge.canPickFile : false

  // Ohne Fokus ans Ende scrollen – bei langen Pfaden ist der Dateiname das Wichtigste
  useLayoutEffect(() => {
    const el = ref.current
    if (el && document.activeElement !== el) el.scrollLeft = el.scrollWidth
  }, [value])
  // … auch nachdem die Monospace-Schrift geladen ist oder sich die Breite ändert
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const toEnd = () => {
      if (document.activeElement !== el) el.scrollLeft = el.scrollWidth
    }
    void document.fonts?.ready.then(toEnd)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(toEnd) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [])

  const onBrowse = async () => {
    const picked = browse === 'folder' ? await pickFolder(value || null) : await pickFile(value || null, fileFilters)
    if (picked) onValueChange(picked)
  }

  return (
    <div className={cn('flex min-w-0 gap-2', className)}>
      <Input
        ref={ref}
        id={id}
        mono
        size={size}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        onBlur={(e) => {
          e.currentTarget.scrollLeft = e.currentTarget.scrollWidth
        }}
        placeholder={placeholder}
        prefix={prefix}
        suffix={suffix}
        spellCheck={false}
        autoComplete="off"
        disabled={disabled}
        invalid={invalid}
        aria-label={ariaLabel}
        title={value || undefined}
      />
      {canBrowse && (
        <Button variant="secondary" size={size} leftIcon={<FolderSearch />} onClick={() => void onBrowse()} disabled={disabled}>
          Durchsuchen …
        </Button>
      )}
    </div>
  )
}
