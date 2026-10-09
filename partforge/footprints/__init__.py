"""Footprint generator (IPC-7351B land patterns in the user's house style).

Public contract (docs/entwicklung/ARCHITEKTUR.md §6)::

    families() -> list[FamilyInfo]
    generate(req, style=None) -> FootprintSpec            # ValueError (German) on invalid parameters
    preview(req, style=None) -> FootprintPreview           # spec + calculation record + warnings + SVG
    chip_request(kind, size) -> FootprintRequest           # series assistant
    request_from_package(family, dims) -> FootprintRequest # datasheet AI (JEDEC symbols)
    write_step(spec, path) -> Path                          # AP214 STEP of the extruded 3D bodies

Conventions shared by :func:`generate` and :func:`preview`:

* ``style=None`` uses the house style of the open workspace (``WorkspaceSettings.footprint``), or the
  defaults when no workspace is open.
* Diodes/LEDs: without an explicit ``cathode_pad`` parameter, pad 1 follows the workspace symbol
  convention (``SymbolStyle.diode_pin1``: ``cathode`` = IPC, ``anode`` -> cathode on pad 2); the
  ``diode_pin1`` keyword overrides it.
* ``req.family`` may be an alias; aliases imply their variant (``"dfn"``, ``"smb"``, ``"sot363"`` …).
* Names are unique per land pattern (see :mod:`.identity`): plain IPC/house names for standard
  packages, ``_<TAG>`` for custom or datasheet dimensions.

Additional helpers: :func:`presets`, :func:`family_info`, :func:`validate_footprint`,
:func:`render_svg`, :func:`step_text`, :func:`error_params`, :func:`with_name_record`.

``spec.generator`` also records ``names`` (``{"ipc", "house"}``: the names the generator gives the
parameters) and – only for a custom name (``FootprintRequest.name`` that is neither of them, e.g.
``MY_SOIC8``) – ``name``; "Neu generieren" passes ``generator["name"]`` back as
``FootprintRequest.name``. :func:`with_name_record` keeps ``generator["name"]`` right when a spec
is saved under another name.

:func:`families`/:func:`family_info` fill ``FamilyInfo.aliases`` (every other name that resolves to
the family) and ``FamilyInfo.supports_land_pattern`` (the family uses ``FootprintRequest.land_pattern``
instead of the IPC calculation – probed once per family, so it can never disagree with the generator).
"""
from __future__ import annotations

import copy
import functools
import logging
import re
from collections.abc import Mapping
from typing import Any, Literal

from ..geometry.model import FootprintSpec
from ..workspace import FootprintStyle, current_or_none
from . import ipc7351 as ipc
from . import naming
from .families import SELECTORS, alias_names, best_preset, get_family, registry, resolve
from .families.base import FamilyDef, GenContext, ParamSource, parse_land_override
from .families.chip import KINDS as CHIP_KINDS
from .families.chip import normalize_size
from .models import CheckIssue, FamilyInfo, FootprintPreview, FootprintRequest, Preset
from .packages import request_from_package
from .params import ParamError, Params
from .render import render_svg
from .step import step_text, write_step
from .validate import validate_footprint

log = logging.getLogger(__name__)

DiodePin1 = Literal["cathode", "anode"]

__all__ = [
    "CheckIssue",
    "FamilyInfo",
    "FootprintPreview",
    "FootprintRequest",
    "ParamError",
    "Preset",
    "chip_request",
    "effective_style",
    "error_params",
    "families",
    "family_info",
    "generate",
    "generated_names",
    "presets",
    "preview",
    "render_svg",
    "request_from_package",
    "step_text",
    "validate_footprint",
    "with_name_record",
    "write_step",
]


def families() -> list[FamilyInfo]:
    """All generator families with parameters, presets, aliases and the land-pattern flag (copies, safe
    to modify)."""
    return [_public_info(f) for f in registry().values()]


def family_info(key: str) -> FamilyInfo:
    """One family (key or alias); ``ValueError`` if unknown."""
    return _public_info(get_family(key))


def _public_info(fam: FamilyDef) -> FamilyInfo:
    info = fam.info.model_copy(deep=True)
    info.aliases = list(alias_names(fam.info.key))
    info.supports_land_pattern = supports_land_pattern(fam.info.key)
    return info


