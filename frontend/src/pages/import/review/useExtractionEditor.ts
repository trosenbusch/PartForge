import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { datasheetKeys, useSaveExtraction, type ExtractionData, type ExtractionOut } from '@/api/datasheets'

export interface ExtractionEditor {
  /** Korrektur anwenden (sofort sichtbar) und speichern; `label` erscheint bei „Rückgängig“. */
  apply: (label: string, change: (draft: ExtractionData) => void) => void
  undo: () => void
  canUndo: boolean
  lastLabel: string | null
  saving: boolean
  /** Zahl der Korrekturen in dieser Sitzung */
  count: number
}

const MAX_UNDO = 30

/**
 * Korrekturen an der Extraktion (Pins, Maße, Lötflächen, Gehäusezuordnung): optimistisch im Cache, gespeichert
 * über PUT …/extraction (der Server bereinigt und prüft neu – seine Antwort ersetzt den Stand). Rückgängig je
 * Sitzung (bis zu 30 Schritte).
 */
export function useExtractionEditor(datasheetId: string): ExtractionEditor {
  const qc = useQueryClient()
  const { mutate, isPending } = useSaveExtraction(datasheetId)
  const [stack, setStack] = useState<{ label: string; data: ExtractionData }[]>([])
  const [count, setCount] = useState(0)

  const apply = useCallback(
    (label: string, change: (draft: ExtractionData) => void) => {
      const key = datasheetKeys.extraction(datasheetId)
      const current = qc.getQueryData<ExtractionOut>(key)
      if (!current) return
      const next = structuredClone(current.extraction)
      change(next)
      if (JSON.stringify(next) === JSON.stringify(current.extraction)) return
      setStack((s) => [...s.slice(-(MAX_UNDO - 1)), { label, data: current.extraction }])
      setCount((n) => n + 1)
      qc.setQueryData<ExtractionOut>(key, { ...current, extraction: next, edited: true })
      mutate(next)
    },
    [qc, datasheetId, mutate],
  )

  const undo = useCallback(() => {
    const key = datasheetKeys.extraction(datasheetId)
    const last = stack[stack.length - 1]
    const current = qc.getQueryData<ExtractionOut>(key)
    if (!last || !current) return
    setStack((s) => s.slice(0, -1))
    setCount((n) => Math.max(0, n - 1))
    qc.setQueryData<ExtractionOut>(key, { ...current, extraction: last.data })
    mutate(last.data)
  }, [qc, datasheetId, stack, mutate])

  return {
    apply,
    undo,
    canUndo: stack.length > 0,
    lastLabel: stack.length ? stack[stack.length - 1].label : null,
    saving: isPending,
    count,
  }
}
