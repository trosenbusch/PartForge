/**
 * Fokus setzen, sobald das Ziel da ist und kein modaler Dialog mehr offen ist (Radix hält den Fokus sonst im Dialog
 * fest, bis er ausgeblendet ist). Gibt eine Abbruchfunktion zurück (für `useEffect`).
 */
export function focusWhenReady(
  target: () => HTMLElement | null | undefined,
  opts: { timeout?: number; scroll?: ScrollIntoViewOptions | false } = {},
): () => void {
  const { timeout = 2500, scroll = false } = opts
  const started = performance.now()
  let timer = 0
  let cancelled = false
  const attempt = () => {
    if (cancelled) return
    const el = target()
    const modalOpen = Boolean(document.querySelector('[aria-modal="true"]'))
    if (el && el.isConnected && !modalOpen) {
      if (scroll) el.scrollIntoView(scroll)
      el.focus({ preventScroll: true })
      return
    }
    if (performance.now() - started < timeout) timer = window.setTimeout(attempt, 60)
  }
  // nach dem Rendern des neuen Inhalts
  timer = window.setTimeout(attempt, 0)
  return () => {
    cancelled = true
    window.clearTimeout(timer)
  }
}
