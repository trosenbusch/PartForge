/**
 * Nächste Schritte nach dem Import: „Bauteile anlegen …“ je importierter Symbolbibliothek (eine Tabelle gehört in
 * **eine** Kategorie) bzw. für alle – die Tabelle der Symbole geht als vorbereiteter Upload an den Tabellen-Import der
 * Bauteile (`/bauteile`, Router-State `partsUpload`); „An Hausstil angleichen …“ (Stapelbearbeitung mit den importierten
 * Bibliotheken, Router-State `libraries`), Symbole/Footprints ansehen, weitere Quelle importieren.
 */
import { CircuitBoard, FolderInput, PaintbrushVertical, RotateCw, Search, Shapes, Signpost, TableProperties, X } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { usePartsTable } from '@/api/libimport'
import { Button, Card, CardContent, CardFooter, CardHeader, IconButton, Input } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { compareNatural, isSchLib, splitRel } from './model'

/** So viele Symbolbibliotheken stehen zuerst in der Liste (weitere auf Wunsch) */
const LIB_PAGE = 8

export interface NextStepsProps {
  /** geschriebene Bibliotheksdateien (relativ zur Bibliothek) */
  libraries: string[]
  /** Zielordner des Imports (für die Beschriftung „alle“) */
  folder: string
  /** der Import hat schon an den Hausstil angeglichen */
  converted: boolean
  onReset: () => void
  /** Quelle erneut einlesen (aktuelle Zustände) – `null`, wenn die Quelle nicht bekannt ist */
  onRescan: (() => void) | null
}

