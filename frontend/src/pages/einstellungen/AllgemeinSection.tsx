import { localizeMessage, t, tc, translate, useI18n, type TranslationParams } from '@/lib/i18n'
/**
 * Allgemein: Profil und Darstellung, KI-Funktionen (inkl. Verbindungstest) und Altium Designer (inkl. Status).
 * App-Einstellungen gelten für diesen Windows-Benutzer (settings.json) – unabhängig von der Bibliothek.
 * Rechts ein Inhaltsverzeichnis (ab ~72 rem Breite); Sprungadressen `/einstellungen#profil|ki|altium` (`#altium`
 * fokussiert das Feld „Bibliotheks-Writer“, solange kein Writer gefunden ist – siehe `anchors.ts`).
 *
 * Pfade zu X2.EXE und Bibliotheks-Writer werden nach dem Speichern geprüft: Fehlt die Datei, steht das als Fehler am
 * Feld; der Speichern-Toast meldet, ob der Bibliotheks-Writer gefunden wurde, und die Status-Kacheln (wie Seitenleiste
 * und Altium-Seite) laden sofort neu.
 */
import { AnimatePresence, motion } from 'motion/react'
import {
  Activity,
  ArrowRight,
  Bot,
  ChevronDown,
  CircleCheck,
  CircleX,
  Cpu,
  FileKey2,
  FileScan,
  FlaskConical,
  FolderCog,
  Info,
  KeyRound,
  Monitor,
  Moon,
  PlugZap,
  RefreshCw,
  Rows2,
  Rows4,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  TriangleAlert,
  UserRound,
  Wallet,
} from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { refreshAltiumStatus, useAiTest, useAltiumStatus, type AltiumStatus } from '@/api/settings'
import {
  aiSettingsSignature,
  useAiConnection,
  useDeleteApiKey,
  useHealth,
  useSaveApiKey,
  useSaveSettings,
  useSettings,
  useWorkspace,
  type AiConnectionCheck,
  type AiEffort,
  type AiProblemCode,
  type AppSettings,
  type LibraryBackend,
  type SettingsOut,
  type ThemePreference,
} from '@/api/system'
import { useTheme } from '@/app/theme'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import {
  Badge,
  Button,
  Callout,
  Card,
  confirm,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  EmptyState,
  Field,
  IconButton,
  Input,
  NumberInput,
  PathInput,
  PathText,
  SegmentedControl,
  Select,
  Skeleton,
  Switch,
  type SelectOption,
} from '@/components/ui'
import type { GridDensity } from '@/components/grid/theme'
import { cn } from '@/lib/cn'
import { formatDecimal, formatRelativeTime } from '@/lib/format'
// Zeilendichte der Bauteiltabelle (gespeicherte Vorliebe des Bauteile-Moduls, auch dort umschaltbar)
import { useBauteile } from '@/pages/bauteile/model/store'
import { GENERAL_ANCHORS, isGeneralAnchor, revealAnchor, WRITER_FIELD_ID, X2_FIELD_ID, type GeneralAnchor } from './anchors'
import { Row, SettingsCard } from './components'
import { useDraft } from './draft'
import { UnsavedChanges } from './UnsavedChanges'

export function AllgemeinSection() {
  const { t } = useI18n()
  const settings = useSettings()
  if (settings.isPending) {
    return (
      <div className="flex max-w-[56rem] flex-col gap-5" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Card key={i} padding="lg" className="flex flex-col gap-4">
            <Skeleton className="h-5 w-48" />
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-2/3" />
          </Card>
        ))}
      </div>
    )
  }
  if (settings.isError || !settings.data) {
    return (
      <Card className="max-w-[56rem]">
        <EmptyState
          illustration="offline"
          titleAs="h2"
          title={t("Einstellungen konnten nicht geladen werden")}
          description={t("Das Backend antwortet nicht. Bitte später erneut versuchen.")}
          actions={<Button onClick={() => void settings.refetch()}>{t("Erneut versuchen")}</Button>}
        />
      </Card>
    )
  }
  return <SettingsForm data={settings.data} />
}

// --------------------------------------------------------------------------- Sprungziele

/** Abstand unter der Oberkante des Inhaltsbereichs, ab dem eine Karte als aktuell gilt (Topbar + `scroll-mt-20`) */
const ACTIVE_OFFSET = 120

/**
 * Aktuelle Karte beim Scrollen (für das Inhaltsverzeichnis): die letzte Karte, deren Oberkante die Topbar erreicht
 * hat – ganz unten immer die letzte Karte, weil sie nicht bis nach oben scrollen kann. Ein Sprung (Adresse oder
 * Inhaltsverzeichnis) markiert sein Ziel sofort; das gilt auch, wenn die Seite gar nicht scrollt.
 */
