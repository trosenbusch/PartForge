import { Fingerprint, RotateCcw, Sparkles } from 'lucide-react'
import { useId } from 'react'
import { CategoryIcon } from '@/components/data'
import { Badge, IconButton, PathText, SegmentedControl, Select } from '@/components/ui'
import { cn } from '@/lib/cn'
import { CommitInput } from '../../shared/CommitInput'
import { SourceChip } from '../../shared/SourceChip'
import { useReview } from '../context'
import { sectionIssues } from '../issues'
import { commonValue } from '../values'
import { FieldLabel, Section } from './Section'

/**
 * Fundstelle der Identität (Hersteller, Bauteil, Beschreibung, Dokument): die Extraktion nennt dafür keine Seite – echt
 * belegt ist, welche Seiten der Durchgang „Bauteile und Pins“ gelesen hat. Gezeigt wird die erste davon (meist die
 * Titelseite); ohne diese Angabe die erste gelesene Seite.
 */
function identitySource(runs: readonly { kind: string; pages: number[]; error?: string | null }[], selected: readonly number[]): number | null {
  const run = [...runs].reverse().find((r) => r.kind === 'identity' && !r.error && r.pages.length)
  const pages = run?.pages ?? selected
  return pages.length ? Math.min(...pages) : null
}

export function IdentitySection() {
  const { ds, extractionOut, extraction, device, proposal, choices, setChoices, categories, category } = useReview()
  const id = useId()
  const sourcePage = identitySource(extractionOut.runs, extractionOut.selected_pages.length ? extractionOut.selected_pages : ds.selected_pages)
  const devices = extraction.devices.map((d) => d.base_part)
  const manufacturer = choices.values.Manufacturer ?? (extraction.manufacturer || proposal?.manufacturer || '')
  const generated = [...new Set((proposal?.variants ?? []).map((v) => v.values.Description ?? '').filter(Boolean))]
  const generatedDescription = commonValue((proposal?.variants ?? []).map((v) => v.values.Description))
  const description = choices.values.Description ?? generatedDescription ?? ''
  const aiCategory = device.category
  const chosen = choices.category ?? proposal?.category ?? aiCategory
  const issues = sectionIssues(extraction.issues, 'identitaet', device)

  // anderes Bauteil: Entscheidungen des bisherigen gelten nicht (auch nicht „Pinbelegung ändern“)
  const switchDevice = (v: string) =>
    setChoices((c) => ({
      ...c,
      device: v,
      category: null,
      variants: null,
      values: {},
      variantValues: {},
      packages: {},
      symbols: {},
      allowPinChanges: [],
    }))

  const setValue = (column: string, value: string | null) =>
    setChoices((c) => {
      const values = { ...c.values }
      if (value === null || !value.trim()) delete values[column]
      else values[column] = value.trim()
      return { ...c, values }
    })

  return (
    <Section
      id="identitaet"
      title="Identität"
      icon={<Fingerprint />}
      issues={issues}
      aside={sourcePage ? <SourceChip pages={[sourcePage]} what={sourcePage === 1 ? 'Titelseite' : 'Angaben zum Bauteil'} /> : undefined}
    >
      {devices.length > 1 && (
        <div className="mb-3">
          <FieldLabel hint={`${devices.length} Bauteile in diesem Datenblatt`}>Bauteil</FieldLabel>
          {devices.length <= 3 ? (
            <SegmentedControl
              aria-label="Bauteil"
              size="sm"
              value={device.base_part}
              onValueChange={switchDevice}
              options={devices.map((d) => ({ value: d, label: <span className="mono">{d}</span> }))}
            />
          ) : (
            <Select
              aria-label="Bauteil"
              size="sm"
              value={device.base_part}
              onValueChange={switchDevice}
              options={devices.map((d) => ({ value: d, label: d }))}
            />
          )}
        </div>
      )}

      <div className="grid gap-x-3 gap-y-3 @[30rem]:grid-cols-2">
        <div className="min-w-0">
          <FieldLabel htmlFor={`${id}-cat`} hint={chosen && chosen === aiCategory ? undefined : aiCategory ? `Claude: ${aiCategory}` : 'nicht erkannt'}>
            Kategorie
          </FieldLabel>
          <div className="flex items-center gap-1.5">
            <Select
              id={`${id}-cat`}
              size="sm"
              value={chosen ?? undefined}
              placeholder="Kategorie wählen …"
              invalid={!chosen}
              onValueChange={(v) => setChoices((c) => ({ ...c, category: v }))}
              options={categories.map((c) => ({
                value: c.table,
                label: c.label,
                description: c.table !== c.label ? c.table : undefined,
                icon: <CategoryIcon name={c.icon} color={c.color ?? undefined} />,
                badge:
                  c.table === aiCategory ? (
                    <Badge variant="spark" size="sm">
                      <Sparkles />
                      KI
                    </Badge>
                  ) : undefined,
              }))}
              className="min-w-0 flex-1"
            />
            {choices.category && choices.category !== aiCategory && aiCategory && (
              <IconButton
                size="sm"
                label="Vorschlag von Claude wiederherstellen"
                icon={<RotateCcw />}
                onClick={() => setChoices((c) => ({ ...c, category: null }))}
              />
            )}
          </div>
          {category && chosen === aiCategory && (
            <p className="mt-1 flex items-center gap-1 text-2xs text-spark-text">
              <Sparkles aria-hidden className="size-3" />
              Von Claude zugeordnet
            </p>
          )}
        </div>

        <div className="min-w-0">
          <FieldLabel htmlFor={`${id}-mfr`} hint={choices.values.Manufacturer ? 'geändert' : undefined}>
            Hersteller
          </FieldLabel>
          <div className="flex items-center gap-1.5">
            <CommitInput
              id={`${id}-mfr`}
              size="sm"
              value={manufacturer}
              onCommit={(v) => setValue('Manufacturer', v === extraction.manufacturer ? null : v)}
              containerClassName="flex-1"
            />
            {choices.values.Manufacturer && (
              <IconButton size="sm" label="Wert aus dem Datenblatt verwenden" icon={<RotateCcw />} onClick={() => setValue('Manufacturer', null)} />
            )}
          </div>
        </div>

        <div className="min-w-0 @[30rem]:col-span-2">
          <FieldLabel
            htmlFor={`${id}-desc`}
            hint={choices.values.Description ? 'eigener Text' : generatedDescription ? 'aus der Vorlage der Kategorie' : undefined}
          >
            Beschreibung
          </FieldLabel>
          <div className="flex items-center gap-1.5">
            <CommitInput
              id={`${id}-desc`}
              size="sm"
              value={description}
              placeholder={generatedDescription === null ? 'Eigener Text für alle Bestellnummern …' : undefined}
              onCommit={(v) => setValue('Description', v === generatedDescription ? null : v)}
              containerClassName="flex-1"
            />
            {choices.values.Description && (
              <IconButton size="sm" label="Beschreibung aus der Vorlage" icon={<RotateCcw />} onClick={() => setValue('Description', null)} />
            )}
          </div>
          {generatedDescription === null && !choices.values.Description && generated.length > 0 && (
            <ul className="mt-1 flex flex-col gap-0.5 text-2xs leading-4 text-fg-subtle">
              {generated.slice(0, 3).map((g) => (
                <li key={g} className="truncate">
                  Vorlage: <span className="mono text-fg-muted">{g}</span>
                </li>
              ))}
            </ul>
          )}
          {device.description && (
            <p className="mt-1 line-clamp-2 text-2xs leading-4 text-fg-subtle">
              Im Datenblatt: <span className="text-fg-muted">{device.description}</span>
            </p>
          )}
        </div>

        <div className="min-w-0 @[30rem]:col-span-2">
          <FieldLabel>Datenblatt-Link der Bauteile</FieldLabel>
          {ds.source_url ? (
            <SegmentedControl
              aria-label="Datenblatt-Link"
              size="sm"
              value={choices.link === 'file' ? 'file' : 'url'}
              onValueChange={(v) => setChoices((c) => ({ ...c, link: v === 'file' ? 'file' : 'auto' }))}
              options={[
                { value: 'url', label: 'Hersteller-Adresse' },
                { value: 'file', label: 'PDF in der Bibliothek' },
              ]}
            />
          ) : null}
          <p className={cn('mt-1 text-2xs leading-4 text-fg-muted', !proposal?.datasheet_link && 'text-fg-subtle')}>
            {proposal?.datasheet_link ? <PathText path={proposal.datasheet_link} /> : '–'}
          </p>
        </div>
      </div>

      {(extraction.title || extraction.document_id || extraction.date) && (
        <dl className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-line pt-3 text-2xs">
          {extraction.title && (
            <>
              <dt className="text-fg-subtle">Titel</dt>
              <dd className="line-clamp-2 text-fg-muted">{extraction.title}</dd>
            </>
          )}
          {extraction.document_id && (
            <>
              <dt className="text-fg-subtle">Dokument</dt>
              <dd className="mono text-fg-muted">
                {extraction.document_id}
                {extraction.date ? ` · ${extraction.date}` : ''}
              </dd>
            </>
          )}
        </dl>
      )}
    </Section>
  )
}
