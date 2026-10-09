"""Series assistant: create a whole series of parts (sizes × values) from an MPN template.

    preview(req) -> SeriesPreview                             # fast (2000 rows < 2 s), writes nothing
    commit(ctx, req, mode="skip", *, library=None) -> dict    # job function -> SeriesCommitResult (as dict)
    sample_check(template, cat, attrs, mpn) -> SampleCheck    # one part as the series would store it

The preview interprets a :class:`SeriesRequest` with the template (codes, value rules,
availability matrix or catalog), builds one row per orderable part with the category
values exactly as a manual entry would store them (``db.values.normalize_cell`` and the
category templates for Value/Comment/Description), the footprint (``footprints``) and the
standard symbol (``symbols``), and classifies every row:

* ``new``      – the part number is free and the row passes the checks ``db.parts`` applies on saving
  (required fields, characters of the part number),
* ``exists``   – the part already exists in the category, found by part number or by the same
  manufacturer part number under another part number (``mode="update"`` refreshes it),
* ``conflict`` – the part number or the manufacturer part number is used by another part / category,
* ``invalid``  – not orderable, not generatable or not storable (messages say why).

The symbol is never guessed: it comes from the template's symbol kind (kinds with a pin map
need ``symbol_params["pinmap"]`` or a pin map that follows safely from package/footprint), else
from :func:`partforge.db.templates.resolve_default_symbol`. Without a certain symbol every row is
``invalid`` and nothing is written.

Required fields are checked like ``db.parts`` checks them, except the fields that do not apply to
the row: a 0-Ω jumper has no tolerance, TCR, power rating or working voltage
(:func:`partforge.db.values.not_applicable`; it stores 0 Ω and a note with the maximum resistance
and the rated current of its size). Footprints whose name carries a uniqueness tag
(``CAPC1608X90N_4328``) say why in :attr:`FootprintRef.name_reason`.

:func:`commit` writes symbol and footprints through :mod:`partforge.altium.sync`
(``ensure_symbols``/``ensure_footprints``; were they unavailable, the registry gets ``pending``
entries for a later library sync) and the parts through :func:`partforge.db.parts.upsert_parts`.
A symbol or footprint that was not written is never hidden: it is listed in
:attr:`SeriesCommitResult.library_problems` (``status`` ``error`` or ``pending``) and as a German
sentence in ``warnings``, and it does not count in ``footprints_created``/``symbol_created``. Rows whose
symbol or footprint failed (``error``, e.g. the PcbLib is locked or open and modified in Altium) are not
written – like the datasheet commit – and count as ``errors`` ("Nicht angelegt – …"); rows of a
``pending`` symbol/footprint (no library writer) are written, the next library sync writes the file
(``pending`` note).
Updating existing parts never touches their release workflow (``PF Status``) and keeps a
lifecycle, datasheet link, symbol or footprint the user set differently (``replace_links`` /
explicit ``field_overrides`` / ``datasheet_url`` replace them). The job stays bound to the
library it was planned in: after a library switch it stops (``JobCancelled``) before writing
anything into the other library.

Job progress: every phase is a log line and ``job.detail`` = ``{"phase": "plan" | "symbol" |
"footprints" | "backup" | "parts" | "done", "done": int | None, "total": int | None}`` (items of the
phase: footprints, parts); the job ends with a German summary in ``job.message`` (also
:attr:`SeriesCommitResult.message`): "Serie erzeugt: 1.248 neu, 12 aktualisiert, 0 übersprungen,
6 Footprints neu".
"""
from __future__ import annotations

import functools
import json
import logging
import math
import os
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, field_validator

from .. import events
from ..jobs import JobCancelled, JobContext
from ..workspace import Workspace, current_or_none
from .eseries import values_in_range
from .mpn import (
    AvailabilityCell,
    MpnError,
    MpnTemplate,
    Resolution,
    compact,
    compile_template,
    encode_mpn,
    find_option,
    format_value,
    get_template,
    in_series,
    parse_series,
    render_fields,
    resolve,
    resolve_size,
)
from .mpn.engine import base_attrs, catalog_attrs, equivalent_option
from .mpn.model import FootprintHint
from .text import clean_free_text, plural
from .units import ambiguous_thousands, parse_quantity

log = logging.getLogger(__name__)

__all__ = [
    "FootprintRef",
    "LibraryProblem",
    "PreviewRow",
    "RequiredField",
    "SampleCheck",
    "SeriesCommitDetail",
    "SeriesCommitResult",
    "SeriesError",
    "SeriesPreview",
    "SeriesRequest",
    "SymbolRef",
    "commit",
    "preview",
    "sample_check",
    "validate",
]

RowStatus = Literal["new", "exists", "conflict", "invalid"]
CommitMode = Literal["skip", "update"]
Level = Literal["info", "warn", "error", "success"]
CommitPhase = Literal["plan", "symbol", "footprints", "backup", "parts", "done"]

DEFAULT_MAX_ROWS = 5000
LINK_DESCRIPTION = "Datenblatt"
DEFAULT_LIFECYCLE = "Aktiv"
DEFAULT_PF_STATUS = "Entwurf"
PART_NUMBER = "Part Number"
MPN_COLUMN = "Manufacturer Part Number"
NO_SAFE_SYMBOL = "Symbol nicht sicher bestimmbar – bitte Symboltyp und Pinbelegung in der Vorlage angeben."
LIBRARY_SWITCHED = ("Bibliothek gewechselt oder geschlossen – Serie abgebrochen. Es wurden keine Bauteile in die "
                    "andere Bibliothek geschrieben; bitte die Serie in der gewünschten Bibliothek neu starten.")
_CHIP_KIND = {"Resistors": "R", "Capacitors": "C", "Inductors": "L", "Ferrite Beads": "FB"}
_GENERATED_TEXTS = ("Value", "Comment", "Description")  # rendered by the category templates
_BOOKKEEPING = ("PF Created", "PF Modified", "PF Author")
_SERIES_LINKS = ("Library Ref", "Footprint Ref")  # always filled by the series (or the row is invalid)
_FIXED_BY_TEMPLATE = (PART_NUMBER.casefold(), MPN_COLUMN.casefold())
_LINKS = (("Library Ref", "Library Path", "Symbol"), ("Footprint Ref", "Footprint Path", "Footprint"))
_LINK_COLUMNS = ("ComponentLink1URL", "ComponentLink1Description")
_LOOKUP_LIMIT = 200  # up to this many part numbers: one query per part number, else one scan of the table
_TARGETED_LIMIT = 20  # up to this many MPN values per category: one query per value, else one scan
_ALL_VALUES = 10**9


class SeriesError(ValueError):
    """The request cannot be processed (German message, API: HTTP 400)."""


# --------------------------------------------------------------------------- request / result models


class SeriesRequest(BaseModel):
    """What to generate. Texts are interpreted like manual input (``1%``, ``±100ppm``, ``10k``)."""

    template_id: str
    sizes: list[str] = Field(default_factory=list,
                             description="Baugrößen: Name, Code der Teilenummer oder metrisch (leer = alle)")
    tolerance: str | None = Field(default=None, description="Toleranz als Wert (1%) oder Code (F); leer = Vorgabe")
    tcr: str | None = Field(default=None, description="Temperaturkoeffizient, z. B. ±100ppm/K (leer = beliebig)")
    e_series: str | list[str] | None = Field(default=None, description="E24, E96, E24+E96 …; leer = laut Datenblatt")
    range_min: str | None = Field(default=None, description="Untere Grenze, z. B. 1Ω oder 10p")
    range_max: str | None = Field(default=None, description="Obere Grenze, z. B. 10M oder 10u")
    values: list[str] = Field(default_factory=list, description="Explizite Werte statt E-Reihe")
    include_jumper: bool = Field(default=False, description="0-Ω-Brücken mit erzeugen")
    voltages: list[str] = Field(default_factory=list, description="Nennspannungen (Kondensatoren), leer = alle")
    dielectrics: list[str] = Field(default_factory=list, description="Dielektrika (leer = alle der Vorlage)")
    packaging: str | None = Field(default=None, description="Verpackungscode (leer = Vorgabe je Baugröße)")
    part_number_scheme: Literal["mpn", "internal"] | None = Field(
        default=None, description="mpn = Teilenummer ist die Hersteller-Teilenummer; leer = Bibliothekseinstellung")
    density: Literal["M", "N", "L"] | None = Field(default=None, description="IPC-Dichte (leer = Hausstil)")
    footprint_height: Literal["standard", "class", "exact"] = Field(
        default="class",
        description="standard = ein Footprint je Baugröße; class = kleinste Standard-Höhenklasse ≥ Bauteilhöhe; "
                    "exact = Footprint mit der Höhe jedes Bauteils",
    )
    field_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Feste Werte für Spalten (auch Library Ref / Footprint Ref: vorhandenes Symbol bzw. Footprint "
                    "statt des erzeugten); Teilenummern kommen immer aus der Vorlage",
    )
    datasheet_url: str | None = Field(default=None, description="Datenblatt-Link (leer = Link der Vorlage)")
    replace_links: bool = Field(
        default=False,
        description="Modus „aktualisieren“: Symbol und Footprint vorhandener Bauteile durch die erzeugten ersetzen "
                    "(sonst bleiben abweichende Verknüpfungen erhalten)",
    )
    max_rows: int = Field(default=DEFAULT_MAX_ROWS, ge=1, le=50000)

    @field_validator("sizes", "values", "voltages", "dielectrics")
    @classmethod
    def _strip(cls, items: list[str]) -> list[str]:
        return [s.strip() for s in items if s and s.strip()]


class FootprintRef(BaseModel):
    name: str
    exists: bool
    family: str
    size: str | None = None
    library: str | None = None
    status: str | None = None
    plain_name: str | None = Field(
        default=None, description="Name ohne Eindeutigkeitskennung (nur wenn der Name eine Kennung „_XXXX“ trägt)")
    name_reason: str | None = Field(
        default=None, description="Warum der reine IPC-/Hausname nicht verwendet wurde (deutsch; nur mit Kennung; "
                                  "in SeriesPreview.footprints/footprints_needed, nicht in jeder Zeile)")


class SymbolRef(BaseModel):
    name: str
    exists: bool
    kind: str | None = None
    library: str | None = None
    status: str | None = None


class PreviewRow(BaseModel):
    part_number: str | None
    mpn: str
    size: str
    value: str
    jumper: bool = False
    values: dict[str, str | None] = Field(default_factory=dict)
    footprint: FootprintRef | None = None
    symbol: SymbolRef | None = None
    status: RowStatus
    messages: list[str] = Field(default_factory=list)


class SeriesPreview(BaseModel):
    template: dict[str, Any]
    table: str
    rows: list[PreviewRow]
    counts: dict[str, int]
    footprints_needed: list[FootprintRef]
    footprints: list[FootprintRef]
    symbol: SymbolRef | None = None
    warnings: list[str] = Field(default_factory=list)
    skipped_by_size: dict[str, int] = Field(
        default_factory=dict,
        description="Ausgelassene Werte je Baugröße (gewählte Reihe/Bereich, laut Datenblatt mit dieser Auswahl nicht "
                    "lieferbar) – keine Zeilen der Vorschau")
    skipped_total: int = Field(default=0, description="Summe von skipped_by_size")
    skipped_reason: str | None = Field(default=None, description="Warum diese Werte ausgelassen wurden (deutsch)")
    duration_s: float = 0.0


class SeriesCommitDetail(BaseModel):
    """Structured progress of the series job (``job.detail``)."""

    phase: CommitPhase | None = Field(
        default=None, description="plan = berechnen, symbol, footprints, backup = Sicherung, parts = Bauteile "
                                  "speichern, done = fertig")
    done: int | None = Field(default=None, description="Erledigte Einheiten der Phase (Footprints, Bauteile)")
    total: int | None = Field(default=None, description="Einheiten der Phase (None = nicht zählbar)")


