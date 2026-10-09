"""Template engine: compile a :class:`MpnTemplate`, resolve codes, encode and decode part numbers.

    res = resolve(template, size="0603", value=10e3, fixed={"tolerance": "F"})   # rules/matrix + defaults
    mpn = encode_mpn(template, size="0603", value=10e3, codes=res.codes)        # CRCW060310K0FKEA
    decoded = decode_mpn(template, "CRCW060310K0FKEA")                          # -> Decoded | None
    size = resolve_size(template, "1608")                                       # "0603" (name/code/metric)

Part numbers are compared in a *compact* form: upper case, without ``-`` and whitespace
(``ERJ-3EKF1002V`` == ``ERJ3EKF1002V``); encoding always produces the canonical spelling
of the pattern. A part number that only matches in another spelling of the value code
(``CRCW0603K100FKEA`` for ``CRCW0603100RFKEA``) is decoded, but never ``valid``.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache

from pydantic import BaseModel, Field

from ...db.values import format_field_quantity
from ..eseries import SERIES
from ..text import strip_format_chars
from ..units import parse_quantity
from .formats import ValueCodeError, ValueFormat, decode_value, encode_value, value_regex
from .model import (
    AvailabilityCell,
    CatalogEntry,
    CodeOption,
    MpnTemplate,
    Segment,
    ValueRule,
    Variable,
    parse_pattern,
)

log = logging.getLogger(__name__)

__all__ = [
    "CompiledTemplate",
    "Decoded",
    "MpnError",
    "Resolution",
    "compact",
    "compile_template",
    "decode_mpn",
    "encode_mpn",
    "equivalent_option",
    "find_option",
    "format_value",
    "in_series",
    "parse_series",
    "render_fields",
    "resolve",
    "resolve_size",
    "series_of_value",
]

_REL = 1e-9


class MpnError(ValueError):
    """German message: a part number cannot be built or read with a template."""


def compact(mpn: str) -> str:
    """Comparison form of a part number: upper case, no ``-``, no whitespace, no invisible format characters
    (soft hyphen, zero-width space … copied from web pages – :func:`partforge.domain.text.strip_format_chars`)."""
    return re.sub(r"[\s\-]+", "", strip_format_chars(str(mpn or ""))).upper()


# --------------------------------------------------------------------------- E-series helpers

_SERIES_SETS: dict[str, frozenset[float]] = {
    name: frozenset(round(m, 6) for m in values) for name, values in SERIES.items()
}


def _mantissa(value: float) -> float:
    """Mantissa in [1, 10) rounded to 6 decimals (float noise removed, no tolerance beyond that)."""
    exp = math.floor(math.log10(value))
    m = round(value / 10.0**exp, 6)
    if m >= 10:
        m = round(m / 10, 6)
    elif m < 1:
        m = round(m * 10, 6)
    return m


def in_series(value: float, series: Iterable[str]) -> bool:
    """True if ``value`` is a value of one of the E-series (e.g. ``["E24", "E96"]``)."""
    if value <= 0:
        return False
    m = _mantissa(value)
    return any(m in _SERIES_SETS.get(name.upper(), frozenset()) for name in series)


def series_of_value(value: float) -> str | None:
    """Smallest E-series containing ``value`` (E3 … E192) or None."""
    if value <= 0:
        return None
    m = _mantissa(value)
    return next((name for name, values in _SERIES_SETS.items() if m in values), None)


def parse_series(spec: str | Iterable[str] | None) -> list[str]:
    """``"E24+E96"``, ``"E24, E96"`` or ``["E24", "E96"]`` -> ``["E24", "E96"]`` (validated)."""
    if spec is None:
        return []
    items = re.split(r"[\s,;+/]+", spec) if isinstance(spec, str) else [str(s) for s in spec]
    out: list[str] = []
    for item in items:
        name = item.strip().upper()
        if not name:
            continue
        if not name.startswith("E"):
            name = f"E{name}"
        if name not in SERIES:
            raise MpnError(f"Unbekannte E-Reihe „{item}“ (erlaubt: {', '.join(SERIES)}).")
        if name not in out:
            out.append(name)
    return out


# --------------------------------------------------------------------------- text helpers


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("±", "").replace("+/-", "").replace("+-", "")).casefold()


@lru_cache(maxsize=4096)
def _quantity(text: str) -> tuple[float, str] | None:
    q = parse_quantity(text)
    if q is None:
        return None
    return q.value, q.unit


def find_option(variable: Variable, text: str | None, size: str | None = None) -> CodeOption | None:
    """Option of ``variable`` meant by ``text`` (value text, numeric value with unit, code, label).

    A text with a unit (``50V``, ``1%``) is only compared numerically; a bare text is first
    taken as a code (``F``), then compared with labels and unit-less numbers."""
    if text is None:
        return None
    wanted = str(text).strip()
    if not wanted:
        return None
    options = variable.options_for(size) or variable.options
    norm = _norm(wanted)
    for option in options:
        if option.value and _norm(option.value) == norm:
            return option
    q = _quantity(wanted.replace("±", ""))
    if q is not None and q[1]:
        for option in options:
            oq = _quantity(option.value.replace("±", "")) if option.value else None
            if oq and oq[1] == q[1] and math.isclose(oq[0], q[0], rel_tol=1e-6):
                return option
        return None
    for option in options:
        if option.code.upper() == wanted.upper():
            return option
    for option in options:
        if option.label and _norm(option.label) == norm:
            return option
    if q is not None:
        for option in options:
            oq = _quantity(option.value.replace("±", "")) if option.value else None
            if oq and math.isclose(oq[0], q[0], rel_tol=1e-6):
                return option
    return None


_METRIC_SUFFIX_RE = re.compile(r"\s*(?:m|metric|metrisch)$", re.IGNORECASE)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def resolve_size(template: MpnTemplate, text: str) -> str:
    """Size name of ``template`` meant by ``text`` – never by numeric similarity (``1005`` is not ``01005``).

    Tried in this order, the first step with a hit wins: size name (``0603``), size code of the
    part number (``1J``, ``10``), label (``0603 (1608)``), metric code (``1608``, ``1608M``,
    ``1608 metrisch``), chip-size aliases of the footprint generator (``R0603``, ``0603/1608``).
    Raises :class:`MpnError` (German) for unknown or ambiguous input."""
    wanted = " ".join(str(text or "").split())
    names = template.size_names()
    available = ", ".join(names) or "–"
    if not wanted:
        raise MpnError(f"Bitte eine Baugröße angeben (verfügbar: {available}).")
    folded = wanted.casefold()
    squashed = _squash(wanted)
    ct = compile_template(template)
    size_options = ct.size_var.options if ct.size_var is not None else []
    metric = _METRIC_SUFFIX_RE.sub("", wanted).strip()
    steps: list[list[str]] = [
        [n for n in names if n.casefold() == folded],
        [o.value or o.code for o in size_options if compact(o.code) and compact(o.code) == compact(wanted)],
        [s.size for s in template.sizes if s.label and _squash(s.label) == squashed]
        + [o.value or o.code for o in size_options if o.label and _squash(o.label) == squashed],
        [s.size for s in template.sizes if metric and s.attrs.get("metric") == metric],
    ]
    for hits in steps:
        found = [h for h in dict.fromkeys(hits) if h in names]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise MpnError(f"Baugröße „{wanted}“ ist mehrdeutig ({', '.join(found)}) – bitte genau angeben.")
    try:
        from ...footprints import normalize_size  # chip aliases: R0603, 0603/1608, RESC1608 …

        alias = normalize_size(wanted)
    except ValueError:
        alias = None
    if alias is not None and alias in names:
        return alias
    raise MpnError(f"Baugröße „{wanted}“ gibt es in der Serie {template.title} nicht (verfügbar: {available}).")


@lru_cache(maxsize=65536)
def format_value(value: float, unit: str) -> str:
    """Canonical field text of a value (``10kΩ``, ``100nF``, ``0Ω``)."""
    if value == 0:
        return f"0{unit}"
    return format_field_quantity(value, unit)


_ATTR_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def render_fields(fields: Mapping[str, str], attrs: Mapping[str, str]) -> dict[str, str]:
    """Fill the field templates; a field whose placeholders are not all set stays empty."""
    out: dict[str, str] = {}
    for column, template in fields.items():
        missing = False

        def repl(m: re.Match[str]) -> str:
            nonlocal missing
            value = attrs.get(m.group(1))
            if value is None or not str(value).strip():
                missing = True
                return ""
            return str(value)

        text = _ATTR_RE.sub(repl, template)
        if not missing and text.strip():
            out[column] = text.strip()
    return out


# --------------------------------------------------------------------------- compiled template


@dataclass(frozen=True)
class _Rule:
    rule: ValueRule
    sizes: frozenset[str]
    when: dict[str, tuple[str, ...]]
    ranges: tuple[tuple[float, float], ...]
    series: tuple[str, ...]


class CompiledTemplate:
    """Pre-processed template (regex, indices) – build with :func:`compile_template`."""

    def __init__(self, template: MpnTemplate):
        self.template = template
        self.variables: dict[str, Variable] = {v.name: v for v in template.variables}
        self.segments: list[Segment] = parse_pattern(template.pattern) if template.pattern else []
        order = [s.variable for s in self.segments if s.variable]
        self.code_order: list[str] = [n for n in order if n not in ("size", "value")] + [
            n for n in self.variables if n not in order and n not in ("size", "value")]
        self.size_var = self.variables.get("size")
        self.value_var = self.variables.get("value")
        self.size_code: dict[str, str] = {}
        self.size_by_code: dict[str, str] = {}
        if self.size_var is not None:
            for option in self.size_var.options:
                size = option.value or option.code
                self.size_code.setdefault(size, option.code)
                self.size_by_code.setdefault(compact(option.code), size)
        self.rules = [self._compile_rule(r) for r in template.rules]
        self.rule_vars: set[str] = {var for r in self.rules for var in r.when}
        self.cells: dict[tuple[str, str, tuple[str, ...]], AvailabilityCell] = {}
        self.cells_by_size: dict[str, list[AvailabilityCell]] = defaultdict(list)
        keys = template.availability_keys
        for cell in template.availability:
            key = (cell.size, cell.value.upper(), tuple(cell.codes.get(k, "").upper() for k in keys))
            self.cells[key] = cell
            self.cells_by_size[cell.size].append(cell)
        self.catalog: dict[str, CatalogEntry] = {compact(e.mpn): e for e in template.catalog}
        self.regex: re.Pattern[str] | None = self._build_regex() if self.segments else None
        self._validate()

    # ------------------------------------------------------------------ build
    def _validate(self) -> None:
        """Data the model validator cannot check without the engine (German :class:`MpnError`):
        matrix value codes must be readable, catalog values must carry the template unit."""
        unit = self.template.value_unit
        for cell in self.template.availability:
            try:
                self.cell_value(cell)
            except (ValueCodeError, MpnError) as exc:
                raise MpnError(f"Vorlage {self.template.id}: Matrixzelle {cell.size} „{cell.value}“ hat keinen "
                               f"gültigen Wertcode ({exc}).") from exc
        for entry in self.template.catalog:
            q = parse_quantity(entry.value, unit)
            if q is None or (q.unit and q.unit != unit):
                raise MpnError(f"Vorlage {self.template.id}: Katalogeintrag {entry.mpn} hat keinen gültigen Wert "
                               f"„{entry.value}“ (Einheit {unit}).")
    def _parse_amount(self, text: str) -> float:
        q = parse_quantity(text, self.template.value_unit)
        if q is None:
            raise MpnError(f"Ungültige Bereichsgrenze „{text}“ in Vorlage {self.template.id}.")
        return q.value

    def _compile_rule(self, rule: ValueRule) -> _Rule:
        return _Rule(
            rule=rule,
            sizes=frozenset(rule.sizes),
            when={k: tuple(c.upper() for c in v) for k, v in rule.when.items()},
            ranges=tuple((self._parse_amount(lo), self._parse_amount(hi)) for lo, hi in rule.ranges),
            series=tuple(s.upper() for s in rule.series),
        )

    def formats(self) -> list[ValueFormat]:
        if self.value_var is None or self.value_var.format is None:
            return []
        return [self.value_var.format, *(o.format for o in self.value_var.format_overrides)]

    def _build_regex(self) -> re.Pattern[str]:
        parts: list[str] = []
        for seg in self.segments:
            if seg.literal is not None:
                parts.append(re.escape(compact(seg.literal)))
                continue
            name = seg.variable or ""
            if name == "value":
                alternatives = list(dict.fromkeys(value_regex(f) for f in self.formats()))
                if self.template.jumper is not None:
                    alternatives.insert(0, re.escape(compact(self.template.jumper.value_code)))
                parts.append(f"(?P<value>{'|'.join(alternatives)})")
                continue
            var = self.variables[name]
            codes = sorted({compact(o.code) for o in var.options}, key=lambda c: (-len(c), c))
            body = "|".join(re.escape(c) for c in codes if c)
            if not body:
                parts.append(f"(?P<{name}>)")
            elif any(not compact(o.code) for o in var.options):
                parts.append(f"(?P<{name}>(?:{body})?)")
            else:
                parts.append(f"(?P<{name}>{body})")
        return re.compile("^" + "".join(parts) + "$")

    # ------------------------------------------------------------------ queries
    def value_format(self, codes: Mapping[str, str]) -> ValueFormat:
        if self.value_var is None or self.value_var.format is None:
            raise MpnError(f"Die Vorlage {self.template.id} hat kein Werteformat.")
        upper = {k: str(v).upper() for k, v in codes.items()}
        for override in self.value_var.format_overrides:
            if all(upper.get(var) in {c.upper() for c in allowed} for var, allowed in override.when.items()):
                return override.format
        return self.value_var.format

    def size_attrs(self, size: str) -> dict[str, str]:
        """Template-wide attributes overlaid with the attributes of ``size``."""
        spec = self.template.size_spec(size)
        return {**self.template.attrs, **(spec.attrs if spec is not None else {})}

    def code_attrs(self, size: str, codes: Mapping[str, str]) -> dict[str, str]:
        """Attributes of the chosen options (option value under the variable name + option attrs)."""
        attrs: dict[str, str] = {}
        for name in self.code_order:
            if name not in codes:
                continue
            option = self.variables[name].option(str(codes[name]), size)
            if option is None:
                continue
            if option.value is not None:
                attrs[name] = option.value
            attrs.update(option.attrs)
        return attrs

    def match_rule(self, size: str, value: float, fixed: Mapping[str, str],
                   attr_filters: Mapping[str, float] | None = None) -> tuple[ValueRule, dict[str, str]] | None:
        """First rule allowing ``value`` for ``size`` and the ``fixed`` codes -> (rule, derived codes)."""
        upper = {k: str(v).upper() for k, v in fixed.items()}
        for r in self.rules:
            if r.sizes and size not in r.sizes:
                continue
            derived: dict[str, str] = {}
            ok = True
            for var, codes in r.when.items():
                if var in upper:
                    if upper[var] not in codes:
                        ok = False
                        break
                else:
                    derived[var] = self._spelling(var, codes[0])
            if not ok or not self._value_ok(r, value):
                continue
            if attr_filters and not _attrs_match(r.rule.attrs, attr_filters):
                continue
            return r.rule, derived
        return None

    def _spelling(self, var: str, code: str) -> str:
        option = self.variables[var].option(code)
        return option.code if option is not None else code

    @staticmethod
    def _value_ok(r: _Rule, value: float) -> bool:
        if r.ranges and not any(lo * (1 - _REL) <= value <= hi * (1 + _REL) for lo, hi in r.ranges):
            return False
        return not r.series or in_series(value, r.series)

    def explain_rejection(self, size: str, value: float, fixed: Mapping[str, str]) -> str:
        """German reason why no rule allows the value (for explicit values and decoding)."""
        upper = {k: str(v).upper() for k, v in fixed.items()}
        relevant = [r for r in self.rules if (not r.sizes or size in r.sizes)
                    and all(upper[var] in codes for var, codes in r.when.items() if var in upper)]
        unit = self.template.value_unit
        text = format_value(value, unit)
        if not relevant:
            hint = self._blocking_code(size, upper)
            return hint or f"Für Baugröße {size} gibt es mit dieser Auswahl keine lieferbaren Werte."
        in_range = [r for r in relevant if not r.ranges or any(lo * (1 - _REL) <= value <= hi * (1 + _REL)
                                                               for lo, hi in r.ranges)]
        if not in_range:
            spans = sorted({(lo, hi) for r in relevant for lo, hi in r.ranges})
            shown = ", ".join(f"{format_value(lo, unit)} … {format_value(hi, unit)}" for lo, hi in spans[:4])
            return f"{text} liegt außerhalb des lieferbaren Bereichs ({shown})."
        series = sorted({s for r in in_range for s in r.series})
        if series and not in_series(value, series):
            return f"{text} ist kein Wert der Reihe {' / '.join(series)}."
        return f"{text} ist mit dieser Auswahl nicht lieferbar."

    def _blocking_code(self, size: str, upper: Mapping[str, str]) -> str | None:
        """German hint naming the chosen code that no rule of ``size`` allows with the other codes."""
        for var in self.code_order:
            if var not in upper or var not in self.rule_vars:
                continue
            others = {k: v for k, v in upper.items() if k != var}
            allowed: list[str] = []
            for r in self.rules:
                if (r.sizes and size not in r.sizes) or var not in r.when:
                    continue
                if all(others[k] in codes for k, codes in r.when.items() if k in others):
                    allowed.extend(c for c in r.when[var] if c not in allowed)
            if allowed and upper[var] not in allowed:
                label = self.variables[var].label
                choices = ", ".join(_option_text(self, var, c) for c in allowed)
                return (f"{label} „{_option_text(self, var, upper[var])}“ ist mit dieser Auswahl nicht lieferbar "
                        f"(möglich: {choices}).")
        return None

    def cell(self, size: str, value_code: str, codes: Mapping[str, str]) -> AvailabilityCell | None:
        key = (size, value_code.upper(), tuple(str(codes.get(k, "")).upper() for k in self.template.availability_keys))
        return self.cells.get(key)

    def cell_value(self, cell: AvailabilityCell) -> float:
        return decode_value(cell.value, self.value_format(cell.codes))

    def complete_codes(self, size: str, codes: Mapping[str, str], attrs: Mapping[str, str]) -> dict[str, str]:
        """``codes`` plus the default of every missing variable (size + ``requires`` aware)."""
        out = dict(codes)
        for name in self.code_order:
            if name in out:
                continue
            context = {**attrs, **out}
            option = self.variables[name].default_option(size, context)
            if option is not None:
                out[name] = option.code
        return out

    def check_codes(self, size: str, codes: Mapping[str, str], attrs: Mapping[str, str]) -> list[str]:
        """German problems of a complete code set (option not valid for the size / requirements)."""
        problems: list[str] = []
        context = {**attrs, **codes}
        for name in self.code_order:
            var = self.variables[name]
            if name not in codes:
                problems.append(f"Für „{var.label}“ fehlt ein Code.")
                continue
            option = var.option(str(codes[name]), size)
            if option is None:
                problems.append(f"„{codes[name]}“ ist kein gültiger Code für „{var.label}“.")
            elif not option.applies_to(size):
                problems.append(f"Code „{option.code}“ ({var.label}) gilt nicht für Baugröße {size}.")
            elif not option.satisfied_by(context):
                fit = equivalent_option(var, option, size, context)
                hint = f" (passend: {fit.code or 'ohne'})" if fit is not None else ""
                problems.append(f"Code „{option.code}“ ({var.label}) passt nicht zu diesem Bauteil{hint}.")
        return problems


def equivalent_option(variable: Variable, option: CodeOption, size: str | None,
                      context: Mapping[str, str]) -> CodeOption | None:
    """Replacement for ``option`` when its ``requires`` do not hold for a part (tape type by thickness,
    laser marking by capacitance): an option valid for ``size`` and ``context`` on the same reel
    (``attrs["reel"]``, e.g. 13" blister for 13" paper), else the variable's default."""
    candidates = [o for o in variable.options_for(size, context) if o is not option]
    reel = option.attrs.get("reel")
    same_reel = [o for o in candidates if reel and o.attrs.get("reel") == reel]
    if same_reel:
        return next((o for o in same_reel if o.default), same_reel[0])
    return variable.default_option(size, context)


