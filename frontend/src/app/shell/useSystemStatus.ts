import { useAltiumStatus } from '@/api/altium'
import { aiSettingsSignature, useAiConnection, useHealth, useSettings, type AiConnectionCheck } from '@/api/system'
import { formatNumber, formatRelativeTime, shortenPath } from '@/lib/format'
import { SETTINGS_PLACE, WRITER } from '@/lib/settingsPlaces'

/**
 * Ampelstufe: `ok` grün · `warn` gelb · `error` rot · `off` grau (bewusst aus / nicht gestartet) ·
 * `unknown` grauer Ring (Abfrage fehlgeschlagen – nie grün) · `pending` grau pulsierend (wird geprüft).
 */
export type StatusLevel = 'ok' | 'warn' | 'error' | 'off' | 'unknown' | 'pending'

export interface StatusItem {
  key: 'db' | 'altium' | 'ai'
  label: string
  level: StatusLevel
  /** Kurzzustand, z. B. „SQLite verbunden“ */
  title: string
  /** Sehr kurzer Zustand für die Sidebar, z. B. „SQLite“ */
  short: string
  /** Detailzeile für den Tooltip */
  detail: string
  /** Wohin führt ein Klick (Behebung) */
  to: string
}

export const statusColor: Record<StatusLevel, string> = {
  ok: 'var(--pf-success)',
  warn: 'var(--pf-warning)',
  error: 'var(--pf-danger)',
  off: 'var(--pf-fg-subtle)',
  unknown: 'var(--pf-fg-subtle)',
  pending: 'var(--pf-fg-subtle)',
}

/**
 * Anzeigenamen der Claude-Modelle (Empfehlungen: docs/entwicklung/recherche/claude-api.md – Opus 5.5 mit
 * Aufwand „niedrig“ für Datenblätter, Haiku 5.5 als schnelles Modell). Unbekannte IDs werden lesbar gemacht.
 */
const MODEL_NAMES: Record<string, string> = {
  'claude-opus-5-5': 'Claude Opus 5.5',
  'claude-sonnet-5-5': 'Claude Sonnet 5.5',
  'claude-haiku-5-5': 'Claude Haiku 5.5',
  'claude-opus-5': 'Claude Opus 5',
  'claude-sonnet-5': 'Claude Sonnet 5',
  'claude-haiku-4-5-20251001': 'Claude Haiku 4.5',
}

export function modelDisplayName(model: string): string {
  const known = MODEL_NAMES[model]
  if (known) return known
  // „claude-sonnet-4-6“ → „Claude Sonnet 4.6“
  const m = model.match(/^claude-([a-z]+)-(\d+)(?:-(\d+))?(?:-\d{8})?$/)
  if (!m) return model
  const family = m[1][0].toUpperCase() + m[1].slice(1)
  return `Claude ${family} ${m[2]}${m[3] ? `.${m[3]}` : ''}`
}

const AI_PROBLEM: Record<NonNullable<AiConnectionCheck['code']>, { level: StatusLevel; title: string; short: string }> = {
  key_rejected: { level: 'error', title: 'Schlüssel abgelehnt', short: 'abgelehnt' },
  key_missing: { level: 'warn', title: 'API-Schlüssel fehlt', short: 'kein Schlüssel' },
  model_unavailable: { level: 'warn', title: 'Modell nicht verfügbar', short: 'Modell fehlt' },
  network: { level: 'warn', title: 'Claude-API nicht erreichbar', short: 'keine Verbindung' },
  rate_limited: { level: 'warn', title: 'Anfragelimit erreicht', short: 'Limit erreicht' },
  ai_disabled: { level: 'off', title: 'KI-Funktionen ausgeschaltet', short: 'aus' },
  unexpected: { level: 'warn', title: 'Unerwartete Antwort', short: 'Antwort unklar' },
  unknown: { level: 'warn', title: 'Verbindungstest fehlgeschlagen', short: 'Fehler' },
}

