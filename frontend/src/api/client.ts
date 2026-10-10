import { t as tr, localizeMessage } from '@/lib/i18n'
export const TOKEN_HEADER = 'X-PartForge-Token'

function readToken(): string {
  if (typeof document !== 'undefined') {
    const meta = document.querySelector<HTMLMetaElement>('meta[name="partforge-token"]')
    const value = meta?.content?.trim()
    if (value) return value
  }
  return import.meta.env.DEV ? 'dev' : ''
}

let sessionToken = readToken()

export function getToken(): string {
  return sessionToken
}

/** Nur für Tests / Sonderfälle. */
export function setToken(token: string): void {
  sessionToken = token
}

// --------------------------------------------------------------------------- Fehler

export class ApiError extends Error {
  /** HTTP-Status; 0 = Netzwerkfehler (Backend nicht erreichbar) */
  readonly status: number
  /** Roher `detail`-Wert aus der Backend-Antwort (String, Validierungsliste oder Objekt) */
  readonly detail: unknown
  readonly method: string
  readonly path: string

  constructor(status: number, message: string, detail: unknown, method: string, path: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.method = method
    this.path = path
  }

  get isNetworkError(): boolean {
    return this.status === 0
  }
  get isUnauthorized(): boolean {
    return this.status === 401
  }
  get isConflict(): boolean {
    return this.status === 409
  }
  get isNotFound(): boolean {
    return this.status === 404
  }
  /** Zeitüberschreitung (Client-Timeout, siehe `RequestOptions.timeoutMs`) */
  get isTimeout(): boolean {
    return this.status === 408
  }
  /**
   * 409 „Die Bibliothek wird gerade geschrieben (Job „…“) … bitte in einigen Sekunden erneut versuchen“ – ein
   * Bibliotheks-Job hält die Bibliothek (Öffnen, Anlegen, Schließen warten bis zu 20 s). Vorübergehend:
   * „Erneut versuchen“ anbieten, kein Konflikt mit dem gewählten Ordner o. Ä.
   */
  get isLibraryBusy(): boolean {
    return this.status === 409 && /^die bibliothek(en)? (wird|werden) gerade geschrieben/i.test(this.message.trim())
  }
  /**
   * 409 „Es ist keine Bibliothek geöffnet.“ – bevorzugt über einen Fehlercode im `detail`
   * (`{"code": "no_workspace", …}`), sonst über den Text des Backends.
   */
  get isNoWorkspace(): boolean {
    if (this.status !== 409) return false
    const code = this.detail && typeof this.detail === 'object' ? (this.detail as { code?: unknown }).code : undefined
    if (code !== undefined) return code === 'no_workspace'
    return /keine bibliothek (ge)?öffnet/i.test(this.message)
  }
}

/** Abbruch durch den Aufrufer (AbortSignal) – kein Fehler, der angezeigt werden sollte. */
export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException ? error.name === 'AbortError' : error instanceof Error && error.name === 'AbortError'
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError
}

/** Fehlertext für die Oberfläche (beliebiger Fehler). */
export function errorMessage(error: unknown, fallback = tr("Unbekannter Fehler")): string {
  if (error instanceof ApiError) return cleanErrorText(error.message)
  if (error instanceof Error && error.message) return cleanErrorText(error.message)
  if (typeof error === 'string') return cleanErrorText(error)
  return fallback
}

/** „ValueError: “, „partforge.altium.bridge.BridgeError: “ … am Anfang eines Fehlertexts */
const ERROR_CLASS_PREFIX =
  /^\s*(?:[a-z_][\w]*\.)*[A-Z][A-Za-z0-9_]*(?:Error|Exception|Exceeded|Unavailable|Busy|Changed|Failed|NotFound|NotOpen|Cancelled|Timeout|Warning)\s*:\s*(?=\S)/

