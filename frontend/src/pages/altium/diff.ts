/**
 * Zeilenweiser Vergleich (LCS) mit Kontext – für die DbLib-Vorschau „Datei auf der Festplatte → Soll-Stand“.
 * Gemeinsamer Anfang und gemeinsames Ende werden vorab abgeschnitten (eine DbLib ändert sich meist nur an wenigen
 * Stellen); ist der Rest sehr groß, wird er als „alles entfernt, alles neu“ gezeigt statt den Rechner zu blockieren.
 */
export interface DiffRow {
  kind: 'same' | 'add' | 'del' | 'gap'
  text?: string
  /** Zeilennummer links (vorher) / rechts (nachher), 1-basiert */
  a?: number
  b?: number
  /** Anzahl ausgelassener, unveränderter Zeilen (`gap`) */
  count?: number
}

const MAX_CELLS = 4_000_000

export function diffLines(before: string[], after: string[], context = 3): DiffRow[] {
  let start = 0
  while (start < before.length && start < after.length && before[start] === after[start]) start++
  let endA = before.length
  let endB = after.length
  while (endA > start && endB > start && before[endA - 1] === after[endB - 1]) {
    endA--
    endB--
  }
  const A = before.slice(start, endA)
  const B = after.slice(start, endB)
  const middle: DiffRow[] = []

  if (A.length * B.length > MAX_CELLS) {
    A.forEach((text, i) => middle.push({ kind: 'del', text, a: start + i + 1 }))
    B.forEach((text, j) => middle.push({ kind: 'add', text, b: start + j + 1 }))
  } else {
    // LCS-Tabelle von hinten (lcs[i][j] = Länge der LCS von A[i..] und B[j..])
    const w = B.length + 1
    const lcs = new Uint32Array((A.length + 1) * w)
    for (let i = A.length - 1; i >= 0; i--) {
      for (let j = B.length - 1; j >= 0; j--) {
        lcs[i * w + j] = A[i] === B[j] ? lcs[(i + 1) * w + j + 1] + 1 : Math.max(lcs[(i + 1) * w + j], lcs[i * w + j + 1])
      }
    }
    let i = 0
    let j = 0
    while (i < A.length || j < B.length) {
      if (i < A.length && j < B.length && A[i] === B[j]) {
        middle.push({ kind: 'same', text: A[i], a: start + i + 1, b: start + j + 1 })
        i++
        j++
      } else if (j < B.length && (i >= A.length || lcs[i * w + j + 1] >= lcs[(i + 1) * w + j])) {
        middle.push({ kind: 'add', text: B[j], b: start + j + 1 })
        j++
      } else {
        middle.push({ kind: 'del', text: A[i], a: start + i + 1 })
        i++
      }
    }
  }

  // Vollständige Folge (Anfang + Mitte + Ende) auf Änderungen mit Kontext verdichten
  const all: DiffRow[] = []
  for (let k = 0; k < start; k++) all.push({ kind: 'same', text: before[k], a: k + 1, b: k + 1 })
  all.push(...middle)
  for (let k = 0; k < before.length - endA; k++) {
    all.push({ kind: 'same', text: before[endA + k], a: endA + k + 1, b: endB + k + 1 })
  }
  if (!all.some((r) => r.kind !== 'same')) return []

  const keep = new Uint8Array(all.length)
  all.forEach((r, idx) => {
    if (r.kind === 'same') return
    for (let k = Math.max(0, idx - context); k <= Math.min(all.length - 1, idx + context); k++) keep[k] = 1
  })
  const out: DiffRow[] = []
  let skipped = 0
  all.forEach((r, idx) => {
    if (keep[idx]) {
      if (skipped) out.push({ kind: 'gap', count: skipped })
      skipped = 0
      out.push(r)
    } else skipped++
  })
  if (skipped) out.push({ kind: 'gap', count: skipped })
  return out
}
