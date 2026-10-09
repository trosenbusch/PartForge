import { motion } from 'motion/react'
import { Tabs as TabsPrimitive } from 'radix-ui'
import {
  createContext,
  useCallback,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ComponentProps,
  type ReactNode,
} from 'react'
import { cn } from '@/lib/cn'

type TabsVariant = 'underline' | 'pill'

interface TabsContextValue {
  value: string
  layoutId: string
  variant: TabsVariant
  /** Werte, zu denen ein `TabsContent` gerendert wird – nur deren Reiter verweisen per `aria-controls` darauf */
  panels: ReadonlySet<string>
  registerPanel: (value: string) => () => void
}

const NO_PANELS: ReadonlySet<string> = new Set()

const TabsContext = createContext<TabsContextValue>({
  value: '',
  layoutId: 'tabs',
  variant: 'underline',
  panels: NO_PANELS,
  registerPanel: () => () => undefined,
})

export interface TabsProps extends Omit<ComponentProps<typeof TabsPrimitive.Root>, 'value' | 'defaultValue' | 'onValueChange'> {
  value?: string
  defaultValue?: string
  onValueChange?: (value: string) => void
  variant?: TabsVariant
}

/**
 * Tabs mit animierter Markierung (Unterstrich oder Pille). Reiter ohne `TabsContent` (reine Umschalter, z. B.
 * „2D | 3D“) bekommen kein `aria-controls` auf ein nicht vorhandenes Element.
 */
export function Tabs({ value, defaultValue, onValueChange, variant = 'underline', className, children, ...props }: TabsProps) {
  const [internal, setInternal] = useState(defaultValue ?? '')
  const current = value ?? internal
  const layoutId = `tabs-${useId()}`
  // Zähler je Wert (zwei Inhalte mit gleichem Wert sind erlaubt), Menge als Zustand für die Reiter
  const counts = useRef(new Map<string, number>())
  const [panels, setPanels] = useState<ReadonlySet<string>>(NO_PANELS)
  const registerPanel = useCallback((v: string) => {
    const m = counts.current
    m.set(v, (m.get(v) ?? 0) + 1)
    setPanels(new Set(m.keys()))
    return () => {
      const n = (m.get(v) ?? 1) - 1
      if (n <= 0) m.delete(v)
      else m.set(v, n)
      setPanels(new Set(m.keys()))
    }
  }, [])
  return (
    <TabsContext.Provider value={{ value: current, layoutId, variant, panels, registerPanel }}>
      <TabsPrimitive.Root
        value={current}
        onValueChange={(v) => {
          if (value === undefined) setInternal(v)
          onValueChange?.(v)
        }}
        className={cn('flex flex-col', className)}
        {...props}
      >
        {children}
      </TabsPrimitive.Root>
    </TabsContext.Provider>
  )
}

export function TabsList({ className, ...props }: ComponentProps<typeof TabsPrimitive.List>) {
  const { variant } = useContext(TabsContext)
  return (
    <TabsPrimitive.List
      className={cn(
        'relative flex items-center',
        variant === 'underline' ? 'gap-1 border-b border-line' : 'gap-0.5 rounded-button border border-line bg-surface-2 p-0.5',
        className,
      )}
      {...props}
    />
  )
}

export interface TabsTriggerProps extends ComponentProps<typeof TabsPrimitive.Trigger> {
  icon?: ReactNode
  /** Zähler rechts (z. B. Anzahl Bauteile) */
  count?: ReactNode
}

export function TabsTrigger({ className, value, icon, count, children, ...props }: TabsTriggerProps) {
  const ctx = useContext(TabsContext)
  const active = ctx.value === value
  // Radix setzt aria-controls immer – ohne zugehörigen Inhalt zeigte es ins Leere (axe: aria-valid-attr-value)
  const orphan = props['aria-controls'] === undefined && !ctx.panels.has(value)
  return (
    <TabsPrimitive.Trigger
      value={value}
      className={cn(
        'relative z-0 flex items-center gap-2 whitespace-nowrap font-medium text-fg-muted outline-none transition-colors',
        'hover:text-fg focus-visible:text-fg data-[state=active]:text-fg disabled:pointer-events-none disabled:opacity-45',
        '[&_svg]:size-4',
        ctx.variant === 'underline'
          ? 'h-10 rounded-t-control px-3 text-ui focus-ring-inset'
          : 'h-7.5 rounded-control px-3 text-ui focus-ring',
        className,
      )}
      {...props}
      {...(orphan ? { 'aria-controls': undefined } : null)}
    >
      {icon}
      {children}
      {count !== undefined && (
        <span
          className={cn(
            'rounded-full px-1.5 text-2xs tabular-nums leading-4',
            active ? 'bg-surface-3 text-fg' : 'bg-surface-3 text-fg-subtle',
          )}
        >
          {count}
        </span>
      )}
      {active &&
        (ctx.variant === 'underline' ? (
          <motion.span
            layoutId={ctx.layoutId}
            aria-hidden
            className="absolute inset-x-2 -bottom-px h-[2px] rounded-full bg-gradient-forge shadow-[0_0_10px_var(--pf-glow-indicator)]"
            transition={{ type: 'spring', stiffness: 480, damping: 38 }}
          />
        ) : (
          <motion.span
            layoutId={ctx.layoutId}
            aria-hidden
            className="absolute inset-0 -z-10 rounded-control border border-line-strong bg-surface shadow-[0_1px_3px_rgba(0,0,0,.18)]"
            transition={{ type: 'spring', stiffness: 480, damping: 38 }}
          />
        ))}
    </TabsPrimitive.Trigger>
  )
}

/**
 * Inhalt eines Reiters. Radix macht ihn fokussierbar (Tab-Stopp nach der Reiterleiste, damit Inhalte ohne eigene
 * Bedienelemente per Tastatur erreichbar sind) – mit sichtbarem Fokusring nach innen, der **unter** dem Inhalt liegt
 * (`focus-ring-panel`): Er verdeckt keine Kanten oder Texte am Rand eines ungepolsterten Inhalts. Enthält der Inhalt
 * selbst fokussierbare Elemente (z. B. eine Leinwand), kann `tabIndex={-1}` den zusätzlichen Stopp entfernen.
 */
export function TabsContent({ className, value, ...props }: ComponentProps<typeof TabsPrimitive.Content>) {
  const { registerPanel } = useContext(TabsContext)
  useLayoutEffect(() => registerPanel(value), [registerPanel, value])
  return <TabsPrimitive.Content value={value} className={cn('outline-none focus-ring-panel', className)} {...props} />
}
