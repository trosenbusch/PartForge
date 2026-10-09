"""MPN template model: how a manufacturer series builds its part numbers and which parts exist.

A template describes one manufacturer series (``Vishay CRCW e3``, ``KEMET C X7R`` …):

* ``pattern`` – the part number with placeholders, e.g. ``"CRCW{size}{value}{tolerance}{tcr}{packaging}"``.
  Every placeholder is a :class:`Variable`: a code table (``tolerance`` F = ±1 %, J = ±5 % …) or
  the ``value`` variable with a :class:`~partforge.domain.mpn.formats.ValueFormat`.
* ``sizes`` – per-size attributes (power, voltage, height …) and the footprint hint.
* Validity, one of:
    - ``rules`` (:class:`ValueRule`): value ranges + E-series per size / tolerance / TCR (resistors);
    - ``availability`` (:class:`AvailabilityCell`): explicit orderable cells (MLCC matrices);
    - ``catalog`` (:class:`CatalogEntry`, ``kind="catalog"``): an explicit part list.
* ``fields`` – category columns filled from row attributes, e.g. ``{"Tolerance": "{tolerance}"}``.

Row attributes (``{name}`` in ``fields``) come from, in this order (later wins): the size spec,
the chosen code options (``value`` of the option is stored under the variable name, plus the
option ``attrs``), the matching rule / availability cell / catalog entry, and the computed
``size``, ``value``, ``mpn``, ``manufacturer``, ``series``.

Well-known variable names: ``size``, ``value``, ``tolerance``, ``tcr``, ``voltage``,
``dielectric``, ``packaging``; templates may add their own (``marking``, ``cspec`` …).
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from ..eseries import SERIES
from .formats import ValueFormat

__all__ = [
    "PLACEHOLDER_RE",
    "TEMPLATE_ID_RE",
    "AvailabilityCell",
    "CatalogEntry",
    "CodeOption",
    "FootprintHint",
    "FormatOverride",
    "JumperSpec",
    "MpnTemplate",
    "Segment",
    "SizeSpec",
    "Source",
    "ValueRule",
    "Variable",
    "forbidden_characters",
    "parse_pattern",
]

TEMPLATE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
VARIABLE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")
_FIELD_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")
#: Never part of a part number (db.values refuses them in ``Part Number``; Altium stores free text
#: unescaped) – checked in codes, pattern literals, jumper codes and catalog part numbers.
_FORBIDDEN_MPN_CHARS = frozenset("'{}|")
_FORBIDDEN_HINT = "nicht erlaubt sind ' { } | und Steuerzeichen"

TemplateKind = Literal["pattern", "catalog"]


def forbidden_characters(text: str) -> str | None:
    """Shown list of the characters of ``text`` that may not appear in a part number, or None."""
    bad = sorted({ch for ch in text if ch in _FORBIDDEN_MPN_CHARS or ord(ch) < 32 or ord(ch) == 127})
    if not bad:
        return None
    return " ".join(repr(ch) if ord(ch) < 32 or ord(ch) == 127 else ch for ch in bad)


def _check_mpn_text(text: str, what: str) -> str:
    shown = forbidden_characters(text)
    if shown:
        raise ValueError(f"{what} „{text}“ enthält unzulässige Zeichen ({shown}) – {_FORBIDDEN_HINT}.")
    return text


class CodeOption(BaseModel):
    """One entry of a code table (``F`` = ±1 %)."""

    code: str = Field(description="Zeichenfolge in der Teilenummer ('' = Stelle bleibt leer)")
    value: str | None = Field(default=None, description="Bedeutung als Feldtext, z. B. ±1%, 6.3V, X7R, 0603")
    label: str | None = Field(default=None, description="Deutsche Beschriftung in der Oberfläche")
    sizes: list[str] = Field(default_factory=list, description="Nur für diese Baugrößen (leer = alle)")
    requires: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Nur wenn andere Codes/Attribute passen, z. B. {'tape': ['paper']} (Verpackung nach Dicke)",
    )
    default: bool = Field(default=False, description="Vorauswahl (je Baugröße die erste passende)")
    attrs: dict[str, str] = Field(
        default_factory=dict,
        description="Zusätzliche Attribute dieser Option (reel = gleichwertige Rolle beim Ersetzen einer Verpackung)",
    )
    note: str | None = None

    @field_validator("code")
    @classmethod
    def _code(cls, value: str) -> str:
        return _check_mpn_text(value.strip(), "Code")

    def applies_to(self, size: str | None) -> bool:
        return not self.sizes or size is None or size in self.sizes

    def satisfied_by(self, context: Mapping[str, str]) -> bool:
        """True if every ``requires`` condition holds for the codes/attributes in ``context``."""
        for name, allowed in self.requires.items():
            have = context.get(name)
            if have is None or str(have).upper() not in {a.upper() for a in allowed}:
                return False
        return True


class FormatOverride(BaseModel):
    """Different value format for some code combinations (Bourns CR: 1 % -> 4 digits, 5 % -> 3)."""

    when: dict[str, list[str]]
    format: ValueFormat


class Variable(BaseModel):
    """A placeholder of the pattern: code table or the value."""

    name: str
    label: str
    options: list[CodeOption] = Field(default_factory=list)
    defaults: dict[str, str] = Field(default_factory=dict, description="Vorauswahl je Baugröße: Baugröße -> Code")
    format: ValueFormat | None = Field(default=None, description="Nur für die Variable 'value'")
    format_overrides: list[FormatOverride] = Field(default_factory=list)
    help: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not VARIABLE_NAME_RE.match(value):
            raise ValueError(f"Ungültiger Variablenname „{value}“ (Kleinbuchstaben, Ziffern, _).")
        return value

    @model_validator(mode="after")
    def _check(self) -> Variable:
        if self.name == "value":
            if self.format is None:
                raise ValueError("Die Variable 'value' braucht ein Werteformat (format).")
        elif not self.options:
            raise ValueError(f"Die Variable „{self.name}“ braucht mindestens eine Option.")
        seen: dict[tuple[str, str], int] = {}
        for option in self.options:
            for size in option.sizes or [""]:
                key = (option.code.upper(), size)
                if key in seen:
                    raise ValueError(f"Variable „{self.name}“: Code „{option.code}“ ist doppelt.")
                seen[key] = 1
        return self

    def option(self, code: str, size: str | None = None) -> CodeOption | None:
        """Option with this code (case-insensitive) that applies to ``size``."""
        wanted = code.upper()
        candidates = [o for o in self.options if o.code.upper() == wanted]
        return next((o for o in candidates if o.applies_to(size)), candidates[0] if candidates else None)

    def options_for(self, size: str | None, context: Mapping[str, str] | None = None) -> list[CodeOption]:
        """Options valid for ``size`` (and, with ``context``, whose ``requires`` hold)."""
        return [o for o in self.options if o.applies_to(size) and (context is None or o.satisfied_by(context))]

    def default_option(self, size: str | None, context: Mapping[str, str] | None = None) -> CodeOption | None:
        """Pre-selected option: per-size default, else the first ``default`` option, else the first one
        (only options valid for ``size`` and – with ``context`` – whose requirements hold)."""
        applicable = self.options_for(size, context)
        if size is not None and size in self.defaults:
            wanted = self.defaults[size].upper()
            chosen = next((o for o in applicable if o.code.upper() == wanted), None)
            if chosen is not None:
                return chosen
        return next((o for o in applicable if o.default), applicable[0] if applicable else None)


class ValueRule(BaseModel):
    """Allowed values (one datasheet table row): ranges and E-series for sizes/codes."""

    sizes: list[str] = Field(default_factory=list, description="Baugrößen (leer = alle)")
    when: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Code-Bedingungen, z. B. {'tolerance': ['F'], 'tcr': ['K']}. Nicht gewählte Variablen "
                    "bekommen den ersten Code der Liste (abgeleiteter Code).",
    )
    ranges: list[tuple[str, str]] = Field(default_factory=list,
                                          description="Wertebereiche (inklusive), Text mit Einheit")
    series: list[str] = Field(default_factory=list, description="Erlaubte E-Reihen (leer = jeder Wert)")
    attrs: dict[str, str] = Field(default_factory=dict, description="Abgeleitete Attribute (TCR, Leistung …)")
    note: str | None = None

    @field_validator("series")
    @classmethod
    def _series(cls, names: list[str]) -> list[str]:
        out: list[str] = []
        for raw in names:
            name = str(raw).strip().upper()
            if name and not name.startswith("E"):
                name = f"E{name}"
            if name not in SERIES:
                raise ValueError(f"Unbekannte E-Reihe „{raw}“ (erlaubt: {', '.join(SERIES)}).")
            if name not in out:
                out.append(name)
        return out


class FootprintHint(BaseModel):
    """How the footprint of a size is generated (``partforge.footprints``)."""

    family: str = "chip"
    kind: str | None = Field(default=None, description="Chip-Bauteilart R/C/L/FB (Familie chip/molded)")
    size: str | None = Field(default=None, description="EIA-Baugröße für chip_request (leer = eigene Maße)")
    params: dict[str, Any] = Field(default_factory=dict, description="Zusätzliche Generator-Parameter (L, W, T, H …)")
    land_pattern: dict[str, Any] | None = Field(default=None, description="Herstellerempfehlung (Pads)")


class SizeSpec(BaseModel):
    size: str
    label: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict, description="power, voltage, height, metric, jumper_current …")
    footprint: FootprintHint | None = Field(default=None, description="None = Vorlagen-Footprint mit dieser Baugröße")


class JumperSpec(BaseModel):
    """The 0-Ω jumper of a resistor series."""

    value_code: str = Field(description="Wertcode der Brücke, z. B. 0000 oder 0R")
    codes: dict[str, str] = Field(default_factory=dict, description="Feste Codes, z. B. {'tolerance': 'Z', 'tcr': '0'}")
    allowed: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Weitere zulässige Codes einer festen Variable, z. B. {'packaging': ['10', '13']} – der Code aus "
                    "'codes' ist die Vorgabe",
    )
    sizes: list[str] = Field(default_factory=list, description="Baugrößen mit Brücke (leer = alle)")
    attrs: dict[str, str] = Field(default_factory=dict)

    @field_validator("value_code")
    @classmethod
    def _value_code(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Der Wertcode der Brücke darf nicht leer sein.")
        return _check_mpn_text(text, "Wertcode der Brücke")

    def accepts(self, variable: str, code: str | None) -> bool:
        """True if ``code`` is the fixed jumper code of ``variable`` or one of its allowed alternatives."""
        if code is None:
            return False
        wanted = code.strip().upper()
        fixed = self.codes.get(variable)
        if fixed is not None and fixed.upper() == wanted:
            return True
        return wanted in {c.upper() for c in self.allowed.get(variable, [])}

    def choices(self, variable: str) -> list[str]:
        """Fixed code first, then the allowed alternatives (for messages)."""
        out = [self.codes[variable]] if variable in self.codes else []
        out += [c for c in self.allowed.get(variable, []) if c.upper() not in {o.upper() for o in out}]
        return out


class AvailabilityCell(BaseModel):
    """One orderable cell of a matrix (size × value × key codes)."""

    size: str
    value: str = Field(description="Wertcode wie in der Teilenummer, z. B. 104")
    codes: dict[str, str] = Field(default_factory=dict,
                                  description="Schlüssel- und gesetzte Codes (voltage, thickness …)")
    tolerances: list[str] = Field(default_factory=list, description="Lieferbare Toleranzcodes (leer = alle)")
    attrs: dict[str, str] = Field(default_factory=dict)


class CatalogEntry(BaseModel):
    """A part of a catalog template."""

    mpn: str
    size: str
    value: str = Field(description="Wert mit Einheit, z. B. 10µH")
    codes: dict[str, str] = Field(default_factory=dict)
    attrs: dict[str, str] = Field(default_factory=dict)

    @field_validator("mpn")
    @classmethod
    def _mpn(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Die Teilenummer eines Katalogeintrags darf nicht leer sein.")
        return _check_mpn_text(text, "Teilenummer")


class Source(BaseModel):
    title: str
    url: str | None = None
    document: str | None = None
    revision: str | None = None
    pages: str | None = None
    note: str | None = None


class Segment(BaseModel):
    """Literal text or a variable placeholder of a pattern."""

    literal: str | None = None
    variable: str | None = None


def parse_pattern(pattern: str) -> list[Segment]:
    """Split ``"CRCW{size}{value}"`` into literal and variable segments (German ValueError)."""
    segments: list[Segment] = []
    pos = 0
    for m in PLACEHOLDER_RE.finditer(pattern):
        if m.start() > pos:
            segments.append(Segment(literal=pattern[pos : m.start()]))
        name = m.group(1).strip()
        if not VARIABLE_NAME_RE.match(name):
            raise ValueError(f"Ungültiger Platzhalter „{{{m.group(1)}}}“ im Muster (Kleinbuchstaben, Ziffern, _).")
        segments.append(Segment(variable=name))
        pos = m.end()
    if pos < len(pattern):
        segments.append(Segment(literal=pattern[pos:]))
    for seg in segments:
        if seg.literal is None:
            continue
        if "{" in seg.literal or "}" in seg.literal:
            raise ValueError("Unvollständiger Platzhalter im Muster (fehlende geschweifte Klammer).")
        shown = forbidden_characters(seg.literal)
        if shown:
            raise ValueError(f"Das Muster enthält unzulässige Zeichen ({shown}) – {_FORBIDDEN_HINT}.")
    return segments


class MpnTemplate(BaseModel):
    """A manufacturer part-number template (built-in or user-defined)."""

    id: str
    manufacturer: str
    series: str
    category: str = Field(description="Kategorietabelle, z. B. Resistors")
    title: str
    description: str = ""
    datasheet_url: str | None = None
    kind: TemplateKind = "pattern"
    pattern: str | None = None
    value_unit: str = Field(default="Ω", description="Einheit des Werts (Ω, F, H)")
    variables: list[Variable] = Field(default_factory=list)
    sizes: list[SizeSpec] = Field(default_factory=list)
    rules: list[ValueRule] = Field(default_factory=list)
    availability: list[AvailabilityCell] = Field(default_factory=list)
    availability_keys: list[str] = Field(default_factory=list,
                                         description="Variablen, die eine Matrixzelle bestimmen (z. B. voltage)")
    catalog: list[CatalogEntry] = Field(default_factory=list)
    jumper: JumperSpec | None = None
    attrs: dict[str, str] = Field(default_factory=dict, description="Feste Attribute aller Zeilen (technology …)")
    fields: dict[str, str] = Field(default_factory=dict, description="Spalte -> Text mit {attribut}")
    footprint: FootprintHint = Field(default_factory=FootprintHint)
    symbol_kind: str | None = Field(
        default=None,
        description="Symboltyp (partforge.symbols, z. B. resistor, diode); leer = Standardsymbol aus Kategorie und "
                    "Werten. Typen mit Pinbelegung (diode, npn …) brauchen symbol_params['pinmap'], sonst muss die "
                    "Belegung aus Gehäuse/Footprint sicher folgen – sie wird nie geraten.",
    )
    symbol_params: dict[str, Any] = Field(default_factory=dict,
                                          description="Parameter des Symboltyps, z. B. {'pinmap': 'KA'}")
    sources: list[Source] = Field(default_factory=list)
    verified: bool = False
    availability_certain: bool = Field(default=True,
                                       description="False = Lieferbarkeit nicht geprüft (Hinweis je Zeile)")
    notes: list[str] = Field(default_factory=list)
    builtin: bool = False

    # compiled form (regex, indices) – see partforge.domain.mpn.engine.compile_template
    _compiled: Any = PrivateAttr(default=None)
    # (weakref to this template, TemplateExample | None) – see partforge.domain.mpn.examples.template_example
    _example: Any = PrivateAttr(default=None)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not TEMPLATE_ID_RE.match(value or ""):
            raise ValueError(f"Ungültige Vorlagen-ID „{value}“ (Buchstaben, Ziffern, . _ -).")
        return value

    @field_validator("manufacturer", "series", "title", "category")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = " ".join((value or "").split())
        if not text:
            raise ValueError("Darf nicht leer sein.")
        return text

    @model_validator(mode="after")
    def _check(self) -> MpnTemplate:
        names = [v.name for v in self.variables]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"Variablen doppelt definiert: {', '.join(duplicates)}.")
        variables = {v.name: v for v in self.variables}
        if self.pattern:
            used = [s.variable for s in parse_pattern(self.pattern) if s.variable]
            missing = sorted({u for u in used if u not in variables})
            if missing:
                raise ValueError(f"Im Muster verwendete Variablen ohne Definition: {', '.join(missing)}.")
            for required in ("size", "value"):
                if required not in used:
                    raise ValueError(f"Das Muster braucht den Platzhalter {{{required}}}.")
            if len(used) != len(set(used)):
                raise ValueError("Jeder Platzhalter darf im Muster nur einmal vorkommen.")
            unused = sorted(set(variables) - set(used))
            if unused:
                raise ValueError(f"Variablen werden im Muster nicht verwendet: {', '.join(unused)}.")
        elif self.kind == "pattern":
            raise ValueError("Eine Muster-Vorlage braucht ein Teilenummern-Muster (pattern).")
        if self.kind == "catalog" and not self.catalog:
            raise ValueError("Eine Katalog-Vorlage braucht mindestens einen Katalogeintrag.")
        for variable in self.variables:
            for size, code in variable.defaults.items():
                if variable.option(code, size) is None:
                    raise ValueError(f"Vorauswahl „{code}“ ({size}) ist kein Code der Variable „{variable.name}“.")
        size_names = [s.size for s in self.sizes]
        if len(size_names) != len(set(size_names)):
            raise ValueError("Baugrößen sind doppelt definiert.")
        size_var = variables.get("size")
        if size_var is not None:
            known = {o.value or o.code for o in size_var.options}
            unknown = sorted(set(size_names) - known)
            if unknown:
                raise ValueError(f"Baugrößen ohne Code in der Variable 'size': {', '.join(unknown)}.")
        for rule in self.rules:
            for name, codes in rule.when.items():
                if name not in variables:
                    raise ValueError(f"Regel verweist auf unbekannte Variable „{name}“.")
                for code in codes:
                    if variables[name].option(code) is None:
                        raise ValueError(f"Regel verweist auf unbekannten Code „{code}“ der Variable „{name}“.")
        for key in self.availability_keys:
            if key not in variables:
                raise ValueError(f"Matrix-Schlüssel „{key}“ ist keine Variable.")
        for cell in self.availability:
            for name, code in cell.codes.items():
                if name not in variables or name in ("size", "value"):
                    raise ValueError(f"Matrixzelle {cell.size}/{cell.value}: unbekannte Variable „{name}“.")
                if variables[name].option(code, cell.size) is None:
                    raise ValueError(f"Matrixzelle {cell.size}/{cell.value}: „{code}“ ist kein Code der Variable "
                                     f"„{name}“.")
        if self.jumper is not None:
            for name, codes in [*((n, [c]) for n, c in self.jumper.codes.items()), *self.jumper.allowed.items()]:
                if name not in variables or name in ("size", "value"):
                    raise ValueError(f"Brücke: unbekannte Variable „{name}“.")
                for code in codes:
                    if variables[name].option(code) is None:
                        raise ValueError(f"Brücke: „{code}“ ist kein Code der Variable „{name}“.")
            for name in self.jumper.allowed:
                if name not in self.jumper.codes:
                    raise ValueError(f"Brücke: zulässige Codes für „{name}“ ohne festen Code (codes).")
        if self.symbol_params and not self.symbol_kind:
            raise ValueError("Symbolparameter (symbol_params) brauchen einen Symboltyp (symbol_kind).")
        for column, text in self.fields.items():
            if not column.strip():
                raise ValueError("Leerer Spaltenname in der Feldzuordnung.")
            for m in PLACEHOLDER_RE.finditer(text):
                if not _FIELD_PLACEHOLDER_RE.fullmatch(m.group(0)):
                    raise ValueError(f"Ungültiger Platzhalter „{m.group(0)}“ in der Feldzuordnung für „{column}“.")
        return self

    # ------------------------------------------------------------------ helpers
    def variable(self, name: str) -> Variable | None:
        return next((v for v in self.variables if v.name == name), None)

    def size_spec(self, size: str) -> SizeSpec | None:
        return next((s for s in self.sizes if s.size == size), None)

    def size_names(self) -> list[str]:
        if self.sizes:
            return [s.size for s in self.sizes]
        if self.kind == "catalog":
            return list(dict.fromkeys(e.size for e in self.catalog))
        var = self.variable("size")
        return [o.value or o.code for o in var.options] if var else []

    def summary(self) -> dict[str, Any]:
        """Short description for template lists (no matrices, no catalogs)."""
        return {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "series": self.series,
            "category": self.category,
            "title": self.title,
            "description": self.description,
            "kind": self.kind,
            "pattern": self.pattern,
            "value_unit": self.value_unit,
            "sizes": self.size_names(),
            "verified": self.verified,
            "availability_certain": self.availability_certain,
            "builtin": self.builtin,
            "datasheet_url": self.datasheet_url,
            "part_count": len(self.catalog) if self.kind == "catalog" else None,
            "availability_count": len(self.availability) or None,
        }
