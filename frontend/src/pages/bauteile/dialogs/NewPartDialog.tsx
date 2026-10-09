/**
 * „Neues Bauteil“ (Strg+N): Kategorie, **Smart-Eingabe** („10k 1% 0603 Dickschicht“ → Felder; eine
 * Hersteller-Teilenummer wie „RC0603FR-0710KL“ wird über die Serienvorlagen gelesen und wählt bei Bedarf auch die
 * Kategorie), Pflichtangaben, Werte, Symbol/Footprint aus der Bibliothek (Vorschlag nur, wenn es ihn gibt – sonst
 * „Symbol erzeugen“) und weitere Angaben. Rechts die Live-Vorschau: erzeugte Texte (Wert, Kommentar, Beschreibung),
 * Teilenummer, Prüfergebnis und Symbol/Footprint.
 *
 * Tastatur: Enter in der Smart-Eingabe übernimmt sie und springt zum ersten offenen Pflichtfeld – angelegt wird nur
 * mit Strg+Enter (oder dem Knopf). Werte mit Hinweis („abc“ als Toleranz, ein Wert außerhalb der Auswahlliste) halten
 * das Anlegen an – der Fuß nennt die Ursache („1 Wert nicht in der Auswahlliste“); ein zweites Strg+Enter legt
 * trotzdem an.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import {
  ArrowRight,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  FolderTree,
  Hammer,
  Lightbulb,
  Plus,
  ScanLine,
  TriangleAlert,
  Wand,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type Ref } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { trackJob } from '@/api/jobs'
import { useCategories, type CategoryDef, type FieldDef } from '@/api/library'
import {
  fieldErrors,
  partsApi,
  partsKeys,
  PART_NUMBER,
  useLibraryFootprint,
  useLibraryFootprints,
  useLibrarySymbol,
  useLibrarySymbols,
  type DecodedPart,
  type PartWriteOut,
  type StandardSymbolMatch,
} from '@/api/parts'
import { symbolsApi, useSaveSymbol } from '@/api/symbols'
import type { Job } from '@/api/system'
import { CATEGORY_GROUP_ORDER, CATEGORY_GROUPS } from '@/components/data/categoryTreeItems'
import { CategoryIcon } from '@/components/data/CategoryIcon'
import { FootprintCanvas } from '@/components/preview/FootprintCanvas'
import { SymbolCanvas } from '@/components/preview/SymbolCanvas'
import {
  Badge,
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
  Kbd,
  Select,
  Skeleton,
  Spinner,
  type SelectGroupDef,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { useHotkey } from '@/lib/hotkeys'
import { useSaveHandler } from '@/app/commands'
import { formatNumber, plural } from '@/lib/format'
import { FieldInput } from '../components/FieldInput'
import { BOOKKEEPING, displayValue, FOOTPRINT_REF, ownWarnings, SYMBOL_REF } from '../model/fields'
import { mpnCandidate, suggestFootprint } from '../model/suggest'
import { useDebounced } from '../model/useDebounced'

export interface NewPartDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Vorausgewählte Kategorie (darf fehlen oder veraltet sein – dann fragt der Dialog) */
  defaultTable: string | null
  onCreated: (table: string, result: PartWriteOut) => void
  /** Bestehendes Bauteil öffnen (Konflikt der Teilenummer) */
  onOpenExisting: (table: string, pn: string) => void
}

/** Felder, die das Backend selbst führt oder die aus Verweisen folgen */
const AUTO_FIELDS = new Set(['Library Path', 'Footprint Path', 'Footprint Path 2', 'ComponentLink1Description'])
const GENERATED = ['Value', 'Comment', 'Description']
const BASICS = ['Manufacturer', 'Manufacturer Part Number', PART_NUMBER]
const LINKS = [SYMBOL_REF, FOOTPRINT_REF, 'ComponentLink1URL']
/** Hinweis „Pflichtfeld ist leer“ / „… fehlt“ – kein Eingabefehler, sondern noch offen */
const REQUIRED_MESSAGE = /pflichtfeld|fehlt/i

type Values = Record<string, string>

/** Ursache eines Feldhinweises – der Fuß fasst danach zusammen, statt alles „nicht lesbar“ zu nennen */
type HintCause = 'unreadable' | 'list' | 'unregistered' | 'other'
const HINT_CAUSES: readonly (readonly [RegExp, HintCause])[] = [
  [/nicht in der Auswahlliste/, 'list'],
  [/nicht in der Bibliothek registriert/, 'unregistered'],
  [/kein gültige[rs]? |keine ganze Zahl|kein Ja\/Nein-Wert|passt nicht zur Einheit|mehrdeutig/, 'unreadable'],
]
const HINT_CAUSE_TEXT: Record<HintCause, string> = {
  unreadable: 'nicht lesbar',
  list: 'nicht in der Auswahlliste',
  unregistered: 'nicht in der Bibliothek registriert',
  other: 'zu prüfen',
}
const HINT_CAUSE_ORDER: HintCause[] = ['unreadable', 'list', 'unregistered', 'other']

function hintCause(text: string): HintCause {
  return HINT_CAUSES.find(([re]) => re.test(text))?.[1] ?? 'other'
}

/** „1 Wert nicht in der Auswahlliste“, „2 Werte nicht lesbar, 1 nicht in der Auswahlliste“ (je Feld die erste Ursache) */
function hintSummary(hints: Record<string, string[]>): string {
  const counts = new Map<HintCause, number>()
  for (const list of Object.values(hints)) {
    if (!list.length) continue
    const cause = hintCause(list[0])
    counts.set(cause, (counts.get(cause) ?? 0) + 1)
  }
  return HINT_CAUSE_ORDER.filter((c) => counts.has(c))
    .map((c, i) => {
      const n = counts.get(c) ?? 0
      return `${i === 0 ? plural(n, 'Wert', 'Werte') : formatNumber(n)} ${HINT_CAUSE_TEXT[c]}`
    })
    .join(', ')
}

function clean(values: Values): Values {
  return Object.fromEntries(Object.entries(values).filter(([, v]) => v.trim() !== '').map(([k, v]) => [k, v.trim()]))
}

const fieldId = (column: string) => `np-${column.replace(/[^a-z0-9]+/gi, '-')}`

