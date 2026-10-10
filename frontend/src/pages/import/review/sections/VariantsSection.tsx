import { t, useI18n } from '@/lib/i18n'
import { ArrowRight, ChevronDown, CircleAlert, Info, ListOrdered } from 'lucide-react'
import { useMemo } from 'react'
import type { PackageData, VariantProposal } from '@/api/datasheets'
import {
  Badge,
  Checkbox,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
  SegmentedControl,
} from '@/components/ui'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { lifecycleLabel } from '../../lib/format'
import { rowNavigationKeyDown } from '../../shared/rowNavigation'
import { SourceChip } from '../../shared/SourceChip'
import { TipButton } from '../../shared/TipButton'
import { useReviewUi } from '../../store'
import { packageLabel, useReview } from '../context'
import { sectionIssues } from '../issues'
import { Section } from './Section'

function StatusBadge({ item, mode }: { item: VariantProposal | undefined; mode: 'skip' | 'update' }) {
  useI18n()
  if (!item) return <span className="text-2xs text-fg-subtle">{t("nicht gewählt")}</span>
  const errors = Object.entries(item.errors)
  if (item.status === 'conflict') {
    return (
      <TipButton navItem tip={t("Teilenummer schon in „{0}“ vergeben – wird nicht angelegt.", { "0": String(item.existing_table ?? t("anderer Kategorie")) })}>
        <Badge variant="danger">{t("Konflikt")}</Badge>
      </TipButton>
    )
  }
  if (item.status === 'exists') {
    return (
      <TipButton navItem tip={t("{0} ist schon in „{1}“.", { "0": String(item.part_number ?? item.mpn), "1": String(item.existing_table ?? t("der Bibliothek")) })}>
        <Badge variant={mode === 'update' ? 'info' : 'neutral'}>{mode === 'update' ? t("wird aktualisiert") : t("vorhanden")}</Badge>
      </TipButton>
    )
  }
  if (errors.length) {
    return (
      <TipButton navItem tip={errors.map(([k, v]) => `${k}: ${v}`).join(' · ')}>
        <Badge variant="danger">
          <CircleAlert />
          {t("Fehler")}</Badge>
      </TipButton>
    )
  }
  return <Badge variant="success">{t("neu")}</Badge>
}

/**
 * Gehäuse einer Bestellnummer: Code immer sichtbar; gibt es mehrere Gehäuse, öffnet er ein Menü zum Umhängen (die
 * Korrektur geht in die Extraktion). Teil der Zeile (Pfeiltasten), kein eigener Tab-Stopp.
 */
