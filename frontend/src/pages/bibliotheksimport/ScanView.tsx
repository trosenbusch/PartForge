/**
 * Ein eingelesener Scan: Übersicht und Hinweise, links der Dateibaum (Auswahl, Filter, Bauteile), rechts Optionen mit
 * Live-Zusammenfassung und Start sowie die Vorschau des gewählten bzw. überfahrenen Bauteils. Die Auswahl gilt je Scan
 * (die Seite rendert die Ansicht mit `key={scan.id}`); vorausgewählt sind alle lesbaren Dateien. Für einen anderen
 * Zielordner als den Vorschlag holt die Ansicht den Scan für diesen Ordner (`GET …/scans/{id}?target=`).
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { useMemo, useState, type ReactNode } from 'react'
import { libImportApi, libImportKeys, type ImportOptions, type ImportScan } from '@/api/libimport'
import { useElementSize } from '@/components/preview/useElementSize'
import { Callout, Card, EmptyState } from '@/components/ui'
import { FileTree, type PreviewTarget } from './FileTree'
import { componentKey, indexScan, planImport, retarget, safeFolderName } from './model'
import { OptionsCard, type ImportOptionsState } from './OptionsCard'
import { PreviewCard } from './PreviewCard'
import { ScanNotes, ScanOverview } from './ScanOverview'
import { useDebounced } from './useDebounced'

/** Ab dieser Breite des Dateibaums (px) steht die Vorschau als Spalte rechts in der Liste */
const PREVIEW_BESIDE = 780

export interface ScanViewProps {
  scan: ImportScan
  /** Ordner der Symbole bzw. Footprints in der Bibliothek */
  bases: { symbols: string; footprints: string }
  /** Import starten (`folder` = bereinigter Zielordner) */
  onStart: (options: ImportOptions, folder: string) => void
  starting: boolean
  startError: ReactNode
  /** Grund, warum gerade nicht importiert werden kann */
  blocked: string | null
}

export function ScanView({ scan: proposed, bases, onStart, starting, startError, blocked }: ScanViewProps) {
  const [options, setOptions] = useState<ImportOptionsState>(() => ({ target: proposed.name, replace: false, extract3d: false, convert: false }))
  const folder = safeFolderName(options.target.trim() || proposed.name)
  /** anderer Zielordner als der Vorschlag des Scans */
  const custom = folder.toLowerCase() !== proposed.name.toLowerCase()
  // Für einen anderen Zielordner rechnet das Backend Ziele, vorhandene Dateien und Namenszustände neu (exakt);
  // bis die Antwort da ist, schätzt die Seite (schon importierte Namen gelten dann als vergeben)
  const wanted = useDebounced(custom ? folder : null, 400)
  const targeted = useQuery({
    queryKey: libImportKeys.scan(proposed.id, wanted),
    queryFn: ({ signal }) => libImportApi.getScan(proposed.id, signal, wanted),
    enabled: wanted !== null,
    staleTime: Infinity,
    retry: false,
    placeholderData: keepPreviousData,
  })
  const exact = custom && wanted === folder && targeted.data?.id === proposed.id && !targeted.isPlaceholderData
  const scan = exact && targeted.data ? targeted.data : proposed
  /** Zustände sind für den gewählten Ordner nur geschätzt */
  const retargeted = custom && !exact
  const index = useMemo(() => indexScan(scan), [scan])
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => index.defaultSelection)
  const [pinned, setPinned] = useState<PreviewTarget | null>(null)
  const [hovered, setHovered] = useState<PreviewTarget | null>(null)
  /** Breite des Dateibaums: ab {@link PREVIEW_BESIDE} px steht die Vorschau rechts in der Liste, sonst unter den Optionen */
  const [treeRef, treeSize] = useElementSize<HTMLDivElement>()
  const previewBeside = treeSize.width >= PREVIEW_BESIDE

  const plan = useMemo(() => planImport(scan, selected, { retargeted, replace: options.replace }), [scan, selected, retargeted, options.replace])
  const shown = hovered ?? pinned

  const onPreview = (target: PreviewTarget | null, how: 'pin' | 'hover') => {
    if (how === 'pin') {
      setPinned(target)
      setHovered(null)
    } else setHovered(target)
  }

  const start = () => {
    const files = scan.files.filter((f) => !f.problem && selected.has(f.rel)).map((f) => f.rel)
    onStart(
      {
        scan_id: scan.id,
        // alle Dateien gewählt (und keine unlesbare dabei) → `null` statt einer langen Liste
        files: index.unreadable === 0 && files.length === scan.files.length ? null : files,
        target: folder,
        replace: options.replace && plan.changed > 0,
        extract_3d: options.extract3d && plan.footprints > 0,
        convert: options.convert,
      },
      folder,
    )
  }

  const importable = scan.new + scan.imported + scan.duplicates

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      className="flex flex-col gap-4"
    >
      <ScanOverview scan={scan} unreadable={index.unreadable} />
      <ScanNotes notes={scan.notes} />
      {scan.files.length === 0 ? (
        <Card>
          <EmptyState
            illustration="search-empty"
            title="Keine Bibliotheken gefunden"
            description="In dieser Quelle liegen keine SchLib-, PcbLib- oder IntLib-Dateien – Ordner werden mit allen Unterordnern durchsucht. Bibliothekspakete (LibPkg) und ZIP-Archive bitte direkt als Datei wählen."
          />
        </Card>
      ) : (
        <>
          {importable === 0 && scan.taken > 0 && (
            <Callout tone="warning" title="Nichts zu übernehmen">
              Alle Namen dieser Quelle sind in der Bibliothek schon vergeben – Altium findet Symbole und Footprints nur über ihren Namen,
              deshalb übernimmt PartForge keinen zweiten mit demselben Namen.
            </Callout>
          )}
          <div className="grid grid-cols-[minmax(0,1fr)_18rem] items-start gap-4 @[76rem]:grid-cols-[minmax(0,1fr)_22rem]">
            <div ref={treeRef} className="min-w-0">
              <FileTree
                index={index}
                selected={selected}
                onSelectedChange={setSelected}
                plan={plan}
                retargeted={retargeted}
                targetOf={(file) => (exact ? file.target : retarget(file.target, proposed.name, folder))}
                replace={options.replace}
                previewKey={pinned ? componentKey(pinned.file.rel, pinned.component.name) : null}
                onPreview={onPreview}
                side={previewBeside ? <PreviewCard scanId={scan.id} target={shown} pinned={!hovered} variant="pane" /> : undefined}
              />
            </div>
            {/* bleibt beim Blättern neben der Liste; ist das Fenster niedriger als Optionen und Vorschau, scrollt sie selbst */}
            <aside
              aria-label="Optionen und Vorschau"
              className="sticky top-[calc(var(--pf-topbar-height)+0.75rem)] -mx-1 -mb-3 flex max-h-[calc(100dvh-var(--pf-topbar-height)-var(--pf-dock-reserve)-1.5rem)] min-w-0 flex-col gap-4 overflow-y-auto overscroll-contain px-1 pb-3 [scrollbar-width:thin]"
            >
              <OptionsCard
                scan={scan}
                plan={plan}
                options={options}
                onOptionsChange={(patch) => setOptions((o) => ({ ...o, ...patch }))}
                folder={folder}
                retargeted={custom}
                approximate={retargeted}
                bases={bases}
                onStart={start}
                starting={starting}
                startError={startError}
                blocked={blocked}
              />
              {!previewBeside && <PreviewCard scanId={scan.id} target={shown} pinned={!hovered} />}
            </aside>
          </div>
        </>
      )}
    </motion.div>
  )
}
