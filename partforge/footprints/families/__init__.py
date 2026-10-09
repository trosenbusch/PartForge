"""Registry of the package-family generators (loaded lazily on first use).

Family names: the key (``"nolead"``), an alias (``"dfn"``) or any spelling of either
(case, ``-``/``_``/spaces ignored). An alias may imply parameters (``"dfn"`` -> ``variant = DFN``,
``"sot363"`` -> ``pins = 6``, ``"sc75"`` -> preset ``SC-75``); :func:`resolve` returns them.
"""
from __future__ import annotations

import copy
import functools
import importlib
import re
from collections.abc import Mapping
from typing import Any

from ..models import FamilyInfo, Preset
from .base import FamilyDef

_MODULES = (
    "chip", "molded", "melf", "sod", "do214", "sot", "sot89", "sot223", "dpak",
    "gullwing", "qfp", "nolead", "bga", "dip", "axial", "radial", "to92", "to220", "pin_header",
)

# Parameters that select a package within a family (used to pick the best matching preset).
SELECTORS = ("variant", "size", "kind", "case", "pins", "leads", "rows", "cols", "pins_per_row", "pitch", "e", "eA")
_STRONG = {"variant", "size", "kind", "case"}


@functools.cache
def registry() -> dict[str, FamilyDef]:
    """Family key -> definition, in UI order."""
    out: dict[str, FamilyDef] = {}
    for module_name in _MODULES:
        module = importlib.import_module(f"{__name__}.{module_name}")
        for family in module.FAMILIES:
            out[family.info.key] = family
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


@functools.cache
def _aliases() -> dict[str, tuple[str, Mapping[str, Any]]]:
    """Normalised name -> (family key, implied parameters)."""
    table: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for key, family in registry().items():
        table[_norm(key)] = (key, {})
    for key, family in registry().items():
        implied = {_norm(alias): params for alias, params in family.alias_params.items()}
        for alias in (*family.aliases, *family.alias_params):
            norm = _norm(alias)
            if norm and norm not in table:  # family keys win over aliases
                table[norm] = (key, implied.get(norm, {}))
    return table


def resolve(key: str) -> tuple[FamilyDef, dict[str, Any]]:
    """(family, parameters implied by the alias) for a family key or alias.

    Raises ``ValueError`` (German) for unknown names. The implied parameters are a fresh copy.
    """
    reg = registry()
    if key in reg:
        return reg[key], {}
    hit = _aliases().get(_norm(key))
    if hit is None:
        raise ValueError(f"Unbekannte Gehäusefamilie „{key}“. Verfügbar: {', '.join(reg)}.")
    family_key, implied = hit
    return reg[family_key], copy.deepcopy(dict(implied))


def get_family(key: str) -> FamilyDef:
    """Family by key or alias; raises ``ValueError`` (German) for unknown keys."""
    return resolve(key)[0]


@functools.cache
def alias_names(family_key: str) -> tuple[str, ...]:
    """The declared aliases of a family (``aliases`` + ``alias_params`` keys, declaration order) that
    :func:`resolve` maps to it – a name that another family's key or alias already claims is left out."""
    family = registry()[family_key]
    table = _aliases()
    out: list[str] = []
    for alias in (*family.aliases, *family.alias_params):
        hit = table.get(_norm(alias))
        if hit is not None and hit[0] == family_key and alias != family_key and alias not in out:
            out.append(alias)
    return tuple(out)


def _same(a: Any, b: Any) -> bool:
    try:
        return abs(float(str(a).replace(",", ".")) - float(str(b).replace(",", "."))) < 1e-6
    except ValueError:
        return str(a).strip().lower() == str(b).strip().lower()


def best_preset(info: FamilyInfo, hints: Mapping[str, Any]) -> Preset | None:
    """The preset that matches the selector hints (variant/size/kind/case/pins/pitch …) best.

    Only presets with positive evidence qualify; a contradicting strong selector (variant, size,
    kind, case) disqualifies a preset. Ties keep the catalogue order.
    """
    best: tuple[int, Preset] | None = None
    for preset in info.presets:
        params = preset.params
        score = 0
        for key, value in hints.items():
            if key not in params or value is None:
                continue
            if _same(params[key], value):
                score += 20 if key == "pins" else (10 if key in _STRONG else 5)
            else:
                score -= 100 if key in _STRONG else (50 if key == "pins" else 20)
        if best is None or score > best[0]:
            best = (score, preset)
    if best is None or best[0] <= 0:
        return None
    return best[1]


__all__ = ["SELECTORS", "FamilyDef", "alias_names", "best_preset", "get_family", "registry", "resolve"]