export function NextSteps({ libraries, folder, converted, onReset, onRescan }: NextStepsProps) {
  const navigate = useNavigate()
  const schLibs = libraries.filter(isSchLib).sort(compareNatural)
  const footprints = libraries.length - schLibs.length
  return (
    <Card>
      <CardHeader icon={<Signpost />} title="Wie geht es weiter?" titleAs="h2" />
      <CardContent className="flex flex-col gap-5">
        {libraries.length === 0 && (
          <p className="text-xs leading-relaxed text-fg-muted">
            Es wurde keine Bibliotheksdatei übernommen – die Gründe stehen im Ergebnis. Eine andere Auswahl oder Quelle wählen.
          </p>
        )}
        {schLibs.length > 0 && <PartsFromSymbols libraries={schLibs} folder={folder} />}
        {libraries.length > 0 && (
          <section aria-labelledby="bibliotheksimport-hausstil" className="flex flex-col gap-2">
            <h3 id="bibliotheksimport-hausstil" className="text-ui font-medium text-fg">
              Hausstil
            </h3>
            <p className="text-xs leading-relaxed text-fg-muted">
              {converted
                ? 'Die importierten Bibliotheken wurden schon angeglichen. In der Stapelbearbeitung lässt sich das prüfen oder rückgängig machen.'
                : 'Schriften, Pinlängen, Lagen und Linienbreiten der importierten Bibliotheken an den Hausstil angleichen – die Stapelbearbeitung prüft zuerst und sichert vorher.'}
            </p>
            <div>
              <Button
                size="sm"
                variant="secondary"
                leftIcon={<PaintbrushVertical />}
                onClick={() => navigate('/stapelbearbeitung', { state: { libraries } })}
              >
                {converted ? 'In der Stapelbearbeitung ansehen …' : 'An Hausstil angleichen …'}
              </Button>
            </div>
          </section>
        )}
        <div className="flex flex-wrap gap-2">
          {schLibs.length > 0 && (
            <Button asChild size="sm" variant="ghost">
              <Link to="/symbole">
                <Shapes aria-hidden className="size-3.5" />
                Zu den Symbolen
              </Link>
            </Button>
          )}
          {footprints > 0 && (
            <Button asChild size="sm" variant="ghost">
              <Link to="/footprints">
                <CircuitBoard aria-hidden className="size-3.5" />
                Zu den Footprints
              </Link>
            </Button>
          )}
        </div>
      </CardContent>
      <CardFooter className="flex-wrap justify-between">
        <Button size="sm" variant="secondary" leftIcon={<FolderInput />} onClick={onReset}>
          Weitere Quelle importieren
        </Button>
        {onRescan && (
          <Button size="sm" variant="ghost" leftIcon={<RotateCw />} onClick={onRescan}>
            Quelle erneut einlesen
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}

/** „Bauteile anlegen …“: je Symbolbibliothek bzw. alle – Tabelle der Symbole für den Tabellen-Import */
function PartsFromSymbols({ libraries, folder }: { libraries: string[]; folder: string }) {
  const navigate = useNavigate()
  const table = usePartsTable()
  /** Bibliothek, deren Tabelle gerade erstellt wird (`*` = alle) */
  const [pending, setPending] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(LIB_PAGE)
  const needle = query.trim().toLowerCase()
  const matches = needle ? libraries.filter((l) => l.toLowerCase().includes(needle)) : libraries
  const shown = matches.slice(0, limit)
  const rest = matches.length - shown.length

  const create = (libs: string[], label: string, key: string) => {
    setPending(key)
    table.mutate(
      { libraries: libs },
      {
        onSuccess: (upload) =>
          navigate('/bauteile', {
            state: { partsUpload: { token: upload.token, fileName: upload.file_name, rows: upload.rows, label } },
          }),
        onSettled: () => setPending(null),
      },
    )
  }

  return (
    <section aria-labelledby="bibliotheksimport-bauteile" className="flex flex-col gap-2">
      <h3 id="bibliotheksimport-bauteile" className="text-ui font-medium text-fg">
        Bauteile anlegen
      </h3>
      <p className="text-xs leading-relaxed text-fg-muted">
        Aus den importierten Symbolen eine Tabelle mit ihren Parametern und Footprint-Verweisen erstellen – der Tabellen-Import ordnet die
        Spalten zu. Eine Tabelle kommt in <em className="not-italic text-fg">eine</em> Kategorie: am besten je Bibliothek.
      </p>
      {libraries.length > 1 && (
        <div>
          <Button
            size="sm"
            variant="secondary"
            leftIcon={<TableProperties />}
            loading={pending === '*'}
            disabled={pending !== null && pending !== '*'}
            onClick={() => create(libraries, `Alle Symbole aus „${folder}“`, '*')}
          >
            Alle {formatNumber(libraries.length)} Symbolbibliotheken …
          </Button>
        </div>
      )}
      {libraries.length > LIB_PAGE && (
        <Input
          size="sm"
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setLimit(LIB_PAGE)
          }}
          placeholder="Bibliothek suchen …"
          aria-label="Symbolbibliotheken durchsuchen"
          prefix={<Search />}
          suffix={query ? <IconButton size="xs" label="Suche leeren" icon={<X />} onClick={() => setQuery('')} tooltip={false} /> : undefined}
          containerClassName="w-64 max-w-full"
        />
      )}
      {shown.length > 0 ? (
        <ul className="flex flex-col divide-y divide-line border-y border-line" aria-label="Importierte Symbolbibliotheken">
          {shown.map((lib) => {
            const { folder: dir, name } = splitRel(lib)
            return (
              <li key={lib} className="flex items-center gap-3 py-1.5">
                <Shapes aria-hidden className="size-4 shrink-0 text-fg-subtle" />
                <div className="min-w-0 flex-1" title={lib}>
                  <div className="truncate text-ui text-fg">{name}</div>
                  {dir && <div className="mono truncate text-2xs text-fg-subtle">{dir}</div>}
                </div>
                <Button
                  size="xs"
                  variant="ghost"
                  leftIcon={<TableProperties />}
                  loading={pending === lib}
                  disabled={pending !== null && pending !== lib}
                  onClick={() => create([lib], name, lib)}
                  aria-label={`Bauteile anlegen – ${name}`}
                >
                  Bauteile anlegen …
                </Button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="text-xs text-fg-subtle">Keine Bibliothek passt zu „{query.trim()}“.</p>
      )}
      {rest > 0 && (
        <div className="flex items-center gap-3 text-2xs text-fg-subtle">
          <Button size="xs" variant="ghost" onClick={() => setLimit((l) => l + LIB_PAGE * 4)}>
            {formatNumber(Math.min(rest, LIB_PAGE * 4))} weitere anzeigen
          </Button>
          {formatNumber(shown.length)} von {plural(matches.length, 'Bibliothek', 'Bibliotheken')}
        </div>
      )}
    </section>
  )
}
