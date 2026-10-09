import { useEffect, useState } from 'react'

/** Wert verzögert übernehmen (Eingaben entprellen). Inhaltlich gleiche Werte (JSON) lösen kein Update aus. */
export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  const key = JSON.stringify(value) ?? ''
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(key === '' ? (undefined as T) : (JSON.parse(key) as T)), ms)
    return () => window.clearTimeout(t)
  }, [key, ms])
  return debounced
}
