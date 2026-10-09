/**
 * Vorschau interner Teilenummern – dieselben Regeln wie `partforge/db/parts.py::_next_internal_pn`
 * (Python `str.format` mit `prefix`, `counter`, `table`). Unterstützt werden die Formatangaben, die in der Praxis
 * vorkommen: `{counter}`, `{counter:06d}`, `{prefix}`, `{table}`, `{{` / `}}`.
 *
 * Abgelehnt wird (wie im Backend: `PUT /api/workspace/settings`, `Workspace.open`):
 * - alles, woran Python scheitern würde (Leerzeichen im Platzhalter `{ prefix }`, unbekannte Namen) – das Backend fiele
 *   sonst stillschweigend auf `{prefix}-{counter:06d}` zurück;
 * - kein oder mehr als ein `{counter}` (ohne Zähler hätten alle Bauteile dieselbe Nummer – jedes Speichern hinge);
 * - Zeichen, die in Teilenummern verboten sind (`'` `{` `}` `|` und Steuerzeichen wie Tab – auch über `{{`/`}}`):
 *   ein ' bricht die Abfragen von Altium (`[Part Number] = '…'`);
 * - Leerzeichen am Anfang/Ende oder mehrere hintereinander (auch durch `{counter:6}`): Eingaben werden so
 *   gekürzt, eine erzeugte Nummer ließe sich nicht wieder eintippen.
 */

export const PN_PLACEHOLDERS = [
  { token: '{prefix}', label: 'Präfix der Kategorie', example: 'R' },
  { token: '{counter:06d}', label: 'Zähler, 6-stellig mit Nullen', example: '000042' },
  { token: '{counter}', label: 'Zähler ohne Nullen', example: '42' },
  { token: '{table}', label: 'Tabellenname', example: 'Resistors' },
] as const

export interface PnFormatResult {
  ok: boolean
  /** Fehlermeldung (Backend würde auf „{prefix}-{counter:06d}“ ausweichen) */
  error: string | null
  render: (prefix: string, counter: number, table: string) => string
}

type Piece = { kind: 'text'; text: string } | { kind: 'field'; name: string; spec: string }

function parse(format: string): Piece[] | string {
  const pieces: Piece[] = []
  let text = ''
  for (let i = 0; i < format.length; i++) {
    const ch = format[i]
    if (ch === '{') {
      if (format[i + 1] === '{') {
        text += '{'
        i++
        continue
      }
      const end = format.indexOf('}', i)
      if (end < 0) return 'Eine geschweifte Klammer „{“ ist nicht geschlossen.'
      if (text) pieces.push({ kind: 'text', text })
      text = ''
      const inner = format.slice(i + 1, end)
      const colon = inner.indexOf(':')
      // Name nicht kürzen: Python sucht „ prefix “ wörtlich (KeyError → Ausweichformat)
      pieces.push({ kind: 'field', name: colon < 0 ? inner : inner.slice(0, colon), spec: colon < 0 ? '' : inner.slice(colon + 1) })
      i = end
      continue
    }
    if (ch === '}') {
      if (format[i + 1] === '}') {
        text += '}'
        i++
        continue
      }
      return 'Eine geschweifte Klammer „}“ steht ohne „{“.'
    }
    text += ch
  }
  if (text) pieces.push({ kind: 'text', text })
  return pieces
}