class LibraryProblem(BaseModel):
    """A symbol or footprint of the series that is not (yet) in its library file."""

    kind: Literal["symbol", "footprint"] = Field(description="Symbol oder Footprint")
    name: str = Field(description="Library Ref bzw. Footprint Ref")
    library: str | None = Field(default=None, description="Bibliotheksdatei (relativ zum Bibliotheksordner)")
    status: Literal["error", "pending", "missing"] = Field(
        description="error = Schreiben fehlgeschlagen (Bauteile damit nicht angelegt), pending = ausstehend "
                    "(Bauteile angelegt, die nächste Synchronisierung schreibt die Datei)")
    message: str = Field(description="Grund (deutsch)")
    parts: int = Field(default=0, description="Zeilen der Serie mit diesem Symbol/Footprint")


class SeriesCommitResult(BaseModel):
    """Result of the series job (``job.result``): what was written and what was not."""

    table: str = Field(description="Kategorietabelle")
    template: str = Field(description="ID der Vorlage")
    rows: int = Field(description="Zeilen der Serie (wie in der Vorschau)")
    created: int = Field(default=0, description="Neu angelegte Bauteile")
    updated: int = Field(default=0, description="Aktualisierte Bauteile (Modus update)")
    unchanged: int = Field(default=0, description="Vorhandene Bauteile ohne Änderung (Modus update)")
    skipped: int = Field(default=0, description="Übersprungene vorhandene Bauteile (Modus skip)")
    errors: int = Field(default=0, description="Beim Speichern abgelehnte Bauteile (Details in error_details)")
    invalid: int = Field(default=0, description="Ungültige Zeilen (nicht geschrieben)")
    conflicts: int = Field(default=0, description="Zeilen mit Konflikt (nicht geschrieben)")
    footprints_created: list[str] = Field(
        default_factory=list, description="Neu angelegte Footprints (in ihre Bibliotheksdatei geschrieben)")
    symbol: str | None = Field(default=None, description="Symbol der Serie")
    symbol_created: bool = Field(default=False, description="Symbol neu angelegt und in die SchLib geschrieben")
    pending: list[str] = Field(default_factory=list,
                               description="Hinweise, wenn Symbol/Footprints nur als „ausstehend“ registriert wurden")
    library_problems: list[LibraryProblem] = Field(
        default_factory=list,
        description="Symbole/Footprints, die nicht in ihre Bibliotheksdatei geschrieben wurden (error/pending)")
    error_details: dict[str, str] = Field(default_factory=dict, description="Teilenummer -> Fehler (höchstens 200)")
    warnings: list[str] = Field(default_factory=list,
                                description="Hinweise der Vorschau und nicht geschriebene Symbole/Footprints")
    created_part_numbers: list[str] = Field(default_factory=list, description="Neue Teilenummern (höchstens 2000)")
    backup: str | None = Field(default=None, description="Dateiname der Sicherung vor dem Schreiben")
    part_warnings: dict[str, list[str]] = Field(
        default_factory=dict, description="Teilenummer -> Hinweise beim Speichern (höchstens 100)")
    message: str = Field(default="", description="Abschlussmeldung (= job.message)")


class RequiredField(BaseModel):
    column: str
    label: str


class SampleCheck(BaseModel):
    """One part of a template as the series would store it (:func:`sample_check`)."""

    values: dict[str, str | None] = Field(default_factory=dict,
                                          description="Werte der Kategoriefelder inkl. erzeugter Texte")
    missing: list[RequiredField] = Field(default_factory=list,
                                         description="Pflichtfelder der Kategorie, die leer bleiben")
    not_applicable: list[str] = Field(default_factory=list,
                                      description="Spalten, die für dieses Bauteil nicht gelten (0-Ω-Brücke)")
    errors: list[str] = Field(default_factory=list, description="Werte, die das Speichern ablehnen würde")
    unknown_columns: list[str] = Field(default_factory=list,
                                       description="Spalten der Vorlage, die es in der Kategorie nicht gibt")


# --------------------------------------------------------------------------- internal structures


@dataclass
class _Candidate:
    size: str
    value: float
    codes: dict[str, str]
    attrs: dict[str, str]
    mpn: str
    ok: bool
    messages: list[str] = field(default_factory=list)
    jumper: bool = False


@dataclass
class _Selection:
    sizes: list[str]
    tolerance: str | None  # code
    tcr_code: str | None
    attr_filters: dict[str, float]
    packaging_var: str | None
    packaging: dict[str, str]  # size -> code (only sizes where the requested code applies)
    voltages: list[str]  # codes (empty = all)
    voltage_values: list[float]  # catalog templates: requested voltages (V)
    explicit: list[tuple[str, float]]  # (input text, value)
    series: list[str]
    low: float | None
    high: float | None
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Plan:
    template: MpnTemplate
    table: str
    ws: Workspace
    rows: list[PreviewRow]
    candidates: list[_Candidate]
    keep: list[set[str]]  # per row: columns an update leaves untouched (status "exists")
    footprint_specs: dict[str, Any]  # name -> FootprintSpec (generated footprints only)
    footprint_refs: dict[str, FootprintRef]
    symbol_spec: Any | None
    symbol_ref: SymbolRef | None
    symbol_kind: str | None
    warnings: list[str]
    scheme: str
    overrides: dict[str, str]
    skipped: _Skipped = field(default_factory=lambda: _Skipped())


@dataclass
class _Skipped:
    """Values of the requested series/range that were left out (no preview row) – per size, with reason."""

    by_size: Counter[str] = field(default_factory=Counter)
    reason_counts: Counter[str] = field(default_factory=Counter)

    def add(self, size: str, reason: str) -> None:
        self.by_size[size] += 1
        self.reason_counts[reason] += 1

    @property
    def total(self) -> int:
        return sum(self.by_size.values())

    def reasons(self) -> str:
        """The reasons in order of frequency, as part of a sentence ("laut Datenblatt …")."""
        return "; ".join(reason for reason, _n in self.reason_counts.most_common())

    def reason_text(self) -> str | None:
        """German explanation for the preview ("Laut Datenblatt nur in anderen Toleranzen lieferbar")."""
        text = self.reasons()
        return text[:1].upper() + text[1:] if text else None


#: Reasons of :class:`_Skipped` (German, part of a sentence)
_SKIP_TOLERANCE = "laut Datenblatt nur in anderen Toleranzen lieferbar"
_SKIP_SELECTION = "laut Datenblatt mit dieser Auswahl nicht lieferbar (Wertebereich, Reihe oder Codes der Baugröße)"
_SKIP_MATRIX = "laut Datenblatt mit dieser Auswahl nicht lieferbar"


@dataclass
class _Stored:
    """Parts already in the library that the series' part numbers / MPNs collide with."""

    used: set[str]  # pn_keys of requested part numbers that exist in any category
    by_pn: dict[str, dict[str, str | None]]  # rows of the target table by pn_key
    by_mpn: dict[str, list[tuple[str, dict[str, str | None]]]]  # compact MPN -> [(table, row)], all categories


# --------------------------------------------------------------------------- request interpretation


def _parse_amount(text: str | None, unit: str, what: str) -> float | None:
    if text is None or not str(text).strip():
        return None
    q = parse_quantity(str(text), unit)
    if q is None and ambiguous_thousands(str(text)):
        raise SeriesError(f"„{text}“ ist mehrdeutig (Komma als Tausendertrennzeichen oder Dezimalkomma?) – bitte für "
                          f"{what} ohne Komma angeben, z. B. 1000 oder 1k.")
    if q is None or (q.unit and q.unit != unit):
        raise SeriesError(f"„{text}“ ist kein gültiger Wert für {what} (Einheit {unit}).")
    if q.value < 0:
        raise SeriesError(f"{what} darf nicht negativ sein.")
    return q.value


def _resolve_sizes(template: MpnTemplate, requested: Sequence[str]) -> list[str]:
    """Size names for the request (name, part-number code, label or metric code – never numeric similarity)."""
    if not requested:
        return template.size_names()
    out: list[str] = []
    for text in requested:
        try:
            size = resolve_size(template, text)
        except MpnError as exc:
            raise SeriesError(str(exc)) from exc
        if size not in out:
            out.append(size)
    return out


def _selection(template: MpnTemplate, req: SeriesRequest) -> _Selection:
    ct = compile_template(template)
    sizes = _resolve_sizes(template, req.sizes)
    warnings: list[str] = []
    unit = template.value_unit

    tolerance: str | None = None
    tol_var = ct.variables.get("tolerance")
    if tol_var is not None:
        if req.tolerance:
            option = find_option(tol_var, req.tolerance)
            if option is None:
                choices = ", ".join(o.value or o.code for o in tol_var.options if not o.attrs.get("jumper_only"))
                raise SeriesError(f"Toleranz „{req.tolerance}“ gibt es in dieser Serie nicht (möglich: {choices}).")
            if option.attrs.get("jumper_only"):
                raise SeriesError(f"„{option.code}“ ist der Code der 0-Ω-Brücke – bitte „Brücken einschließen“ wählen.")
            tolerance = option.code
        elif template.kind != "catalog":
            default = next((o for o in tol_var.options if o.default and not o.attrs.get("jumper_only")), None) or \
                next((o for o in tol_var.options if not o.attrs.get("jumper_only")), None)
            tolerance = default.code if default else None
    elif req.tolerance and template.kind != "catalog":
        warnings.append("Die Vorlage kennt keine Toleranz-Codes – die Angabe wird ignoriert.")

    tcr_code: str | None = None
    attr_filters: dict[str, float] = {}
    if req.tcr:
        tcr_var = ct.variables.get("tcr")
        if tcr_var is not None:
            option = find_option(tcr_var, req.tcr)
            if option is None or option.attrs.get("jumper_only"):
                raise SeriesError(f"Temperaturkoeffizient „{req.tcr}“ gibt es in dieser Serie nicht.")
            tcr_code = option.code
        else:
            q = parse_quantity(req.tcr.replace("±", ""), "ppm/K")
            if q is None:
                raise SeriesError(f"„{req.tcr}“ ist kein gültiger Temperaturkoeffizient (z. B. ±100ppm/K).")
            attr_filters["tcr"] = q.value

    packaging: dict[str, str] = {}
    pack_name = _packaging_var(template)
    if req.packaging:
        if pack_name is None:
            raise SeriesError("Diese Serie hat keinen Verpackungscode.")
        pack_var = ct.variables[pack_name]
        missing = []
        for size in sizes:
            option = find_option(pack_var, req.packaging, size)
            if option is not None and option.applies_to(size):
                packaging[size] = option.code
            else:
                missing.append(size)
        if len(missing) == len(sizes):
            raise SeriesError(f"Verpackung „{req.packaging}“ gibt es für die gewählten Baugrößen nicht.")
        if missing:
            warnings.append(f"Verpackung „{req.packaging}“ gibt es nicht für {', '.join(missing)} – "
                            "dort wird die Standardverpackung verwendet.")

    voltages: list[str] = []
    voltage_values: list[float] = []
    if req.voltages:
        volt_var = ct.variables.get("voltage")
        if volt_var is None and template.kind != "catalog":
            raise SeriesError("Diese Serie hat keine Spannungsauswahl.")
        for text in req.voltages:
            if volt_var is None:
                q = parse_quantity(text, "V")
                if q is None or (q.unit and q.unit != "V"):
                    raise SeriesError(f"„{text}“ ist keine gültige Spannung (z. B. 50V).")
                voltage_values.append(q.value)
                continue
            option = find_option(volt_var, text)
            if option is None:
                choices = ", ".join(o.value or o.code for o in volt_var.options)
                raise SeriesError(f"Nennspannung „{text}“ gibt es in dieser Serie nicht (möglich: {choices}).")
            if option.code not in voltages:
                voltages.append(option.code)

    if req.dielectrics:
        diel_var = ct.variables.get("dielectric")
        if diel_var is not None:
            offered = [o.value or o.code for o in diel_var.options]
        else:
            offered = sorted({e.attrs.get("dielectric", "") for e in template.catalog} - {""}) or \
                ([template.attrs["dielectric"]] if template.attrs.get("dielectric") else [])
        wanted = {d.casefold().replace(" ", "") for d in req.dielectrics}
        if not any(o.casefold().replace(" ", "") in wanted for o in offered):
            raise SeriesError(f"Dielektrikum {', '.join(req.dielectrics)} gibt es in dieser Serie nicht "
                              f"(nur {', '.join(offered) or '–'}).")

    explicit: list[tuple[str, float]] = []
    for text in req.values:
        q = parse_quantity(text, unit)
        if q is None or (q.unit and q.unit != unit) or q.value < 0:
            raise SeriesError(f"„{text}“ ist kein gültiger Wert (Einheit {unit}).")
        explicit.append((text, q.value))

    try:
        series = parse_series(req.e_series) if req.e_series else []
    except MpnError as exc:
        raise SeriesError(str(exc)) from exc
    if not series and tol_var is not None and tolerance:
        option = tol_var.option(tolerance)
        if option is not None and option.attrs.get("eseries"):
            series = parse_series(option.attrs["eseries"])
    low = _parse_amount(req.range_min, unit, "die untere Grenze")
    high = _parse_amount(req.range_max, unit, "die obere Grenze")
    if low is not None and high is not None and high < low:
        raise SeriesError("Die obere Grenze ist kleiner als die untere.")
    return _Selection(sizes=sizes, tolerance=tolerance, tcr_code=tcr_code, attr_filters=attr_filters,
                      packaging_var=pack_name, packaging=packaging, voltages=voltages, voltage_values=voltage_values,
                      explicit=explicit, series=series, low=low, high=high, warnings=warnings)