function PackageCell({
  mpn,
  value,
  packages,
  onChange,
}: {
  mpn: string
  value: string
  packages: readonly PackageData[]
  onChange: (code: string) => void
}) {
  useI18n()
  const pkg = packages.find((p) => p.code === value)
  if (packages.length <= 1) {
    return (
      <span className="mono whitespace-nowrap px-1.5 text-2xs text-fg-muted" title={pkg ? packageLabel(pkg) : undefined}>
        {value || '–'}
      </span>
    )
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          tabIndex={-1}
          data-nav-item=""
          aria-label={t("Gehäuse von {0}: {1} – ändern", { "0": String(mpn), "1": String(pkg ? packageLabel(pkg) : value || t("keins")) })}
          className={cn(
            'mono inline-flex h-6 items-center gap-0.5 whitespace-nowrap rounded-md border border-transparent px-1.5 text-2xs text-fg-muted outline-none transition-colors',
            'hover:border-line-strong hover:bg-control hover:text-fg focus-ring data-[state=open]:border-line-strong data-[state=open]:bg-control data-[state=open]:text-fg',
          )}
        >
          {value || '–'}
          <ChevronDown aria-hidden className="size-3 text-fg-subtle" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuLabel>{t("Gehäuse von ")}{mpn}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value} onValueChange={onChange}>
          {packages.map((p) => (
            <DropdownMenuRadioItem key={p.code} value={p.code}>
              <span className="mono">{p.code}</span>
              <span className="ml-2 text-fg-subtle">{packageLabel(p)}</span>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * Bestellvarianten nach Gehäuse gruppiert – Auswahl, Status, Gehäusezuordnung (Gehäuse → Footprint, Symbol).
 * Tastatur: **ein Tab-Stopp je Zeile** (das Kästchen); Hinweis, Status, Gehäuse und Fundstelle mit ←/→, ↑/↓ wechselt
 * die Zeile (`rowNavigationKeyDown`).
 *
 * Breite: Die Bestellnummer wird **nie** gekürzt (#PBF/#TRPBF unterscheiden die Varianten) – ihre Spalte nimmt die volle
 * Breite der Nummer, Temperatur bricht stattdessen um und die Verpackung kürzt (voller Text im Tooltip).
 */
export function VariantsSection() {
  useI18n()
  const { extraction, device, deviceIndex, proposal, choices, setChoices, edit } = useReview()
  const setPreviewPackage = useReviewUi((s) => s.setPreviewPackage)
  const variants = device.variants
  const all = useMemo(() => variants.map((v) => v.mpn), [variants])
  const selected = new Set(choices.variants ?? all)
  const byMpn = new Map((proposal?.variants ?? []).map((v) => [v.mpn.toLowerCase(), v]))
  const anyExists = (proposal?.variants ?? []).some((v) => v.status === 'exists')
  const issues = sectionIssues(extraction.issues, 'varianten', device)

  const groups = useMemo(() => {
    const order: string[] = []
    const map = new Map<string, number[]>()
    variants.forEach((v, i) => {
      const code = v.package || ''
      if (!map.has(code)) {
        map.set(code, [])
        order.push(code)
      }
      map.get(code)?.push(i)
    })
    return order.map((code) => ({ code, indexes: map.get(code) ?? [] }))
  }, [variants])

  const setSelected = (next: Set<string>) =>
    setChoices((c) => ({ ...c, variants: next.size === all.length ? null : all.filter((m) => next.has(m)) }))
  const toggle = (mpns: string[], on: boolean) => {
    const next = new Set(selected)
    for (const m of mpns) {
      if (on) next.add(m)
      else next.delete(m)
    }
    setSelected(next)
  }
  const allState = selected.size === all.length ? true : selected.size === 0 ? false : 'indeterminate'

  return (
    <Section
      id="varianten"
      title={t("Bestellvarianten")}
      icon={<ListOrdered />}
      count={all.length ? `${formatNumber(selected.size)} / ${formatNumber(all.length)}` : undefined}
      issues={issues}
    >
      {anyExists && (
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-card border border-line bg-surface px-3 py-2">
          <div className="min-w-0 flex-1 text-xs leading-snug">
            <div className="font-medium text-fg">{t("Vorhandene Bauteile")}</div>
            <div className="text-fg-subtle">
              {choices.mode === 'skip'
                ? t("bleiben unverändert – nur neue Bestellnummern werden angelegt")
                : t("werden mit den Werten aus dem Datenblatt aktualisiert (Freigabe und eigene Links bleiben)")}
            </div>
          </div>
          <SegmentedControl
            size="sm"
            aria-label={t("Vorhandene Bauteile")}
            value={choices.mode}
            onValueChange={(mode) => setChoices((c) => ({ ...c, mode }))}
            options={[
              { value: 'skip', label: t("Überspringen") },
              { value: 'update', label: t("Aktualisieren") },
            ]}
          />
        </div>
      )}
      {variants.length === 0 ? (
        <p className="rounded-card border border-dashed border-line-strong px-3 py-2.5 text-xs leading-relaxed text-fg-muted">
          {t("Im Datenblatt stehen keine Bestellnummern – angelegt wird")}{' '}
          <span className="mono text-fg">{proposal?.variants[0]?.mpn ?? device.base_part}</span>{t(". Die Hersteller-Teilenummer lässt sich später in der Bauteiltabelle ergänzen.")}</p>
      ) : (
        <div className="group/variants">
          {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Pfeiltasten zwischen den Bedienelementen einer Zeile (ein Tab-Stopp je Zeile) */}
          <table className="w-full border-separate border-spacing-0 text-xs" onKeyDown={rowNavigationKeyDown}>
            <caption className="sr-only">
              {t("Bestellvarianten nach Gehäuse. Je Zeile ein Tab-Stopp; Hinweis, Status, Gehäuse und Fundstelle mit den Pfeiltasten links und rechts, andere Zeilen mit auf und ab.")}</caption>
            <thead>
              <tr className="text-left text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
                <th scope="col" className="w-7 pb-1.5 pl-1 font-semibold">
                  <Checkbox
                    aria-label={t("Alle Bestellnummern auswählen")}
                    checked={allState}
                    onCheckedChange={(v) => setSelected(v === true ? new Set(all) : new Set())}
                  />
                </th>
                <th scope="col" className="pb-1.5 font-semibold">
                  {t("Bestellnummer")}</th>
                <th scope="col" className="hidden pb-1.5 font-semibold @[30rem]:table-cell">
                  {t("Temperatur")}</th>
                <th scope="col" className="hidden pb-1.5 font-semibold @[38rem]:table-cell">
                  {t("Verpackung")}</th>
                <th scope="col" className="pb-1.5 font-semibold">
                  Status
                </th>
                <th scope="col" className="w-0 whitespace-nowrap pb-1.5 pr-1 text-right font-semibold">
                  {t("Gehäuse")}</th>
              </tr>
            </thead>
            {groups.map((g) => {
              const pkg = extraction.packages.find((p) => p.code === g.code)
              const fp = proposal?.footprints.find((f) => f.package === g.code)
              const sym = proposal?.symbols.find((s) => s.packages.includes(g.code))
              const mpns = g.indexes.map((i) => variants[i].mpn)
              // gemeinsame Fundstelle der Gruppe (die häufigste Seitenliste)
              const pageLists = g.indexes.map((i) => variants[i].pages)
              const groupPages =
                [...pageLists].sort(
                  (a, b) => pageLists.filter((x) => x.join() === b.join()).length - pageLists.filter((x) => x.join() === a.join()).length,
                )[0] ?? []
              const on = mpns.filter((m) => selected.has(m)).length
              const groupState = on === mpns.length ? true : on === 0 ? false : 'indeterminate'
              const groupName = packageLabel(pkg, g.code || t("ohne Gehäuse"))
              return (
                <tbody key={g.code || '–'}>
                  <tr data-nav-row="">
                    <td colSpan={6} className="pt-2">
                      <div className="flex items-center gap-2 rounded-control bg-surface-2/70 px-1 py-1">
                        <span data-nav-host="" className="ml-1 flex">
                          <Checkbox
                            aria-label={t("Alle Bestellnummern im Gehäuse {0} auswählen", { "0": String(groupName) })}
                            checked={groupState}
                            onCheckedChange={(v) => toggle(mpns, v === true)}
                          />
                        </span>
                        <button
                          type="button"
                          tabIndex={-1}
                          data-nav-item=""
                          onClick={() => g.code && setPreviewPackage(g.code)}
                          className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5 rounded-sm text-left outline-none focus-ring"
                        >
                          <span className="font-semibold text-fg">{groupName}</span>
                          {fp?.name && (
                            <span className="flex min-w-0 items-center gap-1 text-fg-muted">
                              <ArrowRight aria-hidden className="size-3 shrink-0 text-fg-subtle" />
                              <span className="mono truncate">{fp.name}</span>
                              <Badge variant={fp.exists ? 'neutral' : 'success'} size="sm">
                                {fp.exists ? t("vorhanden") : t("neu")}
                              </Badge>
                            </span>
                          )}
                          {sym?.name && <span className="truncate text-fg-subtle">Symbol {sym.name}</span>}
                          <span className="sr-only"> {t(" – in der Vorschau zeigen")}</span>
                        </button>
                        <SourceChip navItem pages={groupPages} what={t("Bestellangaben {0}", { "0": String(packageLabel(pkg, g.code)) })} />
                        <span className="pr-1 text-2xs tabular-nums text-fg-subtle">
                          {on}/{mpns.length}
                        </span>
                      </div>
                    </td>
                  </tr>
                  {g.indexes.map((i) => {
                    const v = variants[i]
                    const item = byMpn.get(v.mpn.toLowerCase())
                    const isOn = selected.has(v.mpn)
                    const temp = item?.values['Operating Temperature'] ?? v.temperature_range
                    const life = lifecycleLabel(v.status)
                    return (
                      <tr key={`${v.mpn}-${i}`} data-nav-row="" className={cn('group/row', !isOn && 'text-fg-subtle')}>
                        <td data-nav-host="" className="border-b border-line py-1.5 pl-1 align-middle">
                          <Checkbox aria-label={t("{0} anlegen", { "0": String(v.mpn) })} checked={isOn} onCheckedChange={(c) => toggle([v.mpn], c === true)} />
                        </td>
                        <td className="border-b border-line py-1.5 pr-2 align-middle">
                          <div className="flex items-center gap-1.5">
                            <span className={cn('mono whitespace-nowrap', isOn ? 'text-fg' : 'text-fg-subtle')}>{v.mpn}</span>
                            {v.notes && (
                              <TipButton navItem tip={v.notes} label={t("Anmerkung: {0}", { "0": String(v.notes) })} className="rounded-sm text-fg-subtle">
                                <Info aria-hidden className="size-3.5" />
                              </TipButton>
                            )}
                          </div>
                        </td>
                        <td className="hidden border-b border-line py-1.5 pr-2 align-middle text-fg-muted @[30rem]:table-cell">
                          {/* bricht an den Leerzeichen um („−40 °C …“ / „125 °C“), statt der Bestellnummer Platz zu nehmen */}
                          <span className="mono">{temp ? formatQuantityText(temp) : '–'}</span>
                        </td>
                        <td className="hidden max-w-0 border-b border-line py-1.5 pr-2 align-middle @[38rem]:table-cell">
                          <div className="flex min-w-0 items-center gap-1.5 text-fg-muted">
                            <span className="truncate" title={v.packaging || undefined}>
                              {v.packaging || '–'}
                            </span>
                            {life && life !== t('Aktiv') && (
                              <Badge variant={life === 'NRND' || life === t('Vorschau') ? 'warning' : 'danger'} size="sm">
                                {life}
                              </Badge>
                            )}
                          </div>
                        </td>
                        <td className="border-b border-line py-1.5 pr-2 align-middle">
                          <StatusBadge item={isOn ? item : undefined} mode={choices.mode} />
                        </td>
                        <td className="border-b border-line py-1 pr-1 align-middle">
                          <div className="flex items-center justify-end gap-1">
                            {v.pages.join() !== groupPages.join() && (
                              <SourceChip navItem pages={v.pages} what={t("Bestellangaben {0}", { "0": String(v.mpn) })} className="hidden @[24rem]:inline-flex" />
                            )}
                            <PackageCell
                              mpn={v.mpn}
                              value={v.package}
                              packages={extraction.packages}
                              onChange={(code) =>
                                edit.apply(t("Gehäuse von {0}", { "0": String(v.mpn) }), (d) => {
                                  d.devices[deviceIndex].variants[i].package = code
                                })
                              }
                            />
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              )
            })}
          </table>
          {/* Tastaturhinweis, sobald der Fokus in der Tabelle ist */}
          <p aria-hidden className="mt-1.5 hidden text-2xs text-fg-subtle group-focus-within/variants:block">
            {t("Tab: nächste Zeile · ←/→: Hinweis, Status, Gehäuse, Fundstelle · ↑/↓: Zeile wechseln")}</p>
        </div>
      )}
    </Section>
  )
}
