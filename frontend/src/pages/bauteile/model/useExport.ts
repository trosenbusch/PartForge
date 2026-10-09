/**
 * Export der Bauteiltabelle (XLSX/CSV) über den gemeinsamen Speichern-Helfer `@/lib/download`: im Desktop-Fenster
 * der native Speichern-Dialog (Binärdaten exakt – BOM der CSV und XLSX bleiben erhalten), im Browser ein Download.
 * Solange die Datei entsteht, steht ein Lade-Toast da („Excel-Datei wird erstellt … 1.234 Bauteile“), den das Ergebnis
 * ersetzt (Abbruch im Dialog: verschwindet).
 *
 * Als Job in den Ordner „Exports“ der Bibliothek (Fortschritt im Job-Dock statt einer wartenden Seite): sehr große
 * Auswahl (die Download-Adresse würde zu lang) und **große Excel-Exporte** (über {@link LARGE_XLSX_ROWS} Zeilen – XLSX
 * braucht dort mehrere Sekunden). Den Abschluss meldet das Job-Dock mit der Schlussmeldung des Backends („Export fertig:
 * 1.700 Bauteile in Exports\…“) – auch wenn inzwischen eine andere Kategorie offen ist; solange der Hook lebt, ergänzt er
 * die Meldung um „Im Explorer zeigen“ (die Datei markiert).
 */
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { cleanErrorText, errorMessage } from '@/api/client'
import { trackJob, useJob } from '@/api/jobs'
import { partsApi, type ExportFileResult, type ExportOptions } from '@/api/parts'
import { FILE_TYPES, notifySaveResult, saveFile } from '@/lib/download'
import { formatNumbersInText, plural } from '@/lib/format'
import { revealPath } from '@/lib/native'

/** Längere Download-Adressen (viele Teilenummern) überschreiten die Kopfgrenze des Servers → Export als Job */
const MAX_URL_LENGTH = 12_000
/** Ab so vielen Zeilen läuft ein Excel-Export als Job (≈ 2–4 s Rechenzeit; CSV bleibt auch bei 20.000 Zeilen schnell) */
export const LARGE_XLSX_ROWS = 5_000

export function useExport(table: string | undefined, label: string) {
  const [jobId, setJobId] = useState<string | null>(null)
  useJob<ExportFileResult>(jobId, {
    onDone: (job) => {
      const r = job.result
      // gleiche ID wie die Meldung des Job-Docks → dieselbe Meldung bekommt „Im Explorer zeigen“
      if (r) {
        toast.success(job.title, {
          id: `job:${job.id}`,
          description: formatNumbersInText(job.message || `${plural(r.rows, 'Bauteil', 'Bauteile')} in ${r.rel_path}`),
          action: { label: 'Im Explorer zeigen', onClick: () => void revealPath(r.path, { what: 'Exportdatei' }) },
        })
      }
      setJobId(null)
    },
    // Fehler und Abbruch meldet das Job-Dock
    onFailed: () => setJobId(null),
    onCancelled: () => setJobId(null),
  })

  return useCallback(
    /** `rows` = erwartete Zeilenzahl (Auswahl bzw. Treffer) – entscheidet über den Job und steht im Lade-Toast */
    (opts: ExportOptions, rows?: number | null) => {
      if (!table) return
      const what = opts.format === 'xlsx' ? 'Excel-Datei' : 'CSV-Datei'
      const id = `export:${table}`
      const tooLong = partsApi.exportUrl(table, opts).length > MAX_URL_LENGTH
      const large = opts.format === 'xlsx' && (rows ?? 0) > LARGE_XLSX_ROWS
      if (tooLong || large) {
        toast.loading(`${what} wird vorbereitet …`, { id, description: rows ? plural(rows, 'Bauteil', 'Bauteile') : undefined })
        void partsApi
          .exportJob(table, opts)
          .then(({ job }) => {
            // erst der Hinweis, dann der Job – kleine Exporte sind fertig, bevor die nächste Zeile läuft
            toast.info(large ? 'Großer Excel-Export – läuft im Hintergrund' : 'Große Auswahl – Export in den Bibliotheksordner', {
              id,
              description: large
                ? `${plural(rows ?? 0, 'Bauteil', 'Bauteile')} · die Datei landet im Ordner „Exports“ der Bibliothek, Fortschritt im Job-Dock.`
                : 'Die Datei landet im Ordner „Exports“ der Bibliothek.',
            })
            // Erfolgsmeldung = Schlussmeldung des Jobs (Backend), kein eigener Text
            trackJob<ExportFileResult>(job, { openDock: false })
            setJobId(job.id)
          })
          .catch((err: unknown) => toast.error('Export nicht möglich', { id, description: cleanErrorText(errorMessage(err)) }))
        return
      }
      void saveFile({
        suggestedName: label,
        type: opts.format === 'xlsx' ? FILE_TYPES.xlsx : FILE_TYPES.csv,
        // Rückmeldung, sobald die Datei entsteht (im Browser-Dialog erst nach der Wahl des Speicherorts)
        load: () => {
          toast.loading(`${what} wird erstellt …`, { id, description: rows ? plural(rows, 'Bauteil', 'Bauteile') : undefined })
          return partsApi.exportFile(table, opts)
        },
      })
        .then((result) => {
          if (result.status === 'cancelled') toast.dismiss(id)
          else notifySaveResult(result, { what, id })
        })
        .catch((err: unknown) => toast.error(`${what} konnte nicht gespeichert werden`, { id, description: cleanErrorText(errorMessage(err)) }))
    },
    [table, label],
  )
}