# --------------------------------------------------------------------------- candidate generation


def _in_range(value: float, low: float | None, high: float | None) -> bool:
    if low is not None and value < low * (1 - 1e-9):
        return False
    return not (high is not None and value > high * (1 + 1e-9))


def _rule_span(template: MpnTemplate, size: str) -> tuple[float, float] | None:
    ct = compile_template(template)
    spans = [(lo, hi) for r in ct.rules if not r.sizes or size in r.sizes for lo, hi in r.ranges]
    if not spans:
        return None
    return min(lo for lo, _ in spans), max(hi for _, hi in spans)


def _fixed_codes(sel: _Selection, size: str) -> dict[str, str]:
    """Codes the user chose (tolerance, TCR, packaging of this size)."""
    fixed: dict[str, str] = {}
    if sel.tolerance:
        fixed["tolerance"] = sel.tolerance
    if sel.tcr_code:
        fixed["tcr"] = sel.tcr_code
    if sel.packaging_var and size in sel.packaging:
        fixed[sel.packaging_var] = sel.packaging[size]
    return fixed


def _packaging_var(template: MpnTemplate) -> str | None:
    ct = compile_template(template)
    for name in ("packaging", "cspec", "packing"):
        if name in ct.variables:
            return name
    return None


def _make_candidate(template: MpnTemplate, size: str, value: float, res: Resolution, *, jumper: bool = False,
                    mpn: str | None = None) -> _Candidate:
    messages = list(res.messages)
    if mpn is None:
        try:
            mpn = encode_mpn(template, size=size, value=value, codes=res.codes, jumper=jumper)
        except MpnError as exc:
            return _Candidate(size, value, res.codes, res.attrs, f"({format_value(value, template.value_unit)})",
                              False, [*messages, str(exc)], jumper)
    note = res.attrs.get("row_note")
    if note:
        messages.append(note)
    if res.ok and not template.availability_certain:
        messages.append("Lieferbarkeit nicht geprüft – Teilenummer bitte beim Hersteller oder Distributor prüfen.")
    attrs = {**res.attrs, **base_attrs(template, size, value, mpn)}
    return _Candidate(size, value, dict(res.codes), attrs, mpn, res.ok, messages, jumper)


def _rule_candidates(template: MpnTemplate, sel: _Selection, req: SeriesRequest,
                     skipped: _Skipped) -> list[_Candidate]:
    out: list[_Candidate] = []
    for size in sel.sizes:
        fixed = _fixed_codes(sel, size)
        if sel.explicit:
            for text, value in sel.explicit:
                if value == 0:
                    if template.jumper is not None:
                        res = resolve(template, size=size, value=0.0, fixed=fixed, jumper=True)
                        out.append(_make_candidate(template, size, 0.0, res, jumper=True))
                    else:
                        res = Resolution(False, dict(fixed), {}, ["Diese Serie hat keine 0-Ω-Brücke."])
                        out.append(_make_candidate(template, size, 0.0, res, mpn=f"({text})"))
                    continue
                res = resolve(template, size=size, value=value, fixed=fixed, attr_filters=sel.attr_filters)
                if not res.ok and sel.series and not in_series(value, sel.series):
                    res.messages.append(f"{format_value(value, template.value_unit)} gehört nicht zur Reihe "
                                        f"{' / '.join(sel.series)}.")
                out.append(_make_candidate(template, size, value, res))
        else:
            span = _rule_span(template, size)
            if span is None and (sel.low is None or sel.high is None):
                raise SeriesError("Für diese Vorlage bitte Unter- und Obergrenze oder einzelne Werte angeben.")
            low = sel.low if sel.low is not None else span[0]  # type: ignore[index]
            high = sel.high if sel.high is not None else span[1]  # type: ignore[index]
            series = sel.series or ["E24"]
            values: set[float] = set()
            for name in series:
                values.update(values_in_range(name, max(low, 1e-12), high) if high > 0 else [])
            for value in sorted(values):
                res = resolve(template, size=size, value=value, fixed=fixed, attr_filters=sel.attr_filters)
                if res.ok:
                    out.append(_make_candidate(template, size, value, res))
                else:
                    skipped.add(size, _SKIP_SELECTION)
        if req.include_jumper:
            if template.jumper is None:
                continue
            if template.jumper.sizes and size not in template.jumper.sizes:
                continue
            jfixed = {k: v for k, v in fixed.items() if k not in ("tolerance", "tcr")}
            res = resolve(template, size=size, value=0.0, fixed=jfixed, jumper=True)
            if not any(c.jumper and c.size == size for c in out):
                out.append(_make_candidate(template, size, 0.0, res, jumper=True))
    return out


def _substitute_packaging(template: MpnTemplate, sel: _Selection, size: str, cell: AvailabilityCell,
                          fixed: dict[str, str], substituted: Counter[str]) -> list[str]:
    """Replace a requested reel that does not fit this cell (tape type by thickness, laser marking by
    capacitance) by the equivalent one (same reel size) – German row notes."""
    pack_var = sel.packaging_var
    if not pack_var or size not in sel.packaging or pack_var not in fixed:
        return []
    ct = compile_template(template)
    var = ct.variables[pack_var]
    option = var.option(fixed[pack_var], size)
    context = {**ct.size_attrs(size), **cell.attrs, **cell.codes, **fixed}
    if option is None or option.satisfied_by(context):
        return []
    substitute = equivalent_option(var, option, size, context)
    if substitute is None:
        fixed.pop(pack_var)
        return []
    fixed[pack_var] = substitute.code
    substituted[option.code] += 1
    return [f"{var.label} „{option.code}“ gibt es für dieses Bauteil nicht – „{substitute.code or 'ohne'}“ "
            f"verwendet ({substitute.label or substitute.code})."]


def _matrix_candidates(template: MpnTemplate, sel: _Selection, skipped: _Skipped,
                       substituted: Counter[str]) -> list[_Candidate]:
    ct = compile_template(template)
    out: list[_Candidate] = []
    keys = template.availability_keys
    for size in sel.sizes:
        cells: list[AvailabilityCell] = ct.cells_by_size.get(size, [])
        fixed_base = _fixed_codes(sel, size)
        found_explicit: set[int] = set()
        for cell in cells:
            if sel.voltages and cell.codes.get("voltage", "") not in sel.voltages:
                continue
            value = ct.cell_value(cell)
            if sel.explicit:
                hit = next((i for i, (_t, v) in enumerate(sel.explicit) if math.isclose(v, value, rel_tol=1e-9)), None)
                if hit is None:
                    continue
                found_explicit.add(hit)
            else:
                if not _in_range(value, sel.low, sel.high):
                    continue
                if sel.series and not in_series(value, sel.series):
                    continue
            fixed = {**fixed_base, **{k: cell.codes[k] for k in keys if k in cell.codes}}
            notes = _substitute_packaging(template, sel, size, cell, fixed, substituted)
            res = resolve(template, size=size, value=value, fixed=fixed)
            res.messages.extend(notes)
            if res.ok or sel.explicit:
                out.append(_make_candidate(template, size, value, res))
            else:
                tolerance = str(res.codes.get("tolerance") or "").upper()
                other_tolerance = bool(cell.tolerances) and bool(tolerance) and \
                    tolerance not in {t.upper() for t in cell.tolerances}
                skipped.add(size, _SKIP_TOLERANCE if other_tolerance else _SKIP_MATRIX)
        if sel.explicit:
            for i, (_text, value) in enumerate(sel.explicit):
                if i in found_explicit:
                    continue
                fixed = dict(fixed_base)
                if sel.voltages:
                    fixed["voltage"] = sel.voltages[0]
                res = resolve(template, size=size, value=value, fixed=fixed)
                res.ok = False
                if not res.messages:
                    res.messages.append("Laut Datenblatt nicht lieferbar.")
                candidate = _make_candidate(template, size, value, res)
                candidate.ok = False
                out.append(candidate)
    return out


def _catalog_candidates(template: MpnTemplate, sel: _Selection,
                        req: SeriesRequest) -> tuple[list[_Candidate], list[str]]:
    out: list[_Candidate] = []
    warnings: list[str] = []
    tol_var = compile_template(template).variables.get("tolerance")
    wanted_tol = None
    if req.tolerance:
        if tol_var is not None:
            option = find_option(tol_var, req.tolerance)
            wanted_tol = option.value if option is not None else req.tolerance
        else:
            wanted_tol = req.tolerance
    matched_explicit: set[int] = set()
    for entry in template.catalog:
        if entry.size not in sel.sizes:
            continue
        value, attrs = catalog_attrs(template, entry)
        if value is None:
            continue
        if wanted_tol is not None:
            have = attrs.get("tolerance", "")
            if _norm_tol(have) != _norm_tol(wanted_tol):
                continue
        if sel.voltage_values:
            vq = parse_quantity(attrs.get("voltage", ""), "V")
            if vq is None or not any(math.isclose(vq.value, w, rel_tol=1e-6) for w in sel.voltage_values):
                continue
        if sel.explicit:
            hit = next((i for i, (_t, v) in enumerate(sel.explicit) if math.isclose(v, value, rel_tol=1e-9)), None)
            if hit is None:
                continue
            matched_explicit.add(hit)
        else:
            if not _in_range(value, sel.low, sel.high):
                continue
            if req.e_series and not in_series(value, sel.series):
                continue
        messages = []
        if not template.verified:
            messages.append("Vorlage nicht gegen das Datenblatt geprüft – Werte vor der Freigabe kontrollieren.")
        if attrs.get("row_note"):
            messages.append(attrs["row_note"])
        out.append(_Candidate(entry.size, value, dict(entry.codes), attrs, entry.mpn, True, messages))
    for i, (text, _value) in enumerate(sel.explicit):
        if i not in matched_explicit:
            warnings.append(f"Wert „{text}“ gibt es im Katalog der Serie {template.series} nicht.")
    return out, warnings


def _norm_tol(text: str) -> str:
    return text.replace("±", "").replace(" ", "").replace("%", "").strip()


def _count(n: int) -> str:
    """German number with thousands dots ("1.248")."""
    return f"{n:,}".replace(",", ".")


