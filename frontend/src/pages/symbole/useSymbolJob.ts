/**
 * Hintergrundjobs des Moduls (Speichern/Löschen, wenn das Backend langsam schreibt): im Job-Dock zeigen und nach
 * dem Abschluss die Symbolbibliothek neu laden. Das Job-Dock lädt Daten nur bei einem beobachteten Statuswechsel
 * neu – ein Job, der vor der ersten Abfrage schon fertig ist, würde sonst übersehen.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { trackJob, useJob } from '@/api/jobs'
import { symbolKeys } from '@/api/symbols'
import type { Job } from '@/api/system'

export function useSymbolJob(onDone?: (job: Job) => void): (job: Job, opts?: { openDock?: boolean }) => void {
  const qc = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  useJob(jobId, {
    onDone: (job) => {
      void qc.invalidateQueries({ queryKey: symbolKeys.libraryAll })
      void qc.invalidateQueries({ queryKey: symbolKeys.detailAll })
      onDone?.(job)
    },
  })
  return useCallback((job: Job, opts?: { openDock?: boolean }) => {
    trackJob(job, { openDock: opts?.openDock ?? false })
    setJobId(job.id)
  }, [])
}
