/**
 * Dateien speichern – ehrlich gemeldet: „gespeichert“ nur, wenn die Datei wirklich geschrieben wurde.
 *
 *   const result = await saveFile({ suggestedName: 'Widerstände.csv', content: csv, type: FILE_TYPES.csv })
 *   notifySaveResult(result, { what: 'CSV-Datei' })
 *
 *   // Inhalt erst laden, wenn der Speicherort feststeht (Abbruch = kein unnötiger Abruf):
 *   await saveFile({ suggestedName: `${name}.step`, type: FILE_TYPES.step,
 *     load: () => api.get<Blob>(`/api/footprints/${name}/step`, { responseType: 'blob' }) })
 *
 *   await saveBlob(blob, 'Export.xlsx', { type: FILE_TYPES.xlsx })          // Kurzform
 *   await saveFileWithFeedback({ suggestedName, content, type, what: 'Prüfbericht' })   // inkl. Toasts
 *
 *   // Große Dateien, die das Backend selbst schreiben kann (Export-Job): erst der Dialog, dann schreibt der Job direkt
 *   // in die gewählte Datei – kein Base64-Umweg, ein Abbruch im Dialog kostet nichts
 *   await saveFileWithFeedback({ suggestedName: 'Widerstände.xlsx', type: FILE_TYPES.xlsx, what: 'Excel-Datei',
 *     busy: 'Excel-Datei wird erstellt …',
 *     saveTo: async (path) => { const { job } = await startExportJob({ ...body, target_path: path }); await waitFor(job) },
 *     load: () => api.get<Blob>(url, { responseType: 'blob' }) })                  // Weg ohne `pick_save_path`
 *
 * Reihenfolge:
 *   0. `saveTo` und Desktop-Brücke mit `pick_save_path`: nativer Dialog zuerst, dann `saveTo(pfad)`.
 *   1. Desktop-Brücke `window.pywebview.api.save_file(name, content, filters)` → nativer Windows-Dialog; Text geht
 *      als UTF-8, Binärdaten als `base64:<daten>` (Bytes bleiben exakt erhalten, z. B. BOM einer CSV, XLSX).
 *   2. Desktop-Fenster ohne Brücke: Speichern-Dialog der File-System-Access-API (`showSaveFilePicker`, WebView2).
 *   3. Browser: Download über einen versteckten Link (Status „gestartet“ – den Rest erledigt der Browser).
 *
 * pywebview verwirft Downloads über Links, solange `ALLOW_DOWNLOADS` nicht gesetzt ist – deshalb im Desktop-Fenster
 * nie stillschweigend auf den Link ausweichen (`notifySaveResult` sagt es dann ehrlich).
 * Im Klick-Handler aufrufen: Der Browser-Dialog braucht eine frische Nutzeraktion.
 */
import { toast } from 'sonner'
import { baseName } from './format'
import { canOpenPath, canRevealPath, isDesktopWindow, nativeApi, revealPath } from './native'

export interface SaveFileType {
  /** Beschreibung im Dialog, z. B. „STEP-Modell“ */
  description: string
  /** MIME-Typ (Browser-Dialog, Blob) */
  mime: string
  /** Endungen mit Punkt, z. B. `['.step', '.stp']` (die erste wird bei Bedarf an den Namen gehängt) */
  extensions: string[]
}

/** Gängige Dateitypen für den Speichern-Dialog */
export const FILE_TYPES = {
  csv: { description: 'CSV-Datei', mime: 'text/csv', extensions: ['.csv'] },
  xlsx: {
    description: 'Excel-Arbeitsmappe',
    mime: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    extensions: ['.xlsx'],
  },
  step: { description: 'STEP-Modell', mime: 'model/step', extensions: ['.step', '.stp'] },
  json: { description: 'JSON-Datei', mime: 'application/json', extensions: ['.json'] },
  svg: { description: 'SVG-Grafik', mime: 'image/svg+xml', extensions: ['.svg'] },
  png: { description: 'PNG-Bild', mime: 'image/png', extensions: ['.png'] },
  pdf: { description: 'PDF-Dokument', mime: 'application/pdf', extensions: ['.pdf'] },
  txt: { description: 'Textdatei', mime: 'text/plain', extensions: ['.txt'] },
  zip: { description: 'ZIP-Archiv', mime: 'application/zip', extensions: ['.zip'] },
} satisfies Record<string, SaveFileType>

