import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { datasheetFile } from '@/api/datasheets'
import { canOpenPath, openPath } from '@/lib/native'

/**
 * PDF eines Datenblatts öffnen: im Desktop-Programm über die Desktop-Brücke im PDF-Betrachter des Systems (wie in
 * der Bauteiltabelle), sonst im Browser.
 *
 * Im Browser wird die Datei mit dem Token-**Header** geladen und als Objekt-URL geöffnet – so steht das
 * Sitzungstoken nie in der Adresszeile oder im Verlauf eines neuen Tabs (Sicherheitsfinding: Token nie im Log/URL).
 */
export async function openPdf(ds: { id: string; path?: string | null }): Promise<void> {
  if (ds.path && canOpenPath() && (await openPath(ds.path))) return
  // Den Tab synchron öffnen (Popup-Blocker), dann mit dem geladenen Blob füllen. Ohne „noopener“: damit gibt
  // window.open null zurück, der leere Tab bliebe stehen und die PDF öffnete sich (wenn überhaupt) in einem
  // zweiten. Die Verbindung zum neuen Tab wird stattdessen über `opener = null` getrennt.
  const win = window.open('', '_blank')
  if (win) win.opener = null
  try {
    const { blob } = await datasheetFile(ds.id)
    const url = URL.createObjectURL(pdfBlob(blob))
    if (win && !win.closed) win.location.href = url
    else window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (err) {
    win?.close()
    toast.error(t("Das Datenblatt konnte nicht geöffnet werden."), { description: errorMessage(err) })
  }
}

/** Der Browser zeigt eine Objekt-URL nur als PDF an, wenn der Blob den Typ `application/pdf` trägt. */
function pdfBlob(blob: Blob): Blob {
  return blob.type === 'application/pdf' ? blob : new Blob([blob], { type: 'application/pdf' })
}