/** Deutsche Texte der häufigsten Betriebssystemfehler (`errno`) in Python-Meldungen „[Errno 13] Permission denied: '…'“ */
const ERRNO_TEXT: Record<number, string> = {
  get 2() { return tr("Datei oder Ordner nicht gefunden") },
  get 5() { return tr("Zugriff verweigert") },
  get 13() { return tr("Zugriff verweigert – die Datei ist von einem anderen Programm geöffnet oder schreibgeschützt") },
  get 17() { return tr("Datei oder Ordner gibt es bereits") },
  get 20() { return tr("Kein Ordner") },
  get 21() { return tr("Ist ein Ordner") },
  get 22() { return tr("Ungültiger Name oder Pfad") },
  get 24() { return tr("Zu viele geöffnete Dateien") },
  get 28() { return tr("Kein Speicherplatz mehr auf dem Datenträger") },
  get 30() { return tr("Datenträger ist schreibgeschützt") },
  get 32() { return tr("Die Datei wird von einem anderen Programm verwendet") },
  get 36() { return tr("Dateiname zu lang") },
  get 39() { return tr("Ordner ist nicht leer") },
}

/** Pfad aus einer Python-Darstellung ('C:\\\\Projekte\\\\x') lesbar machen: einfache Backslashes, ohne Anführungszeichen */
function unescapePythonPath(raw: string): string {
  return raw.replace(/\\\\/g, '\\')
}

/**
 * Python-Darstellungen von Betriebssystemfehlern in deutsche Texte übersetzen:
 * „[Errno 13] Permission denied: 'C:\\\\…\\\\PF_CHIP.PcbLib'“ → „Zugriff verweigert … (C:\…\PF_CHIP.PcbLib)“,
 * „[WinError 32] Der Prozess kann …: 'C:\\\\…'“ → „Der Prozess kann …: „C:\…““ (Windows liefert den Text schon deutsch).
 */
