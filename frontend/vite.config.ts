import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig, type Plugin } from 'vite'

// Backend (FastAPI) port used during development; the packaged app serves the
// built frontend itself from partforge/web.
const BACKEND = process.env.PARTFORGE_BACKEND ?? 'http://127.0.0.1:8765'

/**
 * Benannte Vendor-Chunks: schwere Bibliotheken (AG Grid, three.js, Recharts) landen nie im Start-Bundle.
 *
 * Gruppen werden nach Priorität eingesammelt (höher zuerst) und nehmen ihre Abhängigkeiten mit
 * (`includeDependenciesRecursively`). Deshalb zuerst alles, was der Start braucht (React, UI, übrige
 * Start-Abhängigkeiten über das Tag `$initial`) – sonst zieht z. B. die 3D-Gruppe React an sich und die Startseite
 * lädt three.js und AG Grid mit. Danach die schweren, nur lazy geladenen Gruppen, Abhängigkeiten vor ihren
 * Nutzern (ag-stack ← AG-Grid-Kern ← React-Anbindung; three ← React-Three) – so entstehen keine zyklischen Chunks und
 * kein Chunk liegt über der Warnschwelle.
 */
const VENDOR_GROUPS: { name: string; test: RegExp; priority: number; tags?: '$initial'[] }[] = [
  { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/, priority: 50 },
  {
    name: 'vendor-ui',
    test: /node_modules[\\/](radix-ui|@radix-ui|cmdk|sonner|motion|motion-dom|motion-utils|framer-motion|lucide-react|@tanstack|zustand)[\\/]/,
    priority: 49,
  },
  // übrige Bibliotheken des Start-Bundles (clsx, tailwind-merge, Fonts …) – nie in eine Lazy-Gruppe
  { name: 'vendor-base', test: /node_modules[\\/]/, tags: ['$initial'], priority: 48 },
  { name: 'vendor-ag-stack', test: /node_modules[\\/]ag-stack[\\/]/, priority: 33 },
  { name: 'vendor-grid', test: /node_modules[\\/]ag-grid-community[\\/]/, priority: 32 },
  { name: 'vendor-grid-react', test: /node_modules[\\/]ag-grid-react[\\/]/, priority: 31 },
  { name: 'vendor-three', test: /node_modules[\\/]three[\\/]/, priority: 31 },
  {
    name: 'vendor-3d',
    test: /node_modules[\\/](@react-three|three-stdlib|three-mesh-bvh|camera-controls|maath|react-reconciler|its-fine|suspend-react|troika-[a-z-]+|@monogrid|meshline|stats-gl|detect-gpu|hls\.js)[\\/]/,
    priority: 30,
  },
  { name: 'vendor-charts', test: /node_modules[\\/](recharts|d3-[a-z-]+|victory-vendor)[\\/]/, priority: 30 },
]

const GRID_SHIM = fileURLToPath(new URL('./src/components/grid/agGridCommunity.ts', import.meta.url))
const GRID_MODULES = fileURLToPath(new URL('./src/components/grid/modules.ts', import.meta.url))
const normPath = (p: string) => p.split('?')[0].replace(/\\/g, '/').toLowerCase()

/**
 * AG Grid nur mit den genutzten Modulen bündeln: Importe von „ag-grid-community“ aus Quelldateien gehen über
 * `src/components/grid/agGridCommunity.ts` – identisch zum Paket, aber `AllCommunityModule` enthält nur die Module
 * aus `src/components/grid/modules.ts` (fehlt eines, meldet AG Grid im Entwicklungsmodus den Namen).
 * node_modules (ag-grid-react) und die beiden Dateien selbst sehen das Original.
 */
function agGridModules(): Plugin {
  const skip = new Set([normPath(GRID_SHIM), normPath(GRID_MODULES)])
  return {
    name: 'partforge:ag-grid-modules',
    enforce: 'pre',
    resolveId(source, importer) {
      if (source !== 'ag-grid-community' || !importer) return null
      const from = normPath(importer)
      if (from.includes('/node_modules/') || skip.has(from)) return null
      return GRID_SHIM
    },
  }
}

/** Name der Lizenzdatei im Build (neben `index.html`, im Programmpaket unter `partforge\web`) */
export const THIRD_PARTY_LICENSES = 'third-party-licenses.txt'

