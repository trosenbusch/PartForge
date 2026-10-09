import { Command, defaultFilter } from 'cmdk'
import { AnimatePresence, motion } from 'motion/react'
import { CornerDownLeft, Search, Sparkles } from 'lucide-react'
import { Dialog as DialogPrimitive } from 'radix-ui'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { useHealth } from '@/api/system'
import { ForgeMark } from '@/components/brand/ForgeLogo'
import { Kbd, Spinner, useReturnFocus } from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  commandDisabledReason,
  useCommands,
  useSearchProviders,
  type AppCommand,
  type CommandContext,
  type CommandIcon,
  type CommandSearchResult,
} from '../commands'
import { useUi } from '../stores'

const GROUP_ORDER = ['Aktionen', 'Navigation', 'Bibliothek', 'Darstellung', 'System']
const MAX_RESULTS = 12

/**
 * Ab dieser Bewertung (cmdk, 0…1) ist ein Titeltreffer echt: Wortanfang, zusammenhängend oder mitten im Wort
 * („jobs“ in „Hintergrundjobs“ ≈ 0,17). Verstreute Einzelbuchstaben liegen weit darunter („Serie“ in
 * „Bibliotheksordner im Explorer zeigen“ ≈ 0,02) und dürfen nicht vor Stichwort-Treffern stehen.
 */
const TITLE_MATCH = 0.1

/**
 * Bewertung eines Befehls: echte Treffer im Titel zählen mehr als Treffer in Untertitel/Stichworten –
 * „footpr“ findet so zuerst „Footprints“ und nicht „Bibliothek prüfen (… Footprints …)“; verstreute Zufallstreffer
 * fallen weg. (Eigene Sortierung, weil cmdk Gruppen nicht nach Relevanz umordnet.)
 */
function scoreCommand(cmd: AppCommand, search: string): number {
  const titleScore = defaultFilter(cmd.title, search)
  if (titleScore >= TITLE_MATCH) return 0.5 + titleScore / 2 + (cmd.priority ?? 0) / 10_000
  const keywordScore = defaultFilter(cmd.title, search, [cmd.subtitle ?? '', ...(cmd.keywords ?? [])])
  // verstreute Zufallstreffer über mehrere Stichworte ausblenden
  return keywordScore >= 0.2 ? keywordScore / 2 : 0
}

interface ProviderResults {
  group: string
  results: CommandSearchResult[]
}

function useProviderSearch(query: string, open: boolean) {
  const providers = useSearchProviders()
  const providersRef = useRef(providers)
  useEffect(() => {
    providersRef.current = providers
  })
  const [state, setState] = useState<{ key: string; loading: boolean; groups: ProviderResults[] }>({
    key: '',
    loading: false,
    groups: [],
  })
  const q = query.trim()
  // Nur Zeichenketten als Abhängigkeiten: neue Arrays bei jedem Render dürfen die Suche nicht neu starten.
  const activeIds = providers
    .filter((p) => q.length >= (p.minQueryLength ?? 2))
    .map((p) => p.id)
    .join(',')
  const key = `${q}::${activeIds}`

  useEffect(() => {
    if (!open || !activeIds) return
    const ids = activeIds.split(',')
    const active = providersRef.current.filter((p) => ids.includes(p.id))
    const controller = new AbortController()
    const timer = setTimeout(() => {
      setState((s) => (s.key === key && s.loading ? s : { ...s, key, loading: true }))
      void Promise.all(
        active.map((p) =>
          p
            .search(q, controller.signal)
            .then((results) => ({ group: p.group, results }))
            .catch(() => ({ group: p.group, results: [] as CommandSearchResult[] })),
        ),
      ).then((groups) => {
        if (!controller.signal.aborted) setState({ key, loading: false, groups })
      })
    }, 140)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [key, open, activeIds, q])

  if (!open || !activeIds) return { loading: false, groups: [] as ProviderResults[] }
  return { loading: state.loading || state.key !== key, groups: state.key === key ? state.groups : [] }
}

function ItemIcon({ icon: Icon, ai }: { icon?: CommandIcon; ai?: boolean }) {
  return (
    <span
      className={cn(
        'flex size-7 shrink-0 items-center justify-center rounded-control border transition-colors',
        ai
          ? 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] text-spark-b'
          : 'border-line bg-surface-2 text-fg-muted group-data-[selected=true]/item:border-accent/30 group-data-[selected=true]/item:bg-accent-soft group-data-[selected=true]/item:text-accent',
      )}
    >
      {Icon ? <Icon className="size-4" /> : ai ? <Sparkles className="size-4" /> : null}
    </span>
  )
}

