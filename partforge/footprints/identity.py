"""Footprint identity: standard check, name tags and geometry hashes.

Footprint names identify the **land geometry** (pads, paste, courtyard, body outline): libraries and the
registry upsert footprints by name, so two different land patterns must never share a name.

* A request whose resolved parameters equal a preset (or a family's reference set, e.g. a chip size
  table) is *standard* and keeps the plain IPC/house name (``RESC1608X50N``, ``SOIC-8 3.9x4.9MM``).
* Any other request (datasheet or custom dimensions, manufacturer land pattern, per-request tolerance
  or drill overrides …) gets ``_<TAG>`` appended: 4 hex digits of a hash over the land-relevant
  resolved parameters. Identical inputs give identical names (deduplication), the tag does not depend
  on the house style, so regenerating a library after a style change keeps every name.
* Parameters that change neither the land nor the name ("free" parameters of a family such as lead
  thickness ``c`` or standoff ``A1``, naming texts, the diode marking which has its own name marker)
  never create a new name. Height parameters that only enter the name as their maximum ("max only")
  are compared by that maximum.

``land_hash``/``geometry_hash`` are stored in ``FootprintSpec.generator`` so that library writers can
detect a changed footprint behind an unchanged name.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from ..geometry.model import FootprintSpec, compat_text_dump
from . import geom
from .models import FamilyInfo, ParamSpec
from .params import ParamError, nom, parse_tol

ALWAYS_FREE: frozenset[str] = frozenset({"manufacturer", "package_code", "cathode_pad", "preset"})
TAG_LENGTH = 4
HASH_LENGTH = 16
_TRUE = ("1", "true", "ja", "yes", "y", "j", "an", "on")


# --------------------------------------------------------------------------- value normalisation


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        v = float(value.replace(",", ".")) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def normalized(value: Any, kind: str, *, max_only: bool = False) -> Any:
    """Canonical, comparable and JSON-serialisable form of a parameter value."""
    if value is None:
        return None
    if kind == "tol":
        try:
            t = parse_tol(value)
        except (ParamError, ValueError):
            return str(value)
        if t is None:
            return None
        if max_only:
            return round(t.max, 6)
        return [round(t.min, 6), round(nom(t), 6), round(t.max, 6)]
    if kind in ("float", "int"):
        n = _number(value)
        return round(n, 6) if n is not None else str(value).strip().lower()
    if kind == "bool":
        return value.strip().lower() in _TRUE if isinstance(value, str) else bool(value)
    return str(value).strip().lower()


def _specs(info: FamilyInfo) -> dict[str, ParamSpec]:
    return {s.name: s for s in info.params}


def _kind(specs: Mapping[str, ParamSpec], name: str) -> str:
    spec = specs.get(name)
    return spec.kind if spec is not None else "text"


# --------------------------------------------------------------------------- standard check


def _matches(resolved: Mapping[str, Any], reference: Mapping[str, Any], specs: Mapping[str, ParamSpec],
             free: frozenset[str], max_only: frozenset[str], style_values: Mapping[str, Any]) -> bool:
    for name, value in resolved.items():
        if name in free or name in ALWAYS_FREE:
            continue
        kind = _kind(specs, name)
        if name in reference:
            ref = reference[name]
        elif name in style_values:
            ref = style_values[name]
        else:
            spec = specs.get(name)
            if spec is None or spec.default is None:
                return False  # set by the request, absent from the reference: not standard
            ref = spec.default
        only_max = name in max_only
        if normalized(value, kind, max_only=only_max) != normalized(ref, kind, max_only=only_max):
            return False
    return True


def matching_preset(
    info: FamilyInfo,
    resolved: Mapping[str, Any],
    *,
    free: frozenset[str] = frozenset(),
    max_only: frozenset[str] = frozenset(),
    style_values: Mapping[str, Any] | None = None,
    references: Iterable[Mapping[str, Any]] = (),
    prefer: str | None = None,
) -> str | None:
    """Key of the preset (``"#n"`` for the n-th family reference set) whose values the resolved
    parameters equal, or ``None`` for custom dimensions.

    Parameters missing from a preset must equal the house-style value (``style_values``: tolerances,
    rounding, courtyard excess) or the ParamSpec default.
    """
    specs = _specs(info)
    styles = dict(style_values or {})
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    preferred = next((p for p in info.presets if p.key == prefer), None) if prefer else None
    if preferred is not None:
        candidates.append((preferred.key, preferred.params))
    candidates += [(p.key, p.params) for p in info.presets if p is not preferred]
    candidates += [(f"#{i}", ref) for i, ref in enumerate(references)]
    for key, params in candidates:
        if _matches(resolved, params, specs, free, max_only, styles):
            return key
    return None


# --------------------------------------------------------------------------- name tag


def _canonical(value: Any) -> Any:
    """JSON-ready structure with floats rounded to 1e-6 (dataclasses/models flattened)."""
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else str(value)
    return value


def _digest(payload: Any) -> str:
    text = json.dumps(_canonical(payload), sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha1(text.encode("ascii")).hexdigest()


def name_tag(
    info: FamilyInfo,
    density: str,
    resolved: Mapping[str, Any],
    *,
    free: frozenset[str] = frozenset(),
    max_only: frozenset[str] = frozenset(),
    land_pattern: Any = None,
) -> str:
    """4 upper-case hex digits identifying the land-relevant inputs of a non-standard footprint."""
    specs = _specs(info)
    params = {name: normalized(value, _kind(specs, name), max_only=name in max_only)
              for name, value in resolved.items() if name not in free and name not in ALWAYS_FREE}
    payload = {"family": info.key, "density": density, "params": params, "land_pattern": land_pattern}
    return _digest(payload)[:TAG_LENGTH].upper()


# --------------------------------------------------------------------------- geometry hashes


def _q(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def _layer_box(spec: FootprintSpec, layer: str) -> list[float] | None:
    pts: list[geom.XY] = []
    for t in spec.tracks:
        if t.layer == layer:
            pts += [(t.x1, t.y1), (t.x2, t.y2)]
    for a in spec.arcs:
        if a.layer == layer:
            pts += [(a.cx - a.r, a.cy - a.r), (a.cx + a.r, a.cy + a.r)]
    for rg in spec.regions:
        if rg.layer == layer:
            pts += geom.from_points(rg.points)
    box = geom.bbox_points(pts)
    return None if box is None else [round(v, 4) for v in box]


def land_signature(spec: FootprintSpec) -> dict[str, Any]:
    """Pads, paste apertures, courtyard and body outline: what a footprint name stands for."""
    pads = [[p.designator, _q(p.x), _q(p.y), _q(p.width), _q(p.height), p.shape, _q(p.rotation),
             p.corner_radius_pct, p.side, _q(p.hole), _q(p.hole_length), p.plated, p.paste, p.thermal,
             _q(p.paste_expansion), _q(p.mask_expansion)] for p in spec.pads]
    paste = [sorted([_q(pt.x), _q(pt.y)] for pt in rg.points) for rg in spec.regions
             if rg.layer in ("top_paste", "bottom_paste")]
    return {
        "pads": sorted(pads, key=json.dumps),
        "paste": sorted(paste, key=json.dumps),
        "courtyard": _layer_box(spec, "courtyard"),
        "outline": _layer_box(spec, "component_outline"),
    }


def land_hash(spec: FootprintSpec) -> str:
    return _digest(land_signature(spec))[:HASH_LENGTH]


def geometry_hash(spec: FootprintSpec) -> str:
    """Hash over the complete footprint content except name, texts of the description and metadata."""
    data = compat_text_dump(spec.model_dump(mode="json", exclude={"name", "description", "generator", "parameters"}))
    return _digest(data)[:HASH_LENGTH]
