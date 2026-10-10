import { t, useI18n } from '@/lib/i18n'
import { Cable, Plus, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { PinData } from '@/api/datasheets'
import { Badge, Button, IconButton, Select, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { cn } from '@/lib/cn'
import { displayText, ELECTRICAL_LABEL, hasOverbar, partLetter, type ElectricalType } from '@/lib/geometry'
import { CellInput } from '../../shared/CommitInput'
import { OverbarName } from '../../shared/OverbarName'
import { SourceChip } from '../../shared/SourceChip'
import { TipButton } from '../../shared/TipButton'
import { useReviewUi } from '../../store'
import { packageLabel, useReview } from '../context'
import { sectionIssues } from '../issues'
import { Section } from './Section'

/** Pinname: Anzeige mit Überstrich, Bearbeiten in Altium-Syntax (`R\E\S\E\T\`). */
function PinNameCell({ pin, onCommit }: { pin: PinData; onCommit: (name: string) => void }) {
  useI18n()
  const [editing, setEditing] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (editing) inputRef.current?.focus()
  }, [editing])
  if (editing) {
    return (
      <CellInput
        ref={inputRef}
        mono
        aria-label={t("Name von Pin {0} (Überstrich: \\ nach jedem Zeichen)", { "0": String(pin.number) })}
        value={pin.name}
        onCommit={onCommit}
        onBlur={() => setEditing(false)}
        placeholder="R\E\S\E\T\"
      />
    )
  }
  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      onFocus={() => setEditing(true)}
      aria-label={t("Name von Pin {0}: {1} – bearbeiten", { "0": String(pin.number), "1": String(displayText(pin.name) || t("leer")) })}
      className="mono flex h-7 w-full min-w-0 items-center rounded-md border border-transparent px-1.5 text-left text-xs text-fg outline-none transition-colors hover:border-line-strong hover:bg-control focus-ring"
    >
      <OverbarName name={pin.name} className="max-w-full" />
    </button>
  )
}

