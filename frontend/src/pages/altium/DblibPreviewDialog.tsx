import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { ChevronDown, ChevronUp, ClipboardCopy, Download, FileCode2, FolderOpen, Search, X } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { altiumApi, useDblibPreview, type DbLibFileWhich } from '@/api/altium'
import { cleanErrorText, errorMessage } from '@/api/client'
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  IconButton,
  Input,
  Skeleton,
  Tabs,
  TabsList,
  TabsTrigger,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { saveFileWithFeedback, type SaveFileType } from '@/lib/download'
import { formatNumber, plural } from '@/lib/format'
import { revealPath, useNativeBridge } from '@/lib/native'
import { diffLines } from './diff'

type View = 'text' | 'current' | 'diff'

const DBLIB_TYPE: SaveFileType = { get description() { return tr("Altium-Datenbankbibliothek") }, mime: 'text/plain', extensions: ['.DbLib'] }
/** Maskiertes Kennwort in der Vorschau (`mask_secrets`: `PWD=***`, `Password=***`) */
const MASKED_SECRET = /\b(?:pwd|password)\s*=\s*\*\*\*/i

const splitLines = (text: string) => text.replace(/\r\n/g, '\n').split('\n')

export function DblibPreviewDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t: tr } = useI18n()
  const preview = useDblibPreview(open)
  const data = preview.data
  const bridge = useNativeBridge()
  const [view, setView] = useState<View>('text')
  const [query, setQuery] = useState('')
  const [saving, setSaving] = useState(false)
  const differs = Boolean(data?.current !== null && data?.current !== undefined && data.current !== data.text)
  const effectiveView: View = view === 'diff' && !differs ? 'text' : view === 'current' && !data?.current ? 'text' : view

  const text = effectiveView === 'current' ? (data?.current ?? '') : (data?.text ?? '')
  const lines = useMemo(() => splitLines(text), [text])
  const q = query.trim()
  const hits = useMemo(() => {
    if (!q || effectiveView === 'diff') return []
    const needle = q.toLowerCase()
    const out: number[] = []
    lines.forEach((l, i) => {
      if (l.toLowerCase().includes(needle)) out.push(i)
    })
    return out
  }, [lines, q, effectiveView])
  const [cursor, setCursor] = useState(0)
  const [hitsFor, setHitsFor] = useState(hits)
  if (hitsFor !== hits) {
    setHitsFor(hits)
    setCursor(0)
  }
  const current = hits.length ? Math.min(cursor, hits.length - 1) : -1
  const active = current >= 0 ? hits[current] : -1
  const step = (delta: number) => {
    if (hits.length) setCursor((c) => (c + delta + hits.length) % hits.length)
  }

  // Der Soll-Stand wird gespeichert, solange er angezeigt wird; in der Ansicht „Datei auf der Festplatte“ diese Datei
  const which: DbLibFileWhich = effectiveView === 'current' ? 'file' : 'target'
  const masked = MASKED_SECRET.test(which === 'file' ? (data?.current ?? '') : (data?.text ?? ''))

  const copy = () =>
    void navigator.clipboard
      ?.writeText(text)
      .then(() => toast.success(tr("DbLib-Text kopiert"), { description: `${plural(lines.length, tr("Zeile"), tr("Zeilen"))}${masked ? tr(" · Kennwort maskiert") : ''}` }))
      .catch(() => toast.error(tr("Kopieren nicht möglich")))

  /**
   * Speichern: die exakten Bytes vom Backend (`?raw=true`, Windows-1252/CRLF, Kennwort im Klartext) mit dem Dateinamen
   * aus `Content-Disposition` – über die Desktop-Brücke als Binärdaten (base64), sonst Dialog bzw. Download.
   */
  const download = async () => {
    if (saving) return
    setSaving(true)
    const what = which === 'file' ? 'DbLib' : tr("DbLib (Soll-Stand)")
    try {
      const file = await altiumApi.dblibFile(which)
      await saveFileWithFeedback({ suggestedName: file.fileName, content: file.blob, type: DBLIB_TYPE, what, id: 'dblib-download' })
    } catch (err) {
      toast.error(tr("{0} konnte nicht geladen werden", { "0": String(what) }), { id: 'dblib-download', description: cleanErrorText(errorMessage(err)) })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o)
        if (!o) setQuery('')
      }}
    >
      <DialogContent
        size="xl"
        className="h-[min(820px,calc(100dvh-11vh-1.5rem))]"
        onEscapeKeyDown={(e) => {
          // Esc leert zuerst die Suche – erst ein zweites Esc schließt den Dialog
          if (query) {
            e.preventDefault()
            setQuery('')
          }
        }}
      >
        <DialogHeader
          icon={<FileCode2 />}
          title={
            <span className="flex flex-wrap items-center gap-2">
              {tr("DbLib-Vorschau")}{data && (
                <Badge variant={data.up_to_date ? 'success' : 'warning'} dot>
                  {data.up_to_date ? tr("Datei ist aktuell") : data.current === null ? tr("Datei fehlt") : tr("Datei ist veraltet")}
                </Badge>
              )}
            </span>
          }
          description={
            data
              ? tr("{0} – so schreibt PartForge die Datei.{1}", { "0": String(data.file_name), "1": String(masked ? ' Kennwörter sind hier maskiert; die gespeicherte Datei enthält sie, weil Altium sie braucht.' : '') })
              : tr("Wird geladen …")
          }
        />
        <div className="flex shrink-0 flex-wrap items-center gap-3 px-6 pb-3">
          <Tabs value={effectiveView} onValueChange={(v) => setView(v as View)} variant="pill">
            <TabsList aria-label={tr("Ansicht")}>
              <TabsTrigger value="text">{tr("Soll-Stand")}</TabsTrigger>
              <TabsTrigger value="current" disabled={!data?.current}>
                {tr("Datei auf der Festplatte")}</TabsTrigger>
              <TabsTrigger value="diff" disabled={!differs}>
                {tr("Unterschiede")}</TabsTrigger>
            </TabsList>
          </Tabs>
          {effectiveView !== 'diff' && (
            <SearchBox query={query} onQuery={setQuery} hits={hits.length} current={current} onStep={step} />
          )}
        </div>
        {data && data.warnings.length > 0 && (
          <div className="shrink-0 px-6 pb-3">
            <Callout tone="warning" title={plural(data.warnings.length, tr("Hinweis"), tr("Hinweise"))}>
              {data.warnings.map((w) => (
                <span key={w} className="block">
                  {localizeMessage(w)}
                </span>
              ))}
            </Callout>
          </div>
        )}
        <DialogBody className="border-t border-line p-0">
          {preview.isPending ? (
            <div className="flex flex-col gap-2 p-6" aria-busy="true">
              {Array.from({ length: 14 }, (_, i) => (
                <Skeleton key={i} className="h-3.5" style={{ width: `${30 + ((i * 37) % 60)}%` }} />
              ))}
            </div>
          ) : preview.isError ? (
            <div className="p-6">
              <Callout tone="danger" title={tr("Vorschau nicht verfügbar")}>
                {errorMessage(preview.error)}
              </Callout>
            </div>
          ) : data && effectiveView === 'diff' ? (
            <DiffView before={data.current ?? ''} after={data.text} />
          ) : data ? (
            <CodeView key={effectiveView} lines={lines} query={q} active={active} />
          ) : null}
        </DialogBody>
        <DialogFooter className="justify-between">
          <div className="flex items-center gap-2">
            <Button variant="ghost" leftIcon={<ClipboardCopy />} onClick={copy} disabled={!data}>
              {tr("Kopieren")}</Button>
            <Button variant="ghost" leftIcon={<Download />} onClick={() => void download()} disabled={!data} loading={saving}>
              {which === 'file' ? tr("Datei speichern …") : tr("Soll-Stand speichern …")}
            </Button>
            {data && (
              <Button variant="ghost" leftIcon={<FolderOpen />} onClick={() => void revealPath(data.path, { what: 'DbLib' })}>
                {bridge.canRevealPath || bridge.canOpenPath ? tr("Im Explorer zeigen") : tr("Pfad kopieren")}
              </Button>
            )}
          </div>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            {tr("Schließen")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --------------------------------------------------------------------------- Suche

/** Suchfeld mit Trefferzähler und Sprung (wie die Suche eines Editors) – Enter = nächster, ⇧ Enter = vorheriger */
function SearchBox({
  query,
  onQuery,
  hits,
  current,
  onStep,
}: {
  query: string
  onQuery: (q: string) => void
  hits: number
  /** Index des aktiven Treffers (−1 = keiner) */
  current: number
  onStep: (delta: number) => void
}) {
  const { t: tr } = useI18n()
  const searching = Boolean(query.trim())
  return (
    <Input
      size="sm"
      type="search"
      value={query}
      onChange={(e) => onQuery(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          onStep(e.shiftKey ? -1 : 1)
        }
      }}
      placeholder={tr("In der DbLib suchen …")}
      aria-label={tr("In der DbLib suchen")}
      aria-keyshortcuts="Enter Shift+Enter"
      prefix={<Search />}
      suffix={
        searching ? (
          <>
            <span className={cn('mono whitespace-nowrap pr-0.5 text-2xs', hits ? 'text-fg-muted' : 'text-danger-text')} aria-live="polite">
              <span aria-hidden>{hits ? `${formatNumber(current + 1)}/${formatNumber(hits)}` : '0/0'}</span>
              <span className="sr-only">{hits ? tr("Treffer {0} von {1} Zeilen", { "0": String(current + 1), "1": String(hits) }) : tr("Keine Treffer")}</span>
            </span>
            <IconButton size="xs" label={tr("Vorheriger Treffer")} icon={<ChevronUp />} disabled={!hits} onClick={() => onStep(-1)} tooltip={false} />
            <IconButton size="xs" label={tr("Nächster Treffer")} icon={<ChevronDown />} disabled={!hits} onClick={() => onStep(1)} tooltip={false} />
            <IconButton size="xs" label={tr("Suche leeren")} icon={<X />} onClick={() => onQuery('')} tooltip={false} />
          </>
        ) : undefined
      }
      containerClassName="ml-auto w-80 max-w-full"
    />
  )
}

