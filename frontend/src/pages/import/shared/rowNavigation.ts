import type { KeyboardEvent } from 'react'

/**
 * Tabellen mit **einem Tab-Stopp je Zeile** (`<tr data-nav-row>`): Tab springt von Zeile zu Zeile (der Stopp ist das
 * erste Bedienelement, meist das Auswahlkästchen in `[data-nav-host]`), die übrigen Bedienelemente der Zeile tragen
 * `data-nav-item` und `tabIndex={-1}` und sind mit den Pfeiltasten erreichbar:
 *
 *   ←/→  vorheriges/nächstes Bedienelement der Zeile · Pos1/Ende erstes/letztes
 *   ↑/↓  dieselbe Spalte der vorigen/nächsten Zeile (auf Menü-Auslösern öffnet ↓ wie gewohnt das Menü)
 *
 *   <table onKeyDown={rowNavigationKeyDown}> … <tr data-nav-row> <td data-nav-host><Checkbox …/></td> …
 *     <SourceChip navItem …/> …
 *
 * React-Handler (nicht nativ): Kinder wie Radix-Menüs reagieren zuerst; was sie selbst verarbeiten (`defaultPrevented`),
 * bleibt unberührt.
 */
const ITEM_SELECTOR = '[data-nav-item], [data-nav-host] button, [data-nav-host] [role="checkbox"]'

function itemsOf(row: Element): HTMLElement[] {
  return [...new Set(row.querySelectorAll<HTMLElement>(ITEM_SELECTOR))].filter(
    (el) => !el.hasAttribute('disabled') && el.getAttribute('aria-disabled') !== 'true' && el.getClientRects().length > 0,
  )
}

export function rowNavigationKeyDown(e: KeyboardEvent<HTMLElement>): void {
  if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
  const target = e.target as HTMLElement
  const row = target.closest('tr[data-nav-row]')
  if (!row || !e.currentTarget.contains(row)) return
  const items = itemsOf(row)
  const index = items.findIndex((el) => el === target || el.contains(target))
  if (index < 0) return
  let next: HTMLElement | undefined
  switch (e.key) {
    case 'ArrowRight':
      next = items[index + 1]
      break
    case 'ArrowLeft':
      next = items[index - 1]
      break
    case 'Home':
      next = items[0]
      break
    case 'End':
      next = items[items.length - 1]
      break
    case 'ArrowDown':
    case 'ArrowUp': {
      if (target.getAttribute('aria-haspopup') === 'menu') return
      const rows = [...e.currentTarget.querySelectorAll<HTMLElement>('tr[data-nav-row]')].filter((r) => itemsOf(r).length > 0)
      const r = rows.indexOf(row as HTMLElement)
      const other = rows[r + (e.key === 'ArrowDown' ? 1 : -1)]
      if (other) {
        const otherItems = itemsOf(other)
        next = otherItems[Math.min(index, otherItems.length - 1)]
      }
      break
    }
    default:
      return
  }
  if (!next) return
  e.preventDefault()
  next.focus()
}