const COUNTER_SPEC = /^(0?)(\d*)d?$/
/** In Teilenummern verboten (= `partforge/db/values.py::_FORBIDDEN_PN_CHARS`): ' { } | und Steuerzeichen */
// eslint-disable-next-line no-control-regex -- Steuerzeichen sind genau das, was hier gesucht wird
const FORBIDDEN_PN_CHARS = /['{}|\u0000-\u001f\u007f]/g

/** Verbotene Zeichen lesbar: „Tab“, „' |“ */
function describeChars(chars: string[]): string {
  return chars
    .map((c) => {
      if (c === '\t') return 'Tab'
      if (c === '\n' || c === '\r') return 'Zeilenumbruch'
      const code = c.charCodeAt(0)
      return code < 32 || code === 127 ? `Steuerzeichen ${code}` : c
    })
    .join(' ')
}

/** Prüft eine erzeugte Nummer wie das Backend eine eingegebene (`normalize_cell`) – null = in Ordnung */
export function checkGeneratedPn(pn: string): string | null {
  const bad = [...new Set(pn.match(FORBIDDEN_PN_CHARS) ?? [])]
  if (bad.length) {
    return `Das Format erzeugt Zeichen, die in Teilenummern nicht erlaubt sind (${describeChars(bad)}). Nicht erlaubt sind ' { } | und Steuerzeichen.`
  }
  if (pn !== pn.trim()) return 'Das Format erzeugt Leerzeichen am Anfang oder Ende der Teilenummer.'
  if (/\s{2,}/.test(pn)) {
    return 'Das Format erzeugt mehrere Leerzeichen hintereinander (z. B. durch {counter:6}) – bitte {counter:06d} (mit Nullen) verwenden.'
  }
  return null
}

export function compilePnFormat(format: string): PnFormatResult {
  const fallback = (prefix: string, counter: number) => `${prefix}-${String(counter).padStart(6, '0')}`
  if (!format.trim()) {
    return { ok: false, error: 'Das Format darf nicht leer sein.', render: fallback }
  }
  const parsed = parse(format)
  if (typeof parsed === 'string') return { ok: false, error: parsed, render: fallback }
  let counters = 0
  for (const p of parsed) {
    if (p.kind !== 'field') continue
    if (p.name === 'counter') {
      counters += 1
      if (!COUNTER_SPEC.test(p.spec)) {
        return { ok: false, error: `Die Zählerangabe „{counter:${p.spec}}“ wird nicht unterstützt (z. B. {counter:06d}).`, render: fallback }
      }
    } else if (p.name === 'prefix' || p.name === 'table') {
      if (p.spec && p.spec !== 's') {
        return { ok: false, error: `Die Formatangabe „{${p.name}:${p.spec}}“ wird nicht unterstützt.`, render: fallback }
      }
    } else if (/\s/.test(p.name) && ['prefix', 'counter', 'table'].includes(p.name.trim())) {
      return {
        ok: false,
        error: `Leerzeichen im Platzhalter „{${p.name}}“ – bitte {${p.name.trim()}} schreiben.`,
        render: fallback,
      }
    } else {
      return {
        ok: false,
        error: p.name.trim() ? `Unbekannter Platzhalter „{${p.name}}“ – erlaubt sind {prefix}, {counter} und {table}.` : 'Leerer Platzhalter „{}“.',
        render: fallback,
      }
    }
  }
  if (counters === 0) {
    return { ok: false, error: 'Ohne {counter} hätten alle Bauteile dieselbe Nummer.', render: fallback }
  }
  if (counters > 1) {
    return { ok: false, error: '{counter} darf nur einmal vorkommen.', render: fallback }
  }
  const render = (prefix: string, counter: number, table: string) =>
    parsed
      .map((p) => {
        if (p.kind === 'text') return p.text
        if (p.name === 'prefix') return prefix
        if (p.name === 'table') return table
        const m = COUNTER_SPEC.exec(p.spec)
        const width = m && m[2] ? Number(m[2]) : 0
        const digits = String(counter)
        return m && m[1] === '0' ? digits.padStart(width, '0') : digits.padStart(width, ' ')
      })
      .join('')
  // Beispiele wie im Backend prüfen: kurzer und langer Zähler, Präfix und Tabellenname mit Leerzeichen
  for (const [prefix, counter, table] of [
    ['R', 1, 'Resistors'],
    ['U', 123456, 'Integrated Circuits'],
  ] as const) {
    const problem = checkGeneratedPn(render(prefix, counter, table))
    if (problem) return { ok: false, error: problem, render: fallback }
  }
  return { ok: true, error: null, render }
}
