import { t, useI18n } from '@/lib/i18n'
import { Combine, ExternalLink } from 'lucide-react'
import { useState } from 'react'
import type { PackageOrigin } from '@/api/datasheets'
import { Button, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, SegmentedControl } from '@/components/ui'
import { openPdf } from '../../lib/openPdf'
import { PageImage } from '../../shared/PageImage'

/**
 * Zeichnung eines übernommenen Gehäuses ansehen: die Seiten stehen im **anderen** PDF (`PackageOrigin.datasheet_id`),
 * nicht in der PDF-Spalte dieses Datenblatts – deshalb eine eigene, schlichte Seitenansicht.
 */
export function OriginPagesDialog({
  open,
  onOpenChange,
  origin,
  pages,
  label,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  origin: PackageOrigin
  /** Seiten der Zeichnung (Umriss, Lötflächen) im anderen PDF */
  pages: number[]
  label: string
}) {
  useI18n()
  const [page, setPage] = useState<number | null>(null)
  const shown = page !== null && pages.includes(page) ? page : (pages[0] ?? 1)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">
        <DialogHeader
          icon={<Combine />}
          tone="accent"
          title={t("Zeichnung von {0}", { "0": String(label) })}
          description={t("Übernommen aus „{0}“{1}{2}.", { "0": String(origin.file), "1": String(origin.label ? ` (${origin.label})` : ''), "2": String(origin.title ? ` – ${origin.title}` : '') })}
        />
        <DialogBody className="flex flex-col gap-3 pt-1">
          {pages.length > 1 && (
            <SegmentedControl
              size="sm"
              aria-label={t("Seite der Zeichnung")}
              value={String(shown)}
              onValueChange={(v) => setPage(Number(v))}
              options={pages.map((p) => ({ value: String(p), label: t("S. {0}", { "0": String(p) }) }))}
              className="self-start"
            />
          )}
          <PageImage
            datasheetId={origin.datasheet_id}
            page={shown}
            dpi={150}
            loading="eager"
            alt={t("Seite {0} von „{1}“", { "0": String(shown), "1": String(origin.file) })}
            className="w-full rounded-md border border-line shadow-card"
          />
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" leftIcon={<ExternalLink />} onClick={() => void openPdf({ id: origin.datasheet_id })}>
            {t("PDF öffnen")}</Button>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            {t("Schließen")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
