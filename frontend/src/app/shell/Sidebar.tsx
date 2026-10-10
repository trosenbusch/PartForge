import { useI18n } from '@/lib/i18n'
import { motion } from 'motion/react'
import {
  ChevronsUpDown,
  Database,
  FolderOpen,
  FolderPlus,
  FolderSearch,
  Library,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react'
import { Fragment, useId } from 'react'
import { NavLink, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useCloseWorkspace, useOpenWorkspace, useRecentWorkspaces, useWorkspace } from '@/api/system'
import { ForgeLogo, ForgeMark } from '@/components/brand/ForgeLogo'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Kbd,
  Spinner,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, shortenPath } from '@/lib/format'
import { ariaKeyshortcuts } from '@/lib/hotkeys'
import { revealPath, useNativeBridge } from '@/lib/native'
import { NAV_GROUPS, NAV_ITEMS, type NavItem } from '../nav'
import { useUi } from '../stores'
import { confirmLibrarySwitch, switchCancelNote } from './librarySwitch'
import { statusColor, useSystemStatus, type StatusItem, type StatusLevel } from './useSystemStatus'

export const SIDEBAR_WIDTH = 248
export const SIDEBAR_COLLAPSED_WIDTH = 68

/**
 * Seitenleiste. Ein-/Ausklappen ändert die Breite **sofort** (kein Breiten-Übergang – der würde in jedem
 * Frame das ganze Layout inkl. Tabellen neu berechnen); nur die Beschriftungen blenden weich ein.
 */