def compile_template(template: MpnTemplate) -> CompiledTemplate:
    """Compiled form of ``template`` (cached on the template object)."""
    cached = template._compiled
    if isinstance(cached, CompiledTemplate) and cached.template is template:
        return cached
    compiled = CompiledTemplate(template)
    template._compiled = compiled
    return compiled


def _attrs_match(attrs: Mapping[str, str], filters: Mapping[str, float]) -> bool:
    for name, wanted in filters.items():
        raw = attrs.get(name)
        q = _quantity(str(raw).replace("±", "")) if raw else None
        if q is None or not math.isclose(abs(q[0]), abs(wanted), rel_tol=1e-6):
            return False
    return True


# --------------------------------------------------------------------------- resolve


@dataclass
class Resolution:
    """Codes and attributes of one part (``ok`` False: not orderable, see ``messages``)."""

    ok: bool
    codes: dict[str, str]
    attrs: dict[str, str]
    messages: list[str] = field(default_factory=list)
    rule: ValueRule | None = None
    cell: AvailabilityCell | None = None


def resolve(template: MpnTemplate, *, size: str, value: float, fixed: Mapping[str, str],
            jumper: bool = False, attr_filters: Mapping[str, float] | None = None,
            strict: bool = False) -> Resolution:
    """Complete the codes of a part and check it against rules / availability matrix.

    ``fixed``: codes chosen by the user (or read from a part number). Variables that rules
    need but ``fixed`` lacks are derived from the matching rule (e.g. the TCR code); all
    others get their size default. ``strict`` (decoding): nothing is derived, every code
    must be given and valid."""
    ct = compile_template(template)
    codes = {k: v for k, v in fixed.items() if k in ct.variables and k not in ("size", "value")}
    attrs: dict[str, str] = ct.size_attrs(size)
    messages: list[str] = []
    rule: ValueRule | None = None
    cell: AvailabilityCell | None = None
    ok = True
    if jumper:
        spec = template.jumper
        if spec is None:
            return Resolution(False, codes, attrs, ["Diese Serie hat keine 0-Ω-Brücke."])
        if spec.sizes and size not in spec.sizes:
            ok = False
            messages.append(f"Für Baugröße {size} gibt es keine Brücke.")
        if strict:
            wrong = [k for k in spec.codes if not spec.accepts(k, codes.get(k))]
            if wrong:
                ok = False
                messages.append("Brücken haben feste Codes: " + ", ".join(
                    f"{ct.variables[k].label} = {' / '.join(spec.choices(k))}" for k in wrong if k in ct.variables)
                    + ".")
        else:
            for name, code in spec.codes.items():
                chosen = codes.get(name)
                if chosen is not None and spec.accepts(name, chosen):
                    continue  # e.g. a 13" reel that jumpers are also available on
                if chosen is not None and name in spec.allowed and name in ct.variables:
                    messages.append(f"Brücken gibt es nicht mit {ct.variables[name].label} „{chosen}“ – "
                                    f"„{code}“ verwendet.")
                codes[name] = code
        attrs.update(spec.attrs)
    elif template.availability:
        fmt = ct.value_format(codes)
        try:
            value_code = encode_value(value, fmt)
        except ValueCodeError as exc:
            return Resolution(False, codes, attrs, [str(exc)])
        cell = ct.cell(size, value_code, codes)
        if cell is None:
            ok = False
            messages.append("Laut Datenblatt nicht lieferbar (Baugröße, Wert und Spannung).")
        else:
            set_codes = {k: v for k, v in cell.codes.items() if k not in template.availability_keys}
            if strict:
                wrong = [k for k, v in set_codes.items() if codes.get(k, "").upper() != v.upper()]
                if wrong:
                    ok = False
                    messages.append("Abweichender Code: " + ", ".join(
                        f"{ct.variables[k].label if k in ct.variables else k} laut Datenblatt {set_codes[k]}"
                        for k in wrong) + ".")
            else:
                codes.update(set_codes)
            tolerance = codes.get("tolerance")
            if cell.tolerances and tolerance and tolerance.upper() not in {t.upper() for t in cell.tolerances}:
                ok = False
                allowed = ", ".join(_option_text(ct, "tolerance", t) for t in cell.tolerances)
                messages.append(f"Toleranz {_option_text(ct, 'tolerance', tolerance)} ist für diesen Wert nicht "
                                f"lieferbar (nur {allowed}).")
            attrs.update(cell.attrs)
    elif template.rules:
        if strict:
            missing = [v for v in ct.rule_vars if v not in codes]
            if missing:
                ok = False
                messages.append("Codes fehlen: " + ", ".join(missing) + ".")
        match = ct.match_rule(size, value, codes, attr_filters)
        if match is None:
            ok = False
            unfiltered = ct.match_rule(size, value, codes) if attr_filters else None
            if unfiltered is not None:
                have = ", ".join(f"{unfiltered[0].attrs.get(k, '–')}" for k in (attr_filters or {}))
                messages.append(f"{format_value(value, template.value_unit)} gibt es nur mit {have}.")
            else:
                messages.append(ct.explain_rejection(size, value, codes))
        else:
            rule, derived = match
            codes.update(derived)
    if not strict:
        codes = ct.complete_codes(size, codes, attrs)
    attrs.update(ct.code_attrs(size, codes))
    if rule is not None:
        attrs.update(rule.attrs)
    if cell is not None:
        attrs.update(cell.attrs)
    if jumper and template.jumper is not None:
        attrs.update(template.jumper.attrs)
    problems = ct.check_codes(size, codes, attrs)
    if problems:
        ok = False
        messages.extend(problems)
    return Resolution(ok, codes, attrs, messages, rule, cell)


