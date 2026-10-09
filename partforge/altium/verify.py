"""Library check in Altium ("Bibliothek in Altium prüfen"): part selection, result models and
the persisted last result.

The job itself (``POST /api/altium/verify``, :mod:`partforge.api.routes_altium`) resolves the
selected parts through the bridge – :data:`~partforge.altium.bridge.core.RESOLVE_BATCH_SIZE`
parts per Altium script run – and checks symbol, footprints, pins, Comment and the parameter
values. This module holds what is independent of Altium:

* **Parameters** (:func:`compare_parameters`): the values Altium places with a part
  (``DbComponentResolution.parameters`` and ``description``) against the database row – for every
  field the DbLib adds to the design as a parameter of the same name (not the reserved
  ``[Library Ref]`` … mappings, not the fields with ``add_to_design=False``) plus ``Description``
  (``[Description]``). Texts are compared normalised (:func:`comparable_text`: NFKC – micro sign U+00B5 = Greek mu U+03BC,
  ohm sign U+2126 = Greek capital omega U+03A9, ``℃`` = ``°C`` –, ``+/-`` = ``±``, without invisible
  format characters, blanks collapsed); a blank value counts as absent (the global ``AddMode=3`` adds no parameter for it).
  Each difference is a warning (:func:`parameter_message`: „Altium liefert für „Slew Rate“ keinen
  Wert – in der Datenbank steht „290V/µs“.“).
* **Selection** (:func:`select_parts`): named part numbers (``scope="part_numbers"``), every
  part (``"all"``) or a sample of ``limit`` parts (``"sample"``), optionally limited to some
  categories. Sample modes: ``first`` = the first parts in category order (sorted by part
  number), ``spread`` (default) = a deterministic sample across all categories, proportional to
  their size, at least one part per non-empty category (:func:`sample_quotas`), evenly spaced
  inside each category (:func:`spread_indices`). With more categories than ``limit`` the
  sample therefore holds one part per category.
* **Last result** (:func:`save_last` / :func:`load_last`): the result of the last completed
  check of a library is stored in its database (``pf_meta`` key :data:`LAST_RESULT_KEY`, via
  :mod:`partforge.db.meta`) and survives a restart (``GET /api/altium/verify/last``).
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, ValidationError

from ..domain.text import strip_format_chars

if TYPE_CHECKING:
    from ..db.models import CategoryDef

log = logging.getLogger(__name__)

__all__ = [
    "LAST_RESULT_KEY",
    "FootprintCheck",
    "ParameterComparison",
    "ParameterDiff",
    "SampleMode",
    "Selection",
    "VerifiedPart",
    "VerifyError",
    "VerifyRun",
    "VerifyScope",
    "VerifySummary",
    "comparable_text",
    "compare_parameters",
    "load_last",
    "now_iso",
    "parameter_message",
    "sample_quotas",
    "sample_covers_all",
    "save_last",
    "select_parts",
    "spread_indices",
]

#: ``pf_meta`` key of the last completed check (JSON of :class:`VerifyRun`).
LAST_RESULT_KEY = "altium.verify.last"

SampleMode = Literal["first", "spread"]
VerifyScope = Literal["sample", "all", "part_numbers"]


class VerifyError(ValueError):
    """The selection cannot be made (German message; API: the job fails with it)."""


# --------------------------------------------------------------------------- models


class FootprintCheck(BaseModel):
    """One footprint link of a part (``Footprint Ref`` / ``Footprint Ref n``)."""

    column: str
    footprint: str
    library: str | None = None  # stored Footprint Path (n)
    assigned: bool = False  # Altium lists it as implementation of the part
    library_found: bool = False  # the PcbLib file exists
    in_library: bool | None = None  # the PcbLib contains the footprint (None = could not be read)


class ParameterDiff(BaseModel):
    """A field the DbLib adds to the design whose value in Altium differs from the database row."""

    parameter: str = Field(description="Parametername in Altium (= Spalte; „Description“ für [Description])")
    database: str | None = Field(
        default=None, description="Wert in der Datenbank (null = leer – Altium fügt dann keinen Parameter hinzu)"
    )
    altium: str | None = Field(default=None, description="Wert, den Altium liefert (null = kein solcher Parameter)")


class VerifiedPart(BaseModel):
    table: str
    part_number: str
    status: Literal["ok", "warning", "error"]
    symbol_found: bool = False
    library_ref: str | None = None
    lib_reference: str = ""
    symbol_path: str = ""
    pin_count: int | None = None
    expected_pins: int | None = None
    footprint_found: bool = False  # every footprint link verified: assigned, library exists and contains it
    footprint: str | None = None
    footprints: list[str] = Field(default_factory=list)  # implementations Altium created for the part
    footprint_checks: list[FootprintCheck] = Field(default_factory=list)
    comment: str = ""  # Comment of the part as Altium places it
    comment_visible: bool | None = None  # shown on the schematic (None = not reported)
    visible_parameters: list[str] = Field(default_factory=list)  # parameters shown on the schematic (incl. Comment)
    description: str = Field(default="", description="Description, wie Altium das Bauteil platziert ([Description])")
    parameters: dict[str, str] = Field(
        default_factory=dict, description="Parameter, die Altium für das Bauteil liefert (Name → Wert, in Altiums Reihenfolge)"
    )
    parameters_checked: int = Field(
        default=0,
        description="Mit der Datenbank verglichene Felder (zum Design hinzugefügt, mit Description); 0 = nicht verglichen",
    )
    parameter_diffs: list[ParameterDiff] = Field(
        default_factory=list, description="Felder, deren Wert in Altium von der Datenbank abweicht (je eine Warnung)"
    )
    extra_parameters: list[str] = Field(
        default_factory=list,
        description="Parameter, die Altium liefert, die aber kein zum Design hinzugefügtes Datenbankfeld sind (z. B. aus dem Symbol)",
    )
    messages: list[str] = Field(default_factory=list)


class VerifySummary(BaseModel):
    """Counts and timing of one check."""

    message: str = Field(description="Ergebnis als deutscher Satz (wie job.message)")
    checked: int = 0
    ok: int = 0
    warnings: int = 0
    errors: int = 0
    total: int = Field(default=0, description="Kandidaten: Bauteile der gewählten Kategorien bzw. genannte Teilenummern")
    categories: int = Field(default=0, description="Kategorien mit mindestens einem geprüften Bauteil")
    temporarily_installed: bool = False
    duration_s: float = 0.0
    altium_runs: int = Field(default=0, description="Altium-Skriptläufe (einer je RESOLVE_BATCH_SIZE Bauteile)")
    resolve_s: float = 0.0


class VerifyRun(BaseModel):
    """A completed check (``GET /api/altium/verify/last``; stored per library)."""

    scope: VerifyScope = Field(description="sample = Stichprobe, all = alle Bauteile, part_numbers = genannte Bauteile")
    sample: SampleMode | None = Field(default=None, description="Art der Stichprobe (nur scope = sample)")
    limit: int | None = Field(default=None, description="Gewünschte Größe der Stichprobe (nur scope = sample)")
    tables: list[str] = Field(default_factory=list, description="Auf diese Kategorien beschränkt (leer = alle)")
    started: str = Field(description="Beginn (ISO, lokale Zeit)")
    finished: str = Field(description="Ende (ISO, lokale Zeit)")
    summary: VerifySummary
    results: list[VerifiedPart] = Field(default_factory=list)


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- parameters

#: ASCII spellings of „±“ (``+/-``, ``+ / -``)
_PLUS_MINUS = re.compile(r"\+\s*/\s*-")
#: Longest value quoted in a message (the full values are in ``parameters`` / ``parameter_diffs``)
_MESSAGE_VALUE_LIMIT = 80


def comparable_text(value: object) -> str:
    """Text of a parameter value for comparing what Altium returns with the database value.

    NFKC (micro sign U+00B5 = Greek mu U+03BC, ohm sign U+2126 = Greek capital omega U+03A9, ``℃`` = ``°C``,
    no-break and other special blanks = blank, ``…`` = ``...``), ``+/-`` = ``±``, without invisible format characters, blanks
    collapsed and trimmed; ``None`` and blank values give ``""`` (= absent: Altium adds no parameter for them).
    Case is kept – Altium never changes it, a differing case is a different value.
    """
    if value is None:
        return ""
    text = strip_format_chars(unicodedata.normalize("NFKC", str(value)))
    return " ".join(_PLUS_MINUS.sub("±", text).split())


def _name_key(name: str) -> str:
    return " ".join(str(name).split()).casefold()


def _stored_text(value: Any) -> str | None:
    """A database value as stored, ``None`` when blank."""
    return str(value) if comparable_text(value) else None


@dataclass
class ParameterComparison:
    """Result of :func:`compare_parameters`."""

    checked: int  # database fields compared (added to the design, Description included)
    diffs: list[ParameterDiff]
    extra: list[str]  # parameters Altium returns that are no database field added to the design


def compare_parameters(category: CategoryDef, row: Mapping[str, Any], parameters: Mapping[str, str],
                       description: str | None) -> ParameterComparison:
    """Compare the parameters (and Description) Altium returns for a part with its database ``row``.

    Compared are the fields the DbLib adds to the design as parameters of the same name (implicit default or
    a field map without ``AddMode=1``; :func:`partforge.altium.dblib.field_map_for`) and ``Description``
    (reserved ``[Description]`` → ``description``). Other reserved mappings (``[Library Ref]``,
    ``[Footprint Ref]`` …) and fields with ``add_to_design=False`` are no parameters. Values are compared with
    :func:`comparable_text`; blank counts as absent. Differences come in the order of the category's fields, the
    Description last (it is generated from the fields – the differing field is the cause).
    """
    from .dblib import ADD_MODE_DO_NOT_ADD, field_map_for

    remaining: dict[str, tuple[str, str]] = {}
    for name, value in parameters.items():
        remaining.setdefault(_name_key(name), (str(name), "" if value is None else str(value)))
    stored: dict[str, Any] = {}  # column (case-insensitive) -> value; once per part, not per field
    for key, value in row.items():
        stored.setdefault(_name_key(key), value)
    diffs: list[ParameterDiff] = []
    description_diff: list[ParameterDiff] = []  # last: generated from the fields – the differing field is the cause
    checked = 0
    for fdef in category.fields:
        mapping = field_map_for(category.table, fdef)
        reserved = mapping is not None and mapping.parameter_name.startswith("[")
        if reserved:
            if mapping is None or mapping.parameter_name.casefold() != "[description]":
                continue  # symbol / footprint links: no parameters
            name, altium = "Description", description
        elif mapping is not None and mapping.add_mode == ADD_MODE_DO_NOT_ADD:
            continue
        else:
            name = mapping.parameter_name if mapping is not None and mapping.parameter_name else fdef.column
            name, altium = remaining.pop(_name_key(name), (name, None))
        checked += 1
        database = _stored_text(stored.get(_name_key(fdef.column)))
        if comparable_text(database) == comparable_text(altium):
            continue
        diff = ParameterDiff(parameter=name, database=database, altium=altium if comparable_text(altium) else None)
        (description_diff if reserved else diffs).append(diff)
    extra = [name for name, value in remaining.values() if comparable_text(value)]
    return ParameterComparison(checked=checked, diffs=diffs + description_diff, extra=extra)


def _quoted(value: str) -> str:
    text = " ".join(value.split())
    if len(text) > _MESSAGE_VALUE_LIMIT:
        text = text[: _MESSAGE_VALUE_LIMIT - 1].rstrip() + "…"
    return f"„{text}“"


def parameter_message(diff: ParameterDiff) -> str:
    """German warning for one difference – „Altium liefert für „Slew Rate“ keinen Wert – in der Datenbank steht
    „290V/µs“.“ (long values shortened; the full ones are in the result)."""
    what = f"Altium liefert für „{diff.parameter}“"
    if diff.altium is None:
        return f"{what} keinen Wert – in der Datenbank steht {_quoted(diff.database or '')}."
    if diff.database is None:
        return f"{what} {_quoted(diff.altium)} – in der Datenbank ist das Feld leer."
    return f"{what} {_quoted(diff.altium)} – in der Datenbank steht {_quoted(diff.database)}."


# --------------------------------------------------------------------------- sampling


def sample_quotas(counts: Sequence[int], limit: int) -> list[int]:
    """Parts to take per category for a ``spread`` sample of ``limit`` parts.

    Proportional to the category sizes (largest remainder), at least one per non-empty
    category, never more than a category holds; ties go to the earlier category.
    Deterministic. ``limit`` >= the number of parts takes everything; more non-empty
    categories than ``limit`` give one part per category.
    """
    sizes = [max(0, int(n)) for n in counts]
    total = sum(sizes)
    limit = max(0, int(limit))
    if total == 0:
        return [0] * len(sizes)
    if limit >= total:
        return list(sizes)
    ideal = [limit * n / total for n in sizes]
    quotas = [min(n, max(1, math.floor(x))) if n else 0 for n, x in zip(sizes, ideal, strict=True)]
    # over the limit (minimum of one per category): take back from the most over-allocated categories
    while sum(quotas) > limit:
        candidates = [i for i, q in enumerate(quotas) if q > 1]
        if not candidates:
            break  # one per category is the floor
        worst = max(candidates, key=lambda i: (quotas[i] - ideal[i], -i))
        quotas[worst] -= 1
    # below the limit: hand out the rest by largest remainder
    while sum(quotas) < limit:
        candidates = [i for i, q in enumerate(quotas) if q < sizes[i]]
        if not candidates:
            break
        best = max(candidates, key=lambda i: (ideal[i] - quotas[i], -i))
        quotas[best] += 1
    return quotas


def spread_indices(count: int, quota: int) -> list[int]:
    """``quota`` evenly spaced positions in ``range(count)`` (the middle of equal segments)."""
    count, quota = max(0, int(count)), max(0, int(quota))
    if quota >= count:
        return list(range(count))
    return [((2 * j + 1) * count) // (2 * quota) for j in range(quota)]


# --------------------------------------------------------------------------- selection


@dataclass
class Selection:
    """Parts to check: ``[(table, row)]`` in check order plus what was asked for."""

    parts: list[tuple[str, dict[str, Any]]]
    total: int  # candidates (parts of the selected categories / named part numbers)
    scope: VerifyScope
    sample: SampleMode | None = None
    limit: int | None = None
    tables: list[str] = field(default_factory=list)

    @property
    def categories(self) -> int:
        return len({table for table, _ in self.parts})


def _named_parts(part_numbers: Sequence[str]) -> Selection:
    from ..db import parts

    found: list[tuple[str, dict[str, Any]]] = []
    missing: list[str] = []
    for pn in dict.fromkeys(p.strip() for p in part_numbers if p and p.strip()):
        hit = parts.find_part(pn)
        if hit is None:
            missing.append(pn)
        else:
            found.append((hit[0], dict(hit[1])))
    if missing:
        raise VerifyError(f"Teilenummer(n) nicht gefunden: {', '.join(missing[:10])}.")
    return Selection(parts=found, total=len(found), scope="part_numbers")


def _categories(tables: Sequence[str] | None) -> list[Any]:
    from ..db import categories

    wanted = {t.casefold() for t in tables or []}
    cats = [c for c in categories.list_categories(with_counts=False) if c.altium_enabled]
    if wanted:
        unknown = wanted - {c.table.casefold() for c in cats}
        if unknown:
            raise VerifyError(f"Unbekannte oder für Altium deaktivierte Kategorien: {', '.join(sorted(unknown))}.")
        cats = [c for c in cats if c.table.casefold() in wanted]
    return cats


def select_parts(
    *,
    part_numbers: Sequence[str] | None = None,
    tables: Sequence[str] | None = None,
    all_parts: bool = False,
    limit: int | None = 20,
    sample: SampleMode = "spread",
) -> Selection:
    """The parts a check covers (see the module docstring). Raises :class:`VerifyError`."""
    from ..db import parts

    if part_numbers:
        return _named_parts(part_numbers)
    cats = _categories(tables)
    chosen = [c.table for c in cats] if tables else []
    if all_parts:
        selected: list[tuple[str, dict[str, Any]]] = []
        total = 0
        for cat in cats:
            rows, count = parts.query_parts(cat.table, sort="Part Number", limit=None)
            selected.extend((cat.table, dict(r)) for r in rows)
            total += count
        return Selection(parts=selected, total=total, scope="all", tables=chosen)
    size = max(1, int(limit or 20))
    if sample in ("first", "spread") and _candidates(cats) <= size:
        return select_parts(tables=tables, all_parts=True)  # the "sample" holds every part: say so (F6)
    if sample == "first":
        selected = []
        total = 0
        for cat in cats:
            remaining = size - len(selected)
            rows, count = parts.query_parts(cat.table, sort="Part Number", limit=max(remaining, 1))
            if remaining > 0:
                selected.extend((cat.table, dict(r)) for r in rows[:remaining])
            total += count
        return Selection(parts=selected, total=total, scope="sample", sample="first", limit=size, tables=chosen)
    numbers = [(cat.table, parts.matching_part_numbers(cat.table)) for cat in cats]
    quotas = sample_quotas([len(pns) for _, pns in numbers], size)
    selected = []
    for (table, pns), quota in zip(numbers, quotas, strict=True):
        for index in spread_indices(len(pns), quota):
            row = parts.get_part(table, pns[index])
            if row is not None:  # deleted meanwhile: the sample just gets smaller
                selected.append((table, dict(row)))
    return Selection(parts=selected, total=sum(len(pns) for _, pns in numbers), scope="sample", sample="spread",
                     limit=size, tables=chosen)


def sample_covers_all(tables: Sequence[str] | None, limit: int | None) -> bool:
    """Whether a sample of ``limit`` parts holds every part of the selection (then it is reported as ``"all"``)."""
    try:
        return _candidates(_categories(tables)) <= max(1, int(limit or 20))
    except Exception:  # noqa: BLE001 - unknown tables etc.: the job reports them
        return False


def _candidates(cats: Sequence[Any]) -> int:
    """Number of parts in the given categories."""
    from sqlalchemy import func, select

    from ..db import categories as cat_db
    from ..db import core

    total = 0
    with core.read() as conn:
        for cat in cats:
            total += int(conn.execute(select(func.count()).select_from(cat_db.table_for(cat))).scalar_one())
    return total


# --------------------------------------------------------------------------- last result


def save_last(run: VerifyRun) -> None:
    """Store ``run`` as the last check of the open library (``pf_meta``)."""
    from ..db import meta

    meta.set_meta(LAST_RESULT_KEY, run.model_dump_json())


def load_last() -> VerifyRun | None:
    """The last completed check of the open library, ``None`` if there is none (or it is unreadable)."""
    from ..db import meta

    raw = meta.get_meta(LAST_RESULT_KEY)
    if not raw:
        return None
    try:
        return VerifyRun.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        log.warning("Gespeichertes Prüfergebnis nicht lesbar: %s", exc)
        return None
