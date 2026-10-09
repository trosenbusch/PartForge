/**
 * Kopf der Altium-Seite: Schlagzeile mit dem nächsten Schritt, die Kette „Bauteile → DbLib → Bibliotheksdateien →
 * Altium“ (wo sie reißt, steht der Grund im Text und die Behebung direkt am Glied) und die Aktionsleiste
 * (DbLib | In Altium). Aktionen, die ein laufendes Altium brauchen, sind sonst gesperrt – mit Grund am Knopf.
 */
import { useQueryClient } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { Check, ChevronDown, Database, Ellipsis, FileCode2, FileStack, PlugZap, type LucideIcon } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { altiumKeys, type AltiumStatus } from '@/api/altium'
import { useCategories } from '@/api/library'
import { useSaveSettings, type LibraryBackend } from '@/api/system'
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  IconButton,
  Skeleton,
  Switch,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import type { AltiumActions, RegenerateReceipt } from './useAltiumActions'
import { verifyEstimate, verifySampleSize, type ActionKey, type ChainNode, type Headline, type Level, type PageModel } from './model'
import { ACTION_META, LEVEL_LABEL, LEVEL_TEXT } from './tokens'
import { HeadlineLink, LevelDot } from './ui'

const NODE_ICON: Record<ChainNode['key'], LucideIcon> = {
  parts: Database,
  dblib: FileCode2,
  files: FileStack,
  altium: PlugZap,
}

const TONE_DOT: Record<Headline['tone'], string> = {
  success: 'bg-success shadow-[0_0_8px_color-mix(in_oklab,var(--pf-success)_70%,transparent)]',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  neutral: 'bg-fg-subtle/70',
}

export interface StatusHeroProps {
  model: PageModel | null
  status: AltiumStatus | undefined
  /** gewählter Writer (Einstellungen › Allgemein › Altium Designer: auto | rust | altium) */
  backend: LibraryBackend | undefined
  actions: AltiumActions
  onAction: (key: ActionKey) => void
  onVerify: (scope: VerifyScope) => void
  /** Warum Altium-Aktionen gerade nicht gehen (`altiumBlocker`) – `null` = bereit */
  blocker: string | null
}

/** Umfang von „In Altium prüfen“: Stichprobe über alle Kategorien (Standard), alle, eine Kategorie, eigene Auswahl */
export type VerifyScope =
  | { kind: 'sample' }
  | { kind: 'all' }
  | { kind: 'table'; table: string; label: string }
  | { kind: 'parts'; partNumbers: string[]; label: string }

export function StatusHero({ model, status, backend, actions, onAction, onVerify, blocker }: StatusHeroProps) {
  const headline = model?.headline
  const primary = headline?.primary ?? null
  return (
    <section aria-labelledby="altium-headline" className="relative overflow-hidden rounded-panel border border-line bg-surface shadow-card">
      <div
        aria-hidden
        className="dot-grid absolute inset-0 opacity-45 [mask-image:linear-gradient(100deg,transparent_38%,black_88%)]"
      />
      <div
        aria-hidden
        className="absolute -right-36 -top-56 size-[500px] rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]"
      />

      <div className="relative px-6 pb-5 pt-5">
        {/* Schlagzeile + nächster Schritt (ab 40 rem rechts daneben) */}
        <div className="flex flex-col gap-4 @[40rem]:flex-row @[40rem]:items-start @[40rem]:justify-between @[40rem]:gap-8">
          <div className="min-w-0 max-w-[72ch]" aria-live="polite">
            <div className="micro-label flex items-center gap-2">
              <span aria-hidden className={cn('size-2 shrink-0 rounded-full', TONE_DOT[headline?.tone ?? 'neutral'])} />
              {headline?.eyebrow ?? 'Status'}
            </div>
            {headline ? (
              <>
                <h2 id="altium-headline" className="mt-1.5 text-h3 font-semibold tracking-[-0.02em] text-fg">
                  {headline.title}
                </h2>
                <p className="mt-1 text-ui leading-relaxed text-fg-muted">{headline.text}</p>
                {headline.link && <HeadlineLink link={headline.link} className="mt-1.5" />}
              </>
            ) : (
              <>
                <h2 id="altium-headline" className="sr-only">
                  Status wird geladen
                </h2>
                <Skeleton className="mt-2 h-7 w-80" />
                <Skeleton className="mt-2 h-4 w-[28rem] max-w-full" />
              </>
            )}
          </div>
          {primary && (
            <Button
              size="lg"
              variant="primary"
              className="shrink-0 self-start"
              leftIcon={<PrimaryIcon action={primary} />}
              loading={actions.pending[primary]}
              onClick={() => onAction(primary)}
            >
              {ACTION_META[primary].label}
            </Button>
          )}
        </div>

        {/* Kette */}
        <Chain
          nodes={model?.nodes ?? null}
          pending={actions.pending}
          onFix={onAction}
          primary={primary}
          extra={{
            files: status ? <WriterList status={status} backend={backend} /> : null,
            altium: status?.altium_exe ? <AutoRefreshSwitch status={status} /> : null,
          }}
        />
      </div>

      <ActionBar status={status} model={model} actions={actions} primary={primary} onAction={onAction} onVerify={onVerify} blocker={blocker} />
    </section>
  )
}