def _option_text(ct: CompiledTemplate, var: str, code: str) -> str:
    variable = ct.variables.get(var)
    option = variable.option(code) if variable else None
    return option.value or option.code if option is not None else code


# --------------------------------------------------------------------------- encode


def encode_mpn(template: MpnTemplate, *, size: str, value: float, codes: Mapping[str, str],
               jumper: bool = False) -> str:
    """Build the part number. ``codes`` holds every code variable (size/value excluded)."""
    ct = compile_template(template)
    if not ct.segments:
        raise MpnError("Diese Vorlage hat kein Teilenummern-Muster (Katalog mit festen Teilenummern).")
    if size not in ct.size_code:
        raise MpnError(f"Baugröße {size} gibt es in der Vorlage „{template.title}“ nicht.")
    out: list[str] = []
    for seg in ct.segments:
        if seg.literal is not None:
            out.append(seg.literal)
            continue
        name = seg.variable or ""
        if name == "size":
            out.append(ct.size_code[size])
        elif name == "value":
            if jumper:
                if template.jumper is None:
                    raise MpnError("Diese Serie hat keine 0-Ω-Brücke.")
                out.append(template.jumper.value_code)
            else:
                try:
                    out.append(encode_value(value, ct.value_format(codes)))
                except ValueCodeError as exc:
                    raise MpnError(str(exc)) from exc
        else:
            var = ct.variables[name]
            if name not in codes:
                raise MpnError(f"Für „{var.label}“ fehlt ein Code.")
            option = var.option(str(codes[name]), size)
            if option is None:
                raise MpnError(f"„{codes[name]}“ ist kein gültiger Code für „{var.label}“.")
            out.append(option.code)
    return "".join(out)


