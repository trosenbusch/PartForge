/**
 * „In Altium bearbeiten“: Symbol bzw. Footprint in Altium Designer öffnen; PartForge übernimmt jedes Speichern dort
 * automatisch (`partforge.altium.editing`, ARCHITEKTUR §8.9).
 *
 * Start und Übernahme laufen als Jobs: `altium.edit` (Stand festhalten, Bibliothek in Altium öffnen, Bauteil zeigen)
 * und `libraries.altium-edit` (gespeicherte Änderungen übernehmen – startet das Backend von selbst, kurz nachdem die
 * Datei in Altium gespeichert wurde; sein Abschluss-Toast nennt die übernommenen Bauteile und lädt alle Daten neu).
 * Die Liste der beobachteten Bibliotheken (`sessions`) ist billig (kein Altium, nur Dateizeiten) und wird gepollt,
 * solange etwas beobachtet wird.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { toast } from 'sonner'
import { t as tr } from '@/lib/i18n'
import { api, errorMessage } from './client'
import { trackJob } from './jobs'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

export type AltiumEditKind = NonNullable<RequestBodyOf<'/api/altium/edit', 'post'>>['kind']
export type AltiumEditSession = Filled<ResponseOf<'/api/altium/edit/sessions', 'get'>>[number]
export type AltiumEditState = AltiumEditSession['state']
export type AltiumEditEnd = Filled<ResponseOf<'/api/altium/edit/sessions/{session_id}/end', 'post'>>

/** Ergebnis des Start-Jobs (`altium.edit`) */
export interface AltiumEditStartResult {
  message: string
  kind: AltiumEditKind
  name: string
  library: string
  library_abs: string
  session: string
  /** Altium zeigt das Bauteil (false: nur die Bibliothek ist offen) */
  found: boolean
  was_open: boolean
  /** die Bibliothek hatte in Altium schon ungespeicherte Änderungen */
  modified: boolean
  /** eine laufende Bearbeitung derselben Datei wurde fortgesetzt */
  continued: boolean
}

interface JobStart {
  job: Job
}

export const altiumEditKeys = {
  /** unter „altium“: lädt nach jedem Altium-Job neu (`JOB_SCOPES` in `@/api/jobs`) */
  sessions: ['altium', 'edit-sessions'] as const,
}

export const altiumEditApi = {
  start: (kind: AltiumEditKind, name: string) => api.post<JobStart>('/api/altium/edit', { kind, name }),
  sessions: (signal?: AbortSignal) => api.get<AltiumEditSession[]>('/api/altium/edit/sessions', { signal }),
  check: (id: string) => api.post<JobStart>(`/api/altium/edit/sessions/${encodeURIComponent(id)}/check`),
  end: (id: string) => api.post<AltiumEditEnd>(`/api/altium/edit/sessions/${encodeURIComponent(id)}/end`),
}

/** Beobachtete Bibliotheken der offenen Bibliothek – pollt alle 3 s, solange es welche gibt (sonst alle 30 s). */
export function useAltiumEditSessions(enabled = true) {
  return useQuery({
    queryKey: altiumEditKeys.sessions,
    queryFn: ({ signal }) => altiumEditApi.sessions(signal),
    enabled,
    staleTime: 1_500,
    refetchInterval: (query) => ((query.state.data?.length ?? 0) > 0 ? 3_000 : 30_000),
    retry: false,
  })
}

const fold = (s: string) => s.toLocaleLowerCase('en')

/** Die Bearbeitung, in der dieses Bauteil in Altium geöffnet ist (oder `null`). */
export function useAltiumEditSession(kind: AltiumEditKind, name: string | null | undefined, enabled = true) {
  const sessions = useAltiumEditSessions(enabled && Boolean(name))
  const wanted = name ? fold(name) : null
  const session = wanted
    ? (sessions.data ?? []).find((s) => s.kind === kind && s.targets.some((t) => fold(t) === wanted)) ?? null
    : null
  return { session, isLoading: sessions.isLoading }
}

/** Namen (klein geschrieben) der Bauteile dieser Art, die gerade in Altium bearbeitet werden – für Abzeichen in Listen. */
export function useAltiumEditTargets(kind: AltiumEditKind): ReadonlySet<string> {
  const sessions = useAltiumEditSessions()
  return useMemo(
    () => new Set((sessions.data ?? []).filter((s) => s.kind === kind).flatMap((s) => s.targets.map(fold))),
    [sessions.data, kind],
  )
}

/** In Altium öffnen (bzw. das Bauteil dort wieder zeigen). Der Job meldet sein Ende als Toast. */
export function useStartAltiumEdit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, name }: { kind: AltiumEditKind; name: string }) => altiumEditApi.start(kind, name),
    onSuccess: ({ job }) => {
      trackJob(job as Job<AltiumEditStartResult>, {
        warnWhen: (j) => (j.result && !j.result.found ? j.result.message : null),
      })
      void qc.invalidateQueries({ queryKey: altiumEditKeys.sessions })
    },
    onError: (e) => {
      toast.error(tr('In Altium bearbeiten nicht möglich'), { id: 'altium-edit', description: errorMessage(e) })
    },
  })
}

/** Gespeicherte Änderungen jetzt übernehmen (sonst tut es PartForge kurz nach dem Speichern selbst). */
export function useCheckAltiumEdit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => altiumEditApi.check(id),
    onSuccess: ({ job }) => {
      trackJob(job)
      void qc.invalidateQueries({ queryKey: altiumEditKeys.sessions })
    },
    onError: (e) => {
      toast.error(tr('Übernehmen nicht möglich'), { id: 'altium-edit', description: errorMessage(e) })
      void qc.invalidateQueries({ queryKey: altiumEditKeys.sessions })
    },
  })
}

/** Bearbeitung beenden – eine noch nicht übernommene Speicherung übernimmt der Job vorher. */
export function useEndAltiumEdit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => altiumEditApi.end(id),
    onSuccess: (out) => {
      if (out.job) trackJob(out.job as unknown as Job)
      else toast.success(tr('Bearbeitung beendet'), { id: 'altium-edit', description: out.message })
      void qc.invalidateQueries({ queryKey: altiumEditKeys.sessions })
    },
    onError: (e) => {
      toast.error(tr('Beenden nicht möglich'), { id: 'altium-edit', description: errorMessage(e) })
      void qc.invalidateQueries({ queryKey: altiumEditKeys.sessions })
    },
  })
}

/** Vorherige Herkunft einer in Altium bearbeiteten Fassung (`spec.generator.altium_edit.previous_source`). */
export function altiumPreviousSource(generator: unknown): string | null {
  if (!generator || typeof generator !== 'object') return null
  const mark = (generator as { altium_edit?: { previous_source?: unknown } }).altium_edit
  return typeof mark?.previous_source === 'string' ? mark.previous_source : null
}