/** Text (UTF-8) oder Binärdaten */
export type SaveContent = string | Blob | ArrayBuffer | ArrayBufferView

export interface SaveFileOptions {
  /** Vorgeschlagener Dateiname (ohne Endung wird die des ersten Typs angehängt; unzulässige Zeichen werden ersetzt) */
  suggestedName: string
  /** Inhalt – alternativ `load` */
  content?: SaveContent
  /** Inhalt erst laden, wenn er gebraucht wird (Browser-Dialog: nach der Wahl des Speicherorts) */
  load?: () => Promise<SaveContent> | SaveContent
  /**
   * Die Datei schreibt jemand anderes (z. B. der Export-Job des Backends direkt in den Zielpfad): Im Desktop-Fenster
   * mit `pick_save_path` öffnet sich zuerst der Speichern-Dialog, danach `saveTo(pfad)`; wirft es, gilt das Speichern
   * als fehlgeschlagen. Ohne diese Brücke (Browser, ältere Desktop-Brücke) gilt der normale Weg über `content`/`load`.
   */
  saveTo?: (path: string) => Promise<unknown> | unknown
  /** Dateityp(en) für den Dialog (der erste ist vorgewählt) */
  type?: SaveFileType | readonly SaveFileType[]
  /**
   * Speichern-Dialog des Browsers (File-System-Access-API) verwenden: `auto` = nur im Desktop-Fenster ohne Brücke
   * (Standard), `always` = auch im normalen Browser („Speichern unter …“), `never` = immer Download-Link
   */
  picker?: 'auto' | 'always' | 'never'
}

export type SaveFileResult =
  /** Datei geschrieben (`path` nur über die Desktop-Brücke bekannt) */
  | { status: 'saved'; name: string; path: string | null; via: 'desktop' | 'picker' }
  /** Download an den Browser übergeben (der Browser zeigt den Fortschritt) */
  | { status: 'started'; name: string; desktop: boolean }
  /** Nutzer hat den Speichern-Dialog abgebrochen */
  | { status: 'cancelled' }

/** Für Windows unzulässige Zeichen ersetzen (auch Steuerzeichen, Punkte/Leerzeichen am Ende) */
export function safeFileName(name: string, fallback = 'PartForge-Export'): string {
  // oxlint-disable-next-line no-control-regex -- Steuerzeichen sind in Windows-Dateinamen verboten
  const cleaned = name.replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_').replace(/[. ]+$/, '').trim()
  return cleaned || fallback
}

function typeList(type: SaveFileOptions['type']): readonly SaveFileType[] {
  if (!type) return []
  return Array.isArray(type) ? (type as readonly SaveFileType[]) : [type as SaveFileType]
}

/** Endung des ersten Typs anhängen, wenn der Name keine der erlaubten Endungen trägt */
function withExtension(name: string, types: readonly SaveFileType[]): string {
  const first = types[0]
  if (!first?.extensions.length) return name
  const lower = name.toLowerCase()
  if (types.some((t) => t.extensions.some((e) => lower.endsWith(e.toLowerCase())))) return name
  return `${name}${first.extensions[0]}`
}

/** pywebview-Filter: „STEP-Modell (*.step;*.stp)“ */
function bridgeFilters(types: readonly SaveFileType[]): string[] | null {
  return types.length ? types.map((t) => `${t.description} (${t.extensions.map((e) => `*${e}`).join(';')})`) : null
}

function toBlob(content: SaveContent, mime: string | undefined): Blob {
  if (content instanceof Blob) return content
  if (typeof content === 'string') return new Blob([content], { type: mime ? `${mime};charset=utf-8` : 'text/plain;charset=utf-8' })
  const bytes = ArrayBuffer.isView(content)
    ? new Uint8Array(content.buffer, content.byteOffset, content.byteLength)
    : new Uint8Array(content)
  return new Blob([bytes as Uint8Array<ArrayBuffer>], { type: mime ?? 'application/octet-stream' })
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const url = String(reader.result ?? '')
      resolve(url.slice(url.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error('Datei konnte nicht gelesen werden'))
    reader.readAsDataURL(blob)
  })
}