# --------------------------------------------------------------------------- decode


class Decoded(BaseModel):
    """Result of reading a part number with a template."""

    template_id: str
    template_title: str
    manufacturer: str
    category: str
    mpn: str = Field(description="Teilenummer in der Schreibweise der Vorlage")
    size: str | None = None
    value: float | None = None
    value_text: str | None = None
    jumper: bool = False
    codes: dict[str, str] = Field(default_factory=dict)
    attrs: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    valid: bool = False
    messages: list[str] = Field(default_factory=list)


def base_attrs(template: MpnTemplate, size: str | None, value: float | None, mpn: str) -> dict[str, str]:
    """Attributes every row has: manufacturer, series, mpn, size, value (formatted)."""
    attrs = {"manufacturer": template.manufacturer, "series": template.series, "mpn": mpn}
    if size:
        attrs["size"] = size
    if value is not None:
        attrs["value"] = format_value(value, template.value_unit)
    return attrs


def catalog_attrs(template: MpnTemplate, entry: CatalogEntry) -> tuple[float | None, dict[str, str]]:
    """(value, attributes) of a catalog entry."""
    q = parse_quantity(entry.value, template.value_unit)
    value = q.value if q is not None else None
    ct = compile_template(template)
    attrs = {**ct.size_attrs(entry.size), **ct.code_attrs(entry.size, entry.codes), **entry.attrs,
             **base_attrs(template, entry.size, value, entry.mpn)}
    return value, attrs