def _candidates(template: MpnTemplate, sel: _Selection,
                req: SeriesRequest) -> tuple[list[_Candidate], list[str], _Skipped]:
    skipped = _Skipped()
    substituted: Counter[str] = Counter()
    warnings: list[str] = []
    if template.kind == "catalog":
        candidates, warnings = _catalog_candidates(template, sel, req)
    elif template.availability:
        candidates = _matrix_candidates(template, sel, skipped, substituted)
    elif template.rules or sel.explicit or (sel.low is not None and sel.high is not None):
        candidates = _rule_candidates(template, sel, req, skipped)
        if not template.rules:
            warnings.append("Die Vorlage hat keine Wertebereiche – die Lieferbarkeit der Werte ist nicht geprüft.")
    else:
        raise SeriesError("Für diese Vorlage bitte Unter- und Obergrenze oder einzelne Werte angeben.")
    if req.include_jumper and template.jumper is None and template.kind != "catalog":
        warnings.append("Diese Serie hat keine 0-Ω-Brücken.")
    for code, count in substituted.items():
        warnings.append(f"Verpackung „{code}“ passt nicht zu {plural(count, 'Bauteil', 'Bauteilen')} (Gurtart nach "
                        "Dicke bzw. Laserbeschriftung) – dort wird die gleichwertige Verpackung verwendet (Hinweis je "
                        "Zeile).")
    if skipped.total:
        detail = ", ".join(f"{size}: {_count(n)}" for size, n in skipped.by_size.items())
        warnings.append(f"{plural(skipped.total, 'Wert', 'Werte')} ausgelassen ({detail}) – {skipped.reasons()}.")
    return candidates, warnings, skipped


# --------------------------------------------------------------------------- footprints & symbol


def _footprint_hint(template: MpnTemplate, size: str) -> FootprintHint:
    spec = template.size_spec(size)
    if spec is not None and spec.footprint is not None:
        return spec.footprint
    return template.footprint


@dataclass
class _FpOrigin:
    """How a footprint request was built – the reason when the name gets a uniqueness tag."""

    land_pattern: bool = False  # manufacturer land pattern (datasheet) instead of IPC-7351B
    custom: dict[str, Any] | None = None  # body dimensions of the template (size without standard table)
    height: dict[str, float] | None = None  # height range from the part's datasheet thickness
    exact: bool = False  # footprint height "exact" (else: no standard height class fits)
    standard_max: float | None = None  # highest standard height class of the size (mm)


@dataclass
class _FootprintCache:
    density: str | None
    height_mode: str
    specs: dict[str, Any] = field(default_factory=dict)  # request key -> FootprintSpec | error text
    classes: dict[tuple[str, str], list[dict[str, float]]] = field(default_factory=dict)
    reasons: dict[str, tuple[str, str]] = field(default_factory=dict)  # tagged name -> (plain name, reason)

    def height_classes(self, kind: str, size: str) -> list[dict[str, float]]:
        key = (kind, size)
        if key not in self.classes:
            from ..footprints import presets

            found = [dict(p.params["H"]) for p in presets("chip")
                     if p.params.get("kind") == kind and p.params.get("size") == size
                     and isinstance(p.params.get("H"), dict)]
            self.classes[key] = found
        return self.classes[key]


def _part_height(attrs: Mapping[str, str]) -> tuple[float, float] | None:
    try:
        return float(attrs["thickness_nom"]), float(attrs["thickness_tol"])
    except (KeyError, ValueError):
        return None


def _footprint_request(template: MpnTemplate, size: str, attrs: Mapping[str, str],
                       cache: _FootprintCache) -> tuple[Any, _FpOrigin]:
    from ..footprints import chip_request
    from ..footprints.models import FootprintRequest

    hint = _footprint_hint(template, size)
    kind = hint.kind or template.footprint.kind or _CHIP_KIND.get(template.category)
    params = dict(hint.params)
    origin = _FpOrigin()
    if hint.family == "chip" and not params.get("L"):
        if kind is None:
            raise SeriesError(f"Für {template.category} ist keine Chip-Bauteilart bekannt – "
                              "bitte in der Vorlage angeben.")
        req = chip_request(kind, hint.size or size, density=cache.density)
        height = _part_height(attrs)
        if height is not None and cache.height_mode != "standard":
            nominal, tol = height
            exact = {"min": round(nominal - tol, 4), "nom": nominal, "max": round(nominal + tol, 4)}
            classes = cache.height_classes(kind, str(req.params["size"]))
            origin.standard_max = max((c.get("max", 0.0) for c in classes), default=None)
            if cache.height_mode == "exact":
                req.params["H"] = exact
                origin.height = exact
                origin.exact = True
            else:
                fitting = sorted((c for c in classes if c.get("max", 0) >= exact["max"] - 1e-6),
                                 key=lambda c: c.get("max", 0))
                if not fitting:
                    req.params["H"] = exact
                    origin.height = exact
                elif classes and fitting[0] != classes[0]:
                    req.params["H"] = fitting[0]
        return req, origin
    if kind is not None and "kind" not in params:
        params["kind"] = kind
    origin.custom = dict(hint.params) or None
    height = _part_height(attrs)
    if height is not None and cache.height_mode != "standard" and hint.family == "chip":
        nominal, tol = height
        params["H"] = {"min": round(nominal - tol, 4), "nom": nominal, "max": round(nominal + tol, 4)}
    data: dict[str, Any] = {"family": hint.family, "params": params}
    if hint.land_pattern:
        data["land_pattern"] = hint.land_pattern
        origin.land_pattern = True
    if cache.density:
        data["density"] = cache.density
    return FootprintRequest.model_validate(data), origin


def _mm_text(value: float) -> str:
    return f"{round(float(value), 3):g}".replace(".", ",")


def _dimension_text(params: Mapping[str, Any]) -> str:
    """"L 3–3,3 mm, B 4,45–4,75 mm" from tolerance dicts of the body dimensions."""
    labels = {"L": "L", "W": "B", "T": "Anschlusslänge", "H": "H"}
    parts = []
    for key, label in labels.items():
        value = params.get(key)
        if isinstance(value, Mapping) and "min" in value and "max" in value:
            parts.append(f"{label} {_mm_text(value['min'])}–{_mm_text(value['max'])} mm")
    return ", ".join(parts)


def _name_reason(spec: Any, origin: _FpOrigin, size: str) -> tuple[str, str] | None:
    """(plain name, German reason) when the footprint name carries a uniqueness tag (``…_4328``)."""
    generator = spec.generator or {}
    tag = generator.get("name_tag")
    if not tag or not str(spec.name).endswith(f"_{tag}"):
        return None
    plain = str(spec.name)[: -len(tag) - 1]
    marker = f"„_{tag}“"
    if origin.land_pattern:
        reason = (f"Land Pattern nach Herstellerempfehlung im Datenblatt statt IPC-7351B-Berechnung – der reine Name "
                  f"„{plain}“ steht für das berechnete Land Pattern, daher die Kennung {marker}.")
    elif origin.custom:
        dims = _dimension_text(origin.custom)
        reason = (f"Gehäusemaße laut Datenblatt{f' ({dims})' if dims else ''} – für Baugröße {size} hat der "
                  f"Footprint-Generator keine Standardmaße, daher die Kennung {marker} (der reine Name „{plain}“ "
                  "bleibt Footprints mit Standardmaßen vorbehalten).")
    elif origin.height is not None:
        height = (f"{_mm_text(origin.height['nom'])} ± {_mm_text(origin.height['max'] - origin.height['nom'])} mm"
                  if "nom" in origin.height else f"bis {_mm_text(origin.height['max'])} mm")
        if origin.exact:
            reason = (f"Footprint-Höhe „Exakt“: Bauteilhöhe laut Datenblatt {height} statt einer Standardhöhe der "
                      f"Baugröße {size} – daher ein eigener Footprint mit der Kennung {marker} (ein Name steht immer "
                      "für genau ein Land Pattern). „Höhenklassen“ oder „Je Baugröße“ verwenden Standard-Footprints.")
        else:
            standard = (f" (höchste: {_mm_text(origin.standard_max)} mm)" if origin.standard_max else "")
            reason = (f"Bauteilhöhe laut Datenblatt {height}: für Baugröße {size} deckt keine Standard-Höhenklasse "
                      f"diese Höhe ab{standard} – daher ein eigener Footprint mit der Kennung {marker} (ein Name "
                      "steht immer für genau ein Land Pattern). Footprint-Höhe „Je Baugröße“ verwendet stattdessen "
                      "den Standard-Footprint der Baugröße.")
    else:
        reason = (f"Maße weichen von den Standardmaßen der Baugröße {size} ab – die Kennung {marker} hält den Namen "
                  "eindeutig (ein Name steht immer für genau ein Land Pattern).")
    return plain, reason


def _footprint_for(template: MpnTemplate, size: str, attrs: Mapping[str, str], cache: _FootprintCache) -> Any:
    """FootprintSpec for a row (cached per request); raises SeriesError with a German message.
    A tagged name's reason lands in ``cache.reasons``."""
    from ..footprints import generate

    try:
        request, origin = _footprint_request(template, size, attrs, cache)
    except ValueError as exc:
        raise SeriesError(f"Footprint: {exc}") from exc
    key = json.dumps(request.model_dump(mode="json"), sort_keys=True)
    cached = cache.specs.get(key)
    if cached is None:
        try:
            cached = generate(request)
        except ValueError as exc:
            cached = f"Footprint kann nicht erzeugt werden: {exc}"
        cache.specs[key] = cached
        if not isinstance(cached, str) and cached.name not in cache.reasons:
            reason = _name_reason(cached, origin, size)
            if reason is not None:
                cache.reasons[cached.name] = reason
    if isinstance(cached, str):
        raise SeriesError(cached)
    return cached


@functools.cache
def _symbol_kinds() -> tuple[frozenset[str], frozenset[str]]:
    """(all symbol kinds, kinds whose pin assignment is a parameter – diode, LED, transistors …)."""
    from ..symbols import kinds

    infos = kinds()
    return (frozenset(info.key for info in infos),
            frozenset(info.key for info in infos if any(p.name == "pinmap" for p in info.params)))


def _symbol_for(template: MpnTemplate, cat: Any, sample: Mapping[str, Any],
                footprint: Any) -> tuple[Any | None, str | None, str | None]:
    """(SymbolSpec | None, kind, German problem) for the series – a pin-out is never guessed.

    1. ``template.symbol_kind``: generated with ``template.symbol_params``; a kind with a pin map
       needs ``symbol_params["pinmap"]`` or a pin map that the symbol mapping derives safely from
       the values/footprint (:func:`partforge.symbols.suggest_symbol`).
    2. Otherwise :func:`partforge.db.templates.resolve_default_symbol` – the category default kind
       only where it has no pin map (custom categories), never as a pin-out guess."""
    from ..db.templates import resolve_default_symbol
    from ..symbols import SymbolError, generate, suggest_symbol
    from ..symbols.models import SymbolRequest

    known, with_pinmap = _symbol_kinds()
    values = {k: v for k, v in sample.items() if v is not None}
    if template.symbol_kind:
        kind = template.symbol_kind
        if kind not in known:
            return None, kind, f"Symboltyp „{kind}“ der Vorlage ist unbekannt."
        params = dict(template.symbol_params)
        request = SymbolRequest(kind=kind, params=params)
        if kind in with_pinmap and "pinmap" not in params:
            try:
                suggestion = suggest_symbol(cat.table, values, footprint=footprint)
            except Exception:  # noqa: BLE001 - a mapping problem means: not certain
                log.warning("Symbolvorschlag für %s nicht bestimmbar", cat.table, exc_info=True)
                suggestion = None
            if suggestion is None or suggestion.request is None or suggestion.request.kind != kind:
                return None, kind, NO_SAFE_SYMBOL
            request = suggestion.request.model_copy(update={"params": {**suggestion.request.params, **params}})
        try:
            return generate(request), kind, None
        except SymbolError as exc:
            return None, kind, f"Symbol „{kind}“ der Vorlage ist nicht erzeugbar: {exc}"
    try:
        default = resolve_default_symbol(cat, values, footprint=footprint)
    except Exception:  # noqa: BLE001 - mapping problems must not break the preview
        log.warning("Standardsymbol für %s nicht bestimmbar", cat.table, exc_info=True)
        default = None
    if default is None:
        return None, None, NO_SAFE_SYMBOL
    if default.source == "category" and default.kind in with_pinmap:
        return None, default.kind, NO_SAFE_SYMBOL
    return default.spec, default.kind, None