/** Inhalt für `save_file`: Text unverändert, alles Binäre als „base64:…“ (auch Text, der selbst so beginnt) */
async function bridgeContent(content: SaveContent): Promise<string> {
  if (typeof content === 'string' && !content.startsWith('base64:')) return content
  return `base64:${await blobToBase64(toBlob(content, undefined))}`
}

async function resolveContent(opts: SaveFileOptions): Promise<SaveContent> {
  if (opts.content !== undefined) return opts.content
  if (opts.load) return opts.load()
  throw new Error('saveFile: weder „content“ noch „load“ angegeben (ohne `pick_save_path` reicht `saveTo` allein nicht)')
}

interface FilePickerWindow {
  showSaveFilePicker?: (options: {
    suggestedName?: string
    types?: { description: string; accept: Record<string, string[]> }[]
  }) => Promise<{ name: string; createWritable: () => Promise<{ write: (data: Blob) => Promise<void>; close: () => Promise<void> }> }>
}

const isAbort = (e: unknown) => e instanceof DOMException && e.name === 'AbortError'

/** Blob über einen versteckten Link anbieten (Objekt-URL wird nach einer Minute freigegeben). */
function anchorDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.rel = 'noopener'
  a.style.display = 'none'
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
}

function describeError(err: unknown): string {
  if (err instanceof Error && err.message) return err.message
  if (typeof err === 'string' && err) return err
  return 'Unbekannter Fehler'
}

/**
 * Datei speichern (siehe Modulbeschreibung). Wirft bei echten Fehlern (Schreibfehler, Laden fehlgeschlagen) einen
 * `Error` mit deutschem Text; ein abgebrochener Dialog ist kein Fehler (`status: 'cancelled'`).
 */
export async function saveFile(opts: SaveFileOptions): Promise<SaveFileResult> {
  const types = typeList(opts.type)
  const name = withExtension(safeFileName(opts.suggestedName), types)
  const desktop = isDesktopWindow()

  // 0. Erst der Speichern-Dialog, dann schreibt `saveTo` (z. B. das Backend) direkt in die gewählte Datei
  const pickPath = nativeApi()?.pick_save_path
  if (opts.saveTo && typeof pickPath === 'function') {
    let path: string | null
    try {
      path = (await pickPath(name, bridgeFilters(types))) ?? null
    } catch (err) {
      throw new Error(`Der Speichern-Dialog ließ sich nicht öffnen: ${describeError(err)}`, { cause: err })
    }
    if (!path) return { status: 'cancelled' }
    try {
      await opts.saveTo(path)
    } catch (err) {
      throw new Error(`Die Datei konnte nicht gespeichert werden: ${describeError(err)}`, { cause: err })
    }
    return { status: 'saved', name: baseName(path) || name, path, via: 'desktop' }
  }

  // 1. Desktop-Brücke (nativer Dialog, schreibt selbst)
  const bridge = nativeApi()?.save_file
  if (typeof bridge === 'function') {
    const payload = await bridgeContent(await resolveContent(opts))
    let path: string | null
    try {
      path = (await bridge(name, payload, bridgeFilters(types))) ?? null
    } catch (err) {
      throw new Error(`Die Datei konnte nicht gespeichert werden: ${describeError(err)}`, { cause: err })
    }
    return path ? { status: 'saved', name: path.split(/[\\/]/).pop() ?? name, path, via: 'desktop' } : { status: 'cancelled' }
  }

  // 2. Speichern-Dialog der File-System-Access-API
  const mode = opts.picker ?? 'auto'
  const picker = (window as Window & FilePickerWindow).showSaveFilePicker
  if (typeof picker === 'function' && (mode === 'always' || (mode === 'auto' && desktop))) {
    let handle: Awaited<ReturnType<NonNullable<FilePickerWindow['showSaveFilePicker']>>> | null = null
    try {
      handle = await picker.call(window, {
        suggestedName: name,
        types: types.length ? types.map((t) => ({ description: t.description, accept: { [t.mime]: t.extensions } })) : undefined,
      })
    } catch (e) {
      if (isAbort(e)) return { status: 'cancelled' }
      handle = null // nicht erlaubt (z. B. ohne Nutzeraktion) → Link versuchen
    }
    if (handle) {
      const blob = toBlob(await resolveContent(opts), types[0]?.mime)
      try {
        const writable = await handle.createWritable()
        await writable.write(blob)
        await writable.close()
      } catch (err) {
        throw new Error(`Die Datei konnte nicht gespeichert werden: ${describeError(err)}`, { cause: err })
      }
      return { status: 'saved', name: handle.name, path: null, via: 'picker' }
    }
  }

  // 3. Download-Link (Browser; im Desktop-Fenster nur, wenn pywebview Downloads erlaubt)
  anchorDownload(toBlob(await resolveContent(opts), types[0]?.mime), name)
  return { status: 'started', name, desktop }
}

