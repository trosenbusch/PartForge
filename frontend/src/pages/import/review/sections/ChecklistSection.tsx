import { localizeMessage } from '@/lib/i18n'
import { t, useI18n } from '@/lib/i18n'
import { ArrowRight, CircleAlert, GitCompareArrows, Info, ShieldCheck } from 'lucide-react'
import { RadioGroup } from 'radix-ui'
import { useEffect, useId, useRef } from 'react'
import type { PartProposal, SymbolProposal } from '@/api/datasheets'
import { Badge, Button, Callout, Checkbox } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { electricalLabel, type ElectricalType } from '@/lib/geometry'
import { OverbarName } from '../../shared/OverbarName'
import { sameBlocker, sameSymbolName, useReviewUi } from '../../store'
import { useReview } from '../context'
import { conflictName, type Readiness } from '../readiness'

/** Umbenannt, weil ein anderes Symbol dieses Vorschlags den Namen schon mit anderer Belegung nutzt (keine Wahl) */
function internalClash(s: SymbolProposal, proposal: PartProposal): boolean {
  return Boolean(s.taken_name) && proposal.symbols.some((o) => o !== s && sameSymbolName(o.name, s.taken_name))
}

/** Ziel eines Problems (`PartProposal.blocker_targets`): Gehäuse, Symbol-Pins ohne Pad bzw. Footprint-Pads ohne Pin */
interface BlockerTargetData {
  blocker: string
  package?: string | null
  pins?: string[]
  pads?: string[]
}

type Target = { code: string | null; pins: string[]; kind: 'symbol' | 'footprint' }

/**
 * Betroffene Pins/Pads eines Problems – für die Hervorhebung in der Vorschau: Pins ohne Pad zeigt das Symbol, Pads ohne
 * Pin der Footprint. Strukturiert aus `blocker_targets` (gleicher Text wie der Eintrag in `blockers`); ältere Backends
 * ohne dieses Feld: aus dem Text („SOIC-8 (D): Pins ohne Pad im Footprint: 9, 10“).
 */
function blockerTarget(text: string, proposal: PartProposal): Target | null {
  const targets = (proposal as PartProposal & { blocker_targets?: BlockerTargetData[] }).blocker_targets
  if (Array.isArray(targets) && targets.length) {
    const t = targets.find((x) => x && typeof x.blocker === 'string' && sameBlocker(x.blocker, text))
    if (!t) return null
    const pins = t.pins ?? []
    const pads = t.pads ?? []
    if (!pins.length && !pads.length) return null
    return pins.length
      ? { code: t.package ?? null, pins, kind: 'symbol' }
      : { code: t.package ?? null, pins: pads, kind: 'footprint' }
  }
  const m = text.match(/^(?:(.+?): )?(Pins ohne Pad im Footprint|Pads ohne Pin im Symbol): (.+)$/)
  if (!m) return null
  const code = proposal.footprints.find((f) => f.package_label === m[1])?.package ?? null
  return { code, pins: m[3].split(/,\s*/).filter(Boolean), kind: m[2].startsWith('Pins') ? 'symbol' : 'footprint' }
}

/** Unterschied eines Pins zum registrierten Symbol (`SymbolProposal.taken_changes`, Backend `PinoutChange`) */
interface PinoutChangeData {
  pin: string
  old_name?: string | null
  new_name?: string | null
  old_type?: string | null
  new_type?: string | null
  old_part?: number | null
  new_part?: number | null
}

const isPinoutChange = (c: unknown): c is PinoutChangeData =>
  Boolean(c && typeof c === 'object' && typeof (c as { pin?: unknown }).pin === 'string')

/** Älteres Backend: „Pin 3: Name „C\S\“ → „CS““ als Text – Namen trotzdem mit Überstrich */
function changeFromText(text: string): PinoutChangeData | null {
  const m = /^Pin (\S+): Name „(.*)“ → „(.*)“$/.exec(text)
  return m ? { pin: m[1], old_name: m[2], new_name: m[3] } : null
}

const typeLabel = (t: string | null | undefined) => (t ? electricalLabel(t as ElectricalType) : '–')

