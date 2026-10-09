/** Pfad-Helfer der Altium-Seite. */

/** Bauteiltabelle mit ausgewähltem Bauteil (`/bauteile/:table?pn=…`) */
export function partPath(item: { table: string | null; part_number: string | null }): string {
  return `/bauteile/${encodeURIComponent(item.table ?? '')}?pn=${encodeURIComponent(item.part_number ?? '')}`
}
