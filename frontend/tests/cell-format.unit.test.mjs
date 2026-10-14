/** Table cell formatting of technical values follows the UI language (decimal comma only in German). */
import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

let server
let i18n
let cellFormat

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
  cellFormat = await server.ssrLoadModule('/src/components/grid/cellFormat.ts')
})

after(async () => { await server?.close() })

const NNBSP = ' ' // narrow no-break space before the unit

test('quantity text uses the decimal separator of the UI language', () => {
  i18n.setLanguage('de')
  assert.equal(cellFormat.formatQuantityText('0.1W'), `0,1${NNBSP}W`)
  assert.equal(cellFormat.formatQuantityText('4.7kΩ'), `4,7${NNBSP}kΩ`)
  assert.equal(cellFormat.formatQuantityText('-55°C … 155°C'), `−55${NNBSP}°C … 155${NNBSP}°C`)
  i18n.setLanguage('en')
  assert.equal(cellFormat.formatQuantityText('0.1W'), `0.1${NNBSP}W`)
  assert.equal(cellFormat.formatQuantityText('4.7kΩ'), `4.7${NNBSP}kΩ`)
  assert.equal(cellFormat.formatQuantityText('±1%'), `±1${NNBSP}%`)
  assert.equal(cellFormat.formatQuantityText('10kΩ'), `10${NNBSP}kΩ`)
})

test('sorting of non-numeric cells collates in the UI language', () => {
  i18n.setLanguage('en')
  assert.ok(cellFormat.quantityComparator('a', 'b') < 0)
  assert.ok(cellFormat.quantityComparator('', '1k') > 0)
})