/** Ein Pin-Unterschied: Namen in Altium-Überstrich-Syntax mit echtem Überstrich, dazu Typ und Teil, wenn sie abweichen */
function PinoutChangeLine({ change: c, oldKnown }: { change: PinoutChangeData; oldKnown: boolean }) {
  useI18n()
  const added = oldKnown && !c.old_name && Boolean(c.new_name)
  const removed = !c.new_name && Boolean(c.old_name)
  const typeChanged = oldKnown && c.old_type && c.new_type && c.old_type !== c.new_type
  const partChanged = oldKnown && c.old_part != null && c.new_part != null && c.old_part !== c.new_part
  return (
    <li className="flex flex-wrap items-baseline gap-x-1.5">
      <span>
        Pin <span className="mono text-fg">{c.pin}</span>:
      </span>
      {removed ? (
        <span>
          {t("entfällt (")}<OverbarName name={c.old_name ?? ''} className="mono text-fg" />)
        </span>
      ) : added ? (
        <span>
          {t("neu ")}<OverbarName name={c.new_name ?? ''} className="mono text-fg" />
        </span>
      ) : oldKnown && c.old_name !== c.new_name ? (
        <span className="inline-flex flex-wrap items-baseline gap-x-1">
          <OverbarName name={c.old_name ?? ''} className="mono text-fg" />
          <span aria-hidden>→</span>
          <span className="sr-only">{t("wird zu")}</span>
          <OverbarName name={c.new_name ?? ''} className="mono text-fg" />
        </span>
      ) : (
        <OverbarName name={c.new_name ?? c.old_name ?? ''} className="mono text-fg" />
      )}
      {typeChanged && (
        <span>
          {t("· Typ ")}{typeLabel(c.old_type)} → {typeLabel(c.new_type)}
        </span>
      )}
      {partChanged && (
        <span>
          {t("· Teil ")}{c.old_part} → {c.new_part}
        </span>
      )}
    </li>
  )
}

/**
 * „Vor dem Anlegen“: Probleme, die ausdrücklich bestätigt werden müssen (→ `accept_issues` als Texte), die Entscheidung
 * je Symbol, dessen Name schon mit anderer Pinbelegung registriert ist (→ `allow_pin_changes` als Liste), offene Punkte
 * und – nach einer abgelehnten Übernahme – was seitdem neu zu prüfen ist.
 */