export function Sidebar() {
  const { t: tr } = useI18n()
  const collapsed = useUi((s) => s.sidebarCollapsed)
  const toggle = useUi((s) => s.toggleSidebar)

  return (
    <aside
      aria-label={tr("Hauptnavigation")}
      className="relative z-sidebar flex h-full shrink-0 flex-col border-r border-line bg-bg-elev"
      style={{ width: collapsed ? SIDEBAR_COLLAPSED_WIDTH : SIDEBAR_WIDTH }}
    >
      {/* Glut-Schimmer oben links */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-56 bg-[radial-gradient(130%_90%_at_0%_0%,var(--pf-ember-faint),transparent_65%)]"
      />

      {/* Logo + Umschalter (ein und derselbe Button in beiden Zuständen – der Fokus bleibt erhalten) */}
      <div className={cn('relative flex h-14 shrink-0 items-center', collapsed ? 'justify-center' : 'justify-between pl-4 pr-2.5')}>
        {!collapsed && <ForgeLogo size={28} glow />}
        <SidebarToggle collapsed={collapsed} onToggle={toggle} />
      </div>

      {/* Bibliotheks-Umschalter */}
      <div className="relative shrink-0 px-3">
        <WorkspaceSwitcher collapsed={collapsed} />
      </div>

      {/* Navigation */}
      <nav
        id="pf-sidebar-nav"
        aria-label={tr("Bereiche")}
        className="relative mt-3 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto overflow-x-hidden px-3 pb-3 scrollbar-none"
      >
        {NAV_GROUPS.map((group) => (
          <div key={tr(group)} className="flex flex-col gap-0.5">
            {collapsed ? (
              <div className="mx-auto mb-1 h-px w-6 bg-line-strong first:hidden" aria-hidden />
            ) : (
              <div className="micro-label px-2.5 pb-1.5" aria-hidden>
                {tr(group)}
              </div>
            )}
            {NAV_ITEMS.filter((i) => i.group === group).map((item) => (
              <SidebarLink key={item.to} item={item} collapsed={collapsed} />
            ))}
          </div>
        ))}
      </nav>

      {/* Systemstatus */}
      <div className="relative shrink-0 border-t border-line p-3">
        <SystemStatus collapsed={collapsed} />
      </div>
    </aside>
  )
}

function SidebarToggle({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { t: tr } = useI18n()
  const label = collapsed ? tr("Seitenleiste ausklappen") : tr("Seitenleiste einklappen")
  return (
    <Tooltip content={label} hotkey="mod+b" side="right" sideOffset={10}>
      <button
        type="button"
        onClick={onToggle}
        aria-label={label}
        aria-expanded={!collapsed}
        aria-controls="pf-sidebar-nav"
        aria-keyshortcuts={ariaKeyshortcuts('mod+b')}
        className={cn(
          'group/toggle relative flex shrink-0 items-center justify-center rounded-button text-fg-subtle outline-none transition-colors focus-ring',
          collapsed ? 'size-10' : 'size-7 hover:bg-surface-2 hover:text-fg',
        )}
      >
        {collapsed ? (
          <>
            {/* eingeklappt: Bildmarke, beim Hover/Fokus das Ausklapp-Symbol */}
            <ForgeMark
              size={30}
              glow
              title=""
              className="transition-opacity duration-150 group-hover/toggle:opacity-0 group-focus-visible/toggle:opacity-0"
            />
            <span className="absolute inset-0 flex items-center justify-center rounded-button bg-surface-2 text-fg opacity-0 transition-opacity duration-150 group-hover/toggle:opacity-100 group-focus-visible/toggle:opacity-100">
              <PanelLeftOpen aria-hidden className="size-[18px]" />
            </span>
          </>
        ) : (
          <PanelLeftClose aria-hidden className="size-4" />
        )}
      </button>
    </Tooltip>
  )
}

// --------------------------------------------------------------------------- Navigation

function SidebarLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const { t: tr } = useI18n()
  const Icon = item.icon
  // Zugänglicher Name: ausgeklappt der sichtbare Text (+ „KI-gestützt“ nur für Screenreader – Sprachsteuerung trifft
  // die Beschriftung), eingeklappt ohne sichtbaren Text als aria-label; Kbd und KI-Abzeichen sind Zierde
  const name = item.ai ? tr("{0} (KI-gestützt)", { "0": String(item.label) }) : item.label
  const link = (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      aria-label={collapsed ? name : undefined}
      aria-keyshortcuts={ariaKeyshortcuts(item.hotkey)}
      className={({ isActive }) =>
        cn(
          'group/nav relative isolate flex h-9 items-center gap-3 rounded-button text-ui font-medium outline-none transition-colors duration-150 focus-ring',
          collapsed ? 'mx-auto w-[42px] justify-center px-0' : 'px-2.5',
          isActive ? 'text-fg' : 'text-fg-muted hover:bg-[color-mix(in_oklab,var(--pf-surface-2)_70%,transparent)] hover:text-fg',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <motion.span
              layoutId="sidebar-active"
              aria-hidden
              className="absolute inset-0 -z-10 rounded-button border border-line bg-surface-2 shadow-[inset_0_1px_0_var(--pf-highlight),0_1px_2px_rgba(0,0,0,.12)]"
              transition={{ type: 'spring', stiffness: 520, damping: 40 }}
            >
              <span className="absolute -left-3 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-forge shadow-[0_0_12px_1px_var(--pf-glow-indicator)]" />
            </motion.span>
          )}
          <Icon
            aria-hidden
            className={cn(
              'size-[18px] shrink-0 transition-colors duration-150',
              isActive ? 'text-accent' : 'text-fg-subtle group-hover/nav:text-fg-muted',
            )}
          />
          {!collapsed && (
            <motion.span
              className="flex min-w-0 flex-1 items-center"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.16 }}
            >
              <span className="min-w-0 flex-1 truncate">
                {item.label}
                {item.ai && <span className="sr-only"> {tr(" (KI-gestützt)")}</span>}
              </span>
              <span className="relative flex h-5 items-center" aria-hidden>
                {item.ai && (
                  <span className="flex h-[18px] items-center rounded-full border border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] px-1.5 text-2xs font-semibold leading-none text-spark-text transition-opacity group-hover/nav:opacity-0">
                    {tr("KI")}</span>
                )}
                <Kbd
                  hotkey={item.hotkey}
                  size="xs"
                  className="absolute right-0 opacity-0 transition-opacity duration-150 group-hover/nav:opacity-100"
                />
              </span>
            </motion.span>
          )}
          {collapsed && item.ai && (
            <span aria-hidden className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-spark-a shadow-[0_0_6px_var(--pf-spark-a)]" />
          )}
        </>
      )}
    </NavLink>
  )
  if (!collapsed) return link
  return (
    <Tooltip content={name} hotkey={item.hotkey} side="right" sideOffset={10}>
      {link}
    </Tooltip>
  )
}

// --------------------------------------------------------------------------- Bibliotheks-Umschalter