# --------------------------------------------------------------------------- rows


def _row_values(template: MpnTemplate, candidate: _Candidate, overrides: Mapping[str, str],
                datasheet: str | None) -> dict[str, str]:
    """Column texts of a row. ``datasheet``: the requested link; else a catalog entry's own link
    (attribute ``datasheet_url``, e.g. the manufacturer's page of that part), else the template's."""
    values = render_fields(template.fields, candidate.attrs)
    values["Manufacturer"] = template.manufacturer
    values[MPN_COLUMN] = candidate.mpn
    datasheet = datasheet or candidate.attrs.get("datasheet_url") or template.datasheet_url
    if datasheet:
        values["ComponentLink1Description"] = LINK_DESCRIPTION
        values["ComponentLink1URL"] = datasheet
    values["Lifecycle"] = candidate.attrs.get("lifecycle") or DEFAULT_LIFECYCLE
    values["PF Status"] = DEFAULT_PF_STATUS
    values.update(overrides)
    # Altium stores free text unescaped: no '|' / control characters may reach a library
    cleaned = {column: clean_free_text(text) for column, text in values.items()}
    return {column: text for column, text in cleaned.items() if text}


class _Normalizer:
    """``db.values.normalize_cell`` for the category fields, memoised per (column, text): series rows
    share most of their texts (size, power, temperature …), so each distinct value is parsed once."""

    def __init__(self, cat: Any, ws_root: Any):
        self.fields = {f.column.casefold(): f for f in cat.fields}
        self.ws_root = ws_root
        self._cache: dict[tuple[str, str], tuple[str | None, str | None]] = {}

    def row(self, values: Mapping[str, str]) -> tuple[dict[str, str | None], list[str], list[str]]:
        """(normalised values, unknown columns, German errors as ``db.parts`` would report them)."""
        from ..db.values import normalize_cell

        out: dict[str, str | None] = {}
        unknown: list[str] = []
        errors: list[str] = []
        for column, raw in values.items():
            f = self.fields.get(column.casefold())
            if f is None:
                unknown.append(column)
                continue
            key = (f.column, raw)
            if key not in self._cache:
                result = normalize_cell(f, raw, ws_root=self.ws_root)
                self._cache[key] = (result.value, result.error)
            value, error = self._cache[key]
            out[f.column] = value
            if error:
                errors.append(f"{f.label}: {error}")
        return out, unknown, errors


class _TextRenderer:
    """Value/Comment/Description exactly as ``db.parts`` renders them for a new part (category
    templates via ``db.values.render_template``) – built once per preview instead of per row."""

    def __init__(self, cat: Any):
        self.fields = {f.column: f for f in cat.fields}
        self.templates = {
            "Value": f"{{{cat.value_field}}}" if cat.value_field else "",
            "Comment": cat.comment_template or "",
            "Description": cat.description_template or "",
        }

    def fill(self, values: dict[str, str | None]) -> None:
        from ..db.values import render_template

        row: dict[str, Any] = {column: None for column in self.fields}
        row.update(values)
        for column in _GENERATED_TEXTS:
            if column not in self.fields or not self.templates.get(column) or row.get(column):
                continue
            rendered = render_template(self.templates[column], row, self.fields) or None
            row[column] = rendered
            if rendered:
                values[column] = rendered


def _missing_required(cat: Any, values: Mapping[str, str | None], *, scheme: str) -> list[Any]:
    """Required fields (FieldDef) that stay empty – the check ``db.parts`` makes when saving, without
    the fields that do not apply to the row (0-Ω jumper: tolerance, TCR, power, voltage)."""
    from ..db.values import not_applicable

    exempt = not_applicable(cat, values)
    missing = []
    for f in cat.fields:
        if not f.required or f.column in _BOOKKEEPING or values.get(f.column) or f.column in exempt:
            continue
        if f.column == PART_NUMBER and scheme == "internal":
            continue  # assigned when saving
        missing.append(f)
    return missing


def _rows_by_part_number(table: str, pns: Sequence[str]) -> tuple[set[str], dict[str, dict[str, str | None]]]:
    """(pn_keys of ``pns`` used in any category, this table's rows by pn_key)."""
    from ..db import parts

    used = parts.existing_part_numbers(pns)
    keys = {parts.pn_key(p) for p in used}
    matched: dict[str, dict[str, str | None]] = {}
    if len(used) <= _LOOKUP_LIMIT:
        for pn in used:
            row = parts.get_part(table, pn)
            if row is not None:
                matched[parts.pn_key(str(row[PART_NUMBER]))] = row
    else:
        rows, _total = parts.query_parts(table, limit=0)
        matched = {parts.pn_key(str(r[PART_NUMBER])): r for r in rows
                   if r.get(PART_NUMBER) and parts.pn_key(str(r[PART_NUMBER])) in keys}
    return keys, matched


def _rows_with_mpn(table: str, stored_values: Sequence[str]) -> list[dict[str, str | None]]:
    """Rows of ``table`` whose Manufacturer Part Number is one of the stored spellings."""
    from ..db import parts
    from ..db.models import PartFilter

    if len(stored_values) <= _TARGETED_LIMIT:
        rows: list[dict[str, str | None]] = []
        for value in stored_values:
            found, _total = parts.query_parts(table, filters=[PartFilter(column=MPN_COLUMN, op="eq", value=value)],
                                              limit=0)
            rows.extend(found)
        return rows
    wanted = set(stored_values)
    rows, _total = parts.query_parts(table, limit=0)
    return [r for r in rows if r.get(MPN_COLUMN) in wanted]


def _stored_parts(table: str, pns: Sequence[str], mpns: Sequence[str]) -> _Stored:
    """Existing parts by part number (``pns``, any category) and by manufacturer part number (``mpns``,
    compared in compact form – ``ERJ3EKF1002V`` is ``ERJ-3EKF1002V`` – in every category)."""
    from ..db import categories, parts

    used, by_pn = _rows_by_part_number(table, pns) if pns else (set(), {})
    wanted = {compact(m) for m in mpns if m}
    by_mpn: dict[str, list[tuple[str, dict[str, str | None]]]] = {}
    if not wanted:
        return _Stored(used, by_pn, by_mpn)
    seen: set[tuple[str, str]] = set()
    known_values: Counter[str] = Counter()  # stored MPN spellings already explained by the part-number lookup

    def add(owner: str, row: dict[str, str | None]) -> None:
        key = compact(str(row.get(MPN_COLUMN) or ""))
        ident = (owner.casefold(), parts.pn_key(str(row.get(PART_NUMBER) or "")))
        if key in wanted and ident not in seen:
            seen.add(ident)
            by_mpn.setdefault(key, []).append((owner, row))

    for row in by_pn.values():
        add(table, row)
        if row.get(MPN_COLUMN):
            known_values[str(row[MPN_COLUMN])] += 1
    for cat in categories.list_categories(with_counts=False):
        if cat.field(MPN_COLUMN) is None:
            continue
        same_table = cat.table.casefold() == table.casefold()
        unexplained = [item["value"] for item in parts.distinct_values(cat.table, MPN_COLUMN, limit=_ALL_VALUES)
                       if compact(item["value"]) in wanted
                       and item["count"] > (known_values[item["value"]] if same_table else 0)]
        for row in _rows_with_mpn(cat.table, unexplained) if unexplained else []:
            add(cat.table, row)
    return _Stored(used, by_pn, by_mpn)


def _classify(candidate: _Candidate, table: str, scheme: str,
              stored: _Stored) -> tuple[RowStatus, str | None, dict[str, str | None] | None, list[str]]:
    """(status, part number, stored row of an existing part, German messages) of an orderable row."""
    from ..db import parts

    mpn_key = compact(candidate.mpn)
    owners = stored.by_mpn.get(mpn_key, [])
    same = [row for owner, row in owners if owner.casefold() == table.casefold()]
    other = [(owner, row) for owner, row in owners if owner.casefold() != table.casefold()]
    if scheme == "mpn":
        current = stored.by_pn.get(parts.pn_key(candidate.mpn))
        if current is not None:
            stored_mpn = str(current.get(MPN_COLUMN) or "")
            if not stored_mpn or compact(stored_mpn) == mpn_key:
                return "exists", str(current[PART_NUMBER]), current, []
            return "conflict", candidate.mpn, None, [
                f"Die Teilenummer ist bereits für ein anderes Bauteil vergeben (Hersteller-Teilenummer „{stored_mpn}“)."]
        if parts.pn_key(candidate.mpn) in stored.used:
            return "conflict", candidate.mpn, None, ["Die Teilenummer ist bereits in einer anderen Kategorie vergeben."]
    if same:
        row = same[0]
        pn = str(row[PART_NUMBER])
        messages = [] if scheme == "internal" else [f"Vorhanden als „{pn}“ (gleiche Hersteller-Teilenummer)."]
        return "exists", pn, row, messages
    if other:
        owner, row = other[0]
        return "conflict", candidate.mpn if scheme == "mpn" else None, None, [
            f"Die Hersteller-Teilenummer ist bereits als „{row.get(PART_NUMBER)}“ in „{owner}“ vergeben."]
    return "new", candidate.mpn if scheme == "mpn" else None, None, []


def _kept_on_update(values: Mapping[str, str | None], current: Mapping[str, str | None], *, explicit: set[str],
                    replace_links: bool, template_lifecycle: bool) -> tuple[set[str], list[str]]:
    """(columns an update must leave untouched, German notes) for an existing part.

    The release workflow (PF Status) is never changed by a series; a lifecycle, datasheet link,
    symbol or footprint the user set differently stays unless it is given explicitly
    (``explicit`` = casefolded column names) or ``replace_links``. A lifecycle from the template
    (e.g. NRND) replaces only the series default "Aktiv"."""
    keep: set[str] = set()
    notes: list[str] = []
    if "pf status" not in explicit:
        keep.add("PF Status")
        status = current.get("PF Status")
        if status and status != values.get("PF Status"):
            notes.append(f"Freigabestatus „{status}“")
    lifecycle = current.get("Lifecycle")
    if ("lifecycle" not in explicit and lifecycle and values.get("Lifecycle")
            and lifecycle != values.get("Lifecycle") and not (template_lifecycle and lifecycle == DEFAULT_LIFECYCLE)):
        keep.add("Lifecycle")
        notes.append(f"Lebenszyklus „{lifecycle}“")
    url = current.get("ComponentLink1URL")
    if url and "componentlink1url" not in explicit:
        if url != values.get("ComponentLink1URL"):
            keep.update(_LINK_COLUMNS)
            notes.append("Datenblatt-Link")
        elif current.get("ComponentLink1Description") and "componentlink1description" not in explicit:
            keep.add("ComponentLink1Description")
    for ref, path, label in _LINKS:
        stored = current.get(ref)
        new = values.get(ref)
        if replace_links or ref.casefold() in explicit or not stored or not new:
            continue
        if stored.casefold() != new.casefold():
            keep.update((ref, path))
            notes.append(f"{label} „{stored}“")
    return keep, notes