const itemClass = cn(
  'group/item relative flex h-11 cursor-default select-none items-center gap-3 rounded-button px-2.5 text-ui text-fg outline-none',
  'data-[selected=true]:bg-[color-mix(in_oklab,var(--pf-fg)_7%,transparent)] data-[disabled=true]:opacity-60',
)

function CommandRow({
  cmd,
  showGroup,
  onRun,
}: {
  cmd: AppCommand
  showGroup?: boolean
  onRun: (cmd: AppCommand) => void
}) {
  // gerade nicht ausführbar: gedimmt, nicht wählbar, der Grund steht statt des Untertitels da
  const reason = commandDisabledReason(cmd)
  return (
    <Command.Item value={`cmd:${cmd.id}`} disabled={Boolean(reason)} onSelect={() => onRun(cmd)} className={itemClass}>
      <ItemIcon icon={cmd.icon} ai={cmd.ai} />
      <span className="min-w-0 flex-1 truncate" title={reason ?? undefined}>
        <span className={cn(cmd.ai && 'text-gradient-spark font-medium')}>{cmd.title}</span>
        {(reason ?? cmd.subtitle) && <span className="ml-2 text-xs text-fg-subtle">{reason ?? cmd.subtitle}</span>}
      </span>
      {showGroup && cmd.group && <span className="shrink-0 text-2xs text-fg-subtle">{cmd.group}</span>}
      {cmd.hotkey && <Kbd hotkey={cmd.hotkey} size="xs" />}
      <CornerDownLeft className="hidden size-3.5 text-fg-subtle group-data-[selected=true]/item:block" />
    </Command.Item>
  )
}

