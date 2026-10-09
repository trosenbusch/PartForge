"""Pin maps: which pad number(s) belong to which pin function of a standard symbol.

A pin map value can be

* ``None`` / ``""`` / ``"auto"`` – the kind's default (may depend on the house style, e.g.
  ``SymbolStyle.diode_pin1``),
* a preset key (``"EBC"``, ``"SOIC8"``, ``"13-24"`` …),
* a *letter code* for kinds whose functions have one-letter codes: character *i* is the
  function of pad *i* (``"SSSGDDDD"`` = SO-8 MOSFET, ``"AxK"`` = SOT-23 diode with pad 2
  unconnected; ``x`` or ``.`` = not connected),
* an object ``{"<function>": "<pad>" | ["<pad>", …] | "1,2,3"}``.

Several pads of one function become stacked pins (one net, several pads).

Naming rule: a symbol name *without* a pin-map suffix always means the kind's canonical map
(``PinMapSpec.default``, e.g. diode pin 1 = cathode), whatever the house style says. A map
that differs from it - also a style-dependent default - gets the suffix ``(<key>)``, so one
name never stands for two pinouts (:attr:`ResolvedPinMap.is_canonical`).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .errors import SymbolError
from .util import natural_key as _natural_key

__all__ = ["NC_CHARS", "PinFunction", "PinMapSpec", "ResolvedPinMap", "resolve_pinmap"]

NC_CHARS = frozenset("xX.")
_DESIGNATOR_RE = re.compile(r"^[A-Za-z0-9_\-+.]{1,16}$")


@dataclass(frozen=True)
class PinFunction:
    key: str  # function key, e.g. "B", "IN+", "AC1"
    name: str  # pin name written into the symbol
    code: str | None = None  # one-character code for letter-code pin maps


@dataclass(frozen=True)
class PinMapSpec:
    functions: tuple[PinFunction, ...]
    presets: Mapping[str, Mapping[str, tuple[str, ...]]]
    default: str
    preset_labels: Mapping[str, str] = field(default_factory=dict)

    @property
    def letter_codes(self) -> bool:
        return all(f.code for f in self.functions)

    def function(self, key: str) -> PinFunction:
        for f in self.functions:
            if f.key == key:
                return f
        raise KeyError(key)


@dataclass(frozen=True)
class ResolvedPinMap:
    pins: dict[str, tuple[str, ...]]  # function key -> pad designators
    key: str  # preset key, letter code or "M<hash>"
    is_default: bool  # equals the effective default (may follow the house style)
    label: str  # "1=B, 2=E, 3=C"
    is_canonical: bool = True  # equals the kind's canonical map (no name suffix)

    def designators(self, function: str) -> tuple[str, ...]:
        return self.pins[function]


def _label(pins: Mapping[str, Sequence[str]], spec: PinMapSpec) -> str:
    pairs = [(d, spec.function(f).name) for f, ds in pins.items() for d in ds]
    pairs.sort(key=lambda p: _natural_key(p[0]))
    return ", ".join(f"{d}={n}" for d, n in pairs)


def _canonical(pins: Mapping[str, Sequence[str]], spec: PinMapSpec) -> dict[str, tuple[str, ...]]:
    order = [f.key for f in spec.functions]
    return {k: tuple(sorted(pins[k], key=_natural_key)) for k in order if k in pins}


def _as_code(pins: Mapping[str, Sequence[str]], spec: PinMapSpec) -> str | None:
    """Letter code for a map whose pads are 1..n (gaps = not connected), else None."""
    if not spec.letter_codes:
        return None
    by_pad: dict[int, str] = {}
    for fkey, pads in pins.items():
        code = spec.function(fkey).code
        for pad in pads:
            if not pad.isdigit() or pad.startswith("0"):
                return None
            by_pad[int(pad)] = code or "?"
    if not by_pad or max(by_pad) > 32:
        return None
    return "".join(by_pad.get(i, "x") for i in range(1, max(by_pad) + 1))


def _validate(pins: dict[str, tuple[str, ...]], spec: PinMapSpec, what: str) -> None:
    missing = [f.name for f in spec.functions if not pins.get(f.key)]
    if missing:
        raise SymbolError(f"{what}: Pinbelegung unvollständig, es fehlt {', '.join(missing)}.")
    seen: dict[str, str] = {}
    for fkey, pads in pins.items():
        for pad in pads:
            if not _DESIGNATOR_RE.match(pad):
                raise SymbolError(f"{what}: ungültige Pin-Nummer {pad!r}.")
            if pad in seen:
                raise SymbolError(
                    f"{what}: Pin {pad} ist doppelt belegt ({spec.function(seen[pad]).name} und "
                    f"{spec.function(fkey).name})."
                )
            seen[pad] = fkey


def _parse_code(code: str, spec: PinMapSpec, what: str) -> dict[str, tuple[str, ...]]:
    by_code: dict[str, list[PinFunction]] = {}
    for f in spec.functions:
        assert f.code is not None
        by_code.setdefault(f.code.upper(), []).append(f)
    pins: dict[str, list[str]] = {}
    used: dict[str, int] = {}
    for idx, ch in enumerate(code, start=1):
        if ch in NC_CHARS:
            continue
        funcs = by_code.get(ch.upper())
        if not funcs:
            allowed = ", ".join(sorted(by_code))
            raise SymbolError(
                f"{what}: unbekanntes Zeichen {ch!r} in der Pinbelegung {code!r} (erlaubt: {allowed}, x = frei)."
            )
        if len(funcs) == 1:
            func = funcs[0]
        else:  # several functions share a code (e.g. the two AC pins of a bridge): in order
            n = used.get(ch.upper(), 0)
            if n >= len(funcs):
                raise SymbolError(f"{what}: {ch!r} kommt in {code!r} zu oft vor (höchstens {len(funcs)}×).")
            func = funcs[n]
            used[ch.upper()] = n + 1
        pins.setdefault(func.key, []).append(str(idx))
    return {k: tuple(v) for k, v in pins.items()}


def _parse_mapping(value: Mapping[str, Any], spec: PinMapSpec, what: str) -> dict[str, tuple[str, ...]]:
    lookup: dict[str, str] = {}
    for f in spec.functions:
        lookup[f.key.upper()] = f.key
        lookup[f.name.upper()] = f.key
    pins: dict[str, tuple[str, ...]] = {}
    for raw_key, raw_val in value.items():
        fkey = lookup.get(str(raw_key).strip().upper())
        if fkey is None:
            allowed = ", ".join(f.key for f in spec.functions)
            raise SymbolError(f"{what}: unbekannte Pinfunktion {raw_key!r} (erlaubt: {allowed}).")
        if isinstance(raw_val, (list, tuple)):
            pads = [str(v).strip() for v in raw_val]
        else:
            pads = [p.strip() for p in re.split(r"[,;\s]+", str(raw_val)) if p.strip()]
        if not pads:
            raise SymbolError(f"{what}: keine Pin-Nummer für {raw_key!r}.")
        pins[fkey] = tuple(pads)
    return pins


def resolve_pinmap(spec: PinMapSpec, value: Any, *, what: str, default: str | None = None) -> ResolvedPinMap:
    """Resolve a pin-map parameter (see module docstring). ``default`` overrides ``spec.default``."""
    default_key = default or spec.default
    default_pins = _canonical(spec.presets[default_key], spec)

    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto", "standard")):
        pins = default_pins
        key = default_key
    elif isinstance(value, Mapping):
        pins = _canonical(_parse_mapping(value, spec, what), spec)
        _validate(pins, spec, what)
        key = ""
    elif isinstance(value, str):
        text = value.strip()
        preset = next((k for k in spec.presets if k.upper() == text.upper()), None)
        if preset is not None:
            pins = _canonical(spec.presets[preset], spec)
            key = preset
        elif spec.letter_codes:
            pins = _canonical(_parse_code(text, spec, what), spec)
            _validate(pins, spec, what)
            key = ""
        else:
            options = ", ".join(spec.presets)
            raise SymbolError(f"{what}: unbekannte Pinbelegung {value!r} (möglich: {options} oder ein Objekt).")
    else:
        raise SymbolError(f"{what}: Pinbelegung muss Text oder Objekt sein.")

    is_default = pins == default_pins
    if is_default:
        key = default_key
    elif not key:
        # a custom map that equals a preset gets the preset's name
        key = next((k for k, v in spec.presets.items() if _canonical(v, spec) == pins), "")
    if not key:
        key = _as_code(pins, spec) or (
            "M" + hashlib.sha1(json.dumps(pins, sort_keys=True).encode()).hexdigest()[:6].upper()
        )
    canonical = pins == _canonical(spec.presets[spec.default], spec)
    return ResolvedPinMap(
        pins=pins, key=key, is_default=is_default, label=_label(pins, spec), is_canonical=canonical
    )
