import { useEffect, useState } from 'react'

const FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'

/**
 * Scrollt `el`, ohne dass darin etwas per Tastatur erreichbar ist? Dann braucht der Bereich einen eigenen Tab-Stopp
 * (WCAG 2.1.1, axe „scrollable-region-focusable“) – wie `ScrollArea focusable="auto"` des UI-Kits, für eigene
 * Scrollbereiche, die ihre Größe selbst messen (Seitenraster, Zeitleiste der Analyse).
 *
 *   const stop = useScrollTabStop(el)
 *   <div tabIndex={stop ? 0 : undefined} role={stop ? 'region' : undefined} aria-label={stop ? 'Schritte' : undefined} …>
 */
export function useScrollTabStop(el: HTMLElement | null): boolean {
  const [stop, setStop] = useState(false)
  useEffect(() => {
    if (!el) return
    const update = () => {
      const scrolls = el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1
      setStop(scrolls && !el.querySelector(FOCUSABLE))
    }
    update()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(el)
    if (el.firstElementChild) ro?.observe(el.firstElementChild)
    const mo = typeof MutationObserver !== 'undefined' ? new MutationObserver(update) : null
    mo?.observe(el, { childList: true, subtree: true })
    return () => {
      ro?.disconnect()
      mo?.disconnect()
    }
  }, [el])
  return stop
}
