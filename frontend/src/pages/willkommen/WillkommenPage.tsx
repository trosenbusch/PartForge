import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowRight,
  CircuitBoard,
  Database,
  FileScan,
  FolderOpen,
  FolderPlus,
  Layers,
  Library,
  PlugZap,
  Settings,
  Sparkles,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useHealth, useOpenWorkspace, useRecentWorkspaces, useWorkspace } from '@/api/system'
import { ThemeMenu } from '@/app/shell/Topbar'
import { useUi } from '@/app/stores'
import { ForgeLogo, ForgeMark } from '@/components/brand/ForgeLogo'
import { Badge, Button, Kbd, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, shortenPath } from '@/lib/format'
import { DEFAULT_DBLIB_FILE, EXAMPLE_PART_COUNT } from '@/lib/libraryDefaults'

const ease = [0.16, 1, 0.3, 1] as const

const FEATURES = [
  { icon: Layers, title: 'Serien in Sekunden', text: 'Komplette E‑Reihen mit allen Bauformen auf einen Schlag.' },
  { icon: FileScan, title: 'Datenblatt → Bauteil', text: 'Claude liest das PDF und schlägt alle Felder vor.', ai: true },
  { icon: CircuitBoard, title: 'Footprints nach IPC', text: 'IPC‑7351-Footprints und 3D‑Modelle automatisch.' },
  { icon: PlugZap, title: 'Direkt in Altium', text: 'Als Datenbankbibliothek (DbLib) sofort nutzbar.' },
]

/**
 * Endlos-Animationen des Hero nur kurz laufen lassen: 8 s nach dem Laden, nach dem Zurückkehren ins Fenster
 * oder beim Darüberfahren – sonst hält die GPU in WebView2 die App im Leerlauf beschäftigt.
 */