function cleanOsErrors(text: string): string {
  return (
    text
      // englischer Text der C-Bibliothek: nur Buchstaben und Leerzeichen bis zum Pfad bzw. Satzzeichen
      .replace(
        /\[Errno (\d+)\] ([A-Za-z][A-Za-z ']*?)(?:: (['"])((?:(?!\3).)*)\3)?(?=$|[^A-Za-z '])/g,
        (_m, code: string, message: string, _q: string | undefined, path: string | undefined) => {
          const german = ERRNO_TEXT[Number(code)] ?? message.trim()
          return path ? `${german} (${unescapePythonPath(path)})` : german
        },
      )
      .replace(/\[WinError \d+\]\s*/g, '')
      // übrige Python-Pfade mit verdoppelten Backslashes ('C:\\\\x')
      .replace(/(['"])([A-Za-z]:\\\\(?:(?!\1).)*)\1/g, (_m, _q: string, path: string) => `„${unescapePythonPath(path)}“`)
  )
}

/**
 * Fehlertext für Toasts und Statuszeilen: entfernt vorsorglich einen führenden Python-Klassennamen
 * („ValueError: Die Datei …“ → „Die Datei …“) und übersetzt Python-Darstellungen von Betriebssystemfehlern
 * („[Errno 13] Permission denied: 'C:\\\\x'“ → „Zugriff verweigert … (C:\x)“). Backend-Texte sind deutsch; nur ältere
 * Jobs/Fremdfehler tragen das noch. „Interner Fehler (KeyError): …“ bleibt (Hinweis für Fehlerberichte).
 */
export function cleanErrorText(text: string): string {
  return localizeMessage(cleanOsErrors(text.replace(ERROR_CLASS_PREFIX, '')))
}

const STATUS_TEXT: Record<number, string> = {
  get 0() { return tr("Das PartForge-Backend ist nicht erreichbar. Läuft die Anwendung noch?") },
  get 408() { return tr("Zeitüberschreitung: Das Backend hat nicht rechtzeitig geantwortet. Bitte erneut versuchen.") },
  get 400() { return tr("Ungültige Anfrage.") },
  get 401() { return tr("Die Sitzung ist ungültig. Bitte PartForge neu starten.") },
  get 403() { return tr("Keine Berechtigung für diese Aktion.") },
  get 404() { return tr("Nicht gefunden.") },
  get 409() { return tr("Die Aktion steht im Konflikt mit dem aktuellen Zustand.") },
  get 413() { return tr("Die Datei ist zu groß.") },
  get 422() { return tr("Ungültige Eingabe.") },
  get 500() { return tr("Interner Fehler im Backend. Details stehen im Protokoll (partforge.log).") },
  get 502() { return tr("Das Backend antwortet nicht.") },
  get 503() { return tr("Der Dienst ist vorübergehend nicht verfügbar.") },
  get 504() { return tr("Zeitüberschreitung beim Backend.") },
}

const PYDANTIC_MESSAGES: [RegExp, string][] = [
  [/^Field required$/i, 'Pflichtfeld fehlt'],
  [/^Input should be a valid string$/i, 'Text erwartet'],
  [/^Input should be a valid number/i, 'Zahl erwartet'],
  [/^Input should be a valid integer/i, 'Ganzzahl erwartet'],
  [/^Input should be a valid boolean/i, 'Ja/Nein-Wert erwartet'],
  [/^Input should be (.+)$/i, 'Erlaubt: $1'],
  [/^Value error, (.+)$/i, '$1'],
]

function translatePydantic(msg: string): string {
  // the backend's own validators answer in German („Value error, Seitenzahlen beginnen bei 1.“)
  for (const [re, de] of PYDANTIC_MESSAGES) {
    if (re.test(msg)) return localizeMessage(msg.replace(re, tr(de)))
  }
  return localizeMessage(msg)
}

export function detailToMessage(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const parts = detail.map((item) => {
      if (item && typeof item === 'object') {
        const rec = item as { loc?: unknown[]; msg?: string }
        const loc = Array.isArray(rec.loc) ? rec.loc.filter((x) => x !== 'body' && x !== 'query').join('.') : ''
        const msg = translatePydantic(String(rec.msg ?? ''))
        return loc ? `${loc}: ${msg}` : msg
      }
      return String(item)
    })
    if (parts.length) return `${STATUS_TEXT[422]} ${parts.join('; ')}`
  }
  if (detail && typeof detail === 'object') {
    const rec = detail as { message?: unknown; detail?: unknown }
    if (typeof rec.message === 'string') return rec.message
    if (typeof rec.detail === 'string') return rec.detail
  }
  return STATUS_TEXT[status] ?? tr("Fehler {0}", { "0": String(status) })
}

// --------------------------------------------------------------------------- globale Hooks

export type ApiErrorListener = (error: ApiError) => void
const errorListeners = new Set<ApiErrorListener>()

/**
 * Wird bei 401- und 409-Antworten aufgerufen (vor dem Werfen). Gibt eine Abmeldefunktion zurück.
 * Die App-Shell nutzt das für „Sitzung ungültig“ und „keine Bibliothek geöffnet“ → /willkommen.
 */
export function onApiError(listener: ApiErrorListener): () => void {
  errorListeners.add(listener)
  return () => errorListeners.delete(listener)
}

function notify(error: ApiError) {
  if (error.status !== 401 && error.status !== 409) return
  for (const listener of errorListeners) {
    try {
      listener(error)
    } catch (e) {
      console.error(e)
    }
  }
}

// --------------------------------------------------------------------------- Beobachter einzelner Endpunkte

/** Ausgang einer Anfrage für {@link observeApi} */
export type ApiOutcome = { ok: true; status: number; data: unknown } | { ok: false; error: ApiError }

interface EndpointObserver {
  method: string
  path: string | RegExp
  listener: (outcome: ApiOutcome) => void
}

const endpointObservers = new Set<EndpointObserver>()

/**
 * Ergebnis eines Endpunkts beobachten – gleich, welche Seite ihn aufruft (z. B. den KI-Verbindungstest für die
 * Statuszeile der Seitenleiste). `path` ohne Abfrage-Parameter (Zeichenkette exakt oder RegExp). Abbrüche über ein
 * `AbortSignal` werden nicht gemeldet. Gibt eine Abmeldefunktion zurück.
 *
 *   observeApi('POST', '/api/ai/test', (r) => (r.ok ? merken(r.data) : merken(r.error)))
 */
export function observeApi(method: string, path: string | RegExp, listener: (outcome: ApiOutcome) => void): () => void {
  const entry: EndpointObserver = { method: method.toUpperCase(), path, listener }
  endpointObservers.add(entry)
  return () => {
    endpointObservers.delete(entry)
  }
}

function report(method: string, path: string, outcome: ApiOutcome): void {
  if (!endpointObservers.size) return
  for (const o of endpointObservers) {
    if (o.method !== method) continue
    if (typeof o.path === 'string' ? o.path !== path : !o.path.test(path)) continue
    try {
      o.listener(outcome)
    } catch (e) {
      console.error(e)
    }
  }
}

// --------------------------------------------------------------------------- Requests

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | readonly QueryValue[]>

export interface RequestOptions {
  query?: QueryParams
  signal?: AbortSignal
  headers?: Record<string, string>
  /** Standard: JSON (bzw. Text, falls die Antwort kein JSON ist) */
  responseType?: 'json' | 'text' | 'blob'
  /**
   * Zeitlimit in ms (Standard 30 s, Uploads ohne Limit). 0 = kein Limit.
   * Lange Operationen laufen ohnehin als Job und antworten sofort.
   */
  timeoutMs?: number
}

const DEFAULT_TIMEOUT_MS = 30_000

export function buildQuery(query?: QueryParams): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, raw] of Object.entries(query)) {
    const values = Array.isArray(raw) ? raw : [raw]
    for (const v of values) {
      if (v === undefined || v === null || v === '') continue
      params.append(key, String(v))
    }
  }
  const s = params.toString()
  return s ? `?${s}` : ''
}

/**
 * URL für Stellen, die keinen Header senden können – **nur** EventSource und `<img src>` (Seitenbilder der
 * Datenblätter): hängt das Token als Query-Parameter an (das Backend schwärzt `token=` in jedem Protokoll).
 * Downloads, Exporte und die Datenblatt-PDF laden über {@link download}/`api.get` mit dem Header; `withToken = false`
 * baut nur die Adresse (z. B. zum Prüfen ihrer Länge). Siehe ARCHITEKTUR.md §2.1.
 */
export function apiUrl(path: string, query?: QueryParams, withToken = true): string {
  const q = withToken ? { ...query, token: getToken() } : query
  return `${path}${buildQuery(q)}`
}

/**
 * Anfrage senden und Fehler als {@link ApiError} werfen (inkl. 401/409-Hooks und Beobachter) – die Antwort selbst liest
 * der Aufrufer ({@link request}: JSON/Text/Blob, {@link download}: Blob + Dateiname).
 */
async function send(method: string, path: string, body: unknown, opts: RequestOptions, accept: string): Promise<Response> {
  const headers: Record<string, string> = { Accept: accept, ...opts.headers }
  const token = getToken()
  if (token) headers[TOKEN_HEADER] = token

  let payload: BodyInit | undefined
  if (body instanceof FormData || body instanceof Blob) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }

  const url = `${path}${buildQuery(opts.query)}`
  const timeoutMs = opts.timeoutMs ?? (body instanceof FormData ? 0 : DEFAULT_TIMEOUT_MS)
  const timeout = timeoutMs > 0 ? AbortSignal.timeout(timeoutMs) : null
  const signal = timeout && opts.signal ? AbortSignal.any([opts.signal, timeout]) : (timeout ?? opts.signal)
  let response: Response
  try {
    response = await fetch(url, { method, headers, body: payload, signal })
  } catch (err) {
    // Abbruch durch den Aufrufer: Grund unverändert weiterreichen (React Query erkennt das)
    if (opts.signal?.aborted) throw opts.signal.reason ?? err
    if (isAbortError(err) && !timeout?.aborted) throw err
    const error = timeout?.aborted
      ? new ApiError(408, STATUS_TEXT[408], null, method, path)
      : new ApiError(0, STATUS_TEXT[0], null, method, path)
    report(method, path, { ok: false, error })
    throw error
  }

  if (!response.ok) {
    let detail: unknown = null
    const text = await response.text().catch(() => '')
    if (text) {
      try {
        const parsed = JSON.parse(text) as { detail?: unknown }
        detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : parsed
      } catch {
        detail = text.length < 400 ? text : null
      }
    }
    const error = new ApiError(response.status, detailToMessage(detail, response.status), detail, method, path)
    notify(error)
    report(method, path, { ok: false, error })
    throw error
  }
  return response
}