function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const workspace = useWorkspace().data
  const recent = useRecentWorkspaces()
  const openWs = useOpenWorkspace()
  const closeWs = useCloseWorkspace()
  const setLibraryDialog = useUi((s) => s.setLibraryDialog)
  const bridge = useNativeBridge()

  const others = (recent.data ?? []).filter((r) => r.path !== workspace?.root).slice(0, 6)
  const kind = workspace?.db_kind === 'postgres' ? 'PostgreSQL' : 'SQLite'
  const folder = workspace ? baseName(workspace.root) : ''

  const openRecent = async (path: string) => {
    // laufende Bibliotheks-Jobs würde der Wechsel abbrechen – vorher fragen
    if (!(await confirmLibrarySwitch('switch'))) return
    const note = switchCancelNote()
    openWs.mutate(path, {
      onSuccess: (info) => {
        toast.success(tr("„{0}“ geöffnet", { "0": String(info.name) }), { description: note ?? shortenPath(info.root, 56) })
        navigate('/')
      },
      onError: (err) => toast.error(tr("Bibliothek konnte nicht geöffnet werden"), { description: errorMessage(err) }),
    })
  }

  const closeLibrary = async () => {
    if (!(await confirmLibrarySwitch('close'))) return
    const note = switchCancelNote()
    closeWs.mutate(undefined, { onSuccess: () => toast.success(tr("Bibliothek geschlossen"), { description: note ?? undefined }) })
  }

  const trigger = (
    <button
      type="button"
      // eingeklappt ohne sichtbaren Text; ausgeklappt gilt der sichtbare Name (Sprachsteuerung „Shell-Test“)
      aria-label={
        collapsed ? (workspace ? tr("Bibliothek wechseln (aktuell: {0})", { "0": String(workspace.name) }) : tr("Bibliothek öffnen oder anlegen")) : undefined
      }
      title={workspace ? `${workspace.name}\n${workspace.root}` : undefined}
      className={cn(
        'group/ws flex w-full items-center gap-2.5 rounded-card border border-line bg-[color-mix(in_oklab,var(--pf-surface)_80%,transparent)] text-left outline-none',
        'shadow-card transition-[border-color,background-color] duration-150 hover:border-line-strong hover:bg-surface focus-ring data-[state=open]:border-line-strong data-[state=open]:bg-surface',
        collapsed ? 'size-[42px] justify-center p-0' : 'p-2',
      )}
    >
      <span
        aria-hidden
        className="relative flex size-8 shrink-0 items-center justify-center rounded-control border border-line-strong bg-surface-2 text-fg-muted"
      >
        {openWs.isPending ? <Spinner size={14} /> : <Database className="size-4" />}
        {workspace && (
          <span className="absolute -right-0.5 -top-0.5 size-2 rounded-full border-2 border-bg-elev bg-success" />
        )}
      </span>
      {!collapsed && (
        <>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-ui font-semibold leading-5 text-fg">
              {workspace && <span className="sr-only">{tr("Bibliothek wechseln, aktuell: ")}</span>}
              {workspace?.name ?? tr("Keine Bibliothek")}
            </span>
            <span className="sr-only">, </span>
            <span className="block truncate text-2xs leading-4 text-fg-subtle">
              {workspace ? `${kind} · ${folder}` : tr("Öffnen oder anlegen")}
            </span>
          </span>
          <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-fg-subtle transition-colors group-hover/ws:text-fg-muted" />
        </>
      )}
    </button>
  )

  return (
    <DropdownMenu>
      {collapsed ? (
        <Tooltip content={workspace?.name ?? tr("Bibliothek wählen")} side="right" sideOffset={10}>
          <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
        </Tooltip>
      ) : (
        <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
      )}
      <DropdownMenuContent align="start" side={collapsed ? 'right' : 'bottom'} className="w-[300px]">
        {workspace && (
          <>
            <DropdownMenuLabel>{tr("Aktuelle Bibliothek")}</DropdownMenuLabel>
            <div className="mx-1 mb-1 flex items-start gap-2.5 rounded-control bg-surface-2 px-2 py-2">
              <Database aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-muted" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-ui font-medium text-fg">{workspace.name}</div>
                <div className="mono truncate text-2xs text-fg-subtle" title={workspace.root}>
                  {shortenPath(workspace.root, 40)}
                </div>
              </div>
              <span className="shrink-0 rounded-full border border-line-strong px-1.5 text-2xs leading-4 text-fg-muted">{kind}</span>
            </div>
            <DropdownMenuItem
              icon={<FolderSearch />}
              description={bridge.canRevealPath || bridge.canOpenPath ? undefined : tr("Pfad kopieren")}
              onSelect={() => void revealPath(workspace.root, { what: tr("Bibliotheksordner") })}
            >
              {tr("Im Explorer zeigen")}</DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        )}
        <DropdownMenuLabel>{tr("Zuletzt verwendet")}</DropdownMenuLabel>
        {others.length === 0 && <div className="px-2 pb-2 text-xs text-fg-subtle">{tr("Keine weiteren Bibliotheken")}</div>}
        {others.map((r) => (
          <DropdownMenuItem
            key={r.path}
            icon={<Library />}
            disabled={!r.exists || openWs.isPending}
            description={r.exists ? shortenPath(r.path, 38) : tr("Ordner nicht gefunden")}
            onSelect={() => void openRecent(r.path)}
          >
            {r.name ?? baseName(r.path)}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem icon={<FolderPlus />} onSelect={() => setLibraryDialog('create')}>
          {tr("Neue Bibliothek anlegen …")}</DropdownMenuItem>
        <DropdownMenuItem icon={<FolderOpen />} onSelect={() => setLibraryDialog('open')}>
          {tr("Bibliothek öffnen …")}</DropdownMenuItem>
        {workspace && (
          <DropdownMenuItem icon={<LogOut />} onSelect={() => void closeLibrary()}>
            {tr("Bibliothek schließen")}</DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

// --------------------------------------------------------------------------- Status

export function StatusDot({ level, className }: { level: StatusLevel; className?: string }) {
  useI18n()
  const color = statusColor[level]
  return (
    <span className={cn('relative flex size-2 shrink-0', className)} aria-hidden>
      {(level === 'error' || level === 'warn') && (
        <span className="absolute inset-0 animate-ping rounded-full opacity-50 [animation-iteration-count:3]" style={{ background: color }} />
      )}
      {level === 'unknown' ? (
        // unbekannt (Abfrage fehlgeschlagen): leerer Ring – liest sich nicht als „aus“ und nie als „bereit“
        <span className="relative size-2 rounded-full border-[1.5px]" style={{ borderColor: color }} />
      ) : (
        <span
          className={cn('relative size-2 rounded-full', level === 'pending' && 'animate-pulse-soft')}
          style={{ background: color, boxShadow: level === 'off' || level === 'pending' ? undefined : `0 0 8px ${color}` }}
        />
      )}
    </span>
  )
}

function StatusTooltip({ item }: { item: StatusItem }) {
  useI18n()
  return (
    <div className="flex max-w-64 flex-col gap-0.5 py-0.5">
      <div className="flex items-center gap-1.5 font-medium text-fg">
        <StatusDot level={item.level} />
        {item.label}: {item.title}
      </div>
      {item.detail && <div className="text-fg-muted">{item.detail}</div>}
    </div>
  )
}

const statusTextClass = (level: StatusLevel) =>
  level === 'warn' ? 'text-warning-text' : level === 'error' ? 'text-danger-text' : 'text-fg-subtle'

function SystemStatus({ collapsed }: { collapsed: boolean }) {
  useI18n()
  const items = useSystemStatus()
  const navigate = useNavigate()
  const uid = useId()
  if (collapsed) {
    return (
      <div className="flex flex-col items-center gap-1">
        {items.map((item) => (
          <Tooltip key={item.key} content={<StatusTooltip item={item} />} side="right" sideOffset={12}>
            <button
              type="button"
              aria-label={`${item.label}: ${item.title}`}
              onClick={() => navigate(item.to)}
              className="flex size-7 items-center justify-center rounded-control outline-none transition-colors hover:bg-surface-2 focus-ring"
            >
              <StatusDot level={item.level} />
            </button>
          </Tooltip>
        ))}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-px">
      {items.map((item) => (
        <Fragment key={item.key}>
          <Tooltip content={<StatusTooltip item={item} />} side="right" sideOffset={14}>
            {/* Name = sichtbarer Text („Altium läuft“, auch für Sprachsteuerung), Einzelheiten als Beschreibung */}
            <button
              type="button"
              aria-describedby={`${uid}-${item.key}`}
              onClick={() => navigate(item.to)}
              className="group/status flex h-7 min-w-0 items-center gap-2.5 rounded-control px-2 text-2xs outline-none transition-colors hover:bg-surface-2 focus-ring"
            >
              <StatusDot level={item.level} />
              <span className="font-medium text-fg-muted group-hover/status:text-fg">{item.label}</span>{' '}
              <span className={cn('ml-auto truncate', statusTextClass(item.level))}>{item.short}</span>
            </button>
          </Tooltip>
          <span id={`${uid}-${item.key}`} hidden>
            {item.title}
            {item.detail ? `. ${item.detail}` : ''}
          </span>
        </Fragment>
      ))}
    </div>
  )
}