function useIdleLoops(ms = 8000) {
  const reduce = useReducedMotion()
  const [active, setActive] = useState(true)
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const wake = useCallback(() => {
    clearTimeout(timer.current)
    setActive(true)
    timer.current = setTimeout(() => setActive(false), ms)
  }, [ms])
  useEffect(() => {
    timer.current = setTimeout(() => setActive(false), ms)
    const onVisibility = () => {
      if (document.hidden) {
        clearTimeout(timer.current)
        setActive(false)
      } else wake()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      clearTimeout(timer.current)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [ms, wake])
  return { active: active && !reduce, wake }
}

export default function WillkommenPage() {
  const navigate = useNavigate()
  const setLibraryDialog = useUi((s) => s.setLibraryDialog)
  const workspace = useWorkspace().data
  const recent = useRecentWorkspaces()
  const openWs = useOpenWorkspace()
  const version = useHealth().data?.version
  // die geöffnete Bibliothek steht schon im Hinweis darüber – nicht doppelt aufführen
  const recentList = (recent.data ?? []).filter((r) => r.path !== workspace?.root).slice(0, 4)
  const loops = useIdleLoops()

  const openRecent = (path: string) =>
    openWs.mutate(path, {
      onSuccess: (info) => {
        toast.success(`„${info.name}“ geöffnet`, { description: shortenPath(info.root, 56) })
        navigate('/')
      },
      onError: (err) => toast.error('Bibliothek konnte nicht geöffnet werden', { description: errorMessage(err) }),
    })

  return (
    <div className="relative h-screen overflow-y-auto overflow-x-hidden">
      <Backdrop />

      {/* Kopfzeile */}
      <header className="relative z-10 mx-auto flex h-16 max-w-[1280px] items-center justify-between px-10">
        <ForgeLogo size={30} glow />
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" asChild>
            <Link to="/einstellungen">
              <Settings aria-hidden />
              Einstellungen
            </Link>
          </Button>
          <ThemeMenu />
        </div>
      </header>

      <main className="relative z-10 mx-auto grid min-h-[calc(100vh-7.5rem)] max-w-[1280px] grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] items-center gap-8 px-10 pb-6 pt-2 xl:gap-12">
        {/* Text & Aktionen */}
        <div className="flex min-w-0 flex-col">
          <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease }}>
            <span className="inline-flex h-7 items-center gap-2 rounded-full border border-line-strong bg-surface/70 pl-1.5 pr-3 text-xs font-medium text-fg-muted">
              <span aria-hidden className="flex size-[18px] items-center justify-center rounded-full bg-gradient-forge text-on-accent">
                <Database className="size-2.5" strokeWidth={2.25} />
              </span>
              <span>
                Datenbankbibliotheken für <span className="whitespace-nowrap">Altium Designer</span>
              </span>
            </span>
          </motion.div>

          <motion.h1
            className="mt-5 text-display font-semibold tracking-[-0.035em] text-fg"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease, delay: 0.05 }}
          >
            Bauteile <span className="text-gradient-forge">schmieden</span>,
            <br />
            nicht abtippen.
          </motion.h1>

          <motion.p
            className="mt-5 max-w-[34rem] text-md leading-relaxed text-fg-muted"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease, delay: 0.1 }}
          >
            PartForge legt komplette Bauteilserien an, liest Datenblätter per KI und liefert Symbole, Footprints und
            3D‑Modelle direkt als Altium‑Datenbankbibliothek – sauber, einheitlich und in Minuten statt Tagen.
          </motion.p>

          {workspace ? (
            // Bibliothek offen: „Zur Übersicht“ ist die eine Primäraktion
            <motion.div
              className="mt-8 flex max-w-[34rem] flex-col gap-4"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease, delay: 0.16 }}
            >
              <div className="flex items-center gap-3.5 rounded-card border border-line-strong bg-surface p-3.5 shadow-card">
                <span
                  aria-hidden
                  className="relative flex size-10 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted"
                >
                  <Database className="size-[18px]" />
                  <span className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-surface bg-success" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-2xs font-medium uppercase tracking-[0.06em] text-fg-subtle">Geöffnet</span>
                  <span className="block truncate text-ui font-semibold text-fg" title={workspace.root}>
                    {workspace.name}
                  </span>
                </span>
                <Button size="lg" variant="primary" rightIcon={<ArrowRight />} onClick={() => navigate('/')}>
                  Zur Übersicht
                </Button>
              </div>
              <div className="flex flex-wrap items-center gap-2.5">
                {/* Knöpfe, die einen Dialog öffnen, enden wie in Seitenleiste und Befehlspalette auf „…“ */}
                <Button variant="secondary" leftIcon={<FolderPlus />} onClick={() => setLibraryDialog('create')}>
                  Neue Bibliothek anlegen …
                </Button>
                <Button variant="ghost" leftIcon={<FolderOpen />} onClick={() => setLibraryDialog('open')}>
                  Andere Bibliothek öffnen …
                </Button>
              </div>
            </motion.div>
          ) : (
            <motion.div
              className="mt-8 flex flex-wrap items-center gap-3"
              initial={{ opacity: 0, y: 14 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, ease, delay: 0.16 }}
            >
              <Button size="lg" variant="primary" leftIcon={<FolderPlus />} onClick={() => setLibraryDialog('create')}>
                Neue Bibliothek anlegen …
              </Button>
              <Button size="lg" variant="secondary" leftIcon={<FolderOpen />} onClick={() => setLibraryDialog('open')}>
                Bibliothek öffnen …
              </Button>
            </motion.div>
          )}

          <motion.div
            className="mt-9"
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease, delay: 0.24 }}
          >
            {recentList.length > 0 ? (
              <section aria-labelledby="recent-heading" className="max-w-[34rem]">
                <h2 id="recent-heading" className="micro-label mb-2.5 flex items-center justify-between">
                  {workspace ? 'Weitere Bibliotheken' : 'Zuletzt verwendet'}
                  {recent.isFetching && <Spinner size={12} />}
                </h2>
                <ul className="overflow-hidden rounded-card border border-line bg-surface shadow-card">
                  {recentList.map((r, i) => (
                    <motion.li
                      key={r.path}
                      initial={{ opacity: 0, x: -6 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.3 + i * 0.03, duration: 0.3 }}
                      className="border-b border-line last:border-b-0"
                    >
                      <button
                        type="button"
                        disabled={!r.exists || openWs.isPending}
                        onClick={() => openRecent(r.path)}
                        className="group/rl flex w-full items-center gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset disabled:cursor-not-allowed disabled:opacity-55"
                      >
                        <span
                          aria-hidden
                          className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted transition-colors group-hover/rl:text-fg"
                        >
                          {openWs.isPending && openWs.variables === r.path ? <Spinner size={14} /> : <Library className="size-4" />}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-ui font-medium text-fg">{r.name ?? baseName(r.path)}</span>
                          <span className="mono block truncate text-2xs text-fg-subtle">{r.path}</span>
                        </span>
                        {r.exists ? (
                          <ArrowRight
                            aria-hidden
                            className="size-4 shrink-0 -translate-x-1 text-fg-subtle opacity-0 transition-all group-hover/rl:translate-x-0 group-hover/rl:opacity-100 group-focus-visible/rl:translate-x-0 group-focus-visible/rl:opacity-100"
                          />
                        ) : (
                          <Badge variant="warning">nicht gefunden</Badge>
                        )}
                      </button>
                    </motion.li>
                  ))}
                </ul>
              </section>
            ) : (
              !workspace && (
                <ul className="grid max-w-[36rem] grid-cols-2 gap-x-6 gap-y-5">
                  {FEATURES.map((f, i) => (
                    <motion.li
                      key={f.title}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.3 + i * 0.04, duration: 0.35 }}
                      className="flex gap-3"
                    >
                      <span
                        aria-hidden
                        className={cn(
                          'flex size-9 shrink-0 items-center justify-center rounded-button border',
                          f.ai
                            ? 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] text-spark-text'
                            : 'border-line-strong bg-surface-2 text-fg-muted',
                        )}
                      >
                        <f.icon className="size-[18px]" />
                      </span>
                      <span>
                        <span className="block text-ui font-semibold text-fg">{f.title}</span>
                        <span className="mt-0.5 block text-xs leading-relaxed text-fg-muted">{f.text}</span>
                      </span>
                    </motion.li>
                  ))}
                </ul>
              )
            )}
          </motion.div>
        </div>

        {/* Schmiede-Visual */}
        <HeroVisual active={loops.active} onWake={loops.wake} />
      </main>

      <footer className="relative z-10 mx-auto flex max-w-[1280px] items-center gap-6 px-10 pb-6 text-2xs text-fg-subtle">
        <span className="min-w-0">
          Läuft lokal – Ihre Bibliotheken bleiben auf Ihrem Rechner. Datenblätter gehen nur beim KI‑Import an die
          Claude‑API.
        </span>
        <span className="ml-auto flex shrink-0 items-center gap-2">
          <Kbd hotkey="mod+k" size="xs" />
          <span>alle Befehle</span>
        </span>
        {version && <span className="mono shrink-0">PartForge {version}</span>}
      </footer>
    </div>
  )
}

