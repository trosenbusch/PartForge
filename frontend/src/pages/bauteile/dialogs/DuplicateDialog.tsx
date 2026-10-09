/**
 * Duplizieren: ein Bauteil unter neuer Teilenummer oder mehrere Bauteile mit einem Suffix. Kopien starten als
 * „Entwurf“. Teilenummern-Schema „mpn“: Teilenummer = Hersteller-Teilenummer – vorbelegt ist die Nummer der
 * Vorlage zum Abwandeln (eine Kopie heißt nie „…-KOPIE“ als Hersteller-Teilenummer). Schema „intern“: die
 * Teilenummer vergibt PartForge, die Hersteller-Teilenummer ist frei.
 */
import { useMutation } from '@tanstack/react-query'
import { CopyPlus } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import type { CategoryDef } from '@/api/library'
import { partsApi, PART_NUMBER, usePartsInvalidation, type PartRow } from '@/api/parts'
import {
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  Input,
  ProgressBar,
} from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'

export interface DuplicateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  category: CategoryDef
  rows: PartRow[]
  /** Teilenummern-Schema der Bibliothek („mpn“: Teilenummer = Hersteller-Teilenummer, „internal“: vergeben) */
  scheme: string | undefined
  /** Neu angelegte Teilenummern (erste wird geöffnet) */
  onDone: (created: string[]) => void
}

const MPN = 'Manufacturer Part Number'

