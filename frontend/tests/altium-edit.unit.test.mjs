/**
 * Unit-Tests „In Altium bearbeiten“ – ohne Browser, Module über Vites SSR-Loader: wann der Knopf gesperrt ist,
 * die vorherige Herkunft einer Altium-Fassung, dass jeder Oberflächentext eine englische Fassung hat und dass die
 * Meldungen der Jobs (Backend) englisch erscheinen, ohne die Bauteilnamen anzutasten.
 *
 *   npm test            (= node --test tests/)
 */
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { after, afterEach, before, describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
let server
let i18n
let rules
let api

before(async () => {
  server = await createServer({
    root,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  i18n = await server.ssrLoadModule('/src/lib/i18n.ts')
  rules = await server.ssrLoadModule('/src/pages/_shared/altiumEditRules.ts')
  api = await server.ssrLoadModule('/src/api/altiumEdit.ts')
})

afterEach(() => i18n.setLanguage('en'))
after(async () => { await server?.close() })

describe('In Altium bearbeiten', () => {
  test('the button says why it cannot edit', () => {
    i18n.setLanguage('de')
    const rec = { name: 'RESC1608X50N', source: 'generated', status: 'ok' }
    assert.equal(rules.altiumEditBlocker(rec, true), null)
    assert.equal(rules.altiumEditBlocker(null, true), null)
    assert.match(rules.altiumEditBlocker({ ...rec, source: 'external' }, true), /externen Bibliothek/)
    assert.match(rules.altiumEditBlocker({ ...rec, status: 'pending' }, true), /Synchronisieren/)
    assert.match(rules.altiumEditBlocker(rec, false), /nicht gefunden/)
    i18n.setLanguage('en')
    assert.match(rules.altiumEditBlocker({ ...rec, status: 'pending' }, true), /synchronizing/)
  })

  test('the previous source of an Altium version comes from the generator data', () => {
    assert.equal(api.altiumPreviousSource({ family: 'chip', altium_edit: { previous_source: 'generated' } }), 'generated')
    assert.equal(api.altiumPreviousSource({ family: 'chip' }), null)
    assert.equal(api.altiumPreviousSource(null), null)
  })

  test('every text of the feature has an English wording', () => {
    const files = ['src/pages/_shared/AltiumEdit.tsx', 'src/pages/_shared/altiumEditRules.ts', 'src/api/altiumEdit.ts']
    const missing = []
    for (const file of files) {
      const text = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8')
      for (const match of text.matchAll(/\btr\(\s*(['"])((?:(?!\1)[^\\]|\\.)*)\1/g)) {
        const source = match[2].replace(/\\(.)/g, '$1')
        if (!Object.hasOwn(i18n.englishMessages, source)) missing.push(`${file}: ${source}`)
      }
    }
    assert.deepEqual(missing, [])
  })

  test('job messages of the backend appear in English, names stay as they are', () => {
    i18n.setLanguage('en')
    assert.equal(i18n.localizeMessage('Aus Altium übernommen: RESC1608X50N, Ä-Teil (2).'),
      'Taken over from Altium: RESC1608X50N, Ä-Teil (2).')
    assert.equal(i18n.localizeMessage('Aus Altium übernommen: A, B, C, D und 3 weitere.'),
      'Taken over from Altium: A, B, C, D and 3 more.')
    assert.equal(i18n.localizeMessage('„MY_CHIP“ ist in Altium geöffnet – nach dem Speichern dort übernimmt PartForge die Änderungen automatisch.'),
      '“MY_CHIP” is open in Altium – after you save there, PartForge takes over the changes automatically.')
    // a job message of several lines: no template may swallow the lines after its own (its placeholder matches \n)
    const twoLines = 'Aus Altium übernommen: MY_CHIP.\n„RESC1608X50N“ wurde in Altium vermutlich in „MY_CHIP“ umbenannt – Bauteile verweisen weiter auf „RESC1608X50N“.'
    assert.equal(i18n.localizeMessage(twoLines),
      'Taken over from Altium: MY_CHIP.\n“RESC1608X50N” was probably renamed to “MY_CHIP” in Altium – parts still refer to “RESC1608X50N”.')
    assert.equal(i18n.localizeMessage('Änderungen aus Altium übernehmen: PF_CHIP.PcbLib'), 'Take over changes from Altium: PF_CHIP.PcbLib')
    i18n.setLanguage('de')
    assert.equal(i18n.localizeMessage('Aus Altium übernommen: X.'), 'Aus Altium übernommen: X.')
  })
})