// --------------------------------------------------------------------------- Code

interface Token {
  text: string
  cls: string
}

/** INI-Zeile in gefärbte Abschnitte zerlegen: [Abschnitt], Schlüssel=Wert, ;Kommentar, Options=a=b|c=d */
function tokenize(line: string): Token[] {
  const trimmed = line.trimStart()
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) return [{ text: line, cls: 'font-semibold text-accent-text' }]
  if (trimmed.startsWith(';')) return [{ text: line, cls: 'italic text-fg-subtle' }]
  const eq = line.indexOf('=')
  if (eq < 0) return [{ text: line, cls: 'text-fg' }]
  const out: Token[] = [
    { text: line.slice(0, eq), cls: 'text-info-text' },
    { text: '=', cls: 'text-fg-subtle' },
  ]
  const value = line.slice(eq + 1)
  if (!value.includes('|')) {
    out.push({ text: value, cls: 'text-fg' })
    return out
  }
  // Altium-Optionen: Schlüssel=Wert-Paare, durch „|“ getrennt
  value.split('|').forEach((pair, i) => {
    if (i > 0) out.push({ text: '|', cls: 'text-fg-subtle' })
    const at = pair.indexOf('=')
    if (at < 0) out.push({ text: pair, cls: 'text-fg' })
    else
      out.push(
        { text: pair.slice(0, at), cls: 'text-fg-muted' },
        { text: '=', cls: 'text-fg-subtle' },
        { text: pair.slice(at + 1), cls: 'text-fg' },
      )
  })
  return out
}