function PrimaryIcon({ action }: { action: ActionKey }) {
  const Icon = ACTION_META[action].icon
  return <Icon />
}


// --------------------------------------------------------------------------- Kette

function Chain({
  nodes,
  pending,
  onFix,
  primary,
  extra,
}: {
  nodes: ChainNode[] | null
  pending: Record<ActionKey, boolean>
  onFix: (key: ActionKey) => void
  /** Primäraktion der Schlagzeile – dieselbe Behebung am Glied entfällt (kein doppelter Aufruf) */
  primary: ActionKey | null
  /** Zusatz unter einem Glied (z. B. Schalter „Automatisch aktualisieren“ am Altium-Glied) */
  extra?: Partial<Record<ChainNode['key'], ReactNode>>
}) {
  if (!nodes) {
    return (
      <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 @[44rem]:grid-cols-4" aria-hidden>
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex flex-col gap-2">
            <Skeleton className="size-9 rounded-button" />
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-4 w-28" />
          </div>
        ))}
      </div>
    )
  }
  return (
    <ol aria-label="Weg der Bauteile nach Altium" className="mt-5 grid grid-cols-2 gap-x-6 gap-y-5 @[44rem]:grid-cols-4 @[44rem]:gap-x-0">
      {nodes.map((node, i) => {
        const Icon = NODE_ICON[node.key]
        const next = nodes[i + 1]
        return (
          <motion.li
            key={node.key}
            className="relative flex min-w-0 flex-col @[44rem]:pr-3"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1], delay: 0.04 + i * 0.05 }}
          >
            <div className="flex items-center">
              <span
                aria-hidden
                className={cn(
                  'relative flex size-9 shrink-0 items-center justify-center rounded-button border bg-surface-2 text-fg-muted shadow-[inset_0_1px_0_var(--pf-highlight)] [&_svg]:size-[18px]',
                  node.level === 'error' ? 'border-danger/40' : node.level === 'warn' ? 'border-warning/45' : 'border-line-strong',
                )}
              >
                <Icon />
                <span className="absolute -right-1 -top-1 flex rounded-full bg-surface p-[2px]">
                  <LevelDot level={node.level} />
                </span>
              </span>
              {next && <Connector from={node.level} to={next.level} />}
            </div>
            <div className="mt-3 min-w-0">
              <div className="micro-label truncate">{node.label}</div>
              <div
                className={cn(
                  'mt-0.5 truncate text-sm font-semibold tracking-[-0.01em]',
                  node.emphasis === 'detail' ? 'text-fg' : LEVEL_TEXT[node.level],
                )}
                title={node.value}
              >
                {node.value}
                <span className="sr-only"> ({LEVEL_LABEL[node.level]})</span>
              </div>
              {node.detail && (
                <div
                  className={cn(
                    'mt-0.5 line-clamp-2 text-xs leading-snug',
                    node.emphasis === 'detail' && node.level !== 'ok' ? LEVEL_TEXT[node.level] : 'text-fg-muted',
                  )}
                  title={node.detail}
                >
                  {node.detail}
                </div>
              )}
              {node.fix && node.fix.action !== primary && (
                <Button
                  variant="link"
                  size="xs"
                  className="mt-1 text-xs"
                  loading={pending[node.fix.action]}
                  onClick={() => node.fix && onFix(node.fix.action)}
                >
                  {node.fix.label} →
                </Button>
              )}
              {extra?.[node.key] && <div className="mt-2">{extra[node.key]}</div>}
            </div>
          </motion.li>
        )
      })}
    </ol>
  )
}

