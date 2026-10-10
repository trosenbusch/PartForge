import { t as translate, useI18n } from '@/lib/i18n'
/**
 * Eigenschaften einer Kategorie: Bezeichnung, Präfix, Symbol und Farbe, Standardsymbol (mit Vorschau),
 * Sichtbarkeit in Altium, Tabellenname und – abgesetzt – Löschen mit getippter Bestätigung.
 */
import { Database, Shapes, Trash2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useDeleteCategory, useSymbolKinds, type CategoryDef } from '@/api/settings'
import { SymbolCanvas, useSymbolPreview } from '@/components/preview'
import { Button, Callout, Field, Input, Select, Spinner, Switch, type SelectGroupDef } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { TypedConfirm } from '../TypedConfirm'
import type { CategoryDraft, DraftErrors } from './categoryDraft'
import { normalizeName } from './meta'
import { CategoryTile, ColorPicker, IconPicker } from './pickers'

const NONE = '__none'

export function PropertiesPanel({
  category,
  draft,
  errors,
  onChange,
  onDeleted,
}: {
  category: CategoryDef
  draft: CategoryDraft
  errors: DraftErrors
  onChange: (patch: Partial<CategoryDraft>) => void
  onDeleted: () => void
}) {
  useI18n()
  const kinds = useSymbolKinds()
  const preview = useSymbolPreview(draft.default_symbol ? { kind: draft.default_symbol } : null)
  const parts = category.part_count ?? 0
  const renamed = normalizeName(draft.table) !== category.table

  const groups: SelectGroupDef[] = [
    { label: '', options: [{ value: NONE, label: translate("Kein Standardsymbol"), description: translate("Symbol wird je Bauteil gewählt (ICs, Steckverbinder …)") }] },
  ]
  const byGroup = new Map<string, SelectGroupDef>()
  for (const k of kinds.data ?? []) {
    if (k.key === 'ic') continue
    const g = byGroup.get(k.group) ?? { label: translate(k.group), options: [] }
    g.options.push({ value: k.key, label: translate(k.label), description: k.default_name })
    byGroup.set(k.group, g)
  }
  groups.push(...byGroup.values())
  if (draft.default_symbol && !(kinds.data ?? []).some((k) => k.key === draft.default_symbol)) {
    groups.push({ label: translate("Unbekannt"), options: [{ value: draft.default_symbol, label: draft.default_symbol }] })
  }

  return (
    <div className="flex flex-col">
      <div className="flex flex-col divide-y divide-line px-5">
        <Field label={translate("Bezeichnung")} layout="row" className="py-4" required error={errors.label} help={translate("Name in Navigation, Tabellen und Formularen.")}>
          <Input value={draft.label} onChange={(e) => onChange({ label: e.target.value })} placeholder={translate("z. B. Widerstände")} />
        </Field>
        <Field
          label={translate("Bezeichner-Präfix")}
          layout="row"
          className="py-4"
          required
          error={errors.prefix}
          help={translate("Bezeichner im Schaltplan (R1, C3, U7) und Präfix interner Teilenummern.")}
        >
          <Input
            mono
            value={draft.prefix}
            onChange={(e) => onChange({ prefix: e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 8) })}
            containerClassName="max-w-32"
            maxLength={8}
          />
        </Field>
        <Field label={translate("Symbol und Farbe")} layout="row" className="py-4" error={errors.color} help={translate("Kennzeichnet die Kategorie im Bauteilbaum, in Diagrammen und Listen.")}>
          <div className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <CategoryTile icon={draft.icon} color={draft.color} size="lg" />
              <ColorPicker value={draft.color} onChange={(color) => onChange({ color })} className="min-w-0 flex-1" />
            </div>
            <IconPicker value={draft.icon} onChange={(icon) => onChange({ icon })} color={draft.color} />
          </div>
        </Field>
        <Field
          label={translate("Standardsymbol")}
          layout="row"
          className="py-4"
          help={translate("Neue Bauteile dieser Kategorie erhalten dieses Schaltplansymbol, sofern nichts anderes gewählt wird.")}
        >
          <div className="flex flex-col gap-2">
            <Select
              value={draft.default_symbol ?? NONE}
              onValueChange={(v) => onChange({ default_symbol: v === NONE ? null : v })}
              groups={groups}
              prefix={<Shapes />}
              placeholder={kinds.isPending ? translate("Lade Symboltypen …") : translate("Symbol wählen …")}
            />
            {draft.default_symbol && (
              <div className="relative h-32 overflow-hidden rounded-control border border-line">
                <SymbolCanvas
                  spec={preview.data?.spec}
                  interactive={false}
                  showGrid
                  showInfo={false}
                  aria-label={translate("Vorschau Standardsymbol {value1}", { value1: preview.data?.spec?.name ?? '' })}
                  className="h-full"
                />
                {preview.isFetching && (
                  <span className="absolute right-2 top-2">
                    <Spinner size={12} />
                  </span>
                )}
                {preview.data?.spec && (
                  <span className="mono absolute bottom-1.5 left-2 rounded-sm bg-surface/80 px-1.5 py-0.5 text-2xs text-fg-muted">
                    {preview.data.spec.name}
                  </span>
                )}
              </div>
            )}
          </div>
        </Field>
        <div className="py-4">
          <Switch
            checked={draft.altium_enabled}
            onCheckedChange={(v) => onChange({ altium_enabled: v })}
            label={translate("In Altium sichtbar")}
            description={translate("Die Kategorie erscheint als Tabelle in der DbLib. Ausgeschaltet bleiben die Bauteile nur in PartForge (z. B. Entwürfe).")}
          />
        </div>
        <Field
          label={translate("Tabellenname")}
          layout="row"
          className="py-4"
          error={errors.table}
          hint={translate("Altium-Bibliotheksname")}
          help={
            parts > 0
              ? translate("Enthält {value1} – der Name ist fest, weil Altium ihn in platzierten Bauteilen speichert. Die Bezeichnung lässt sich jederzeit ändern.", { value1: plural(parts, translate("Bauteil"), translate("Bauteile")) })
              : translate("ASCII ohne Umlaute; nur änderbar, solange die Kategorie leer ist.")
          }
        >
          <Input
            mono
            value={draft.table}
            onChange={(e) => onChange({ table: e.target.value })}
            disabled={parts > 0}
            prefix={<Database />}
            spellCheck={false}
          />
        </Field>
        {renamed && !errors.table && (
          <div className="py-4">
            <Callout tone="warning" icon={<TriangleAlert />} title={translate("Tabelle wird umbenannt")}>
              {translate("Die DbLib wird angepasst. Gespeicherte Ansichten ziehen mit.")}</Callout>
          </div>
        )}
      </div>

      <DangerZone category={category} onDeleted={onDeleted} />
    </div>
  )
}

