import { localizeMessage } from '@/lib/i18n'
import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
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
  key_rejected: { level: 'error', get title() { return tr("Schlüssel abgelehnt") }, get short() { return tr('abgelehnt') } },
  key_missing: { level: 'warn', get title() { return tr("API-Schlüssel fehlt") }, get short() { return tr("kein Schlüssel") } },
  model_unavailable: { level: 'warn', get title() { return tr("Modell nicht verfügbar") }, get short() { return tr("Modell fehlt") } },
  network: { level: 'warn', get title() { return tr("Claude-API nicht erreichbar") }, get short() { return tr("keine Verbindung") } },
  rate_limited: { level: 'warn', get title() { return tr("Anfragelimit erreicht") }, get short() { return tr("Limit erreicht") } },
  ai_disabled: { level: 'off', get title() { return tr("KI-Funktionen ausgeschaltet") }, get short() { return tr('aus') } },
  unexpected: { level: 'warn', get title() { return tr("Unerwartete Antwort") }, get short() { return tr("Antwort unklar") } },
  unknown: { level: 'warn', get title() { return tr("Verbindungstest fehlgeschlagen") }, get short() { return tr("Fehler") } },
}

/** Ampelstatus für Datenbank, Altium und KI (Sidebar, Übersicht). */
export function useSystemStatus(): StatusItem[] {
  const { t: tr } = useI18n()
  const health = useHealth()
  const settings = useSettings()
  const altiumStatus = useAltiumStatus()
  const lastAiCheck = useAiConnection((s) => s.last)

  // --- Datenbank
  let db: StatusItem
  if (health.isError) {
    db = {
      key: 'db',
      label: tr("Datenbank"),
      level: 'error',
      title: tr("Backend nicht erreichbar"),
      short: 'offline',
      detail: tr("Der lokale PartForge-Dienst antwortet nicht."),
      to: '/',
    }
  } else if (!health.data) {
    db = { key: 'db', label: tr("Datenbank"), level: 'pending', title: tr("Wird geprüft …"), short: '…', detail: '', to: '/' }
  } else if (health.data.workspace) {
    const ws = health.data.workspace
    const kind = ws.db_kind === 'postgres' ? 'PostgreSQL' : 'SQLite'
    db = {
      key: 'db',
      label: tr("Datenbank"),
      level: 'ok',
      title: tr("{0} verbunden", { "0": String(kind) }),
      short: kind,
      detail: ws.db_kind === 'postgres' ? ws.name : shortenPath(ws.sqlite_path, 48),
      to: SETTINGS_PLACE.library.to,
    }
  } else {
    db = {
      key: 'db',
      label: tr("Datenbank"),
      level: 'off',
      title: tr("Keine Bibliothek geöffnet"),
      short: tr('keine'),
      detail: tr("Bibliothek öffnen oder neu anlegen."),
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
      title: tr("Altium-Status unbekannt"),
      short: tr('unbekannt'),
      detail: tr("Der Status konnte nicht abgefragt werden – PartForge versucht es alle 15 Sekunden erneut."),
      to: '/altium',
    }
  } else if (!st) {
    altium = { key: 'altium', label: 'Altium', level: 'pending', title: tr("Wird geprüft …"), short: '…', detail: '', to: '/altium' }
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
        title: tr("Altium-Skript hängt"),
        short: tr("Skript hängt"),
        detail: tr("Ein PartForge-Skript hängt in Altium – dort Strg+F3 drücken (Skript anhalten) und erneut versuchen."),
        to: '/altium',
      }
    } else if (st.altium_running) {
      altium = {
        key: 'altium',
        label: 'Altium',
        level: 'ok',
        title: tr("{0} läuft", { "0": String(version) }),
        short: tr("läuft"),
        detail: st.refresh.auto_refresh
          ? tr("Änderungen an der Bibliothek erscheinen automatisch in Altium.")
          : tr("Änderungen erscheinen nach „In Altium aktualisieren“."),
        to: '/altium',
      }
    } else if (!st.altium_exe) {
      altium = {
        key: 'altium',
        label: 'Altium',
        level: rustReady && backend !== 'altium' ? 'off' : 'warn',
        title: tr("Altium Designer nicht gefunden"),
        short: tr("nicht gefunden"),
        detail: rustReady
          ? tr("Bibliotheken schreibt der {0} ohne Altium. Für Installieren und Prüfen den Pfad zu X2.EXE unter {1} eintragen.", { "0": tr(WRITER), "1": String(SETTINGS_PLACE.altium.label) })
          : tr("Weder Altium Designer noch der {0} ist verfügbar – ohne sie entstehen keine Bibliotheksdateien. Pfade unter {1} eintragen.", { "0": tr(WRITER), "1": String(SETTINGS_PLACE.altium.label) }),
        to: SETTINGS_PLACE.altium.to,
      }
    } else {
      // gefunden, aber nicht gestartet
      const needsAltium = backend === 'altium' || !rustReady
      altium = {
        key: 'altium',
        label: 'Altium',
        level: needsAltium ? 'warn' : 'off',
        title: tr("Altium Designer nicht gestartet"),
        short: needsAltium && backend !== 'altium' ? tr("kein Writer") : tr("nicht gestartet"),
        detail: needsAltium
          ? backend === 'altium'
            ? tr("„Über Altium“ ist gewählt – zum Schreiben der Bibliotheken Altium Designer starten.")
            : tr("Ohne Altium und ohne {0} entstehen keine Bibliotheksdateien – {1} unter {2} eintragen oder Altium Designer starten.", { "0": tr(WRITER), "1": tr(WRITER), "2": String(SETTINGS_PLACE.altium.label) })
          : tr("Bibliotheken schreibt der {0} ohne Altium. Für Installieren, Aktualisieren und Prüfen Altium Designer starten.", { "0": tr(WRITER) }),
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
      label: tr("KI"),
      level: settings.isError ? 'unknown' : 'pending',
      title: settings.isError ? tr("KI-Status unbekannt") : tr("Wird geprüft …"),
      short: settings.isError ? tr('unbekannt') : '…',
      detail: '',
      to: SETTINGS_PLACE.ai.to,
    }
  } else if (!s.settings.ai.enabled) {
    ai = {
      key: 'ai',
      label: tr("KI"),
      level: 'off',
      title: tr("KI-Funktionen ausgeschaltet"),
      get short() { return tr('aus') },
      detail: tr("Einschaltbar unter {0}.", { "0": String(SETTINGS_PLACE.ai.label) }),
      to: SETTINGS_PLACE.ai.to,
    }
  } else if (!s.ai_key_configured) {
    ai = {
      key: 'ai',
      label: tr("KI"),
      level: 'warn',
      title: tr("API-Schlüssel fehlt"),
      short: tr("kein Schlüssel"),
      detail: tr("Claude-API-Schlüssel unter {0} eingeben.", { "0": String(SETTINGS_PLACE.ai.label) }),
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
        label: tr("KI"),
        level: p.level,
        title: p.title,
        short: p.short,
        detail: `${localizeMessage(check.message ?? p.title)} (${check.source === 'job' ? tr('Datenblatt-Analyse') : tr('Verbindungstest')} ${when})`,
        to: SETTINGS_PLACE.ai.to,
      }
    } else if (check?.ok) {
      const latency = check.latencyMs !== null ? ` in ${formatNumber(check.latencyMs)} ms` : ''
      ai = {
        key: 'ai',
        label: tr("KI"),
        level: 'ok',
        title: tr("Claude verbunden"),
        short: name.replace(/^Claude /, ''),
        detail: tr("{0} – Verbindung {1} geprüft{2}.", { "0": String(name), "1": String(when), "2": String(check.model ? ` (${modelDisplayName(check.model)}${latency})` : latency) }),
        to: SETTINGS_PLACE.ai.to,
      }
    } else {
      ai = {
        key: 'ai',
        label: tr("KI"),
        level: 'ok',
        title: tr("Claude bereit"),
        short: name.replace(/^Claude /, ''),
        detail: tr("{0} – Schlüssel hinterlegt, Verbindung noch nicht geprüft ({1} › Verbindung testen).", { "0": String(name), "1": String(SETTINGS_PLACE.ai.label) }),
        to: SETTINGS_PLACE.ai.to,
      }
    }
  }

  return [db, altium, ai]
}
