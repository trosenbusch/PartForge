/**
 * Entwurfszustand der Einstellungsbereiche: Eingaben bleiben lokal, bis gespeichert wird.
 *
 * `useDraft(saved)` merkt sich, von welchem Serverstand der Entwurf stammt. Ändert sich der Serverstand
 * (gespeichert, anderer Bereich, anderes Fenster) und der Entwurf ist unverändert, folgt er automatisch –
 * angefangene Eingaben werden nie überschrieben.
 *
 * Entwürfe der Bibliothekseinstellungen gehören zu genau einer Bibliothek: Die Seite baut diese Bereiche beim
 * Bibliothekswechsel neu auf (Schlüssel = Bibliotheksordner), und `save` schreibt nur, solange dieselbe
 * Bibliothek geöffnet ist.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { useWorkspace, type WorkspaceSettings } from '@/api/system'
import { useUpdateWorkspaceSettings } from '@/api/settings'

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

export interface Draft<T> {
  draft: T
  setDraft: (next: T | ((current: T) => T)) => void
  dirty: boolean
  /** Entwurf verwerfen (zurück zum Serverstand) */
  reset: () => void
  /** Neuer Serverstand nach dem Speichern */
  commit: (saved: T) => void
}

export function useDraft<T>(saved: T): Draft<T> {
  const [state, setState] = useState({ base: saved, draft: saved })
  // Serverstand geändert → übernehmen, solange nichts bearbeitet wurde (Zustandsanpassung beim Rendern)
  if (!same(state.base, saved)) {
    const untouched = same(state.draft, state.base)
    setState({ base: saved, draft: untouched ? saved : state.draft })
  }
  return {
    draft: state.draft,
    setDraft: (next) =>
      setState((s) => ({ ...s, draft: typeof next === 'function' ? (next as (c: T) => T)(s.draft) : next })),
    dirty: !same(state.draft, saved),
    reset: () => setState({ base: saved, draft: saved }),
    commit: (value) => setState({ base: value, draft: value }),
  }
}

export interface WorkspaceDraftOptions {
  /** Name des Bereichs – für die Bestätigung „… gespeichert“ */
  label: string
  /** Zusatz in der Bestätigung (z. B. wofür die Änderung gilt) */
  savedDescription?: string
}

/**
 * Entwurf eines Teils der Bibliothekseinstellungen. `select` liest den Teil, `apply` schreibt ihn in einen
 * (frisch geladenen) Gesamtstand – so überschreibt ein Bereich nie die Änderungen eines anderen.
 */
export function useWorkspaceDraft<T>(
  select: (settings: WorkspaceSettings) => T,
  apply: (settings: WorkspaceSettings, value: T) => WorkspaceSettings,
  { label, savedDescription }: WorkspaceDraftOptions,
) {
  const workspace = useWorkspace()
  const settings = workspace.data?.settings
  const root = workspace.data?.root ?? null
  const saved = settings ? select(settings) : null
  const d = useDraft<T | null>(saved)
  const mutation = useUpdateWorkspaceSettings()

  const save = async (): Promise<boolean> => {
    const value = d.draft
    if (value === null || root === null || mutation.isPending) return false
    try {
      const info = await mutation.mutateAsync({ change: (current) => apply(current, value), root })
      d.commit(select(info.settings))
      toast.success(`${label} gespeichert`, { id: `settings-saved-${label}`, description: savedDescription })
      return true
    } catch {
      return false
    }
  }

  return {
    workspace,
    info: workspace.data ?? null,
    /** Bibliothek, zu der dieser Entwurf gehört */
    root,
    saved,
    draft: d.draft,
    setDraft: (fn: (current: T) => T) => d.setDraft((c) => (c === null ? c : fn(c))),
    dirty: d.dirty && d.draft !== null,
    reset: d.reset,
    save,
    saving: mutation.isPending,
  }
}

/** Einzelnen Wert eines Objekts setzen (typsicher) */
export function setKey<T extends object, K extends keyof T>(obj: T, key: K, value: T[K]): T {
  return { ...obj, [key]: value }
}