// --------------------------------------------------------------------------- Hintergrund

function Backdrop() {
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 overflow-hidden">
      <div className="dot-grid absolute inset-0 [mask-image:radial-gradient(ellipse_70%_60%_at_70%_45%,black,transparent_75%)]" />
      <div className="absolute -left-40 bottom-[-220px] size-[720px] rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]" />
      <div className="absolute left-[60%] top-[46%] size-[640px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]" />
    </div>
  )
}

// --------------------------------------------------------------------------- Hero

interface FloatCardProps {
  className: string
  delay: number
  active: boolean
  icon: ReactNode
  ai?: boolean
  label: string
  mpn: string
  meta: string
  badge?: ReactNode
}

function FloatCard({ className, delay, active, icon, ai, label, mpn, meta, badge }: FloatCardProps) {
  return (
    <motion.div
      className={cn('absolute w-[184px] xl:w-[204px]', className)}
      initial={{ opacity: 0, scale: 0.9, y: 14 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.7, ease, delay: 0.35 + delay }}
    >
      <motion.div
        animate={active ? { y: [0, -7, 0] } : { y: 0 }}
        transition={
          active
            ? { duration: 5 + delay * 2, repeat: Infinity, ease: 'easeInOut', delay: delay * 1.5 }
            : { duration: 0.8, ease }
        }
        className="rounded-card border border-line-strong bg-surface p-3 shadow-raised"
      >
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'flex size-6 items-center justify-center rounded-md border [&_svg]:size-3.5',
              ai
                ? 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] text-spark-text'
                : 'border-line-strong bg-surface-2 text-fg-muted',
            )}
          >
            {icon}
          </span>
          <span className="flex-1 truncate text-2xs font-medium text-fg-muted">{label}</span>
          {badge}
        </div>
        <div className="mono mt-2 truncate text-xs font-medium text-fg">{mpn}</div>
        <div className="mt-0.5 truncate text-2xs text-fg-subtle">{meta}</div>
      </motion.div>
    </motion.div>
  )
}

/** Leiterbahn mit fließendem Signal */
function Trace({ d, delay, active }: { d: string; delay: number; active: boolean }) {
  return (
    <g>
      <path d={d} stroke="var(--pf-accent)" strokeOpacity="0.28" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
      <motion.path
        d={d}
        stroke="url(#heroSignal)"
        strokeWidth="2"
        fill="none"
        strokeLinecap="round"
        strokeDasharray="10 150"
        initial={{ strokeDashoffset: 160, opacity: 0 }}
        animate={active ? { strokeDashoffset: [160, 0], opacity: 1 } : { opacity: 0 }}
        transition={active ? { duration: 2.4, repeat: Infinity, ease: 'linear', delay } : { duration: 0.6 }}
      />
    </g>
  )
}