/** Zeile färben und Treffer markieren – auch über Abschnittsgrenzen hinweg (z. B. „ParameterName=[Footprint Ref]“) */
function highlight(line: string, query: string): ReactNode {
  const ranges: [number, number][] = []
  if (query) {
    const lower = line.toLowerCase()
    const q = query.toLowerCase()
    for (let at = lower.indexOf(q); at >= 0; at = lower.indexOf(q, at + q.length)) ranges.push([at, at + q.length])
  }
  let pos = 0
  return tokenize(line).map((tok, i) => {
    const start = pos
    const end = pos + tok.text.length
    pos = end
    const parts: ReactNode[] = []
    let cur = start
    for (const [a, b] of ranges) {
      if (b <= cur || a >= end) continue
      const from = Math.max(a, cur)
      const to = Math.min(b, end)
      if (from > cur) parts.push(tok.text.slice(cur - start, from - start))
      parts.push(
        <mark key={from} className="rounded-sm bg-accent/30 text-fg">
          {tok.text.slice(from - start, to - start)}
        </mark>,
      )
      cur = to
    }
    if (cur < end) parts.push(tok.text.slice(cur - start))
    return (
      <span key={i} className={tok.cls}>
        {parts}
      </span>
    )
  })
}

function CodeView({ lines, query, active }: { lines: string[]; query: string; active: number }) {
  const { t: tr } = useI18n()
  const container = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (active < 0) return
    // Treffer selbst ansteuern (auch waagerecht – Options-Zeilen sind lang), sonst die Zeile
    const row = container.current?.querySelector(`[data-line="${active}"]`)
    const hit = row?.querySelector('mark') ?? row
    hit?.scrollIntoView({ block: 'center', inline: 'center' })
  }, [active])

  const digits = String(lines.length).length
  return (
    <div
      ref={container}
      role="textbox"
      aria-readonly="true"
      aria-multiline="true"
      aria-label={tr("DbLib-Text")}
      tabIndex={0}
      className="overflow-x-auto py-2 font-mono text-xs leading-[1.6] outline-none focus-ring-inset"
    >
      {lines.map((line, i) => (
        <div
          key={i}
          data-line={i}
          className={cn('flex min-w-max pr-6 [content-visibility:auto] [contain-intrinsic-size:auto_19px]', i === active && 'bg-accent-soft')}
        >
          <span aria-hidden className="sticky left-0 z-10 shrink-0 select-none bg-surface px-3 text-right text-fg-subtle/80" style={{ width: `${digits + 2.5}ch` }}>
            {i + 1}
          </span>
          <span className="whitespace-pre pl-2">{line ? highlight(line, query) : ' '}</span>
        </div>
      ))}
    </div>
  )
}

