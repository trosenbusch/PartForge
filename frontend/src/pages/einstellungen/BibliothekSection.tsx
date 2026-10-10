import { t, useI18n } from '@/lib/i18n'
/**
 * Bibliothek: Speicherort und Kennzahlen, Name, Aufteilung der Bibliotheksdateien (mit den echten Dateien),
 * Teilenummern-Schema und Sicherungen (anlegen, wiederherstellen mit starker Bestätigung).
 */
import {
  Archive,
  ArchiveRestore,
  Box,
  CircuitBoard,
  Database,
  DatabaseBackup,
  FileBox,
  FileCode2,
  FileText,
  FolderOpen,
  FolderOutput,
  FolderTree,
  Hash,
  History,
  Plus,
  Shapes,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import {
  useAltiumStatus,
  useBackups,
  useCreateBackup,
  useLibraryFiles,
  useLibraryStatsSummary,
  useRestoreBackup,
  type BackupInfo,
  type LibraryFileInfo,
} from '@/api/settings'
import type { WorkspaceInfo, WorkspaceSettings } from '@/api/system'
import { useCategories } from '@/api/library'
import { Badge, Button, Callout, EmptyState, Field, Input, SegmentedControl, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatBytes, formatDateTime, formatNumber, formatRelativeTime } from '@/lib/format'
import { naturalCompare } from '@/lib/geometry'
import { revealPath, useNativeBridge } from '@/lib/native'
import { NoWorkspace, PathLine, SettingsCard } from './components'
import { setKey, useWorkspaceDraft } from './draft'
import { compilePnFormat, PN_PLACEHOLDERS } from './pnFormat'
import { TypedConfirm } from './TypedConfirm'
import { UnsavedChanges } from './UnsavedChanges'

type LibraryDraft = Pick<WorkspaceSettings, 'name' | 'library_layout' | 'part_number_scheme' | 'internal_pn_format'>

const selectLibrary = (s: WorkspaceSettings): LibraryDraft => ({
  name: s.name,
  library_layout: s.library_layout,
  part_number_scheme: s.part_number_scheme,
  internal_pn_format: s.internal_pn_format,
})
const applyLibrary = (s: WorkspaceSettings, v: LibraryDraft): WorkspaceSettings => ({ ...s, ...v })

export function BibliothekSection() {
  const { t } = useI18n()
  const ws = useWorkspaceDraft(selectLibrary, applyLibrary, { label: t("Bibliothek") })
  if (ws.workspace.isPending) {
    return (
      <div className="flex flex-col gap-5" aria-busy="true">
        <Skeleton className="h-64 rounded-card" />
        <Skeleton className="h-48 rounded-card" />
      </div>
    )
  }
  if (!ws.info || !ws.draft) return <NoWorkspace what={t("Speicherort, Teilenummern und Sicherungen")} />

  const draft = ws.draft
  const set = <K extends keyof LibraryDraft>(key: K, value: LibraryDraft[K]) => ws.setDraft((d) => setKey(d, key, value))
  const pn = compilePnFormat(draft.internal_pn_format)
  const invalid =
    !draft.name.trim()
      ? t("Die Bibliothek braucht einen Namen.")
      : draft.part_number_scheme === 'internal' && !pn.ok
        ? t("Das Nummernformat ist ungültig.")
        : null

  return (
    <div className="flex flex-col gap-5">
      <LocationCard info={ws.info} />

      <SettingsCard icon={<FolderTree />} title={t("Name und Dateien")} description={t("Wie die Bibliothek heißt und wie Symbole und Footprints auf Dateien verteilt werden")}>
        <Field
          label="Name"
          layout="row"
          className="py-4"
          required
          error={!draft.name.trim() ? t("Bitte einen Namen eingeben.") : undefined}
          help={t("Erscheint im Bibliotheks-Umschalter und in der Liste zuletzt geöffneter Bibliotheken.")}
        >
          <Input value={draft.name} onChange={(e) => set('name', e.target.value)} placeholder={t("z. B. Firmenbibliothek")} />
        </Field>
        <Field
          label={t("Bibliotheksdateien")}
          layout="row"
          className="py-4"
          help={
            draft.library_layout === 'grouped'
              ? t("Wenige Dateien, nach Bauteilgruppe bzw. Gehäusefamilie gebündelt – übersichtlich in Altium.")
              : t("Jedes Symbol und jeder Footprint in einer eigenen Datei – ideal für Versionsverwaltung.")
          }
        >
          <div className="flex flex-col gap-3">
            <SegmentedControl<WorkspaceSettings['library_layout']>
              aria-label={t("Bibliotheksdateien")}
              fullWidth
              value={draft.library_layout}
              onValueChange={(v) => set('library_layout', v)}
              options={[
                { value: 'grouped', label: t("Gebündelt") },
                { value: 'per_item', label: t("Je Symbol/Footprint") },
              ]}
            />
            <LayoutPreview layout={draft.library_layout} saved={ws.saved?.library_layout ?? draft.library_layout} />
          </div>
        </Field>
      </SettingsCard>

      <SettingsCard icon={<Hash />} title={t("Teilenummern")} description={t("Der eindeutige Schlüssel jedes Bauteils (Spalte „Part Number“)")}>
        <Field
          label={t("Schema")}
          layout="row"
          className="py-4"
          help={
            draft.part_number_scheme === 'mpn'
              ? t("Die Teilenummer ist die Hersteller-Teilenummer – eindeutig, sprechend und direkt bestellbar.")
              : t("PartForge vergibt fortlaufende interne Nummern je Präfix. Die Hersteller-Teilenummer bleibt ein eigenes Feld.")
          }
        >
          <SegmentedControl<WorkspaceSettings['part_number_scheme']>
            aria-label={t("Teilenummern-Schema")}
            fullWidth
            value={draft.part_number_scheme}
            onValueChange={(v) => set('part_number_scheme', v)}
            options={[
              { value: 'mpn', label: t("Hersteller-Nr. (MPN)") },
              { value: 'internal', label: t("Interne Nummer") },
            ]}
          />
        </Field>
        {draft.part_number_scheme === 'internal' ? (
          <PnFormatEditor value={draft.internal_pn_format} onChange={(v) => set('internal_pn_format', v)} />
        ) : (
          <div className="py-4">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-control bg-surface-2/60 px-3 py-2.5 text-xs text-fg-muted">
              <span className="micro-label">{t("Beispiel")}</span>
              <span className="mono text-fg">RC0603FR-0710KL</span>
              <span aria-hidden>·</span>
              <span className="mono text-fg">GRM188R71H104KA93D</span>
              <span aria-hidden>·</span>
              <span className="mono text-fg">LM2596S-5.0/NOPB</span>
            </div>
          </div>
        )}
        {draft.part_number_scheme !== ws.saved?.part_number_scheme && (
          <div className="py-4">
            <Callout tone="info" title={t("Gilt für neue Bauteile")}>
              {t("Vorhandene Bauteile behalten ihre Teilenummer – Altium speichert sie in platzierten Bauteilen.")}</Callout>
          </div>
        )}
      </SettingsCard>

      <BackupsCard info={ws.info} />

      <UnsavedChanges
        dirty={ws.dirty}
        saving={ws.saving}
        onSave={ws.save}
        onDiscard={ws.reset}
        label={t("Bibliothek")}
        invalid={ws.dirty ? invalid : null}
        root={ws.root}
      />
    </div>
  )
}

// --------------------------------------------------------------------------- Speicherort

function joinPath(root: string, part: string): string {
  return `${root.replace(/[\\/]+$/, '')}\\${part.replace(/^[\\/]+/, '')}`
}

function maskUrl(url: string): string {
  return url.replace(/(\/\/[^:/@]+):[^@]*@/, '$1:•••@')
}

function LocationCard({ info }: { info: WorkspaceInfo }) {
  const { t } = useI18n()
  const stats = useLibraryStatsSummary()
  const status = useAltiumStatus()
  const s = info.settings
  const dblib = status.data?.dblib
  const isSqlite = s.db.kind === 'sqlite'
  // Größe der Datenbankdatei, sobald das Backend sie in der Bibliotheksinfo mitliefert (Wunsch: `db_size`)
  const dbSize = (info as WorkspaceInfo & { db_size?: number | null }).db_size

  const folders: { key: keyof WorkspaceSettings['folders']; label: string; icon: ReactNode }[] = [
    { key: 'symbols', label: t("Symbole"), icon: <Shapes /> },
    { key: 'footprints', label: 'Footprints', icon: <CircuitBoard /> },
    { key: 'models', label: t("3D‑Modelle"), icon: <Box /> },
    { key: 'datasheets', label: t("Datenblätter"), icon: <FileText /> },
    { key: 'backups', label: t("Sicherungen"), icon: <Archive /> },
    { key: 'exports', label: t("Exporte"), icon: <FolderOutput /> },
  ]

  const counts: { label: string; value: number | null | undefined }[] = [
    { label: t("Bauteile"), value: stats.data?.total_parts },
    { label: t("Kategorien"), value: stats.data?.category_count },
    { label: t("Symbole"), value: stats.data?.symbols.total },
    { label: 'Footprints', value: stats.data?.footprints.total },
    { label: t("Datenblätter"), value: stats.data?.datasheets },
  ]

  return (
    <SettingsCard
      flush
      icon={<FolderOpen />}
      title={t("Speicherort")}
      description={t("Alles liegt in einem Ordner – verschieben, sichern oder versionieren Sie ihn als Ganzes.")}
      aside={
        <Badge variant="outline" size="md">
          <Database />
          {isSqlite ? `SQLite · ${s.db.journal_mode === 'wal' ? 'WAL' : 'Journal'}` : 'PostgreSQL'}
        </Badge>
      }
    >
      <div className="@container">
        <dl className="grid grid-cols-3 border-b border-line @[40rem]:grid-cols-5">
          {counts.map((c, i) => (
            <div key={c.label} className={cn('flex flex-col gap-0.5 px-5 py-3.5', i > 0 && 'border-l border-line', i === 3 && 'border-l-0 @[40rem]:border-l')}>
              <dt className="text-2xs text-fg-subtle">{c.label}</dt>
              <dd className="mono tabular text-h3 leading-tight text-fg">
                {c.value === undefined ? <Skeleton className="mt-1 h-5 w-10" /> : c.value === null ? '–' : formatNumber(c.value)}
              </dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-col divide-y divide-line px-5">
          <PathLine icon={<FolderOpen />} label={t("Bibliotheksordner")} path={info.root} what={t("Bibliotheksordner")} />
          {isSqlite ? (
            <PathLine
              icon={<Database />}
              label={t("Datenbank")}
              hint={
                <>
                  {s.db.journal_mode === 'wal' ? t("SQLite im WAL-Modus – Altium liest parallel") : 'SQLite'}
                  {typeof dbSize === 'number' && <span className="mono"> · {formatBytes(dbSize)}</span>}
                </>
              }
              path={info.sqlite_path}
              what={t("Datenbankdatei")}
            />
          ) : (
            <PathLine icon={<Database />} label={t("Datenbank")} hint={t("PostgreSQL-Server")} path={maskUrl(s.db.postgres_url ?? '–')} reveal={false} what={t("Adresse")} />
          )}
          <PathLine
            icon={<FileCode2 />}
            label={t("DbLib für Altium")}
            hint={
              dblib ? (
                <span className={dblib.exists && dblib.up_to_date ? 'text-success-text' : 'text-warning-text'}>
                  {!dblib.exists ? t("fehlt") : dblib.up_to_date ? t("aktuell") : t("veraltet")}
                </span>
              ) : undefined
            }
            path={info.dblib_path}
            what="DbLib"
          />
        </div>
        <div className="border-t border-line px-3 pb-3 pt-3.5">
          <div className="micro-label mb-1.5 px-2">{t("Unterordner")}</div>
          <ul className="grid grid-cols-2 gap-x-1 @[34rem]:grid-cols-3">
            {folders.map((f) => (
              <li key={f.key} className="min-w-0">
                <FolderRow icon={f.icon} label={f.label} folder={s.folders[f.key]} path={joinPath(info.root, s.folders[f.key])} />
              </li>
            ))}
          </ul>
        </div>
      </div>
    </SettingsCard>
  )
}

/** Unterordner als randlose Zeile: Klick öffnet den Ordner im Explorer (außerhalb des Desktop-Programms: Pfad kopieren) */
function FolderRow({ icon, label, folder, path }: { icon: ReactNode; label: string; folder: string; path: string }) {
  const { t } = useI18n()
  const bridge = useNativeBridge()
  const action = bridge.canRevealPath || bridge.canOpenPath ? t("Im Explorer zeigen") : t("Pfad kopieren")
  return (
    <Tooltip content={`${action}: ${path}`}>
      <button
        type="button"
        onClick={() => void revealPath(path, { what: t("Ordner „{0}“", { "0": label }) })}
        className="group/ft flex w-full min-w-0 items-center gap-2.5 rounded-control px-2 py-1.5 text-left outline-none transition-colors hover:bg-surface-2/70 focus-ring-inset"
      >
        <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-md bg-surface-2 text-fg-muted transition-colors group-hover/ft:text-fg [&_svg]:size-3.5">
          {icon}
        </span>
        <span className="min-w-0">
          <span className="block text-xs font-medium text-fg">{label}</span>
          <span className="mono block truncate text-2xs text-fg-subtle">{folder}\</span>
          {/* Name = sichtbarer Text (Ordner) + was der Klick tut */}
          <span className="sr-only"> – {action}</span>
        </span>
      </button>
    </Tooltip>
  )
}

// --------------------------------------------------------------------------- Aufteilung (Vorschau)

interface TreeFile {
  name: string
  note: string
}

/**
 * Beispiel, wenn die echten Dateien fehlen oder die Aufteilung gerade umgestellt wird – wie der Writer die Dateien
 * benennt (`partforge/altium/libwriter.py`: Symbole nach Bauteilgruppe, Footprints nach Gehäusefamilie).
 */
const LAYOUT_EXAMPLE: Record<WorkspaceSettings['library_layout'], { folder: string; files: TreeFile[] }[]> = {
  grouped: [
    {
      folder: 'Symbols',
      files: [
        { name: 'PF_Passives.SchLib', note: 'Widerstände, Kondensatoren, Induktivitäten, Ferrite' },
        { name: 'PF_ICs.SchLib', note: 'Datenwandler, ICs, Optokoppler' },
      ],
    },
    {
      folder: 'Footprints',
      files: [
        { name: 'PF_CHIP.PcbLib', note: '0402, 0603, 0805 …' },
        { name: 'PF_GULLWING.PcbLib', note: 'SOIC, MSOP, TSSOP …' },
      ],
    },
  ],
  per_item: [
    { folder: 'Symbols', files: [{ name: 'Resistor.SchLib', note: '' }, { name: 'Diode.SchLib', note: '' }] },
    { folder: 'Footprints', files: [{ name: 'RESC1608X50N.PcbLib', note: '' }, { name: 'SOIC127P600X175-8N.PcbLib', note: '' }] },
  ],
}

const FILES_PER_FOLDER = 3

/** Echte Dateien der Bibliothek nach Ordner (größte zuerst) */
function realTree(files: LibraryFileInfo[]): { folder: string; files: TreeFile[]; more: number }[] {
  const groups = new Map<string, LibraryFileInfo[]>()
  for (const f of files) {
    if (!f.exists) continue
    const parts = f.rel.split(/[\\/]+/)
    const folder = parts.length > 1 ? parts.slice(0, -1).join('\\') : '.'
    groups.set(folder, [...(groups.get(folder) ?? []), f])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => naturalCompare(a, b))
    .map(([folder, list]) => {
      const sorted = [...list].sort((a, b) => (b.components ?? 0) - (a.components ?? 0) || naturalCompare(a.rel, b.rel))
      return {
        folder,
        files: sorted.slice(0, FILES_PER_FOLDER).map((f) => ({
          name: baseName(f.rel),
          note:
            f.components === null || f.components === undefined
              ? ''
              : `${formatNumber(f.components)} ${f.kind === 'schlib' ? (f.components === 1 ? 'Symbol' : t("Symbole")) : f.components === 1 ? 'Footprint' : 'Footprints'}`,
        })),
        more: Math.max(0, sorted.length - FILES_PER_FOLDER),
      }
    })
}

function LayoutPreview({ layout, saved }: { layout: WorkspaceSettings['library_layout']; saved: WorkspaceSettings['library_layout'] }) {
  const { t } = useI18n()
  const changed = layout !== saved
  const files = useLibraryFiles(!changed)
  const real = !changed && files.data && files.data.some((f) => f.exists) ? realTree(files.data) : null
  const tree = real ?? LAYOUT_EXAMPLE[layout].map((g) => ({ ...g, more: 0 }))
  const caption = real ? t("Dateien dieser Bibliothek") : changed ? t("So werden neue Dateien abgelegt (Beispiel)") : t("Beispiel")

  return (
    <div className="rounded-control bg-surface-2/50 px-3 py-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <span className="micro-label">{caption}</span>
        {!changed && files.isFetching && !files.data && <Skeleton className="h-3 w-16" />}
      </div>
      <ul className="mono flex flex-col gap-0.5 text-2xs leading-5" aria-label={caption}>
        {tree.map((group) => (
          <li key={group.folder}>
            <div className="flex items-center gap-1.5 text-fg-muted">
              <FolderOpen aria-hidden className="size-3 text-fg-subtle" />
              {group.folder}\
            </div>
            <ul>
              {group.files.map((f) => (
                <li key={f.name} className="flex min-w-0 items-baseline gap-2 pl-4 text-fg">
                  <FileBox aria-hidden className="size-3 shrink-0 translate-y-0.5 text-fg-subtle" />
                  <span className="min-w-0 break-all">{f.name}</span>
                  {f.note && <span className="ml-auto shrink-0 pl-2 font-sans text-fg-subtle">{t(f.note)}</span>}
                </li>
              ))}
              {(group.more > 0 || (!real && layout === 'per_item')) && (
                <li className="pl-4 font-sans text-fg-subtle">
                  {group.more > 0 ? t("… und {0} weitere", { "0": formatNumber(group.more) }) : '…'}
                </li>
              )}
            </ul>
          </li>
        ))}
      </ul>
      {changed && (
        <p className="mt-2 border-t border-line pt-2 text-2xs leading-snug text-fg-muted">
          {t("Gilt für neu geschriebene Symbole und Footprints. Vorhandene Dateien bleiben, bis sie neu geschrieben werden.")}</p>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- Interne Nummern

function PnFormatEditor({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { t } = useI18n()
  const inputRef = useRef<HTMLInputElement>(null)
  const categories = useCategories()
  const compiled = compilePnFormat(value)
  const samples = (categories.data ?? [])
    .filter((c, i, list) => list.findIndex((o) => o.prefix === c.prefix) === i)
    .slice(0, 4)
  const examples = samples.length ? samples : [{ table: 'Resistors', prefix: 'R', label: t("Widerstände") }]

  const insert = (token: string) => {
    const el = inputRef.current
    const start = el?.selectionStart ?? value.length
    const end = el?.selectionEnd ?? value.length
    const next = value.slice(0, start) + token + value.slice(end)
    onChange(next)
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(start + token.length, start + token.length)
    })
  }

  return (
    <Field
      label={t("Nummernformat")}
      layout="row"
      className="py-4"
      error={compiled.error ?? undefined}
      help={t("Platzhalter: {prefix} = Bezeichner-Präfix der Kategorie, {counter} = fortlaufender Zähler je Präfix, {table} = Tabellenname.")}
    >
      <div className="flex flex-col gap-2.5">
        <Input ref={inputRef} mono value={value} onChange={(e) => onChange(e.target.value)} placeholder="{prefix}-{counter:06d}" />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("Platzhalter einfügen")}>
          {PN_PLACEHOLDERS.map((p) => (
            <Tooltip key={p.token} content={t("{0} (z. B. {1})", { "0": t(p.label), "1": p.example })}>
              <button
                type="button"
                onClick={() => insert(p.token)}
                className="mono inline-flex h-6 items-center gap-1 rounded-md border border-line bg-surface-2 px-1.5 text-2xs text-fg-muted outline-none transition-colors hover:border-line-strong hover:text-fg focus-ring"
              >
                <Plus aria-hidden className="size-3" />
                {p.token}
              </button>
            </Tooltip>
          ))}
        </div>
        <div className="rounded-control bg-surface-2/60 px-3 py-2.5" aria-live="polite">
          <div className="micro-label mb-1.5">{t("Vorschau")}</div>
          <ul className="flex flex-col gap-1">
            {examples.map((c) => (
              <li key={c.table} className="flex min-w-0 items-baseline justify-between gap-3 text-xs">
                <span className="truncate text-fg-muted">{c.label}</span>
                <span className={cn('mono shrink-0', compiled.ok ? 'text-fg' : 'text-fg-subtle line-through')}>
                  {compiled.render(c.prefix || 'P', 1, c.table)}
                  <span className="text-fg-subtle">, {compiled.render(c.prefix || 'P', 2, c.table)} …</span>
                </span>
              </li>
            ))}
          </ul>
          {!compiled.ok && (
            <p className="mt-1.5 text-2xs text-fg-subtle">{t("Ungültige Formate ersetzt PartForge durch")} {'{prefix}-{counter:06d}'}.</p>
          )}
        </div>
      </div>
    </Field>
  )
}

// --------------------------------------------------------------------------- Sicherungen

const REASONS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^manuell$/i, () => t("Manuell")],
  [/^vor_loeschen_(\d+)_bauteile$/i, (m) => t("Vor dem Löschen von {0} Bauteilen", { "0": formatNumber(Number(m[1])) })],
  [/^vor_loeschen_(.+)$/i, (m) => t("Vor dem Löschen der Kategorie „{0}“", { "0": m[1].replace(/_/g, ' ') })],
  [/^vor_feld_entfernen_(.+)$/i, (m) => t("Vor dem Entfernen eines Felds in „{0}“", { "0": m[1].replace(/_/g, ' ') })],
  [/^vor_serie$/i, () => t("Vor dem Anlegen einer Serie")],
  [/^vor_import$/i, () => t("Vor einem Import")],
  [/^vor_wiederherstellung_roh$/i, () => t("Vor dem Wiederherstellen (Rohkopie)")],
  [/^vor_wiederherstellung$/i, () => t("Vor dem Wiederherstellen")],
]

function reasonText(reason: string): string {
  for (const [re, fn] of REASONS) {
    const m = reason.match(re)
    if (m) return fn(m)
  }
  const text = reason.replace(/_/g, ' ').trim()
  return text ? text[0].toUpperCase() + text.slice(1) : t("Sicherung")
}

/** Automatische Sicherungen (vor riskanten Aktionen) – eigene Notizen zählen nicht dazu */
function isAutomatic(reason: string): boolean {
  return /^vor_(loeschen|feld_entfernen|serie|import|wiederherstellung)/i.test(reason)
}

function BackupsCard({ info }: { info: WorkspaceInfo }) {
  const { t } = useI18n()
  const backups = useBackups()
  const create = useCreateBackup()
  const restore = useRestoreBackup()
  const [note, setNote] = useState('')
  const [target, setTarget] = useState<BackupInfo | null>(null)
  const isSqlite = info.settings.db.kind === 'sqlite'
  const folder = joinPath(info.root, info.settings.folders.backups)

  const createNow = () =>
    create.mutate(note.trim() || 'manuell', {
      onSuccess: (b) => {
        setNote('')
        toast.success(t("Sicherung erstellt"), { description: `${b.name} · ${formatBytes(b.size)}` })
      },
    })

  const list = backups.data ?? []

  return (
    <SettingsCard
      flush
      icon={<DatabaseBackup />}
      title={t("Sicherungen")}
      description={t("Vollständige Kopien der Datenbank im Ordner „Backups“ – die neuesten 30 bleiben erhalten.")}
      aside={
        <Button size="sm" variant="ghost" leftIcon={<FolderOpen />} onClick={() => void revealPath(folder, { what: t("Sicherungsordner") })}>
          {t("Ordner")}</Button>
      }
    >
      {!isSqlite ? (
        <div className="p-5">
          <Callout tone="info" title={t("Sicherungen übernimmt der Datenbankserver")}>
            {t("Für PostgreSQL-Bibliotheken erstellt der Server die Sicherungen (z. B. mit pg_dump). PartForge sichert nur SQLite-Bibliotheken.")}</Callout>
        </div>
      ) : (
        <>
          <form
            className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3.5"
            onSubmit={(e) => {
              e.preventDefault()
              e.stopPropagation()
              createNow()
            }}
          >
            <Input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder={t("Notiz (optional), z. B. vor Umbau Kondensatoren")}
              aria-label={t("Notiz zur Sicherung")}
              containerClassName="min-w-56 flex-1"
              maxLength={60}
            />
            <Button type="submit" variant="secondary" leftIcon={<DatabaseBackup />} loading={create.isPending}>
              {t("Jetzt sichern")}</Button>
          </form>

          {backups.isPending ? (
            <div className="flex flex-col gap-2 p-5" aria-busy="true">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : backups.isError ? (
            <div className="p-5">
              <Callout tone="warning" title={t("Sicherungen konnten nicht gelesen werden")}>
                {errorMessage(backups.error)}
              </Callout>
            </div>
          ) : list.length === 0 ? (
            <EmptyState
              size="sm"
              icon={<History />}
              title={t("Noch keine Sicherungen")}
              description={t("PartForge sichert automatisch vor riskanten Aktionen – Kategorie löschen, Feld entfernen, Import, Serie, Wiederherstellen.")}
            />
          ) : (
            <ul className="max-h-[22rem] divide-y divide-line overflow-y-auto" aria-label={t("Sicherungen")}>
              {list.map((b, i) => (
                <li key={b.name} className="group/bk flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-surface-2/50">
                  <span
                    aria-hidden
                    className={cn(
                      'flex size-7 shrink-0 items-center justify-center rounded-control [&_svg]:size-3.5',
                      isAutomatic(b.reason) ? 'bg-surface-2 text-fg-subtle' : 'bg-surface-3 text-fg-muted',
                    )}
                  >
                    {isAutomatic(b.reason) ? <History /> : <Archive />}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex min-w-0 items-baseline gap-2">
                      <span className="truncate text-ui font-medium text-fg">{reasonText(b.reason)}</span>
                      {i === 0 && <Badge variant="neutral">{t("neueste")}</Badge>}
                    </div>
                    <div className="flex items-center gap-1.5 text-2xs text-fg-subtle">
                      <time dateTime={b.created} title={formatDateTime(b.created)}>
                        {formatDateTime(b.created)}
                      </time>
                      <span aria-hidden>·</span>
                      <span>{formatRelativeTime(b.created)}</span>
                      <span aria-hidden>·</span>
                      <span className="mono tabular">{formatBytes(b.size)}</span>
                    </div>
                  </div>
                  <Button size="sm" variant="ghost" leftIcon={<ArchiveRestore />} onClick={() => setTarget(b)}>
                    {t("Wiederherstellen …")}</Button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      <TypedConfirm
        open={target !== null}
        onOpenChange={(o) => !o && setTarget(null)}
        icon={<ArchiveRestore />}
        title={t("Sicherung wiederherstellen?")}
        description={
          target ? (
            <>
              {t("Die Datenbank wird auf den Stand vom")} <strong className="font-medium text-fg">{formatDateTime(target.created)}</strong>{' '}
              {t("zurückgesetzt (")}{reasonText(target.reason)}).
            </>
          ) : undefined
        }
        phrase={t('wiederherstellen')}
        confirmLabel={t("Wiederherstellen")}
        onConfirm={async () => {
          if (!target) return
          await restore.mutateAsync(target.name)
          toast.success(t("Sicherung wiederhergestellt"), {
            description: t("Der vorherige Stand liegt als „Vor dem Wiederherstellen“ in den Sicherungen."),
          })
        }}
      >
        <ul className="flex flex-col gap-1.5 text-xs leading-snug text-fg-muted">
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-danger" />
            {t("Alle Änderungen an Bauteilen, Kategorien und Feldern nach diesem Zeitpunkt gehen verloren.")}</li>
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
            {t("Der aktuelle Stand wird vorher automatisch gesichert – Sie können jederzeit zurück.")}</li>
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
            {t("Danach gleicht PartForge die Symbol- und Footprint-Dateien mit dem wiederhergestellten Stand ab und schreibt Fehlendes neu (Hintergrundjob); ein laufendes Altium liest die Datenbank neu ein.")}</li>
        </ul>
      </TypedConfirm>
    </SettingsCard>
  )
}
