import { useI18n } from '@/lib/i18n'
/**
 * Kategorie-Symbol aus dem Lucide-Namen der Datenbank (`CategoryDef.icon`, z. B. „cpu“, „triangle-right“).
 * Bewusst eine feste Auswahl (statt aller ~1.600 Lucide-Icons im Bundle); Unbekanntes → „box“.
 */
import {
  Activity,
  AudioWaveform,
  Battery,
  Binary,
  Box,
  Boxes,
  Cable,
  CircuitBoard,
  Cog,
  Component,
  Cpu,
  Fan,
  Gauge,
  GitFork,
  GitMerge,
  Layers,
  Lightbulb,
  Magnet,
  MemoryStick,
  Microchip,
  Monitor,
  Package,
  Plug,
  Radio,
  RadioTower,
  Shield,
  Speaker,
  SquareSplitHorizontal,
  SunMedium,
  Thermometer,
  ToggleLeft,
  Triangle,
  TriangleRight,
  WavesHorizontal,
  Wifi,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/cn'

const ICONS: Record<string, LucideIcon> = {
  activity: Activity,
  'audio-waveform': AudioWaveform,
  battery: Battery,
  binary: Binary,
  box: Box,
  boxes: Boxes,
  cable: Cable,
  'circuit-board': CircuitBoard,
  cog: Cog,
  component: Component,
  cpu: Cpu,
  fan: Fan,
  gauge: Gauge,
  'git-fork': GitFork,
  'git-merge': GitMerge,
  layers: Layers,
  lightbulb: Lightbulb,
  magnet: Magnet,
  'memory-stick': MemoryStick,
  microchip: Microchip,
  monitor: Monitor,
  package: Package,
  plug: Plug,
  radio: Radio,
  'radio-tower': RadioTower,
  shield: Shield,
  speaker: Speaker,
  'square-split-horizontal': SquareSplitHorizontal,
  'sun-medium': SunMedium,
  thermometer: Thermometer,
  'toggle-left': ToggleLeft,
  triangle: Triangle,
  'triangle-right': TriangleRight,
  waves: WavesHorizontal,
  'waves-horizontal': WavesHorizontal,
  wifi: Wifi,
  wrench: Wrench,
  zap: Zap,
}

export interface CategoryIconProps {
  /** Lucide-Name aus der Datenbank */
  name?: string | null
  /** Kategoriefarbe (färbt das Symbol) */
  color?: string | null
  className?: string
}

/** Symbol einer Kategorie (dekorativ) */
export function CategoryIcon({ name, color, className }: CategoryIconProps) {
  useI18n()
  const Icon = (name && ICONS[name]) || Box
  return <Icon aria-hidden className={cn('size-4 shrink-0', className)} style={color ? { color } : undefined} />
}
