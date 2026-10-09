/** Standardwerte des Hausstils (wie `partforge/workspace.py`) – für „Standard: …“ und Zurücksetzen. */
import type { FootprintStyle, SymbolStyle } from '@/api/system'

export const FOOTPRINT_DEFAULTS: FootprintStyle = {
  density: 'N',
  naming: 'ipc',
  rounding: 'kicad',
  fab_tolerance: 0.1,
  placement_tolerance: 0.05,
  silk_width: 0.2,
  silk_width_small: 0.15,
  silk_pad_clearance: 0.2,
  pin1_dot_radius: 0.125,
  assembly_width: 0.1,
  courtyard_width: 0.05,
  courtyard_grid: 0.05,
  min_copper_gap: 0.15,
  center_cross: true,
  text_height: 1,
  pad_corner_radius_pct: 50,
  exposed_pad_designator: 'next',
  generate_3d: true,
}

export const SYMBOL_DEFAULTS: SymbolStyle = {
  grid: 100,
  ic_pin_length: 200,
  discrete_pin_length: 100,
  ic_line_color: '#800000',
  ic_fill_color: '#FFFFB0',
  discrete_line_color: '#0000FF',
  pin_color: '#000000',
  line_width: 'small',
  font: 'Times New Roman',
  font_size: 10,
  diode_pin1: 'cathode',
  resistor_style: 'iec',
}
