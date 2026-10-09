"""Example part number of a template, split into its meaningful segments (template cards, docs).

    example = template_example(template)    # TemplateExample | None – cached on the template object
    segments = mpn_segments(template, size="0603", value=10e3, codes={...})   # list[MpnSegment]
    facts = template_facts(template)         # TemplateFacts: mode, value range, E-series, jumper

The example is what the series assistant would generate for a typical value (10 kΩ, 100 nF,
10 µH) in a common size (0603, else the middle size) with the template's default codes; a
matrix/catalog template takes the orderable part closest to that value (capacitors: preferably
50 V; catalogs: preferably a part in production). ``CRCW060310K0FKEA`` becomes ``CRCW | 0603 | 10K0 | F | K | EA`` with the meaning of each
segment (size, value, tolerance …). Nothing here needs a library.
"""
from __future__ import annotations

import logging
import math
import weakref
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..eseries import SERIES, values_in_range
from .engine import (
    CompiledTemplate,
    MpnError,
    Resolution,
    base_attrs,
    catalog_attrs,
    compact,
    compile_template,
    encode_mpn,
    format_value,
    resolve,
)
from .formats import ValueCodeError, encode_value
from .model import MpnTemplate

log = logging.getLogger(__name__)

__all__ = ["MpnSegment", "TemplateExample", "TemplateFacts", "mpn_segments", "template_example", "template_facts"]

SegmentKind = Literal["literal", "size", "value", "code"]
TemplateMode = Literal["rules", "matrix", "catalog", "open"]

#: Short labels of well-known variables for narrow displays ("Tol.", "TK", "Verp." …)
SHORT_LABELS: dict[str, str] = {
    "size": "Größe", "value": "Wert", "tolerance": "Tol.", "tcr": "TK", "packaging": "Verp.", "cspec": "Verp.",
    "packing": "Gurt", "voltage": "Spg.", "dielectric": "Diel.", "thickness": "Dicke", "marking": "Druck",
    "power": "Leist.", "quantity": "Menge", "termination": "Anschl.", "char": "Merkm.", "spec": "Spez.",
}
#: Typical example value per value unit
TYPICAL_VALUES: dict[str, float] = {"Ω": 10e3, "F": 100e-9, "H": 10e-6}
_PREFERRED_SIZE = "0603"
_PREFERRED_VOLTAGE = 50.0
_MAX_TRIES = 400


class MpnSegment(BaseModel):
    """One piece of a part number: fixed text or the code of a variable with its meaning."""

    text: str = Field(description="Zeichen der Teilenummer, z. B. 0603, 10K0, F")
    kind: SegmentKind = Field(description="literal = fester Text, size, value, code = Code einer Variable")
    name: str | None = Field(default=None, description="Variablenname (size, value, tolerance …)")
    label: str = Field(description="Bezeichnung, z. B. Baugröße, Toleranz; „fest“ für festen Text")
    short: str = Field(default="", description="Kurzform für enge Darstellungen (Größe, Tol., TK …)")
    meaning: str | None = Field(default=None, description="Bedeutung, z. B. ±1 %, 10kΩ, 0603 (1608)")


class TemplateExample(BaseModel):
    """A typical part of a template: part number, size, value and the part number's segments."""

    mpn: str
    size: str | None = None
    value: float | None = Field(default=None, description="Wert in der Basiseinheit")
    value_text: str | None = Field(default=None, description="Wert als Feldtext, z. B. 10kΩ")
    valid: bool = Field(default=True, description="False: laut Vorlage nicht bestellbar (message sagt warum)")
    message: str | None = None
    codes: dict[str, str] = Field(default_factory=dict)
    attrs: dict[str, str] = Field(default_factory=dict, description="Zeilenattribute (für die Feldwerte)")
    segments: list[MpnSegment] = Field(default_factory=list)


