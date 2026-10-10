import { useI18n } from '@/lib/i18n'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useSettings, useWorkspace } from '@/api/system'
import { Badge } from '@/components/ui'
import { useDroppedFiles } from '../stores'

function hasFiles(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes('Files')
}

function isPdf(file: File): boolean {
  return file.type === 'application/pdf' || /\.pdf$/i.test(file.name)
}

function isTextTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target instanceof HTMLTextAreaElement) return true
  return target instanceof HTMLInputElement && !['checkbox', 'radio', 'button', 'submit', 'range', 'color', 'file'].includes(target.type)
}

/**
 * Fensterweite Drop-Zone für Datenblätter: PDF irgendwo ins Fenster ziehen → Vollbild-Overlay →
 * Dateien landen im Dropped-Files-Store → Navigation zu /import.
 *
 * Schutz: Das Fenster darf **nie** zu einer abgelegten Datei oder einem Link navigieren (das Desktop-Fenster
 * hat keinen Zurück-Knopf). Erlaubt bleiben nur Drops auf Textfelder (Text) und auf eigene Drop-Zonen
 * (die `preventDefault()` selbst aufrufen). Ziehvorgänge, die *in* der Seite beginnen (Bilder, Zeilen),
 * zeigen kein Overlay. Seiten mit eigener Drop-Zone unterdrücken das Overlay mit `useSuppressGlobalDrop()`.
 */