interface BundledPackage {
  name: string
  version: string
  license: string
  homepage: string | null
  /** Lizenz-, Copying- und Notice-Dateien des Pakets */
  texts: { file: string; text: string }[]
}

const LICENSE_FILE = /^(licen[cs]e|copying|notice|copyright)([-._].*)?$/i

/**
 * Werkzeuge, von denen nur kleine Laufzeithelfer im Build landen (Vite: Preload-Helfer, Modulepreload-Polyfill;
 * Rolldown: Modul-Laufzeit) – ihr eigener Lizenztext, nicht die Lizenzen ihrer (nicht ausgelieferten) Abhängigkeiten.
 */
const RUNTIME_HELPERS = ['vite', 'rolldown']
const BUNDLED_DEPENDENCIES_HEADING = /^#\s*Licenses of bundled dependencies/m

function readPackage(dir: string, runtimeOnly = false): BundledPackage | null {
  try {
    const pkg = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')) as {
      name?: string
      version?: string
      license?: string | { type?: string }
      licenses?: { type?: string }[]
      homepage?: string
      repository?: string | { url?: string }
    }
    const license =
      typeof pkg.license === 'string'
        ? pkg.license
        : (pkg.license?.type ?? pkg.licenses?.map((l) => l.type).filter(Boolean).join(' OR ') ?? 'unbekannt')
    const repo = typeof pkg.repository === 'string' ? pkg.repository : pkg.repository?.url
    const texts = readdirSync(dir)
      .filter((f) => (runtimeOnly ? /^licen[cs]e(\.md|\.txt)?$/i.test(f) : LICENSE_FILE.test(f)))
      .sort()
      .map((file) => {
        let text = readFileSync(join(dir, file), 'utf8').replace(/\r\n/g, '\n')
        if (runtimeOnly) text = text.split(BUNDLED_DEPENDENCIES_HEADING)[0]
        return { file, text: text.trim() }
      })
    return {
      name: pkg.name ?? dir,
      version: pkg.version ?? '',
      license: license || 'unbekannt',
      homepage: pkg.homepage ?? repo?.replace(/^git\+/, '') ?? null,
      texts,
    }
  } catch {
    return null
  }
}

/** Paketordner unter node_modules zu einer Modul-ID (innerstes node_modules, Scopes wie `@radix-ui/x`) */
function packageDir(id: string): string | null {
  const clean = id.split('?')[0].replace(/\\/g, '/')
  if (clean.startsWith('\0')) return null
  const i = clean.lastIndexOf('/node_modules/')
  if (i < 0) return null
  const parts = clean.slice(i + '/node_modules/'.length).split('/')
  const name = parts[0]?.startsWith('@') ? `${parts[0]}/${parts[1]}` : parts[0]
  return name ? `${clean.slice(0, i)}/node_modules/${name}` : null
}

/**
 * Lizenzhinweise aller gebündelten Drittanbieter-Pakete (JavaScript, CSS, Schriften) als `third-party-licenses.txt`
 * neben die Seite schreiben: Name, Version, Lizenz und die Lizenz-/Notice-Texte der Pakete (MIT/BSD/ISC/Apache
 * verlangen den Hinweis samt Text, die OFL der Schriften Inter und JetBrains Mono ebenso). Erfasst wird jedes Paket,
 * aus dem der Build ein Modul lädt – auch die Schriftpakete, deren CSS `main.tsx` importiert.
 */