#: Manufacturer land pattern used to probe :func:`supports_land_pattern` (any complete pattern works:
#: a family that supports it switches to it in its first land calculation).
_PROBE_LAND_PATTERN: dict[str, Any] = {"pad_width": 0.5, "pad_length": 0.8, "row_spacing": 2.0}


@functools.cache
def supports_land_pattern(family_key: str) -> bool:
    """Whether the family uses a manufacturer land pattern (``FootprintRequest.land_pattern``).

    Determined by building the family's first preset with a probe pattern: families that support it
    take it in their land calculation (``GenContext.ipc_land``), the others (through-hole, BGA) keep
    the IPC calculation. A probe that fails after the land calculation still answers correctly.
    """
    fam = registry()[family_key]
    params: dict[str, Any] = {"preset": fam.info.presets[0].key} if fam.info.presets else {}
    req = FootprintRequest(family=family_key, params=params, land_pattern=_PROBE_LAND_PATTERN, with_3d=False)
    ctx, _ = _context(req, FootprintStyle(), "cathode", probe=True)
    try:
        fam.build(ctx)
    except ValueError:  # e.g. pads of the probe pattern overlap: the land calculation ran before
        log.debug("Land-Pattern-Probe für %s abgebrochen", family_key, exc_info=True)
    return ctx.override_used


def error_params(exc: BaseException, family: str | None = None) -> list[str]:
    """Request parameters a generator error is about (``ParamError.params``), else the parameters whose
    German labels the message names (longest label first, whole words) – ``[]`` if none."""
    named = getattr(exc, "params", None)
    if isinstance(named, tuple) and named:
        return list(dict.fromkeys(named))
    if not family:
        return []
    try:
        specs = get_family(family).info.params
    except ValueError:
        return []
    rest = str(exc)
    found: list[str] = []
    for spec in sorted(specs, key=lambda s: len(s.label), reverse=True):
        pattern = re.compile(re.escape(spec.label) + r"(?![\wÄÖÜäöüß])")
        if spec.label and pattern.search(rest):
            found.append(spec.name)
            rest = pattern.sub(" ", rest)
    return found


def presets(key: str) -> list[Preset]:
    return [p.model_copy(deep=True) for p in get_family(key).info.presets]


# --------------------------------------------------------------------------- workspace conventions


def effective_style(style: FootprintStyle | None = None) -> FootprintStyle:
    """``style``, else the open workspace's footprint style, else the defaults."""
    if style is not None:
        return style
    ws = current_or_none()
    return ws.settings.footprint.model_copy(deep=True) if ws is not None else FootprintStyle()


def _diode_pin1(explicit: str | None) -> DiodePin1:
    if explicit is not None:
        if explicit not in ("cathode", "anode"):
            raise ValueError(f"Ungültige Dioden-Konvention „{explicit}“ (erlaubt: cathode, anode).")
        return explicit  # type: ignore[return-value]
    ws = current_or_none()
    return ws.settings.symbol.diode_pin1 if ws is not None else "cathode"


# --------------------------------------------------------------------------- parameter merging


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _find_preset(fam: FamilyDef, key: Any) -> Preset:
    wanted = str(key).strip().lower()
    preset = next((p for p in fam.info.presets if p.key.lower() == wanted), None)
    if preset is None:
        raise ParamError(f"Unbekannte Vorlage „{key}“ für {fam.info.label}.", params=("preset",))
    return preset