export function NewPartDialog({ open, onOpenChange, defaultTable, onCreated, onOpenExisting }: NewPartDialogProps) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const categories = useCategories()
  /** Ausdrücklich gewählte Kategorie (null = Vorgabe bzw. erkannt) */
  const [chosen, setChosen] = useState<string | null>(null)
  const [values, setValues] = useState<Values>({})
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [suggested, setSuggested] = useState<Set<string>>(new Set())
  const [smartText, setSmartText] = useState('')
  /** Smart-Eingabe sofort auswerten (Enter) statt nach der Entprellung */
  const [smartFlush, setSmartFlush] = useState<string | null>(null)
  const [assigned, setAssigned] = useState<Record<string, string>>({})
  const [submitted, setSubmitted] = useState(false)
  const [moreOpen, setMoreOpen] = useState(false)
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  /** Werte, für die die Hinweise (nicht lesbare Werte) gezeigt wurden – zweites Strg+Enter legt trotzdem an */
  const [warnedFor, setWarnedFor] = useState<string | null>(null)
  const smartKeys = useRef<string[]>([])
  const smartRef = useRef<HTMLInputElement>(null)
  /** Nach Enter in der Smart-Eingabe: zum ersten offenen Pflichtfeld springen, sobald die Werte übernommen sind */
  const jumpAfterSmart = useRef(false)

  // Beim Öffnen neu beginnen (abgeleiteter Zustand statt Effekt)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setChosen(null)
      setValues({})
      setTouched(new Set())
      setSuggested(new Set())
      setSmartText('')
      setSmartFlush(null)
      setAssigned({})
      setSubmitted(false)
      setMoreOpen(false)
      setServerErrors({})
      setSubmitError(null)
      setWarnedFor(null)
      smartKeys.current = []
    }
  }

  // ------------------------------------------------------------------ Kategorie (beim Rendern bestimmt)
  const findCategory = (t: string | null | undefined) =>
    t ? (categories.data?.find((c) => c.table.toLowerCase() === t.toLowerCase()) ?? null) : null

  // Smart-Eingabe + Teilenummern-Erkennung (die Erkennung braucht keine Kategorie – sie kann sie liefern)
  const debouncedSmart = useDebounced(smartText.trim(), 320)
  const smartQuery = smartFlush !== null && smartFlush === smartText.trim() ? smartFlush : debouncedSmart
  const candidate = smartQuery ? mpnCandidate(smartQuery) : null
  const decode = useQuery({
    queryKey: ['parts', 'decode', candidate] as const,
    queryFn: ({ signal }) => partsApi.decode(candidate as string, signal),
    enabled: open && Boolean(candidate),
    staleTime: Infinity,
    retry: false,
  })
  const decodedAny: DecodedPart | null = candidate && decode.data?.best && decode.data.best.valid ? decode.data.best : null

  const category = findCategory(chosen) ?? findCategory(defaultTable) ?? findCategory(decodedAny?.category)
  const table = category?.table ?? null
  const fields = useMemo(() => new Map((category?.fields ?? []).map((f) => [f.column, f])), [category])
  const decoded = decodedAny && table && decodedAny.category.toLowerCase() === table.toLowerCase() ? decodedAny : null
  const decodedOther = decodedAny && table && !decoded ? decodedAny : null

  const smart = useQuery({
    queryKey: [...partsKeys.table(table ?? ''), 'smart-fill', smartQuery] as const,
    queryFn: ({ signal }) => partsApi.smartFill(table as string, smartQuery, signal),
    enabled: open && Boolean(table && smartQuery),
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  })

  // Ergebnisse übernehmen – nur in Felder, die der Nutzer nicht selbst bearbeitet hat
  const smartData = smartQuery && table ? smart.data : undefined
  const tokens = useMemo(() => new Set(smartQuery.split(/[\s,;]+/).filter(Boolean)), [smartQuery])
  useEffect(() => {
    if (!open || !category) return
    const next: Values = {}
    if (decoded) {
      for (const [k, v] of Object.entries(decoded.fields)) if (fields.has(k)) next[k] = v
      if (decoded.manufacturer) next.Manufacturer = decoded.manufacturer
      next['Manufacturer Part Number'] = decoded.mpn
    }
    for (const [k, v] of Object.entries(smartData?.values ?? {})) if (fields.has(k)) next[k] = v
    // zugeordnete Wörter nur, solange sie noch in der Eingabe stehen
    for (const [token, col] of Object.entries(assigned)) if (fields.has(col) && tokens.has(token)) next[col] = token
    const previous = smartKeys.current
    smartKeys.current = Object.keys(next)
    setValues((current) => {
      const out = { ...current }
      for (const k of previous) if (!(k in next) && !touched.has(k)) delete out[k]
      for (const [k, v] of Object.entries(next)) if (!touched.has(k)) out[k] = v
      return out
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `touched` nur lesen, nicht auslösen
  }, [smartData, decoded, assigned, tokens, category, open])

  const unmatched = (smartData?.unmatched ?? []).filter((t) => !(t in assigned) && !(decoded && t === candidate))

  // ------------------------------------------------------------------ Vorschläge für Symbol und Footprint
  const valueFields = useMemo(() => {
    if (!category) return {}
    return Object.fromEntries(category.fields.filter((f) => !f.common && values[f.column]).map((f) => [f.column, values[f.column]]))
  }, [category, values])
  const debouncedValueFields = useDebounced(valueFields, 400)
  const standardSymbol = useQuery({
    queryKey: partsKeys.standardSymbol(table ?? '', debouncedValueFields),
    queryFn: ({ signal }) => partsApi.standardSymbol(table as string, debouncedValueFields, signal),
    enabled: open && Boolean(table),
    staleTime: 60_000,
    retry: false,
  })
  const symbolList = useLibrarySymbols(open)
  const footprintList = useLibraryFootprints(open)
  const registeredSymbols = useMemo(() => new Set((symbolList.data ?? []).map((s) => s.name.toLowerCase())), [symbolList.data])
  const registeredFootprints = useMemo(() => new Set((footprintList.data ?? []).map((s) => s.name.toLowerCase())), [footprintList.data])
  const footprintSuggestion = useMemo(
    () => (table && footprintList.data ? suggestFootprint(table, values, footprintList.data) : null),
    [table, values, footprintList.data],
  )
  const standardName = standardSymbol.data?.name ?? null
  // Nur vorschlagen, was es in der Bibliothek gibt – sonst „Symbol erzeugen“ anbieten (Liste fehlt = Welle 2 → frei)
  const listKnown = Boolean(symbolList.data)
  const symbolSuggestion = standardName && (!listKnown || registeredSymbols.has(standardName.toLowerCase())) ? standardName : null
  const missingStandard: StandardSymbolMatch | null =
    standardSymbol.data && standardName && listKnown && !registeredSymbols.has(standardName.toLowerCase()) ? standardSymbol.data : null

  useEffect(() => {
    if (!open) return
    const apply = (col: string, name: string | null) => {
      if (touched.has(col)) return
      setValues((v) => {
        const current = v[col] ?? ''
        if (!name) {
          if (current && suggested.has(col)) {
            const out = { ...v }
            delete out[col]
            return out
          }
          return v
        }
        if (current && !suggested.has(col)) return v
        return current === name ? v : { ...v, [col]: name }
      })
      setSuggested((s) => {
        if (!name === !s.has(col)) return s
        const next = new Set(s)
        if (name) next.add(col)
        else next.delete(col)
        return next
      })
    }
    apply(SYMBOL_REF, symbolSuggestion)
    if (fields.has(FOOTPRINT_REF)) apply(FOOTPRINT_REF, footprintSuggestion)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- nur bei neuen Vorschlägen
  }, [symbolSuggestion, footprintSuggestion, open])

  // Fehlendes Standardsymbol direkt erzeugen (Generator-Anfrage aus „standard-for“ → Vorschau → speichern)
  const saveSymbol = useSaveSymbol()
  const [generating, setGenerating] = useState(false)
  const generateSymbol = async (match: StandardSymbolMatch) => {
    if (!match.request || !table) return
    setGenerating(true)
    try {
      const preview = await symbolsApi.preview(match.request)
      const result = await saveSymbol.mutateAsync({
        spec: preview.spec,
        category: table,
        source: 'generated',
        allow_pinout_change: false,
      })
      const name = result.kind === 'saved' ? result.record.name : preview.spec.name
      if (result.kind === 'job') {
        trackJob(result.job as Job, { openDock: false })
        toast.success(`Symbol „${name}“ wird geschrieben`, {
          description: result.out.library ? `Ziel: ${result.out.library} – das Job-Dock meldet den Abschluss.` : 'Das Job-Dock meldet den Abschluss.',
        })
      } else {
        toast.success(`Symbol „${name}“ erzeugt`, { description: `In ${result.record.library} geschrieben.` })
      }
      void qc.invalidateQueries({ queryKey: partsKeys.symbols })
      setValues((v) => ({ ...v, [SYMBOL_REF]: name }))
      setSuggested((s) => new Set(s).add(SYMBOL_REF))
    } catch (err) {
      toast.error('Symbol nicht erzeugt', {
        description: errorMessage(err),
        action: match.kind ? { label: 'Im Generator öffnen', onClick: () => navigate(`/symbole?art=${encodeURIComponent(match.kind ?? '')}`) } : undefined,
      })
    } finally {
      setGenerating(false)
    }
  }

  // ------------------------------------------------------------------ Live-Prüfung (Texte, Fehler, Konflikt)
  const debouncedValues = useDebounced(clean(values), 260)
  const validation = useQuery({
    queryKey: [...partsKeys.table(table ?? ''), 'validate-new', debouncedValues] as const,
    queryFn: ({ signal }) => partsApi.validate(table as string, debouncedValues, { signal }),
    enabled: open && Boolean(table),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    retry: false,
  })
  const result = validation.data
  const errors = { ...(result?.errors ?? {}), ...serverErrors }
  const blocking = Object.entries(errors).filter(([, msg]) => !REQUIRED_MESSAGE.test(msg))
  const missing = Object.entries(errors).filter(([, msg]) => REQUIRED_MESSAGE.test(msg))
  const conflict = result?.conflict ?? null
  // Hinweise je Feld (nicht lesbare Werte, nicht registrierte Symbole/Footprints)
  const fieldHints = useMemo(() => {
    const out: Record<string, string[]> = {}
    for (const f of category?.fields ?? []) {
      const own = ownWarnings(f, result?.warnings ?? [])
      if (own.length) out[f.column] = own
    }
    const symbol = values[SYMBOL_REF]?.trim()
    if (symbol && symbolList.data && !registeredSymbols.has(symbol.toLowerCase())) {
      ;(out[SYMBOL_REF] ??= []).push(`„${symbol}“ ist nicht in der Bibliothek registriert – Altium findet es nur, wenn die SchLib es enthält.`)
    }
    const footprint = values[FOOTPRINT_REF]?.trim()
    if (footprint && footprintList.data && !registeredFootprints.has(footprint.toLowerCase())) {
      ;(out[FOOTPRINT_REF] ??= []).push(`„${footprint}“ ist nicht in der Bibliothek registriert – Altium findet ihn nur, wenn die PcbLib ihn enthält.`)
    }
    return out
  }, [category, result?.warnings, values, symbolList.data, footprintList.data, registeredSymbols, registeredFootprints])
  const hintCount = Object.keys(fieldHints).length
  const otherWarningsList = (result?.warnings ?? []).filter(
    (w) => !(category?.fields ?? []).some((f) => w.startsWith(`${f.label}:`) && fieldHints[f.column]),
  )
  const ready = Boolean(result) && Object.keys(errors).length === 0 && !conflict
  // Als Entwurf: nur Pflichtfelder offen – die Teilenummer (bzw. Hersteller-Teilenummer) muss aber feststehen
  const canDraft =
    Boolean(result) && blocking.length === 0 && !conflict && missing.length > 0 && Boolean(result?.values[PART_NUMBER]) && !errors[PART_NUMBER]

  // ------------------------------------------------------------------ Anlegen
  const create = useMutation({
    mutationFn: (draft: boolean) => partsApi.create(table as string, clean(values), draft),
    meta: { silentError: true },
    onSuccess: (res) => {
      onCreated(table as string, res)
      onOpenChange(false)
    },
    onError: (err) => {
      setServerErrors(fieldErrors(err))
      setSubmitError(errorMessage(err))
    },
  })

  const setField = (col: string, value: string) => {
    setValues((v) => ({ ...v, [col]: value }))
    setTouched((t) => (t.has(col) ? t : new Set(t).add(col)))
    if (suggested.has(col)) setSuggested((s) => { const n = new Set(s); n.delete(col); return n })
    if (serverErrors[col]) setServerErrors((e) => { const n = { ...e }; delete n[col]; return n })
    setSubmitError(null)
    setWarnedFor(null)
  }

  const changeTable = (next: string) => {
    const target = categories.data?.find((c) => c.table === next)
    setChosen(next)
    if (target) {
      const allowed = new Set(target.fields.map((f) => f.column))
      setValues((v) => Object.fromEntries(Object.entries(v).filter(([k]) => allowed.has(k))))
    }
    setSuggested(new Set())
    setServerErrors({})
    setSubmitError(null)
    setWarnedFor(null)
  }

  // ------------------------------------------------------------------ Felder gliedern
  const sections = useMemo(() => {
    if (!category) return null
    const usable = category.fields.filter((f) => !BOOKKEEPING.has(f.column) && !AUTO_FIELDS.has(f.column))
    const values_ = usable.filter((f) => !f.common).sort((a, b) => Number(b.required) - Number(a.required))
    const basics = BASICS.map((c) => fields.get(c)).filter((f): f is FieldDef => Boolean(f))
    const links = LINKS.map((c) => fields.get(c)).filter((f): f is FieldDef => Boolean(f))
    const taken = new Set([...basics, ...values_, ...links].map((f) => f.column))
    const more = usable.filter((f) => !taken.has(f.column) && !GENERATED.includes(f.column))
    const generated = GENERATED.map((c) => fields.get(c)).filter((f): f is FieldDef => Boolean(f))
    return { basics, values: values_, links, more: [...more, ...generated] }
  }, [category, fields])

  /** Erstes offenes Pflichtfeld (in der Reihenfolge des Formulars) */
  const firstMissing = (current: Values): string | null => {
    if (!sections) return null
    const order = [...sections.basics, ...sections.values, ...sections.links]
    for (const f of order) {
      if (!f.required || GENERATED.includes(f.column)) continue
      if (f.column === PART_NUMBER) continue // leer = Hersteller-Teilenummer
      if (!current[f.column]?.trim()) return f.column
    }
    return null
  }

  // Nach Enter in der Smart-Eingabe: warten, bis Erkennung/Smart-Fill übernommen sind, dann springen
  const smartBusy = (smart.isFetching || decode.isFetching) && Boolean(smartQuery)
  useEffect(() => {
    if (!jumpAfterSmart.current || smartBusy || !open) return
    if (smartFlush !== null && smartQuery !== smartFlush) return
    jumpAfterSmart.current = false
    const target = firstMissing(values)
    if (target) {
      const el = document.getElementById(fieldId(target))
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el?.focus({ preventScroll: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `firstMissing` liest nur
  }, [smartBusy, values, smartQuery, smartFlush, open])

  const applySmart = () => {
    setSmartFlush(smartText.trim())
    jumpAfterSmart.current = true
  }

  const [checking, setChecking] = useState(false)
  const submit = async (draft: boolean) => {
    setSubmitted(true)
    if (!table || create.isPending || checking) return
    // Prüfung zum aktuellen Stand (die Live-Prüfung ist entprellt und kann einen Tastendruck zurückliegen)
    const current = clean(values)
    let check = result
    if (!check || validation.isFetching || JSON.stringify(current) !== JSON.stringify(debouncedValues)) {
      setChecking(true)
      try {
        check = await partsApi.validate(table, current)
      } catch {
        check = undefined // Prüfung nicht möglich – das Anlegen meldet Fehler selbst
      } finally {
        setChecking(false)
      }
    }
    if (check) {
      const errs = check.errors
      const block = Object.entries(errs).filter(([, m]) => !REQUIRED_MESSAGE.test(m))
      const ok = Object.keys(errs).length === 0 && !check.conflict
      const draftOk = block.length === 0 && !check.conflict && Boolean(check.values[PART_NUMBER]) && !errs[PART_NUMBER]
      if (draft ? !draftOk : !ok) {
        const first = Object.keys(errs)[0]
        if (first) document.getElementById(fieldId(first))?.focus()
        return
      }
      // Nicht lesbare Werte: erst zeigen, beim zweiten Mal (gleiche Werte) trotzdem anlegen
      const warned = (category?.fields ?? []).filter((f) => ownWarnings(f, check?.warnings ?? []).length)
      const key = JSON.stringify(current)
      if (warned.length && warnedFor !== key) {
        setWarnedFor(key)
        document.getElementById(fieldId(warned[0].column))?.focus()
        return
      }
    }
    create.mutate(draft)
  }
  const onSubmit = (e: FormEvent) => {
    e.preventDefault()
    void submit(false)
  }
  // Strg+Enter legt an – auch aus Eingabefeldern heraus; Strg+S ebenso (modal: speichert den Dialog, nicht die Seite)
  useHotkey('mod+enter', () => void submit(false), { enabled: open && Boolean(category), allowInInputs: true })
  useSaveHandler(() => void submit(false), { modal: true, enabled: open && Boolean(category) })

  // Enter in einem Eingabefeld legt nie an (implizites Absenden) – es springt zum nächsten offenen Pflichtfeld
  const onFormKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Enter' || e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return
    const target = e.target as HTMLElement
    if (target.tagName !== 'INPUT' || (target as HTMLInputElement).type === 'checkbox') return
    e.preventDefault()
    if (target === smartRef.current) {
      applySmart()
      return
    }
    const next = firstMissing(values)
    if (next && fieldId(next) !== target.id) document.getElementById(fieldId(next))?.focus()
  }
  const formKeyHandler = useRef(onFormKeyDown)
  useEffect(() => {
    formKeyHandler.current = onFormKeyDown
  })
  const [formEl, setFormEl] = useState<HTMLFormElement | null>(null)
  useEffect(() => {
    if (!formEl) return
    const listener = (e: KeyboardEvent) => formKeyHandler.current(e)
    formEl.addEventListener('keydown', listener)
    return () => formEl.removeEventListener('keydown', listener)
  }, [formEl])

  const showError = (col: string) => (submitted || touched.has(col) ? errors[col] : undefined)
  const categoryGroups = useCategoryGroups(categories.data ?? [])
  const warnedNow = warnedFor !== null && warnedFor === JSON.stringify(clean(values))

  const formField = (f: FieldDef, extra: Partial<FormFieldProps> = {}) => (
    <FormField
      key={f.column}
      field={f}
      table={table as string}
      value={values[f.column] ?? ''}
      error={showError(f.column)}
      hints={fieldHints[f.column]}
      onChange={(v) => setField(f.column, v)}
      {...extra}
    />
  )

  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent
        size="xl"
        className="max-w-[min(64rem,calc(100vw-48px))]"
        onOpenAutoFocus={(e) => {
          // Start in der Smart-Eingabe (die Kategorie ist meist schon passend vorausgewählt)
          e.preventDefault()
          smartRef.current?.focus({ preventScroll: true })
        }}
      >
        <form ref={setFormEl} onSubmit={onSubmit} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader
            icon={<Plus />}
            tone="accent"
            title="Neues Bauteil"
            description="Werte eintippen wie im Gespräch – die Smart-Eingabe verteilt sie auf die Felder. Wert, Kommentar und Beschreibung entstehen aus den Vorlagen der Kategorie."
          />
          <DialogBody className="grid min-h-0 grid-cols-1 gap-6 pt-3 @container md:grid-cols-[minmax(0,1fr)_17.5rem]">
            {/* ------------------------------------------------ Eingaben */}
            <div className="flex min-w-0 flex-col gap-5">
              <div className="grid grid-cols-[minmax(0,15rem)_minmax(0,1fr)] gap-3">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="np-category" className="text-ui font-medium text-fg">
                    Kategorie
                  </label>
                  <Select
                    id="np-category"
                    value={table ?? undefined}
                    onValueChange={changeTable}
                    groups={categoryGroups}
                    placeholder={categories.isPending ? 'Kategorien werden geladen …' : 'Kategorie wählen …'}
                    disabled={categories.isPending}
                  />
                </div>
                <SmartInput
                  inputRef={smartRef}
                  value={smartText}
                  onChange={setSmartText}
                  busy={smartBusy}
                  disabled={categories.isPending}
                  example={smartExample(category)}
                />
              </div>

              <SmartResult
                category={category}
                recognized={smartKeys.current.filter((k) => values[k] && !touched.has(k))}
                values={values}
                decoded={decoded}
                decodedOther={decodedOther}
                unmatched={unmatched}
                onAssign={(token, col) => setAssigned((a) => ({ ...a, [token]: col }))}
                onSwitchCategory={(t) => changeTable(t)}
                categories={categories.data ?? []}
              />

              {category && sections ? (
                <>
                  <FieldSection title="Grunddaten">
                    {sections.basics.map((f) =>
                      formField(
                        f,
                        f.column === PART_NUMBER
                          ? {
                              placeholder: partNumberPlaceholder(values, result?.values[PART_NUMBER]),
                              hint: 'leer = Hersteller-Teilenummer',
                              required: false,
                            }
                          : {},
                      ),
                    )}
                  </FieldSection>
                  {sections.values.length > 0 && (
                    <FieldSection title={`Werte · ${category.label}`}>
                      {sections.values.map((f) =>
                        formField(f, { smart: smartKeys.current.includes(f.column) && !touched.has(f.column) }),
                      )}
                    </FieldSection>
                  )}
                  <FieldSection title="Symbol, Footprint und Datenblatt">
                    {sections.links.map((f) =>
                      formField(f, {
                        suggestion: suggested.has(f.column) ? 'Vorschlag' : undefined,
                        below:
                          f.column === SYMBOL_REF && missingStandard && !values[SYMBOL_REF] ? (
                            <MissingSymbol match={missingStandard} busy={generating} onGenerate={() => void generateSymbol(missingStandard)} />
                          ) : undefined,
                      }),
                    )}
                  </FieldSection>
                  <div className="flex flex-col gap-3">
                    <button
                      type="button"
                      onClick={() => setMoreOpen((o) => !o)}
                      aria-expanded={moreOpen}
                      className="flex items-center gap-2 self-start rounded-control text-ui font-medium text-fg-muted outline-none hover:text-fg focus-ring"
                    >
                      <ChevronRight aria-hidden className={cn('size-4 transition-transform', moreOpen && 'rotate-90')} />
                      Weitere Angaben
                      <span className="text-xs font-normal text-fg-subtle">
                        Gehäuse, Lieferanten, Lebenszyklus, Texte überschreiben …
                      </span>
                    </button>
                    <AnimatePresence initial={false}>
                      {moreOpen && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                          className="overflow-hidden"
                        >
                          <div className="grid grid-cols-1 gap-x-4 gap-y-3 pb-1 @[34rem]:grid-cols-2">
                            {sections.more.map((f) =>
                              formField(f, {
                                placeholder: GENERATED.includes(f.column) ? result?.rendered[f.column] || 'aus Vorlage' : undefined,
                                hint: GENERATED.includes(f.column) ? 'leer = aus Vorlage' : undefined,
                                required: GENERATED.includes(f.column) ? false : undefined,
                                wide: f.column === 'Notes' || f.column === 'Description',
                              }),
                            )}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </>
              ) : categories.isPending ? (
                <div className="flex flex-col gap-3" aria-hidden>
                  {Array.from({ length: 4 }, (_, i) => (
                    <Skeleton key={i} className="h-9" />
                  ))}
                </div>
              ) : (
                <ChooseCategory categories={categories.data ?? []} onChoose={changeTable} />
              )}
            </div>

            {/* ------------------------------------------------ Vorschau */}
            <aside aria-label="Vorschau des neuen Bauteils" className="flex min-w-0 flex-col gap-3 md:sticky md:top-0 md:self-start">
              <Summary
                category={category}
                categories={categories.data ?? []}
                symbolName={values[SYMBOL_REF] ?? ''}
                footprintName={values[FOOTPRINT_REF] ?? ''}
                partNumber={result?.values[PART_NUMBER] ?? null}
                rendered={category ? (result?.rendered ?? null) : null}
                checking={validation.isFetching}
                blocking={blocking.map(([c, m]) => [fields.get(c)?.label ?? c, m] as const)}
                missing={missing
                  // ohne Hersteller-Teilenummer fehlt die Teilenummer automatisch mit – nur einmal nennen
                  .filter(([c]) => !(c === PART_NUMBER && errors['Manufacturer Part Number']))
                  .map(([c]) => fields.get(c)?.label ?? c)}
                hinted={Object.keys(fieldHints).map((c) => fields.get(c)?.label ?? c)}
                warnings={otherWarningsList}
                conflict={conflict}
                ready={ready && hintCount === 0}
                onOpenExisting={(t, pn) => {
                  onOpenChange(false)
                  onOpenExisting(t, pn)
                }}
              />
            </aside>
          </DialogBody>
          <DialogFooter className="justify-between">
            <div className="min-w-0 text-xs text-fg-muted" aria-live="polite">
              {submitError ? (
                <span className="flex items-center gap-1.5 text-danger-text">
                  <CircleAlert aria-hidden className="size-3.5 shrink-0" />
                  <span className="line-clamp-2">{submitError}</span>
                </span>
              ) : warnedNow ? (
                <span className="flex items-center gap-1.5 text-warning-text">
                  <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
                  <span className="line-clamp-2">
                    {hintSummary(fieldHints)} – erneut <Kbd hotkey="mod+enter" size="xs" /> legt trotzdem an
                  </span>
                </span>
              ) : (
                <span className="hidden items-center gap-1.5 sm:flex">
                  <Kbd hotkey="mod+enter" size="xs" /> anlegen
                  <span aria-hidden className="text-fg-subtle">
                    ·
                  </span>
                  <Kbd size="xs">Enter</Kbd> nächstes Pflichtfeld
                </span>
              )}
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={create.isPending}>
                Abbrechen
              </Button>
              {canDraft && (
                <Button variant="secondary" onClick={() => void submit(true)} loading={create.isPending && create.variables === true}>
                  Als Entwurf anlegen
                </Button>
              )}
              <Button
                type="submit"
                variant="primary"
                leftIcon={<Plus />}
                loading={checking || (create.isPending && create.variables === false)}
                disabled={!category}
                aria-keyshortcuts="Control+Enter"
              >
                {warnedNow ? 'Trotzdem anlegen' : 'Bauteil anlegen'}
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// --------------------------------------------------------------------------- Bausteine

function partNumberPlaceholder(values: Values, resolved: string | null | undefined): string {
  return resolved || values['Manufacturer Part Number'] || '= Hersteller-Teilenummer'
}

function smartExample(category: CategoryDef | null): string {
  switch (category?.table) {
    case 'Resistors':
      return 'z. B. 10k 1% 0603 oder RC0603FR-0710KL'
    case 'Capacitors':
      return 'z. B. 100n 50V X7R 0603'
    case 'Inductors':
      return 'z. B. 4u7 2A geschirmt'
    case 'LEDs':
      return 'z. B. Grün 0603 20mA'
    case 'Connectors':
      return 'z. B. Stiftleiste 2,54mm gerade'
    case undefined:
      return 'Hersteller-Teilenummer – erkennt die Kategorie'
    default:
      return 'Werte, Bauform oder Teilenummer …'
  }
}

function useCategoryGroups(list: CategoryDef[]): SelectGroupDef[] {
  return useMemo(() => {
    const map = new Map<string, CategoryDef[]>()
    for (const c of list) {
      const g = CATEGORY_GROUPS[c.table] ?? 'Weitere'
      map.set(g, [...(map.get(g) ?? []), c])
    }
    return [...map.entries()]
      .sort(([a], [b]) => CATEGORY_GROUP_ORDER.indexOf(a) - CATEGORY_GROUP_ORDER.indexOf(b))
      .map(([label, items]) => ({
        label,
        options: items.map((c) => ({
          value: c.table,
          label: c.label,
          icon: <CategoryIcon name={c.icon} color={c.color} />,
          badge: <span className="mono text-2xs text-fg-subtle">{formatNumber(c.part_count ?? 0)}</span>,
        })),
      }))
  }, [list])
}

/** Ohne (gültige) Vorauswahl: Kategorie wählen – die häufigsten als Schnellwahl */
function ChooseCategory({ categories, onChoose }: { categories: CategoryDef[]; onChoose: (table: string) => void }) {
  const top = [...categories].sort((a, b) => (b.part_count ?? 0) - (a.part_count ?? 0)).slice(0, 6)
  if (!categories.length) {
    return (
      <Callout
        tone="warning"
        title="Noch keine Kategorie"
        actions={
          <Button asChild variant="secondary" size="sm">
            <Link to="/einstellungen/kategorien">
              Kategorien und Felder öffnen
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        }
      >
        Legen Sie zuerst unter „Einstellungen › Kategorien und Felder“ eine Kategorie an.
      </Callout>
    )
  }
  return (
    <section aria-labelledby="np-choose" className="flex flex-col gap-3 rounded-card border border-dashed border-line-strong px-4 py-4">
      <div className="flex items-start gap-3">
        <span aria-hidden className="flex size-8 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted">
          <FolderTree className="size-4" />
        </span>
        <div>
          <h3 id="np-choose" className="text-ui font-medium text-fg">
            Kategorie wählen
          </h3>
          <p className="text-xs leading-relaxed text-fg-muted">
            Oben auswählen – oder eine Hersteller-Teilenummer in die Smart-Eingabe tippen, dann wird die Kategorie erkannt.
          </p>
        </div>
      </div>
      <ul className="grid grid-cols-2 gap-1.5 @[34rem]:grid-cols-3" aria-label="Häufige Kategorien">
        {top.map((c) => (
          <li key={c.table}>
            <button
              type="button"
              onClick={() => onChoose(c.table)}
              className="flex h-8 w-full items-center gap-2 rounded-control border border-line px-2.5 text-left text-ui text-fg outline-none transition-colors hover:border-line-strong hover:bg-surface-2 focus-ring"
            >
              <CategoryIcon name={c.icon} color={c.color} className="size-3.5 shrink-0" />
              <span className="min-w-0 flex-1 truncate">{c.label}</span>
              <span className="mono text-2xs text-fg-subtle">{formatNumber(c.part_count ?? 0)}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SmartInput({
  value,
  onChange,
  busy,
  disabled,
  example,
  inputRef,
}: {
  value: string
  onChange: (v: string) => void
  busy: boolean
  disabled: boolean
  example: string
  inputRef: Ref<HTMLInputElement>
}) {
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor="np-smart" className="flex items-center gap-1.5 text-ui font-medium text-fg">
        Smart-Eingabe
        <span className="truncate text-2xs font-normal text-fg-subtle">Werte, Bauform, Hersteller-Teilenummer</span>
      </label>
      <div
        className={cn(
          'group/smart relative flex h-8.5 items-center gap-2 rounded-button border border-line-control bg-control px-3 transition-[border-color,box-shadow] duration-150',
          'focus-within:border-accent focus-within:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
          disabled && 'pointer-events-none opacity-55',
        )}
      >
        <Wand aria-hidden className="size-4 shrink-0 text-accent" />
        <input
          id="np-smart"
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={example}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
          aria-describedby="np-smart-help"
          className="mono h-full min-w-0 flex-1 bg-transparent text-ui text-fg outline-none placeholder:font-sans placeholder:text-fg-subtle"
        />
        <span id="np-smart-help" className="sr-only">
          Enter übernimmt die Eingabe und springt zum ersten offenen Pflichtfeld. Strg+Enter legt das Bauteil an.
        </span>
        {busy ? (
          <Spinner size={14} tone="accent" />
        ) : value ? (
          <button
            type="button"
            onClick={() => onChange('')}
            aria-label="Smart-Eingabe leeren"
            className="flex size-5 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
          >
            <X aria-hidden className="size-3.5" />
          </button>
        ) : null}
      </div>
    </div>
  )
}

const ASSIGN_TARGETS: { column: string; label: string }[] = [
  { column: 'Manufacturer', label: 'als Hersteller' },
  { column: 'Manufacturer Part Number', label: 'als Hersteller-Teilenummer' },
  { column: 'Package', label: 'als Gehäuse' },
  { column: 'Notes', label: 'als Notiz' },
]

function SmartResult({
  category,
  recognized,
  values,
  decoded,
  decodedOther,
  unmatched,
  onAssign,
  onSwitchCategory,
  categories,
}: {
  category: CategoryDef | null
  recognized: string[]
  values: Values
  decoded: DecodedPart | null
  decodedOther: DecodedPart | null
  unmatched: string[]
  onAssign: (token: string, column: string) => void
  onSwitchCategory: (table: string) => void
  categories: CategoryDef[]
}) {
  const fields = new Map((category?.fields ?? []).map((f) => [f.column, f]))
  const otherCategory = decodedOther ? categories.find((c) => c.table.toLowerCase() === decodedOther.category.toLowerCase()) : null
  const visible = recognized.length > 0 || unmatched.length > 0 || decoded || decodedOther
  if (!visible) return null
  return (
    <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} className="-mt-2 flex flex-col gap-2">
      {decoded && !decodedOther && (
        <p className="flex items-center gap-2 text-xs text-fg-muted">
          <ScanLine aria-hidden className="size-3.5 shrink-0 text-accent-text" />
          Teilenummer erkannt: <span className="font-medium text-fg">{decoded.template_title}</span>
        </p>
      )}
      {decodedOther && otherCategory && (
        <Callout
          tone="info"
          icon={<Lightbulb />}
          title={`„${decodedOther.mpn}“ gehört zu „${otherCategory.label}“`}
          actions={
            <Button size="sm" variant="secondary" rightIcon={<ArrowRight />} onClick={() => onSwitchCategory(otherCategory.table)}>
              Kategorie wechseln
            </Button>
          }
        >
          {decodedOther.template_title}
        </Callout>
      )}
      {(recognized.length > 0 || unmatched.length > 0) && (
        <ul aria-label="Ergebnis der Smart-Eingabe" className="flex flex-wrap items-center gap-1.5">
          {recognized.map((col) => (
            <li key={col}>
              <Badge variant="neutral" className="gap-1">
                <span className="font-normal text-fg-muted">{fields.get(col)?.label ?? col}</span>
                <span className="mono text-fg">{displayValue(fields.get(col), values[col])}</span>
              </Badge>
            </li>
          ))}
          {unmatched.map((token) => (
            <li key={token}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="inline-flex h-5 items-center gap-1 rounded-full border border-dashed border-warning/60 px-2 text-2xs text-warning-text outline-none hover:border-warning hover:bg-warning/8 focus-ring"
                    aria-label={`„${token}“ nicht erkannt – zuordnen`}
                  >
                    <span className="mono">{token}</span>
                    <span aria-hidden>?</span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-60">
                  <DropdownMenuLabel>„{token}“ übernehmen …</DropdownMenuLabel>
                  {ASSIGN_TARGETS.filter((t) => fields.has(t.column)).map((t) => (
                    <DropdownMenuItem key={t.column} onSelect={() => onAssign(token, t.column)}>
                      {t.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </li>
          ))}
          {unmatched.length > 0 && <li className="text-2xs text-fg-subtle">nicht erkannt – zum Zuordnen anklicken</li>}
        </ul>
      )}
    </motion.div>
  )
}

function FieldSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="micro-label">{title}</h3>
      <div className="grid grid-cols-1 gap-x-4 gap-y-3 @[34rem]:grid-cols-2">{children}</div>
    </section>
  )
}

/** Standardsymbol fehlt in der Bibliothek → erzeugen statt einen toten Verweis vorzuschlagen */
function MissingSymbol({ match, busy, onGenerate }: { match: StandardSymbolMatch; busy: boolean; onGenerate: () => void }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
      <Lightbulb aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
      <span>
        Passend wäre <span className="mono text-fg">{match.name}</span> – noch nicht in der Bibliothek.
      </span>
      {match.request && (
        <Button variant="link" size="xs" leftIcon={busy ? <Spinner size={11} /> : <Hammer />} disabled={busy} onClick={onGenerate} className="h-auto p-0">
          Symbol erzeugen
        </Button>
      )}
    </div>
  )
}

interface FormFieldProps {
  field: FieldDef
  table: string
  value: string
  error?: string
  /** Hinweise (nicht lesbar, nicht registriert) – gelb unter dem Feld */
  hints?: string[]
  onChange: (v: string) => void
  placeholder?: string
  hint?: string
  required?: boolean
  smart?: boolean
  suggestion?: string
  wide?: boolean
  /** Zusatz unter dem Feld (z. B. „Symbol erzeugen“) */
  below?: ReactNode
}

function FormField({
  field,
  table,
  value,
  error,
  hints,
  onChange,
  placeholder,
  hint,
  required,
  smart,
  suggestion,
  wide,
  below,
}: FormFieldProps) {
  const id = fieldId(field.column)
  const isRequired = required ?? field.required
  const msgId = `${id}-msg`
  const hasMessage = Boolean(error || hints?.length)
  return (
    <div className={cn('flex min-w-0 flex-col gap-1.5', wide && '@[34rem]:col-span-2')}>
      <div className="flex min-h-5 items-baseline justify-between gap-2">
        <label htmlFor={id} className="truncate text-ui font-medium text-fg" title={field.help ?? field.column}>
          {field.label}
          {isRequired && (
            <span aria-hidden className="ml-0.5 text-accent-text">
              *
            </span>
          )}
        </label>
        {smart ? (
          <span className="flex shrink-0 items-center gap-1 text-2xs text-fg-subtle">
            <Wand aria-hidden className="size-3 text-accent-text" />
            erkannt
          </span>
        ) : suggestion && value ? (
          <span className="flex shrink-0 items-center gap-1 text-2xs text-fg-subtle">
            <Lightbulb aria-hidden className="size-3" />
            {suggestion}
          </span>
        ) : hint ? (
          <span className="shrink-0 text-2xs text-fg-subtle">{hint}</span>
        ) : null}
      </div>
      <FieldInput
        id={id}
        field={field}
        table={table}
        value={value}
        onChange={onChange}
        invalid={Boolean(error)}
        placeholder={placeholder}
        aria-label={undefined}
        describedBy={hasMessage ? msgId : undefined}
        required={isRequired}
        className={cn(!error && hints?.length && 'border-warning hover:border-warning')}
      />
      {error ? (
        <p id={msgId} role="alert" className="flex items-start gap-1.5 text-xs leading-snug text-danger-text">
          <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : hints?.length ? (
        <p id={msgId} className="flex items-start gap-1.5 text-xs leading-snug text-warning-text">
          <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          <span>{hints.join(' ')}</span>
        </p>
      ) : null}
      {below}
    </div>
  )
}

function Summary({
  category,
  categories,
  symbolName,
  footprintName,
  partNumber,
  rendered,
  checking,
  blocking,
  missing,
  hinted,
  warnings,
  conflict,
  ready,
  onOpenExisting,
}: {
  category: CategoryDef | null
  categories: CategoryDef[]
  symbolName: string
  footprintName: string
  partNumber: string | null
  rendered: Record<string, string> | null
  checking: boolean
  blocking: (readonly [string, string])[]
  missing: string[]
  /** Felder mit Hinweisen (nicht lesbar, nicht registriert) */
  hinted: string[]
  warnings: string[]
  conflict: { table: string; part_number: string; message: string } | null
  ready: boolean
  onOpenExisting: (table: string, pn: string) => void
}) {
  const symbol = useLibrarySymbol(symbolName || null)
  const footprint = useLibraryFootprint(footprintName || null)
  const conflictLabel = conflict ? (categories.find((c) => c.table.toLowerCase() === conflict.table.toLowerCase())?.label ?? conflict.table) : ''
  const textRow = (label: string, value: string | null | undefined, mono = true) => (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-2xs text-fg-subtle">{label}</dt>
      <dd className={cn('min-w-0 break-words text-ui text-fg', mono && 'mono text-xs', !value && 'text-fg-subtle')}>{value || '–'}</dd>
    </div>
  )
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface-2/40">
      <div className="grid grid-cols-2 gap-px border-b border-line bg-line">
        <div className="relative h-28 bg-bg">
          {symbol.data?.spec ? (
            <SymbolCanvas spec={symbol.data.spec} interactive={false} controls={false} showInfo={false} showPartTabs={false} showGrid={false} className="absolute inset-0" />
          ) : (
            <MiniPlaceholder label="Symbol" name={symbolName} loading={symbol.isFetching} />
          )}
        </div>
        <div className="relative h-28 bg-canvas">
          {footprint.data?.spec ? (
            <FootprintCanvas spec={footprint.data.spec} interactive={false} controls={false} showInfo={false} showLegend={false} className="absolute inset-0" />
          ) : (
            <MiniPlaceholder label="Footprint" name={footprintName} loading={footprint.isFetching} board />
          )}
        </div>
      </div>
      <div className="flex flex-col gap-2.5 px-3.5 py-3">
        <div className="flex items-center gap-2">
          {category ? <CategoryIcon name={category.icon} color={category.color} /> : <FolderTree aria-hidden className="size-4 text-fg-subtle" />}
          <span className={cn('text-xs font-medium', category ? 'text-fg' : 'text-fg-subtle')}>{category?.label ?? 'Kategorie wählen'}</span>
          {checking && <Spinner size={12} className="ml-auto text-fg-subtle" />}
        </div>
        <dl className="flex flex-col gap-2.5">{textRow('Teilenummer', partNumber)}</dl>
        {/* Erzeugte Texte gehen so nach Altium (Dezimalpunkt, ohne Leerzeichen: „4.7kΩ“) – anders als die
            deutsch formatierten Werte der Felder („4,7 kΩ“). Darum ausdrücklich als Altium-Texte beschriftet. */}
        <div className="flex flex-col gap-1.5 border-t border-line pt-2.5">
          <p className="flex items-baseline justify-between gap-2">
            <span className="micro-label">Texte für Altium</span>
            <span className="text-2xs text-fg-subtle">aus den Vorlagen</span>
          </p>
          <dl className="flex flex-col gap-2.5">
            {textRow('Wert', rendered?.Value)}
            {textRow('Kommentar (Schaltplan)', rendered?.Comment)}
            {textRow('Beschreibung', rendered?.Description, false)}
          </dl>
        </div>
      </div>
      <div className="flex flex-col gap-2 border-t border-line px-3.5 py-3 text-xs">
        {!category ? (
          <span className="text-fg-subtle">Noch keine Kategorie gewählt.</span>
        ) : conflict ? (
          <div role="alert" className="flex flex-col gap-1.5 text-danger-text">
            <span className="flex items-start gap-1.5">
              <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
              <span>Teilenummer schon vergeben in „{conflictLabel}“.</span>
            </span>
            <Button variant="link" size="xs" className="self-start" onClick={() => onOpenExisting(conflict.table, conflict.part_number)}>
              „{conflict.part_number}“ öffnen
            </Button>
          </div>
        ) : ready ? (
          <span className="flex items-center gap-1.5 font-medium text-success-text">
            <CircleCheck aria-hidden className="size-3.5" />
            Bereit zum Anlegen
          </span>
        ) : (
          <>
            {blocking.map(([label, msg]) => (
              <span key={label} className="flex items-start gap-1.5 text-danger-text">
                <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                <span>
                  {label}: {msg}
                </span>
              </span>
            ))}
            {missing.length > 0 && (
              <span className="flex items-start gap-1.5 text-fg-muted">
                <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
                <span>
                  {plural(missing.length, 'Pflichtfeld fehlt', 'Pflichtfelder fehlen')}: {missing.join(', ')}
                </span>
              </span>
            )}
            {hinted.length > 0 && (
              <span className="flex items-start gap-1.5 text-warning-text">
                <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                <span>Bitte prüfen: {hinted.join(', ')}</span>
              </span>
            )}
          </>
        )}
        {warnings.slice(0, 3).map((w) => (
          <span key={w} className="flex items-start gap-1.5 text-warning-text">
            <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
            <span>{w}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

function MiniPlaceholder({ label, name, loading, board }: { label: string; name: string; loading: boolean; board?: boolean }) {
  return (
    <div className={cn('absolute inset-0 flex flex-col items-center justify-center gap-1 px-2 text-center', board ? 'text-pcb-paste' : 'text-fg-subtle')}>
      {loading ? (
        <Spinner size={14} tone="accent" />
      ) : (
        <>
          <span className="micro-label text-[inherit]">{label}</span>
          <span className="mono line-clamp-2 break-all text-2xs">{name || 'nicht gewählt'}</span>
        </>
      )}
    </div>
  )
}
