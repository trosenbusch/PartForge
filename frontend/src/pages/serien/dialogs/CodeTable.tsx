/** Codetabelle einer Variable im Vorlagen-Editor: Code · Bedeutung · Beschriftung · Vorgabe. */
import { Plus, Trash2 } from 'lucide-react'
import { Button, IconButton, Input } from '@/components/ui'
import { cn } from '@/lib/cn'
import { optionKey, type DraftVariable } from './customTemplate'

export interface CodeTableProps {
  variable: DraftVariable
  unused: boolean
  onChange: (v: DraftVariable) => void
}

const PLACEHOLDER: Record<string, string> = {
  tolerance: '±1%',
  tcr: '±100ppm/K',
  voltage: '50V',
  dielectric: 'X7R',
}

export function CodeTable({ variable: v, unused, onChange }: CodeTableProps) {
  const set = (key: string, patch: Partial<DraftVariable['options'][number]>) =>
    onChange({ ...v, options: v.options.map((o) => (o.key === key ? { ...o, ...patch } : o)) })
  const setDefault = (key: string) => onChange({ ...v, options: v.options.map((o) => ({ ...o, isDefault: o.key === key })) })
  return (
    <div className={cn('rounded-control border border-line', unused && 'opacity-60')}>
      <div className="flex items-center gap-2 border-b border-line bg-surface-2/50 px-3 py-2">
        <span className="mono rounded-sm bg-surface-3 px-1.5 py-0.5 text-2xs text-fg-muted">{`{${v.name}}`}</span>
        <Input
          size="sm"
          value={v.label}
          onChange={(e) => onChange({ ...v, label: e.target.value })}
          aria-label={`Bezeichnung der Variable ${v.name}`}
          containerClassName="max-w-[14rem]"
        />
        {unused && <span className="text-2xs text-fg-subtle">nicht im Muster</span>}
        <Button
          size="xs"
          variant="ghost"
          leftIcon={<Plus />}
          className="ml-auto"
          onClick={() =>
            onChange({ ...v, options: [...v.options, { key: optionKey(), code: '', value: '', label: '', isDefault: !v.options.length }] })
          }
        >
          Code
        </Button>
      </div>
      <table className="w-full table-fixed text-left">
        <thead>
          <tr className="text-2xs text-fg-subtle">
            <th scope="col" className="w-[22%] px-3 pb-1 pt-2 font-medium">
              Code
            </th>
            <th scope="col" className="w-[28%] px-1 pb-1 pt-2 font-medium">
              Bedeutung
            </th>
            <th scope="col" className="px-1 pb-1 pt-2 font-medium">
              Beschriftung
            </th>
            <th scope="col" className="w-16 px-1 pb-1 pt-2 text-center font-medium">
              Vorgabe
            </th>
            <th scope="col" className="w-10 pb-1 pt-2">
              <span className="sr-only">Entfernen</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {v.options.map((o, i) => (
            <tr key={o.key} className="align-middle">
              <td className="px-3 py-1">
                <Input
                  size="sm"
                  mono
                  value={o.code}
                  onChange={(e) => set(o.key, { code: e.target.value })}
                  placeholder="leer"
                  aria-label={`Code ${i + 1} von ${v.label}`}
                />
              </td>
              <td className="px-1 py-1">
                <Input
                  size="sm"
                  mono
                  value={o.value}
                  onChange={(e) => set(o.key, { value: e.target.value })}
                  placeholder={PLACEHOLDER[v.name] ?? 'optional'}
                  aria-label={`Bedeutung von Code ${i + 1}`}
                />
              </td>
              <td className="px-1 py-1">
                <Input
                  size="sm"
                  value={o.label}
                  onChange={(e) => set(o.key, { label: e.target.value })}
                  placeholder="optional"
                  aria-label={`Beschriftung von Code ${i + 1}`}
                />
              </td>
              <td className="px-1 py-1 text-center">
                <input
                  type="radio"
                  name={`default-${v.name}`}
                  checked={o.isDefault}
                  onChange={() => setDefault(o.key)}
                  aria-label={`Code ${i + 1} als Vorgabe`}
                  className="size-4 accent-[var(--pf-accent)] focus-ring"
                />
              </td>
              <td className="py-1 pr-2">
                <IconButton
                  size="xs"
                  label={`Code ${i + 1} entfernen`}
                  icon={<Trash2 />}
                  disabled={v.options.length <= 1}
                  onClick={() => onChange({ ...v, options: v.options.filter((x) => x.key !== o.key) })}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