/** Pintabellen je Gehäuse: Nummer, Name mit Überstrich, elektrischer Typ, Funktion, Gruppe, Teil – editierbar. */
export function PinsSection() {
  useI18n()
  const types = Object.entries(ELECTRICAL_LABEL).map(([value, label]) => ({ value: value as ElectricalType, label }))
  const { extraction, device, deviceIndex, edit, codes } = useReview()
  const setHighlight = useReviewUi((s) => s.setHighlight)
  const setPreviewPackage = useReviewUi((s) => s.setPreviewPackage)
  const previewPackage = useReviewUi((s) => s.previewPackage)
  const bodyRef = useRef<HTMLTableSectionElement>(null)
  // Hervorhebung beenden, sobald Maus oder Tastaturfokus die Tabelle verlassen (Tabelle wechselt mit dem Reiter)
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const leave = () => setHighlight([])
    const blur = (e: FocusEvent) => {
      if (!el.contains(e.relatedTarget as Node | null)) setHighlight([])
    }
    el.addEventListener('mouseleave', leave)
    el.addEventListener('focusout', blur)
    return () => {
      el.removeEventListener('mouseleave', leave)
      el.removeEventListener('focusout', blur)
    }
  })
  const tables = device.pin_tables
  const preferred = tables.findIndex((t) => t.package === previewPackage)
  const [chosen, setChosen] = useState<number | null>(null)
  const index = chosen ?? (preferred >= 0 ? preferred : Math.max(0, tables.findIndex((t) => codes.includes(t.package))))
  const table = tables[index]
  const issues = sectionIssues(extraction.issues, 'pins', device, undefined, table?.package)
  const pkg = table ? extraction.packages.find((p) => p.code === table.package) : undefined
  const maxPart = table ? Math.max(1, ...table.pins.map((p) => p.part)) : 1
  const partOptions = Array.from({ length: Math.min(26, maxPart + 1) + 1 }, (_, n) => ({
    value: String(n),
    label: n === 0 ? t("alle") : partLetter(n),
  }))

  const change = (label: string, i: number, patch: (pin: PinData) => void) =>
    edit.apply(label, (d) => {
      const pin = d.devices[deviceIndex].pin_tables[index].pins[i]
      if (pin) patch(pin)
    })

  if (!table) {
    return (
      <Section id="pins" title="Pins" icon={<Cable />} issues={issues}>
        <p className="text-xs text-fg-muted">{t("Keine Pintabelle gefunden. Für ein IC-Symbol bitte die Seite mit der Pinbelegung erneut analysieren lassen.")}</p>
      </Section>
    )
  }

  const wide = maxPart > 1 || table.pins.some((p) => p.part !== 1)

  const body = (
    <>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[20rem] border-separate border-spacing-0 text-xs">
          <thead>
            <tr className="text-left text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
              <th scope="col" className="w-12 pb-1.5 pl-1.5 font-semibold">
                {t("Nr.")}</th>
              <th scope="col" className="w-[28%] pb-1.5 pl-1.5 font-semibold">
                Name
              </th>
              <th scope="col" className="w-[7.5rem] pb-1.5 pl-1.5 font-semibold">
                {t("Typ")}</th>
              <th scope="col" className="hidden pb-1.5 pl-1.5 font-semibold @[34rem]:table-cell">
                {t("Funktion")}</th>
              <th scope="col" className="hidden w-24 pb-1.5 pl-1.5 font-semibold @[44rem]:table-cell">
                {t("Gruppe")}</th>
              {wide && (
                <th scope="col" className="w-16 pb-1.5 pl-1.5 font-semibold">
                  {t("Teil")}</th>
              )}
              <th scope="col" className="w-7 pb-1.5">
                <span className="sr-only">{t("Aktionen")}</span>
              </th>
            </tr>
          </thead>
          <tbody ref={bodyRef}>
            {table.pins.map((pin, i) => (
              <tr
                key={`${pin.number}-${i}`}
                className="group/pin"
                onMouseEnter={() => {
                  setHighlight([pin.number])
                  if (previewPackage !== table.package) setPreviewPackage(table.package)
                }}
                onFocusCapture={() => setHighlight([pin.number])}
              >
                <td className="border-b border-line py-0.5 align-middle">
                  <CellInput
                    mono
                    aria-label={t("Nummer von Pin {0}", { "0": String(i + 1) })}
                    value={pin.number}
                    onCommit={(v) => change(t("Pinnummer {0} → {1}", { "0": String(pin.number), "1": String(v) }), i, (p) => void (p.number = v.trim()))}
                  />
                </td>
                <td className="max-w-0 border-b border-line py-0.5 align-middle">
                  <div className="flex min-w-0 items-center gap-1">
                    <div className="min-w-0 flex-1">
                      <PinNameCell
                        pin={pin}
                        onCommit={(v) =>
                          change(t("Pin {0} umbenannt", { "0": String(pin.number) }), i, (p) => {
                            p.name = v
                            p.active_low = v.includes('\\')
                          })
                        }
                      />
                    </div>
                    {pin.no_connect && <Badge size="sm">NC</Badge>}
                    {pin.exposed_pad && <Badge size="sm">EP</Badge>}
                  </div>
                </td>
                <td className="border-b border-line py-0.5 pl-1 align-middle">
                  <Select
                    size="sm"
                    aria-label={t("Elektrischer Typ von Pin {0}", { "0": String(pin.number) })}
                    value={pin.electrical}
                    onValueChange={(v) => change(t("Typ von Pin {0}", { "0": String(pin.number) }), i, (p) => void (p.electrical = v))}
                    options={types}
                    className="h-7 border-transparent bg-transparent px-1.5 text-xs shadow-none hover:border-line-strong"
                  />
                </td>
                <td className="hidden max-w-0 border-b border-line py-0.5 pl-1 align-middle @[34rem]:table-cell">
                  <CellInput
                    aria-label={t("Funktion von Pin {0}", { "0": String(pin.number) })}
                    value={pin.function}
                    onCommit={(v) => change(t("Funktion von Pin {0}", { "0": String(pin.number) }), i, (p) => void (p.function = v))}
                    className="text-fg-muted"
                  />
                </td>
                <td className="hidden max-w-0 border-b border-line py-0.5 pl-1 align-middle @[44rem]:table-cell">
                  <CellInput
                    aria-label={t("Gruppe von Pin {0}", { "0": String(pin.number) })}
                    value={pin.group}
                    onCommit={(v) => change(t("Gruppe von Pin {0}", { "0": String(pin.number) }), i, (p) => void (p.group = v))}
                    className="text-fg-muted"
                  />
                </td>
                {wide && (
                  <td className="border-b border-line py-0.5 pl-1 align-middle">
                    <Select
                      size="sm"
                      aria-label={t("Teil von Pin {0}", { "0": String(pin.number) })}
                      value={String(pin.part)}
                      onValueChange={(v) => change(t("Teil von Pin {0}", { "0": String(pin.number) }), i, (p) => void (p.part = Number(v)))}
                      options={partOptions}
                      className="h-7 border-transparent bg-transparent px-1.5 text-xs shadow-none hover:border-line-strong"
                    />
                  </td>
                )}
                <td className="border-b border-line py-0.5 align-middle">
                  <div className="flex justify-end opacity-0 transition-opacity group-focus-within/pin:opacity-100 group-hover/pin:opacity-100">
                    <IconButton
                      size="xs"
                      label={t("Pin {0} entfernen", { "0": String(pin.number) })}
                      icon={<Trash2 />}
                      onClick={() =>
                        edit.apply(t("Pin {0} entfernt", { "0": String(pin.number) }), (d) => {
                          d.devices[deviceIndex].pin_tables[index].pins.splice(i, 1)
                        })
                      }
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-2">
        <Button
          size="xs"
          variant="ghost"
          leftIcon={<Plus />}
          onClick={() =>
            edit.apply(t("Pin hinzugefügt"), (d) => {
              const pins = d.devices[deviceIndex].pin_tables[index].pins
              const numbers = pins.map((p) => Number(p.number)).filter((n) => Number.isFinite(n))
              pins.push({
                number: String((numbers.length ? Math.max(...numbers) : 0) + 1),
                name: '',
                function: '',
                electrical: 'passive',
                active_low: false,
                no_connect: false,
                exposed_pad: false,
                group: '',
                part: 1,
              })
            })
          }
        >
          {t("Pin hinzufügen")}</Button>
        <TipButton
          tip={t("Überstrich (low-aktiv): Backslash nach jedem Zeichen, z. B. R\\E\\S\\E\\T\\ – angezeigt als RESET mit Strich darüber")}
          className="ml-auto rounded-sm text-2xs text-fg-subtle"
        >
          {table.pins.some((p) => hasOverbar(p.name)) ? t("Überstrich = low-aktiv") : t("Tipp: R\\E\\S\\E\\T\\ = Überstrich")}
        </TipButton>
      </div>
    </>
  )

  return (
    <Section
      id="pins"
      title="Pins"
      icon={<Cable />}
      count={table.pins.length}
      issues={issues}
      aside={<SourceChip pages={table.pages} what={t("Pintabelle {0}", { "0": String(packageLabel(pkg, table.package)) })} />}
    >
      {tables.length > 1 ? (
        <Tabs
          variant="pill"
          value={String(index)}
          onValueChange={(v) => {
            const i = Number(v)
            setChosen(i)
            if (tables[i]) setPreviewPackage(tables[i].package)
          }}
        >
          <TabsList aria-label={t("Pintabelle")} className="mb-2 w-fit max-w-full flex-wrap">
            {tables.map((t, i) => (
              <TabsTrigger
                key={`${t.package}-${i}`}
                value={String(i)}
                count={t.pins.length}
                className={cn('h-7 px-2.5 text-xs', !codes.includes(t.package) && i !== index && 'opacity-60')}
              >
                {packageLabel(
                  extraction.packages.find((x) => x.code === t.package),
                  t.package,
                )}
              </TabsTrigger>
            ))}
          </TabsList>
          <TabsContent value={String(index)}>{body}</TabsContent>
        </Tabs>
      ) : (
        body
      )}
    </Section>
  )
}