/** Ampelstatus für Datenbank, Altium und KI (Sidebar, Übersicht). */
export function useSystemStatus(): StatusItem[] {
  const health = useHealth()
  const settings = useSettings()
  const altiumStatus = useAltiumStatus()
  const lastAiCheck = useAiConnection((s) => s.last)

  // --- Datenbank
  let db: StatusItem
  if (health.isError) {
    db = {
      key: 'db',
      label: 'Datenbank',
      level: 'error',
      title: 'Backend nicht erreichbar',
      short: 'offline',
      detail: 'Der lokale PartForge-Dienst antwortet nicht.',
      to: '/',
    }
  } else if (!health.data) {
    db = { key: 'db', label: 'Datenbank', level: 'pending', title: 'Wird geprüft …', short: '…', detail: '', to: '/' }
  } else if (health.data.workspace) {
    const ws = health.data.workspace
    const kind = ws.db_kind === 'postgres' ? 'PostgreSQL' : 'SQLite'
    db = {
      key: 'db',
      label: 'Datenbank',
      level: 'ok',
      title: `${kind} verbunden`,
      short: kind,
      detail: ws.db_kind === 'postgres' ? ws.name : shortenPath(ws.sqlite_path, 48),
      to: SETTINGS_PLACE.library.to,
    }
  } else {
    db = {
      key: 'db',
      label: 'Datenbank',
      level: 'off',
      title: 'Keine Bibliothek geöffnet',
      short: 'keine',
      detail: 'Bibliothek öffnen oder neu anlegen.',
      to: '/willkommen',
    }
  }

  // --- Altium (GET /api/altium/status: läuft Altium Designer gerade?) – nie grün ohne frische, erfolgreiche Antwort
  const s = settings.data
  let altium: StatusItem
  const st = altiumStatus.data
  if (altiumStatus.isError) {
    altium = {
      key: 'altium',
      label: 'Altium',
      level: 'unknown',
      title: 'Altium-Status unbekannt',
      short: 'unbekannt',
      detail: 'Der Status konnte nicht abgefragt werden – PartForge versucht es alle 15 Sekunden erneut.',
      to: '/altium',
    }
  } else if (!st) {
    altium = { key: 'altium', label: 'Altium', level: 'pending', title: 'Wird geprüft …', short: '…', detail: '', to: '/altium' }
  } else {
    const backend = s?.settings.altium.library_backend
    const rust = st.backends.find((b) => b.name === 'rust')
    const rustReady = Boolean(rust?.available)
    const version = st.version ? `Altium Designer ${st.version}` : 'Altium Designer'
    if (st.altium_running && st.bridge_wedged) {
      altium = {
        key: 'altium',
        label: 'Altium',
        level: 'error',
        title: 'Altium-Skript hängt',
        short: 'Skript hängt',
        detail: 'Ein PartForge-Skript hängt in Altium – dort Strg+F3 drücken (Skript anhalten) und erneut versuchen.',
        to: '/altium',
      }
    } else if (st.altium_running) {
      altium = {
        key: 'altium',
        label: 'Altium',
        level: 'ok',
        title: `${version} läuft`,
        short: 'läuft',
        detail: st.refresh.auto_refresh
          ? 'Änderungen an der Bibliothek erscheinen automatisch in Altium.'
          : 'Änderungen erscheinen nach „In Altium aktualisieren“.',
        to: '/altium',
      }
    } else if (!st.altium_exe) {
      altium = {
        key: 'altium',
        label: 'Altium',
        level: rustReady && backend !== 'altium' ? 'off' : 'warn',
        title: 'Altium Designer nicht gefunden',
        short: 'nicht gefunden',
        detail: rustReady
          ? `Bibliotheken schreibt der ${WRITER} ohne Altium. Für Installieren und Prüfen den Pfad zu X2.EXE unter ${SETTINGS_PLACE.altium.label} eintragen.`
          : `Weder Altium Designer noch der ${WRITER} ist verfügbar – ohne sie entstehen keine Bibliotheksdateien. Pfade unter ${SETTINGS_PLACE.altium.label} eintragen.`,
        to: SETTINGS_PLACE.altium.to,
      }
    } else {
      // gefunden, aber nicht gestartet
      const needsAltium = backend === 'altium' || !rustReady
      altium = {
        key: 'altium',
        label: 'Altium',
        level: needsAltium ? 'warn' : 'off',
        title: 'Altium Designer nicht gestartet',
        short: needsAltium && backend !== 'altium' ? 'kein Writer' : 'nicht gestartet',
        detail: needsAltium
          ? backend === 'altium'
            ? '„Über Altium“ ist gewählt – zum Schreiben der Bibliotheken Altium Designer starten.'
            : `Ohne Altium und ohne ${WRITER} entstehen keine Bibliotheksdateien – ${WRITER} unter ${SETTINGS_PLACE.altium.label} eintragen oder Altium Designer starten.`
          : `Bibliotheken schreibt der ${WRITER} ohne Altium. Für Installieren, Aktualisieren und Prüfen Altium Designer starten.`,
        // Behebung: ohne Writer der Writer-Pfad (nicht die Altium-Seite, deren „Synchronisieren“ ebenso scheitert)
        to: needsAltium && backend !== 'altium' ? SETTINGS_PLACE.writer.to : '/altium',
      }
    }
  }

  // --- KI (Einstellungen + letzter Verbindungstest; ein abgelehnter Schlüssel bleibt rot, bis er ersetzt ist)
  let ai: StatusItem
  if (!s) {
    ai = {
      key: 'ai',
      label: 'KI',
      level: settings.isError ? 'unknown' : 'pending',
      title: settings.isError ? 'KI-Status unbekannt' : 'Wird geprüft …',
      short: settings.isError ? 'unbekannt' : '…',
      detail: '',
      to: SETTINGS_PLACE.ai.to,
    }
  } else if (!s.settings.ai.enabled) {
    ai = {
      key: 'ai',
      label: 'KI',
      level: 'off',
      title: 'KI-Funktionen ausgeschaltet',
      short: 'aus',
      detail: `Einschaltbar unter ${SETTINGS_PLACE.ai.label}.`,
      to: SETTINGS_PLACE.ai.to,
    }
  } else if (!s.ai_key_configured) {
    ai = {
      key: 'ai',
      label: 'KI',
      level: 'warn',
      title: 'API-Schlüssel fehlt',
      short: 'kein Schlüssel',
      detail: `Claude-API-Schlüssel unter ${SETTINGS_PLACE.ai.label} eingeben.`,
      to: SETTINGS_PLACE.ai.to,
    }
  } else {
    const name = modelDisplayName(s.settings.ai.model)
    // Ein Testergebnis gilt nur für die Konfiguration, mit der getestet wurde
    const check = lastAiCheck && lastAiCheck.signature === aiSettingsSignature(s) ? lastAiCheck : null
    const when = check ? formatRelativeTime(check.at) : ''
    if (check && !check.ok && check.code) {
      const p = AI_PROBLEM[check.code]
      ai = {
        key: 'ai',
        label: 'KI',
        level: p.level,
        title: p.title,
        short: p.short,
        detail: `${check.message ?? p.title} (${check.source === 'job' ? 'Datenblatt-Analyse' : 'Verbindungstest'} ${when})`,
        to: SETTINGS_PLACE.ai.to,
      }
    } else if (check?.ok) {
      const latency = check.latencyMs !== null ? ` in ${formatNumber(check.latencyMs)} ms` : ''
      ai = {
        key: 'ai',
        label: 'KI',
        level: 'ok',
        title: 'Claude verbunden',
        short: name.replace(/^Claude /, ''),
        detail: `${name} – Verbindung ${when} geprüft${check.model ? ` (${modelDisplayName(check.model)}${latency})` : latency}.`,
        to: SETTINGS_PLACE.ai.to,
      }
    } else {
      ai = {
        key: 'ai',
        label: 'KI',
        level: 'ok',
        title: 'Claude bereit',
        short: name.replace(/^Claude /, ''),
        detail: `${name} – Schlüssel hinterlegt, Verbindung noch nicht geprüft (${SETTINGS_PLACE.ai.label} › Verbindung testen).`,
        to: SETTINGS_PLACE.ai.to,
      }
    }
  }

  return [db, altium, ai]
}