def _same_value(a: Any, b: Any) -> bool:
    try:
        return abs(float(str(a).replace(",", ".")) - float(str(b).replace(",", "."))) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def _merged_params(
    fam: FamilyDef,
    params: Mapping[str, Any],
    implied: Mapping[str, Any],
    assumed: frozenset[str],
    alias: str,
) -> tuple[dict[str, Any], str | None, dict[str, ParamSource], list[str]]:
    """Request parameters on top of the preset (explicit ``preset`` key, or the preset an alias implies:
    ``"preset": "<key>"`` or ``"preset": "*"`` = best match for the alias and request selectors).

    Returns (parameters, base preset key, source per parameter, notes). Values are deep copies, the
    module-level presets are never shared with the request.
    """
    raw = copy.deepcopy(dict(params or {}))
    explicit_preset = raw.pop("preset", None)
    raw = {k: v for k, v in raw.items() if not _blank(v)}
    implied = copy.deepcopy(dict(implied))
    implied_preset = implied.pop("preset", None)
    notes: list[str] = []
    base: Preset | None = None
    base_source: ParamSource = "preset"
    if not _blank(explicit_preset):
        base = _find_preset(fam, explicit_preset)
    elif implied_preset == "*":
        hints = {**implied, **{k: raw[k] for k in SELECTORS if k in raw}}
        base, base_source = best_preset(fam.info, hints), "alias"
    elif implied_preset:
        base, base_source = _find_preset(fam, implied_preset), "alias"
    merged: dict[str, Any] = {}
    sources: dict[str, ParamSource] = {}
    if base is not None:
        merged.update(copy.deepcopy(base.params))
        sources.update(dict.fromkeys(base.params, base_source))
    for key, value in implied.items():
        if base_source == "preset" and base is not None and key in merged and not _same_value(merged[key], value):
            notes.append(f"Die Vorlage „{base.label}“ passt nicht zum Gehäuse „{alias}“ "
                         f"({key} = {merged[key]} statt {value}) – Werte der Vorlage verwendet.")
            continue
        merged[key] = value
        sources[key] = "alias"
    for key, value in raw.items():
        merged[key] = value
        sources[key] = "assumed" if key in assumed else "explicit"
    return merged, (base.key if base is not None else None), sources, notes


def _assumed_note(fam: FamilyDef, sources: Mapping[str, ParamSource], label: str) -> str | None:
    """Warning listing the land-relevant values a datasheet mapping took from a typical package."""
    specs = {s.name: s for s in fam.info.params}
    names = [specs[k].label for k, src in sources.items()
             if src == "assumed" and k in specs and k not in fam.free_params and k not in ("E2", "D2")
             and (specs[k].kind in ("tol", "float") or k in ("kind", "variant"))]  # EP has its own warning
    if not names:
        return None
    return (f"Nicht im Datenblatt angegeben, aus der Vorlage „{label}“ übernommen: {', '.join(names)} – "
            "bitte prüfen.")


@functools.cache
def _alternates(family_key: str) -> dict[str, frozenset[str]]:
    """Presets whose plain name an earlier preset of the family already uses for another land pattern
    (IPC names omit foot length, lead width …, e.g. SOT-523 vs SC-75), per naming scheme.

    Requests matching such a preset keep a tag, so a name never stands for two land patterns. Computed
    once per family by probing every preset at M/N/L; the fine "ipc" rounding (0.01 mm) reveals land
    differences that the 0.05 mm KiCad grid would hide.
    """
    fam = registry()[family_key]
    probe_style = FootprintStyle(rounding="ipc")
    first: dict[str, dict[str, tuple[str, ...]]] = {"ipc": {}, "house": {}}
    out: dict[str, set[str]] = {"ipc": set(), "house": set()}
    for preset in fam.info.presets:
        lands: list[str] = []
        names: dict[str, str] = {}
        for density in ("M", "N", "L"):
            req = FootprintRequest(family=family_key, params={"preset": preset.key}, density=density)
            ctx, _ = _context(req, probe_style, "cathode", probe=True)
            spec = fam.build(ctx)
            assert spec.generator is not None
            lands.append(str(spec.generator["land_hash"]))
            if density == "N":
                names = {"ipc": ctx.calc["names"]["ipc"], "house": ctx.calc["names"]["house"]}
        for scheme, name in names.items():
            owner = first[scheme].setdefault(name, tuple(lands))
            if owner != tuple(lands):
                out[scheme].add(preset.key)
    return {scheme: frozenset(keys) for scheme, keys in out.items()}


