import {
  Bold,
  Copy,
  Download,
  FileUp,
  Filter,
  Italic,
  Layers,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Sparkles,
  Trash2,
  Underline,
  Zap,
} from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { useElementSize } from '@/components/preview'
import { formatEngineering, nearestInSeries } from '@/lib/units'
import { SharedDemos } from './SharedDemos'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  Checkbox,
  ChipGroup,
  Combobox,
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Drawer,
  DrawerBody,
  DrawerContent,
  DrawerFooter,
  DrawerHeader,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Field,
  IconButton,
  Input,
  Kbd,
  KeyValueList,
  NumberInput,
  PageHeader,
  PathInput,
  Popover,
  PopoverContent,
  PopoverTrigger,
  ProgressBar,
  ProgressRing,
  ScrollArea,
  SegmentedControl,
  Select,
  Separator,
  Skeleton,
  SkeletonText,
  Slider,
  Spinner,
  StatCard,
  Stepper,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  Toolbar,
  ToolbarButton,
  ToolbarSeparator,
  ToolbarSpacer,
  Tooltip,
  confirm,
  type IllustrationName,
} from '@/components/ui'

/** E-Reihe E12 als Raster für den logarithmischen Slider (Pfeiltasten springen von Stufe zu Stufe) */
const snapE12 = (v: number) => nearestInSeries('E12', v)
const formatOhm = (v: number) => formatEngineering(v, 'Ω')

const ILLUSTRATIONS: IllustrationName[] = ['no-library', 'no-parts', 'drop-pdf', 'search-empty', 'all-good', 'forge', 'offline']

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} description={description} className="border-b border-line pb-3" />
      <CardContent className="pt-4">{children}</CardContent>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-4 py-2">
      <span className="micro-label">{label}</span>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}