export function ChecklistSection({ state }: { state: Readiness }) {
  useI18n()
  const { proposal, acknowledged, setAcknowledged } = useReview()
  const showSection = useReviewUi((s) => s.showSection)
  const refusal = useReviewUi((s) => s.refusal)
  if (!proposal) return null
  const blockers = proposal.blockers
  const conflicts = proposal.symbols.filter((s) => conflictName(s) && !internalClash(s, proposal))
  const internal = proposal.symbols.filter((s) => internalClash(s, proposal))
  const reasons = state.reasons
  const isAck = (b: string) => acknowledged.some((a) => sameBlocker(a, b))
  const isNew = (b: string) => refusal?.kind === 'blockers' && refusal.items.some((i) => sameBlocker(i, b))
  const refusalOpen = refusal ? (refusal.kind === 'blockers' ? refusal.items.some((i) => !isAck(i)) : true) : false
  if (!blockers.length && !conflicts.length && !internal.length && !reasons.length && !refusalOpen) return null

  const confirmed = blockers.filter(isAck).length
  const toggle = (b: string, on: boolean) =>
    setAcknowledged(on ? [...acknowledged.filter((a) => !sameBlocker(a, b)), b] : acknowledged.filter((a) => !sameBlocker(a, b)))
  // neue Probleme einer abgelehnten Übernahme zuerst
  const ordered = [...blockers].sort((a, b) => Number(isNew(b)) - Number(isNew(a)))

  return (
    <section
      id="sec-pruefen"
      data-section="pruefen"
      aria-labelledby="sec-pruefen-title"
      className="border-b border-line bg-[linear-gradient(180deg,color-mix(in_oklab,var(--pf-warning)_7%,transparent),transparent)] px-4 py-4"
    >
      <div className="flex items-center gap-2">
        <span aria-hidden className="flex size-6 items-center justify-center rounded-md bg-warning/15 text-warning-text [&_svg]:size-3.5">
          <ShieldCheck />
        </span>
        <h2 id="sec-pruefen-title" className="text-ui font-semibold text-fg">
          {t("Vor dem Anlegen prüfen")}</h2>
        <span className="ml-auto text-2xs text-fg-subtle">{blockers.length > 0 && t("{0} von {1} bestätigt", { "0": String(confirmed), "1": String(blockers.length) })}</span>
      </div>

      {refusal && refusalOpen && (
        <Callout
          tone={refusal.kind === 'invalid' ? 'danger' : 'warning'}
          title={
            refusal.kind === 'blockers'
              ? t("Übernahme abgelehnt – es wurde nichts geschrieben")
              : refusal.kind === 'changed'
                ? t("Der Vorschlag hat sich geändert – es wurde nichts geschrieben")
                : t("Übernahme abgelehnt")
          }
          actions={
            refusal.kind === 'blockers' ? undefined : (
              <Button size="xs" variant="ghost" onClick={() => useReviewUi.getState().setRefusal(null)}>
                {t("Verstanden")}</Button>
            )
          }
          className="mt-3"
        >
          {refusal.kind === 'blockers'
            ? t("Beim Anlegen kam {0} hinzu (markiert mit „neu“). Bitte prüfen und bestätigen, dann erneut anlegen.", { "0": String(refusal.items.length === 1 ? t("ein neues Problem") : t("{0} neue Probleme", { "0": String(formatNumber(refusal.items.length)) })) })
            : refusal.kind === 'changed'
              ? t("Seit der Prüfung haben sich Bibliothek oder Analyse geändert – etwa durch inzwischen angelegte Bauteile, Symbole oder Footprints. Angezeigt ist jetzt der neue Stand: bitte prüfen und erneut anlegen.")
              : localizeMessage(refusal.message)}
        </Callout>
      )}

      {blockers.length > 0 && (
        <div className="mt-3 rounded-card border border-danger/30 bg-surface px-3.5 py-3">
          <p className="text-xs leading-relaxed text-fg-muted">
            {t("Die automatische Prüfung hat Probleme gefunden, die zu einem fehlerhaften Bauteil führen können. Bitte im Datenblatt nachsehen, korrigieren – oder bewusst bestätigen:")}</p>
          <ul className="mt-2.5 flex flex-col gap-2">
            {ordered.map((b) => (
              <BlockerItem
                key={b}
                text={b}
                fresh={isNew(b)}
                checked={isAck(b)}
                onCheckedChange={(on) => toggle(b, on)}
                target={blockerTarget(b, proposal)}
                onJump={() => showSection('pins')}
              />
            ))}
          </ul>
          {blockers.length > 1 && confirmed < blockers.length && (
            <Button
              size="xs"
              variant="ghost"
              className="mt-2"
              onClick={() => setAcknowledged([...acknowledged.filter((a) => !blockers.some((b) => sameBlocker(a, b))), ...blockers])}
            >
              {t("Alle bestätigen")}</Button>
          )}
        </div>
      )}

      {conflicts.map((s) => (
        <PinoutDecision key={`${s.package}-${conflictName(s)}`} symbol={s} />
      ))}

      {internal.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1.5">
          {internal.map((s) => (
            <li key={`${s.package}-${s.name}`} className="flex items-start gap-2 text-xs leading-relaxed text-fg-muted">
              <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-info-text" />
              <span>
                Symbol <span className="mono text-fg">„{s.name}“</span> {t(" bekommt einen eigenen Namen: „")}{s.taken_name}{t("“ verwendet in diesem Vorschlag schon eine andere Pinbelegung.")}</span>
            </li>
          ))}
        </ul>
      )}

      {reasons.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1">
          {reasons.slice(0, 6).map((r) => (
            <li key={r.text}>
              <button
                type="button"
                onClick={() => showSection(r.section)}
                className="group/reason flex w-full items-start gap-2 rounded-control px-2 py-1 text-left text-xs text-fg-muted outline-none transition-colors hover:bg-surface-2 hover:text-fg focus-ring"
              >
                <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger-text" />
                <span className="min-w-0 flex-1">{localizeMessage(r.text)}</span>
                <ArrowRight aria-hidden className="mt-0.5 size-3.5 shrink-0 opacity-0 transition-opacity group-hover/reason:opacity-100" />
              </button>
            </li>
          ))}
          {reasons.length > 6 && <li className="px-2 text-2xs text-fg-subtle">{t("… und ")}{reasons.length - 6} {t(" weitere")}</li>}
        </ul>
      )}
    </section>
  )
}

