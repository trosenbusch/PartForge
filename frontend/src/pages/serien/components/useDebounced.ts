import { useEffect, useState } from 'react'

/** Wert erst übernehmen, wenn er sich `delay` ms nicht geändert hat */
export function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(t)
  }, [value, delay])
  return debounced
}
