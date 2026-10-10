import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

let server
let i18n
let params
let families
let pins
let symbols
let geometryI18n
let geometry

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    configFile: false,
    resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  i18n = await server.ssrLoadModule('/src/lib/i18n.ts')
  geometryI18n = await server.ssrLoadModule('/src/components/preview/i18n.ts')
  geometry = await server.ssrLoadModule('/src/lib/geometry.ts')
  params = await server.ssrLoadModule('/src/pages/footprints/lib/params.ts')
  families = await server.ssrLoadModule('/src/pages/footprints/lib/families.ts')
  pins = await server.ssrLoadModule('/src/pages/symbole/ic/pins.ts')
  symbols = await server.ssrLoadModule('/src/pages/symbole/store.ts')
})

after(async () => { await server?.close() })
beforeEach(() => i18n.setLanguage('en'))

test('footprint dimensions update locale even when formatter is already cached', () => {
  assert.equal(params.formatDim(0.25), '0.25')
  i18n.setLanguage('de')
  assert.equal(params.formatDim(0.25), '0,25')
  i18n.setLanguage('en')
  assert.equal(params.formatDim(0.25), '0.25')
  assert.equal(params.parseTolText('0,25').value, 0.25)
  assert.equal(params.parseTolText('0.25').value, 0.25)
})

test('translated package metadata is searchable without changing source values', () => {
  const family = { key: 'chip', label: 'Chip-Bauteile', group: 'Chip-Bauteile', description: 'Widerstand', aliases: [], presets: [] }
  assert.equal(families.familyShortLabel(family), 'Chip components')
  assert.ok(families.familyMatches(family, 'resistor') > 0)
  assert.equal(family.label, 'Chip-Bauteile')
  i18n.setLanguage('de')
  assert.equal(families.familyShortLabel(family), 'Chip-Bauteile')
  assert.ok(families.familyMatches(family, 'Widerstand') > 0)
})

test('symbol library filter tokens remain stable in both languages', () => {
  for (const language of ['en', 'de']) {
    i18n.setLanguage(language)
    symbols.useLibraryFilters.getState().reset()
    const state = symbols.useLibraryFilters.getState()
    assert.equal(state.group, 'alle')
    assert.equal(state.source, 'alle')
    assert.equal(state.status, 'alle')
  }
})

test('pin paste understands German and English independently of UI language', () => {
  for (const language of ['en', 'de']) {
    i18n.setLanguage(language)
    for (const text of ['Nummer\tName\tTyp\tVerborgen\n1\tVCC\tVersorgung\tja', 'Number\tName\tType\tHidden\n1\tVCC\tPower\tyes']) {
      const result = pins.parsePinTable(text)
      assert.equal(result.pins.length, 1)
      assert.equal(result.pins[0].electrical, 'power')
      assert.equal(result.pins[0].hidden, true)
    }
  }
})

test('pin validation switches language and CAD text stays unchanged', () => {
  const pin = pins.makePin('', { name: 'Widerstand', group: 'Versorgung', description: 'Eigene Beschreibung' })
  assert.match(pins.validatePins([pin]).issues[0].message, /pin number missing/)
  i18n.setLanguage('de')
  assert.match(pins.validatePins([pin]).issues[0].message, /Pin-Nummer fehlt/)
  const request = pins.toIcPin(pin)
  assert.equal(request.name, 'Widerstand')
  assert.equal(request.group, 'Versorgung')
  assert.equal(request.description, 'Eigene Beschreibung')
})


test('engineering labels use their domain meanings independently of shared catalogs', () => {
  assert.equal(geometryI18n.t('Sicherung'), 'Fuse')
  assert.equal(geometryI18n.t('Induktivität'), 'Inductor')
  assert.equal(geometryI18n.t('Seiten'), 'Sides')
  assert.equal(geometry.ELECTRICAL_LABEL.power, 'Power')
  assert.equal(geometry.ELECTRICAL_LABEL.io, 'Bidirectional')
  i18n.setLanguage('de')
  assert.equal(geometryI18n.t('Sicherung'), 'Sicherung')
  assert.equal(geometryI18n.t('Induktivität'), 'Induktivität')
  assert.equal(geometryI18n.t('Seiten'), 'Seiten')
  assert.equal(geometry.ELECTRICAL_LABEL.power, 'Versorgung')
  assert.equal(geometry.ELECTRICAL_LABEL.io, 'Ein-/Ausgang')
})