/** Komponenten-Galerie (intern): alle Bausteine des UI-Kits in beiden Themes prüfen. */
export default function UiKitPage() {
  const [segment, setSegment] = useState<'grid' | 'list' | 'cards'>('grid')
  const [density, setDensity] = useState<'L' | 'N' | 'M'>('N')
  const [model, setModel] = useState('claude-opus-5-5')
  const [budget, setBudget] = useState<number | null>(2)
  const [resistance, setResistance] = useState<number | null>(4700)
  const [path, setPath] = useState('C:\\PartForge-Examples\\Altium_Libs\\PartForge\\Footprints\\PF_CHIP.PcbLib')
  const [sizes, setSizes] = useState<string[]>(['0402', '0603'])
  const [pkg, setPkg] = useState<string | null>('0603')
  const [checked, setChecked] = useState<boolean | 'indeterminate'>(true)
  const [sw, setSw] = useState(true)
  const [single, setSingle] = useState([40])
  const [range, setRange] = useState([1000, 470000])
  const [step, setStep] = useState(2)
  // wie im Serien-Assistenten: unter 900 px kurze Schritte ohne Beschreibung (nichts wird abgeschnitten)
  const [stepperRef, stepperSize] = useElementSize<HTMLDivElement>()
  const compactStepper = stepperSize.width > 0 && stepperSize.width < 900
  const [dialogOpen, setDialogOpen] = useState(false)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(false)
  const [showGrid, setShowGrid] = useState(true)
  // Bereich über den Hash wählbar (Screenshots): #vorschau bzw. #vorschau-3d (öffnet die 3D-Ansicht im Vollbild)
  const location = useLocation()
  const navigate = useNavigate()
  const area = location.hash.startsWith('#vorschau') ? 'geteilt' : 'basis'
  const setArea = (next: string) => navigate({ hash: next === 'geteilt' ? '#vorschau' : '' }, { replace: true })

  return (
    <PageBody>
      <PageTitle title="UI-Kit" subtitle="Alle Bausteine des Designsystems „Forge“" />
      <PageActions>
        <Button size="sm" variant="secondary" leftIcon={<Download />}>
          Beispiel-Aktion
        </Button>
      </PageActions>

      <PageHeader
        icon={<Layers />}
        eyebrow="Intern"
        title="Komponenten-Galerie"
        description="Referenz für alle Seiten: Varianten, Größen und Zustände – dazu die geteilten Vorschau-, Tabellen- und Daten-Bausteine mit echten Backend-Daten. Im Theme-Menü oben rechts zwischen Hell und Dunkel wechseln."
        actions={
          <>
            <Button variant="secondary" leftIcon={<Copy />}>
              Sekundär
            </Button>
            <Button variant="primary" leftIcon={<Plus />}>
              Primär
            </Button>
          </>
        }
      />

      <Tabs value={area} onValueChange={setArea} className="mt-6">
        <TabsList aria-label="Bereich">
          <TabsTrigger value="basis">Grundbausteine</TabsTrigger>
          <TabsTrigger value="geteilt">Vorschau und Daten</TabsTrigger>
        </TabsList>
        <TabsContent value="basis" className="pt-5">
          <div className="grid grid-cols-2 gap-5">
            <Section title="Buttons" description="primary · secondary · outline · ghost · danger · spark · link">
              <Row label="Varianten">
                <Button variant="primary" leftIcon={<Plus />}>
                  Primär
                </Button>
                <Button variant="secondary">Sekundär</Button>
                <Button variant="outline">Outline</Button>
                <Button variant="ghost">Ghost</Button>
                <Button variant="danger" leftIcon={<Trash2 />}>
                  Löschen
                </Button>
              </Row>
              <Row label="KI und Link">
                <Button variant="spark" leftIcon={<Sparkles />}>
                  Mit KI analysieren
                </Button>
                <Button variant="link">Mehr erfahren</Button>
              </Row>
              <Row label="Größen">
                <Button size="xs">XS</Button>
                <Button size="sm">Klein</Button>
                <Button size="md">Mittel</Button>
                <Button size="lg" variant="primary">
                  Groß
                </Button>
              </Row>
              <Row label="Zustände">
                <Button variant="primary" loading>
                  Speichert …
                </Button>
                <Button variant="spark" loading>
                  Analysiert …
                </Button>
                <Button disabled>Deaktiviert</Button>
                <IconButton label="Bearbeiten" icon={<Pencil />} hotkey="f2" />
                <IconButton label="Mehr" icon={<MoreHorizontal />} variant="secondary" />
              </Row>
            </Section>

            <Section title="Badges, Tasten und Ladeanzeigen">
              <Row label="Badges">
                <Badge>Neutral</Badge>
                <Badge variant="outline">Outline</Badge>
                <Badge variant="accent">Kupfer</Badge>
                <Badge variant="success" dot>
                  synchron
                </Badge>
                <Badge variant="warning" dot pulse>
                  veraltet
                </Badge>
                <Badge variant="danger">Konflikt</Badge>
                <Badge variant="info">neu</Badge>
                <Badge variant="spark">
                  <Sparkles />
                  KI
                </Badge>
              </Row>
              <Row label="Tasten">
                <Kbd hotkey="mod+k" />
                <Kbd hotkey="mod+shift+p" />
                <Kbd hotkey="alt+1" size="xs" />
                <Kbd>Esc</Kbd>
                <Kbd hotkey="delete" size="md" />
              </Row>
              <Row label="Spinner">
                <Spinner />
                <Spinner tone="accent" size={20} />
                <Spinner tone="spark" size={24} />
              </Row>
              <Row label="Ringe">
                <ProgressRing value={0.25} showValue />
                <ProgressRing value={0.66} tone="spark" showValue size={40} />
                <ProgressRing value={1} tone="success" size={40}>
                  ✓
                </ProgressRing>
                <ProgressRing indeterminate size={32} />
              </Row>
              <div className="mt-2 flex flex-col gap-3">
                <ProgressBar value={0.42} label="Serie wird angelegt" showValue live />
                <ProgressBar value={0.8} tone="spark" size="xs" />
                <ProgressBar indeterminate tone="accent" />
              </div>
            </Section>

            <Section title="Formulare" description="Field mit Label, Hilfe und Fehler; Input, Select, Combobox, Textarea">
              <div className="grid grid-cols-2 gap-4">
                <Field label="Suche" hint="optional">
                  <Input prefix={<Search />} placeholder="MPN, Wert, Gehäuse …" />
                </Field>
                <Field label="Widerstand" help="Mit Einheit">
                  <Input mono defaultValue="10k" suffix="Ω" />
                </Field>
                <Field label="Modell">
                  <Select
                    value={model}
                    onValueChange={setModel}
                    options={[
                      { value: 'claude-opus-5-5', label: 'Claude Opus 5.5', description: 'Empfohlen für Datenblätter' },
                      { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', description: 'Ausgewogen' },
                      { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', description: 'Schnell und günstig' },
                    ]}
                  />
                </Field>
                <Field label="Bauform">
                  <Combobox
                    value={pkg}
                    onValueChange={setPkg}
                    allowCustom
                    clearable
                    mono
                    options={['0201', '0402', '0603', '0805', '1206', '1210', '2512'].map((v) => ({
                      value: v,
                      label: v,
                      description: `Chip ${v} (imperial)`,
                      group: 'Chip-Bauformen',
                    }))}
                  />
                </Field>
                <Field label="Toleranz" error="Bitte einen Wert zwischen 0,01 % und 20 % angeben.">
                  <Input mono defaultValue="25" suffix="%" />
                </Field>
                <Field label="Beschreibung">
                  <Textarea autoResize placeholder="Freitext …" defaultValue="Dickschicht-Chipwiderstand, AEC-Q200" />
                </Field>
                <Field label="Budget (NumberInput)" help="„2,5“ oder „2.5“ – geprüft beim Verlassen">
                  <NumberInput value={budget} onValueChange={setBudget} min={0} max={100} step={0.5} unit="USD" />
                </Field>
                <Field label="Wert (technisch)" help="„4k7“, „100n“, „2,2 M“">
                  <NumberInput value={resistance} onValueChange={setResistance} engineering min={0} unit="Ω" decimals={3} />
                </Field>
                <Field label="Pfad (PathInput)" className="col-span-2" help="Zeigt ohne Fokus das Ende des Pfads">
                  <PathInput value={path} onValueChange={setPath} browse="file" />
                </Field>
              </div>
              <div className="mt-4">
                <div className="micro-label mb-2">Bauformen (ChipGroup)</div>
                <ChipGroup
                  aria-label="Bauformen"
                  mono
                  value={sizes}
                  onValueChange={setSizes}
                  options={['0201', '0402', '0603', '0805', '1206'].map((v) => ({ value: v, label: v }))}
                />
              </div>
              <Separator className="my-4" />
              <div className="grid grid-cols-2 gap-4">
                <Checkbox
                  checked={checked}
                  onCheckedChange={setChecked}
                  label="Footprints mit erzeugen"
                  description="Fehlende Footprints werden nach IPC-7351 generiert."
                />
                <Checkbox checked="indeterminate" label="Teilweise ausgewählt" />
                <Switch checked={sw} onCheckedChange={setSw} label="Automatisch synchronisieren" description="Nach jeder Änderung." />
                <Switch tone="spark" defaultChecked label="KI-Vorschläge" description="Werte automatisch ergänzen." />
              </div>
            </Section>

            <Section title="Umschalter, Slider und Tabs">
              <Row label="Segmente">
                <SegmentedControl
                  value={segment}
                  onValueChange={setSegment}
                  aria-label="Ansicht"
                  options={[
                    { value: 'grid', label: 'Raster' },
                    { value: 'list', label: 'Liste' },
                    { value: 'cards', label: 'Karten' },
                  ]}
                />
                <SegmentedControl
                  size="sm"
                  value={density}
                  onValueChange={setDensity}
                  aria-label="Dichte"
                  options={[
                    { value: 'L', label: 'L' },
                    { value: 'N', label: 'N' },
                    { value: 'M', label: 'M' },
                  ]}
                />
              </Row>
              <div className="mt-3 flex flex-col gap-5">
                <div>
                  <div className="micro-label mb-2">Einfach (linear)</div>
                  <Slider value={single} onValueChange={setSingle} min={0} max={100} formatValue={(v) => `${Math.round(v)} %`} aria-label="Wert" />
                </div>
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <span className="micro-label">Bereich (logarithmisch, E12)</span>
                    <span className="mono text-xs text-fg">
                      {formatOhm(range[0])} – {formatOhm(range[1])}
                    </span>
                  </div>
                  <Slider
                    value={range}
                    onValueChange={setRange}
                    min={1}
                    max={10_000_000}
                    scale="log"
                    snap={snapE12}
                    formatValue={formatOhm}
                    thumbLabels={['Minimum', 'Maximum']}
                    marks={[1, 100, 10_000, 1_000_000, 10_000_000]}
                  />
                </div>
              </div>
              <Separator className="my-4" />
              <Tabs defaultValue="parameter">
                <TabsList>
                  <TabsTrigger value="parameter" count={12}>
                    Parameter
                  </TabsTrigger>
                  <TabsTrigger value="symbol">Symbol</TabsTrigger>
                  <TabsTrigger value="footprint">Footprint</TabsTrigger>
                  <TabsTrigger value="historie" count={3}>
                    Historie
                  </TabsTrigger>
                </TabsList>
                <TabsContent value="parameter" className="pt-3 text-xs text-fg-muted">
                  Unterstrich-Tabs mit animierter Markierung.
                </TabsContent>
                <TabsContent value="symbol" className="pt-3 text-xs text-fg-muted">
                  Symbolvorschau …
                </TabsContent>
                <TabsContent value="footprint" className="pt-3 text-xs text-fg-muted">
                  Footprintvorschau …
                </TabsContent>
                <TabsContent value="historie" className="pt-3 text-xs text-fg-muted">
                  Änderungen …
                </TabsContent>
              </Tabs>
              <Tabs defaultValue="2d" variant="pill" className="mt-4">
                <TabsList className="self-start">
                  <TabsTrigger value="2d">2D</TabsTrigger>
                  <TabsTrigger value="3d">3D</TabsTrigger>
                  <TabsTrigger value="altium">Altium-Ansicht</TabsTrigger>
                </TabsList>
              </Tabs>
            </Section>
          </div>

          <div className="mt-5 flex flex-col gap-5">
            <Section title="Assistent (Stepper)">
              <div ref={stepperRef}>
              <Stepper
                current={step}
                onStepClick={setStep}
                compact={compactStepper}
                steps={
                  compactStepper
                    ? [
                        { id: 'kat', label: 'Kategorie' },
                        { id: 'serie', label: 'Serie' },
                        { id: 'werte', label: 'Werte' },
                        { id: 'vorschau', label: 'Vorschau' },
                        { id: 'erzeugen', label: 'Erzeugen' },
                      ]
                    : [
                        { id: 'kat', label: 'Kategorie', description: 'Widerstände' },
                        { id: 'serie', label: 'Hersteller-Serie', description: 'Yageo RC0603' },
                        { id: 'werte', label: 'Werte und Varianten', description: 'E96 · 1 Ω … 10 MΩ' },
                        { id: 'vorschau', label: 'Vorschau', description: '1.156 Bauteile' },
                        { id: 'erzeugen', label: 'Erzeugen' },
                      ]
                }
              />
              </div>
              <div className="mt-4 flex gap-2">
                <Button size="sm" onClick={() => setStep((s) => Math.max(0, s - 1))}>
                  Zurück
                </Button>
                <Button size="sm" variant="primary" onClick={() => setStep((s) => Math.min(4, s + 1))}>
                  Weiter
                </Button>
              </div>
            </Section>

            <div className="grid grid-cols-2 gap-4 @[64rem]:grid-cols-4">
              <StatCard label="Bauteile" value={1156} icon={<Layers />} delta={{ value: 289, label: 'diese Woche' }} sparkline={[3, 5, 4, 8, 12, 11, 15, 22]} />
              <StatCard label="Footprints" value={87} icon={<Zap />} hint="alle synchron" />
              <StatCard label="KI-Importe" value={23} tone="spark" icon={<Sparkles />} delta={{ value: 0 }} />
              <StatCard label="Offene Punkte" value={5} tone="warning" icon={<Filter />} delta={{ value: 3, upIsGood: false }} hint="seit gestern" />
            </div>

            <Section title="Hinweise (Callout)" description="neutral · info · success · warning · danger · spark">
              <div className="grid grid-cols-1 gap-3 @[48rem]:grid-cols-2">
                <Callout tone="info" title="DbLib wird beim Öffnen aktualisiert">Wenn der Ordner verschoben wurde, schreibt PartForge die Pfade neu.</Callout>
                <Callout tone="warning" title="3 Footprints ausstehend" actions={<Button size="sm">Synchronisieren</Button>}>
                  Sie werden beim nächsten Abgleich in die PcbLib geschrieben.
                </Callout>
                <Callout tone="danger" title="Import fehlgeschlagen">Seite 7 ist nicht lesbar (gescannt, ohne Textebene).</Callout>
                <Callout tone="spark" title="KI-Vorschlag">Werte aus dem Datenblatt – bitte vor dem Anlegen prüfen.</Callout>
              </div>
            </Section>

            <Section title="Leere Zustände" description="Linien-Illustrationen für jede Situation">
              <div className="grid grid-cols-2 gap-3 @[56rem]:grid-cols-4">
                {ILLUSTRATIONS.map((name) => (
                  <div key={name} className="rounded-card border border-line bg-surface-2/30">
                    <EmptyState size="sm" illustration={name} title={name} description="Kurzer Hinweis mit nächster Aktion." />
                  </div>
                ))}
                <div className="rounded-card border border-line bg-surface-2/30 p-4">
                  <div className="micro-label mb-3">Skeleton</div>
                  <Skeleton className="mb-3 h-8 w-24" />
                  <SkeletonText lines={4} />
                </div>
              </div>
            </Section>

            {/* Werte-Demo (Bestellnummern, Footprint-Namen) nicht in ein Drittel zwängen: bei 1120 px zwei Spalten */}
            <div className="grid grid-cols-1 gap-5 @[48rem]:grid-cols-2 @[76rem]:grid-cols-3">
              <Section title="Overlays">
                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" onClick={() => setDialogOpen(true)}>
                    Dialog
                  </Button>
                  <Button onClick={() => setDrawerOpen(true)}>Drawer</Button>
                  <Button onClick={() => setPanelOpen((o) => !o)} aria-pressed={panelOpen}>
                    Detailpanel (nicht modal)
                  </Button>
                  <Button
                    variant="danger"
                    onClick={async () => {
                      const ok = await confirm({
                        title: '3 Bauteile löschen?',
                        description: 'Die Bauteile werden aus der Datenbank entfernt. Ein Backup bleibt erhalten.',
                        confirmLabel: 'Löschen',
                        destructive: true,
                      })
                      if (ok) toast.success('3 Bauteile gelöscht')
                    }}
                  >
                    Bestätigung
                  </Button>
                  <Popover>
                    <PopoverTrigger asChild>
                      <Button variant="outline">Popover</Button>
                    </PopoverTrigger>
                    <PopoverContent>
                      <div className="text-ui font-medium text-fg">Schnellfilter</div>
                      <p className="mt-1 text-xs text-fg-muted">Popover für kleine Formulare und Details.</p>
                      <Input className="mt-3" size="sm" placeholder="Filter …" />
                    </PopoverContent>
                  </Popover>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="ghost" rightIcon={<MoreHorizontal />}>
                        Menü
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      <DropdownMenuLabel>Bauteil</DropdownMenuLabel>
                      <DropdownMenuItem icon={<Pencil />} hotkey="f2">
                        Bearbeiten
                      </DropdownMenuItem>
                      <DropdownMenuItem icon={<Copy />} hotkey="mod+d">
                        Duplizieren
                      </DropdownMenuItem>
                      <DropdownMenuCheckboxItem checked={showGrid} onCheckedChange={setShowGrid}>
                        Raster anzeigen
                      </DropdownMenuCheckboxItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem icon={<Trash2 />} destructive hotkey="delete">
                        Löschen
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                  <Tooltip content="Tooltip mit Tastenkürzel" hotkey="mod+k">
                    <Button variant="ghost">Tooltip</Button>
                  </Tooltip>
                </div>
                <ContextMenu>
                  <ContextMenuTrigger asChild>
                    <div className="mt-4 flex h-20 items-center justify-center rounded-card border border-dashed border-line-strong text-xs text-fg-subtle">
                      Rechtsklick für Kontextmenü
                    </div>
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem icon={<Pencil />}>Bearbeiten</ContextMenuItem>
                    <ContextMenuItem icon={<Copy />} hotkey="mod+c">
                      Kopieren
                    </ContextMenuItem>
                    <ContextMenuSeparator />
                    <ContextMenuItem icon={<Trash2 />} destructive>
                      Löschen
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              </Section>

              <Section title="Toasts">
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => toast.success('Serie angelegt', { description: '1.156 Bauteile in 4 Bauformen' })}>
                    Erfolg
                  </Button>
                  <Button size="sm" onClick={() => toast.error('Import fehlgeschlagen', { description: 'Seite 7 ist nicht lesbar.' })}>
                    Fehler
                  </Button>
                  <Button size="sm" onClick={() => toast.warning('DbLib veraltet', { description: 'Bitte neu erzeugen.' })}>
                    Warnung
                  </Button>
                  <Button size="sm" onClick={() => toast.info('Tipp', { description: 'Mit Strg+K finden Sie jede Aktion.' })}>
                    Info
                  </Button>
                  <Button
                    size="sm"
                    onClick={() =>
                      toast.promise(new Promise((r) => setTimeout(r, 1800)), {
                        loading: 'Footprints werden erzeugt …',
                        success: '12 Footprints erzeugt',
                        error: 'Fehler',
                      })
                    }
                  >
                    Promise
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => toast('Bauteil gelöscht', { action: { label: 'Rückgängig', onClick: () => toast.success('Wiederhergestellt') } })}
                  >
                    Mit Aktion
                  </Button>
                </div>
              </Section>

              <Section title="Werte und Werkzeugleiste">
                <KeyValueList
                  items={[
                    { label: 'MPN', value: 'RC0603FR-0710KL', mono: true, copy: 'RC0603FR-0710KL' },
                    { label: 'Hersteller', value: 'Yageo' },
                    { label: 'Wert', value: '10 kΩ', mono: true, hint: '± 1 %' },
                    { label: 'Footprint', value: 'RESC1608X55N', mono: true },
                    { label: 'Datenblatt', value: null },
                  ]}
                />
                <Toolbar className="mt-4" aria-label="Formatierung">
                  <ToolbarButton asChild>
                    <IconButton label="Fett" icon={<Bold />} size="sm" />
                  </ToolbarButton>
                  <ToolbarButton asChild>
                    <IconButton label="Kursiv" icon={<Italic />} size="sm" />
                  </ToolbarButton>
                  <ToolbarButton asChild>
                    <IconButton label="Unterstrichen" icon={<Underline />} size="sm" />
                  </ToolbarButton>
                  <ToolbarSeparator />
                  <ToolbarSpacer />
                  <ToolbarButton asChild>
                    <Button size="sm" variant="primary" leftIcon={<FileUp />}>
                      Import
                    </Button>
                  </ToolbarButton>
                </Toolbar>
              </Section>
            </div>

            <div className="grid grid-cols-1 gap-5 @[40rem]:grid-cols-2 @[64rem]:grid-cols-3">
              <Card variant="interactive" padding="md">
                <div className="text-ui font-medium">Interaktiv</div>
                <p className="mt-1 text-xs text-fg-muted">Hover: 1 px Lift und stärkere Kante.</p>
              </Card>
              <Card variant="spark" padding="md">
                <div className="text-ui font-medium text-gradient-spark">KI-Ergebnis</div>
                <p className="mt-1 text-xs text-fg-muted">Statischer Funken-Rahmen für KI-Inhalte.</p>
              </Card>
              <Card variant="highlight" padding="md">
                <div className="text-ui font-medium">Hervorgehoben</div>
                <p className="mt-1 text-xs text-fg-muted">Kupferlinie am oberen Rand.</p>
              </Card>
              <Card variant="glass" padding="md">
                <div className="text-ui font-medium">Glas</div>
                <p className="mt-1 text-xs text-fg-muted">Für schwebende Panels.</p>
              </Card>
              <Card variant="ghost" padding="md">
                <div className="text-ui font-medium">Ghost</div>
                <p className="mt-1 text-xs text-fg-muted">Ablagefläche / Platzhalter.</p>
              </Card>
              <Card>
                <CardHeader title="Mit Fußzeile" description="Card + CardHeader + CardFooter" />
                <CardContent>
                  <ScrollArea className="h-16 rounded-button border border-line">
                    <div className="p-2 text-xs text-fg-muted">
                      {Array.from({ length: 12 }, (_, i) => (
                        <div key={i}>Zeile {i + 1} im Scrollbereich</div>
                      ))}
                    </div>
                  </ScrollArea>
                </CardContent>
                <CardFooter>
                  <Button size="sm" variant="ghost">
                    Abbrechen
                  </Button>
                  <Button size="sm" variant="primary" className="ml-auto">
                    Übernehmen
                  </Button>
                </CardFooter>
              </Card>
            </div>
          </div>
        </TabsContent>
        <TabsContent value="geteilt" className="pt-5">
          <SharedDemos fullscreen3d={location.hash === '#vorschau-3d'} />
        </TabsContent>
      </Tabs>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent size="md">
          <DialogHeader icon={<Plus />} title="Neues Bauteil" description="Smart-Eingabe: „10k 1% 0603“ eintippen – die Felder werden befüllt." />
          <DialogBody className="flex flex-col gap-4">
            <Field label="Smart-Eingabe">
              <Input mono placeholder="10k 1% 0603" />
            </Field>
            <Field label="Kategorie">
              <Select
                defaultValue="res"
                options={[
                  { value: 'res', label: 'Widerstände' },
                  { value: 'cap', label: 'Kondensatoren' },
                ]}
              />
            </Field>
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              Abbrechen
            </Button>
            <Button variant="primary" onClick={() => setDialogOpen(false)}>
              Anlegen
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Drawer open={drawerOpen} onOpenChange={setDrawerOpen}>
        <DrawerContent size="md">
          <DrawerHeader title="RC0603FR-0710KL" description="Widerstand · Yageo · 0603" icon={<Layers />}>
            <div className="flex gap-1.5">
              <Badge variant="success" dot>
                synchron
              </Badge>
              <Badge variant="accent">E96</Badge>
            </div>
          </DrawerHeader>
          <DrawerBody>
            <KeyValueList
              items={[
                { label: 'Wert', value: '10 kΩ', mono: true },
                { label: 'Toleranz', value: '1 %', mono: true },
                { label: 'Leistung', value: '0,1 W', mono: true },
                { label: 'Footprint', value: 'RESC1608X55N', mono: true },
              ]}
            />
          </DrawerBody>
          <DrawerFooter>
            <Button variant="ghost" onClick={() => setDrawerOpen(false)}>
              Schließen
            </Button>
            <Button variant="primary">Speichern</Button>
          </DrawerFooter>
        </DrawerContent>
      </Drawer>

      {/* Nicht modal: Seite bleibt bedienbar, Klicks daneben schließen nicht, Kürzel bleiben aktiv */}
      <Drawer open={panelOpen} onOpenChange={setPanelOpen} modal={false}>
        <DrawerContent size="sm">
          <DrawerHeader title="Detailpanel" description="Nicht modal – z. B. neben der Bauteiltabelle" icon={<Layers />} />
          <DrawerBody>
            <p className="text-ui text-fg-muted">
              Klicks in die Seite schließen dieses Panel nicht. Schließen mit ✕, Esc (Fokus im Panel) oder dem Auslöser.
            </p>
          </DrawerBody>
        </DrawerContent>
      </Drawer>
    </PageBody>
  )
}