/** Ein Problem: Überfahren/Fokus hebt die betroffenen Pins bzw. Pads in der Vorschau hervor. */
function BlockerItem({
  text,
  fresh,
  checked,
  onCheckedChange,
  target,
  onJump,
}: {
  text: string
  /** neu seit der abgelehnten Übernahme */
  fresh: boolean
  checked: boolean
  onCheckedChange: (on: boolean) => void
  target: ReturnType<typeof blockerTarget>
  onJump: () => void
}) {
  useI18n()
  const ref = useRef<HTMLLIElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el || !target) return
    const show = () => {
      const ui = useReviewUi.getState()
      if (target.code) ui.setPreviewPackage(target.code)
      ui.setPreviewTab(target.kind)
      ui.setHighlight(target.pins)
    }
    const hide = () => useReviewUi.getState().setHighlight([])
    // Fokus wandert innerhalb des Eintrags (Kästchen → „Zu den Pins“) – erst beim Verlassen ausblenden
    const blur = (e: FocusEvent) => {
      if (!el.contains(e.relatedTarget as Node | null)) hide()
    }
    el.addEventListener('mouseenter', show)
    el.addEventListener('mouseleave', hide)
    el.addEventListener('focusin', show)
    el.addEventListener('focusout', blur)
    return () => {
      el.removeEventListener('mouseenter', show)
      el.removeEventListener('mouseleave', hide)
      el.removeEventListener('focusin', show)
      el.removeEventListener('focusout', blur)
    }
  }, [target])
  return (
    <li ref={ref} className="flex items-start gap-2">
      <Checkbox
        checked={checked}
        onCheckedChange={(v) => onCheckedChange(v === true)}
        label={
          <span className={cn('text-ui', checked ? 'text-fg-muted' : 'text-fg')}>
            {fresh && (
              <Badge variant="warning" size="sm" className="mr-1.5 align-[1px]">
                {t("neu")}</Badge>
            )}
            {localizeMessage(text)}
          </span>
        }
        className="min-w-0 flex-1"
      />
      {target && (
        <Button size="xs" variant="ghost" onClick={onJump} className="shrink-0">
          {t("Zu den Pins")}</Button>
      )}
    </li>
  )
}

/**
 * Entscheidung für **ein** Symbol, dessen Name schon mit anderer Pinbelegung registriert ist: neues Symbol unter freiem
 * Namen (empfohlen – vorhandene Bauteile bleiben) oder das vorhandene Symbol ändern (alle Bauteile damit ändern sich).
 * Unterschiede und Verwendung kommen strukturiert vom Backend (`taken_changes`, `usage`).
 */