/** Verbindung zwischen zwei Gliedern: durchgezogen, wenn das linke Glied in Ordnung ist, sonst gestrichelt */
function Connector({ from, to }: { from: Level; to: Level }) {
  const solid = from === 'ok' || from === 'busy'
  return (
    <span aria-hidden className="relative mx-3 hidden h-px flex-1 @[44rem]:block">
      {solid ? (
        <span
          className={cn(
            'absolute inset-0 rounded-full',
            to === 'ok' || to === 'busy'
              ? 'bg-[linear-gradient(90deg,color-mix(in_oklab,var(--pf-success)_70%,transparent),color-mix(in_oklab,var(--pf-success)_40%,transparent))]'
              : 'bg-[linear-gradient(90deg,color-mix(in_oklab,var(--pf-success)_65%,transparent),var(--pf-line-strong))]',
          )}
        />
      ) : (
        <span
          className={cn(
            'absolute inset-x-0 top-0 border-t border-dashed',
            from === 'error' ? 'border-danger/55' : from === 'warn' ? 'border-warning/60' : 'border-line-strong',
          )}
        />
      )}
    </span>
  )
}

// --------------------------------------------------------------------------- Aktionsleiste

/** Barrierefreier Name: der lange Text nur, wenn er die sichtbare Beschriftung enthält (WCAG 2.5.3) */
function accessibleName(key: ActionKey, visible: string): string | undefined {
  const name = ACTION_META[key].label
  return name !== visible && name.toLowerCase().includes(visible.toLowerCase()) ? name : undefined
}

function ActionBar({
  status,
  model,
  actions,
  primary,
  onAction,
  onVerify,
  blocker,
}: {
  status: AltiumStatus | undefined
  model: PageModel | null
  actions: AltiumActions
  primary: ActionKey | null
  onAction: (key: ActionKey) => void
  onVerify: (scope: VerifyScope) => void
  blocker: string | null
}) {
  const installed = model?.altium.installed === true
  const button = (key: ActionKey, blocked: string | null = null) => {
    const Icon = ACTION_META[key].icon
    const label = ACTION_META[key].short
    return (
      <GatedButton
        key={key}
        blocked={blocked}
        icon={<Icon />}
        loading={actions.pending[key]}
        onClick={() => onAction(key)}
        aria-label={accessibleName(key, label)}
      >
        {label}
      </GatedButton>
    )
  }
  const note = !status ? null : !status.altium_exe ? 'nicht gefunden' : status.altium_running ? null : 'nicht gestartet'

  return (
    <div className="relative flex flex-wrap items-center gap-x-6 gap-y-3 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_45%,transparent)] px-6 py-3">
      <Group label="DbLib">
        {button('regenerate')}
        {button('preview')}
        {button('odbc')}
      </Group>
      <span aria-hidden className="hidden h-5 w-px bg-line-strong @[52rem]:block" />
      <Group label="In Altium" note={note}>
        {installed ? button('uninstall', blocker) : button(primary === 'installReplace' ? 'installReplace' : 'install', blocker)}
        {button('refresh', blocker)}
        <VerifyMenu onVerify={onVerify} pending={actions.pending.verify} blocked={blocker} />
        <MoreMenu onAction={onAction} blocked={blocker} />
      </Group>
      {actions.lastRegenerate && <RegenerateNote receipt={actions.lastRegenerate} />}
      {blocker && (
        <span id="altium-blocker" className="sr-only">
          {blocker}
        </span>
      )}
    </div>
  )
}

