import { useEffect, useRef, useState } from 'react'

/** Wert erst nach `delay` ms Ruhe übernehmen. Gleiche Inhalte (JSON) lösen keine neue Fassung aus. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value)
  const last = useRef(JSON.stringify(value))
  useEffect(() => {
    const json = JSON.stringify(value)
    if (json === last.current) return
    const t = setTimeout(() => {
      last.current = json
      setDebounced(value)
    }, delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

/** Sekundentakt, solange `active` (z. B. Laufzeit einer Analyse) – sonst kein Timer. */
export function useNow(active: boolean, interval = 1000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), interval)
    return () => clearInterval(t)
  }, [active, interval])
  return now
}