function useActiveAnchor(): GeneralAnchor {
  const target = useLocation().hash.slice(1)
  const [active, setActive] = useState<GeneralAnchor>(isGeneralAnchor(target) ? target : 'profil')
  const [jumped, setJumped] = useState(target)
  if (jumped !== target) {
    setJumped(target)
    if (isGeneralAnchor(target)) setActive(target)
  }
  useEffect(() => {
    const root = document.getElementById('main')
    if (!root) return
    let frame = 0
    const update = () => {
      frame = 0
      const next = anchorAtTop(root)
      if (next) setActive(next)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    root.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      root.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [])
  return active
}

function anchorAtTop(root: HTMLElement): GeneralAnchor | null {
  const overflow = root.scrollHeight - root.clientHeight
  if (overflow <= 4) return null
  if (root.scrollTop >= overflow - 4) return GENERAL_ANCHORS[GENERAL_ANCHORS.length - 1].id
  const line = root.getBoundingClientRect().top + ACTIVE_OFFSET
  let current: GeneralAnchor = GENERAL_ANCHORS[0].id
  for (const a of GENERAL_ANCHORS) {
    const el = document.getElementById(a.id)
    if (el && el.getBoundingClientRect().top <= line) current = a.id
  }
  return current
}

/** Inhaltsverzeichnis rechts neben dem Formular (Sprung + Fokus auf die Kartenüberschrift) */
function GeneralToc({ onJump, className }: { onJump: (id: GeneralAnchor) => void; className?: string }) {
  const { t } = useI18n()
  const active = useActiveAnchor()
  return (
    <nav aria-label={t("Abschnitte von Allgemein")} className={cn('sticky top-[5.5rem]', className)}>
      <div className="micro-label mb-2 pl-3">{t("Auf dieser Seite")}</div>
      <ul className="flex flex-col border-l border-line">
        {GENERAL_ANCHORS.map((a) => {
          const on = a.id === active
          return (
            <li key={a.id}>
              <a
                href={`#${a.id}`}
                aria-current={on ? 'location' : undefined}
                onClick={(e) => {
                  e.preventDefault()
                  onJump(a.id)
                }}
                className={cn(
                  '-ml-px flex min-h-8 items-center border-l-2 py-1 pl-3 pr-2 text-xs leading-snug outline-none transition-colors focus-ring-inset',
                  on ? 'border-accent font-medium text-fg' : 'border-transparent text-fg-muted hover:border-line-strong hover:text-fg',
                )}
              >
                {t(a.label)}
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

/**
 * Sprungadresse (`#ki`) beim Öffnen und bei späteren Änderungen der Adresse auswerten. `focusFor` nennt je Karte ein
 * Feld, das statt der Überschrift den Fokus bekommt (`#altium` ohne Bibliotheks-Writer → dessen Pfadfeld).
 */
function useAnchorJump(focusFor: (id: GeneralAnchor) => string | null): (id: GeneralAnchor) => void {
  const { hash } = useLocation()
  const navigate = useNavigate()
  const handled = useRef<string | null>(null)
  const focusRef = useRef(focusFor)
  useEffect(() => {
    focusRef.current = focusFor
  })
  useEffect(() => {
    const id = hash.slice(1)
    if (!id || handled.current === hash || !isGeneralAnchor(id)) return
    handled.current = hash
    // erst nach dem Zeichnen (Karten stehen dann sicher im DOM)
    const raf = requestAnimationFrame(() => revealAnchor(id, focusRef.current(id)))
    return () => cancelAnimationFrame(raf)
  }, [hash])
  return (id) => {
    handled.current = `#${id}`
    revealAnchor(id)
    void navigate({ hash: `#${id}` }, { replace: true, preventScrollReset: true })
  }
}

type Editable = Pick<AppSettings, 'author' | 'language' | 'ai' | 'altium'>

function editable(s: AppSettings): Editable {
  return { author: s.author, language: s.language, ai: s.ai, altium: s.altium }
}

const MODEL_OPTIONS: SelectOption[] = [
  {
    value: 'claude-opus-5-5',
    label: 'Claude Opus 5.5',
    description: 'Liest Zeichnungen und Tabellen am genauesten · ca. 0,15–0,18 $ je Datenblatt',
    badge: <RecommendedBadge />,
  },
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', description: 'Ausgewogen · ca. 0,09 $ je Datenblatt' },
  { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', description: 'Sehr günstig (< 0,01 $), aber langsamer' },
]

const FAST_MODEL_OPTIONS: SelectOption[] = [
  {
    value: 'claude-haiku-5-5',
    label: 'Claude Haiku 5.5',
    description: 'Schnell und günstig – für Smart-Eingabe und Seitenauswahl',
    badge: <RecommendedBadge />,
  },
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', description: 'Gründlicher, etwas teurer' },
  { value: 'claude-opus-5-5', label: 'Claude Opus 5.5', description: 'Höchste Qualität, am teuersten' },
]

function withCurrent(options: SelectOption[], current: string): SelectOption[] {
  const translated = options.map((option) => ({ ...option, description: typeof option.description === 'string' ? t(option.description) : option.description }))
  return options.some((o) => o.value === current)
    ? translated
    : [...translated, { value: current, label: current, description: t("Benutzerdefiniertes Modell") }]
}

function RecommendedBadge() {
  const { t } = useI18n()
  return <Badge variant="neutral">{t('empfohlen')}</Badge>
}

const EFFORT_HELP: Record<AiEffort, string> = {
  low: 'Schnell und günstig – reicht für die meisten Datenblätter.',
  medium: 'Etwas gründlicher – hilft bei dichten Gehäusen (QFN, BGA) oder wenn die Prüfung Fehler meldet.',
  high: 'Maximale Gründlichkeit – deutlich langsamer und teurer.',
}

const BACKEND_HELP: Record<LibraryBackend, string> = {
  auto: 'Mit dem Bibliotheks-Writer, wenn er vorhanden ist (ohne Altium) – sonst über Altium Designer.',
  rust: 'Der Bibliotheks-Writer schreibt SchLib und PcbLib direkt – schnell, Altium muss nicht laufen.',
  altium: 'Erzeugt die Bibliotheken per Skript in Altium Designer (Altium muss installiert sein).',
}

/** Herkunft des Schlüssels (`ai_key_source`): Hinweis unter dem Feld und Beschriftung des Badges */
const KEY_SOURCE: Record<string, { help: string; badge: string }> = {
  stored: { help: 'Verschlüsselt gespeichert – nur für diesen Windows-Benutzer lesbar.', badge: 'Gespeichert' },
  env: { help: 'Aus der Umgebungsvariable ANTHROPIC_API_KEY (hat Vorrang).', badge: 'Umgebungsvariable' },
  file: { help: 'Aus der Schlüsseldatei (siehe unten).', badge: 'Aus Datei' },
  // Wiedergabemodus für Tests und Vorführungen (PARTFORGE_AI_REPLAY_DIR): aufgezeichnete Antworten, keine Anfrage
  replay: { help: 'Testmodus: aufgezeichnete Antworten statt der Claude-API – es entstehen keine Kosten.', badge: 'Testmodus' },
}

function nullIfEmpty(value: string): string | null {
  const v = value.trim()
  return v ? v : null
}

function SettingsForm({ data }: { data: SettingsOut }) {
  const { t } = useI18n()
  const saved = editable(data.settings)
  const { draft, setDraft, dirty, reset, commit } = useDraft<Editable>(saved)
  const [keyDialog, setKeyDialog] = useState(false)
  const save = useSaveSettings()
  const deleteKey = useDeleteApiKey()
  // Verbindungstest: Kartenkopf und Schlüssel-Badge folgen dem Fehlercode des letzten Tests (`POST /api/ai/test`,
  // `detail.code`) – egal, wo er lief (hier oder im Datenblatt-Import; die Shell merkt ihn sich über Neustarts). Er gilt
  // nur für die gespeicherte KI-Konfiguration (Schlüsselquelle, -datei, Modelle); ein neuer oder entfernter Schlüssel
  // setzt ihn zurück.
  const aiTest = useAiTest()
  const signature = aiSettingsSignature(data)
  const lastCheck = useAiConnection((s) => s.last)
  const check = lastCheck && lastCheck.signature === signature ? lastCheck : null
  // während eines neuen Tests bleibt der Kopf beim letzten Ergebnis (die Zeile „Verbindung“ zeigt den laufenden Test)
  const verdict = aiVerdict(check)
  const { theme, setTheme } = useTheme()
  const density = useBauteile((s) => s.density)
  const setDensity = useBauteile((s) => s.setDensity)
  const version = useHealth().data?.version

  const keyFileChanged = (draft.ai.api_key_file ?? '') !== (saved.ai.api_key_file ?? '')
  const aiOn = draft.ai.enabled

  const setAi = <K extends keyof AppSettings['ai']>(key: K, value: AppSettings['ai'][K]) =>
    setDraft((d) => ({ ...d, ai: { ...d.ai, [key]: value } }))
  const setAltium = <K extends keyof AppSettings['altium']>(key: K, value: AppSettings['altium'][K]) =>
    setDraft((d) => ({ ...d, altium: { ...d.altium, [key]: value } }))

  const submit = async (): Promise<boolean> => {
    if (!dirty || save.isPending) return false
    const aiChanged = JSON.stringify(draft.ai) !== JSON.stringify(saved.ai)
    const altiumChanged = JSON.stringify(draft.altium) !== JSON.stringify(saved.altium)
    const writerChanged =
      (draft.altium.rust_writer_path ?? '') !== (saved.altium.rust_writer_path ?? '') ||
      draft.altium.library_backend !== saved.altium.library_backend
    try {
      // Änderungen auf den aktuellen Serverstand anwenden (Theme, zuletzt geöffnete Bibliotheken bleiben unberührt)
      const out = await save.mutateAsync((current) => ({ ...current, ...draft }))
      commit(editable(out.settings))
      // The save callback was created in the previous language; feedback follows the saved setting.
      const savedText = (source: string, params?: TranslationParams) => translate(source, out.settings.language, params)
      const notes: string[] = []
      let warn = false
      if (altiumChanged) {
        // Kacheln, Seitenleiste und Altium-Seite sofort auf den neuen Stand bringen (nicht erst nach 15 s) – die
        // Rückmeldung wartet höchstens 4 s darauf (sonst nennt sie, was das Speichern selbst ergab)
        const status = await Promise.race([
          refreshAltiumStatus().catch(() => null),
          new Promise<null>((resolve) => window.setTimeout(() => resolve(null), 4000)),
        ])
        if (writerChanged) {
          const rust = status?.backends.find((b) => b.name === 'rust')
          const path = out.settings.altium.rust_writer_path
          if (path && out.rust_writer !== path) {
            // eingetragener Pfad fehlt (ein automatisch gefundener Writer springt dann ein)
            warn = true
            notes.push(
              out.rust_writer
                ? savedText("Bibliotheks-Writer nicht gefunden: {0} – es gilt der automatisch gefundene.", { "0": path })
                : savedText("Bibliotheks-Writer nicht gefunden: {0}", { "0": path }),
            )
          } else if (rust?.available || (!status && out.rust_writer)) {
            notes.push(savedText("Bibliotheks-Writer gefunden{0}.", { "0": rust?.version ? ` (${rust.version})` : '' }))
          } else if (out.settings.altium.library_backend !== 'altium') {
            warn = true
            notes.push(savedText("Kein Bibliotheks-Writer gefunden – Bibliotheksdateien entstehen nur über Altium Designer."))
          }
        }
      }
      // Der Schlüssel-Hinweis gehört zu Änderungen an der KI – nicht zu jedem Speichern
      if (aiChanged && out.settings.ai.enabled && !out.ai_key_configured) {
        notes.push(savedText("Hinweis: Es ist noch kein Claude-API-Schlüssel hinterlegt."))
      }
      const description = notes.length ? notes.join(' ') : undefined
      if (warn) toast.warning(savedText("Einstellungen gespeichert"), { description, duration: 8000 })
      else toast.success(savedText("Einstellungen gespeichert"), { description })
      return true
    } catch {
      return false
    }
  }

  const removeKey = async () => {
    const ok = await confirm({
      title: t("Gespeicherten Schlüssel entfernen?"),
      description: t("KI-Funktionen sind danach erst wieder verfügbar, wenn ein Schlüssel hinterlegt ist."),
      confirmLabel: t("Entfernen"),
      destructive: true,
      icon: <Trash2 />,
      onConfirm: () => deleteKey.mutateAsync(),
    })
    if (ok) {
      aiTest.reset()
      toast.success(t("Schlüssel entfernt"))
    }
  }

  // Quelle des Schlüssels – breiter als `ApiKeySource`: neuere Backends melden auch den Testmodus („replay“)
  const keySource: string | null = data.ai_key_source
  const x2Detected = !draft.altium.x2_path && data.altium_exe
  const writerDetected = !draft.altium.rust_writer_path && data.rust_writer
  // Eingetragener Pfad: erst nach dem Speichern prüfbar (`data` gilt für den gespeicherten Stand). Gespeichert, aber
  // nicht verwendet (SettingsOut nennt dann einen anderen bzw. keinen Pfad) = Datei fehlt.
  const x2Path = draft.altium.x2_path ?? ''
  const x2Pending = x2Path !== (saved.altium.x2_path ?? '')
  const x2Missing = Boolean(x2Path) && !x2Pending && data.altium_exe !== x2Path
  const writerPath = draft.altium.rust_writer_path ?? ''
  const writerPending = writerPath !== (saved.altium.rust_writer_path ?? '')
  const writerMissing = Boolean(writerPath) && !writerPending && data.rust_writer !== writerPath
  // `/einstellungen#altium` ohne Bibliotheks-Writer: gleich ins Pfadfeld
  const jump = useAnchorJump((id) => (id === 'altium' && !data.rust_writer ? WRITER_FIELD_ID : null))

  return (
    <div className="grid grid-cols-1 items-start gap-8 @[72rem]:grid-cols-[minmax(0,56rem)_minmax(0,1fr)]">
    <form
      className="flex min-w-0 flex-col gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        void submit()
      }}
    >
      {/* Profil und Darstellung */}
      <SettingsCard
        id="profil"
        icon={<UserRound />}
        title={t("Profil und Darstellung")}
        description={t("Ihr Name in der Änderungshistorie, Farbschema und Zeilendichte")}
      >
        <Field label={t("Autor")} layout="row" className="py-4" help={t("Wird bei neuen und geänderten Bauteilen als Bearbeiter eingetragen.")}>
          <Input value={draft.author} onChange={(e) => setDraft((d) => ({ ...d, author: e.target.value }))} placeholder={t("Ihr Name")} />
        </Field>
        <Field label={t("Sprache")} layout="row" className="py-4" help={t("Die Sprache wird nach dem Speichern für die gesamte Anwendung übernommen.")}>
          <Select
            value={draft.language}
            onValueChange={(language) => setDraft((d) => ({ ...d, language: language as AppSettings['language'] }))}
            options={[{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }]}
            aria-label={t("Sprache")}
          />
        </Field>
        <Field label={t("Farbschema")} layout="row" className="py-4" help={t("Wird sofort angewendet. „Wie System“ folgt der Windows‑Einstellung.")}>
          <SegmentedControl<ThemePreference>
            aria-label={t("Farbschema")}
            fullWidth
            value={theme}
            onValueChange={setTheme}
            options={[
              { value: 'dark', label: t("Dunkel"), icon: <Moon /> },
              { value: 'light', label: t("Hell"), icon: <Sun /> },
              { value: 'system', label: t("Wie System"), icon: <Monitor /> },
            ]}
          />
        </Field>
        <Field
          label={t("Dichte der Tabellen")}
          layout="row"
          className="py-4"
          help={t("Zeilenhöhe der Bauteiltabelle: kompakt zeigt mehr Zeilen, komfortabel liest sich leichter. Wird sofort angewendet.")}
        >
          <SegmentedControl<GridDensity>
            aria-label={t("Dichte der Tabellen")}
            fullWidth
            value={density}
            onValueChange={setDensity}
            options={[
              { value: 'compact', label: t("Kompakt"), icon: <Rows4 /> },
              { value: 'comfortable', label: t("Komfortabel"), icon: <Rows2 /> },
            ]}
          />
        </Field>
      </SettingsCard>

      {/* KI */}
      <SettingsCard
        id="ki"
        spark
        icon={<Sparkles />}
        title={t("KI-Funktionen")}
        description={t("Claude liest Datenblätter, schlägt Werte vor und erzeugt Symbole")}
        aside={
          !aiOn ? (
            <Badge variant="neutral" size="md">
              {t("Ausgeschaltet")}</Badge>
          ) : !data.ai_key_configured ? (
            <Badge variant="warning" size="md">
              <TriangleAlert />
              {t("Schlüssel fehlt")}</Badge>
          ) : verdict ? (
            <Badge variant={verdict.tone} size="md">
              {verdict.tone === 'success' ? <CircleCheck /> : verdict.tone === 'danger' ? <CircleX /> : <TriangleAlert />}
              {t(verdict.label)}
            </Badge>
          ) : keySource === 'replay' ? (
            <Badge variant="neutral" size="md">
              <FlaskConical />
              {t("Testmodus")}</Badge>
          ) : (
            <Badge variant="success" size="md">
              <CircleCheck />
              {t("Bereit")}</Badge>
          )
        }
      >
        <Row>
          <Switch
            tone="spark"
            checked={aiOn}
            onCheckedChange={(v) => setAi('enabled', v)}
            label={t("KI-Funktionen verwenden")}
            description={t("Datenblatt-Import, Smart-Eingabe und Vorschläge nutzen die Claude-API. Nur dann werden Datenblätter an die Claude-API gesendet – alles andere läuft lokal.")}
          />
        </Row>
        <div className={cn('divide-y divide-line transition-opacity', !aiOn && 'opacity-50')} aria-disabled={!aiOn || undefined}>
          <Field
            label={t("Claude-API-Schlüssel")}
            layout="row"
            className="py-4"
            help={
              keySource
                ? t(KEY_SOURCE[keySource]?.help ?? "Schlüssel hinterlegt.")
                : t("Noch kein Schlüssel hinterlegt. Den Schlüssel gibt es in der Claude Console.")
            }
          >
            <div className="flex min-h-8.5 flex-wrap items-center justify-between gap-2">
              <Badge variant={!data.ai_key_configured ? 'warning' : verdict?.keyRejected ? 'danger' : 'success'} size="md">
                {!data.ai_key_configured ? <TriangleAlert /> : verdict?.keyRejected ? <CircleX /> : <CircleCheck />}
                {keySource ? t(KEY_SOURCE[keySource]?.badge ?? "Hinterlegt") : t("Fehlt")}
                {data.ai_key_configured && verdict?.keyRejected && t(" · abgelehnt")}
              </Badge>
              <div className="flex items-center gap-1">
                {keySource === 'stored' && (
                  <Button variant="ghost" iconOnly aria-label={t("Gespeicherten Schlüssel entfernen")} disabled={!aiOn} onClick={() => void removeKey()}>
                    <Trash2 />
                  </Button>
                )}
                <Button disabled={!aiOn} leftIcon={<KeyRound />} onClick={() => setKeyDialog(true)}>
                  {keySource === 'stored' ? t("Ersetzen …") : t("Schlüssel eingeben …")}
                </Button>
              </div>
            </div>
          </Field>
          <AiConnectionTest
            test={aiTest}
            check={check}
            verdict={verdict}
            onRun={() => aiTest.mutate()}
            disabled={!aiOn || !data.settings.ai.enabled}
            keyConfigured={data.ai_key_configured}
            fastModel={data.settings.ai.fast_model}
            pendingChanges={dirty}
          />
          <Field label={t("Modell für Datenblätter")} layout="row" className="py-4" help={t("Liest PDFs und extrahiert Parameter, Pins und Gehäusemaße.")}>
            <Select
              value={draft.ai.model}
              onValueChange={(v) => setAi('model', v)}
              options={withCurrent(MODEL_OPTIONS, draft.ai.model)}
              prefix={<Bot />}
              disabled={!aiOn}
            />
          </Field>
          <Field label={t("Gründlichkeit")} layout="row" className="py-4" help={t(EFFORT_HELP[draft.ai.effort])}>
            <SegmentedControl<AiEffort>
              aria-label={t("Gründlichkeit")}
              fullWidth
              disabled={!aiOn}
              value={draft.ai.effort}
              onValueChange={(v) => setAi('effort', v)}
              options={[
                { value: 'low', label: t("Niedrig") },
                { value: 'medium', label: t("Mittel") },
                { value: 'high', label: t("Hoch") },
              ]}
            />
          </Field>
          <Field label={t("Schnelles Modell")} layout="row" className="py-4" help={t("Für kurze Aufgaben wie Smart-Eingabe, Seitenauswahl und Gegenprüfung.")}>
            <Select
              value={draft.ai.fast_model}
              onValueChange={(v) => setAi('fast_model', v)}
              options={withCurrent(FAST_MODEL_OPTIONS, draft.ai.fast_model)}
              prefix={<Cpu />}
              disabled={!aiOn}
            />
          </Field>
          <Row>
            <Switch
              tone="spark"
              checked={draft.ai.use_fallbacks}
              onCheckedChange={(v) => setAi('use_fallbacks', v)}
              disabled={!aiOn}
              label={t("Ausweichmodell bei Überlastung")}
              description={t("Ist das gewählte Modell gerade ausgelastet, antwortet automatisch ein gleichwertiges Modell, statt abzubrechen.")}
            />
          </Row>
          <Field label={t("Kostenlimit je Import")} layout="row" className="py-4" help={t("Obergrenze der API-Kosten für einen einzelnen Datenblatt-Import.")}>
            <NumberInput
              value={draft.ai.max_cost_per_import_usd}
              onValueChange={(v) => setAi('max_cost_per_import_usd', v ?? 0)}
              min={0}
              max={100}
              step={0.5}
              unit="USD"
              disabled={!aiOn}
              containerClassName="max-w-40"
            />
          </Field>
          <Field
            label={t("Schlüsseldatei")}
            hint={t("alternativ")}
            layout="row"
            className="py-4"
            error={!keyFileChanged && data.ai_key_file_problem ? localizeMessage(data.ai_key_file_problem) : undefined}
            help={
              keyFileChanged
                ? t("Die Datei wird nach dem Speichern geprüft.")
                : t("Lokale Textdatei, die nur den Schlüssel (sk-ant-…) enthält. Ein gespeicherter Schlüssel oder ANTHROPIC_API_KEY hat Vorrang.")
            }
          >
            <PathInput
              value={draft.ai.api_key_file ?? ''}
              onValueChange={(v) => setAi('api_key_file', nullIfEmpty(v))}
              prefix={<FileKey2 />}
              browse="file"
              fileFilters={[t("Textdateien (*.txt)"), t("Alle Dateien (*.*)")]}
              suffix={keyFileChanged ? <Badge>{t("ungeprüft")}</Badge> : undefined}
              placeholder="C:\…\claude-api-key.txt"
              disabled={!aiOn}
            />
          </Field>
        </div>
        <AiUsageNotes maxCost={draft.ai.max_cost_per_import_usd} model={draft.ai.model} fastModel={draft.ai.fast_model} />
      </SettingsCard>

      {/* Altium */}
      <SettingsCard
        id="altium"
        icon={<PlugZap />}
        title="Altium Designer"
        description={t("Wie PartForge Bibliotheksdateien erzeugt und Altium steuert")}
        aside={<AltiumBadge found={Boolean(data.altium_exe)} />}
      >
        <AltiumStatusStrip onSetupWriter={() => revealAnchor('altium', WRITER_FIELD_ID)} />
        <Field
          label="Altium Designer (X2.EXE)"
          layout="row"
          className="py-4"
          htmlFor={X2_FIELD_ID}
          error={
            x2Missing ? (
              <>
                {t("Datei nicht gefunden:")} <PathText path={x2Path} />  {t("– Pfad korrigieren oder leer lassen (automatische Erkennung).")}</>
            ) : undefined
          }
          help={
            x2Pending && x2Path ? (
              t("Der Pfad wird nach dem Speichern geprüft.")
            ) : x2Detected ? (
              <>
                {t("Automatisch erkannt:")} <PathText path={data.altium_exe ?? ''} className="text-fg-muted" />
              </>
            ) : x2Path ? (
              t("Leer lassen für die automatische Erkennung.")
            ) : (
              t("Nicht automatisch gefunden – bitte den Pfad zur Altium-Installation angeben.")
            )
          }
        >
          <PathInput
            value={draft.altium.x2_path ?? ''}
            onValueChange={(v) => setAltium('x2_path', nullIfEmpty(v))}
            placeholder={data.altium_exe ? t("Automatisch erkannt") : 'C:\\Program Files\\Altium\\AD25\\X2.EXE'}
            browse="file"
            fileFilters={['Altium Designer (X2.EXE)']}
            suffix={x2Detected ? <CircleCheck className="text-success-text" /> : undefined}
          />
        </Field>
        <Field label={t("Bibliotheksdateien erzeugen")} layout="row" className="py-4" help={t(BACKEND_HELP[draft.altium.library_backend])}>
          <SegmentedControl<LibraryBackend>
            aria-label={t("Bibliotheksdateien erzeugen")}
            fullWidth
            value={draft.altium.library_backend}
            onValueChange={(v) => setAltium('library_backend', v)}
            options={[
              { value: 'auto', label: t("Automatisch") },
              { value: 'rust', label: t("Ohne Altium") },
              { value: 'altium', label: t("Über Altium") },
            ]}
          />
        </Field>
        <Field
          label={t("Bibliotheks-Writer")}
          layout="row"
          className="py-4"
          htmlFor={WRITER_FIELD_ID}
          error={
            writerMissing ? (
              <>
                {t("Datei nicht gefunden:")} <PathText path={writerPath} /> –{' '}
                {data.rust_writer
                  ? t("Pfad korrigieren oder leer lassen (dann gilt der automatisch gefundene Bibliotheks-Writer).")
                  : t("Pfad zur altium-designer-mcp.exe korrigieren oder „Über Altium“ wählen.")}
              </>
            ) : undefined
          }
          help={
            writerPending && writerPath ? (
              t("Der Pfad wird nach dem Speichern geprüft.")
            ) : writerDetected ? (
              <>
                {t("Automatisch erkannt:")} <PathText path={data.rust_writer ?? ''} className="text-fg-muted" />
              </>
            ) : writerPath ? (
              t("Leer lassen für die automatische Erkennung.")
            ) : (
              t("Nicht gefunden – Pfad zur altium-designer-mcp.exe angeben oder „Über Altium“ wählen.")
            )
          }
        >
          <PathInput
            value={draft.altium.rust_writer_path ?? ''}
            onValueChange={(v) => setAltium('rust_writer_path', nullIfEmpty(v))}
            placeholder={data.rust_writer ? t("Automatisch erkannt") : 'C:\\…\\altium-designer-mcp.exe'}
            browse="file"
            fileFilters={[t("Programme (*.exe)")]}
            suffix={writerDetected ? <CircleCheck className="text-success-text" /> : undefined}
          />
        </Field>
        <Field label={t("Skript-Zeitlimit")} layout="row" className="py-4" help={t("Maximale Laufzeit eines Altium-Skripts, bevor PartForge abbricht.")}>
          <NumberInput
            value={draft.altium.script_timeout_s}
            onValueChange={(v) => setAltium('script_timeout_s', v ?? 180)}
            min={10}
            max={3600}
            step={10}
            decimals={0}
            unit="s"
            containerClassName="max-w-40"
          />
        </Field>
        <Row>
          <Switch
            checked={draft.altium.auto_refresh}
            onCheckedChange={(v) => setAltium('auto_refresh', v)}
            label={t("Altium automatisch aktualisieren")}
            description={t("Nach Änderungen an der Datenbank liest ein laufendes Altium die Bauteile neu ein – ohne Neustart und ohne Klick auf „Aktualisieren“.")}
          />
        </Row>
        <Row>
          <Switch
            checked={draft.altium.auto_reload_libraries}
            onCheckedChange={(v) => setAltium('auto_reload_libraries', v)}
            label={t("Geöffnete Bibliotheken neu laden")}
            description={t("Nach dem Neuschreiben von SchLib/PcbLib lädt Altium geöffnete, unveränderte Bibliotheksdateien neu.")}
          />
        </Row>
        <Disclosure label={t("Erweitert")} description={t("Zeitlimit des Bibliotheks-Writers und Austauschordner der Altium-Brücke")}>
          <Field label={t("Zeitlimit des Bibliotheks-Writers")} layout="row" className="py-4" help={t("Maximale Laufzeit für einen Schreibvorgang.")}>
            <NumberInput
              value={draft.altium.rust_writer_timeout_s}
              onValueChange={(v) => setAltium('rust_writer_timeout_s', v ?? 120)}
              min={10}
              max={3600}
              step={10}
              decimals={0}
              unit="s"
              containerClassName="max-w-40"
            />
          </Field>
          <Field
            label={t("Austauschordner der Brücke")}
            hint="optional"
            layout="row"
            className="py-4"
            help={t("Über diesen Ordner tauschen PartForge und die Altium-Skripte Aufträge aus. Leer = %LOCALAPPDATA%\\PartForge\\bridge.")}
          >
            <PathInput
              value={draft.altium.bridge_exchange_dir ?? ''}
              onValueChange={(v) => setAltium('bridge_exchange_dir', nullIfEmpty(v))}
              prefix={<FolderCog />}
              browse="folder"
              placeholder={t("Standardordner")}
            />
          </Field>
        </Disclosure>
      </SettingsCard>

      {/* Info */}
      <p className="flex items-center gap-2 px-1 text-2xs text-fg-subtle">
        <Info aria-hidden className="size-3.5 shrink-0" />
        <span>{t("App-Einstellungen gelten für diesen Windows-Benutzer (settings.json im PartForge-Datenordner).")}</span>
        {version && <span className="mono ml-auto shrink-0">PartForge {version}</span>}
      </p>

      <UnsavedChanges dirty={dirty} saving={save.isPending} onSave={submit} onDiscard={reset} label={t("Allgemein")} />

      <ApiKeyDialog open={keyDialog} onOpenChange={setKeyDialog} replacing={keySource === 'stored'} onSaved={() => aiTest.reset()} />
    </form>
    <GeneralToc onJump={jump} className="hidden @[72rem]:block" />
    </div>
  )
}

// --------------------------------------------------------------------------- Aufklappbarer Bereich

function Disclosure({ label, description, children }: { label: string; description?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="-mx-2 my-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-control px-2 py-2 text-left outline-none transition-colors hover:bg-surface-2/70 focus-ring"
      >
        <ChevronDown aria-hidden className={cn('size-4 shrink-0 text-fg-subtle transition-transform duration-200', !open && '-rotate-90')} />
        <span className="text-ui font-medium text-fg">{label}</span>
        {description && <span className="truncate text-xs text-fg-subtle">{description}</span>}
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="divide-y divide-line border-t border-line">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// --------------------------------------------------------------------------- KI: Verbindungstest

type AiTest = ReturnType<typeof useAiTest>

/** Bewertung eines Verbindungstests für Kartenkopf und Schlüssel-Badge */
interface AiVerdict {
  tone: 'success' | 'warning' | 'danger' | 'neutral'
  label: string
  /** Der Schlüssel selbst ist das Problem (Schlüssel-Badge rot) */
  keyRejected: boolean
}

const AI_CONNECTED: AiVerdict = { tone: 'success', label: 'Verbunden', keyRejected: false }

/**
 * Je Fehlercode von `POST /api/ai/test` (`detail.code`, eingeordnet von `classifyAiError` der Shell); `unexpected` =
 * Claude hat geantwortet, aber nicht wie erwartet. `unknown` ist meist eine von der API abgelehnte Anfrage (400).
 */
const AI_VERDICT: Record<AiProblemCode | 'unexpected', AiVerdict> = {
  key_rejected: { tone: 'danger', label: 'Schlüssel abgelehnt', keyRejected: true },
  key_missing: { tone: 'warning', label: 'Schlüssel fehlt', keyRejected: false },
  model_unavailable: { tone: 'warning', label: 'Modell nicht verfügbar', keyRejected: false },
  rate_limited: { tone: 'warning', label: 'Limit erreicht', keyRejected: false },
  network: { tone: 'warning', label: 'Keine Verbindung', keyRejected: false },
  ai_disabled: { tone: 'neutral', label: 'KI ausgeschaltet', keyRejected: false },
  unknown: { tone: 'warning', label: 'Test fehlgeschlagen', keyRejected: false },
  unexpected: { tone: 'warning', label: 'Unerwartete Antwort', keyRejected: false },
}

/** `null` = noch nicht geprüft (bzw. Test einer anderen KI-Konfiguration) */
function aiVerdict(check: AiConnectionCheck | null): AiVerdict | null {
  if (!check) return null
  if (check.ok) return AI_CONNECTED
  return AI_VERDICT[check.code ?? 'unknown'] ?? AI_VERDICT.unknown
}

function AiConnectionTest({
  test,
  check,
  verdict,
  onRun,
  disabled,
  keyConfigured,
  fastModel,
  pendingChanges,
}: {
  test: AiTest
  /** Letzter Test der gespeicherten Konfiguration (auch aus dem Datenblatt-Import oder vor einem Neustart) */
  check: AiConnectionCheck | null
  verdict: AiVerdict | null
  onRun: () => void
  disabled: boolean
  keyConfigured: boolean
  fastModel: string
  pendingChanges: boolean
}) {
  const { t } = useI18n()
  let result: ReactNode = (
    <span className="text-xs text-fg-subtle">{keyConfigured ? t("Noch nicht geprüft") : t("Zuerst einen Schlüssel hinterlegen")}</span>
  )
  if (test.isPending) {
    result = <span className="text-xs text-fg-muted">{t("Sende Testanfrage an")} {modelDisplayName(fastModel)} …</span>
  } else if (check && verdict) {
    const when = `${check.source === 'job' ? t("Bei einer Datenblatt-Analyse festgestellt") : t("Geprüft")} ${formatRelativeTime(check.at)}`
    result = check.ok ? (
      // Kosten kennt nur die Antwort dieser Seite (der gemerkte Test speichert sie nicht)
      <AiTestOutcome check={check} costUsd={test.data?.cost_usd ?? null} when={when} />
    ) : (
      <TestOutcome
        ok={false}
        title={t(verdict.label)}
        detail={
          <>
            {check.message && <span className="basis-full">{localizeMessage(check.message)}</span>}
            <span className="basis-full text-fg-subtle">{when}</span>
          </>
        }
      />
    )
  }

  return (
    <Field
      label={t("Verbindung")}
      layout="row"
      className="py-4"
      help={
        pendingChanges
          ? t("Geprüft werden die gespeicherten Einstellungen – vorher speichern, um Änderungen zu testen.")
          : t("Sendet eine winzige Anfrage an das schnelle Modell und misst die Antwortzeit (Kosten < 0,01 $).")
      }
    >
      <div className="flex flex-col items-stretch gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            leftIcon={<Activity />}
            onClick={onRun}
            loading={test.isPending}
            disabled={disabled || !keyConfigured}
          >
            {t("Verbindung testen")}</Button>
        </div>
        <div aria-live="polite" className="min-h-5">
          {result}
        </div>
      </div>
    </Field>
  )
}

function AiTestOutcome({ check, costUsd, when }: { check: AiConnectionCheck; costUsd: number | null; when: string }) {
  const cost = costUsd === null ? null : costUsd < 0.0001 ? '< 0,0001 $' : `${formatDecimal(costUsd, 4)} $`
  const parts = [
    check.model ? modelDisplayName(check.model) : null,
    check.latencyMs !== null ? `${formatDecimal(check.latencyMs, 0)} ms` : null,
    cost,
  ].filter((p): p is string => Boolean(p))
  return (
    <TestOutcome
      ok
      title={t(AI_CONNECTED.label)}
      detail={
        <>
          {parts.map((p, i) => (
            <span key={p} className="contents">
              {i > 0 && <span aria-hidden>·</span>}
              <span className="mono tabular">{p}</span>
            </span>
          ))}
          <span className="basis-full text-fg-subtle">{when}</span>
        </>
      }
    />
  )
}

function TestOutcome({ ok, title, detail }: { ok: boolean; title: string; detail: ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      {ok ? (
        <CircleCheck aria-hidden className="mt-px size-4 shrink-0 text-success-text" />
      ) : (
        <CircleX aria-hidden className="mt-px size-4 shrink-0 text-danger-text" />
      )}
      <div className="min-w-0">
        <div className={cn('font-medium', ok ? 'text-success-text' : 'text-danger-text')}>{title}</div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-fg-muted">{detail}</div>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- KI: Hinweise zur Nutzung

function AiUsageNotes({ maxCost, model, fastModel }: { maxCost: number; model: string; fastModel: string }) {
  const { t } = useI18n()
  const notes: { icon: ReactNode; title: string; text: ReactNode }[] = [
    {
      icon: <FileScan />,
      title: t("Datenblatt-Import"),
      text: (
        <>
          {modelDisplayName(model)}  {t("liest Tabellen, Pinbelegung und Gehäusemaße. Typisch 0,10–0,20 $ je Datenblatt, nie mehr als")} {formatDecimal(maxCost, 2)} $.
        </>
      ),
    },
    {
      icon: <Sparkles />,
      title: t("Smart-Eingabe und Prüfung"),
      text: <>{modelDisplayName(fastModel)}  {t("ordnet Eingaben wie „10k 1% 0603“ zu und prüft Ergebnisse – Bruchteile eines Cents.")}</>,
    },
    {
      icon: <ShieldCheck />,
      title: t("Datenschutz"),
      text: t("Gesendet werden nur Datenblatt-Seiten und Ihre Eingaben. Bibliothek, Bauteile und Dateien bleiben auf diesem Rechner."),
    },
    {
      icon: <Wallet />,
      title: t("Abrechnung"),
      text: t("Über Ihr Konto in der Claude Console. Jeder Import zeigt Modell, Dauer und Kosten im Protokoll."),
    },
  ]
  return (
    <div className="@container -mx-5 border-t border-line bg-surface-2/35 px-5 py-4">
      <div className="micro-label mb-3">{t("So nutzt PartForge die KI")}</div>
      <ul className="grid grid-cols-1 gap-x-6 gap-y-3 @[34rem]:grid-cols-2">
        {notes.map((n) => (
          <li key={n.title} className="flex gap-2.5">
            <span aria-hidden className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-surface-3/70 text-fg-muted [&_svg]:size-3.5">
              {n.icon}
            </span>
            <div className="min-w-0">
              <div className="text-xs font-medium text-fg">{n.title}</div>
              <p className="mt-0.5 text-xs leading-snug text-fg-muted">{n.text}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

// --------------------------------------------------------------------------- Altium: Status

type Level = 'ok' | 'warn' | 'error' | 'off'

const LEVEL_DOT: Record<Level, string> = {
  ok: 'bg-success shadow-[0_0_6px_var(--pf-success)]',
  warn: 'bg-warning',
  error: 'bg-danger',
  off: 'bg-fg-subtle/60',
}

function StatusTile({
  level,
  title,
  value,
  detail,
  action,
}: {
  level: Level
  title: string
  value: string
  detail?: ReactNode
  /** Knopf unter dem Text (z. B. „Pfad eintragen“) */
  action?: ReactNode
}) {
  return (
    <div className="min-w-0 rounded-control bg-surface-2/60 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <span aria-hidden className={cn('size-2 shrink-0 rounded-full', LEVEL_DOT[level])} />
        <span className="micro-label">{title}</span>
      </div>
      <div className="mt-1 truncate text-ui font-medium text-fg" title={value}>
        {value}
      </div>
      {detail && <div className="mt-0.5 line-clamp-3 text-2xs leading-snug text-fg-subtle">{detail}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

/** Kopf der Altium-Karte: läuft / nicht gestartet / nicht gefunden (Live-Status, sonst Pfad-Erkennung) */
function AltiumBadge({ found }: { found: boolean }) {
  const { t } = useI18n()
  const status = useAltiumStatus()
  const running = status.data?.altium_running
  if (running) {
    return (
      <Badge variant="success" size="md" dot>
        {t("Läuft")}{status.data?.version ? ` · ${status.data.version}` : ''}
      </Badge>
    )
  }
  const exe = status.data ? Boolean(status.data.altium_exe) : found
  return (
    <Badge variant={exe ? 'neutral' : 'warning'} size="md">
      {exe ? <CircleCheck /> : <TriangleAlert />}
      {exe ? t("Gefunden · nicht gestartet") : t("Nicht gefunden")}
    </Badge>
  )
}

function AltiumStatusStrip({ onSetupWriter }: { onSetupWriter: () => void }) {
  const { t } = useI18n()
  const workspace = useWorkspace()
  const status = useAltiumStatus()
  if (status.isPending) {
    return (
      <div className="grid grid-cols-1 gap-2 py-4 @[36rem]:grid-cols-3" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[70px] rounded-control" />
        ))}
      </div>
    )
  }
  if (status.isError) {
    return (
      <Row>
        <Callout
          tone="warning"
          title={t("Altium-Status nicht verfügbar")}
          actions={
            <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} onClick={() => void status.refetch()}>
              {t("Erneut prüfen")}</Button>
          }
        >
          {errorMessage(status.error)}
        </Callout>
      </Row>
    )
  }
  return (
    <AltiumStatusTiles
      data={status.data}
      hasWorkspace={Boolean(workspace.data)}
      checkedAt={status.dataUpdatedAt}
      refreshing={status.isFetching}
      onRefresh={() => void status.refetch()}
      onSetupWriter={onSetupWriter}
    />
  )
}

function AltiumStatusTiles({
  data,
  hasWorkspace,
  checkedAt,
  refreshing,
  onRefresh,
  onSetupWriter,
}: {
  data: AltiumStatus
  hasWorkspace: boolean
  checkedAt: number
  refreshing: boolean
  onRefresh: () => void
  /** Fokus ins Feld „Bibliotheks-Writer“ (diese Seite) */
  onSetupWriter: () => void
}) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const rust = data.backends.find((b) => b.name === 'rust')
  const viaAltium = data.backends.find((b) => b.name === 'altium')
  const writerReady = Boolean(rust?.available)
  const anyWriter = writerReady || Boolean(viaAltium?.available)
  const dblib = data.dblib
  const refresh = data.refresh
  const refreshed = refresh.last_refresh ? formatRelativeTime(refresh.last_refresh * 1000) : null
  const wedged = data.bridge_wedged ? t("Die Altium-Brücke reagiert nicht – in Altium Strg+F3 drücken oder Altium neu starten.") : null
  return (
    <div className="@container py-4">
      <div className="grid grid-cols-1 gap-2 @[36rem]:grid-cols-3">
        <StatusTile
          // Nicht gestartet ist nur dann „in Ordnung“ (grau), wenn der Bibliotheks-Writer ohne Altium schreiben kann
          level={wedged ? 'error' : data.altium_running ? 'ok' : data.altium_exe && writerReady ? 'off' : 'warn'}
          title="Altium Designer"
          value={data.altium_running ? t("Läuft{0}", { "0": data.version ? ` · ${data.version}` : '' }) : data.altium_exe ? t("Nicht gestartet") : t("Nicht gefunden")}
          detail={
            wedged ??
            (data.altium_running
              ? refreshed
                ? t("Zuletzt aktualisiert {0}", { "0": refreshed })
                : t("Bauteiländerungen erscheinen automatisch")
              : !writerReady
                ? t("Ohne Bibliotheks-Writer entstehen keine Bibliotheksdateien – Pfad eintragen oder Altium starten")
                : data.altium_exe
                  ? t("Bibliotheken entstehen trotzdem – ohne Altium")
                  : t("X2.EXE unten angeben"))
          }
        />
        <StatusTile
          level={writerReady ? 'ok' : anyWriter ? 'off' : 'warn'}
          title={t("Bibliotheks-Writer")}
          value={
            writerReady
              ? t("Bereit{0}", { "0": rust?.version ? ` · ${rust.version}` : '' })
              : viaAltium?.available
                ? t("Über Altium")
                : t("Nicht gefunden")
          }
          detail={
            writerReady
              ? t("Schreibt SchLib und PcbLib – ohne Altium")
              : viaAltium?.available
                ? t("altium-designer-mcp.exe fehlt – Altium Designer schreibt die Bibliotheken")
                : t("altium-designer-mcp.exe fehlt – Pfad unten unter „Bibliotheks-Writer“ eintragen")
          }
          action={
            writerReady ? undefined : (
              <Button variant="link" size="xs" rightIcon={<ArrowRight />} onClick={onSetupWriter}>
                {t("Pfad eintragen")}</Button>
            )
          }
        />
        <StatusTile
          level={!hasWorkspace || !dblib ? 'off' : !dblib.exists ? 'warn' : dblib.up_to_date ? 'ok' : 'warn'}
          title="DbLib"
          value={!hasWorkspace || !dblib ? t("Keine Bibliothek") : !dblib.exists ? t("Fehlt") : dblib.up_to_date ? t("Aktuell") : t("Veraltet")}
          detail={
            dblib
              ? dblib.installed_in_altium === true
                ? t("In Altium installiert")
                : dblib.installed_in_altium === false
                  ? t("In Altium nicht installiert")
                  : dblib.file_name
              : undefined
          }
        />
      </div>
      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-fg-subtle">
        <span className="flex items-center gap-1.5">
          <span aria-hidden className={cn('size-1.5 rounded-full', refresh.auto_refresh ? 'bg-success' : 'bg-fg-subtle/60')} />
          {t("Automatisch aktualisieren")} {refresh.auto_refresh ? t("an") : t("aus")}
          {refresh.pending ? t(" · Änderungen warten") : ''}
          {refresh.last_error ? t(" · letzter Fehler: {0}", { "0": localizeMessage(refresh.last_error) }) : ''}
        </span>
        <span aria-live="polite">{t("Stand")} {formatRelativeTime(checkedAt)}</span>
        <span className="ml-auto flex items-center gap-1">
          <IconButton size="xs" label={t("Status jetzt prüfen")} icon={<RefreshCw className={cn(refreshing && 'animate-spin')} />} onClick={onRefresh} />
          {hasWorkspace && (
            <Button variant="link" size="xs" rightIcon={<ArrowRight />} onClick={() => void navigate('/altium')}>
              {t("Altium-Seite")}</Button>
          )}
        </span>
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- API-Schlüssel

function ApiKeyDialog({
  open,
  onOpenChange,
  replacing,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  replacing: boolean
  /** Neuer Schlüssel gespeichert (ein früherer Verbindungstest gilt nicht mehr) */
  onSaved: () => void
}) {
  const { t } = useI18n()
  const [key, setKey] = useState('')
  const saveKey = useSaveApiKey()
  const trimmed = key.trim()
  const formatHint = trimmed && !trimmed.startsWith('sk-') ? t("Claude-API-Schlüssel beginnen mit „sk-“.") : null

  const close = (o: boolean) => {
    onOpenChange(o)
    if (!o) {
      setKey('')
      saveKey.reset()
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    e.stopPropagation() // nicht das umgebende Einstellungsformular absenden
    if (!trimmed || formatHint) return
    saveKey.mutate(trimmed, {
      onSuccess: () => {
        onSaved()
        toast.success(t("Claude-API-Schlüssel gespeichert"), { description: t("Verschlüsselt für diesen Windows-Benutzer.") })
        close(false)
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="md">
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader
            tone="spark"
            icon={<KeyRound />}
            title={replacing ? t("Schlüssel ersetzen") : t("Claude-API-Schlüssel eingeben")}
            description={t("Der Schlüssel wird mit Windows (DPAPI) verschlüsselt gespeichert, nur für Ihren Benutzer lesbar und nie wieder angezeigt.")}
          />
          <DialogBody className="flex flex-col gap-4">
            <Field label={tc('apiKey', 'Schlüssel')} required error={formatHint ?? (saveKey.error ? errorMessage(saveKey.error) : undefined)}>
              <Input
                type="password"
                mono
                autoComplete="off"
                spellCheck={false}
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="sk-ant-…"
              />
            </Field>
            <Callout tone="neutral">
              {t("Datenblätter werden nur beim Datenblatt-Import an die Claude-API gesendet. Bibliotheken und Bauteile bleiben auf Ihrem Rechner.")}</Callout>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => close(false)}>
              {t("Abbrechen")}</Button>
            <Button type="submit" variant="primary" loading={saveKey.isPending} disabled={!trimmed || Boolean(formatHint)}>
              {t("Speichern")}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