// --------------------------------------------------------------------------- Unterschiede

function DiffView({ before, after }: { before: string; after: string }) {
  const { t: tr } = useI18n()
  const rows = useMemo(() => diffLines(splitLines(before), splitLines(after)), [before, after])
  const added = rows.filter((r) => r.kind === 'add').length
  const removed = rows.filter((r) => r.kind === 'del').length
  return (
    <div className="py-2 font-mono text-xs leading-[1.6]">
      <div className="flex items-center gap-3 px-4 pb-2 font-sans text-2xs text-fg-muted">
        <span>{tr("Datei auf der Festplatte → Soll-Stand:")}</span>
        <span className="mono text-success-text">+{formatNumber(added)}</span>
        <span className="mono text-danger-text">−{formatNumber(removed)}</span>
      </div>
      {rows.length === 0 && <p className="px-4 font-sans text-xs text-fg-muted">{tr("Nur Zeilenenden oder Zeichensatz unterscheiden sich.")}</p>}
      {rows.map((r, i) => (
        <Fragment key={i}>
          {r.kind === 'gap' ? (
            <div className="my-1 border-y border-line bg-surface-2/50 px-4 py-0.5 font-sans text-2xs text-fg-subtle">
              {plural(r.count ?? 0, tr("unveränderte Zeile"), tr("unveränderte Zeilen"))}
            </div>
          ) : (
            <div className={cn('flex min-w-max pr-6', r.kind === 'add' && 'bg-success/10', r.kind === 'del' && 'bg-danger/10')}>
              <span aria-hidden className="w-12 shrink-0 select-none px-2 text-right text-fg-subtle/80">
                {r.a ?? ''}
              </span>
              <span aria-hidden className="w-12 shrink-0 select-none px-2 text-right text-fg-subtle/80">
                {r.b ?? ''}
              </span>
              <span
                className={cn(
                  'w-5 shrink-0 select-none text-center',
                  r.kind === 'add' ? 'text-success-text' : r.kind === 'del' ? 'text-danger-text' : 'text-fg-subtle',
                )}
              >
                {r.kind === 'add' ? '+' : r.kind === 'del' ? '−' : ' '}
                <span className="sr-only">{r.kind === 'add' ? tr("neu") : r.kind === 'del' ? tr("entfällt") : ''}</span>
              </span>
              <span className={cn('whitespace-pre', r.kind === 'same' ? 'text-fg-muted' : 'text-fg')}>{r.text || ' '}</span>
            </div>
          )}
        </Fragment>
      ))}
    </div>
  )
}
