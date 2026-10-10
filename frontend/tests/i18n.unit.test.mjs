/** Locale behavior and message safety, loaded through the same Vite modules as the app. */
import assert from 'node:assert/strict'
import { after, afterEach, before, describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
let server
let i18n
let format

before(async () => {
  server = await createServer({
    root,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  i18n = await server.ssrLoadModule('/src/lib/i18n.ts')
  format = await server.ssrLoadModule('/src/lib/format.ts')
})

afterEach(() => i18n.setLanguage('en'))
after(async () => { await server?.close() })

describe('application language', () => {
  test('starts in English when no preference exists', () => {
    assert.equal(i18n.getLanguage(), 'en')
    assert.equal(i18n.getLocale(), 'en-US')
    assert.equal(i18n.t('Speichern'), 'Save')
    assert.equal(i18n.t('Sprache'), 'Language')
    assert.equal(i18n.t('Einstellungen gespeichert'), 'Settings saved')
  })

  test('German selection and switching back apply to already loaded helpers', () => {
    i18n.setLanguage('de')
    assert.equal(i18n.getLocale(), 'de-DE')
    assert.equal(i18n.t('Speichern'), 'Speichern')
    assert.equal(i18n.t('Einstellungen gespeichert'), 'Einstellungen gespeichert')
    i18n.setLanguage('en')
    assert.equal(i18n.t('Speichern'), 'Save')
  })

  test('unsupported or absent preferences normalize to English', () => {
    for (const value of [undefined, null, '', 'fr', 'EN', 123]) {
      assert.equal(i18n.normalizeLanguage(value), 'en')
    }
    assert.equal(i18n.normalizeLanguage('de'), 'de')
  })

  test('updates the HTML language and persisted browser preference', () => {
    const originalDocument = globalThis.document
    const originalStorage = globalThis.localStorage
    const values = new Map()
    globalThis.document = { documentElement: { lang: 'en' }, cookie: '' }
    globalThis.localStorage = {
      setItem: (key, value) => values.set(key, value),
      getItem: (key) => values.get(key) ?? null,
      removeItem: (key) => values.delete(key),
    }
    try {
      i18n.setLanguage('de')
      assert.equal(document.documentElement.lang, 'de')
      assert.equal(values.get('pf-language'), 'de')
      assert.match(document.cookie, /pf-language=de/)
      i18n.setLanguage('en')
      assert.equal(document.documentElement.lang, 'en')
      assert.equal(values.get('pf-language'), 'en')
    } finally {
      if (originalDocument === undefined) delete globalThis.document
      else globalThis.document = originalDocument
      if (originalStorage === undefined) delete globalThis.localStorage
      else globalThis.localStorage = originalStorage
    }
  })
})

describe('message interpolation', () => {
  test('preserves names, paths and placeholder-like user data verbatim', () => {
    const name = 'Prüfung {0} $& <b>Ω</b> C:\\Teile\\Deutsch'
    assert.equal(i18n.translate('Diese Bereiche gelten für die Bibliothek „{0}“', 'en', { 0: name }),
      `These sections apply to library “${name}”`)
    assert.equal(i18n.translate('Diese Bereiche gelten für die Bibliothek „{0}“', 'de', { 0: name }),
      `Diese Bereiche gelten für die Bibliothek „${name}“`)
  })

  test('leaves unknown strings and literal part-number placeholders intact', () => {
    const unknown = 'ACME Ω / CRCW060310K0 / C:\\Bauteile\\3D'
    assert.equal(i18n.translate(unknown, 'en'), unknown)
    assert.equal(i18n.translate('Ohne {counter} hätten alle Bauteile dieselbe Nummer.', 'en'),
      'Without {counter}, all parts would have the same number.')
    assert.equal(i18n.translate('Ohne {counter} hätten alle Bauteile dieselbe Nummer.', 'de'),
      'Ohne {counter} hätten alle Bauteile dieselbe Nummer.')
  })

  test('translates a backend diagnostic without translating its embedded file name', () => {
    const name = 'Deutsch [Ω] (1).pdf'
    i18n.setLanguage('en')
    assert.equal(i18n.localizeMessage(`Die Datei „${name}“ existiert nicht.`),
      `The file “${name}” does not exist.`)
    i18n.setLanguage('de')
    assert.equal(i18n.localizeMessage(`Die Datei „${name}“ existiert nicht.`),
      `Die Datei „${name}“ existiert nicht.`)
  })

  test('localizes health remedies and the complete default writer-unavailable diagnostic', () => {
    assert.equal(i18n.localizeMessage('Datenblatt-URL eintragen oder ein Datenblatt importieren.'),
      'Enter a datasheet URL or import a datasheet.')
    const diagnostic = 'Kein Bibliotheks-Writer verfügbar – bitte den Pfad zum Bibliotheks-Writer unter Einstellungen › Allgemein › Altium Designer eintragen oder Altium Designer starten. Grund: Der Bibliotheks-Writer wurde nicht gefunden; Altium Designer (X2.EXE) wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › Altium Designer eintragen.'
    assert.equal(i18n.localizeMessage(diagnostic),
      'No library writer available – enter the library writer path under Settings › General › Altium Designer or start Altium Designer. Reason: the library writer was not found; Altium Designer (X2.EXE) was not found – enter its path under Settings › General › Altium Designer.')
    i18n.setLanguage('de')
    assert.equal(i18n.localizeMessage(diagnostic), diagnostic)
  })
})

describe('locale-sensitive formatting', () => {
  test('switches cached decimal, number, byte and date formatters', () => {
    const date = new Date(2026, 9, 10, 14, 35)
    for (const [language, locale, decimal, number, bytes] of [
      ['en', 'en-US', '1,234.5', '1,234.50', '1.5 KB'],
      ['de', 'de-DE', '1.234,5', '1.234,50', '1,5 KB'],
      ['en', 'en-US', '1,234.5', '1,234.50', '1.5 KB'],
    ]) {
      i18n.setLanguage(language)
      assert.equal(format.formatDecimal(1234.5), decimal)
      assert.equal(format.formatNumber(1234.5, 2), number)
      assert.equal(format.formatBytes(1536), bytes)
      assert.equal(format.formatDateTime(date), new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(date))
    }
  })

  test('reads locale-formatted input and preserves machine-format values', () => {
    i18n.setLanguage('en')
    assert.equal(format.parseDecimal('1,234.5'), 1234.5)
    assert.equal(format.plainNumber(1234.5), '1234.5')
    i18n.setLanguage('de')
    assert.equal(format.parseDecimal('1.234,5'), 1234.5)
    assert.equal(format.plainNumber(1234.5), '1234.5')
  })

  test('a single separator is a decimal sign; ambiguous English grouping is rejected, never guessed', () => {
    for (const language of ['en', 'de']) {
      i18n.setLanguage(language)
      for (const [text, value] of [['0,125', 0.125], ['-0,050', -0.05], ['2,54', 2.54], ['1.27', 1.27], ['1,2345', 1.2345],
        ['1.234,5', 1234.5], ['1,234.5', 1234.5], ['1.234.567', 1234567], ['1,234,567', 1234567], ['−0,5', -0.5]]) {
        assert.equal(format.parseDecimal(text), value, `${language}: ${text}`)
      }
      for (const text of ['12.34,5', '1,2,3', '1.234,5.6', '1,23.4']) assert.equal(format.parseDecimal(text), null, `${language}: ${text}`)
    }
    i18n.setLanguage('en')
    assert.equal(format.parseDecimal('1,250'), null)
    assert.equal(format.parseDecimal('12,500'), null)
    i18n.setLanguage('de')
    assert.equal(format.parseDecimal('1,250'), 1.25)
  })

  test('input fields read their own display back unchanged', () => {
    for (const language of ['en', 'de']) {
      i18n.setLanguage(language)
      for (const value of [1250, 1250.5, 0.125, -0.05, 4096, 1234567.25]) {
        assert.equal(format.parseDecimal(format.formatInputNumber(value, 3)), value, `${language}: ${value}`)
      }
    }
    i18n.setLanguage('de')
    assert.equal(format.formatInputNumber(1250.5), '1250,5')
  })

  test('English nouns after a count are lowercase, names and abbreviations keep their spelling', () => {
    assert.equal(format.plural(3, 'Bauteil', 'Bauteile'), '3 parts')
    assert.equal(format.plural(1, 'Fehler', 'Fehler'), '1 error')
    assert.equal(format.plural(2, 'Fehler', 'Fehler'), '2 errors')
    assert.equal(format.plural(1, 'Treffer', 'Treffer'), '1 match')
    assert.equal(format.plural(2, 'PcbLib', 'PcbLibs'), '2 PcbLibs')
    assert.equal(format.plural(2, 'PDF', 'PDFs'), '2 PDFs')
    assert.equal(format.pluralNoun(2, 'Altium-Bibliothek', 'Altium-Bibliotheken').startsWith('Altium'), true)
    i18n.setLanguage('de')
    assert.equal(format.plural(3, 'Bauteil', 'Bauteile'), '3 Bauteile')
    assert.equal(format.plural(1, 'Fehler', 'Fehler'), '1 Fehler')
  })
})

describe('catalog consistency', () => {
  test('general catalogs never give one source two English wordings', async () => {
    const { readdirSync } = await import('node:fs')
    const dir = fileURLToPath(new URL('../src/i18n/catalogs/', import.meta.url))
    const seen = new Map()
    const conflicts = []
    for (const file of readdirSync(dir).filter((name) => name.endsWith('.ts')).sort()) {
      if (i18n.CONTEXT_CATALOGS.has(file.slice(0, -3))) continue
      const catalog = (await server.ssrLoadModule(`/src/i18n/catalogs/${file}`)).default
      for (const [source, english] of Object.entries(catalog)) {
        const earlier = seen.get(source)
        if (earlier && earlier.english !== english) conflicts.push(`${JSON.stringify(source)}: ${earlier.file} ${JSON.stringify(earlier.english)} ≠ ${file} ${JSON.stringify(english)}`)
        else if (!earlier) seen.set(source, { file, english })
      }
    }
    assert.deepEqual(conflicts, [], 'use tc(context, source) for a wording that depends on the use')
  })

  test('domain catalogs keep their terms to their own translators', async () => {
    const preview = await server.ssrLoadModule('/src/components/preview/i18n.ts')
    assert.equal(i18n.t('Herkunft'), 'Source')
    assert.equal(preview.t('Herkunft'), 'Origin')
    assert.equal(i18n.t('Versorgung'), 'Power')
    assert.equal(i18n.metadataLabel('Versorgung'), 'Supply Voltage')
  })

  test('context translations override only where requested', async () => {
    const contexts = (await server.ssrLoadModule('/src/i18n/contexts.ts')).default
    assert.equal(i18n.tc('author', 'von'), 'by')
    assert.equal(i18n.tc('range', 'von'), 'from')
    assert.equal(i18n.t('von'), 'of')
    assert.equal(i18n.tc('author', 'Speichern'), 'Save')
    for (const [context, messages] of Object.entries(contexts)) {
      for (const source of Object.keys(messages)) {
        assert.ok(Object.hasOwn(i18n.englishMessages, source), `${context}: „${source}“ has no default wording`)
      }
    }
    i18n.setLanguage('de')
    assert.equal(i18n.tc('author', 'von'), 'von')
  })
})
