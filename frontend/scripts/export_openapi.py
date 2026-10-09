"""Dump the PartForge OpenAPI schema to frontend/openapi.json – or check that it is current.

    .venv/Scripts/python.exe frontend/scripts/export_openapi.py            # schreiben
    .venv/Scripts/python.exe frontend/scripts/export_openapi.py --check    # nur prüfen (Exit-Code 1 bei Abweichung)
    npm run gen:api            (inside frontend/: export + openapi-typescript)
    npm run gen:api:check      (läuft vor jedem `npm run build`)

The schema is generated from ``partforge.app.create_app`` without starting a server.
PARTFORGE_HOME is pointed at a temporary folder so the user's real settings are untouched.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1]
ROOT = FRONTEND.parent
TARGET = FRONTEND / "openapi.json"


def build_spec() -> dict:
    os.environ.setdefault("PARTFORGE_HOME", tempfile.mkdtemp(prefix="partforge-openapi-"))
    sys.path.insert(0, str(ROOT))
    from partforge.app import create_app

    return create_app(token="openapi-export").openapi()


def main() -> int:
    # In Pipes (npm, CI) schreibt Python sonst im ANSI-Zeichensatz – Umlaute würden unlesbar
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="nur prüfen, ob openapi.json aktuell ist")
    args = parser.parse_args()

    try:
        spec = build_spec()
    except Exception as exc:  # noqa: BLE001 - backend currently broken: warn, but do not block frontend builds
        print(f"WARNUNG: OpenAPI-Schema konnte nicht erzeugt werden ({exc.__class__.__name__}: {exc}).", file=sys.stderr)
        print("         Typprüfung gegen das Backend übersprungen.", file=sys.stderr)
        return 0

    if args.check:
        current = json.loads(TARGET.read_text(encoding="utf-8")) if TARGET.is_file() else None
        if current != spec:
            paths_now = set(spec.get("paths", {}))
            paths_old = set((current or {}).get("paths", {}))
            added, removed = sorted(paths_now - paths_old), sorted(paths_old - paths_now)
            print("FEHLER: src/api/schema.d.ts ist nicht mehr aktuell – das Backend-API hat sich geändert.", file=sys.stderr)
            if added:
                print(f"  neue Pfade: {', '.join(added[:12])}{' …' if len(added) > 12 else ''}", file=sys.stderr)
            if removed:
                print(f"  entfernte Pfade: {', '.join(removed[:12])}{' …' if len(removed) > 12 else ''}", file=sys.stderr)
            if not added and not removed:
                print("  (geänderte Modelle/Felder)", file=sys.stderr)
            print("  Bitte `npm run gen:api` ausführen und Typfehler beheben.", file=sys.stderr)
            return 1
        print(f"OpenAPI-Schema aktuell ({len(spec.get('paths', {}))} Pfade).")
        return 0

    # newline="\n": LF on every platform, as in the repository (.gitattributes)
    TARGET.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{TARGET} ({len(spec.get('paths', {}))} Pfade)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