export function DuplicateDialog({ open, onOpenChange, category, rows, scheme, onDone }: DuplicateDialogProps) {
  const single = rows.length === 1 ? rows[0] : null
  const sourcePn = single ? String(single[PART_NUMBER] ?? '') : ''
  const sourceMpn = single ? String(single[MPN] ?? '') : ''
  const mpnScheme = scheme !== 'internal'
  const hasMpn = category.fields.some((f) => f.column === MPN)
  const [pn, setPn] = useState('')
  const [mpn, setMpn] = useState('')
  const [suffix, setSuffix] = useState('-KOPIE')
  const [progress, setProgress] = useState<number | null>(null)
  const [failed, setFailed] = useState<string[]>([])
  const invalidate = usePartsInvalidation()

  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      // „mpn“: Nummer der Vorlage zum Abwandeln; „intern“: leer = nächste freie Nummer
      setPn(mpnScheme ? sourcePn : '')
      setMpn(sourceMpn)
      setSuffix('-KOPIE')
      setProgress(null)
      setFailed([])
    }
  }

  const targets = useMemo(
    () => rows.map((r) => String(r[PART_NUMBER] ?? '')).filter(Boolean).map((p) => ({ from: p, to: `${p}${suffix}` })),
    [rows, suffix],
  )
  const unchanged = mpnScheme && pn.trim().toLowerCase() === sourcePn.toLowerCase()

  /** Hersteller-Teilenummer der Kopie setzen – ein Fehler macht die Kopie nicht ungeschehen, er wird gemeldet */
  const setCopyMpn = async (copyPn: string, wanted: string, part: PartRow): Promise<string | null> => {
    if (!hasMpn || !wanted || wanted === String(part[MPN] ?? '')) return null
    try {
      await partsApi.update(category.table, copyPn, { [MPN]: wanted })
      return null
    } catch (err) {
      return errorMessage(err)
    }
  }

  const run = useMutation({
    mutationFn: async () => {
      const created: string[] = []
      const errors: string[] = []
      const mpnProblems: string[] = []
      if (single) {
        const res = await partsApi.duplicate(category.table, sourcePn, pn.trim())
        const newPn = String(res.part[PART_NUMBER] ?? pn.trim())
        created.push(newPn)
        const problem = await setCopyMpn(newPn, (mpnScheme ? newPn : mpn).trim(), res.part)
        if (problem) mpnProblems.push(`${newPn}: ${problem}`)
      } else {
        for (let i = 0; i < targets.length; i++) {
          setProgress(i / targets.length)
          try {
            const res = await partsApi.duplicate(category.table, targets[i].from, targets[i].to)
            const newPn = String(res.part[PART_NUMBER] ?? targets[i].to)
            created.push(newPn)
            if (mpnScheme) {
              const problem = await setCopyMpn(newPn, newPn, res.part)
              if (problem) mpnProblems.push(`${newPn}: ${problem}`)
            }
          } catch (err) {
            errors.push(`${targets[i].from}: ${errorMessage(err)}`)
          }
        }
        setProgress(1)
      }
      return { created, errors, mpnProblems }
    },
    meta: { silentError: true },
    onSuccess: ({ created, errors, mpnProblems }) => {
      invalidate(category.table)
      if (errors.length) setFailed(errors)
      if (created.length) {
        toast.success(created.length === 1 ? `„${created[0]}“ angelegt` : `${plural(created.length, 'Kopie', 'Kopien')} angelegt`, {
          description: 'Kopien starten als Entwurf.',
        })
        if (mpnProblems.length) {
          toast.warning('Hersteller-Teilenummer nicht geändert', {
            description: `${mpnProblems.slice(0, 3).join(' · ')} – die Kopie trägt noch die der Vorlage.`,
          })
        }
        onDone(created)
      }
      if (!errors.length) onOpenChange(false)
    },
    onError: (err) => setFailed([errorMessage(err)]),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (single ? (mpnScheme ? pn.trim() && !unchanged : true) : suffix.trim()) run.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !run.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader
            icon={<CopyPlus />}
            title={single ? 'Bauteil duplizieren' : `${plural(rows.length, 'Bauteil', 'Bauteile')} duplizieren`}
            description={
              single
                ? `Alle Werte von „${sourcePn}“ werden übernommen – Symbol, Footprint und Datenblatt eingeschlossen.`
                : 'Jede Kopie erhält die bisherige Teilenummer mit dem Suffix. Alle Werte werden übernommen.'
            }
          />
          <DialogBody className="flex flex-col gap-4">
            {single ? (
              mpnScheme ? (
                <Field
                  label={hasMpn ? 'Neue Hersteller-Teilenummer' : 'Neue Teilenummer'}
                  required
                  help={
                    unchanged
                      ? 'Noch die Nummer der Vorlage – abwandeln, z. B. den Wert-Code.'
                      : hasMpn
                        ? 'Wird auch die Teilenummer (Schema dieser Bibliothek). Muss in der ganzen Bibliothek eindeutig sein.'
                        : 'Muss in der ganzen Bibliothek eindeutig sein.'
                  }
                >
                  <Input value={pn} onChange={(e) => setPn(e.target.value)} mono onFocus={(e) => e.target.select()} />
                </Field>
              ) : (
                <>
                  <Field label="Neue Teilenummer" help="Leer lassen – PartForge vergibt die nächste freie Nummer.">
                    <Input value={pn} onChange={(e) => setPn(e.target.value)} mono placeholder="automatisch" />
                  </Field>
                  {hasMpn && (
                    <Field label="Hersteller-Teilenummer" help="Von der Vorlage übernommen – für eine Variante anpassen.">
                      <Input value={mpn} onChange={(e) => setMpn(e.target.value)} mono onFocus={(e) => e.target.select()} />
                    </Field>
                  )}
                </>
              )
            ) : (
              <>
                <Field label="Suffix für die Teilenummern" required>
                  <Input value={suffix} onChange={(e) => setSuffix(e.target.value)} mono />
                </Field>
                <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto rounded-button border border-line bg-surface-2/50 px-3 py-2 text-xs">
                  {targets.slice(0, 50).map((t) => (
                    <li key={t.from} className="mono flex min-w-0 items-center gap-2">
                      <span className="truncate text-fg-muted">{t.from}</span>
                      <span aria-hidden className="text-fg-subtle">
                        →
                      </span>
                      <span className="truncate text-fg">{t.to}</span>
                    </li>
                  ))}
                  {targets.length > 50 && <li className="text-fg-subtle">… und {formatNumber(targets.length - 50)} weitere</li>}
                </ul>
                {progress !== null && <ProgressBar value={progress} live={run.isPending} label="Kopien werden angelegt" showValue />}
              </>
            )}
            {failed.length > 0 && (
              <Callout tone="danger" title={single ? 'Nicht dupliziert' : 'Einige Kopien wurden nicht angelegt'} urgent>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {failed.slice(0, 6).map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              </Callout>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={run.isPending}>
              {failed.length && !single ? 'Schließen' : 'Abbrechen'}
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={run.isPending}
              disabled={single ? mpnScheme && (!pn.trim() || unchanged) : !suffix.trim()}
            >
              {single ? 'Duplizieren' : `${formatNumber(rows.length)} duplizieren`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