/** „mit 3 Bauteilen“ / „mit einem Bauteil“ / „ohne Bauteile“ */
function partsText(parts: number): string {
  if (parts === 0) return translate("ohne Bauteile")
  return parts === 1 ? translate("mit einem Bauteil") : translate("mit {value1} Bauteilen", { value1: formatNumber(parts) })
}

function DangerZone({ category, onDeleted }: { category: CategoryDef; onDeleted: () => void }) {
  useI18n()
  const [open, setOpen] = useState(false)
  const del = useDeleteCategory()
  const navigate = useNavigate()
  const parts = category.part_count ?? 0
  return (
    <div className="mt-2 border-t border-danger/25 bg-danger/[0.04] px-5 py-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-ui font-medium text-fg">{translate("Kategorie löschen")}</div>
          <p className="mt-0.5 text-xs leading-snug text-fg-muted">
            {translate("Entfernt die Tabelle")}{' '}<span className="mono">{category.table}</span> {partsText(parts)}{translate(". Vorher wird automatisch eine Sicherung angelegt.")}</p>
        </div>
        <Button variant="danger" leftIcon={<Trash2 />} onClick={() => setOpen(true)}>
          {translate("Löschen …")}</Button>
      </div>
      <TypedConfirm
        open={open}
        onOpenChange={setOpen}
        icon={<Trash2 />}
        title={translate("„{value1}“ löschen?", { value1: category.label })}
        description={
          <>
            {translate("Die Tabelle")}{' '}<span className="mono text-fg">{category.table}</span> {' '}{translate("wird mit allen Feldern")}{' '}
            {parts === 0 ? '' : translate("und {value1} ", { value1: parts === 1 ? translate("einem Bauteil") : translate("{value1} Bauteilen", { value1: formatNumber(parts) }) })}{translate("aus der Datenbank entfernt.")}</>
        }
        phrase={category.table}
        confirmLabel={translate("Endgültig löschen")}
        onConfirm={async () => {
          const out = await del.mutateAsync(category.table)
          onDeleted()
          toast.success(translate("Kategorie „{value1}“ gelöscht", { value1: category.label }), {
            description: out.backup ? translate("Sicherung: {value1}", { value1: out.backup }) : undefined,
            action: { label: translate("Sicherungen"), onClick: () => navigate('/einstellungen/bibliothek') },
          })
        }}
      >
        <ul className="flex flex-col gap-1.5 text-xs leading-snug text-fg-muted">
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-danger" />
            {translate("Die Kategorie verschwindet aus der DbLib. In Altium-Designs platzierte Bauteile bleiben erhalten, verlieren aber den Datenbankabgleich.")}</li>
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
            {translate("Symbole, Footprints und Datenblätter bleiben in der Bibliothek.")}</li>
          <li className="flex gap-2">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-fg-subtle" />
            {translate("Rückgängig über Bibliothek › Sicherungen (automatische Sicherung „Vor dem Löschen“).")}</li>
        </ul>
      </TypedConfirm>
    </div>
  )
}