#: Variables that only choose the packaging (reel, tape): a catalog part on another reel is the same part
PACKAGING_VARIABLES = ("packaging", "cspec", "packing")


def _packaging_variant(template: MpnTemplate, size: str, value: float,
                       codes: Mapping[str, str]) -> CatalogEntry | None:
    """Catalog entry that equals the decoded part except for its packaging code, or None. A packaging
    option with a ``tape`` attribute must fit the entry's tape (paper reels for a paper-taped part)."""
    wanted = {k: str(v).upper() for k, v in codes.items() if k not in PACKAGING_VARIABLES}
    if len(wanted) == len(codes):
        return None  # the template has no packaging variable
    ct = compile_template(template)
    tapes: set[str] = set()
    for name, code in codes.items():
        option = ct.variables[name].option(str(code), size) if name in PACKAGING_VARIABLES else None
        if option is not None and option.attrs.get("tape"):
            tapes.add(option.attrs["tape"])
    for entry in template.catalog:
        if entry.size != size or not entry.codes:
            continue
        have = {k: str(v).upper() for k, v in entry.codes.items() if k not in PACKAGING_VARIABLES}
        if have != wanted or (tapes and entry.attrs.get("tape") and entry.attrs["tape"] not in tapes):
            continue
        q = parse_quantity(entry.value, template.value_unit)
        if q is not None and math.isclose(q.value, value, rel_tol=1e-9):
            return entry
    return None