function PinoutDecision({ symbol: s }: { symbol: SymbolProposal }) {
  useI18n()
  const { proposal, choices, setChoices } = useReview()
  const uid = useId()
  const key = conflictName(s) ?? ''
  const change = choices.allowPinChanges.some((n) => sameSymbolName(n, key))
  // strukturiert (`PinoutChange`) – ältere Backends liefern Sätze; „Pin 3: Name „C\S\“ → „CS““ wird trotzdem gelesen
  const diffs = (s.taken_changes as readonly unknown[]).map((c) => (isPinoutChange(c) ? c : typeof c === 'string' ? (changeFromText(c) ?? c) : String(c)))
  // ohne Geometrie registriert (z. B. externe Bibliothek): die alte Seite ist für alle Pins unbekannt
  const oldKnown = diffs.some((c) => typeof c === 'string' || Boolean(c.old_name || c.old_type || c.old_part != null))
  const usage = s.usage
  const packages = s.packages
    .map((code) => proposal?.footprints.find((f) => f.package === code)?.package_label || code)
    .filter(Boolean)
  const renamedTo = !change && s.taken_name ? s.name : null
  const set = (allow: boolean) =>
    setChoices((c) => {
      const rest = c.allowPinChanges.filter((n) => !sameSymbolName(n, key))
      return { ...c, allowPinChanges: allow ? [...rest, key] : rest }
    })
  const shown = diffs.slice(0, 8)
  return (
    <div className="mt-3 rounded-card border border-warning/35 bg-surface px-3.5 py-3">
      <div className="flex items-start gap-2">
        <GitCompareArrows aria-hidden className="mt-0.5 size-4 shrink-0 text-warning-text" />
        <div className="min-w-0 flex-1">
          <div id={`${uid}-title`} className="text-ui font-medium text-fg">
            {change ? (
              <>
                Symbol <span className="mono">„{key}“</span> {t(" bekommt eine neue Pinbelegung")}</>
            ) : (
              <>
                Symbol <span className="mono">„{key}“</span> {t(" gibt es schon – mit anderer Pinbelegung")}</>
            )}
          </div>
          <div className="mt-0.5 text-2xs text-fg-subtle">
            {packages.length ? t("Für {0}", { "0": String(packages.join(', ')) }) : t("Für dieses Bauteil")}
            {usage ? t(" · {0} das vorhandene Symbol", { "0": String(plural(usage, t("Bauteil verwendet"), t("Bauteile verwenden"))) }) : t(" · noch von keinem Bauteil verwendet")}
          </div>
          {shown.length > 0 && (
            <ul aria-label={t("Unterschiede zur Pinbelegung von „{0}“", { "0": String(key) })} className="mt-1.5 flex flex-col gap-0.5 text-xs text-fg-muted">
              {shown.map((c, i) =>
                typeof c === 'string' ? (
                  <li key={`${c}-${i}`}>{c}</li>
                ) : (
                  <PinoutChangeLine key={`${c.pin}-${i}`} change={c} oldKnown={oldKnown} />
                ),
              )}
              {diffs.length > shown.length && <li>{t("… und ")}{formatNumber(diffs.length - shown.length)} {t(" weitere")}</li>}
              {!oldKnown && <li>{t("Die Belegung des vorhandenen Symbols ist unbekannt (ohne Geometrie registriert).")}</li>}
            </ul>
          )}
          <p className="mt-1.5 text-xs leading-relaxed text-fg-muted">
            {change ? (
              usage ? (
                <>
                  <span className="font-medium text-warning-text">{plural(usage, t("vorhandenes Bauteil"), t("vorhandene Bauteile"))}</span> {t(" mit diesem Symbol ")}{usage === 1 ? t("bekommt") : t("bekommen")} {t(" die neue Pinbelegung.")}</>
              ) : (
                t("Das vorhandene Symbol wird mit der neuen Pinbelegung überschrieben.")
              )
            ) : renamedTo ? (
              <>
                {t("Damit vorhandene Bauteile unverändert bleiben, legt PartForge ein neues Symbol ")}<span className="mono text-fg">„{renamedTo}“</span> {t(" an.")}</>
            ) : (
              t("Damit vorhandene Bauteile unverändert bleiben, bitte einen anderen Namen wählen oder die neue Pinbelegung bestätigen.")
            )}
          </p>
          <RadioGroup.Root
            aria-labelledby={`${uid}-title`}
            value={change ? 'change' : 'new'}
            onValueChange={(v) => set(v === 'change')}
            className="mt-2.5 flex flex-col gap-1.5"
          >
            <ChoiceRadio
              value="new"
              label={renamedTo ? t("Neues Symbol „{0}“ anlegen (empfohlen)", { "0": String(renamedTo) }) : t("Neues Symbol unter freiem Namen anlegen (empfohlen)")}
              description={t("Vorhandene Bauteile behalten ihr Symbol.")}
            />
            <ChoiceRadio
              value="change"
              label={t("Vorhandenes Symbol „{0}“ ändern", { "0": String(key) })}
              description={
                usage
                  ? t("{0} mit diesem Symbol {1} die neue Pinbelegung.", { "0": String(plural(usage, t("Bauteil"), t("Bauteile"))), "1": String(usage === 1 ? t("bekommt") : t("bekommen")) })
                  : t("Kein Bauteil verwendet es bisher.")
              }
              tone="warning"
            />
          </RadioGroup.Root>
        </div>
      </div>
    </div>
  )
}

function ChoiceRadio({ value, label, description, tone }: { value: string; label: string; description: string; tone?: 'warning' }) {
  useI18n()
  return (
    <RadioGroup.Item
      value={value}
      className={cn(
        'group/radio flex items-start gap-2.5 rounded-control border border-line px-2.5 py-2 text-left outline-none transition-colors focus-ring hover:bg-surface-2',
        tone === 'warning'
          ? 'data-[state=checked]:border-warning/50 data-[state=checked]:bg-warning/8'
          : 'data-[state=checked]:border-accent/45 data-[state=checked]:bg-accent-soft',
      )}
    >
      <span
        aria-hidden
        className="mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border border-line-control bg-control group-data-[state=checked]/radio:border-transparent group-data-[state=checked]/radio:bg-gradient-forge"
      >
        <RadioGroup.Indicator className="size-1.5 rounded-full bg-on-accent" />
      </span>
      <span className="min-w-0">
        <span className="block text-ui text-fg">{label}</span>
        <span className="block text-xs leading-snug text-fg-muted">{description}</span>
      </span>
    </RadioGroup.Item>
  )
}