export function CommandPalette() {
  const open = useUi((s) => s.commandPaletteOpen)
  const setOpen = useUi((s) => s.setCommandPaletteOpen)
  const navigate = useNavigate()
  const commands = useCommands()
  const version = useHealth().data?.version
  const [query, setQuery] = useState('')
  const provider = useProviderSearch(query, open)
  const q = query.trim()

  const close = () => setOpen(false)
  const ctx: CommandContext = { navigate, close }

  const groups = useMemo(() => {
    const map = new Map<string, AppCommand[]>()
    for (const c of commands) {
      const g = c.group ?? 'Aktionen'
      map.set(g, [...(map.get(g) ?? []), c])
    }
    return [...map.entries()].sort(
      ([a], [b]) => (GROUP_ORDER.indexOf(a) + 1 || 99) - (GROUP_ORDER.indexOf(b) + 1 || 99),
    )
  }, [commands])

  // Fokus nach dem Schließen dorthin zurück, wo er vorher war (die Palette hat keinen Auslöser-Button)
  const returnFocus = useReturnFocus(open)

  const ranked = useMemo(() => {
    if (!q) return null
    const seenTargets = new Set<string>()
    return commands
      .map((cmd) => ({ cmd, score: scoreCommand(cmd, q) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .filter(({ cmd }) => {
        // gleiches Ziel (z. B. „Serie erzeugen“ und „Serien-Assistent“) nur einmal anzeigen
        if (!cmd.target) return true
        if (seenTargets.has(cmd.target)) return false
        seenTargets.add(cmd.target)
        return true
      })
      .slice(0, MAX_RESULTS)
      .map((x) => x.cmd)
  }, [commands, q])

  const execute = (run: (c: CommandContext) => void | Promise<void>, keepOpen?: boolean) => {
    if (!keepOpen) close()
    // erst schließen, dann ausführen (Fokus/Dialoge der Zielseite nicht stören)
    setTimeout(() => void run(ctx), 0)
  }
  const runCmd = (cmd: AppCommand) => execute(cmd.run, cmd.keepOpen)
  const providerGroups = provider.groups.filter((g) => g.results.length > 0)

  return (
    <DialogPrimitive.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setQuery('')
      }}
    >
      <AnimatePresence>
        {open && (
          <DialogPrimitive.Portal forceMount>
            <DialogPrimitive.Overlay asChild forceMount>
              <motion.div
                className="fixed inset-0 z-palette bg-overlay backdrop-blur-[3px]"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              />
            </DialogPrimitive.Overlay>
            <div className="pointer-events-none fixed inset-0 z-palette flex items-start justify-center pt-[13vh]">
              <DialogPrimitive.Content
                asChild
                forceMount
                aria-modal="true"
                onCloseAutoFocus={returnFocus}
              >
                <motion.div
                  className="pf-palette pointer-events-auto relative w-[min(660px,calc(100vw-48px))] overflow-hidden rounded-panel border border-line-strong bg-[color-mix(in_oklab,var(--pf-surface)_94%,transparent)] shadow-pop backdrop-blur-2xl outline-none"
                  initial={{ opacity: 0, y: -10, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: -6, scale: 0.985, transition: { duration: 0.12 } }}
                  transition={{ type: 'spring', stiffness: 520, damping: 38 }}
                >
                  <DialogPrimitive.Title className="sr-only">Befehlspalette</DialogPrimitive.Title>
                  <span
                    aria-hidden
                    className="pointer-events-none absolute inset-x-16 top-0 h-px bg-[linear-gradient(90deg,transparent,var(--pf-accent),transparent)] opacity-70"
                  />
                  <Command loop vimBindings={false} shouldFilter={false} label="Befehlspalette" className="flex flex-col">
                    <div className="flex items-center gap-3 border-b border-line px-4">
                      <Search className="size-[18px] shrink-0 text-fg-subtle" />
                      <Command.Input
                        value={query}
                        onValueChange={setQuery}
                        placeholder="Wohin oder was? Seiten, Aktionen, Bauteile …"
                        className="h-14 flex-1 bg-transparent text-md text-fg outline-none placeholder:text-fg-subtle"
                      />
                      {provider.loading && <Spinner size={16} tone="accent" />}
                      <Kbd size="sm">Esc</Kbd>
                    </div>

                    <Command.List className="overflow-y-auto overscroll-contain px-2 py-2">
                      {ranked ? (
                        <>
                          {ranked.length > 0 && (
                            <Command.Group heading="Beste Treffer">
                              {ranked.map((cmd) => (
                                <CommandRow key={cmd.id} cmd={cmd} showGroup onRun={runCmd} />
                              ))}
                            </Command.Group>
                          )}
                          {providerGroups.map((g) => (
                            <Command.Group key={g.group} heading={g.group}>
                              {g.results.map((r) => (
                                <Command.Item
                                  key={r.id}
                                  value={`search:${r.id}`}
                                  onSelect={() => execute(r.run)}
                                  className={itemClass}
                                >
                                  <ItemIcon icon={r.icon} />
                                  <span className="min-w-0 flex-1 truncate">
                                    <span className={cn(r.mono !== false && 'mono')}>{r.title}</span>
                                    {r.subtitle && <span className="ml-2 text-xs text-fg-subtle">{r.subtitle}</span>}
                                  </span>
                                  {r.meta && (
                                    <span className="flex shrink-0 items-center gap-1.5 text-2xs text-fg-subtle">
                                      {r.color && (
                                        <span aria-hidden className="size-1.5 rounded-full" style={{ background: r.color }} />
                                      )}
                                      {r.meta}
                                    </span>
                                  )}
                                </Command.Item>
                              ))}
                            </Command.Group>
                          ))}
                          {ranked.length === 0 && providerGroups.length === 0 && !provider.loading && (
                            <div className="flex flex-col items-center gap-1 py-10 text-center">
                              <span className="text-ui font-medium text-fg">Keine Treffer</span>
                              <span className="text-xs text-fg-muted">
                                Für „{q}“ gibt es weder Befehl noch Bauteil. Versuchen Sie einen anderen Begriff.
                              </span>
                            </div>
                          )}
                        </>
                      ) : (
                        groups.map(([group, cmds]) => (
                          <Command.Group key={group} heading={group}>
                            {cmds.map((cmd) => (
                              <CommandRow key={cmd.id} cmd={cmd} onRun={runCmd} />
                            ))}
                          </Command.Group>
                        ))
                      )}
                    </Command.List>

                    <div className="flex h-10 items-center gap-4 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_50%,transparent)] px-4 text-2xs text-fg-subtle">
                      <span className="flex items-center gap-1.5">
                        <Kbd size="xs">↑</Kbd>
                        <Kbd size="xs">↓</Kbd>
                        navigieren
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Kbd size="xs">↵</Kbd>
                        ausführen
                      </span>
                      <span className="flex items-center gap-1.5">
                        <Kbd size="xs">Esc</Kbd>
                        schließen
                      </span>
                      <span className="ml-auto flex items-center gap-1.5">
                        <ForgeMark size={14} />
                        PartForge{version ? ` ${version}` : ''}
                      </span>
                    </div>
                  </Command>
                </motion.div>
              </DialogPrimitive.Content>
            </div>
          </DialogPrimitive.Portal>
        )}
      </AnimatePresence>
    </DialogPrimitive.Root>
  )
}