export function GlobalDropOverlay() {
  const { t: tr } = useI18n()
  const [dragging, setDragging] = useState(false)
  const [count, setCount] = useState(0)
  const depth = useRef(0)
  const internalDrag = useRef(false)
  const navigate = useNavigate()
  const suppressed = useDroppedFiles((s) => s.suppressCount > 0)
  const hasWorkspace = Boolean(useWorkspace().data)
  const aiEnabled = useSettings().data?.settings.ai.enabled ?? true

  useEffect(() => {
    const reset = () => {
      depth.current = 0
      setDragging(false)
    }
    const wantsOverlay = (e: DragEvent) => hasFiles(e) && !internalDrag.current && !suppressed
    const onDragStart = () => {
      internalDrag.current = true
    }
    const onDragEnd = () => {
      internalDrag.current = false
    }
    const onEnter = (e: DragEvent) => {
      if (!wantsOverlay(e)) return
      e.preventDefault()
      depth.current += 1
      setCount(e.dataTransfer?.items?.length ?? 0)
      setDragging(true)
    }
    const onOver = (e: DragEvent) => {
      if (e.defaultPrevented) return // eigene Drop-Zone hat übernommen
      if (wantsOverlay(e)) {
        e.preventDefault()
        if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
        return
      }
      if (!hasFiles(e) && isTextTarget(e.target)) return // Text in ein Eingabefeld ziehen: Standardverhalten
      // alles andere (Dateien neben einer Seiten-Drop-Zone, Links, Bilder): Ablegen hier nicht erlaubt
      e.preventDefault()
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'none'
    }
    const onLeave = (e: DragEvent) => {
      if (!wantsOverlay(e)) return
      depth.current = Math.max(0, depth.current - 1)
      const outside =
        e.relatedTarget === null &&
        (e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight)
      if (depth.current === 0 || outside) reset()
    }
    const onDrop = (e: DragEvent) => {
      const overlay = wantsOverlay(e)
      internalDrag.current = false
      if (e.defaultPrevented) return
      if (!overlay) {
        if (!hasFiles(e) && isTextTarget(e.target)) return
        e.preventDefault() // nie zur Datei/zum Link navigieren
        return
      }
      e.preventDefault()
      reset()
      const files = Array.from(e.dataTransfer?.files ?? [])
      const pdfs = files.filter(isPdf)
      if (pdfs.length === 0) {
        toast.error(tr("Keine PDF-Datei erkannt"), {
          description: tr("Bitte ein Datenblatt im PDF-Format ablegen."),
        })
        return
      }
      const added = useDroppedFiles.getState().add(pdfs)
      const skipped = files.length - pdfs.length
      const title =
        pdfs.length === 1 ? tr("„{0}“ übernommen", { "0": String(pdfs[0].name) }) : tr("{0} Datenblätter übernommen", { "0": String(pdfs.length) })
      if (!hasWorkspace) {
        toast.warning(title, { description: tr("Bitte zuerst eine Bibliothek öffnen oder anlegen – dann geht es weiter.") })
        return
      }
      toast.success(title, {
        description:
          (added.length < pdfs.length ? tr("Bereits vorhandene Dateien wurden übersprungen. ") : '') +
          (skipped > 0 ? tr("{0} Nicht-PDF-Datei(en) ignoriert. ", { "0": String(skipped) }) : '') +
          tr("Die Analyse startet auf der Import-Seite."),
      })
      navigate('/import')
    }
    window.addEventListener('dragstart', onDragStart)
    window.addEventListener('dragend', onDragEnd)
    window.addEventListener('dragenter', onEnter)
    window.addEventListener('dragover', onOver)
    window.addEventListener('dragleave', onLeave)
    window.addEventListener('drop', onDrop)
    return () => {
      window.removeEventListener('dragstart', onDragStart)
      window.removeEventListener('dragend', onDragEnd)
      window.removeEventListener('dragenter', onEnter)
      window.removeEventListener('dragover', onOver)
      window.removeEventListener('dragleave', onLeave)
      window.removeEventListener('drop', onDrop)
    }
  }, [suppressed, hasWorkspace, navigate, tr])

  return (
    <AnimatePresence>
      {dragging && !suppressed && (
        <motion.div
          key="drop"
          aria-live="polite"
          className="pointer-events-none fixed inset-0 z-drop flex items-center justify-center bg-[color-mix(in_oklab,var(--pf-bg)_84%,transparent)] backdrop-blur-md"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.15 } }}
          transition={{ duration: 0.18 }}
        >
          {/* Funken-Schein im Hintergrund (KI-Analyse) */}
          <div
            aria-hidden
            className="absolute left-1/2 top-1/2 size-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,#818cf8_14%,transparent),transparent)]"
          />
          <div aria-hidden className="dot-grid mask-radial absolute inset-0 opacity-60" />
          {/* laufender Rahmen */}
          <svg aria-hidden className="absolute inset-4 h-[calc(100%-32px)] w-[calc(100%-32px)] overflow-visible">
            <defs>
              <linearGradient id="dropFrame" x1="0" y1="0" x2="1" y2="1">
                <stop offset="0" stopColor="#38BDF8" />
                <stop offset="0.5" stopColor="#818CF8" />
                <stop offset="1" stopColor="#C084FC" />
              </linearGradient>
            </defs>
            <rect
              x="1"
              y="1"
              rx="22"
              style={{ width: 'calc(100% - 2px)', height: 'calc(100% - 2px)' }}
              fill="none"
              stroke="url(#dropFrame)"
              strokeOpacity="0.8"
              strokeWidth="2"
              strokeDasharray="12 12"
              className="animate-dash"
            />
          </svg>

          <motion.div
            className="relative flex flex-col items-center text-center"
            initial={{ scale: 0.94, y: 12 }}
            animate={{ scale: 1, y: 0 }}
            transition={{ type: 'spring', stiffness: 360, damping: 26 }}
          >
            <ScanningDocument />
            <h2 className="mt-9 text-h1 font-semibold tracking-[-0.025em] text-fg">
              {tr("Datenblatt loslassen ")}<span className="text-gradient-spark">{tr("zum Analysieren")}</span>
            </h2>
            <p className="mt-2 max-w-lg text-sm leading-relaxed text-fg-muted">
              {count > 1 ? tr("{0} Dateien", { "0": String(count) }) : tr("PDF-Datei")} {tr(" ablegen – Parameter, Pinbelegung und Gehäusemaße werden erkannt und als Vorschlag für ein vollständiges Bauteil aufbereitet.")}</p>
            <div className="mt-5 flex items-center gap-2">
              <Badge variant="spark" size="md">
                <Sparkles />
                {tr("KI-Extraktion")}</Badge>
              <Badge size="md">Parameter</Badge>
              <Badge size="md">Symbol</Badge>
              <Badge size="md">Footprint</Badge>
              <Badge size="md">{tr("3D-Modell")}</Badge>
            </div>
            {!aiEnabled && (
              <p className="mt-4 text-xs text-fg-subtle">
                {tr("KI ist ausgeschaltet – das Datenblatt wird abgelegt und kann von Hand ausgewertet werden.")}</p>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Animiertes Datenblatt mit Scan-Strahl und Funken. */
function ScanningDocument() {
  useI18n()
  const reduce = useReducedMotion()
  return (
    <motion.div
      className="relative"
      animate={reduce ? undefined : { y: [0, -8, 0] }}
      transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
    >
      <div
        aria-hidden
        className="absolute -inset-12 rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,#818cf8_30%,transparent),transparent)] blur-xl"
      />
      <svg width="190" height="232" viewBox="0 0 190 232" fill="none" className="relative" aria-hidden>
        <defs>
          <linearGradient id="dropMark" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#38BDF8" />
            <stop offset="0.5" stopColor="#818CF8" />
            <stop offset="1" stopColor="#C084FC" />
          </linearGradient>
          <linearGradient id="dropBeam" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#38BDF8" stopOpacity="0" />
            <stop offset="0.3" stopColor="#38BDF8" />
            <stop offset="0.7" stopColor="#C084FC" />
            <stop offset="1" stopColor="#C084FC" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="dropBeamGlow" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#818CF8" stopOpacity="0" />
            <stop offset="1" stopColor="#818CF8" stopOpacity="0.28" />
          </linearGradient>
          <clipPath id="dropPage">
            <path d="M22 8h112l40 40v172a8 8 0 0 1-8 8H22a8 8 0 0 1-8-8V16a8 8 0 0 1 8-8Z" />
          </clipPath>
        </defs>
        {/* Blatt */}
        <path
          d="M22 8h112l40 40v172a8 8 0 0 1-8 8H22a8 8 0 0 1-8-8V16a8 8 0 0 1 8-8Z"
          fill="var(--pf-surface)"
          stroke="var(--pf-line-strong)"
          strokeWidth="1.5"
        />
        <path d="M134 8v32a8 8 0 0 0 8 8h32" fill="var(--pf-surface-2)" stroke="var(--pf-line-strong)" strokeWidth="1.5" />
        {/* Kopf */}
        <rect x="30" y="26" width="64" height="9" rx="3" fill="var(--pf-fg)" opacity="0.75" />
        <rect x="30" y="41" width="92" height="5" rx="2.5" fill="var(--pf-fg-subtle)" opacity="0.5" />
        {/* Pinout-Skizze */}
        <g stroke="var(--pf-fg-muted)" strokeWidth="1.5" strokeLinecap="round">
          <rect x="40" y="64" width="38" height="50" rx="4" fill="var(--pf-surface-2)" />
          {[72, 84, 96, 108].map((y) => (
            <g key={y}>
              <path d={`M30 ${y}h10`} />
              <path d={`M78 ${y}h10`} />
            </g>
          ))}
        </g>
        <circle cx="47" cy="71" r="2.4" fill="var(--pf-spark-a)" />
        {/* Tabelle */}
        <g opacity="0.65">
          {[0, 1, 2, 3, 4].map((i) => (
            <g key={i}>
              <rect x="100" y={66 + i * 10} width="22" height="4" rx="2" fill="var(--pf-fg-subtle)" />
              <rect x="128" y={66 + i * 10} width={14 + ((i * 7) % 16)} height="4" rx="2" fill="var(--pf-fg-subtle)" opacity="0.7" />
            </g>
          ))}
        </g>
        {/* Textzeilen */}
        {[132, 142, 152, 162, 172, 182].map((y, i) => (
          <rect key={y} x="30" y={y} width={i % 3 === 2 ? 96 : 128} height="4" rx="2" fill="var(--pf-fg-subtle)" opacity="0.35" />
        ))}
        {/* PDF-Marke */}
        <rect x="30" y="198" width="44" height="18" rx="5" fill="url(#dropMark)" />
        <text
          x="52"
          y="211"
          textAnchor="middle"
          fontSize="10"
          fontWeight="700"
          letterSpacing="0.08em"
          fill="#0B1020"
          fontFamily="Inter Variable, sans-serif"
        >
          PDF
        </text>
        {/* Scan-Strahl */}
        <g clipPath="url(#dropPage)">
          <motion.g
            initial={{ y: 0 }}
            animate={reduce ? undefined : { y: [0, 196, 0] }}
            transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
          >
            <rect x="14" y="0" width="160" height="26" fill="url(#dropBeamGlow)" />
            <rect x="14" y="25" width="160" height="2.5" rx="1.25" fill="url(#dropBeam)" />
          </motion.g>
        </g>
      </svg>
      {/* Funken */}
      {[
        { x: -18, y: 26, s: 14, d: 0 },
        { x: 196, y: 70, s: 10, d: 0.6 },
        { x: 178, y: 196, s: 12, d: 1.2 },
      ].map((p, i) => (
        <motion.svg
          key={i}
          width={p.s}
          height={p.s}
          viewBox="0 0 10 10"
          className="absolute"
          style={{ left: p.x, top: p.y }}
          animate={reduce ? undefined : { scale: [0.6, 1.15, 0.6], rotate: [0, 45, 0], opacity: [0.5, 1, 0.5] }}
          transition={{ duration: 2.2, repeat: Infinity, delay: p.d, ease: 'easeInOut' }}
          aria-hidden
        >
          <path d="M5 0 Q5.8 4.2 10 5 Q5.8 5.8 5 10 Q4.2 5.8 0 5 Q4.2 4.2 5 0Z" fill={i === 1 ? '#C084FC' : '#38BDF8'} />
        </motion.svg>
      ))}
    </motion.div>
  )
}