/** Kurzform für vorhandene Daten: `saveBlob(blob, 'Export.xlsx', { type: FILE_TYPES.xlsx })` */
export function saveBlob(
  blob: Blob | SaveContent,
  suggestedName: string,
  opts: Omit<SaveFileOptions, 'suggestedName' | 'content' | 'load'> = {},
): Promise<SaveFileResult> {
  return saveFile({ ...opts, suggestedName, content: blob })
}

export interface NotifySaveOptions {
  /** Was gespeichert wurde, z. B. „STEP-Datei“ (Standard: „Datei“) */
  what?: string
  /** Toast-ID (wiederholtes Speichern ersetzt den Toast statt zu stapeln) */
  id?: string
}

/**
 * Ergebnis melden: Erfolg nur, wenn die Datei geschrieben wurde (mit „Im Explorer zeigen“, wenn der Pfad bekannt ist);
 * ein an den Browser übergebener Download ist „gestartet“; im Desktop-Fenster ohne Dialog ehrlich mit Hinweis.
 * Abbruch bleibt still.
 */
export function notifySaveResult(result: SaveFileResult, { what = 'Datei', id = 'pf-save-file' }: NotifySaveOptions = {}): void {
  if (result.status === 'cancelled') return
  if (result.status === 'saved') {
    const path = result.path
    toast.success(`${what} gespeichert`, {
      id,
      description: path ?? result.name,
      // Explorer mit markierter Datei (ältere Desktop-Brücke: Ordner öffnen)
      action:
        path && (canRevealPath() || canOpenPath())
          ? { label: 'Im Explorer zeigen', onClick: () => void revealPath(path, { what }) }
          : undefined,
    })
  } else if (result.desktop) {
    toast.info(`${what} angefordert`, {
      id,
      description: `${result.name} – erscheint kein Speichern-Dialog, sind Downloads in diesem Fenster noch nicht freigeschaltet.`,
    })
  } else {
    toast('Download gestartet', { id, description: result.name })
  }
}

export interface SaveFeedbackOptions extends NotifySaveOptions {
  /**
   * Text eines Lade-Toasts, solange der Inhalt entsteht (`load` bzw. `saveTo` läuft – nach der Wahl des Speicherorts),
   * z. B. „Excel-Datei wird erstellt …“; das Ergebnis ersetzt ihn (gleiche Toast-ID), ein Abbruch entfernt ihn.
   */
  busy?: string
}

/** `saveFile` + `notifySaveResult` + Fehler-Toast in einem – liefert das Ergebnis oder `null` bei einem Fehler. */
export async function saveFileWithFeedback(opts: SaveFileOptions & SaveFeedbackOptions): Promise<SaveFileResult | null> {
  const { what = 'Datei', id = 'pf-save-file', busy, ...save } = opts
  let shown = false
  const showBusy = () => {
    if (!busy || shown) return
    shown = true
    toast.loading(busy, { id })
  }
  if (busy) {
    const { load, saveTo } = save
    if (load) {
      save.load = () => {
        showBusy()
        return load()
      }
    }
    if (saveTo) {
      save.saveTo = (path) => {
        showBusy()
        return saveTo(path)
      }
    }
  }
  try {
    const result = await saveFile(save)
    if (result.status === 'cancelled' && shown) toast.dismiss(id)
    notifySaveResult(result, { what, id })
    return result
  } catch (err) {
    toast.error(`${what} konnte nicht gespeichert werden`, { id, description: describeError(err) })
    return null
  }
}