function HeroVisual({ active, onWake }: { active: boolean; onWake: () => void }) {
  return (
    <div
      className="relative mx-auto aspect-square w-full max-w-[440px] xl:max-w-[520px]"
      aria-hidden
      onPointerEnter={onWake}
    >
      {/* Leiterbahnen + Orbits */}
      <svg viewBox="0 0 540 540" className="absolute inset-0 size-full overflow-visible">
        <defs>
          <linearGradient id="heroSignal" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#FFC27A" />
            <stop offset="1" stopColor="#FF6B1A" />
          </linearGradient>
          <radialGradient id="heroCore" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="var(--pf-accent)" stopOpacity="0.4" />
            <stop offset="0.6" stopColor="var(--pf-accent)" stopOpacity="0.07" />
            <stop offset="1" stopColor="var(--pf-accent)" stopOpacity="0" />
          </radialGradient>
        </defs>
        <circle cx="270" cy="270" r="200" fill="none" stroke="var(--pf-line-strong)" strokeDasharray="2 7" />
        <circle cx="270" cy="270" r="140" fill="none" stroke="var(--pf-line)" />
        <circle cx="270" cy="270" r="150" fill="url(#heroCore)" className="light:opacity-60" />
        <Trace d="M246 200 V128 L230 112 H196" delay={0} active={active} />
        <Trace d="M340 240 H372 L398 214 V180" delay={0.6} active={active} />
        <Trace d="M232 340 V372 L210 394 H180" delay={1.2} active={active} />
        <Trace d="M300 340 V380 L328 408 V430" delay={1.8} active={active} />
        {[
          [246, 128],
          [372, 240],
          [232, 372],
          [300, 380],
        ].map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="3.5" fill="var(--pf-bg-elev)" stroke="var(--pf-accent)" strokeOpacity="0.6" strokeWidth="1.5" />
        ))}
      </svg>

      {/* ein pulsierender Ring (nur solange die Animationen laufen) */}
      {active && (
        <motion.span
          className="absolute left-1/2 top-1/2 size-36 -translate-x-1/2 -translate-y-1/2 rounded-[40px] border border-accent/40 xl:size-40"
          initial={{ scale: 0.75, opacity: 0 }}
          animate={{ scale: [0.75, 1.9], opacity: [0.5, 0] }}
          transition={{ duration: 3.6, repeat: Infinity, ease: 'easeOut' }}
        />
      )}

      {/* Bildmarke */}
      <motion.div
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2"
        initial={{ scale: 0.6, opacity: 0, rotate: -8 }}
        animate={{ scale: 1, opacity: 1, rotate: 0 }}
        transition={{ type: 'spring', stiffness: 160, damping: 16, delay: 0.1 }}
      >
        <div className="absolute -inset-10 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember-strong),transparent)] blur-2xl" />
        <ForgeMark
          size={148}
          title=""
          animated={active}
          className="relative size-[120px] drop-shadow-[0_24px_48px_var(--pf-ember-strong)] xl:size-[148px]"
        />
      </motion.div>

      {/* Bauteil-Karten (Funken-Stil nur für die KI-Karte) */}
      <FloatCard
        className="left-0 top-[6%]"
        delay={0}
        active={active}
        icon={<Layers />}
        label="Widerstand · Serie E96"
        mpn="RC0603FR-0710KL"
        meta="10 kΩ · 1 % · 0603 · 0,1 W"
      />
      <FloatCard
        className="right-0 top-[14%]"
        delay={0.25}
        active={active}
        icon={<CircuitBoard />}
        label="Kondensator"
        mpn="GRM188R71H104KA93D"
        meta="100 nF · 50 V · X7R · 0603"
      />
      <FloatCard
        className="bottom-[11%] left-0"
        delay={0.5}
        active={active}
        ai
        icon={<Sparkles />}
        label="Aus Datenblatt"
        mpn="LM358DR"
        meta="Dual-OPV · SOIC-8 · 8 Pins"
        badge={<Badge variant="spark">KI</Badge>}
      />
      {/* DbLib wie bei einer neuen Bibliothek mit Beispielinhalten – etwas breiter, damit ihr Name ganz passt */}
      <FloatCard
        className="bottom-[3%] right-[2%] w-[216px] xl:w-[224px]"
        delay={0.75}
        active={active}
        icon={<PlugZap />}
        label="Altium Designer"
        mpn={DEFAULT_DBLIB_FILE}
        meta={`${EXAMPLE_PART_COUNT} Bauteile · synchron`}
        badge={<span className="size-1.5 rounded-full bg-success shadow-[0_0_8px_var(--pf-success)]" />}
      />
    </div>
  )
}