class TemplateFacts(BaseModel):
    """Key facts of a template for lists (no matrices, no catalogs)."""

    mode: TemplateMode = Field(description="rules = Wertebereiche, matrix = Lieferbarkeitsmatrix, catalog = feste "
                                           "Teilenummern, open = ohne Gültigkeitsdaten")
    value_range: list[float] | None = Field(default=None, description="[kleinster, größter] Wert (Basiseinheit)")
    e_series: list[str] = Field(default_factory=list, description="E-Reihen der Regeln (E24, E96 …)")
    jumper: bool = Field(default=False, description="Die Serie hat 0-Ω-Brücken")


# --------------------------------------------------------------------------- segments


def _short(name: str, label: str) -> str:
    if name in SHORT_LABELS:
        return SHORT_LABELS[name]
    return f"{label[:5]}." if len(label) > 7 else label


def _size_meaning(template: MpnTemplate, ct: CompiledTemplate, size: str) -> str:
    spec = template.size_spec(size)
    if spec is not None and spec.label:
        return spec.label
    option = next((o for o in (ct.size_var.options if ct.size_var else []) if (o.value or o.code) == size), None)
    return (option.label if option is not None and option.label else None) or size


def mpn_segments(template: MpnTemplate, *, size: str, value: float, codes: Mapping[str, str],
                 jumper: bool = False) -> list[MpnSegment]:
    """Segments of the part number ``encode_mpn`` builds for these inputs (empty codes are left out).
    Raises :class:`MpnError` like :func:`encode_mpn`."""
    ct = compile_template(template)
    if not ct.segments:
        raise MpnError("Diese Vorlage hat kein Teilenummern-Muster (Katalog mit festen Teilenummern).")
    if size not in ct.size_code:
        raise MpnError(f"Baugröße {size} gibt es in der Vorlage „{template.title}“ nicht.")
    out: list[MpnSegment] = []
    for seg in ct.segments:
        if seg.literal is not None:
            if seg.literal:
                out.append(MpnSegment(text=seg.literal, kind="literal", label="fest"))
            continue
        name = seg.variable or ""
        if name == "size":
            out.append(MpnSegment(text=ct.size_code[size], kind="size", name="size", label="Baugröße",
                                  short=SHORT_LABELS["size"], meaning=_size_meaning(template, ct, size)))
        elif name == "value":
            if jumper:
                if template.jumper is None:
                    raise MpnError("Diese Serie hat keine 0-Ω-Brücke.")
                out.append(MpnSegment(text=template.jumper.value_code, kind="value", name="value", label="Brücke",
                                      short="Brücke", meaning=f"0 {template.value_unit}"))
                continue
            try:
                text = encode_value(value, ct.value_format(codes))
            except ValueCodeError as exc:
                raise MpnError(str(exc)) from exc
            label = ct.value_var.label if ct.value_var is not None else "Wert"
            out.append(MpnSegment(text=text, kind="value", name="value", label=label, short=SHORT_LABELS["value"],
                                  meaning=format_value(value, template.value_unit)))
        else:
            var = ct.variables[name]
            if name not in codes:
                raise MpnError(f"Für „{var.label}“ fehlt ein Code.")
            option = var.option(str(codes[name]), size)
            if option is None:
                raise MpnError(f"„{codes[name]}“ ist kein gültiger Code für „{var.label}“.")
            if not option.code:
                continue
            out.append(MpnSegment(text=option.code, kind="code", name=name, label=var.label,
                                  short=_short(name, var.label), meaning=option.label or option.value or option.code))
    return out


# --------------------------------------------------------------------------- example