def _decoded(template: MpnTemplate, **kw: object) -> Decoded:
    return Decoded(template_id=template.id, template_title=template.title, manufacturer=template.manufacturer,
                   category=template.category, **kw)  # type: ignore[arg-type]


def _spelling_problem(template: MpnTemplate, ct: CompiledTemplate, key: str, size: str, raw_value: str,
                      value: float, codes: Mapping[str, str], jumper: bool) -> tuple[str | None, str | None]:
    """(canonical part number or None, German problem) – the input must be the manufacturer's spelling."""
    try:
        canonical = encode_mpn(template, size=size, value=value, codes=codes, jumper=jumper)
    except MpnError as exc:
        return None, f"Wertcode „{raw_value}“ ist nicht die Schreibweise des Herstellers: {exc}"
    if compact(canonical) == key:
        return canonical, None
    if jumper and template.jumper is not None:
        expected = template.jumper.value_code
    else:
        try:
            expected = encode_value(value, ct.value_format(codes))
        except ValueCodeError:  # pragma: no cover - encode_mpn above succeeded with the same format
            expected = ""
    if compact(expected) != compact(raw_value):
        return canonical, (f"Wertcode „{raw_value}“ ist nicht die Schreibweise des Herstellers "
                           f"(richtig: {canonical}).")
    return canonical, f"Die Teilenummer ist nicht in der Schreibweise des Herstellers (richtig: {canonical})."


