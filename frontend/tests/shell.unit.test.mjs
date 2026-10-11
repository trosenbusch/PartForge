/**
 * Unit-Tests der Shell-Logik (Job-Rückmeldung, Fehlertexte, Downloads, Bibliotheksbezug, Rückgängig einer
 * Massenänderung) – ohne Browser.
 * Lädt die TypeScript-Module über Vites SSR-Loader (Aliase `@/…`, `import.meta.env` wie im Build).
 *
 *   npm test            (= node --test tests/)
 */
import assert from 'node:assert/strict'
import { after, before, describe, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('..', import.meta.url))
let server
let jobs
let client
let system
let format
let download
let parts
let undo

before(async () => {
  server = await createServer({
    root,
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  const i18n = await server.ssrLoadModule('/src/lib/i18n.ts')
  i18n.setLanguage('de')
  client = await server.ssrLoadModule('/src/api/client.ts')
  system = await server.ssrLoadModule('/src/api/system.ts')
  jobs = await server.ssrLoadModule('/src/api/jobs.ts')
  format = await server.ssrLoadModule('/src/lib/format.ts')
  download = await server.ssrLoadModule('/src/lib/download.ts')
  parts = await server.ssrLoadModule('/src/api/parts.ts')
  undo = await server.ssrLoadModule('/src/pages/bauteile/model/undo.ts')
})

after(async () => {
  await server?.close()
})

/** Job-Schnappschuss mit Standardwerten */
function job(patch = {}) {
  return {
    id: 'j1',
    kind: 'series',
    title: 'Serie Vishay CRCW e3',
    status: 'done',
    progress: 1,
    message: 'Serie erzeugt: 22 neu, 0 aktualisiert, 0 übersprungen, 1 Footprint neu',
    log: [],
    result: null,
    error: null,
    created: 1,
    started: 1,
    finished: 2,
    version: 3,
    ...patch,
  }
}

describe('clipText (F2/F11: Toasts nie mitten im Wort kürzen)', () => {
  test('kurze Texte bleiben', () => {
    assert.equal(jobs.clipText('Alles gut.', 200), 'Alles gut.')
  })
  test('lange Texte enden am Satz- bzw. Wortende', () => {
    const reason =
      'Kein Bibliotheks-Writer verfügbar: Der Rust-Writer (altium-designer-mcp.exe) wurde nicht gefunden und Altium Designer ' +
      'steht nicht zur Verfügung (Altium Designer ist nicht gestartet.). Bitte den Rust-Writer unter Einstellungen » Altium ' +
      'eintragen oder Altium Designer starten. Nicht geschriebene Symbole und Footprints bleiben „ausstehend“.'
    const clipped = jobs.clipText(reason, 200)
    assert.ok(clipped.length <= 200, `zu lang: ${clipped.length}`)
    assert.ok(clipped.endsWith(' …'))
    assert.ok(!/Rust- …$/.test(clipped), clipped)
    // das letzte vollständige Wort vor „…“ steht so auch im Original
    const lastWord = clipped.replace(/ …$/, '').split(/\s+/).pop()
    assert.ok(reason.includes(`${lastWord} `) || reason.includes(`${lastWord}.`), `abgeschnittenes Wort: ${lastWord}`)
  })
  test('„z. B.“ ist kein Satzende', () => {
    const text = `${'Wort '.repeat(30)}z. B. ${'weiter '.repeat(30)}`
    const clipped = jobs.clipText(text, 200)
    assert.ok(!clipped.endsWith('z. …') && !clipped.endsWith('B. …'), clipped)
  })
})

describe('apiUrl (Token nur für Kontexte ohne Header: EventSource, <img>)', () => {
  test('hängt das Token als Query-Parameter an', () => {
    const url = client.apiUrl('/api/datasheets/1/pages/2.png', { dpi: 110 })
    assert.ok(url.startsWith('/api/datasheets/1/pages/2.png?'), url)
    assert.ok(/[?&]token=/.test(url), url)
  })
  test('withToken=false lässt das Token weg (Header-Weg)', () => {
    assert.ok(!/token=/.test(client.apiUrl('/api/x', undefined, false)), 'kein Token erwartet')
  })
  test('Export-Adresse (Längenprüfung) ohne Token, CSV Excel-sicher', () => {
    const previous = client.getToken()
    client.setToken('geheim-123')
    try {
      const url = parts.partsApi.exportUrl('Resistors', { format: 'csv', columns: ['Part Number'] })
      assert.ok(url.startsWith('/api/export/Resistors?'), url)
      assert.ok(!/token=/.test(url) && !url.includes('geheim-123'), url)
      assert.ok(/[?&]excel_safe=true/.test(url), url)
    } finally {
      client.setToken(previous)
    }
  })
})

describe('cleanErrorText (F11: keine Python-Darstellungen in Meldungen)', () => {
  test('[Errno 13] mit verdoppelten Backslashes', () => {
    const raw =
      "Die Bibliothek PF_CHIP.PcbLib konnte vor dem Schreiben nicht gesichert werden: [Errno 13] Permission denied: " +
      "'C:\\\\Projekte\\\\Tools\\\\Lib\\\\Footprints\\\\PF_CHIP.PcbLib'. Der Vorgang wurde zurückgesetzt."
    const clean = client.cleanErrorText(raw)
    assert.ok(!clean.includes('[Errno'), clean)
    assert.ok(!clean.includes('Permission denied'), clean)
    assert.ok(!clean.includes('\\\\'), clean)
    assert.ok(clean.includes('C:\\Projekte\\Tools\\Lib\\Footprints\\PF_CHIP.PcbLib'), clean)
    assert.ok(clean.includes('Zugriff verweigert'), clean)
    assert.ok(clean.endsWith('Der Vorgang wurde zurückgesetzt.'), clean)
  })
  test('[WinError 32] behält den deutschen Windows-Text, Pfad lesbar', () => {
    const raw = "[WinError 32] Der Prozess kann nicht auf die Datei zugreifen: 'C:\\\\x\\\\a.PcbLib'"
    const clean = client.cleanErrorText(raw)
    assert.equal(clean, 'Der Prozess kann nicht auf die Datei zugreifen: „C:\\x\\a.PcbLib“')
  })
  test('Klassenname vorn wird entfernt, Rest bleibt', () => {
    assert.equal(client.cleanErrorText('ValueError: Die Datei fehlt.'), 'Die Datei fehlt.')
    assert.equal(client.cleanErrorText('[Errno 28] No space left on device'), 'Kein Speicherplatz mehr auf dem Datenträger')
  })
})

describe('jobResultProblem / jobOutcome (F1b: nicht geschriebene Bibliothekseinträge)', () => {
  const problem = {
    name: 'RESC6332X70N',
    library: 'PF_CHIP.PcbLib',
    status: 'error',
    message: 'Datei gesperrt',
  }
  test('library_problems → Warnung mit Name, Datei und Grund', () => {
    const text = jobs.jobResultProblem(job({ result: { created: 22, errors: [], library_problems: [problem] } }))
    assert.equal(text, 'Footprint RESC6332X70N wurde nicht in PF_CHIP.PcbLib geschrieben – Datei gesperrt')
  })
  test('Form des Backends: kind, Pfad relativ zur Bibliothek, Anzahl der Bauteile', () => {
    const backend = {
      kind: 'footprint',
      name: 'RESC6332X70N',
      library: 'Footprints\\PF_CHIP.PcbLib',
      status: 'error',
      message: 'Datei gesperrt',
      parts: 22,
    }
    assert.equal(
      jobs.jobResultProblem(job({ result: { library_problems: [backend] } })),
      'Footprint RESC6332X70N wurde nicht in PF_CHIP.PcbLib geschrieben – Datei gesperrt',
    )
    const locked = { ...backend, message: 'PF_CHIP.PcbLib wurde nicht geschrieben – die Bibliothek ist unverändert.' }
    assert.equal(
      jobs.jobResultProblem(job({ result: { library_problems: [locked] } })),
      'Footprint RESC6332X70N: PF_CHIP.PcbLib wurde nicht geschrieben – die Bibliothek ist unverändert.',
      'die Datei nicht doppelt nennen',
    )
    const symbol = { kind: 'symbol', name: 'Resistor', library: null, status: 'pending', message: '' }
    assert.equal(
      jobs.jobResultProblem(job({ result: { library_problems: [symbol] } })),
      'Symbol Resistor wurde nicht in die Bibliotheksdatei geschrieben – noch ausstehend',
    )
  })
  test('mehrere Einträge und Kurzfassung der Jobliste', () => {
    const many = jobs.jobResultProblem(
      job({ result: { library_problems: [problem, { ...problem, name: 'SYM', library: 'PF_Passives.SchLib' }] } }),
    )
    assert.ok(many.startsWith('2 Bibliothekseinträge nicht in die Bibliotheksdateien geschrieben – RESC6332X70N'), many)
    const brief = jobs.jobResultProblem(job({ result: { library_problems_count: 3, result_truncated: true } }))
    assert.equal(brief, '3 Bibliothekseinträge nicht in die Bibliotheksdateien geschrieben')
  })
  test('Ausgang: ausstehend → Behebung „Synchronisieren“, fehlgeschlagen → keine (Ursache beheben, wiederholen)', () => {
    const pending = jobs.jobOutcome(job({ result: { library_problems: [{ ...problem, status: 'pending', message: 'Datei gesperrt' }] } }))
    assert.equal(pending.tone, 'warning')
    // die Aktion reist als Router-State, nie als ?aktion= in der Adresse (sec-spa-crosssite-aktion)
    assert.deepEqual(pending.action, { label: 'Synchronisieren', to: '/altium', state: { aktion: 'sync' } })
    assert.ok(!pending.action.to.includes('?'), pending.action.to)
    const failed = jobs.jobOutcome(job({ result: { library_problems: [problem] } }))
    assert.equal(failed.tone, 'warning')
    assert.equal(failed.action, null)
  })
  test('Serie: Fehlerzahl mit dem Grund aus library_problems', () => {
    const result = {
      created: 0,
      errors: 22,
      error_details: { 'CRCW25124R70FKEG': 'Footprint fehlt' },
      library_problems: [{ kind: 'footprint', name: 'RESC6332X70N', library: 'Footprints\\PF_CHIP.PcbLib', status: 'error', message: 'Datei gesperrt' }],
    }
    assert.equal(
      jobs.jobResultProblem(job({ result })),
      '22 Fehler – Footprint RESC6332X70N wurde nicht in PF_CHIP.PcbLib geschrieben – Datei gesperrt',
    )
    const noProblems = { errors: 2, error_details: { A1: 'Wert ungültig', A2: 'x' } }
    assert.equal(jobs.jobResultProblem(job({ result: noProblems })), '2 Fehler – A1: Wert ungültig')
  })
  test('ohne Writer ausstehend → „Writer einrichten“', () => {
    const pending = { ...problem, status: 'pending', message: 'Kein Bibliotheks-Writer verfügbar' }
    const outcome = jobs.jobOutcome(job({ result: { library_problems: [pending] } }))
    assert.deepEqual(outcome.action, { label: 'Writer einrichten', to: '/einstellungen#altium' })
  })
  test('ohne Probleme: Erfolg', () => {
    const outcome = jobs.jobOutcome(job({ result: { created: 22, errors: [], library_problems: [] } }))
    assert.equal(outcome.tone, 'success')
    assert.equal(outcome.action, null)
  })
})

describe('Bibliotheken schreiben ohne Writer (F2)', () => {
  const reason =
    'Kein Bibliotheks-Writer verfügbar – bitte den Pfad zum Bibliotheks-Writer unter Einstellungen › Allgemein › Altium ' +
    'Designer eintragen oder Altium Designer starten. Grund: Der Bibliotheks-Writer wurde nicht gefunden; Altium Designer ' +
    'ist nicht gestartet. Nicht geschriebene Symbole und Footprints bleiben „ausstehend“ und werden beim nächsten ' +
    'Synchronisieren geschrieben.'
  const skipped = job({
    kind: 'libraries',
    title: 'Bibliotheken schreiben',
    message: 'Bibliotheken nicht geschrieben – kein Bibliotheks-Writer verfügbar; Symbole und Footprints bleiben ausstehend',
    result: { skipped: true, reason },
  })
  test('erkannt, Behebung und voller Text', () => {
    assert.equal(jobs.jobLacksWriter(skipped), true)
    const outcome = jobs.jobOutcome(skipped)
    assert.equal(outcome.tone, 'warning')
    assert.deepEqual(outcome.action, jobs.SETUP_WRITER_ACTION)
    assert.equal(outcome.problem, reason, 'problem = ungekürzter Grund')
    assert.ok(outcome.description.startsWith('Bibliotheken nicht geschrieben – kein Bibliotheks-Writer'), outcome.description)
    assert.ok(!outcome.description.includes(' …'), 'kurze Meldung passt ungekürzt')
  })
  test('geschlossene Bibliothek ist kein Writer-Problem', () => {
    const closed = job({ kind: 'libraries', result: { skipped: true, reason: 'Die Bibliothek C:\\x ist nicht mehr geöffnet.' } })
    assert.equal(jobs.jobLacksWriter(closed), false)
  })
})

describe('Neu laden nach Jobs (perf-health-dashboard)', () => {
  test('Exporte und Datenblattsuche laden nichts neu', () => {
    assert.deepEqual([...jobs.jobRefreshScopes('export')], [])
    assert.deepEqual([...jobs.jobRefreshScopes('datasheet-find')], [])
  })
  test('Altium-Jobs nur das Modul „altium“', () => {
    assert.deepEqual([...jobs.jobRefreshScopes('altium.verify')], ['altium'])
    assert.deepEqual([...jobs.jobRefreshScopes('altium.install')], ['altium'])
  })
  test('schreibende und unbekannte Jobs: alles (inkl. Bibliotheksprüfung)', () => {
    for (const kind of ['series', 'import', 'libraries', 'libraries.sync', 'libraries.save', 'datasheet-commit', 'neu.unbekannt']) {
      assert.equal(jobs.jobRefreshScopes(kind), 'all', kind)
    }
  })
})

describe('Beschädigte Bibliotheksdatei (INT-05: Befund library_unreadable, Behebung aus der Sicherung)', () => {
  const issue = (patch = {}) => ({
    severity: 'error',
    check: 'library_unreadable',
    table: null,
    part_number: null,
    column: null,
    message: 'Footprints\\PF_CHIP.PcbLib ist nicht lesbar – vermutlich beschädigt.',
    fix_hint: '„Aus Sicherung wiederherstellen“ setzt die Datei zurück.',
    kind: 'footprint',
    component: null,
    library: 'Footprints\\PF_CHIP.PcbLib',
    affected_parts: 10,
    part_numbers: [],
    fix_action: 'restore_library_backup',
    ...patch,
  })
  const report = (issues) => ({ issues, summary: {}, counts: { error: issues.length, warning: 0, info: 0 } })
  test('mit lesbarer Sicherung: Ein-Klick-Behebung „restore-backup“, sonst keine', async () => {
    const libraries = await server.ssrLoadModule('/src/api/libraries.ts')
    const withBackup = libraries.mergeHealth(undefined, report([issue()]), null)
    const group = withBackup.groups.find((g) => g.check === 'library_unreadable')
    assert.equal(group.info.fix, 'restore-backup')
    assert.equal(group.info.label, 'Bibliotheksdatei nicht lesbar (beschädigt?)')
    assert.equal(group.items[0].fixAction, libraries.RESTORE_BACKUP_ACTION)
    const without = libraries.mergeHealth(undefined, report([issue({ fix_action: null })]), null)
    assert.equal(without.groups.find((g) => g.check === 'library_unreadable').info.fix, undefined)
  })
  test('Dateiübersicht: beschädigt geht „außerhalb geändert“ vor (wie changed_outside des Backends)', async () => {
    const model = await server.ssrLoadModule('/src/pages/altium/model.ts')
    const file = (patch = {}) => ({
      rel: 'Footprints\\PF_CHIP.PcbLib', path: 'C:\\x\\Footprints\\PF_CHIP.PcbLib', kind: 'pcblib', exists: true,
      components: null, in_sync: false, external_changes: true, missing: [], unregistered: [], pending: 0, errors: 0,
      layers_ok: null, unreadable: true, message: 'nicht lesbar', ...patch,
    })
    const damaged = model.summarizeFiles([file(), file({ rel: 'Symbols\\PF_Passives.SchLib', kind: 'schlib', components: 4,
      external_changes: false, unreadable: false, in_sync: true })])
    assert.equal(damaged.damaged, 1)
    assert.equal(damaged.outside, 0)
    assert.equal(damaged.level, 'error')
    assert.equal(damaged.value, '1 Datei beschädigt')
    // ohne Lesezugriff (kein Writer): wie bisher „nicht lesbar“, kein Schaden
    const noReader = model.summarizeFiles([file({ external_changes: false, unreadable: false })])
    assert.equal(noReader.damaged, 0)
    assert.equal(noReader.value, '1 nicht lesbar')
  })
})

describe('Stille Jobs (F11: automatische Aktualisierung ohne installierte DbLib)', () => {
  test('result.quiet → kein Abschluss-Toast, sonst wie gewohnt', async () => {
    const { toast } = await import('sonner')
    const calls = []
    const saved = { success: toast.success, info: toast.info, warning: toast.warning, error: toast.error }
    for (const tone of Object.keys(saved)) toast[tone] = (...args) => calls.push([tone, ...args])
    try {
      const quiet = job({ id: 'quiet-1', kind: 'altium.refresh', title: 'In Altium aktualisieren', status: 'running' })
      jobs.noteJobSnapshot(quiet)
      jobs.noteJobSnapshot({
        ...quiet,
        status: 'done',
        message: 'Die DbLib „PartForge.DbLib“ ist in Altium nicht installiert – nichts zu aktualisieren.',
        result: { trigger: 'auto', installed: false, quiet: true, result: null },
      })
      assert.deepEqual(calls, [])
      const loud = job({ id: 'quiet-2', kind: 'altium.refresh', title: 'In Altium aktualisieren', status: 'running' })
      jobs.noteJobSnapshot(loud)
      jobs.noteJobSnapshot({ ...loud, status: 'done', message: 'Altium hat die DbLib neu eingelesen.',
        result: { trigger: 'auto', installed: true, quiet: false, result: {} } })
      assert.equal(calls.length, 1)
      assert.equal(calls[0][0], 'success')
    } finally {
      Object.assign(toast, saved)
    }
  })
})

describe('Bibliotheksbezug von Jobs (K2)', () => {
  test('gleicher Ordner trotz Schreibweise', () => {
    assert.equal(system.sameLibraryRoot('C:\\Libs\\A\\', 'c:/libs/a'), true)
    assert.equal(system.sameLibraryRoot('C:\\Libs\\A', 'C:\\Libs\\AB'), false)
  })
  test('Jobs ohne Bibliothek gelten als zugehörig', () => {
    assert.equal(system.isJobOfLibrary({ library: null }, 'C:\\Libs\\A'), true)
    assert.equal(system.isJobOfLibrary({ library: 'C:\\Libs\\A' }, 'C:\\Libs\\B'), false)
    assert.equal(system.isJobOfLibrary({ library: 'C:\\Libs\\A' }, 'c:\\libs\\a'), true)
  })
  test('Abbruch durch Bibliothekswechsel', () => {
    assert.equal(system.isLibrarySwitchCancel({ status: 'cancelled', cancel_reason: 'library_switch' }), true)
    assert.equal(system.isLibrarySwitchCancel({ status: 'cancelled', cancel_reason: null }), false)
  })
})

describe('api.download / Content-Disposition (K16)', () => {
  test('UTF-8-Name vor einfachem Namen', () => {
    const h = 'attachment; filename="Widerstande.xlsx"; filename*=UTF-8\'\'Widerst%C3%A4nde.xlsx'
    assert.equal(client.fileNameFromDisposition(h, 'x'), 'Widerstände.xlsx')
    assert.equal(client.fileNameFromDisposition('attachment; filename="PartForge.DbLib"', 'x'), 'PartForge.DbLib')
    assert.equal(client.fileNameFromDisposition(null, 'Fallback.txt'), 'Fallback.txt')
  })
  test('api.download ist vorhanden', () => {
    assert.equal(typeof client.api.download, 'function')
  })
})

describe('plainNumber (K13: ARIA-Werte ohne Exponent)', () => {
  test('kleine und große Werte', () => {
    assert.equal(format.plainNumber(1e-12), '0.000000000001')
    assert.equal(format.plainNumber(4.7e-12), '0.0000000000047')
    assert.equal(format.plainNumber(1e7), '10000000')
    assert.equal(format.plainNumber(1e21), '1000000000000000000000')
    assert.ok(!/e/i.test(format.plainNumber(Number.MIN_VALUE)))
  })
})

describe('saveFile mit saveTo (perf-export-xlsx: erst der Dialog, dann schreibt das Backend)', () => {
  test('Dialog zuerst, kein Laden des Inhalts, Pfad an saveTo', async () => {
    const calls = []
    globalThis.window = {
      pywebview: {
        api: {
          pick_save_path: async (name, filters) => {
            calls.push(['pick', name, filters])
            return 'C:\\Export\\Widerstände.xlsx'
          },
          save_file: async () => {
            calls.push(['save_file'])
            return null
          },
        },
      },
    }
    try {
      const result = await download.saveFile({
        suggestedName: 'Widerstände',
        type: download.FILE_TYPES.xlsx,
        load: () => {
          calls.push(['load'])
          return 'x'
        },
        saveTo: async (path) => {
          calls.push(['saveTo', path])
        },
      })
      assert.deepEqual(calls.map((c) => c[0]), ['pick', 'saveTo'])
      assert.equal(calls[0][1], 'Widerstände.xlsx')
      assert.equal(calls[1][1], 'C:\\Export\\Widerstände.xlsx')
      assert.deepEqual(result, { status: 'saved', name: 'Widerstände.xlsx', path: 'C:\\Export\\Widerstände.xlsx', via: 'desktop' })
    } finally {
      delete globalThis.window
    }
  })
  test('Abbruch im Dialog: nichts geschrieben', async () => {
    let wrote = false
    globalThis.window = { pywebview: { api: { pick_save_path: async () => null } } }
    try {
      const result = await download.saveFile({ suggestedName: 'a.xlsx', saveTo: () => (wrote = true), content: 'x' })
      assert.deepEqual(result, { status: 'cancelled' })
      assert.equal(wrote, false)
    } finally {
      delete globalThis.window
    }
  })
})

describe('restoreUpdatesOutcome (Rückgängig einer Massenänderung bzw. von „Texte neu erzeugen“)', () => {
  const result = (patch = {}) => ({ restored: [], conflicts: {}, unchanged: [], not_found: [], warnings: [], ...patch })
  const CHANGED = 'Seit der Änderung erneut geändert (Toleranz) – nicht zurückgesetzt.'

  test('alle zurückgesetzt', () => {
    assert.deepEqual(undo.restoreUpdatesOutcome(result({ restored: ['R1', 'R2', 'R3'] }), 3), {
      tone: 'success', title: '3 Bauteile zurückgesetzt', description: undefined,
    })
    assert.equal(undo.restoreUpdatesOutcome(result({ restored: ['RC0603FR-0710KL'] }), 1).title, '„RC0603FR-0710KL“ zurückgesetzt')
  })

  test('seither geänderte Bauteile: übersprungen mit Teilenummer und Grund', () => {
    const partial = undo.restoreUpdatesOutcome(result({ restored: ['R1', 'R2'], conflicts: { R3: CHANGED } }), 3)
    assert.equal(partial.tone, 'warning')
    assert.equal(partial.title, '2 von 3 Bauteilen zurückgesetzt')
    assert.equal(partial.description, '1 Bauteil übersprungen – R3: Seit der Änderung erneut geändert (Toleranz)')
    const none = undo.restoreUpdatesOutcome(
      result({ conflicts: { R1: CHANGED, R2: CHANGED, R3: 'Das Bauteil gibt es nicht mehr (gelöscht oder umbenannt) – nicht zurückgesetzt.', R4: CHANGED } }),
      4,
    )
    assert.equal(none.tone, 'warning')
    assert.equal(none.title, 'Nichts zurückgesetzt')
    assert.match(none.description, /^4 Bauteile übersprungen – R1: Seit der Änderung erneut geändert \(Toleranz\) · R2: .+ … und 2 weitere$/)
  })

  test('schon zurück bzw. nicht mehr in der Änderungshistorie', () => {
    assert.equal(undo.restoreUpdatesOutcome(result({ unchanged: ['R1'] }), 1).tone, 'info')
    const gone = undo.restoreUpdatesOutcome(result({ not_found: [7, 8] }), 2)
    assert.equal(gone.tone, 'warning')
    assert.equal(gone.description, '2 Änderungen sind nicht mehr in der Änderungshistorie')
  })
})