/**
 * Knopf, der gesperrt sein kann, ohne aus der Tab-Reihenfolge zu fallen: `aria-disabled` statt `disabled`, der Grund
 * steht im Tooltip (Maus und Tastaturfokus) und als Beschreibung für Screenreader.
 */
function GatedButton({
  blocked,
  icon,
  loading,
  onClick,
  children,
  size = 'sm',
  variant = 'secondary',
  rightIcon,
  'aria-label': ariaLabel,
}: {
  blocked: string | null
  icon: ReactNode
  loading?: boolean
  onClick: () => void
  children: ReactNode
  size?: 'sm' | 'md'
  variant?: 'secondary' | 'primary'
  rightIcon?: ReactNode
  'aria-label'?: string
}) {
  if (!blocked) {
    return (
      <Button size={size} variant={variant} leftIcon={icon} rightIcon={rightIcon} loading={loading} onClick={onClick} aria-label={ariaLabel}>
        {children}
      </Button>
    )
  }
  return (
    <Tooltip content={blocked}>
      <Button
        size={size}
        variant={variant}
        leftIcon={icon}
        rightIcon={rightIcon}
        aria-disabled
        aria-describedby="altium-blocker"
        aria-label={ariaLabel}
        className="aria-disabled:pointer-events-auto aria-disabled:cursor-not-allowed aria-disabled:active:scale-100"
      >
        {children}
      </Button>
    </Tooltip>
  )
}

function Group({ label, note, children }: { label: string; note?: string | null; children: ReactNode }) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap items-center gap-2">
      <span className="micro-label mr-1 flex items-center gap-1.5">
        {label}
        {note && <span className="font-normal normal-case tracking-normal text-fg-subtle">· {note}</span>}
      </span>
      {children}
    </div>
  )
}

/**
 * „In Altium prüfen“ mit Umfang: **Stichprobe über alle Kategorien** (Standard – anteilig, mindestens ein Bauteil je
 * Kategorie, deterministisch), alle Bauteile, eine Kategorie (oder eigene Auswahl oben, z. B. „nur mit Befund“).
 */