def decode_mpn(template: MpnTemplate, mpn: str) -> Decoded | None:
    """Read ``mpn`` with ``template``; ``None`` if it does not follow the pattern / catalog.

    ``valid`` tells whether the part is orderable according to the template data; the
    reasons are in ``messages``. A part number in another spelling than the manufacturer's
    (value code ``K100`` instead of ``100R``, ``1234K`` that the series cannot write) is read,
    but never ``valid``; ``mpn`` then holds the manufacturer's spelling when there is one.
    Never raises for user input."""
    ct = compile_template(template)
    key = compact(mpn)
    if not key:
        return None
    if key in ct.catalog:
        entry = ct.catalog[key]
        value, attrs = catalog_attrs(template, entry)
        return _decoded(template, mpn=entry.mpn, size=entry.size, value=value, value_text=attrs.get("value"),
                        codes=dict(entry.codes), attrs=attrs, fields=render_fields(template.fields, attrs),
                        valid=True)
    if ct.regex is None:
        return None
    m = ct.regex.match(key)
    if m is None:
        return None
    groups = m.groupdict()
    size = ct.size_by_code.get(compact(groups.get("size") or ""))
    if size is None:
        return None
    codes: dict[str, str] = {}
    for name in ct.code_order:
        raw = compact(groups.get(name) or "")
        var = ct.variables[name]
        option = next((o for o in var.options if compact(o.code) == raw and o.applies_to(size)), None) or \
            next((o for o in var.options if compact(o.code) == raw), None)
        if option is None:
            return None
        codes[name] = option.code
    value_code = compact(groups.get("value") or "")
    jumper = template.jumper is not None and value_code == compact(template.jumper.value_code)
    if jumper:
        value = 0.0
    else:
        try:
            value = decode_value(value_code, ct.value_format(codes))
        except (ValueCodeError, MpnError):
            return None
        if value <= 0:
            return None
    if template.kind == "catalog":
        variant = _packaging_variant(template, size, value, codes)
        if variant is not None:  # the catalog part on another reel (Murata …KA93J for …KA93D)
            _value, entry_attrs = catalog_attrs(template, variant)
            attrs = {**entry_attrs, **ct.code_attrs(size, codes), **base_attrs(template, size, value, mpn)}
            return _decoded(template, mpn=mpn.strip().upper(), size=size, value=value, value_text=attrs.get("value"),
                            codes=codes, attrs=attrs, fields=render_fields(template.fields, attrs), valid=True,
                            messages=[f"Verpackungsvariante des Katalogtyps {variant.mpn}."])
        attrs = {**ct.size_attrs(size), **ct.code_attrs(size, codes), **base_attrs(template, size, value, mpn)}
        return _decoded(template, mpn=mpn.strip().upper(), size=size, value=value, value_text=attrs.get("value"),
                        jumper=jumper, codes=codes, attrs=attrs, fields=render_fields(template.fields, attrs),
                        valid=False, messages=["Die Teilenummer folgt dem Muster, steht aber nicht im Katalog."])
    res = resolve(template, size=size, value=value, fixed=codes, jumper=jumper, strict=True)
    canonical, spelling = _spelling_problem(template, ct, key, size, groups.get("value") or "", value, codes, jumper)
    shown = canonical or mpn.strip().upper()
    messages = ([spelling] if spelling else []) + list(res.messages)
    valid = res.ok and spelling is None
    if valid and not template.availability_certain:
        messages.append("Lieferbarkeit nicht geprüft – Teilenummer bitte beim Hersteller oder Distributor prüfen.")
    attrs = {**res.attrs, **base_attrs(template, size, value, shown)}
    return _decoded(template, mpn=shown, size=size, value=value, value_text=attrs.get("value"), jumper=jumper,
                    codes=codes, attrs=attrs, fields=render_fields(template.fields, attrs), valid=valid,
                    messages=messages)