def _context(req: FootprintRequest, style: FootprintStyle | None, diode_pin1: str | None, *,
             probe: bool = False) -> tuple[GenContext, FamilyDef]:
    style = effective_style(style)
    fam, implied = resolve(req.family)
    params, preset_key, sources, notes = _merged_params(fam, req.params, implied, frozenset(req.assumed),
                                                        req.family)
    names = {s.name for s in fam.info.params}
    if ("cathode_pad" in names and _blank(params.get("cathode_pad"))
            and _diode_pin1(diode_pin1) == "anode"):
        params["cathode_pad"] = "2"
        sources["cathode_pad"] = "workspace"
    if preset_key is None and req.assumed_from:
        preset_key = req.assumed_from
    p = Params(params, fam.info.params)
    density = req.density if "density" in req.model_fields_set else style.density

    def opt_float(name: str, fallback: float) -> float:
        if name not in names:
            return fallback
        value = p.float_opt(name)
        return fallback if value is None else value

    rounding: ipc.RoundingMode = style.rounding
    if "rounding" in names and p.given("rounding"):
        rounding = "ipc" if p.enum("rounding") == "ipc" else "kicad"
    override, override_notes = parse_land_override(req.land_pattern)
    ctx = GenContext(
        req=req,
        style=style,
        info=fam.info,
        p=p,
        density=density,
        F=opt_float("fab_tolerance", style.fab_tolerance),
        P=opt_float("placement_tolerance", style.placement_tolerance),
        rounding=rounding,
        min_gap=opt_float("min_copper_gap", ipc.DEFAULT_MIN_COPPER_GAP),
        cy_grid=opt_float("courtyard_grid", ipc.DEFAULT_COURTYARD_GRID),
        cy_excess=p.float_opt("courtyard_excess") if "courtyard_excess" in names else None,
        with_3d=bool(req.with_3d and style.generate_3d),
        override=override,
        preset=preset_key,
        family=fam,
        sources=sources,
        preset_labels={pr.key: pr.label for pr in fam.info.presets},
        probe=probe,
        alternates={} if probe else _alternates(fam.info.key),
    )
    for note in (*req.notes, *notes, *override_notes):
        ctx.warn(note)
    if req.assumed:
        label = ctx.preset_labels.get(req.assumed_from or "", req.assumed_from or "typisches Gehäuse")
        note = _assumed_note(fam, sources, label)
        if note:
            ctx.warn(note)
    unknown = sorted(set(params) - names)
    if unknown:
        ctx.warn(f"Unbekannte Parameter werden ignoriert: {', '.join(unknown)}.")
    return ctx, fam


def _run(req: FootprintRequest, style: FootprintStyle | None, diode_pin1: str | None
         ) -> tuple[FootprintSpec, GenContext]:
    ctx, fam = _context(req, style, diode_pin1)
    spec = fam.build(ctx)
    if ctx.override is not None and not ctx.override_used:
        ctx.warn("Die Herstellerempfehlung (Land Pattern) wird für diese Gehäusefamilie nicht unterstützt – "
                 "IPC-7351B-Berechnung verwendet.")
    log.debug("Footprint %s erzeugt (Familie %s, Dichte %s, %d Pads, %d Hinweise)", spec.name, fam.info.key,
              ctx.density, len(spec.pads), len(ctx.warnings))
    return spec, ctx


def generate(req: FootprintRequest, style: FootprintStyle | None = None, *,
             diode_pin1: DiodePin1 | None = None) -> FootprintSpec:
    """Generate a footprint; raises ``ValueError`` with a German message on invalid parameters.

    ``style=None``: house style of the open workspace (defaults without workspace).
    ``diode_pin1``: overrides the workspace convention for unspecified ``cathode_pad`` values.

    Unlike :func:`preview` (which shows the problems), a footprint that fails an error-level check
    (overlapping pads, silkscreen on copper, courtyard …) is never returned: inconsistent dimensions
    raise a ``ValueError`` instead of producing a wrong library footprint.
    """
    effective = effective_style(style)
    spec, ctx = _run(req, effective, diode_pin1)
    errors = [i for i in validate_footprint(spec, effective, calc=ctx.calc, min_copper_gap=ctx.min_gap)
              if i.severity == "error"]
    if errors:
        details = " ".join(i.message for i in errors[:3])
        raise ValueError(f"Mit diesen Maßen entsteht kein gültiger Footprint: {details} "
                         "Bitte die Gehäusemaße prüfen (die Vorschau zeigt die Details).")
    return spec


