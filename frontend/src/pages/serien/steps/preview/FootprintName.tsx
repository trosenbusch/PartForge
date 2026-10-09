/**
 * Footprint-Name mit gedämpfter Eindeutigkeitskennung: „CAPC1608X90N“ + „_4328“. Die Kennung trägt ein Footprint, der
 * nicht der reine IPC-/Hausname sein kann (`FootprintRef.plain_name`); warum, steht in `name_reason` (Vorschau).
 */
import type { SeriesFootprintRef } from '@/api/series'

export function FootprintName({
  footprint,
  className,
}: {
  footprint: Pick<SeriesFootprintRef, 'name' | 'plain_name'>
  className?: string
}) {
  const plain = footprint.plain_name
  if (!plain || plain === footprint.name || !footprint.name.startsWith(plain)) return <span className={className}>{footprint.name}</span>
  return (
    <span className={className}>
      {plain}
      <span className="text-fg-subtle">{footprint.name.slice(plain.length)}</span>
    </span>
  )
}
