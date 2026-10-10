import { useEffect, useState } from 'react'

/** Wert erst nach `delay` ms Ruhe übernehmen (z. B. den getippten Zielordner, bevor das Backend neu rechnet). */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    if (Object.is(value, debounced)) return
    const t = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(t)
  }, [value, debounced, delay])
  return debounced
}