def _example_size(template: MpnTemplate, sizes: list[str]) -> str | None:
    if not sizes:
        return None
    if _PREFERRED_SIZE in sizes:
        return _PREFERRED_SIZE
    return sizes[(len(sizes) - 1) // 2]


def _typical(template: MpnTemplate, span: tuple[float, float] | None) -> float:
    typical = TYPICAL_VALUES.get(template.value_unit)
    if typical is not None:
        return typical
    if span is not None and span[0] > 0:
        return math.sqrt(span[0] * span[1])
    return 1.0


def _distance(value: float, typical: float) -> float:
    if value <= 0 or typical <= 0:
        return math.inf
    return abs(math.log10(value / typical))


def _voltage(text: str | None) -> float | None:
    from ..units import parse_quantity

    q = parse_quantity(text or "", "V")
    return q.value if q is not None and q.unit in ("", "V") else None


def _default_tolerance(ct: CompiledTemplate) -> dict[str, str]:
    """The series' default tolerance code (the preview's selection without a tolerance chosen)."""
    var = ct.variables.get("tolerance")
    if var is None:
        return {}
    options = [o for o in var.options if not o.attrs.get("jumper_only")]
    chosen = next((o for o in options if o.default), options[0] if options else None)
    return {"tolerance": chosen.code} if chosen is not None else {}


def _rule_span(ct: CompiledTemplate, size: str) -> tuple[float, float] | None:
    spans = [(lo, hi) for r in ct.rules if not r.sizes or size in r.sizes for lo, hi in r.ranges]
    if not spans:
        return None
    return min(lo for lo, _ in spans), max(hi for _, hi in spans)


def _rule_example(template: MpnTemplate, ct: CompiledTemplate, size: str) -> tuple[float, Resolution] | None:
    fixed = _default_tolerance(ct)
    span = _rule_span(ct, size)
    typical = _typical(template, span)
    candidates: list[float] = [typical]
    if span is not None and span[1] > 0:
        values: set[float] = set()
        for name in ("E24", "E96"):
            values.update(values_in_range(name, max(span[0], 1e-12), span[1]))
        candidates += sorted(values, key=lambda v: (_distance(v, typical), v))
    first_failure: tuple[float, Resolution] | None = None
    for value in candidates[:_MAX_TRIES]:
        res = resolve(template, size=size, value=value, fixed=fixed)
        if res.ok:
            return value, res
        if first_failure is None:
            first_failure = (value, res)
    return first_failure


def _matrix_example(template: MpnTemplate, ct: CompiledTemplate, size: str) -> tuple[float, Resolution] | None:
    cells = ct.cells_by_size.get(size) or list(template.availability)
    if not cells:
        return None
    typical = _typical(template, None)
    voltage_var = ct.variables.get("voltage")

    def rank(cell: Any) -> tuple[float, float]:
        option = voltage_var.option(cell.codes.get("voltage", ""), cell.size) if voltage_var else None
        volts = _voltage(option.value if option is not None else None)
        return _distance(ct.cell_value(cell), typical), abs((volts or 0.0) - _PREFERRED_VOLTAGE)

    first_failure: tuple[float, Resolution] | None = None
    tolerance = _default_tolerance(ct)
    for cell in sorted(cells, key=rank)[:_MAX_TRIES]:
        value = ct.cell_value(cell)
        fixed = {**tolerance, **{k: cell.codes[k] for k in template.availability_keys if k in cell.codes}}
        res = resolve(template, size=cell.size, value=value, fixed=fixed)
        if res.ok:
            return value, res
        if first_failure is None:
            first_failure = (value, res)
    return first_failure


def _catalog_example(template: MpnTemplate, size: str | None) -> TemplateExample | None:
    entries = [e for e in template.catalog if e.size == size] or list(template.catalog)
    if not entries:
        return None
    typical = _typical(template, None)
    ranked = []
    for index, entry in enumerate(entries):
        value, attrs = catalog_attrs(template, entry)
        volts = _voltage(attrs.get("voltage"))
        retired = 1 if attrs.get("lifecycle") else 0  # prefer a part in production (no NRND/discontinued)
        ranked.append((retired, _distance(value or 0.0, typical), abs((volts or 0.0) - _PREFERRED_VOLTAGE)
                       if volts is not None else 0.0, index, entry, value, attrs))
    *_rank, entry, value, attrs = min(ranked, key=lambda item: item[:4])
    segments: list[MpnSegment] = []
    if template.pattern and value is not None:
        try:
            built = mpn_segments(template, size=entry.size, value=value, codes=entry.codes)
            if compact("".join(s.text for s in built)) == compact(entry.mpn):
                segments = built
        except MpnError:
            segments = []
    if not segments:
        segments = [MpnSegment(text=entry.mpn, kind="literal", label="Katalog",
                               meaning="Teilenummer aus dem Katalog der Vorlage")]
    return TemplateExample(mpn=entry.mpn, size=entry.size, value=value, value_text=attrs.get("value"),
                           codes=dict(entry.codes), attrs=attrs, segments=segments)


def _build_example(template: MpnTemplate) -> TemplateExample | None:
    size = _example_size(template, template.size_names())
    if template.kind == "catalog":
        return _catalog_example(template, size)
    if size is None:
        return None
    ct = compile_template(template)
    if template.availability:
        found = _matrix_example(template, ct, size)
    elif template.rules:
        found = _rule_example(template, ct, size)
    else:
        fixed = _default_tolerance(ct)
        value = _typical(template, None)
        found = (value, resolve(template, size=size, value=value, fixed=fixed))
    if found is None:
        return None
    value, res = found
    size = res.cell.size if res.cell is not None else size
    mpn = encode_mpn(template, size=size, value=value, codes=res.codes)
    segments = mpn_segments(template, size=size, value=value, codes=res.codes)
    attrs = {**res.attrs, **base_attrs(template, size, value, mpn)}
    message = None if res.ok else ("; ".join(res.messages) or "Laut Vorlage nicht bestellbar.")
    return TemplateExample(mpn=mpn, size=size, value=value, value_text=attrs.get("value"), valid=res.ok,
                           message=message, codes=dict(res.codes), attrs=attrs, segments=segments)


def template_example(template: MpnTemplate) -> TemplateExample | None:
    """Typical part of ``template`` (see the module docstring); ``None`` if the template cannot build one.
    Cached on the template object (built-in templates are built once; a copy builds its own – the cache
    holds a weak reference to its template, which keeps deep copies free of cycles); never raises."""
    cached = template._example
    if isinstance(cached, tuple) and len(cached) == 2 and cached[0]() is template:
        return cached[1]
    try:
        example = _build_example(template)
    except (MpnError, ValueError, KeyError, IndexError) as exc:
        log.info("Kein Beispiel für Serienvorlage %s: %s", template.id, exc)
        example = None
    template._example = (weakref.ref(template), example)
    return example


# --------------------------------------------------------------------------- facts


def template_facts(template: MpnTemplate) -> TemplateFacts:
    """Mode, value range, E-series and jumper of a template (cheap; never raises)."""
    if template.kind == "catalog":
        mode: TemplateMode = "catalog"
    elif template.availability:
        mode = "matrix"
    elif template.rules:
        mode = "rules"
    else:
        mode = "open"
    values: list[float] = []
    series: set[str] = set()
    try:
        ct = compile_template(template)
        if mode == "rules":
            for rule in ct.rules:
                for lo, hi in rule.ranges:
                    values += [lo, hi]
                series.update(rule.series)
        elif mode == "matrix":
            values = [ct.cell_value(cell) for cell in template.availability]
        elif mode == "catalog":
            values = [v for v in (catalog_attrs(template, e)[0] for e in template.catalog) if v is not None]
    except (MpnError, ValueError, KeyError) as exc:
        log.info("Kennzahlen der Serienvorlage %s nicht bestimmbar: %s", template.id, exc)
    positive = [v for v in values if v > 0]
    value_range = [float(f"{min(positive):.12g}"), float(f"{max(positive):.12g}")] if positive else None
    return TemplateFacts(mode=mode, value_range=value_range, e_series=[name for name in SERIES if name in series],
                         jumper=template.jumper is not None)