def _checked(req: SeriesRequest) -> tuple[MpnTemplate, Any, Any, str, _Selection]:
    """(template, category, workspace, part-number scheme, selection) – cheap request validation."""
    from ..db import categories, core
    from ..db.errors import CategoryNotFound

    template = get_template(req.template_id)
    table = template.category
    try:
        cat = categories.get_category(table)
    except CategoryNotFound as exc:
        raise SeriesError(f"Die Kategorie „{table}“ der Vorlage gibt es in dieser Bibliothek nicht – bitte anlegen "
                          "oder eine andere Vorlage wählen.") from exc
    fixed = [k for k in req.field_overrides if k.strip().casefold() in _FIXED_BY_TEMPLATE]
    if fixed:
        raise SeriesError(f"„{fixed[0].strip()}“ kommt aus der Vorlage und kann nicht fest vorgegeben werden.")
    ws = core.current_workspace()
    scheme = req.part_number_scheme or ws.settings.part_number_scheme
    if scheme == "internal" and ws.settings.part_number_scheme != "internal":
        raise SeriesError("Interne Teilenummern sind in dieser Bibliothek nicht eingestellt (Einstellungen › "
                          "Teilenummern). Bitte das Schema „mpn“ verwenden oder die Einstellung ändern.")
    try:
        compile_template(template)
    except MpnError as exc:
        raise SeriesError(str(exc)) from exc
    return template, cat, ws, scheme, _selection(template, req)


def validate(req: SeriesRequest) -> None:
    """Check a request without generating rows (template, category, codes, ranges) – raises
    :class:`SeriesError` or :class:`~partforge.domain.mpn.TemplateNotFound` (German messages)."""
    _checked(req)


def sample_check(template: MpnTemplate, cat: Any, attrs: Mapping[str, str], mpn: str, *,
                 ws_root: Any = None) -> SampleCheck:
    """One part of ``template`` as the series would store it in category ``cat``: the category values
    (normalised like a manual entry, Value/Comment/Description from the category templates) and the
    required fields that stay empty. Symbol and footprint count as filled (the series generates them),
    fields that do not apply (0-Ω jumper) as not required. ``attrs``: row attributes of the part
    (``Resolution.attrs`` + :func:`~partforge.domain.mpn.engine.base_attrs`, or a catalog entry's)."""
    from ..db.values import not_applicable

    candidate = _Candidate(size=str(attrs.get("size") or ""), value=0.0, codes={}, attrs=dict(attrs), mpn=mpn,
                           ok=True)
    raw = _row_values(template, candidate, {}, None)
    normalized, unknown, errors = _Normalizer(cat, ws_root).row(raw)
    if cat.field(PART_NUMBER) is not None:
        normalized[PART_NUMBER] = mpn
    _TextRenderer(cat).fill(normalized)
    probe = {**normalized, **{column: "(Serie)" for column in _SERIES_LINKS}}
    missing = _missing_required(cat, probe, scheme="mpn")
    return SampleCheck(values=normalized, missing=[RequiredField(column=f.column, label=f.label) for f in missing],
                       not_applicable=sorted(not_applicable(cat, normalized)), errors=errors,
                       unknown_columns=sorted(unknown))


def _override(overrides: Mapping[str, str], column: str) -> str | None:
    wanted = column.casefold()
    return next((clean_free_text(v) or None for k, v in overrides.items() if k.casefold() == wanted), None)


def _build_plan(req: SeriesRequest) -> _Plan:
    from ..db import registry

    template, cat, ws, scheme, sel = _checked(req)
    table = template.category
    candidates, gen_warnings, skipped = _candidates(template, sel, req)
    warnings = [*sel.warnings, *gen_warnings]
    if len(candidates) > req.max_rows:
        raise SeriesError(f"Die Auswahl ergibt {len(candidates)} Bauteile (höchstens {req.max_rows}). Bitte Bereich, "
                          "Baugrößen oder Reihe einschränken.")
    if not candidates:
        warnings.append("Mit dieser Auswahl entstehen keine Bauteile.")

    normalizer = _Normalizer(cat, ws.root)
    renderer = _TextRenderer(cat)
    datasheet = req.datasheet_url  # else per row: catalog entry link, template link
    overrides = {k.strip(): v for k, v in req.field_overrides.items() if k and k.strip()}
    explicit = {k.casefold() for k in overrides}
    if req.datasheet_url:
        explicit.update(c.casefold() for c in _LINK_COLUMNS)
    fixed_footprint = _override(overrides, "Footprint Ref")
    fixed_symbol = _override(overrides, "Library Ref")
    cache = _FootprintCache(density=req.density, height_mode=req.footprint_height)
    footprint_records = {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)}
    symbol_records = {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)}
    if fixed_footprint and len({c.size for c in candidates}) > 1:
        warnings.append(f"Fester Footprint „{fixed_footprint}“ für mehrere Baugrößen – bitte prüfen.")
    if fixed_footprint and fixed_footprint.casefold() not in footprint_records:
        warnings.append(f"Footprint „{fixed_footprint}“ ist nicht registriert – Footprint-Pfad bitte selbst angeben.")
    if fixed_symbol and fixed_symbol.casefold() not in symbol_records:
        warnings.append(f"Symbol „{fixed_symbol}“ ist nicht registriert – Bibliothekspfad bitte selbst angeben.")

    # values + footprints
    staged: list[tuple[_Candidate, dict[str, str | None], Any, list[str]]] = []
    unknown_columns: set[str] = set()
    for candidate in candidates:
        messages = list(candidate.messages)
        raw = _row_values(template, candidate, overrides, datasheet)
        normalized, unknown, errors = normalizer.row(raw)
        unknown_columns.update(unknown)
        if errors:
            messages.extend(errors)
            candidate.ok = False
        footprint = None
        if fixed_footprint is None:
            try:
                footprint = _footprint_for(template, candidate.size, candidate.attrs, cache)
            except SeriesError as exc:
                messages.append(str(exc))
                candidate.ok = False
        staged.append((candidate, normalized, footprint, messages))
    if unknown_columns:
        warnings.append("Spalten fehlen in der Kategorie und werden nicht gefüllt: "
                        + ", ".join(sorted(unknown_columns)) + ".")

    # symbol (one per series) – never a guessed pin-out
    symbol_spec: Any | None = None
    symbol_kind: str | None = None
    symbol_problem: str | None = None
    symbol_ref: SymbolRef | None = None
    if fixed_symbol is not None:
        known_symbol = symbol_records.get(fixed_symbol.casefold())
        symbol_ref = SymbolRef(name=fixed_symbol, exists=known_symbol is not None,
                               kind=known_symbol.kind if known_symbol else None,
                               library=known_symbol.library if known_symbol else None,
                               status=known_symbol.status if known_symbol else None)
    elif staged:
        sample = next((n for c, n, _f, _m in staged if c.ok), staged[0][1])
        sample_fp = next((f for c, _n, f, _m in staged if c.ok and f is not None), None)
        symbol_spec, symbol_kind, symbol_problem = _symbol_for(template, cat, sample, sample_fp)
        if symbol_spec is not None:
            known_symbol = symbol_records.get(symbol_spec.name.casefold())
            symbol_ref = SymbolRef(name=symbol_spec.name, exists=known_symbol is not None, kind=symbol_kind,
                                   library=known_symbol.library if known_symbol else None,
                                   status=known_symbol.status if known_symbol else None)
        else:
            warnings.append(symbol_problem or NO_SAFE_SYMBOL)

    # links, generated texts, checks of db.parts
    footprint_specs: dict[str, Any] = {}
    footprint_refs: dict[str, FootprintRef] = {}
    row_refs: dict[str, FootprintRef] = {}  # the rows' copy without name_reason (once per footprint is enough)
    fp_refs: list[FootprintRef | None] = []
    for candidate, normalized, footprint, messages in staged:
        fp_ref: FootprintRef | None = None
        name = fixed_footprint or (footprint.name if footprint is not None else None)
        if name is not None:
            fp_ref = row_refs.get(name)
            if fp_ref is None:
                known = footprint_records.get(name.casefold())
                plain, reason = cache.reasons.get(name, (None, None)) if footprint is not None else (None, None)
                full = FootprintRef(name=name, exists=known is not None,
                                    family=footprint.family if footprint is not None else (
                                        (known.family if known else None) or "–"),
                                    size=candidate.size, library=known.library if known else None,
                                    status=known.status if known else None, plain_name=plain, name_reason=reason)
                footprint_refs[name] = full
                fp_ref = row_refs[name] = full.model_copy(update={"name_reason": None}) if reason else full
                if footprint is not None:
                    footprint_specs[name] = footprint
            normalized["Footprint Ref"] = name
        if symbol_ref is not None:
            normalized["Library Ref"] = symbol_ref.name
        elif candidate.ok:
            messages.append(symbol_problem or NO_SAFE_SYMBOL)
            candidate.ok = False
        if candidate.ok:
            if scheme == "mpn":
                normalized[PART_NUMBER] = candidate.mpn
            renderer.fill(normalized)
            missing = _missing_required(cat, normalized, scheme=scheme)
            if missing:
                messages.extend(f"{f.label}: Pflichtfeld ist leer." for f in missing)
                candidate.ok = False
        fp_refs.append(fp_ref)

    # part numbers and status
    ok_mpns = [c.mpn for c, _n, _f, _m in staged if c.ok]
    stored = _stored_parts(table, ok_mpns if scheme == "mpn" else [], ok_mpns) if ok_mpns else \
        _Stored(set(), {}, {})
    rows: list[PreviewRow] = []
    keep: list[set[str]] = []
    seen_pn: dict[str, int] = {}
    for (candidate, normalized, _footprint, messages), fp_ref in zip(staged, fp_refs, strict=True):
        part_number: str | None
        status: RowStatus
        kept: set[str] = set()
        if not candidate.ok:
            status = "invalid"
            part_number = candidate.mpn if scheme == "mpn" else None
            if part_number:
                normalized[PART_NUMBER] = part_number
        else:
            status, part_number, current, notes = _classify(candidate, table, scheme, stored)
            messages.extend(notes)
            if status == "exists" and current is not None:
                kept, kept_notes = _kept_on_update(normalized, current, explicit=explicit,
                                                   replace_links=req.replace_links,
                                                   template_lifecycle=bool(candidate.attrs.get("lifecycle")))
                if kept_notes:
                    messages.append("Beim Aktualisieren bleiben erhalten: " + ", ".join(kept_notes) + ".")
            if status in ("new", "exists"):
                key = part_number.casefold() if part_number else compact(candidate.mpn)
                if key in seen_pn:
                    status = "conflict"
                    messages.append(f"Doppelt in der Vorschau (Zeile {seen_pn[key] + 1}).")
                else:
                    seen_pn[key] = len(rows)
            if part_number:
                normalized[PART_NUMBER] = part_number
            else:
                normalized.pop(PART_NUMBER, None)
        rows.append(PreviewRow(
            part_number=part_number, mpn=candidate.mpn, size=candidate.size,
            value=format_value(candidate.value, template.value_unit) if candidate.value or candidate.jumper else "",
            jumper=candidate.jumper, values=normalized, footprint=fp_ref,
            symbol=symbol_ref, status=status, messages=list(dict.fromkeys(messages)),
        ))
        keep.append(kept)
    return _Plan(template=template, table=table, ws=ws, rows=rows, candidates=[c for c, _n, _f, _m in staged],
                 keep=keep, footprint_specs=footprint_specs, footprint_refs=footprint_refs, symbol_spec=symbol_spec,
                 symbol_ref=symbol_ref, symbol_kind=symbol_kind, warnings=warnings, scheme=scheme,
                 overrides=overrides, skipped=skipped)


# --------------------------------------------------------------------------- public API


def preview(req: SeriesRequest) -> SeriesPreview:
    """Rows, statuses, needed footprints and symbol for a request (nothing is written)."""
    started = time.perf_counter()
    plan = _build_plan(req)
    counts = Counter(r.status for r in plan.rows)
    needed = [ref for name, ref in plan.footprint_refs.items() if not ref.exists and name in plan.footprint_specs]
    result = SeriesPreview(
        template=plan.template.summary(),
        table=plan.table,
        rows=plan.rows,
        counts={"total": len(plan.rows), **{s: counts.get(s, 0) for s in ("new", "exists", "conflict", "invalid")}},
        footprints_needed=needed,
        footprints=list(plan.footprint_refs.values()),
        symbol=plan.symbol_ref,
        warnings=plan.warnings,
        skipped_by_size=dict(plan.skipped.by_size),
        skipped_total=plan.skipped.total,
        skipped_reason=plan.skipped.reason_text(),
    )
    result.duration_s = round(time.perf_counter() - started, 3)
    log.debug("Serienvorschau %s: %d Zeilen in %.2f s", req.template_id, len(plan.rows), result.duration_s)
    return result


