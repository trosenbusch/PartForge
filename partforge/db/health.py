"""Data quality checks of the library ("Bibliothek prüfen").

Each issue: ``{severity: error|warning|info, check, table, part_number, column, message, fix_hint}``.

Checks: empty required fields, duplicate part numbers (across tables) and MPNs, unparsable /
non-canonical values, enum values outside the option list, invisible characters in part numbers and
MPNs, references to symbols/footprints that are not registered or failed to sync, library files that
do not exist, missing datasheet links.

Fields that do not apply to a part are not required: a 0-Ω jumper has no tolerance, TCR, power
rating or working voltage (:func:`partforge.db.values.not_applicable`). Asymmetric tolerance bands
(``"-100 … +350ppm/K"``) are valid values of relative fields. Duplicates are found with the keys the
database layer uses for uniqueness: :func:`partforge.db.parts.pn_key` (part numbers – Unicode case,
NFC/NFD and invisible format characters ignored) and :func:`partforge.db.parts.mpn_key` (MPNs, also
without blanks and dashes).

Report (:func:`health_report`): ``issues`` (sorted by severity and check, at most ``max_per_check``
per check), ``summary`` (issues per check) and ``counts`` (per severity) over **all** issues, ``total``,
``truncated``, ``checked_at`` and – exact even when issues are cut – ``checked_parts``,
``affected_parts`` / ``affected_part_numbers`` (every part with an error or warning exactly once) and
``checks`` (per check: ``severity``, ``issues``, ``affected_parts`` and the first
:data:`CHECK_SAMPLE_SIZE` ``part_numbers``).

Speed: values are normalised once per distinct (field, value) per report and the scan of the
database is cached until the database changes (:func:`partforge.db.core.data_version`, the SQLite
file and its WAL, i.e. also writes of other programs); only the existence of the library files is
checked again on every request.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select

from . import categories, core, registry
from .models import CategoryDef, FieldDef, HealthIssue, IssueSeverity
from .parts import BOOKKEEPING, DATASHEET_COLUMN, mpn_key, pn_key
from .values import (
    IDENTITY_COLUMNS,
    PART_NUMBER,
    CellResult,
    invisible_characters,
    normalize_cell,
    not_applicable,
)

log = logging.getLogger(__name__)

__all__ = ["CHECK_SAMPLE_SIZE", "check_database", "health_report"]

#: Part numbers per check in ``checks[<check>].part_numbers`` (sorted, the rest is only counted).
CHECK_SAMPLE_SIZE = 20

_TYPED_KINDS = ("quantity", "range", "int", "bool", "url", "date")
_FOOTPRINT_REF = re.compile(r"^Footprint Ref( \d+)?$", re.IGNORECASE)
_FOOTPRINT_PATH = re.compile(r"^Footprint Path( \d+)?$", re.IGNORECASE)
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
_FILE_MISSING_HINT = "Bibliotheken synchronisieren (Bereich Altium) oder den Pfad korrigieren."


@dataclass(frozen=True, slots=True)
class _Issue:
    """One finding (light-weight: the cached scan holds thousands of them)."""

    check: str
    severity: IssueSeverity
    message: str
    table: str | None = None
    part_number: str | None = None
    column: str | None = None
    fix_hint: str | None = None


@dataclass
class _Scan:
    """Everything the report needs that depends only on the database content (cached)."""

    issues: list[_Issue] = field(default_factory=list)
    checked_parts: int = 0
    # stored library path -> references (table, part number, column) whose file must exist
    path_refs: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)


class _Values:
    """``normalize_cell`` once per distinct (field definition, value) within one report."""

    def __init__(self, ws_root: Path) -> None:
        self._ws_root = ws_root
        self._memo: dict[tuple[Any, ...], CellResult] = {}

    def __call__(self, f: FieldDef, cell: str) -> CellResult:
        key = (id(f), cell)  # the field objects live as long as the scan
        res = self._memo.get(key)
        if res is None:
            res = normalize_cell(f, cell, ws_root=self._ws_root)
            self._memo[key] = res
        return res


@dataclass
class _Layout:
    """Per-category column roles (computed once per category, not per row)."""

    typed: list[FieldDef]
    required: list[FieldDef]
    footprint_refs: list[str]
    path_columns: list[str]
    has_datasheet: bool


def _layout(cat: CategoryDef) -> _Layout:
    columns = [f.column for f in cat.fields]
    return _Layout(
        typed=[f for f in cat.fields if (f.kind == "enum" and f.options) or f.kind in _TYPED_KINDS
               or f.column in IDENTITY_COLUMNS],
        required=[f for f in cat.fields if f.required and f.column not in BOOKKEEPING],
        footprint_refs=[c for c in columns if _FOOTPRINT_REF.match(c)],
        path_columns=[c for c in columns if c == "Library Path" or _FOOTPRINT_PATH.match(c)],
        has_datasheet=DATASHEET_COLUMN in columns,
    )


def _check_values(out: list[_Issue], cat: CategoryDef, lay: _Layout, row: Mapping[str, Any], values: _Values) -> None:
    pn = str(row.get(PART_NUMBER) or "")
    exempt = not_applicable(cat, row) if lay.required else frozenset()  # 0-Ω jumper: no tolerance, TCR, power …
    missing_required: set[str] = set()
    for f in lay.required:
        cell = row.get(f.column)
        if (cell is None or str(cell).strip() == "") and f.column not in exempt:
            missing_required.add(f.column)
            out.append(_Issue("required", "error", f"Pflichtfeld „{f.label}“ ist leer.", cat.table, pn, f.column,
                              "Wert eintragen – Altium braucht ihn für Platzierung oder Stückliste."))
    for f in lay.typed:
        cell = row.get(f.column)
        if cell is None or f.column in missing_required:
            continue
        text = str(cell)
        if not text.strip():
            continue
        if f.column in IDENTITY_COLUMNS and f.kind not in _TYPED_KINDS and f.kind != "enum":
            hidden = invisible_characters(text)
            if hidden:  # soft hyphen, zero-width space, BOM … copied from a web page or PDF
                out.append(_Issue(
                    "format", "warning", f"{f.label}: „{text}“ enthält unsichtbare Zeichen ({', '.join(hidden)}).",
                    cat.table, pn, f.column,
                    "Den Wert neu eintippen (bei der Teilenummer: Bauteil umbenennen) – sonst sieht Altium zwei "
                    "verschiedene Nummern, die gleich aussehen."))
            continue
        res = values(f, text)
        if f.kind == "enum":
            if res.warning:
                out.append(_Issue("enum", "info", f"„{cell}“ steht nicht in der Auswahlliste von „{f.label}“.",
                                  cat.table, pn, f.column,
                                  "Wert vereinheitlichen oder die Auswahlliste des Feldes ergänzen."))
            continue
        if res.warning:
            out.append(_Issue("value", "warning", f"{f.label}: {res.warning}", cat.table, pn, f.column,
                              "Wert korrigieren (Schreibweise z. B. 10k, 100n, ±1 %, 2.7 … 5.5 V)."))
        elif res.value is not None and res.value != cell and f.kind in ("quantity", "range"):
            out.append(_Issue("format", "info", f"{f.label}: „{cell}“ ist nicht im Standardformat („{res.value}“).",
                              cat.table, pn, f.column,
                              "Bauteil einmal speichern – PartForge schreibt den Wert dann einheitlich."))


def _check_links(scan: _Scan, cat: CategoryDef, lay: _Layout, row: Mapping[str, Any], symbols: dict[str, Any],
                 footprints: dict[str, Any]) -> None:
    out = scan.issues
    pn = str(row.get(PART_NUMBER) or "")
    lib_ref = str(row.get("Library Ref") or "").strip()
    pending_refs: set[str] = set()
    if lib_ref:
        rec = symbols.get(lib_ref.casefold())
        if rec is None:
            out.append(_Issue("symbol_missing", "warning", f"Symbol „{lib_ref}“ ist in PartForge nicht registriert.",
                              cat.table, pn, "Library Ref", "Symbol erzeugen/importieren oder „Library Ref“ korrigieren."))
        elif rec.status == "pending":
            pending_refs.add("Library Path")
    for column in lay.footprint_refs:
        ref = str(row.get(column) or "").strip()
        if not ref:
            continue
        rec = footprints.get(ref.casefold())
        if rec is None:
            out.append(_Issue("footprint_missing", "warning", f"Footprint „{ref}“ ist in PartForge nicht registriert.",
                              cat.table, pn, column,
                              "Footprint mit dem Generator erzeugen/importieren oder den Namen korrigieren."))
        elif rec.status == "pending":
            pending_refs.add(column.replace("Ref", "Path"))
    for column in lay.path_columns:
        path = str(row.get(column) or "").strip()
        if path and column not in pending_refs:
            scan.path_refs.setdefault(path, []).append((cat.table, pn, column))
    if lay.has_datasheet and not str(row.get(DATASHEET_COLUMN) or "").strip():
        out.append(_Issue("datasheet_missing", "info", "Kein Datenblatt-Link hinterlegt.", cat.table, pn,
                          DATASHEET_COLUMN, "Datenblatt-URL eintragen oder ein Datenblatt importieren."))


def _scan_database(ws_root: Path) -> _Scan:
    scan = _Scan()
    values = _Values(ws_root)
    symbols = {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)}
    footprints = {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)}
    pn_seen: dict[str, list[tuple[str, str]]] = {}
    mpn_seen: dict[str, list[tuple[str, str, str]]] = {}
    cats = categories.list_categories(with_counts=False)
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)
            lay = _layout(cat)
            for raw in conn.execute(select(table)).mappings():
                row = {str(k): (v if v is None or isinstance(v, str) else str(v)) for k, v in raw.items()}
                scan.checked_parts += 1
                pn = str(row.get(PART_NUMBER) or "")
                pn_seen.setdefault(pn_key(pn), []).append((cat.table, pn))
                mpn = str(row.get("Manufacturer Part Number") or "").strip()
                if mpn:
                    mpn_seen.setdefault(mpn_key(mpn), []).append((cat.table, pn, mpn))
                _check_values(scan.issues, cat, lay, row, values)
                _check_links(scan, cat, lay, row, symbols, footprints)
    for occurrences in pn_seen.values():
        if len(occurrences) < 2:
            continue
        first_table, first_pn = occurrences[0]
        for table_name, pn in occurrences[1:]:
            scan.issues.append(_Issue(
                "duplicate_pn", "error", f"Teilenummer „{pn}“ ist mehrfach vergeben (auch „{first_pn}“ in „{first_table}“).",
                table_name, pn, PART_NUMBER,
                "Eine der Teilenummern ändern – Altium findet sonst beim Aktualisieren das falsche Bauteil."))
    for mpn_occurrences in mpn_seen.values():
        if len(mpn_occurrences) < 2:
            continue
        for table_name, pn, mpn in mpn_occurrences:
            others = ", ".join(f"{p} ({t})" for t, p, _ in mpn_occurrences if (t, p) != (table_name, pn))
            scan.issues.append(_Issue(
                "duplicate_mpn", "warning", f"Hersteller-Teilenummer „{mpn}“ kommt mehrfach vor (auch bei {others}).",
                table_name, pn, "Manufacturer Part Number",
                "Doppelte Bauteile zusammenführen oder die Hersteller-Teilenummer korrigieren."))
    for kind, records in (("Symbol", symbols), ("Footprint", footprints)):
        for rec in records.values():
            if rec.status == "error":
                scan.issues.append(_Issue(
                    "registry_error", "warning",
                    f"{kind} „{rec.name}“ konnte nicht geschrieben werden: {rec.status_message or 'unbekannter Fehler'}.",
                    fix_hint="Im Bereich Altium „Synchronisieren“ erneut ausführen; Details im Protokoll."))
            elif rec.status == "missing":
                scan.issues.append(_Issue(
                    "registry_missing", "warning", f"{kind} „{rec.name}“ fehlt in der Bibliotheksdatei „{rec.library}“.",
                    fix_hint="Im Bereich Altium „Synchronisieren“ ausführen."))
    return scan


# --------------------------------------------------------------------------- cache of the database scan

_cache_lock = threading.Lock()
_scan_lock = threading.Lock()
_cached: tuple[tuple[Any, ...], _Scan] | None = None


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _scan_key(ws: Any, version: int) -> tuple[Any, ...]:
    """When the cached scan is still valid: same library, no write of this process since, and – SQLite –
    the database file and its WAL unchanged (writes of other programs such as Altium's table browser)."""
    key: tuple[Any, ...] = (str(ws.root), id(core.get_engine()), version)
    if ws.settings.db.kind == "sqlite":
        db = ws.sqlite_path
        key += (_file_stamp(db), _file_stamp(db.with_name(db.name + "-wal")))
    else:  # PostgreSQL: changes of other clients are seen within a minute
        key += (int(_dt.datetime.now().timestamp() // 60),)
    return key


def _database_scan(ws: Any) -> _Scan:
    global _cached
    with _scan_lock:  # concurrent requests (dashboard, Altium page) wait for one scan instead of running two
        key = _scan_key(ws, core.data_version())  # read before scanning: a write meanwhile makes it stale
        with _cache_lock:
            if _cached is not None and _cached[0] == key:
                return _cached[1]
        scan = _scan_database(ws.root)
        with _cache_lock:
            _cached = (key, scan)
        return scan


def clear_cache() -> None:
    """Forget the cached database scan (tests)."""
    global _cached
    with _cache_lock:
        _cached = None


# --------------------------------------------------------------------------- report


def _file_issues(scan: _Scan, file_exists: Callable[[str], bool]) -> list[_Issue]:
    out: list[_Issue] = []
    for path, refs in scan.path_refs.items():
        if file_exists(path):
            continue
        for table, pn, column in refs:
            out.append(_Issue("library_file_missing", "warning", f"Bibliotheksdatei „{path}“ ({column}) existiert nicht.",
                              table, pn, column, _FILE_MISSING_HINT))
    return out


def health_report(*, max_per_check: int | None = 200) -> dict[str, Any]:
    """Run all checks. Returns ``{issues, summary, counts, total, truncated, checked_at, checked_parts,
    affected_parts, affected_part_numbers, checks}`` (see the module docstring)."""
    ws = core.current_workspace()
    scan = _database_scan(ws)
    exists: dict[str, bool] = {}

    def file_exists(stored: str) -> bool:
        if stored not in exists:
            path = ws.abs(stored)
            exists[stored] = bool(path and path.is_file())
        return exists[stored]

    every = [*scan.issues, *_file_issues(scan, file_exists)]
    every.sort(key=lambda i: (_SEVERITY_ORDER[i.severity], i.check, i.table or "", i.part_number or ""))
    summary: dict[str, int] = {}
    counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    per_check: dict[str, dict[str, Any]] = {}
    affected: set[str] = set()
    listed: list[_Issue] = []
    truncated = False
    for issue in every:
        n = summary.get(issue.check, 0) + 1
        summary[issue.check] = n
        counts[issue.severity] += 1
        stat = per_check.setdefault(issue.check, {"severity": issue.severity, "issues": 0, "parts": set()})
        stat["issues"] += 1
        if _SEVERITY_ORDER[issue.severity] < _SEVERITY_ORDER[stat["severity"]]:
            stat["severity"] = issue.severity
        if issue.part_number:
            stat["parts"].add(issue.part_number)
            if issue.severity != "info":
                affected.add(issue.part_number)
        if max_per_check is not None and n > max_per_check:
            truncated = True
            continue
        listed.append(issue)
    checks = {
        check: {"severity": stat["severity"], "issues": stat["issues"], "affected_parts": len(stat["parts"]),
                "part_numbers": sorted(stat["parts"])[:CHECK_SAMPLE_SIZE]}
        for check, stat in sorted(per_check.items())
    }
    return {
        "issues": [HealthIssue(severity=i.severity, check=i.check, table=i.table, part_number=i.part_number,
                               column=i.column, message=i.message, fix_hint=i.fix_hint).model_dump() for i in listed],
        "summary": dict(sorted(summary.items())),
        "counts": counts,
        "total": len(every),
        "truncated": truncated,
        "checked_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "checked_parts": scan.checked_parts,
        "affected_parts": len(affected),
        "affected_part_numbers": sorted(affected),
        "checks": checks,
    }


def check_database(*, max_per_check: int | None = None) -> list[dict[str, Any]]:
    """All issues as dicts (``severity, check, table, part_number, column, message, fix_hint``)."""
    return list(health_report(max_per_check=max_per_check)["issues"])