function thirdPartyLicenses(): Plugin {
  return {
    name: 'partforge:third-party-licenses',
    apply: 'build',
    generateBundle(_options, bundle) {
      const dirs = new Set<string>()
      for (const id of this.getModuleIds()) {
        const dir = packageDir(id)
        if (dir) dirs.add(dir)
      }
      for (const out of Object.values(bundle)) {
        if (out.type !== 'chunk') continue
        for (const id of out.moduleIds ?? Object.keys(out.modules ?? {})) {
          const dir = packageDir(id)
          if (dir) dirs.add(dir)
        }
      }
      const helpers = RUNTIME_HELPERS.map((name) => fileURLToPath(new URL(`./node_modules/${name}`, import.meta.url)))
      // The STEP parser is bundled by a separate worker build, outside this module graph.
      const stepDir = fileURLToPath(new URL('./node_modules/occt-import-js', import.meta.url))
      const stepPackage = readPackage(stepDir)
      if (stepPackage) {
        stepPackage.license += ' (Open CASCADE Technology: LGPL-2.1 mit OCCT-Ausnahme)'
        for (const file of ['dist/license.occt.txt', 'dist/license.occt-import-js.txt']) {
          stepPackage.texts.push({ file, text: readFileSync(join(stepDir, file), 'utf8').trim() })
        }
        stepPackage.texts.push({
          file: 'Open CASCADE Technology / OCCT_LGPL_EXCEPTION.txt',
          text: readFileSync(new URL('../scripts/licenses/occt-lgpl-exception.txt', import.meta.url), 'utf8').trim(),
        }, {
          file: 'STEP library sources and rebuild instructions',
          text: [
            'The STEP preview uses Open CASCADE Technology, distributed unchanged as a separate WASM file.',
            'occt-import-js 0.0.23: https://github.com/kovacsv/occt-import-js/tree/0.0.23',
            'Open CASCADE Technology 7.6.1 (d2abb6d844231cb8f29be6894440874a4700e4a5): https://github.com/Open-Cascade-SAS/OCCT/tree/V7_6_1',
            'Sources, rebuilding and replacing the library: https://github.com/trosenbusch/PartForge/blob/main/THIRD_PARTY_NOTICES.md',
          ].join('\n'),
        })
      }
      const packages = [
        ...[...dirs].filter((dir) => existsSync(join(dir, 'package.json'))).map((dir) => readPackage(dir)),
        ...helpers.filter((dir) => existsSync(join(dir, 'package.json'))).map((dir) => readPackage(dir, true)),
        stepPackage,
      ].filter((p): p is BundledPackage => p !== null)
      // je Paketname eine Fassung (verschachtelte Kopien gleicher Version zusammenfassen)
      const unique = new Map<string, BundledPackage>()
      for (const p of packages) unique.set(`${p.name}@${p.version}`, p)
      const sorted = [...unique.values()].sort((a, b) => a.name.localeCompare(b.name))
      const rule = '='.repeat(100)
      const lines = [
        'PartForge – Lizenzhinweise der Oberfläche (Drittanbieter-Pakete)',
        '',
        `Diese Datei entsteht beim Bauen des Frontends (vite build) und nennt alle ${sorted.length} Pakete, die in die`,
        'ausgelieferten Skripte, Stile und Schriften gebündelt sind – mit Version, Lizenz und dem Lizenztext des Pakets.',
        'Die Python-Seite des Programms beschreibt THIRD_PARTY_NOTICES.md bzw. THIRD_PARTY_LICENSES.txt im Programmordner.',
        '',
        ...sorted.map((p) => `  ${p.name} ${p.version} – ${p.license}`),
        '',
      ]
      // Pakete ohne eigene Lizenzdatei: Verweis auf den Text eines Pakets mit derselben Lizenz (Standardtext)
      const sample = new Map<string, string>()
      for (const p of sorted) if (p.texts.length && !sample.has(p.license)) sample.set(p.license, p.name)
      for (const p of sorted) {
        lines.push(rule, `${p.name} ${p.version}`, `Lizenz: ${p.license}`)
        if (p.homepage) lines.push(`Quelle: ${p.homepage}`)
        if (!p.texts.length) {
          const like = sample.get(p.license)
          lines.push(
            '',
            like
              ? `(Das Paket enthält keine eigene Lizenzdatei – es gilt der Standardtext der Lizenz ${p.license}, siehe „${like}“.)`
              : `(Das Paket enthält keine eigene Lizenzdatei – es gilt der Standardtext der Lizenz ${p.license}.)`,
          )
        }
        for (const t of p.texts) lines.push('', `--- ${t.file} ---`, '', t.text)
        lines.push('')
      }
      this.emitFile({ type: 'asset', fileName: THIRD_PARTY_LICENSES, source: `${lines.join('\n')}\n` })
    },
  }
}

export default defineConfig({
  plugins: [agGridModules(), react(), tailwindcss(), thirdPartyLicenses()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: BACKEND, changeOrigin: true, ws: true },
    },
  },
  build: {
    outDir: '../partforge/web',
    emptyOutDir: true,
    // Warnung ab 900 kB – größere Chunks deuten auf eine schwere Bibliothek im falschen Bundle hin
    chunkSizeWarningLimit: 900,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: VENDOR_GROUPS,
        },
      },
    },
  },
})