def preview(req: FootprintRequest, style: FootprintStyle | None = None, *, svg: bool = True,
            diode_pin1: DiodePin1 | None = None) -> FootprintPreview:
    """Footprint + calculation record + warnings (generator clamps and plausibility checks) + SVG."""
    effective = effective_style(style)
    spec, ctx = _run(req, effective, diode_pin1)
    issues = validate_footprint(spec, effective, calc=ctx.calc, min_copper_gap=ctx.min_gap)
    warnings = list(ctx.warnings)
    for issue in issues:
        if issue.severity != "info" and issue.message not in warnings:
            warnings.append(("Fehler: " if issue.severity == "error" else "") + issue.message)
    return FootprintPreview(
        spec=spec,
        calc=ctx.calc,
        warnings=warnings,
        issues=issues,
        svg=render_svg(spec) if svg else None,
    )


def generated_names(spec: FootprintSpec) -> set[str] | None:
    """Casefolded names the generator gives the parameters of ``spec`` (IPC and house name, with
    the ``_<TAG>`` of custom dimensions); ``None`` if unknown (no generator data, or the stored
    parameters cannot be generated again).

    New specs carry them in ``generator["names"]``; for older ones the stored request
    (family, parameters, density, rounding, land pattern) is generated again."""
    gen = spec.generator if isinstance(spec.generator, dict) else None
    if not gen or not gen.get("family") or not isinstance(gen.get("params"), dict):
        return None
    stored = gen.get("names")
    if isinstance(stored, dict) and stored:
        return {str(n).casefold() for n in stored.values() if n}
    land = gen.get("land_pattern")
    density = gen.get("density") if gen.get("density") in ("M", "N", "L") else (spec.density or "N")
    try:
        req = FootprintRequest(family=str(gen["family"]), params=dict(gen["params"]), density=density,
                               land_pattern=dict(land) if isinstance(land, dict) else None, with_3d=False)
        style = effective_style(None)
        if gen.get("rounding") in ("kicad", "ipc"):
            style = style.model_copy(update={"rounding": gen["rounding"]})
        calc = preview(req, style, svg=False).calc
    except Exception as exc:  # noqa: BLE001 - unknown: the caller keeps the spec as it is
        log.debug("Erzeugte Namen von %s nicht bestimmbar: %s", spec.name, exc)
        return None
    names = calc.get("names") if isinstance(calc.get("names"), dict) else {}
    tag = names.get("tag")
    found = {naming.with_tag(str(n), tag).casefold() for n in (names.get("ipc"), names.get("house")) if n}
    return found or None


def with_name_record(spec: FootprintSpec) -> FootprintSpec:
    """``spec`` with ``generator["name"]`` = its name when that is a **custom** name (neither the IPC
    nor the house name the generator gives its parameters, e.g. ``MY_SOIC8``) and without it
    otherwise – "Neu generieren" passes ``generator["name"]`` as ``FootprintRequest.name`` and so
    reproduces a custom name, while a generated name follows the naming scheme of the house style.

    Specs without generator data are returned unchanged; if the generated names cannot be
    determined, only a stale ``generator["name"]`` is corrected. Never raises."""
    gen = spec.generator if isinstance(spec.generator, dict) else None
    if not gen:
        return spec
    known = generated_names(spec)
    updated = dict(gen)
    if known is None:
        if "name" not in gen or gen.get("name") == spec.name:
            return spec
        updated["name"] = spec.name
    elif spec.name.casefold() in known:
        if "name" not in gen:
            return spec
        updated.pop("name")
    else:
        if gen.get("name") == spec.name:
            return spec
        updated["name"] = spec.name
    return spec.model_copy(update={"generator": updated})


def chip_request(kind: str, size: str, *, density: str | None = None) -> FootprintRequest:
    """Request for a standard chip part (series assistant), e.g. ``chip_request("R", "0603")``."""
    k = str(kind).strip().upper()
    if k not in CHIP_KINDS:
        raise ValueError(f"Unbekannte Chip-Bauteilart „{kind}“ (erlaubt: {', '.join(CHIP_KINDS)}).")
    data: dict[str, Any] = {"family": "chip", "params": {"kind": k, "size": normalize_size(size)}}
    if density:
        data["density"] = density
    return FootprintRequest.model_validate(data)
