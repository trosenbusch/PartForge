import assert from 'node:assert/strict'
import { after, before, beforeEach, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

let server
let i18n
let fields

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
  fields = await server.ssrLoadModule('/src/pages/bauteile/model/fields.ts')
})

after(async () => { await server?.close() })
beforeEach(() => i18n.setLanguage('en'))

const field = (column, label, kind) => ({ column, label, kind, options: [], common: true })

test('parts start in English and interpolation preserves user text', () => {
  assert.equal(i18n.getLanguage(), 'en')
  assert.equal(i18n.t('Neues Bauteil'), 'New part')
  assert.equal(i18n.t('„{1}“ angelegt', { 1: 'Widerstände {untouched}' }), '“Widerstände {untouched}” created')
})

test('field groups, kinds and filter operators update after switching languages', () => {
  assert.equal(fields.FIELD_GROUPS[0].label, 'General')
  assert.equal(fields.KIND_LABEL.quantity, 'Measurement')
  assert.equal(fields.KIND_LABEL.range, 'Range')
  assert.equal(fields.opLabel('contains'), 'contains')
  i18n.setLanguage('de')
  assert.equal(fields.FIELD_GROUPS[0].label, 'Allgemein')
  assert.equal(fields.KIND_LABEL.quantity, 'Messwert')
  assert.equal(fields.opLabel('contains'), 'enthält')
  i18n.setLanguage('en')
  assert.equal(fields.FIELD_GROUPS[0].label, 'General')
})

test('date filters accept English, German and ISO input without changing the API date', () => {
  const now = new Date(2026, 9, 10, 12)
  for (const input of ['today', 'heute', '2026-10-10', '10.10.2026']) {
    assert.equal(fields.parseDateInput(input, now), '2026-10-10')
  }
  for (const input of ['yesterday', 'gestern']) assert.equal(fields.parseDateInput(input, now), '2026-10-09')
  assert.equal(fields.parseDateInput('2026-02-30', now), null)
  assert.equal(fields.parseDateInput('31.02.2026', now), null)
  const dateField = field('PF Modified', 'Geändert', 'date')
  assert.deepEqual(fields.toPartFilters([{ id: 'd', column: 'PF Modified', op: 'eq', value: '09.10.2026' }], [dateField]), [
    { column: 'PF Modified', op: 'eq', value: '2026-10-09' },
  ])
})

test('dates and date-input examples follow the selected language', () => {
  assert.equal(fields.formatDateInput('2026-10-09'), '2026-10-09')
  assert.equal(fields.formatDateText('2026-10-09'), '10/09/2026')
  assert.equal(fields.placeholderFor(field('PF Modified', 'Geändert', 'date')), 'YYYY-MM-DD')
  i18n.setLanguage('de')
  assert.equal(fields.formatDateInput('2026-10-09'), '09.10.2026')
  assert.equal(fields.formatDateText('2026-10-09'), '09.10.2026')
  assert.equal(fields.placeholderFor(field('PF Modified', 'Geändert', 'date')), 'TT.MM.JJJJ')
})

test('translated boolean and status displays preserve database/filter values', () => {
  const boolField = field('Polarized', 'Gepolt', 'bool')
  const statusField = { ...field('PF Status', 'Freigabe', 'enum'), options: ['Entwurf'] }
  assert.equal(fields.displayValue(boolField, 'Ja'), 'Yes')
  assert.equal(fields.displayValue(statusField, 'Entwurf'), 'Draft')
  assert.equal(fields.displayValue({ ...field('Fuse Type', 'Typ', 'enum'), options: ['Sicherung'] }, 'Sicherung'), 'Fuse')
  assert.equal(i18n.metadataLabel('Widerstand'), 'Resistance')
  assert.equal(i18n.metadataLabel('Raster'), 'Pitch')
  assert.deepEqual(fields.toPartFilters([
    { id: 'b', column: 'Polarized', op: 'in', values: ['Ja'] },
    { id: 's', column: 'PF Status', op: 'in', values: ['Entwurf'] },
  ], [boolField, statusField]), [
    { column: 'Polarized', op: 'in', value: ['Ja'] },
    { column: 'PF Status', op: 'in', value: ['Entwurf'] },
  ])
  i18n.setLanguage('de')
  assert.equal(fields.displayValue(boolField, 'Ja'), 'Ja')
  assert.equal(fields.displayValue(statusField, 'Entwurf'), 'Entwurf')
})

test('free text values are not translated', () => {
  assert.equal(fields.displayValue(field('Description', 'Beschreibung', 'text'), 'Widerstände'), 'Widerstände')
  assert.equal(fields.displayValue(field('Custom', 'Custom field', 'text'), 'Ja'), 'Ja')
  assert.equal(fields.displayValue({ ...field('Supplier 1', 'Lieferant 1', 'enum'), options: ['Mouser'] }, 'Wert'), 'Wert')
})
