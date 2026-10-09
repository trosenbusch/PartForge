/**
 * Unit-Tests der Altium-Seite (Runde „polish“) – ohne Browser, Module über Vites SSR-Loader:
 * Hinweis nach „Aus Altium deinstallieren“ (E2EREG-2), Parameterliste der Prüfung in Altium (E2EREG-3), der
 * Wortlaut „nicht installiert“ und die Altium-Zeile der Erfolgsansichten (Serie, Datenblatt-Import).
 *
 *   npm test            (= node --test tests/)
 */
import assert from 'node:assert/strict'
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { after, before, describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
let server
let jobs
let model
let navigation

before(async () => {
  server = await createServer({
    root,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  jobs = await server.ssrLoadModule('/src/api/jobs.ts')
  model = await server.ssrLoadModule('/src/pages/altium/model.ts')
  navigation = await server.ssrLoadModule('/src/app/navigation.ts')
})

after(async () => {
  await server?.close()
})

const HINT = 'Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen (sonst Altium neu starten).'
const MESSAGE = `Die DbLib wurde in Altium deinstalliert. ${HINT}`

function uninstallJob(result, message = MESSAGE) {
  return {
    id: 'u1', kind: 'altium.uninstall', title: 'DbLib in Altium deinstallieren', status: 'done', progress: 1, message,
    log: [], result, error: null, created: 1, started: 1, finished: 2, version: 9,
  }
}

const held = {
  message: MESSAGE,
  database_released: false,
  database_holders: [{ pid: 81348, name: 'Altium Designer' }],
  database_hint: HINT,
  outcome: 'partial',
}

describe('uninstallWarning (E2EREG-2: Hinweis statt grünem, gekürztem Erfolg)', () => {
  test('hält Altium die Datenbank, ist der volle Text der Hinweis', () => {
    assert.equal(model.uninstallWarning(uninstallJob(held)), MESSAGE)
  })

  test('freigegeben oder nicht feststellbar: kein Hinweis', () => {
    const msg = 'Die DbLib wurde in Altium deinstalliert.'
    assert.equal(model.uninstallWarning(uninstallJob({ message: msg, database_released: true, database_holders: [] }, msg)), null)
    assert.equal(model.uninstallWarning(uninstallJob({ message: msg, database_released: null }, msg)), null)
    assert.equal(model.uninstallWarning(uninstallJob({ message: 'Die DbLib war in Altium nicht installiert – nichts zu tun.' })), null)
    assert.equal(model.uninstallWarning(uninstallJob(null)), null)
  })

  test('fehlt der Hinweis im Text, kommt er aus dem Ergebnis bzw. aus database_holders', () => {
    const msg = 'Die DbLib wurde in Altium deinstalliert.'
    assert.equal(model.uninstallWarning(uninstallJob({ ...held, message: msg }, msg)), `${msg} ${HINT}`)
    const older = { message: msg, database_released: false, database_holders: [{ pid: 7, name: 'DB Browser for SQLite' }] }
    assert.equal(
      model.uninstallWarning(uninstallJob(older, msg)),
      `${msg} Ordner erst danach verschiebbar – DB Browser for SQLite hält die Datenbank noch offen.`,
    )
  })

  test('Toast und Dock: gelb, voller Text ungekürzt (≤ 200 Zeichen)', () => {
    const job = uninstallJob(held)
    const outcome = jobs.jobOutcome(job, { warnWhen: (j) => model.uninstallWarning(j) })
    assert.equal(outcome.tone, 'warning')
    assert.equal(outcome.description, MESSAGE)
    assert.equal(outcome.problem, MESSAGE)
    assert.ok(MESSAGE.length <= 200 && !outcome.description.endsWith('…'))
    // ohne die Option (z. B. nach dem Neuladen, anderes Fenster): `outcome: 'partial'` des Backends reicht
    const generic = jobs.jobOutcome(job, {})
    assert.equal(generic.tone, 'warning')
    assert.equal(generic.problem, MESSAGE)
  })
})

describe('parameterRows (E2EREG-3: Parameterliste der Prüfung in Altium)', () => {
  const part = {
    parameters: { 'Part Number': 'LM358DR', Comment: 'LM358DR', GBW: '700kHz', Notes: 'intern', 'Rail-to-Rail': '' },
    parameter_diffs: [
      { parameter: 'Slew Rate', database: '0.3V/µs', altium: null },
      { parameter: 'GBW', database: '1MHz', altium: '700kHz' },
      { parameter: 'Description', database: 'IC OPAMP 2CH 700kHz 0.3V/µs SOIC-8', altium: 'IC OPAMP 2CH 700kHz SOIC-8' },
    ],
    extra_parameters: ['Notes'],
    parameters_checked: 25,
    visible_parameters: ['Comment'],
  }

  test('Altiums Reihenfolge, Zustand je Parameter, fehlende am Ende, ohne Beschreibung', () => {
    const rows = model.parameterRows(part)
    assert.deepEqual(
      rows.map((r) => [r.name, r.state, r.altium, r.database]),
      [
        ['Part Number', 'same', 'LM358DR', null],
        ['Comment', 'same', 'LM358DR', null],
        ['GBW', 'diff', '700kHz', '1MHz'],
        ['Notes', 'extra', 'intern', null],
        ['Rail-to-Rail', 'same', null, null], // leer = nicht geliefert
        ['Slew Rate', 'diff', null, '0.3V/µs'],
      ],
    )
    assert.deepEqual(rows.filter((r) => r.visible).map((r) => r.name), ['Comment'])
  })

  test('ältere Ergebnisse ohne Vergleich: „nicht verglichen“, ohne Parameter leer', () => {
    assert.deepEqual(model.parameterRows({ ...part, parameter_diffs: [], extra_parameters: [], parameters_checked: 0 })
      .map((r) => r.state), ['unchecked', 'unchecked', 'unchecked', 'unchecked', 'unchecked'])
    assert.deepEqual(model.parameterRows({ visible_parameters: [] }), [])
  })
})

describe('Schlagzeile nach dem Deinstallieren (Wortlaut)', () => {
  test('„nicht installiert“ statt „noch nicht installiert“, mit Installieren', () => {
    const status = {
      backends: [{ name: 'rust', available: true, message: 'bereit', version: '0.1.0', path: 'x.exe' }],
      altium_running: true,
      altium_exe: 'C:\\Programme\\Altium\\X2.EXE',
      version: '26.10.1.5',
      bridge_wedged: null,
      workspace_open: true,
      dblib: {
        path: 'C:\\Bib\\PartForge.DbLib', file_name: 'PartForge.DbLib', exists: true, up_to_date: true, db_path_ok: true,
        db_kind: 'sqlite', database: 'C:\\Bib\\PartForge.sqlite', dblib_database: 'C:\\Bib\\PartForge.sqlite',
        modified: 1, size: 1, tables: 19, enabled_tables: [], field_maps: 266, installed_in_altium: false,
        install: { path: 'C:\\Bib\\PartForge.DbLib', file_name: 'PartForge.DbLib', installed: false, same_name: [], duplicates: [] },
        issues: [{ code: 'not_installed', severity: 'info', message: 'Die DbLib ist in Altium nicht installiert.' }],
      },
      odbc: { kind: 'sqlite', driver: 'SQLite3 ODBC Driver', installed: true },
      refresh: { auto_refresh: true, pending: false, manual_pending: false, running: false, last_error: null },
    }
    const m = model.buildModel({ status, files: [], backend: 'auto', partCount: 46, reportErrors: 0 })
    assert.equal(m.headline.title, 'Die DbLib ist in Altium nicht installiert')
    assert.equal(m.headline.primary, 'install')
    assert.ok(!/noch nicht/.test(`${m.headline.title} ${m.headline.text}`))
  })
})

describe('Schlagzeile bei ausstehenden Änderungen', () => {
  function status(refresh) {
    return {
      backends: [{ name: 'rust', available: true, message: 'bereit', version: '0.1.0', path: 'x.exe' }],
      altium_running: true,
      altium_exe: 'C:\\Programme\\Altium\\X2.EXE',
      version: '26.10.1.5',
      bridge_wedged: null,
      workspace_open: true,
      dblib: {
        path: 'C:\\Bib\\PartForge.DbLib', file_name: 'PartForge.DbLib', exists: true, up_to_date: true, db_path_ok: true,
        db_kind: 'sqlite', database: 'C:\\Bib\\PartForge.sqlite', dblib_database: 'C:\\Bib\\PartForge.sqlite',
        modified: 1, size: 1, tables: 19, enabled_tables: [], field_maps: 266, installed_in_altium: true,
        install: { path: 'C:\\Bib\\PartForge.DbLib', file_name: 'PartForge.DbLib', installed: true, same_name: [], duplicates: [] },
        issues: [],
      },
      odbc: { kind: 'sqlite', driver: 'SQLite3 ODBC Driver', installed: true },
      refresh: { auto_refresh: true, pending: false, manual_pending: false, running: false, last_error: null, ...refresh },
    }
  }
  const headline = (refresh) => model.buildModel({ status: status(refresh), files: [], backend: 'auto', partCount: 46, reportErrors: 0 }).headline

  test('ohne automatische Aktualisierung wartet nichts: „In Altium aktualisieren“ statt „wird übergeben“', () => {
    const h = headline({ auto_refresh: false, pending: true })
    assert.equal(h.title, 'Altium kennt noch nicht alle Änderungen')
    assert.equal(h.primary, 'refresh')
    assert.ok(!/wartet einen Moment/.test(h.text))
  })

  test('mit automatischer Aktualisierung: Änderungen werden übergeben', () => {
    assert.equal(headline({ pending: true }).title, 'Änderungen werden an Altium übergeben …')
    assert.equal(headline({ auto_refresh: false, manual_pending: true, running: true }).title, 'Änderungen werden an Altium übergeben …')
  })
})

describe('altiumAfterWrite (Erfolgsansichten: was Altium von neuen Bauteilen sieht)', () => {
  const NOT_INSTALLED = 'Die DbLib „Firmenbibliothek.DbLib“ ist in Altium nicht installiert – nichts zu aktualisieren.'

  function status({ running = true, installed = true, refresh = {}, issues = [], wedged = null } = {}) {
    return {
      backends: [],
      altium_running: running,
      altium_exe: 'C:\\Programme\\Altium\\X2.EXE',
      version: '26.10.1.5',
      bridge_wedged: wedged,
      workspace_open: true,
      dblib: { file_name: 'Firmenbibliothek.DbLib', installed_in_altium: installed, issues },
      refresh: {
        auto_refresh: true, pending: false, manual_pending: false, running: false, last_error: null,
        last_skip_reason: null, ...refresh,
      },
    }
  }

  test('DbLib nicht installiert: sagt es und bietet „In Altium installieren“ an – nie „erscheinen gleich“', () => {
    for (const refresh of [{ pending: true }, { running: true }, { last_skip_reason: NOT_INSTALLED }]) {
      const n = model.altiumAfterWrite(status({ installed: false, refresh }))
      assert.equal(n.tone, 'warn')
      assert.match(n.text, /^Die DbLib „Firmenbibliothek\.DbLib“ ist in Altium nicht installiert/)
      assert.deepEqual(n.next, { action: 'install', label: 'In Altium installieren' })
    }
  })

  test('installiert: Aktualisierung läuft bzw. folgt → „erscheinen gleich“, danach automatisch', () => {
    const busy = model.altiumAfterWrite(status({ refresh: { pending: true } }))
    assert.equal(busy.tone, 'busy')
    assert.equal(busy.text, 'Altium Designer wird aktualisiert – die neuen Bauteile erscheinen gleich im Bauteilbrowser.')
    const done = model.altiumAfterWrite(status())
    assert.equal(done.tone, 'ok')
    assert.equal(done.text, 'Altium Designer läuft – PartForge aktualisiert die Bibliothek dort automatisch.')
    assert.equal(done.next, undefined)
  })

  test('übersprungen bzw. automatisch aus: „In Altium aktualisieren“ statt „wird aktualisiert“', () => {
    const off = 'Die automatische Aktualisierung in Altium ist ausgeschaltet (Einstellungen › Allgemein › Altium Designer).'
    for (const refresh of [
      { auto_refresh: false, pending: true, last_skip_reason: off },
      { auto_refresh: false, pending: true },
      { pending: true, last_skip_reason: 'Prüfung fehlgeschlagen: Zeitüberschreitung' },
    ]) {
      const n = model.altiumAfterWrite(status({ refresh }))
      assert.equal(n.tone, 'manual', JSON.stringify(refresh))
      assert.deepEqual(n.next, { action: 'refresh', label: 'In Altium aktualisieren' })
    }
    const failed = model.altiumAfterWrite(status({ refresh: { last_error: 'Altium antwortet nicht.' } }))
    assert.equal(failed.tone, 'warn')
    assert.equal(failed.next.action, 'refresh')
  })

  test('Installation ungeprüft: die Aktualisierung prüft sie, sonst von Hand aktualisieren', () => {
    assert.match(model.altiumAfterWrite(status({ installed: null, refresh: { running: true } })).text, /prüft dabei, ob die DbLib/)
    assert.equal(model.altiumAfterWrite(status({ installed: null })).tone, 'manual')
  })

  test('Altium läuft nicht, Skript hängt, gleichnamige DbLib', () => {
    const stopped = model.altiumAfterWrite(status({ running: false, installed: false }))
    assert.equal(stopped.tone, 'off')
    assert.match(stopped.text, /Laut letzter Prüfung ist die DbLib „Firmenbibliothek\.DbLib“ dort nicht installiert/)
    assert.equal(stopped.next, undefined) // Installieren braucht ein laufendes Altium
    assert.equal(
      model.altiumAfterWrite(status({ running: false, installed: null })).text,
      'Altium Designer läuft nicht – beim nächsten Start sind die Bauteile in der DbLib.',
    )
    const wedged = model.altiumAfterWrite(status({ wedged: { last_step: 'refresh' } }))
    assert.equal(wedged.tone, 'error')
    assert.equal(wedged.next.action, 'refresh')
    const issues = [{ code: 'duplicates', severity: 'error', message: 'Diese DbLib ist in Altium nicht installiert, aber …' }]
    const dup = model.altiumAfterWrite(status({ installed: false, issues }))
    assert.equal(dup.tone, 'warn')
    assert.deepEqual(dup.next, { action: 'page', label: 'Zur Altium-Seite' })
    assert.equal(model.altiumAfterWrite(undefined), null)
  })
})

/** Quelldateien des Frontends (ohne generierte Typen) */
function sourceFiles(dir = join(root, 'src')) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? sourceFiles(join(dir, e.name)) : /\.tsx?$/.test(e.name) && !e.name.endsWith('.d.ts') ? [join(dir, e.name)] : [],
  )
}

describe('Aktionen der Altium-Seite nur als Router-State (sec-spa-crosssite-aktion)', () => {
  test('altiumActionState und altiumActionFromState: jede Aktion übersteht den Rundweg', () => {
    for (const aktion of navigation.ALTIUM_ACTIONS) {
      assert.deepEqual(navigation.altiumActionState(aktion), { aktion })
      assert.equal(navigation.altiumActionFromState(navigation.altiumActionState(aktion)), aktion)
    }
    assert.deepEqual(
      [...navigation.ALTIUM_ACTIONS].sort(),
      ['aktualisieren', 'dblib', 'installieren', 'odbc', 'pruefen', 'sync', 'vorschau'],
    )
  })

  test('unbekannte oder fehlende Werte lösen nichts aus', () => {
    for (const state of [null, undefined, 'sync', 42, {}, { aktion: 'loeschen' }, { aktion: 1 }, { aktion: ['sync'] }]) {
      assert.equal(navigation.altiumActionFromState(state), null, JSON.stringify(state))
    }
  })

  test('appNavigate gibt den Router-State an den Router weiter (Job-Toast „Synchronisieren“)', () => {
    const calls = []
    navigation.setAppNavigate((to, options) => calls.push({ to, options }))
    try {
      const fix = jobs.SYNC_LIBRARIES_ACTION
      navigation.appNavigate(fix.to, { state: fix.state })
      assert.deepEqual(calls, [{ to: '/altium', options: { state: { aktion: 'sync' } } }])
    } finally {
      navigation.setAppNavigate(null)
    }
  })

  test('keine Stelle baut mehr eine Adresse mit ?aktion=, die Altium-Seite liest die Aktion nicht aus der Adresse', () => {
    const offenders = []
    for (const file of sourceFiles()) {
      readFileSync(file, 'utf8')
        .split(/\r?\n/)
        .forEach((line, i) => {
          const code = line.trim()
          if (code.startsWith('*') || code.startsWith('//') || code.startsWith('/*')) return // Kommentare
          if (/aktion=/.test(code)) offenders.push(`${file.slice(root.length)}:${i + 1}: ${code}`)
        })
    }
    assert.deepEqual(offenders, [])
    const page = readFileSync(join(root, 'src', 'pages', 'altium', 'AltiumPage.tsx'), 'utf8')
    assert.ok(!/get\(\s*['"]aktion['"]\s*\)/.test(page), 'AltiumPage liest ?aktion= aus der Adresse')
    assert.match(page, /altiumActionFromState\(location\.state\)/)
  })
})