export async function request<T>(method: string, path: string, body?: unknown, opts: RequestOptions = {}): Promise<T> {
  const response = await send(method, path, body, opts, 'application/json')
  const data = await readBody<T>(response, opts.responseType)
  report(method, path, { ok: true, status: response.status, data })
  return data
}

/** Datei-Antwort von {@link download} */
export interface DownloadResult {
  blob: Blob
  /** aus `Content-Disposition` (UTF-8-Name nach RFC 5987 vor `filename="…"`), sonst `fallbackName` */
  fileName: string
  size: number
  /** MIME-Typ der Antwort (`Content-Type`) */
  contentType: string
}

export interface DownloadOptions extends Omit<RequestOptions, 'responseType'> {
  /** Dateiname, wenn die Antwort keinen nennt (Standard: letzter Abschnitt des Pfads) */
  fallbackName?: string
}

/** Dateiname aus `Content-Disposition` – `filename*=UTF-8''…` (RFC 5987) vor `filename="…"` bzw. `filename=…` */
export function fileNameFromDisposition(header: string | null | undefined, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*\s*=\s*([^';]*)'[^']*'([^;]+)/i.exec(header)
  if (star) {
    try {
      const name = decodeURIComponent(star[2].trim().replace(/^"|"$/g, ''))
      if (name) return name
    } catch {
      // ungültige Kodierung: auf den einfachen Namen zurückfallen
    }
  }
  const quoted = /filename\s*=\s*"((?:[^"\\]|\\.)*)"/i.exec(header)
  if (quoted?.[1]) return quoted[1].replace(/\\(.)/g, '$1')
  const bare = /filename\s*=\s*([^;]+)/i.exec(header)
  return bare?.[1]?.trim() || fallback
}

