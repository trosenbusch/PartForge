import { t, useI18n } from '@/lib/i18n'
import { ArrowRight, FolderInput, Upload } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { ImportScan } from '@/api/libimport'
import { Badge, Button, Callout, Card, CardContent, CardFooter, CardHeader, Field, Input, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { importFolder, type ImportPlan } from './model'
import { RelPath } from './ui'

export interface ImportOptionsState {
  target: string
  replace: boolean
  extract3d: boolean
  convert: boolean
}

export interface OptionsCardProps {
  scan: ImportScan
  plan: ImportPlan
  options: ImportOptionsState
  onOptionsChange: (patch: Partial<ImportOptionsState>) => void
  /** bereinigter Zielordner (wie im Backend) */
  folder: string
  /** anderer Zielordner als vorgeschlagen */
  retargeted: boolean
  /** Zustände für den gewählten Zielordner sind noch geschätzt (Antwort des Backends steht aus) */
  approximate?: boolean
  /** Ordner der Symbole bzw. Footprints in der Bibliothek */
  bases: { symbols: string; footprints: string }
  onStart: () => void
  starting: boolean
  /** Fehler beim Start (mit Behebung) */
  startError: ReactNode
  /** Grund, warum gerade nicht importiert werden kann (z. B. Einlesen läuft) */
  blocked: string | null
}

export function OptionsCard({
  scan,
  plan,
  options,
  onOptionsChange,
  folder,
  retargeted,
  approximate = retargeted,
  bases,
  onStart,
  starting,
  startError,
  blocked,
}: OptionsCardProps) {
  useI18n()
  const sanitized = options.target.trim() !== '' && folder !== options.target.trim()
  const anyImported = scan.imported > 0 || scan.files.some((f) => f.exists !== 'no')
  const nothing = plan.files === 0
  const skippedNames = plan.taken + plan.duplicates

  return (
    <Card>
      <CardHeader icon={<FolderInput />} title={t("Importieren")} titleAs="h2" description={t("Kopiert die gewählten Dateien unverändert.")} />
      <CardContent className="flex flex-col gap-3.5">
        <Field
          label={t("Zielordner")}
          hint={retargeted ? t("geändert") : t("Vorschlag")}
          help={sanitized ? t("Wird zu „{0}“ – Zeichen wie \\ / : * ? \" < > | sind in Ordnernamen nicht erlaubt.", { "0": String(folder) }) : undefined}
        >
          <Input
            mono
            value={options.target}
            onChange={(e) => onOptionsChange({ target: e.target.value })}
            placeholder={scan.name}
            spellCheck={false}
            autoComplete="off"
            disabled={starting}
          />
        </Field>
        <ul className="-mt-2 flex flex-col gap-0.5 text-2xs text-fg-subtle" aria-label={t("Zielordner in der Bibliothek")}>
          <li>
            {t("Symbole: ")}<RelPath rel={`${importFolder(bases.symbols, folder)}\\`} className="text-2xs" />
          </li>
          <li>
            Footprints: <RelPath rel={`${importFolder(bases.footprints, folder)}\\`} className="text-2xs" />
          </li>
        </ul>
        {approximate && anyImported && (
          <Callout tone="warning" className="px-3 py-2.5">
            {t("Schon importierte Dateien liegen in „")}{scan.name}{t("“. Mit einem anderen Zielordner gelten ihre Namen als vergeben und werden nicht noch einmal übernommen.")}</Callout>
        )}

        <div className="flex flex-col gap-3">
          <Switch
            checked={options.replace && plan.changed > 0}
            onCheckedChange={(replace) => onOptionsChange({ replace })}
            disabled={plan.changed === 0 || starting}
            label={
              <span className="flex flex-wrap items-center gap-1.5">
                {t("Geänderte ersetzen")}{plan.changed > 0 && (
                  <Badge variant="warning" className="tabular-nums">
                    {formatNumber(plan.changed)}
                  </Badge>
                )}
              </span>
            }
            description={
              plan.changed > 0
                ? t("{0} seit dem letzten Import geändert. Ersetzt gilt die neue Fassung – Namen, die darin fehlen, werden abgemeldet.", { "0": String(plural(plan.changed, t("Datei wurde"), t("Dateien wurden"))) })
                : t("Keine gewählte, schon importierte Datei wurde seither geändert.")
            }
          />
          <Switch
            checked={options.extract3d}
            onCheckedChange={(extract3d) => onOptionsChange({ extract3d })}
            disabled={starting || plan.footprints === 0}
            label={t("3D-Modelle vorab ablegen")}
            description={
              plan.footprints === 0
                ? t("Keine Footprints in der Auswahl.")
                : plan.with3d > 0
                  ? t("{0} ein 3D-Modell. STEP-Dateien jetzt im Ordner „3D“ ablegen; sonst lädt die Vorschau sie bei Bedarf.", { "0": String(plural(plan.with3d, t("Footprint hat"), t("Footprints haben"))) })
                  : t("Eingebettete STEP-Dateien jetzt im Ordner „3D“ ablegen; sonst lädt die Vorschau sie bei Bedarf.")
            }
          />
          <div className="flex flex-col gap-1">
            <Switch
              checked={options.convert}
              onCheckedChange={(convert) => onOptionsChange({ convert })}
              disabled={starting}
              label={t("An den Hausstil angleichen")}
              description={t("Danach mit den Regeln der letzten Stapelbearbeitung – mit Sicherung, dort auch rückgängig.")}
            />
            <Link
              to="/stapelbearbeitung"
              className="inline-flex w-fit items-center gap-1 rounded-sm text-xs font-medium text-accent-text underline-offset-4 outline-none hover:underline focus-ring"
            >
              {t("Regeln ansehen")}<ArrowRight aria-hidden className="size-3" />
            </Link>
          </div>
        </div>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-3">
        <div className="flex flex-col gap-1.5">
          <p className="text-ui leading-snug text-fg" aria-live="polite" aria-atomic="true">
            {nothing ? (
              <span className="font-medium">{t("Nichts zu übernehmen")}</span>
            ) : (
              <>
                <Num value={plan.files} one={t("Datei")} many={t("Dateien")} /> · <Num value={plan.symbols} one="Symbol" many={t("Symbole")} /> ·{' '}
                <Num value={plan.footprints} one="Footprint" many="Footprints" /> {plan.files === 1 ? t("wird") : t("werden")} {t(" übernommen")}</>
            )}
          </p>
          <ul className="flex flex-col gap-0.5 text-xs text-fg-muted">
            {plan.selected === 0 && <li>{t("Keine Datei ausgewählt.")}</li>}
            {skippedNames > 0 && (
              <li className="text-warning-text">
                {plural(skippedNames, t("Name ist"), t("Namen sind"))} {plan.duplicates && plan.taken ? t("vergeben oder doppelt") : plan.taken ? t("vergeben") : t("doppelt")}{' '}
                {t("und ")}{skippedNames === 1 ? t("wird") : t("werden")} {t(" übersprungen")}</li>
            )}
            {plan.noNames > 0 && (
              <li>
                {plural(plan.noNames, t("Datei ohne übernehmbaren Namen wird"), t("Dateien ohne übernehmbare Namen werden"))} {t(" nicht kopiert")}</li>
            )}
            {plan.kept > 0 && <li className="text-warning-text">{plural(plan.kept, t("geänderte Datei bleibt"), t("geänderte Dateien bleiben"))} {t(" unverändert")}</li>}
            {plan.unchanged > 0 && (
              <li>
                {plural(plan.unchanged, t("Datei ist"), t("Dateien sind"))} {t(" schon unverändert importiert – ")}{plan.unchanged === 1 ? t("ihre") : t("deren")} {t(" Namen werden aufgefrischt")}</li>
            )}
          </ul>
        </div>
        {startError}
        <Button
          variant="primary"
          leftIcon={<Upload />}
          loading={starting}
          disabled={nothing || Boolean(blocked)}
          onClick={onStart}
          className="w-full"
        >
          {nothing ? t("Importieren") : t("{0} importieren", { "0": String(plural(plan.files, t("Datei"), t("Dateien"))) })}
        </Button>
        {blocked && <p className="-mt-1 text-center text-2xs text-fg-subtle">{blocked}</p>}
      </CardFooter>
    </Card>
  )
}

function Num({ value, one, many }: { value: number; one: string; many: string }) {
  useI18n()
  return (
    <span className={cn('whitespace-nowrap', value === 0 && 'text-fg-muted')}>
      <span className="mono font-semibold tabular-nums">{formatNumber(value)}</span> {value === 1 ? one : many}
    </span>
  )
}