def _same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(os.path.abspath(os.fspath(b)))


class _LibraryGuard:
    """Keeps the series job in the library it was planned for (ARCHITEKTUR §8.4: never write across a
    library switch). Watches ``WORKSPACE_CLOSED``/``WORKSPACE_OPENED`` and compares the open database
    and workspace with the planned library; :meth:`bound` holds the database write lock (a library
    switch swaps the database under the same lock) while parts are written."""

    def __init__(self, ctx: JobContext | None):
        self._ctx = ctx
        self._switched = False
        self._logged = False
        self._unsubscribe: list[Callable[[], None]] = [
            events.subscribe(events.WORKSPACE_CLOSED, self._on_switch),
            events.subscribe(events.WORKSPACE_OPENED, self._on_switch),
        ]
        self.root: Path | None = None

    def _on_switch(self, *_args: Any, **_kwargs: Any) -> None:
        self._switched = True

    def bind(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.check()

    def is_current(self) -> bool:
        from ..db import core

        if self._switched or self.root is None:
            return False
        try:
            if not core.is_open() or not _same_path(core.current_workspace().root, self.root):
                return False
        except Exception:  # noqa: BLE001 - closed concurrently
            return False
        now = current_or_none()
        return now is not None and _same_path(now.root, self.root)

    def check(self) -> None:
        if self.is_current():
            return
        if not self._logged:
            self._logged = True
            _log(self._ctx, LIBRARY_SWITCHED, "warn")
        raise JobCancelled(LIBRARY_SWITCHED)

    @contextmanager
    def bound(self) -> Iterator[None]:
        from ..db import core

        with core.write_lock():
            self.check()
            yield

    def close(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []


_PHASE_KEYS = frozenset({"phase", "done", "total"})


@dataclass
class _Counter:
    """Items of a phase a sub-step works on: its progress 0..1 covers ``offset`` … ``offset + span``
    of ``total`` (``job.detail`` done/total)."""

    offset: int
    span: int
    total: int


class _JobView:
    """Job context handed to the steps of a commit (``sync.ensure_*``, ``db.parts.upsert_parts``):
    maps their progress 0..1 into a sub-range, never lets the bar go backwards, counts the items of
    the phase into ``job.detail`` (done/total), and every cancellation point also checks that the
    planned library is still open."""

    def __init__(self, ctx: JobContext | None, guard: _LibraryGuard | None = None, low: float = 0.0,
                 high: float = 1.0, floor: list[float] | None = None, counter: _Counter | None = None,
                 last_done: list[int] | None = None):
        self._ctx = ctx
        self._guard = guard
        self._low = low
        self._high = high
        self._floor = floor if floor is not None else [0.0]
        self._counter = counter
        self._last_done = last_done if last_done is not None else [-1]
        self.job = ctx.job if ctx is not None else None

    def _map(self, fraction: float) -> float:
        return self._low + (self._high - self._low) * max(0.0, min(1.0, fraction))

    def scaled(self, low: float, high: float, *, counter: _Counter | None = None) -> _JobView:
        """View for a step that reports 0..1 into [low, high] of this view (``counter``: the items it
        works on, reported as ``job.detail`` done/total)."""
        return _JobView(self._ctx, self._guard, self._map(low), self._map(high), self._floor, counter,
                        self._last_done)

    def phase(self, name: CommitPhase, message: str, fraction: float, *, total: int | None = None,
              done: int | None = None, log_it: bool = True) -> None:
        """Start a phase: log line, progress bar + message, ``job.detail`` = {phase, done, total}."""
        if log_it:
            _log(self, message)
        if self._ctx is None:
            return
        start = done if done is not None else (0 if total is not None else None)
        self._last_done[0] = start if start is not None else -1
        self._ctx.detail(phase=name, done=start, total=total)
        self.progress(fraction, message)

    def progress(self, fraction: float | None = None, message: str | None = None) -> None:
        if self._ctx is None:
            return
        mapped = None
        if fraction is not None:
            mapped = max(self._floor[0], self._map(fraction))
            self._floor[0] = mapped
            if self._counter is not None:
                counter = self._counter
                done = min(counter.total, counter.offset + round(counter.span * max(0.0, min(1.0, fraction))))
                if done > self._last_done[0]:
                    self._last_done[0] = done
                    self._ctx.detail(done=done, total=counter.total)
        self._ctx.progress(mapped, message)

    def counted(self, done: int) -> None:
        """All items of the current phase are finished (``job.detail`` done)."""
        if self._ctx is not None and done > self._last_done[0]:
            self._last_done[0] = done
            self._ctx.detail(done=done)

    def detail(self, **fields: Any) -> None:
        """Structured progress of a sub-step: forwarded, except the series' own keys (phase, done, total)."""
        own = {k: v for k, v in fields.items() if k not in _PHASE_KEYS}
        if self._ctx is not None and own:
            self._ctx.detail(**own)

    def log(self, text: str, level: Level = "info") -> None:
        if self._ctx is not None:
            self._ctx.log(text, level)

    @property
    def cancelled(self) -> bool:
        return self._ctx.cancelled if self._ctx is not None else False

    @property
    def cancel_reason(self) -> str | None:
        return self._ctx.cancel_reason if self._ctx is not None else None

    def check_cancelled(self) -> None:
        if self._ctx is not None:
            self._ctx.check_cancelled()
        if self._guard is not None:
            self._guard.check()


def _log(ctx: JobContext | _JobView | None, text: str, level: Level = "info") -> None:
    if ctx is not None:
        ctx.log(text, level)
    log.info("Serie: %s", text)


def _written_names(kind: Literal["symbol", "footprint"], names: Sequence[str]) -> set[str]:
    """Casefolded names among ``names`` that are registered **and** in their file (status ``ok``) – one light
    query, no spec parsed."""
    from ..db import registry

    if not names:
        return set()
    lister = registry.list_symbols if kind == "symbol" else registry.list_footprints
    return {r.name.casefold() for r in lister(names=list(names), with_spec=False, with_usage=False) if r.status == "ok"}


def _problem(kind: Literal["symbol", "footprint"], record: Any) -> LibraryProblem | None:
    """The registry record of a written symbol/footprint as :class:`LibraryProblem` – ``None`` when it is
    in its library file (status ``ok``)."""
    if record is None or record.status == "ok":
        return None
    reason = record.status_message or ("Fehler beim Schreiben" if record.status == "error" else "noch nicht geschrieben")
    return LibraryProblem(kind=kind, name=record.name, library=record.library or None,
                          status=cast(Any, record.status if record.status in ("error", "pending", "missing") else "error"),
                          message=reason)


def _ensure_symbol(plan: _Plan, view: _JobView) -> tuple[str | None, bool, str | None, LibraryProblem | None]:
    """Register/write the series symbol -> (library, created and written, pending note, problem)."""
    from ..altium import sync
    from ..altium.libwriter import symbol_library_path
    from ..db import core, registry
    from ..db.models import SymbolRecord

    spec = plan.symbol_spec
    if spec is None:
        return None, False, None, None
    existed = spec.name.casefold() in _written_names("symbol", [spec.name])  # in the SchLib already
    try:
        records = sync.ensure_symbols([spec], category=plan.table, source="generated", ctx=cast(JobContext, view))
        record = next((r for r in records if r.name.casefold() == spec.name.casefold()),
                      records[0] if records else None)
        problem = _problem("symbol", record)
        if problem is not None:
            _log(view, f"Symbol {spec.name}: {problem.message}", "warn")
        return (record.library if record else None), not existed and problem is None, None, problem
    except NotImplementedError:
        ws = core.current_workspace()
        current = registry.get_symbol(spec.name, with_usage=False)
        if current is not None:
            return current.library, False, None, _problem("symbol", current)
        library = ws.rel(symbol_library_path(ws, spec, plan.table))
        note = "Bibliotheks-Synchronisation noch nicht verfügbar – Symbol als „ausstehend“ registriert."
        record = registry.upsert_symbol(SymbolRecord(name=spec.name, library=library, source="generated", spec=spec,
                                                     pin_count=len(spec.pins), part_count=spec.part_count,
                                                     kind=plan.symbol_kind, status="pending", status_message=note))
        return library, False, None, _problem("symbol", record)  # the problem carries the note


def _ensure_footprints(plan: _Plan, names: Sequence[str], view: _JobView) -> tuple[dict[str, str], list[str],
                                                                                   str | None, list[LibraryProblem]]:
    """Register/write the footprints -> ({name: library}, created and written names, pending note, problems)."""
    from ..altium import sync
    from ..altium.libwriter import footprint_library_path
    from ..db import core, registry
    from ..db.models import FootprintRecord

    specs = [plan.footprint_specs[n] for n in names]
    if not specs:
        return {}, [], None, []
    before = _written_names("footprint", names)  # in their PcbLib already (a failed earlier write is not)
    try:
        records = sync.ensure_footprints(specs, source="generated", ctx=cast(JobContext, view))
        by_name = {r.name.casefold(): r for r in records}
        problems: list[LibraryProblem] = []
        for n in names:
            problem = _problem("footprint", by_name.get(n.casefold()))
            if problem is not None:
                problems.append(problem)
                _log(view, f"Footprint {problem.name}: {problem.message}", "warn")
        failed = {pr.name.casefold() for pr in problems}
        created = [n for n in names
                   if n.casefold() not in before and n.casefold() in by_name and n.casefold() not in failed]
        return ({n: by_name[n.casefold()].library if n.casefold() in by_name else "" for n in names}, created, None,
                problems)
    except NotImplementedError:
        ws = core.current_workspace()
        note = "Bibliotheks-Synchronisation noch nicht verfügbar – Footprints als „ausstehend“ registriert."
        new_records = []
        registered: dict[str, str] = {}
        problems = []
        for spec in specs:
            current = registry.get_footprint(spec.name, with_usage=False)
            if current is not None:
                registered[spec.name] = current.library
                if (problem := _problem("footprint", current)) is not None:
                    problems.append(problem)
                continue
            library = ws.rel(footprint_library_path(ws, spec))
            registered[spec.name] = library
            new_records.append(FootprintRecord(name=spec.name, library=library, source="generated", spec=spec,
                                               family=spec.family or None, ipc_name=spec.ipc_name,
                                               pad_count=len(spec.pads), height=spec.height, status="pending",
                                               status_message=note))
        if new_records:
            for record in registry.upsert_footprints(new_records):
                if (problem := _problem("footprint", record)) is not None:
                    problems.append(problem)
        return registered, [], None, problems  # the problems carry the note


def _problem_sentence(problem: LibraryProblem) -> str:
    """German summary of a symbol/footprint that is not in its file (``result.warnings``)."""
    what = "Symbol" if problem.kind == "symbol" else "Footprint"
    where = f"in {problem.library}" if problem.library else "in seine Bibliothek"
    if problem.status == "pending":
        return (f"{what} „{problem.name}“ ist noch nicht {where} geschrieben ({problem.message}) – die Bauteile sind "
                "angelegt; „Bibliotheksdateien synchronisieren“ (Bereich Altium) holt es nach, sobald ein "
                "Bibliotheks-Writer bereitsteht.")
    rows = f"{plural(problem.parts, 'Bauteil wurde', 'Bauteile wurden')} deshalb nicht angelegt" if problem.parts else (
        "Bauteile damit wurden nicht angelegt")
    return (f"{what} „{problem.name}“ wurde nicht {where} geschrieben: {problem.message} – {rows}. Bitte die Ursache "
            "beheben (z. B. die Datei in Altium speichern und schließen) und die Serie erneut erzeugen.")


def _payloads(plan: _Plan, writable: Sequence[int]) -> list[dict[str, Any]]:
    """Values to save per writable row: generated texts are left to ``db.parts`` (re-rendered while they
    still equal the generated text), an update keeps the columns of :func:`_kept_on_update`."""
    out: list[dict[str, Any]] = []
    for index in writable:
        row = plan.rows[index]
        values: dict[str, Any] = {k: v for k, v in row.values.items()
                                  if k not in _GENERATED_TEXTS or k in plan.overrides}
        if row.status == "exists":
            for column in plan.keep[index]:
                values.pop(column, None)
        elif plan.scheme == "internal":
            values.pop(PART_NUMBER, None)
        out.append(values)
    return out


def commit(ctx: JobContext | None, req: SeriesRequest | Mapping[str, Any], mode: CommitMode = "skip",
           author: str | None = None, *, library: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Job function: create the series (symbol, footprints, parts). Returns :class:`SeriesCommitResult`
    as a JSON-able dict (``job.result``); ``job.message`` gets its German summary.

    ``library``: root folder of the library the series was requested for (API: at submit time) –
    if another library is open when the job runs, or the library is switched or closed while it
    runs, the job stops with :class:`~partforge.jobs.JobCancelled` and writes nothing more."""
    from ..db import core

    request = req if isinstance(req, SeriesRequest) else SeriesRequest.model_validate(dict(req))
    if mode not in ("skip", "update"):
        raise SeriesError(f"Ungültiger Modus „{mode}“ (skip oder update).")
    guard = _LibraryGuard(ctx)  # watches library switches from now on
    view = _JobView(ctx, guard)
    try:
        view.phase("plan", "Serie wird berechnet …", 0.02)
        guard.bind(library if library is not None else core.current_workspace().root)
        plan = _build_plan(request)
        guard.bind(plan.ws.root)
        return _write(plan, mode, author, view, guard).model_dump(mode="json")
    finally:
        guard.close()


def _plan_summary(plan: _Plan) -> str:
    """German log line after planning: "Serie berechnet: 1.260 Zeilen – 1.248 neu, 12 vorhanden"."""
    counts = Counter(r.status for r in plan.rows)
    parts = [f"{_count(counts['new'])} neu", f"{_count(counts['exists'])} vorhanden"]
    if counts["conflict"]:
        parts.append(plural(counts["conflict"], "Konflikt", "Konflikte"))
    if counts["invalid"]:
        parts.append(f"{_count(counts['invalid'])} ungültig")
    return f"Serie berechnet: {plural(len(plan.rows), 'Zeile', 'Zeilen')} – {', '.join(parts)}."


def _not_written(result: SeriesCommitResult) -> list[str]:
    out = []
    if result.invalid:
        out.append(f"{_count(result.invalid)} ungültig")
    if result.conflicts:
        out.append(plural(result.conflicts, "Konflikt", "Konflikte"))
    return out


def _final_message(result: SeriesCommitResult) -> str:
    """"Serie erzeugt: 1.248 neu, 12 aktualisiert, 0 übersprungen, 6 Footprints neu" (+ errors / rows
    not written, when there are any)."""
    parts = [f"{_count(result.created)} neu", f"{_count(result.updated)} aktualisiert"]
    if result.unchanged:
        parts.append(f"{_count(result.unchanged)} unverändert")
    parts.append(f"{_count(result.skipped)} übersprungen")
    if result.errors:
        parts.append(plural(result.errors, "Fehler", "Fehler"))
    parts.append(f"{plural(len(result.footprints_created), 'Footprint', 'Footprints')} neu")
    for kind, one, many in (("symbol", "Symbol", "Symbole"), ("footprint", "Footprint", "Footprints")):
        for status, word in (("error", "nicht geschrieben"), ("pending", "ausstehend")):
            n = sum(1 for p in result.library_problems if p.kind == kind and p.status == status)
            if n:
                parts.append(f"{plural(n, one, many)} {word}")
    text = "Serie erzeugt: " + ", ".join(parts)
    not_written = _not_written(result)
    if not_written:
        text += f" (nicht geschrieben: {', '.join(not_written)})"
    return text


def _footprint_phase_text(names: Sequence[str]) -> str:
    """Log line of the footprint phase – only footprints not in their file yet "werden angelegt" (K8):
    „3 Footprints werden angelegt (5 vorhanden) …“, „8 vorhandene Footprints werden geprüft …“."""
    written = _written_names("footprint", names)
    new = sum(1 for n in names if n.casefold() not in written)
    existing = len(names) - new
    if not new:
        return f"{plural(existing, 'vorhandener Footprint wird', 'vorhandene Footprints werden')} geprüft …"
    text = f"{plural(new, 'Footprint wird', 'Footprints werden')} angelegt"
    return f"{text} ({_count(existing)} vorhanden) …" if existing else f"{text} …"


def _write(plan: _Plan, mode: CommitMode, author: str | None, view: _JobView,
           guard: _LibraryGuard) -> SeriesCommitResult:
    from ..db import backup, parts

    # "skip": existing parts are left alone (no symbol/footprint work for them either)
    wanted = ("new", "exists") if mode == "update" else ("new",)
    writable = [i for i, row in enumerate(plan.rows) if row.status in wanted]
    existing = sum(1 for r in plan.rows if r.status == "exists") if mode == "skip" else 0
    invalid = [r for r in plan.rows if r.status == "invalid"]
    conflicts = [r for r in plan.rows if r.status == "conflict"]
    result = SeriesCommitResult(
        table=plan.table, template=plan.template.id, rows=len(plan.rows), skipped=existing, invalid=len(invalid),
        conflicts=len(conflicts), symbol=plan.symbol_ref.name if plan.symbol_ref else None,
        warnings=list(plan.warnings))
    _log(view, _plan_summary(plan))
    for row in invalid[:50]:
        _log(view, f"{row.mpn}: {'; '.join(row.messages) or 'ungültig'}", "warn")
    for row in conflicts[:50]:
        _log(view, f"{row.mpn}: {'; '.join(row.messages) or 'Konflikt'}", "warn")
    if not writable:
        reasons = [f"{_count(existing)} bereits vorhanden"] if existing else []
        reasons += _not_written(result)
        result.message = "Serie: nichts zu schreiben" + (f" – {', '.join(reasons)}" if reasons else "") + "."
        _log(view, result.message, "warn")
        view.phase("done", result.message, 1.0, total=0, done=0, log_it=False)
        return result
    payloads = _payloads(plan, writable)
    if any(plan.rows[i].status == "new" and not values.get("Library Ref")
           for i, values in zip(writable, payloads, strict=True)):
        raise SeriesError(NO_SAFE_SYMBOL)  # defensive: the plan marks such rows invalid – never write them
    view.check_cancelled()

    symbol = plan.symbol_spec
    symbol_needed = symbol is not None and any(v.get("Library Ref") == symbol.name for v in payloads)
    symbol_library: str | None = None
    problems: list[LibraryProblem] = []
    if symbol is not None and symbol_needed:
        verb = "wird geprüft" if _written_names("symbol", [symbol.name]) else "wird angelegt"
        view.phase("symbol", f"Symbol „{symbol.name}“ {verb} …", 0.08, total=1)
        symbol_library, result.symbol_created, symbol_note, symbol_problem = _ensure_symbol(
            plan, view.scaled(0.08, 0.15))
        if symbol_note:
            result.pending.append(symbol_note)
        if symbol_problem is not None:
            problems.append(symbol_problem)
        view.counted(1)
    view.check_cancelled()

    needed = list(dict.fromkeys(str(v["Footprint Ref"]) for v in payloads
                                if v.get("Footprint Ref") in plan.footprint_specs))
    libraries: dict[str, str] = {}
    if needed:
        view.phase("footprints", _footprint_phase_text(needed), 0.15, total=len(needed))
        libraries, result.footprints_created, fp_note, fp_problems = _ensure_footprints(
            plan, needed, view.scaled(0.15, 0.35, counter=_Counter(0, len(needed), len(needed))))
        if fp_note:
            result.pending.append(fp_note)
        problems.extend(fp_problems)
        view.counted(len(needed))
    view.check_cancelled()

    # a symbol/footprint that could not be written: its rows are not written (like the datasheet commit)
    failed = {(p.kind, p.name.casefold()): p for p in problems if p.status != "pending"}
    uses: Counter[tuple[str, str]] = Counter()
    regular: list[dict[str, Any]] = []
    jumpers: list[dict[str, Any]] = []
    for index, values in zip(writable, payloads, strict=True):
        footprint = values.get("Footprint Ref")
        library_ref = values.get("Library Ref")
        keys = [("symbol", str(library_ref).casefold()) if library_ref else None,
                ("footprint", str(footprint).casefold()) if footprint else None]
        for key in keys:
            if key is not None:
                uses[key] += 1
        blocked = next((failed[k] for k in keys if k is not None and k in failed), None)
        if blocked is not None:
            row = plan.rows[index]
            label = str(values.get(PART_NUMBER) or row.part_number or row.mpn)
            what = "Symbol" if blocked.kind == "symbol" else "Footprint"
            verb = "Nicht aktualisiert" if row.status == "exists" else "Nicht angelegt"
            result.errors += 1
            if len(result.error_details) < 200:
                result.error_details[label] = (f"{verb} – {what} „{blocked.name}“ konnte nicht geschrieben werden: "
                                               f"{blocked.message}")
            continue
        if footprint in plan.footprint_specs and libraries.get(footprint):
            values["Footprint Path"] = libraries[footprint]
        if symbol is not None and library_ref == symbol.name and symbol_library:
            values["Library Path"] = symbol_library
        (jumpers if plan.candidates[index].jumper else regular).append(values)
    for problem in problems:
        problem.parts = uses.get((problem.kind, problem.name.casefold()), 0)
        result.library_problems.append(problem)
        sentence = _problem_sentence(problem)  # shown with the result (SuccessView: pending + warnings)
        target = result.pending if problem.status == "pending" else result.warnings
        if sentence not in target:
            target.append(sentence)

    total = len(regular) + len(jumpers)
    results = []
    with guard.bound():  # parts go into the planned library or nowhere
        view.phase("backup", "Sicherung wird angelegt …", 0.35)
        backup_file = backup.auto_backup("vor_serie")
        result.backup = backup_file.name if backup_file else None
        if backup_file:
            _log(view, f"Sicherung angelegt: {backup_file.name}")
        view.phase("parts", f"{plural(total, 'Bauteil wird', 'Bauteile werden')} gespeichert …", 0.4, total=total)
        split = 0.4 + 0.57 * len(regular) / max(1, total)
        if regular:
            results.append(parts.upsert_parts(
                plan.table, regular, mode=mode, author=author,
                ctx=cast(JobContext, view.scaled(0.4, split, counter=_Counter(0, len(regular), total)))))
        if jumpers:
            # 0-Ω jumpers have no tolerance, TCR, power rating or working voltage: db.parts knows that rule
            # (db.values.not_applicable), the batch is only separate for the progress counter
            results.append(parts.upsert_parts(
                plan.table, jumpers, mode=mode, author=author,
                ctx=cast(JobContext, view.scaled(split, 0.97, counter=_Counter(len(regular), len(jumpers), total)))))
        view.counted(total)
    created_pns: list[str] = []
    for upserted in results:
        result.created += len(upserted.created)
        result.updated += len(upserted.updated)
        result.unchanged += len(upserted.unchanged)
        result.skipped += len(upserted.skipped)
        result.errors += len(upserted.errors)
        result.error_details.update(dict(list(upserted.errors.items())[:200]))
        result.part_warnings.update(dict(list(upserted.warnings.items())[:100]))
        created_pns.extend(upserted.created)
    result.created_part_numbers = created_pns[:2000]
    # db.parts.upsert_parts announces the writes itself (events.PARTS_CHANGED -> Altium refresh)
    for pn, message in list(result.error_details.items())[:50]:
        _log(view, f"{pn}: {message}", "error")
    result.message = _final_message(result)
    _log(view, result.message, "success" if not result.errors and not result.library_problems else "warn")
    view.phase("done", result.message, 1.0, total=total, done=total, log_it=False)
    return result