export function VerifyMenu({
  onVerify,
  pending,
  size = 'sm',
  variant = 'secondary',
  label = ACTION_META.verify.short,
  blocked = null,
  extra,
}: {
  onVerify: (scope: VerifyScope) => void
  pending?: boolean
  size?: 'sm' | 'md'
  variant?: 'secondary' | 'primary'
  label?: string
  /** Altium nicht bereit – Knopf gesperrt mit Grund */
  blocked?: string | null
  /** zusätzliche Auswahl oben im Menü */
  extra?: { scope: Extract<VerifyScope, { kind: 'parts' }>; description: string }[]
}) {
  const categories = useCategories().data
  const filled = (categories ?? []).filter((c) => (c.part_count ?? 0) > 0 && c.altium_enabled)
  const total = filled.reduce((n, c) => n + (c.part_count ?? 0), 0)
  const sample = verifySampleSize(filled.map((c) => c.part_count ?? 0))
  /** die Stichprobe umfasst ohnehin alle Bauteile – „Alle Bauteile“ wäre doppelt */
  const everything = total > 0 && sample >= total
  const Icon = ACTION_META.verify.icon
  if (blocked) {
    return (
      <GatedButton blocked={blocked} icon={<Icon />} rightIcon={<ChevronDown />} size={size} variant={variant} onClick={() => undefined}>
        {label}
      </GatedButton>
    )
  }
  const sampleText = !categories
    ? 'anteilig, mindestens ein Bauteil je Kategorie'
    : everything
      ? `aus ${plural(filled.length, 'Kategorie', 'Kategorien')} · ${verifyEstimate(total)}`
      : `${plural(sample, 'Bauteil', 'Bauteile')} aus ${plural(filled.length, 'Kategorie', 'Kategorien')}, anteilig verteilt · ${verifyEstimate(sample)}`
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size={size} variant={variant} leftIcon={<Icon />} rightIcon={<ChevronDown />} loading={pending}>
          {label}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-80">
        <DropdownMenuLabel>Altium löst jedes Bauteil auf – Symbol, Footprints, Pins, Parameter</DropdownMenuLabel>
        {extra?.map((e) => (
          <DropdownMenuItem key={e.scope.label} description={e.description} onSelect={() => onVerify(e.scope)}>
            {e.scope.label}
          </DropdownMenuItem>
        ))}
        {extra?.length ? <DropdownMenuSeparator /> : null}
        {/* umfasst die Stichprobe ohnehin alles, prüft der Eintrag „Alle …“ auch als „alle Bauteile“ (Titel und Ergebnis) */}
        <DropdownMenuItem description={sampleText} onSelect={() => onVerify(everything ? { kind: 'all' } : { kind: 'sample' })}>
          {everything ? `Alle ${plural(total, 'Bauteil', 'Bauteile')}` : 'Stichprobe über alle Kategorien'}
        </DropdownMenuItem>
        {!everything && (
          <DropdownMenuItem
            description={total ? `${plural(total, 'Bauteil', 'Bauteile')} · ${verifyEstimate(total)}` : 'Alle Bauteile der Bibliothek'}
            onSelect={() => onVerify({ kind: 'all' })}
          >
            Alle Bauteile
          </DropdownMenuItem>
        )}
        {filled.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuSub>
              <DropdownMenuSubTrigger>Eine Kategorie</DropdownMenuSubTrigger>
              {/* breit genug für „Optokoppler und Optoelektronik“ samt Anzahl (Mindestbreite 1120 px, nichts gekürzt) */}
              <DropdownMenuSubContent className="max-h-80 w-72 overflow-y-auto">
                {filled.map((c) => {
                  const count = c.part_count ?? 0
                  return (
                    // Farbpunkt, Name und Anzahl als eigene Plätze (E2EREG-1: sonst Punkt ohne Breite, „Widerstände17“)
                    <DropdownMenuItem
                      key={c.table}
                      icon={<span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: c.color ?? 'var(--pf-fg-subtle)' }} />}
                      trailing={<span className="mono">{formatNumber(count)}</span>}
                      aria-label={`${c.label}, ${plural(count, 'Bauteil', 'Bauteile')}`}
                      textValue={c.label}
                      onSelect={() => onVerify({ kind: 'table', table: c.table, label: c.label })}
                    >
                      {c.label}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuSubContent>
            </DropdownMenuSub>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** So lange bleibt die Rückmeldung von „Neu erzeugen“ in der Aktionsleiste stehen */
const RECEIPT_MS = 45_000

/**
 * Rückmeldung von „DbLib neu erzeugen“ direkt in der Aktionsleiste – der Grund in den Worten des Backends
 * (`reason_text`). Der Toast meldet dasselbe (und wird angesagt); hier bleibt es 45 s stehen.
 */
function RegenerateNote({ receipt }: { receipt: RegenerateReceipt }) {
  const [expiredFor, setExpiredFor] = useState<number | null>(null)
  useEffect(() => {
    const left = RECEIPT_MS - (Date.now() - receipt.at)
    const t = setTimeout(() => setExpiredFor(receipt.at), Math.max(0, left))
    return () => clearTimeout(t)
  }, [receipt.at])
  if (expiredFor === receipt.at) return null
  const { result } = receipt
  return (
    <p className="flex min-w-0 basis-full items-start gap-1.5 text-xs leading-snug text-fg-muted">
      <Check aria-hidden className="mt-px size-3.5 shrink-0 text-success-text" />
      <span className="min-w-0">
        <span className="font-medium text-fg">{result.written ? 'DbLib neu erzeugt' : 'DbLib geprüft'}</span>
        {' – '}
        {result.reason_text}
        {result.warnings.length > 0 && <span className="text-warning-text"> {result.warnings.join(' ')}</span>}
      </span>
    </p>
  )
}

function MoreMenu({ onAction, blocked }: { onAction: (key: ActionKey) => void; blocked: string | null }) {
  const item = (key: ActionKey, description: string, needsAltium = true) => {
    const Icon = ACTION_META[key].icon
    const off = needsAltium && Boolean(blocked)
    return (
      <DropdownMenuItem icon={<Icon />} description={off ? 'Erst Altium Designer starten' : description} disabled={off} onSelect={() => onAction(key)}>
        {ACTION_META[key].label}
      </DropdownMenuItem>
    )
  }
  return (
    <DropdownMenu>
      <Tooltip content="Weitere Aktionen">
        <DropdownMenuTrigger asChild>
          <IconButton size="sm" variant="ghost" label="Weitere Altium-Aktionen" icon={<Ellipsis />} tooltip={false} />
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-72">
        {item('open', 'Zeigt die DbLib in Altium an')}
        {item('installState', 'Liest die installierten Bibliotheken')}
        {item('refreshRebuild', 'Leert Altiums Cache, baut den Index neu auf')}
        <DropdownMenuSeparator />
        {item('settings', 'Pfad zu Altium, Bibliotheks-Writer, Aktualisierung', false)}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Schalter „Automatisch aktualisieren“ (App-Einstellung `altium.auto_refresh`, wirkt sofort) */
function AutoRefreshSwitch({ status }: { status: AltiumStatus }) {
  const qc = useQueryClient()
  const save = useSaveSettings()
  const checked = status.refresh.auto_refresh
  const setChecked = (value: boolean) => {
    qc.setQueryData<AltiumStatus>(altiumKeys.status, (cur) => (cur ? { ...cur, refresh: { ...cur.refresh, auto_refresh: value } } : cur))
    save.mutate((cur) => ({ ...cur, altium: { ...cur.altium, auto_refresh: value } }), {
      onSettled: () => void qc.invalidateQueries({ queryKey: altiumKeys.status }),
    })
  }
  return (
    <span className="flex items-center gap-2" title="Nach Änderungen an der Datenbank liest ein laufendes Altium die Bauteile selbst neu ein.">
      <Switch id="altium-auto-refresh" size="sm" checked={checked} disabled={save.isPending} onCheckedChange={setChecked} />
      <label htmlFor="altium-auto-refresh" className="cursor-pointer select-none whitespace-nowrap text-xs leading-tight text-fg-muted">
        Automatisch aktualisieren
      </label>
    </span>
  )
}

/** Beide Writer mit Version und Bereitschaft (im Text); der aktive (laut Einstellung bzw. automatisch) ist markiert */
function WriterList({ status, backend }: { status: AltiumStatus; backend: LibraryBackend | undefined }) {
  const rust = status.backends.find((b) => b.name === 'rust')
  const altium = status.backends.find((b) => b.name === 'altium')
  const active = backend === 'rust' || backend === 'altium' ? backend : rust?.available ? 'rust' : altium?.available ? 'altium' : null
  const rows = [
    { key: 'rust', label: 'Bibliotheks-Writer', b: rust, off: 'fehlt' },
    { key: 'altium', label: 'Altium', b: altium, off: 'nicht bereit' },
  ]
  return (
    <ul className="flex flex-col gap-0.5" aria-label="Bibliotheks-Writer">
      {rows.map(({ key, label, b, off }) => (
        <li key={key} className={cn('flex min-w-0 items-start gap-1.5 text-2xs leading-4', active === key ? 'text-fg-muted' : 'text-fg-subtle')}>
          <span aria-hidden className={cn('mt-[5px] size-1.5 shrink-0 rounded-full', b?.available ? 'bg-success' : 'bg-fg-subtle/60')} />
          <span className="min-w-0">
            {label}
            {b?.version && <span className="mono"> {b.version}</span>}
            {!b?.available && <span className={active === key ? 'text-warning-text' : undefined}> · {off}</span>}
          </span>
          {active === key && <span className="shrink-0 rounded-sm bg-surface-3 px-1 text-2xs leading-4 text-fg-muted">aktiv</span>}
          {b?.available && <span className="sr-only"> – bereit</span>}
        </li>
      ))}
    </ul>
  )
}