/**
 * Datei laden (GET): Inhalt als Blob **und** Dateiname aus `Content-Disposition` – für Downloads, die über
 * `saveFile`/`saveBlob` aus `@/lib/download` gespeichert werden. Fehler wie bei `api.get` (`ApiError`, deutscher Text).
 *
 *   const { blob, fileName } = await api.download('/api/altium/dblib/preview', { query: { raw: true } })
 *   await saveBlob(blob, fileName, { type: FILE_TYPES.txt })
 */
export async function download(path: string, opts: DownloadOptions = {}): Promise<DownloadResult> {
  const { fallbackName, ...rest } = opts
  const response = await send('GET', path, undefined, rest, '*/*')
  const blob = await response.blob()
  const fallback = fallbackName ?? (path.split('?')[0].split('/').filter(Boolean).pop() || 'Download')
  const result: DownloadResult = {
    blob,
    fileName: fileNameFromDisposition(response.headers.get('content-disposition'), fallback),
    size: blob.size,
    contentType: response.headers.get('content-type') ?? blob.type,
  }
  report('GET', path, { ok: true, status: response.status, data: result })
  return result
}

async function readBody<T>(response: Response, responseType: RequestOptions['responseType']): Promise<T> {
  if (response.status === 204) return undefined as T
  if (responseType === 'blob') return (await response.blob()) as T
  if (responseType === 'text') return (await response.text()) as T
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) return (await response.json()) as T
  const text = await response.text()
  return (text ? text : undefined) as T
}

export const api = {
  get: <T>(path: string, opts?: RequestOptions) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('POST', path, body, opts),
  put: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PUT', path, body, opts),
  patch: <T>(path: string, body?: unknown, opts?: RequestOptions) => request<T>('PATCH', path, body, opts),
  delete: <T>(path: string, opts?: RequestOptions) => request<T>('DELETE', path, undefined, opts),
  /** multipart/form-data, z. B. Datenblatt-Upload: api.upload('/api/datasheets', form) */
  upload: <T>(path: string, form: FormData, opts?: RequestOptions) => request<T>('POST', path, form, opts),
  /** Datei laden: `{ blob, fileName, size, contentType }` (Name aus `Content-Disposition`) – siehe {@link download} */
  download,
  url: apiUrl,
}
