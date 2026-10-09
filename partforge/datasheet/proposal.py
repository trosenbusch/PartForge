"""Part proposal from an extraction and its commit (symbols, footprints, database rows).

:func:`build_proposal` is a dry run (nothing is written): for the chosen device it builds

* one footprint per package (``footprints.request_from_package`` with the datasheet dimensions and their
  descriptions; IPC-7351B by default, the manufacturer land pattern as alternative; preview warnings),
* one symbol per distinct pinout (``symbols.suggest_symbol`` with the pin table and the footprint, else an IC
  symbol from the pin table; exposed pads get the footprint's pad designator),
* one database row per orderable variant (category fields, package data, symbol/footprint references, the
  datasheet link), validated with ``partforge.db.parts.validate_part``; parts that already exist are found by
  their part number *and* their manufacturer part number (``partforge.db.parts.find_by_mpn``: every category,
  compared without spaces/dashes and case – also with internal part numbers),
* pin/pad consistency per package (``check_symbol_footprint`` without NC pads and exposed pads) against the
  symbol and footprint that will actually be linked; the NC pads a generated symbol has no pin for are recorded as
  ``SymbolSpec.generator["nc_pads"]``, so the library check (``sync.library_health``) applies the same rule.

What the UI needs comes structured, never as text to parse: ``PartProposal.blocker_targets`` (package, symbol pins,
footprint pads per blocker) and ``SymbolProposal.taken_changes`` (one :class:`~.models.PinoutChange` per differing
pin, names in overbar syntax); German warnings name pins readably (:func:`readable_pin_name`).

**Correctness before convenience** (ARCHITEKTUR §1): error-level checks of the chosen device/packages and pins
without pads (or pads without pins) are :attr:`~.models.PartProposal.blockers` – the proposal is not ready and
the commit refuses until the user confirmed each of them (``ProposalChoices.accept_issues`` = the confirmed blocker
texts; ``True`` = all, deprecated). A generated symbol whose name is registered with another pin-out is never linked
silently: it gets a free name (``taken_name``, ``taken_changes``, ``usage``), unless the user confirms the new
pin-out for that symbol (``ProposalChoices.allow_pin_changes``: ``True`` or the symbol names), which the commit passes
to ``sync.ensure_symbols(allow_pin_changes=True)`` for exactly these symbols.

Every proposal carries a :attr:`~.models.PartProposal.fingerprint` (choices, blockers and the plan: names, write
decisions, rows). :func:`commit_proposal` (job) rebuilds the proposal and refuses – nothing written, the job fails
with a German message and ``detail.code`` = ``unconfirmed_blockers`` (+ ``detail.unconfirmed_blockers``) or
``proposal_changed`` (+ ``detail.fingerprint``/``expected_fingerprint``) – when blockers are not confirmed or the
plan differs from the reviewed one (``ProposalChoices.expected_fingerprint``). Otherwise it writes missing
symbols/footprints through ``partforge.altium.sync`` and inserts the parts with
``partforge.db.parts.upsert_parts``; parts whose symbol or footprint could not be written are not created (reported in
``errors``). It holds the library it was started for (:func:`partforge.jobs.library_hold`): a library switch cancels
it and waits until it stopped, and if that library is no longer open the commit stops (``LibraryChanged``) before
writing anything. Progress: ``detail.step`` = check, footprints, symbols, parts, save; the job ends with
"Angelegt: 3 Bauteile, 1 Symbol, 2 Footprints".

**Only the symbols or only the footprints** (``ProposalChoices.scope`` = ``symbols`` | ``footprints``, not part of the
fingerprint – the reviewed proposal serves every scope): the commit writes just these into their SchLib/PcbLib, creates
no parts and needs only that scope to be valid (``PartProposal.ready_symbols`` / ``ready_footprints``: every symbol
resp. footprint valid, at least one to write, no unconfirmed blocker of that scope – ``BlockerTarget.scopes``: pin-table
problems block the symbols, drawing problems the footprints, a pin count that contradicts the package both, pins
without pads only the whole part). It ends with "Gespeichert: 1 Symbol". A datasheet without device but with package
drawings (``PartProposal.package_only``, e.g. a separate package-outline document) gets a proposal with one footprint
per drawn package and nothing else.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, Literal

from ..db import categories as db_categories
from ..db import parts as db_parts
from ..db import registry
from ..db.models import CategoryDef, UpsertResult
from ..domain.text import ascii_name, clean_free_text, plural
from ..geometry.model import FootprintSpec, SymbolSpec
from ..jobs import JobContext, library_hold
from ..workspace import Workspace, current, current_or_none
from . import store
from .errors import CommitRefused, DatasheetError, NoExtraction
from .models import (
    COMMIT_SCOPES,
    BlockerTarget,
    CommitInfo,
    CommitScope,
    CostSummary,
    DeviceData,
    ExtractionData,
    FootprintAlternative,
    FootprintProposal,
    Issue,
    PackageChoice,
    PackageData,
    PartProposal,
    PinData,
    PinoutChange,
    ProposalChoices,
    SymbolChoice,
    SymbolProposal,
    VariantData,
    VariantProposal,
)
from .normalize import GEOMETRY_ISSUES, IDENTITY_ISSUES, clean_pin_name

log = logging.getLogger(__name__)

__all__ = ["COMMIT_STEPS", "SCOPE_STEPS", "build_proposal", "commit_outcome", "commit_proposal", "datasheet_link",
           "pin_pad_warnings", "pinout_diff", "proposal_fingerprint", "readable_pin_name"]

_LIFECYCLE = {
    "ACTIVE": "Aktiv", "PRODUCTION": "Aktiv", "IN PRODUCTION": "Aktiv", "NRND": "NRND",
    "NOT RECOMMENDED FOR NEW DESIGNS": "NRND", "LIFEBUY": "Abgekündigt", "LAST TIME BUY": "Abgekündigt",
    "EOL": "Abgekündigt", "DISCONTINUED": "Obsolet", "OBSOLETE": "Obsolet",
}
_GROUND = re.compile(r"^(?:A|D|P|S)?(?:GND|VSS|V-|VEE|AGND|DGND|PGND)", re.I)
_BOOKKEEPING = frozenset({"PF Status", "PF Created", "PF Modified", "PF Author"})
_MAX_NAME_TRIES = 50
#: Steps of the commit job (``detail.step``) and their German labels.
COMMIT_STEPS: dict[str, str] = {
    "check": "Vorschlag prüfen",
    "footprints": "Footprints anlegen",
    "symbols": "Symbole anlegen",
    "parts": "Bauteile speichern",
    "save": "Datenblatt verknüpfen",
}
#: Steps of a commit per scope (``detail.steps``).
SCOPE_STEPS: dict[str, tuple[str, ...]] = {
    "part": tuple(COMMIT_STEPS),
    "symbols": ("check", "symbols", "save"),
    "footprints": ("check", "footprints", "save"),
}


# --------------------------------------------------------------------------- helpers


def datasheet_link(rec: Any, meta: Any, ws: Workspace, mode: str = "auto") -> str:
    """Manufacturer URL if known (URL import), else the absolute path of the local PDF."""
    path = ws.abs(rec.file)
    local = str(path) if path is not None else rec.file
    if mode == "file":
        return local
    if meta.source_url and mode in ("auto", "url"):
        return str(meta.source_url)
    return local


def _ci(mapping: Mapping[str, Any], key: str) -> Any:
    wanted = key.casefold()
    return next((v for k, v in mapping.items() if k.casefold() == wanted), None)


def _fold(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def _height(pkg: PackageData) -> str | None:
    dim = pkg.dim("A")
    if dim is None:
        return None
    value = dim.max if dim.max is not None else dim.value()
    return f"{value:g}mm" if value else None


def _lifecycle(status: str) -> str | None:
    key = re.sub(r"\s+", " ", status.strip().upper())
    return _LIFECYCLE.get(key)


def _style_ep_designator(pins: int, ws: Workspace | None) -> str:
    style = ws.settings.footprint.exposed_pad_designator if ws is not None else "next"
    return "EP" if style == "EP" else str(pins + 1)


def _pin_signature(pins: Sequence[PinData]) -> tuple[tuple[str, str, str], ...]:
    return tuple(sorted((p.number, p.name, p.electrical) for p in pins))


def _writer_problems(spec: SymbolSpec | FootprintSpec) -> list[str]:
    """What would stop the library writer (``sync.validate_spec``: free text, names, coordinates …)."""
    from ..altium import sync

    try:
        return list(sync.validate_spec(spec))
    except Exception as exc:  # noqa: BLE001 - a crashing check must not break the preview
        log.warning("Prüfung von %s für den Writer fehlgeschlagen: %s", spec.name, exc)
        return [f"{spec.name}: Prüfung für den Bibliotheks-Writer nicht möglich ({type(exc).__name__})."]


# --------------------------------------------------------------------------- footprints


def _family_params(family: str, pkg: PackageData) -> dict[str, Any]:
    from ..footprints import family_info

    params: dict[str, Any] = {}
    try:
        specs = {s.name: s for s in family_info(family).params}
    except ValueError:
        return params
    if pkg.pin_count and "pins" in specs:
        params["pins"] = str(pkg.pin_count) if specs["pins"].kind == "enum" else pkg.pin_count
    if family == "nolead" and pkg.exposed_pad and pkg.exposed_pad_number and "ep_name" in specs:
        params["ep_name"] = pkg.exposed_pad_number
    if pkg.layout is not None:  # terminal arrangement entered in the review (irregular QFN/QFP)
        params.update({k: v for k, v in pkg.layout.generator_params().items() if k in specs})
    return params


def _footprint_request(pkg: PackageData, choice: PackageChoice, mode: str) -> Any:
    from ..footprints import request_from_package

    dims = [d.model_dump() for d in pkg.dimensions if d.unit == "mm"]
    land = pkg.land_pattern.to_override() if mode == "manufacturer" else None
    params = _family_params(pkg.family or "", pkg)
    last: Exception | None = None
    for family in (pkg.name, pkg.family):
        if not family:
            continue
        try:
            return request_from_package(family, dims, density=choice.density, land_pattern=land, name=choice.name,
                                        params=params)
        except ValueError as exc:
            last = exc
    raise last or ValueError(f"Gehäuse „{pkg.label}“ ist keiner Footprint-Familie zugeordnet.")


def _preview(pkg: PackageData, choice: PackageChoice, mode: str, svg: bool) -> tuple[Any, list[str], bool, Any]:
    """(preview or None, warnings, valid, request JSON)."""
    from ..footprints import preview as fp_preview

    try:
        req = _footprint_request(pkg, choice, mode)
        pv = fp_preview(req, svg=svg)
    except ValueError as exc:
        return None, [f"{pkg.label}: {exc}"], False, None
    errors = [i for i in pv.issues if i.severity == "error"]
    return pv, list(pv.warnings), not errors, req.model_dump(mode="json")


def _footprint(pkg: PackageData, choice: PackageChoice, svg: bool,
               overwrite: bool) -> tuple[FootprintProposal, FootprintSpec | None]:
    """The proposal and the footprint the parts will be linked to (the registered one if it is not rewritten)."""
    from ..footprints import render_svg as fp_svg

    out = FootprintProposal(package=pkg.code, package_label=pkg.label, family=pkg.family)
    if choice.footprint == "existing":
        name = (choice.existing or "").strip()
        rec = registry.get_footprint(name) if name else None
        out.mode = "existing"
        if rec is None:
            out.warnings.append(f"{pkg.label}: Footprint „{name}“ ist nicht registriert.")
            return out, None
        out.name, out.exists, out.valid, out.status = rec.name, True, True, rec.status
        out.pad_count, out.ipc_name, out.spec = rec.pad_count, rec.ipc_name, rec.spec
        out.svg = fp_svg(rec.spec) if svg and rec.spec is not None else None
        return out, rec.spec
    if pkg.family is None:
        out.warnings.append(f"{pkg.label}: Gehäuse keiner Footprint-Familie zugeordnet – bitte einen vorhandenen "
                            "Footprint wählen.")
        return out, None
    mode = choice.footprint
    has_land = pkg.land_pattern.complete()
    if mode == "manufacturer" and not has_land:
        out.warnings.append(f"{pkg.label}: Keine vollständige Herstellerempfehlung – IPC-7351B-Berechnung verwendet.")
        mode = "ipc"
    pv, warnings, valid, request = _preview(pkg, choice, mode, svg)
    out.mode = mode  # type: ignore[assignment]
    out.warnings.extend(warnings)
    out.request = request
    linked: FootprintSpec | None = None
    if pv is not None:
        spec: FootprintSpec = pv.spec
        out.spec, out.svg, out.valid = spec, pv.svg, valid
        out.name, out.ipc_name, out.pad_count = spec.name, spec.ipc_name, len(spec.pad_designators())
        rec = registry.get_footprint(spec.name)
        out.exists = rec is not None
        out.status = rec.status if rec is not None else None
        linked = spec
        if rec is not None and not overwrite and rec.status == "ok" and rec.spec is not None:
            linked = rec.spec  # registered and not rewritten: the parts get the registered footprint
            if set(rec.spec.pad_designators()) != set(spec.pad_designators()):
                out.warnings.append(f"{pkg.label}: Footprint „{spec.name}“ ist bereits mit anderen Pads registriert – "
                                    "der vorhandene wird verwendet („Vorhandene überschreiben“ ersetzt ihn).")
        if _will_write(out, overwrite) and out.valid:
            problems = _writer_problems(spec)
            if problems:
                out.valid = False
                out.warnings.extend(problems[:6])
    if has_land:
        other: Literal["ipc", "manufacturer"] = "ipc" if mode == "manufacturer" else "manufacturer"
        alt, alt_warnings, alt_valid, _ = _preview(pkg, choice.model_copy(update={"name": None}), other, svg)
        if alt is not None:
            out.alternatives.append(FootprintAlternative(mode=other, name=alt.spec.name, svg=alt.svg,
                                                         warnings=alt_warnings, valid=alt_valid))
    return out, linked


def _will_write(item: FootprintProposal | SymbolProposal, overwrite: bool) -> bool:
    """Whether the commit writes this symbol/footprint (new, overwrite, pin-out change or last write failed)."""
    if item.spec is None:
        return False
    if isinstance(item, FootprintProposal):
        if item.mode == "existing":
            return False
    elif item.source == "existing":
        return False
    if not item.exists or overwrite or item.status not in (None, "ok"):
        return True
    return isinstance(item, SymbolProposal) and bool(item.pin_changes)


# --------------------------------------------------------------------------- symbols


def _ic_pins(pins: Sequence[PinData], pkg: PackageData | None, footprint: FootprintSpec | None,
             ws: Workspace | None) -> tuple[list[Any], set[str]]:
    """Symbol pins for the pin table (exposed pad renumbered to the footprint's thermal pad) and the designators
    that belong to the exposed pad. Names and descriptions are cleaned for the SchLib (no ``|``/control chars)."""
    from ..symbols import IcPin

    thermal = [p.designator for p in footprint.pads if p.thermal] if footprint is not None else []
    ep_designator = thermal[0] if thermal else (
        _style_ep_designator(pkg.pin_count or len(pins), ws) if pkg is not None and pkg.exposed_pad else None)
    out: list[IcPin] = []
    exposed: set[str] = set()
    seen: set[str] = set()
    use_parts = any(p.part > 1 for p in pins)
    for pin in pins:
        number = clean_free_text(pin.number, max_len=12).replace(" ", "") or "?"
        if pin.exposed_pad and ep_designator:
            number = ep_designator
        if number in seen:
            continue
        seen.add(number)
        name = clean_pin_name(pin.name) or number
        electrical = pin.electrical
        if pin.exposed_pad:
            exposed.add(number)
            if name.replace("\\", "").upper() in ("EP", "PAD", "EPAD"):
                name, electrical = "EP", ("power" if _GROUND.match(pin.function or "") else electrical)
        description = clean_free_text(pin.function, max_len=200) or None
        out.append(IcPin(designator=number, name=name, electrical=electrical,
                         group=clean_free_text(pin.group, max_len=40) or None,
                         part=(pin.part if use_parts else 1), description=description))
    if pkg is not None and pkg.exposed_pad and ep_designator and ep_designator not in seen:
        exposed.add(ep_designator)
        out.append(IcPin(designator=ep_designator, name="EP", electrical="passive", group="EP",
                         part=0 if use_parts else 1, description="Exposed Pad"))
    return out, exposed


def _natural(text: str) -> tuple[Any, ...]:
    return tuple((0, int(t)) if t.isdigit() else (1, t.upper()) for t in re.split(r"(\d+)", text) if t)


def _pin_pad_problems(symbol: SymbolSpec, footprint: FootprintSpec,
                      nc_pins: set[str]) -> tuple[list[tuple[str, list[str], list[str]]], list[str]]:
    """``([(blocking text, symbol pins, footprint pads)], hints)``: pins without pad and pads without pin block; an
    exposed pad without pin is a hint (connect it as the datasheet says). NC pads may stay without symbol pin."""
    pads = set(footprint.pad_designators())
    pins = {p.designator for p in symbol.pins}
    thermal = {p.designator for p in footprint.pads if p.thermal}
    blocking: list[tuple[str, list[str], list[str]]] = []
    missing = sorted(pins - pads, key=_natural)
    if missing:
        blocking.append((f"Pins ohne Pad im Footprint: {', '.join(missing)}", missing, []))
    unused = sorted(pads - pins - nc_pins - thermal, key=_natural)
    if unused:
        blocking.append((f"Pads ohne Pin im Symbol: {', '.join(unused)}", [], unused))
    hints: list[str] = []
    open_ep = sorted(thermal - pins, key=_natural)
    if open_ep:
        hints.append(f"Exposed Pad {', '.join(open_ep)} ohne Pin im Symbol – auf der Leiterplatte laut Datenblatt "
                     "anschließen.")
    return blocking, hints


def _pin_pad_check(symbol: SymbolSpec, footprint: FootprintSpec, nc_pins: set[str]) -> tuple[list[str], list[str]]:
    """(blocking mismatches, hints) as German texts (see :func:`_pin_pad_problems`)."""
    blocking, hints = _pin_pad_problems(symbol, footprint, nc_pins)
    return [text for text, _pins, _pads in blocking], hints


def _nc_pads(symbol: SymbolSpec, pins: Sequence[PinData], footprint: FootprintSpec | None) -> list[str]:
    """Pads the datasheet marks NC (not connected) that the symbol has no pin for – of the linked footprint if known
    (ARCHITEKTUR §10: recorded as ``generator.nc_pads`` for the library check)."""
    nc = {clean_free_text(p.number, max_len=12).replace(" ", "") for p in pins if p.no_connect}
    nc -= {p.designator for p in symbol.pins}
    if footprint is not None:
        nc &= set(footprint.pad_designators())
    return sorted((n for n in nc if n), key=_natural)


def _with_nc_pads(spec: SymbolSpec, nc_pads: Sequence[str]) -> SymbolSpec:
    """``spec`` with ``generator["nc_pads"]`` – the pads it leaves without pin on purpose (datasheet NC pins)."""
    generator = dict(spec.generator) if isinstance(spec.generator, dict) else {}
    if list(nc_pads) == generator.get("nc_pads") or (not nc_pads and "nc_pads" not in generator):
        return spec
    if nc_pads:
        generator["nc_pads"] = list(nc_pads)
    else:
        generator.pop("nc_pads", None)
    return spec.model_copy(update={"generator": generator or None})


# --------------------------------------------------------------------------- pin-out differences


def readable_pin_name(name: str | None) -> str:
    """A pin name for German message texts: Altium's overbar syntax (``C\\S\\``) as a real overline (combining
    U+0305 after each overlined character: ``C̅S̅``) instead of backslashes."""
    from ..symbols.text import parse_overbar

    return "".join(ch + ("̅" if barred else "") for ch, barred in parse_overbar(str(name or "")))


def _pins_by_designator(spec: SymbolSpec) -> dict[str, Any]:
    return {pin.designator: pin for pin in spec.pins}  # like sync.pinout: the last pin of a designator counts


def pinout_diff(old: SymbolSpec, new: SymbolSpec) -> list[PinoutChange]:
    """Structured pin-out differences between a registered symbol (``old``) and the proposed one (``new``): one
    entry per pin that was added, removed or has another name, electrical type or part (natural order). Empty when the
    pin-out is the same for the library (designators, names and parts – ``sync.pinout_changes``); a type-only change is
    no conflict."""
    from ..altium import sync

    if not sync.pinout_changes(old, new):
        return []
    a, b = _pins_by_designator(old), _pins_by_designator(new)
    out: list[PinoutChange] = []
    for designator in sorted(set(a) | set(b), key=_natural):
        before, after = a.get(designator), b.get(designator)
        if before is not None and after is not None and (before.name, before.electrical, before.part) == (
                after.name, after.electrical, after.part):
            continue
        out.append(PinoutChange(
            pin=designator,
            old_name=before.name if before is not None else None, new_name=after.name if after is not None else None,
            old_type=before.electrical if before is not None else None,
            new_type=after.electrical if after is not None else None,
            old_part=before.part if before is not None else None, new_part=after.part if after is not None else None))
    return out


def _unknown_pinout(new: SymbolSpec) -> list[PinoutChange]:
    """Differences to a registered symbol without geometry (external/imported): its pins are unknown."""
    return [PinoutChange(pin=d, new_name=p.name, new_type=p.electrical, new_part=p.part)
            for d, p in sorted(_pins_by_designator(new).items(), key=lambda item: _natural(item[0]))]


def _change_texts(changes: Sequence[PinoutChange], *, limit: int = 8) -> list[str]:
    """German sentences for warnings (like ``sync.pinout_changes``, pin names readable without overbar syntax):
    „Pins entfernt: 1, 2“, „Pins hinzugefügt: 9“, „Pin 1: Name „CS“ → „C̅S̅““, „Pin 3: Teil 1 → 2“."""
    def listed(items: list[str]) -> str:
        return ", ".join(items[:limit]) + (" …" if len(items) > limit else "")

    removed = [c.pin for c in changes if c.new_name is None and c.old_name is not None]
    added = [c.pin for c in changes if c.old_name is None and c.new_name is not None]
    texts: list[str] = []
    if removed:
        texts.append(f"Pins entfernt: {listed(removed)}")
    if added:
        texts.append(f"Pins hinzugefügt: {listed(added)}")
    for c in changes:
        if c.old_name is None or c.new_name is None:
            continue
        if c.old_name != c.new_name:
            texts.append(f"Pin {c.pin}: Name „{readable_pin_name(c.old_name)}“ → „{readable_pin_name(c.new_name)}“")
        if c.old_part != c.new_part:
            texts.append(f"Pin {c.pin}: Teil {c.old_part} → {c.new_part}")
    return texts


def pin_pad_warnings(symbol: SymbolSpec, footprint: FootprintSpec, nc_pins: set[str]) -> list[str]:
    """``check_symbol_footprint`` without the expected gaps: NC pads may stay without symbol pin, an exposed pad
    without pin gets a hint to connect it as the datasheet says."""
    blocking, hints = _pin_pad_check(symbol, footprint, nc_pins)
    return [*blocking, *hints]


def _symbol_name(device: DeviceData, pkg: PackageData | None, distinct: int) -> str:
    base = device.base_part
    if distinct > 1 and pkg is not None:
        base = f"{base} {pkg.name or pkg.code}"
    return ascii_name(base, max_len=64, fallback="IC")


def _registered_changes(name: str, spec: SymbolSpec) -> tuple[Any | None, list[PinoutChange], list[str]]:
    """(registered record of that name, structured pin-out differences to ``spec``, the same as German texts)."""
    rec = registry.get_symbol(name)
    if rec is None:
        return None, [], []
    if rec.spec is None:  # registered without geometry (external/imported): compare what is known
        if rec.pin_count and rec.pin_count != len(spec.pins):
            return rec, _unknown_pinout(spec), [f"{rec.pin_count} statt {len(spec.pins)} Pins"]
        return rec, [], []
    changes = pinout_diff(rec.spec, spec)
    return rec, changes, _change_texts(changes)


def _name_candidates(name: str, pkg: PackageData | None) -> Iterator[str]:
    if pkg is not None:
        suffix = pkg.name or pkg.code
        if suffix and _fold(suffix) not in _fold(name):
            yield ascii_name(f"{name} {suffix}", max_len=64, fallback="IC")
    for n in range(2, _MAX_NAME_TRIES + 2):
        tail = f"_{n}"
        yield ascii_name(name, max_len=64 - len(tail), fallback="IC") + tail


def _renamed(spec: SymbolSpec, name: str) -> SymbolSpec:
    generator = spec.generator
    if isinstance(generator, dict) and isinstance(generator.get("request"), dict):
        generator = {**generator, "request": {**generator["request"], "name": name}}
    return spec.model_copy(update={"name": name, "generator": generator})


def _settle_name(out: SymbolProposal, spec: SymbolSpec, pkg: PackageData | None, *, explicit: bool,
                 allow_changes: bool, proposed: Mapping[str, SymbolSpec]) -> SymbolSpec | None:
    """Name of a generated symbol checked against this proposal and the registry.

    Same name and same pin-out: the registered symbol is reused. Another pin-out: with ``allow_changes`` the
    registered symbol gets the new pin-out (``out.pin_changes``); otherwise a free name is chosen – or, for a name
    the user typed, the symbol is invalid. ``out.taken_changes`` lists the differences per pin (structured, names in
    overbar syntax), the warnings name them readably. Returns the (renamed) spec or ``None``."""

    def clash(name: str) -> tuple[bool, list[PinoutChange], list[str], Any | None, bool]:
        """(blocked, pin-out differences, the same as texts, registered record, clash within this proposal)."""
        other = proposed.get(name.casefold())
        if other is not None:  # the first symbol of that name already settled the registry question
            diff = pinout_diff(other, spec)
            return bool(diff), diff, _change_texts(diff), registry.get_symbol(name), True
        rec, changes, texts = _registered_changes(name, spec)
        return bool(changes), changes, texts, rec, False

    blocked, changes, texts, rec, in_proposal = clash(spec.name)
    out.usage = rec.usage if rec is not None else 0
    if not blocked:
        out.exists = rec is not None
        out.status = rec.status if rec is not None else None
        if in_proposal and rec is not None and rec.spec is not None and allow_changes:
            diff = pinout_diff(rec.spec, spec)
            out.pin_changes, out.taken_changes = _change_texts(diff), diff
        return spec
    out.taken_changes = list(changes)
    if allow_changes and not in_proposal and rec is not None:
        out.exists, out.status, out.pin_changes = True, rec.status, list(texts)
        users = f" – {plural(rec.usage, 'Bauteil verwendet', 'Bauteile verwenden')} es und bekommen sie ebenfalls" \
            if rec.usage else ""
        out.warnings.append(f"Symbol „{spec.name}“ bekommt eine neue Pinbelegung ({'; '.join(texts[:6])}){users}.")
        return spec
    if explicit:
        out.warnings.append(f"Symbol „{spec.name}“ existiert bereits mit anderer Pinbelegung "
                            f"({'; '.join(texts[:6])}) – bitte einen anderen Namen wählen oder die neue Pinbelegung "
                            "bestätigen.")
        return None
    for candidate in _name_candidates(spec.name, pkg):
        taken, _changes, _texts, existing, _ = clash(candidate)
        if taken:
            continue
        out.taken_name = spec.name
        out.exists = existing is not None
        out.status = existing.status if existing is not None else None
        out.warnings.append(
            f"Symbol „{spec.name}“ ist bereits mit anderer Pinbelegung registriert ({'; '.join(texts[:4])}) – "
            f"neuer Name „{candidate}“. Soll das vorhandene Symbol die neue Pinbelegung bekommen, bitte „Pinbelegung "
            "ändern“ bestätigen.")
        return _renamed(spec, candidate)
    out.warnings.append(f"Für das Symbol „{spec.name}“ wurde kein freier Name gefunden – bitte einen Namen angeben.")
    return None


def _symbol(device: DeviceData, category: CategoryDef | None, values: Mapping[str, Any], pkg: PackageData | None,
            pins: Sequence[PinData], footprint: FootprintSpec | None, choice: SymbolChoice, distinct: int,
            ws: Workspace | None, svg: bool, choices: ProposalChoices,
            proposed: Mapping[str, SymbolSpec]) -> tuple[SymbolProposal, SymbolSpec | None]:
    """The proposal and the symbol the parts will be linked to (the registered one if it is not rewritten)."""
    from ..symbols import SymbolError, generate, ic_symbol, suggest_symbol
    from ..symbols import render_svg as sym_svg

    code = pkg.code if pkg is not None else ""
    out = SymbolProposal(package=code, packages=[code] if code else [])
    if choice.mode == "existing":
        name = (choice.existing or "").strip()
        rec = registry.get_symbol(name) if name else None
        out.source = "existing"
        if rec is None:
            out.warnings.append(f"Symbol „{name}“ ist nicht registriert.")
            return out, None
        out.name, out.exists, out.valid, out.spec, out.status = rec.name, True, True, rec.spec, rec.status
        out.pin_count, out.part_count, out.kind, out.usage = rec.pin_count, rec.part_count, rec.kind, rec.usage
        out.svg = sym_svg(rec.spec) if svg and rec.spec is not None else None
        return out, rec.spec
    ic_pins, exposed = _ic_pins(pins, pkg, footprint, ws)
    spec: SymbolSpec | None = None
    if choice.mode in ("auto", "standard") and category is not None:
        # standard symbols have no pin for the exposed pad: the footprint's thermal pad covers it
        signal_pins = [p for p in ic_pins if p.designator not in exposed]
        suggestion = suggest_symbol(category.table, values, pins=signal_pins or None, footprint=footprint)
        if suggestion.request is not None:
            try:
                spec = generate(suggestion.request)
                out.source, out.kind = "standard", suggestion.kind
                out.request = suggestion.request.model_dump(mode="json")
                out.warnings.extend(suggestion.messages)
            except SymbolError as exc:
                out.warnings.append(str(exc))
        elif choice.mode == "standard":
            out.warnings.extend(suggestion.messages or ["Für dieses Bauteil passt kein Standardsymbol."])
            return out, None
    if spec is None:
        if not ic_pins:
            out.warnings.append(f"{device.base_part}: Keine Pintabelle für {pkg.label if pkg else 'das Gehäuse'} – "
                                "IC-Symbol nicht möglich.")
            return out, None
        name = choice.name or _symbol_name(device, pkg, distinct)
        parts = choice.parts if choice.parts is not None else (None if any(p.part > 1 for p in ic_pins) else "auto")
        prefix = category.prefix if category is not None and category.prefix else "U"
        try:
            spec = ic_symbol(ascii_name(name, max_len=64, fallback="IC"), ic_pins, parts=parts,
                             description=clean_free_text(device.description, max_len=120), designator_prefix=prefix)
        except (SymbolError, ValueError) as exc:
            out.warnings.append(f"IC-Symbol nicht erzeugbar: {exc}")
            return out, None
        out.source, out.kind = "ic", "ic"
        out.request = {"kind": "ic", "name": spec.name, "parts": parts, "pins": [p.model_dump(mode="json") for p in ic_pins]}
    # NC pads of the datasheet stay without symbol pin on purpose: recorded with the symbol, so the library check
    # (sync.library_health, pin_pad_mismatch) applies the same rule as this proposal
    spec = _with_nc_pads(spec, _nc_pads(spec, pins, footprint))
    explicit = bool(choice.name) and out.source == "ic"  # SymbolChoice.name names IC symbols only
    settled = _settle_name(out, spec, pkg, explicit=explicit, allow_changes=choices.allows_pin_change(spec.name),
                           proposed=proposed)
    out.pin_count, out.part_count = len(spec.pins), spec.part_count
    if settled is None:
        out.name, out.spec = spec.name, spec
        out.svg = sym_svg(spec) if svg else None
        return out, None
    spec = settled
    if out.request is not None and "name" in out.request:
        out.request["name"] = spec.name
    out.spec, out.name, out.valid = spec, spec.name, True
    out.svg = sym_svg(spec) if svg else None
    linked: SymbolSpec | None = spec
    if _will_write(out, choices.overwrite_existing):
        problems = _writer_problems(spec)
        if problems:
            out.valid = False
            out.warnings.extend(problems[:6])
    elif out.exists:
        rec = registry.get_symbol(spec.name)
        if rec is not None and rec.spec is not None:
            linked = rec.spec  # registered, same pin-out, not rewritten
    return out, linked


# --------------------------------------------------------------------------- values


def _device_values(data: ExtractionData, device: DeviceData) -> dict[str, str]:
    values: dict[str, str] = {}
    if data.manufacturer:
        values["Manufacturer"] = data.manufacturer
    for p in device.parameters:
        values[p.column] = p.value
    return values


def _row(data: ExtractionData, device: DeviceData, variant: VariantData, pkg: PackageData | None,
         category: CategoryDef, symbol: str | None, footprint: str | None, link: str | None,
         choices: ProposalChoices, scheme: str) -> dict[str, str]:
    values = _device_values(data, device)
    values["Manufacturer Part Number"] = variant.mpn
    if scheme == "mpn":
        values["Part Number"] = variant.mpn
    if pkg is not None:
        values["Package"] = pkg.name or pkg.code
        if pkg.mounting:
            values["Mounting"] = pkg.mounting
        height = _height(pkg)
        if height:
            values["Height"] = height
    if variant.temperature_range:
        values["Operating Temperature"] = variant.temperature_range
    lifecycle = _lifecycle(variant.status) if variant.status else None
    if lifecycle:
        values["Lifecycle"] = lifecycle
    notes = "; ".join(t for t in (variant.packaging and f"Verpackung: {variant.packaging}", variant.notes) if t)
    if notes:
        values["Notes"] = clean_free_text(notes, max_len=500)
    for p in variant.values:
        values[p.column] = p.value
    if symbol:
        values["Library Ref"] = symbol
    if footprint:
        values["Footprint Ref"] = footprint
    if link:
        values["ComponentLink1Description"] = "Datenblatt"
        values["ComponentLink1URL"] = link
    if "Channels" not in values and category.field("Channels") is not None:
        table = device.pin_table(pkg.code) if pkg is not None else None
        parts = {p.part for p in table.pins if p.part > 0} if table is not None else set()
        if len(parts) > 1:
            values["Channels"] = str(len(parts))
    # Description: the category template, unless it would stay (almost) empty
    rendered = db_parts.render_templates(category.table, values).get("Description", "")
    if device.description and len(rendered.split()) <= 2:
        values["Description"] = clean_free_text(device.description, max_len=255)
    values.update({k: v for k, v in choices.values.items() if v is not None})
    values.update({k: v for k, v in (_ci(choices.variant_values, variant.mpn) or {}).items() if v is not None})
    known = {f.column.casefold(): f.column for f in category.fields}
    return {known[k.casefold()]: str(v) for k, v in values.items() if k.casefold() in known and str(v).strip()}


def _parts_by_mpn(mpns: Sequence[str]) -> dict[str, list[tuple[str, dict[str, str | None]]]]:
    """Existing parts per manufacturer part number in every category (``partforge.db.parts.find_by_mpn``, keyed by
    ``db.parts.mpn_key``): ``{mpn_key: [(table, row)]}``. Finds parts whose part number is not the MPN (internal part
    numbers, renamed parts) and rows without MPN whose part number is the MPN."""
    try:
        found = db_parts.find_by_mpn([m for m in mpns if m and m.strip()])
    except Exception as exc:  # noqa: BLE001 - a broken category must not break the preview
        log.warning("Suche nach Herstellernummern fehlgeschlagen: %s", exc)
        return {}
    return {key: [(table, row) for table, _pn, row in hits] for key, hits in found.items()}


def _existing_part(hits: Sequence[tuple[str, dict[str, str | None]]], table: str, manufacturer: str,
                   warnings: list[str]) -> tuple[str, dict[str, str | None]] | None:
    """The existing part for a variant (same category first); warnings for duplicates and another manufacturer."""
    if not hits:
        return None
    ordered = sorted(hits, key=lambda h: h[0].casefold() != table.casefold())
    choice = ordered[0]
    if len(hits) > 1:
        listed = ", ".join(f"{t}: {r.get('Part Number')}" for t, r in hits[:4])
        warnings.append(f"Hersteller-Teilenummer mehrfach vorhanden ({listed}) – „{choice[1].get('Part Number')}“ wird "
                        "verwendet.")
    other = str(choice[1].get("Manufacturer") or "")
    if other and manufacturer and _fold(other) not in _fold(manufacturer) and _fold(manufacturer) not in _fold(other):
        warnings.append(f"Das vorhandene Bauteil {choice[1].get('Part Number')} hat den Hersteller „{other}“.")
    return choice


# --------------------------------------------------------------------------- proposal


def _select_variants(device: DeviceData, choices: ProposalChoices, warnings: list[str]) -> list[VariantData]:
    variants = list(device.variants)
    if not variants:
        codes = [t.package for t in device.pin_tables]
        variants = [VariantData(mpn=device.base_part, package=codes[0] if len(codes) == 1 else "")]
        warnings.append(f"Keine Bestellnummern im Datenblatt – „{device.base_part}“ wird als Teilenummer verwendet.")
    if choices.variants is None:
        return variants
    wanted = {m.strip().casefold() for m in choices.variants if m and m.strip()}
    chosen = [v for v in variants if v.mpn.casefold() in wanted]
    unknown = sorted(wanted - {v.mpn.casefold() for v in variants})
    if unknown:
        warnings.append(f"Unbekannte Bestellnummern ignoriert: {', '.join(unknown)}.")
    return chosen


def _relevant_issue(issue: Issue, device: DeviceData, codes: Sequence[str]) -> bool:
    """An issue of the chosen device (or of the datasheet) that concerns one of the chosen packages."""
    if issue.device not in (None, device.base_part):
        return False
    return issue.package is None or issue.package in codes


def _issue_scopes(issue: Issue) -> list[CommitScope]:
    """The commits an error-level issue blocks: pin-table problems the symbols, drawing problems the footprints, a pin
    count that contradicts the package (one of them is wrong) and unknown checks everything."""
    if issue.code in GEOMETRY_ISSUES:
        return ["part", "footprints"]
    if issue.code in IDENTITY_ISSUES and issue.code != "pin_count":
        return ["part", "symbols"]
    return ["part", "symbols", "footprints"]


def _set_blockers(proposal: PartProposal, targets: Sequence[BlockerTarget]) -> None:
    """``blockers`` (unique texts, first occurrence) and one target per blocker (the scopes of equal texts joined)."""
    first: dict[str, BlockerTarget] = {}
    for target in targets:
        known = first.get(target.blocker)
        if known is None:
            first[target.blocker] = target.model_copy(deep=True)
        else:
            known.scopes = [s for s in COMMIT_SCOPES if s in {*known.scopes, *target.scopes}]
    proposal.blockers = list(first)
    proposal.blocker_targets = list(first.values())


def _package_only_proposal(rec: Any, meta: Any, data: ExtractionData, choices: ProposalChoices, *,
                           svg: bool) -> PartProposal:
    """Proposal of a datasheet without device (a package drawing): one footprint per drawn package, nothing else."""
    from ..config import load_settings

    proposal = PartProposal(datasheet_id=rec.id, device="", package_only=True, manufacturer=data.manufacturer,
                            issues=list(data.issues), cost=CostSummary(usd=meta.cost_usd, runs=len(meta.runs)))
    proposal.cost.budget_usd = load_settings().ai.max_cost_per_import_usd
    drawn = [p for p in data.packages if p.has_geometry()]
    undrawn = [p.label for p in data.packages if not p.has_geometry()]
    if undrawn and drawn:
        proposal.warnings.append(f"Ohne Maße, kein Footprint: {', '.join(undrawn)}.")
    packages = drawn or list(data.packages)
    codes = [p.code for p in packages]
    errors = [i for i in data.issues if i.severity == "error" and (i.package is None or i.package in codes)]
    _set_blockers(proposal, [BlockerTarget(blocker=i.message, package=i.package, scopes=_issue_scopes(i))
                             for i in errors])
    for pkg in packages:
        footprint, _linked = _footprint(pkg, choices.packages.get(pkg.code) or PackageChoice(), svg,
                                        choices.overwrite_existing)
        proposal.footprints.append(footprint)
    if not packages:
        proposal.warnings.append("Das Datenblatt beschreibt weder ein Bauteil noch ein Gehäuse.")
    return _finish(proposal, choices)


def _finish(proposal: PartProposal, choices: ProposalChoices) -> PartProposal:
    """Open blockers, readiness per scope and the fingerprint (the last step of every proposal)."""
    proposal.unconfirmed_blockers = [b for b in proposal.blockers if not choices.accepts(b)]
    proposal.ready = _ready(proposal, choices)
    proposal.ready_symbols = _scope_ready(proposal, choices, "symbols")
    proposal.ready_footprints = _scope_ready(proposal, choices, "footprints")
    proposal.fingerprint = proposal_fingerprint(proposal, choices)
    return proposal


def build_proposal(datasheet_id: str, choices: ProposalChoices | None = None, *, ws: Workspace | None = None,
                   svg: bool = True) -> PartProposal:
    """Dry run: what "Bauteil anlegen" would create (see module docstring)."""
    choices = choices or ProposalChoices()
    ws = ws or current()
    rec = store.get_record(datasheet_id)
    meta = store.load_meta(rec)
    data = meta.extraction
    if data is None:
        raise NoExtraction(datasheet_id)
    if not data.devices:
        return _package_only_proposal(rec, meta, data, choices, svg=svg)
    device = data.device(choices.device)
    if device is None:
        raise DatasheetError(f"Das Bauteil „{choices.device}“ ist in diesem Datenblatt nicht enthalten.")
    warnings: list[str] = []
    cats = {c.table.casefold(): c for c in db_categories.list_categories(with_counts=False)}
    table = choices.category or device.category
    category = cats.get(table.casefold()) if table else None
    if category is None:
        warnings.append("Bitte eine Kategorie wählen." if not table else f"Kategorie „{table}“ gibt es nicht.")
    proposal = PartProposal(
        datasheet_id=rec.id, device=device.base_part, devices=[d.base_part for d in data.devices],
        manufacturer=data.manufacturer, category=category.table if category else None,
        category_label=category.label if category else None,
        issues=[i for i in data.issues if i.device in (None, device.base_part)],
        cost=CostSummary(usd=meta.cost_usd, runs=len(meta.runs)),
    )
    from ..config import load_settings

    proposal.cost.budget_usd = load_settings().ai.max_cost_per_import_usd
    variants = _select_variants(device, choices, warnings)
    codes: list[str] = []
    for v in variants:
        if v.package and v.package not in codes:
            codes.append(v.package)
    if not codes:
        codes = [t.package for t in device.pin_tables][:1]
    blocking_issues = [i for i in data.issues if i.severity == "error" and _relevant_issue(i, device, codes)]
    targets: list[BlockerTarget] = [BlockerTarget(blocker=i.message, package=i.package, scopes=_issue_scopes(i))
                                    for i in blocking_issues]

    # footprints per package
    footprints: dict[str, FootprintProposal] = {}
    linked_footprints: dict[str, FootprintSpec | None] = {}
    for code in codes:
        pkg = data.package(code)
        if pkg is None:
            warnings.append(f"Gehäuse „{code}“ ist im Datenblatt nicht beschrieben – bitte einen Footprint wählen.")
            continue
        footprints[code], linked_footprints[code] = _footprint(pkg, choices.packages.get(code) or PackageChoice(), svg,
                                                               choices.overwrite_existing)
    proposal.footprints = list(footprints.values())

    # symbols per distinct pinout
    tables = {code: device.pin_table(code) for code in codes}
    distinct = len({_pin_signature(t.pins) for t in tables.values() if t is not None}) or 1
    base_values = _device_values(data, device)
    symbols: dict[str, SymbolProposal] = {}  # package code -> proposal
    linked_symbols: dict[str, SymbolSpec | None] = {}
    by_signature: dict[Any, tuple[SymbolProposal, SymbolSpec | None]] = {}
    proposed: dict[str, SymbolSpec] = {}  # names of this proposal (casefold) -> spec
    for code in codes:
        pkg = data.package(code)
        table_ = tables.get(code)
        pins = table_.pins if table_ is not None else []
        choice = choices.symbols.get(code) or choices.symbol
        signature = (_pin_signature(pins), choice.model_dump_json())
        fp_linked = linked_footprints.get(code)
        shared = by_signature.get(signature)
        if shared is not None:
            shared_spec = shared[1]
            compatible = True
            if fp_linked is not None and shared_spec is not None:
                nc_pins = {p.number for p in pins if p.no_connect}
                compatible = not _pin_pad_check(shared_spec, fp_linked, nc_pins)[0]
            if compatible:  # same pinout and the pads match: one symbol for both packages
                shared[0].packages.append(code)
                symbols[code], linked_symbols[code] = shared
                continue
        values = {**base_values, "Package": pkg.name if pkg is not None else ""}
        channels = {p.part for p in pins if p.part > 0}
        if len(channels) > 1 and not _ci(values, "Channels"):
            values["Channels"] = str(len(channels))
        # built for the footprint the parts will get (the registered one when it is not rewritten)
        sym, sym_linked = _symbol(device, category, values, pkg, pins, fp_linked, choice, distinct, ws, svg, choices,
                                  proposed)
        same_name = next((s for s in by_signature.values() if s[0].name and sym.name and s[0].valid and sym.valid
                          and s[0].name.casefold() == sym.name.casefold()), None)
        if same_name is not None:  # the same symbol (same name, same pin-out – _settle_name ensured it)
            same_name[0].packages.append(code)
            symbols[code], linked_symbols[code] = same_name
            continue
        by_signature[signature] = (sym, sym_linked)
        symbols[code], linked_symbols[code] = sym, sym_linked
        if sym.valid and sym.spec is not None and sym.name:
            proposed[sym.name.casefold()] = sym.spec
    unique_symbols: list[SymbolProposal] = []
    for candidate in symbols.values():
        if not any(candidate is known for known in unique_symbols):
            unique_symbols.append(candidate)
    proposal.symbols = unique_symbols

    # symbol <-> footprint check per package against what will be linked (NC pads and the exposed pad may stay
    # without symbol pin)
    for code in codes:
        pkg_footprint = footprints.get(code)
        sym_spec, fp_spec = linked_symbols.get(code), linked_footprints.get(code)
        if pkg_footprint is None or sym_spec is None or fp_spec is None:
            continue
        pin_table = tables.get(code)
        nc_pins = {p.number for p in pin_table.pins if p.no_connect} if pin_table is not None else set()
        blocking, hints = _pin_pad_problems(sym_spec, fp_spec, nc_pins)
        for message in [*(text for text, _pins, _pads in blocking), *hints]:
            pkg_footprint.warnings.append(f"{pkg_footprint.package_label}: {message}")
        for message, pins_, pads_ in blocking:  # the pairing only: symbols and footprints alone are not affected
            text = f"{pkg_footprint.package_label}: {message}"
            targets.append(BlockerTarget(blocker=text, package=code, pins=pins_, pads=pads_))
    _set_blockers(proposal, targets)

    # rows
    link = datasheet_link(rec, meta, ws, choices.link)
    proposal.datasheet_link = link
    scheme = ws.settings.part_number_scheme
    known = _parts_by_mpn([v.mpn for v in variants]) if category is not None else {}
    for v in variants:
        pkg = data.package(v.package) if v.package else (data.package(codes[0]) if len(codes) == 1 else None)
        code = pkg.code if pkg is not None else ""
        v_symbol, v_footprint = symbols.get(code), footprints.get(code)
        item = VariantProposal(mpn=v.mpn, package=code, footprint=v_footprint.name if v_footprint else None,
                               symbol=v_symbol.name if v_symbol else None)
        if category is not None:
            item.values = _row(data, device, v, pkg, category, item.symbol, item.footprint, link, choices, scheme)
            existing = _existing_part(known.get(db_parts.mpn_key(v.mpn), []), category.table, data.manufacturer,
                                      item.warnings)
            if existing is not None and existing[1].get("Part Number"):
                item.values["Part Number"] = str(existing[1]["Part Number"])  # update/skip that part
            try:
                check = db_parts.validate_part(category.table, item.values)
            except Exception as exc:  # noqa: BLE001 - validation must never break the preview
                item.warnings.append(str(exc))
                item.errors["Prüfung"] = str(exc)
            else:
                # bookkeeping columns are the database's business (an update must not reset "PF Status")
                item.values = {k: v_ for k, v_ in check["values"].items()
                               if v_ not in (None, "") and k not in _BOOKKEEPING}
                item.part_number = check["values"].get("Part Number")
                item.errors = {str(k): str(msg) for k, msg in check["errors"].items()}
                item.warnings.extend(f"{k}: {msg}" for k, msg in check["errors"].items())
                item.warnings.extend(check["warnings"])
                conflict = check.get("conflict")
                if conflict:
                    same = str(conflict.get("table", "")).casefold() == category.table.casefold()
                    item.status = "exists" if same else "conflict"
                    item.existing_table = conflict.get("table")
                    item.part_number = conflict.get("part_number") or item.part_number
        if not item.footprint:
            item.warnings.append("Kein Footprint.")
        if not item.symbol:
            item.warnings.append("Kein Symbol.")
        proposal.variants.append(item)
    proposal.warnings = warnings
    return _finish(proposal, choices)


def _ready(proposal: PartProposal, choices: ProposalChoices) -> bool:
    if proposal.package_only or not proposal.category or not proposal.variants:
        return False
    if any(not s.valid for s in proposal.symbols) or any(not f.valid for f in proposal.footprints):
        return False
    if proposal.unconfirmed_blockers:
        return False
    for item in proposal.variants:
        if not item.symbol or not item.footprint or item.status == "conflict":
            return False
        if item.status == "exists" and choices.mode == "skip":
            continue
        if item.errors:
            return False
    return True


def _scope_items(proposal: PartProposal, scope: CommitScope) -> list[SymbolProposal] | list[FootprintProposal]:
    return proposal.symbols if scope == "symbols" else proposal.footprints


def _scope_unconfirmed(proposal: PartProposal, scope: CommitScope) -> list[str]:
    """Unconfirmed blockers that stop a commit of ``scope``."""
    open_ = set(proposal.unconfirmed_blockers)
    return [t.blocker for t in proposal.blocker_targets if t.blocker in open_ and scope in t.scopes]


def _scope_ready(proposal: PartProposal, choices: ProposalChoices, scope: CommitScope) -> bool:
    """"Nur Symbol/Footprint speichern": every item of the scope valid, at least one to write, its blockers confirmed."""
    items = _scope_items(proposal, scope)
    if not items or any(not item.valid for item in items):
        return False
    if not any(_will_write(item, choices.overwrite_existing) for item in items):
        return False
    return not _scope_unconfirmed(proposal, scope)


# --------------------------------------------------------------------------- fingerprint


def _spec_hash(spec: SymbolSpec | FootprintSpec | None) -> str | None:
    if spec is None:
        return None
    return hashlib.sha256(spec.model_dump_json().encode("utf-8")).hexdigest()[:16]


def _choices_key(choices: ProposalChoices) -> dict[str, Any]:
    data = choices.model_dump(mode="json", exclude={"accept_issues", "expected_fingerprint", "scope"})
    if isinstance(data.get("variants"), list):
        data["variants"] = sorted({str(v).strip().casefold() for v in data["variants"]})
    if isinstance(data.get("allow_pin_changes"), list):
        data["allow_pin_changes"] = sorted({str(v).strip().casefold() for v in data["allow_pin_changes"]})
    return data


def proposal_fingerprint(proposal: PartProposal, choices: ProposalChoices) -> str:
    """Stable hash (16 hex characters) of what "Bauteil anlegen" would do: the choices (without ``accept_issues``,
    ``expected_fingerprint`` and ``scope``), the blockers and the plan – symbols and footprints (name, write decision,
    pin-out change, geometry), the rows (part number, status, symbol, footprint, values, errors) and the datasheet link.
    SVG previews do not count."""
    overwrite = choices.overwrite_existing
    plan = {
        "choices": _choices_key(choices),
        "device": proposal.device,
        "package_only": proposal.package_only,
        "category": proposal.category,
        "blockers": list(proposal.blockers),
        "symbols": [{"name": s.name, "valid": s.valid, "exists": s.exists, "status": s.status,
                     "write": _will_write(s, overwrite), "pin_changes": s.pin_changes, "taken_name": s.taken_name,
                     "spec": _spec_hash(s.spec)} for s in proposal.symbols],
        "footprints": [{"package": f.package, "name": f.name, "valid": f.valid, "exists": f.exists, "status": f.status,
                        "write": _will_write(f, overwrite), "mode": f.mode, "spec": _spec_hash(f.spec)}
                       for f in proposal.footprints],
        "variants": [{"mpn": v.mpn, "part_number": v.part_number, "status": v.status, "table": v.existing_table,
                      "symbol": v.symbol, "footprint": v.footprint, "values": v.values, "errors": v.errors}
                     for v in proposal.variants],
        "link": proposal.datasheet_link,
    }
    text = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- commit


def _scope_blocking(proposal: PartProposal, choices: ProposalChoices, scope: CommitScope) -> list[str]:
    """Problems that stop "Nur Symbol/Footprint speichern" apart from the blockers (none, invalid, nothing to write)."""
    items = _scope_items(proposal, scope)
    noun = ("Symbol", "Symbole") if scope == "symbols" else ("Footprint", "Footprints")
    if not items:
        return [f"Der Vorschlag enthält kein {noun[0]}."]
    problems: list[str] = []
    for item in items:
        if item.valid:
            continue
        if isinstance(item, SymbolProposal):
            problems.extend(item.warnings or [f"Symbol für {', '.join(item.packages) or 'das Bauteil'} ist ungültig."])
        else:
            problems.extend(item.warnings or [f"Footprint für {item.package_label} ist ungültig."])
    if not problems and not any(_will_write(item, choices.overwrite_existing) for item in items):
        names = ", ".join(f"„{item.name}“" for item in items if item.name)
        problems.append(f"Nichts zu speichern – {noun[1] if len(items) > 1 else noun[0]} {names} "
                        f"{'sind' if len(items) > 1 else 'ist'} bereits in der Bibliothek.")
    return problems


def _blocking(proposal: PartProposal, choices: ProposalChoices) -> list[str]:
    """Problems that stop the commit apart from the blockers (no category, invalid symbols/footprints, no variants)."""
    problems: list[str] = []
    if proposal.package_only:
        return [("Das Datenblatt beschreibt nur Gehäuse und kein Bauteil – bitte die Footprints speichern oder das "
                 "Gehäuse in das Datenblatt des Bauteils übernehmen.")]
    if not proposal.category:
        problems.append("Keine Kategorie gewählt.")
    for s in proposal.symbols:
        if not s.valid:
            problems.extend(s.warnings or [f"Symbol für {', '.join(s.packages) or 'das Bauteil'} ist ungültig."])
    for f in proposal.footprints:
        if not f.valid:
            problems.extend(f.warnings or [f"Footprint für {f.package_label} ist ungültig."])
    if not proposal.variants:
        problems.append("Keine Bestellnummern ausgewählt.")
    return problems


def _confirm_text(blockers: Sequence[str]) -> str:
    more = f" (und {len(blockers) - 3} weitere)" if len(blockers) > 3 else ""
    return "Bitte zuerst prüfen und bestätigen: " + "; ".join(blockers[:3]) + more + "."


def commit_outcome(result: Mapping[str, Any]) -> str:
    """"Angelegt: 3 Bauteile, 1 Symbol, 2 Footprints" (+ updated/skipped/errors) – the outcome sentence of a commit;
    "Gespeichert: 1 Symbol" for a commit of only the symbols (footprints)."""
    created, updated = len(result.get("created") or []), len(result.get("updated") or [])
    skipped, errors = len(result.get("skipped") or []), len(result.get("errors") or {})
    symbols, footprints = len(result.get("symbols") or []), len(result.get("footprints") or [])
    scope = result.get("scope") or "part"
    if scope != "part":
        noun = ("Symbol", "Symbole") if scope == "symbols" else ("Footprint", "Footprints")
        written = symbols if scope == "symbols" else footprints
        head = f"Gespeichert: {plural(written, *noun)}" if written else f"Kein {noun[0]} gespeichert"
        return head + (f" ({plural(errors, 'Fehler', 'Fehler')})" if errors else "")
    if created:
        head = f"Angelegt: {plural(created, 'Bauteil', 'Bauteile')}"
    elif updated:
        head = f"Aktualisiert: {plural(updated, 'Bauteil', 'Bauteile')}"
    else:
        head = "Keine Bauteile angelegt"
    if symbols:
        head += f", {plural(symbols, 'Symbol', 'Symbole')}"
    if footprints:
        head += f", {plural(footprints, 'Footprint', 'Footprints')}"
    extra = []
    if created and updated:
        extra.append(f"{updated} aktualisiert")
    if skipped:
        extra.append(f"{skipped} übersprungen")
    if errors:
        extra.append(plural(errors, "Fehler", "Fehler"))
    return head + (f" ({', '.join(extra)})" if extra else "")


def commit_proposal(ctx: JobContext | None, datasheet_id: str, choices: ProposalChoices | None = None, *,
                    ws: Workspace | None = None, author: str | None = None) -> dict[str, Any]:
    """Job: create the symbols/footprints that are missing and insert (or update) the parts – with
    ``choices.scope`` = ``symbols`` | ``footprints`` only the symbols or only the footprints, no parts.

    Holds the library ``ws`` (default: the open one) for the whole run – :func:`partforge.jobs.library_hold`
    raises ``LibraryChanged`` (a ``JobCancelled``) if it is no longer open."""
    choices = choices or ProposalChoices()
    root = (ws or current()).root
    with library_hold(ctx, root) as held:  # the open workspace object of that library
        return _commit(ctx, datasheet_id, choices, ws=held, author=author)


def _commit(ctx: JobContext | None, datasheet_id: str, choices: ProposalChoices, *, ws: Workspace,
            author: str | None) -> dict[str, Any]:
    from ..altium import sync

    def step(fraction: float, name: str, message: str) -> None:
        if ctx is not None:
            ctx.check_cancelled()
            ctx.detail(step=name, step_label=COMMIT_STEPS[name])
            ctx.progress(fraction, message)
            ctx.log(message)

    def same_library() -> None:
        if current_or_none() is not ws:
            raise DatasheetError("Die Bibliothek wurde gewechselt – bitte den Vorschlag neu erstellen.")

    scope: CommitScope = choices.scope
    if ctx is not None:
        ctx.detail(datasheet_id=datasheet_id, steps=list(SCOPE_STEPS[scope]), scope=scope)
    step(0.02, "check", "Vorschlag wird erstellt …")
    proposal = build_proposal(datasheet_id, choices, ws=ws, svg=False)
    if ctx is not None:
        ctx.detail(fingerprint=proposal.fingerprint)
    if choices.expected_fingerprint and choices.expected_fingerprint != proposal.fingerprint:
        if ctx is not None:
            ctx.detail(code="proposal_changed", expected_fingerprint=choices.expected_fingerprint)
        raise CommitRefused(
            "Der Vorschlag hat sich seit der Prüfung geändert (z. B. durch inzwischen angelegte Bauteile, Symbole oder "
            "Footprints oder eine geänderte Analyse) – bitte den Vorschlag neu laden und erneut prüfen. Es wurde nichts "
            "geschrieben.", code="proposal_changed")
    if scope == "part":
        problems = _blocking(proposal, choices)
        unconfirmed = list(proposal.unconfirmed_blockers)
        what = "Das Bauteil kann so nicht angelegt werden"
    else:
        problems = _scope_blocking(proposal, choices, scope)
        unconfirmed = _scope_unconfirmed(proposal, scope)
        what = f"{'Die Symbole können' if scope == 'symbols' else 'Die Footprints können'} so nicht gespeichert werden"
    if unconfirmed and ctx is not None:
        ctx.detail(code="unconfirmed_blockers", unconfirmed_blockers=unconfirmed)
    if problems or unconfirmed:
        parts = problems[:4] + ([_confirm_text(unconfirmed)] if unconfirmed else [])
        raise CommitRefused(f"{what}: " + " ".join(parts) + " Es wurde nichts geschrieben.",
                            code="unconfirmed_blockers" if unconfirmed and not problems else "invalid",
                            items=unconfirmed)
    same_library()
    table = proposal.category or ""
    confirmed = proposal.blockers if scope == "part" else [t.blocker for t in proposal.blocker_targets
                                                           if scope in t.scopes]
    warnings: list[str] = [f"Bestätigt: {b}" for b in confirmed]
    failed: dict[str, str] = {}  # "symbol:<name>" / "footprint:<name>" (casefold) -> German reason

    fp_specs = [f.spec for f in proposal.footprints if f.spec is not None and _will_write(f, choices.overwrite_existing)
                and scope in ("part", "footprints")]
    written_fps: list[str] = []
    if fp_specs:
        step(0.1, "footprints", f"{len(fp_specs)} Footprint(s) werden angelegt …")
        for fp_record in sync.ensure_footprints(fp_specs, source="datasheet", ctx=ctx):
            if fp_record.status == "error":
                reason = fp_record.status_message or "Fehler beim Schreiben"
                failed[f"footprint:{fp_record.name.casefold()}"] = reason
                warnings.append(f"Footprint {fp_record.name}: {reason}")
            else:
                written_fps.append(fp_record.name)
    to_write = [s for s in proposal.symbols if s.spec is not None and _will_write(s, choices.overwrite_existing)
                and scope in ("part", "symbols")]
    written_syms: list[str] = []
    if to_write:
        step(0.45, "symbols", f"{len(to_write)} Symbol(e) werden angelegt …")
        # a new pin-out only for the symbols the user confirmed it for (their proposal lists the pin changes)
        changing = [s.spec for s in to_write if s.pin_changes and s.spec is not None]
        others = [s.spec for s in to_write if not s.pin_changes and s.spec is not None]
        records = []
        for specs, allow in ((others, False), (changing, True)):
            if specs:
                records.extend(sync.ensure_symbols(specs, category=table, source="datasheet", ctx=ctx,
                                                   allow_pin_changes=allow))
        for sym_record in records:
            if sym_record.status == "error":
                reason = sym_record.status_message or "Fehler beim Schreiben"
                failed[f"symbol:{sym_record.name.casefold()}"] = reason
                warnings.append(f"Symbol {sym_record.name}: {reason}")
            else:
                written_syms.append(sym_record.name)
    same_library()
    if scope != "part":
        return _scope_done(ctx, datasheet_id, proposal, scope, table=table, symbols=written_syms,
                           footprints=written_fps, failed=failed, warnings=warnings, step=step)

    step(0.8, "parts", f"{len(proposal.variants)} Bauteil(e) werden in „{table}“ gespeichert …")
    rows: list[dict[str, str]] = []
    errors: dict[str, str] = {}
    for item in proposal.variants:
        label = item.part_number or item.mpn
        if item.status == "conflict":
            errors[label] = f"Die Teilenummer existiert bereits in der Kategorie „{item.existing_table}“."
            continue
        reason = failed.get(f"symbol:{(item.symbol or '').casefold()}")
        what = "Symbol"
        if reason is None:
            reason, what = failed.get(f"footprint:{(item.footprint or '').casefold()}"), "Footprint"
        if reason is not None:
            errors[label] = f"Nicht angelegt – {what} konnte nicht geschrieben werden: {reason}"
            continue
        rows.append(dict(item.values))
    result = db_parts.upsert_parts(table, rows, mode=choices.mode, author=author) if rows else UpsertResult()
    for pn, message in result.errors.items():
        errors[pn] = message

    step(0.95, "save", "Datenblatt wird verknüpft …")
    committed = [v.mpn for v in proposal.variants if (v.part_number or v.mpn) not in errors and v.mpn not in errors]
    info = CommitInfo(ts=store.now_iso(), table=table, created=list(result.created), updated=list(result.updated),
                      symbols=written_syms, footprints=written_fps, errors=dict(errors), warnings=list(warnings))

    def link(rec: Any, meta: Any) -> dict[str, Any]:
        meta.committed.append(info)
        return {"mpns": list(dict.fromkeys([*rec.mpns, *committed])),
                "manufacturer": proposal.manufacturer or rec.manufacturer}

    store.update_meta(datasheet_id, link)
    out: dict[str, Any] = {
        "scope": "part",
        "table": table,
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "unchanged": result.unchanged,
        "errors": errors,
        "symbols": written_syms,
        "footprints": written_fps,
        "warnings": warnings,
        "fingerprint": proposal.fingerprint,
    }
    out["message"] = commit_outcome(out)
    if ctx is not None:
        level: Literal["success", "warn"] = "success" if not errors else "warn"
        ctx.log(f"{len(result.created)} neu, {len(result.updated)} aktualisiert, {len(result.skipped)} übersprungen, "
                f"{len(errors)} Fehler", level)
        for pn, message in list(errors.items())[:10]:
            ctx.log(f"{pn}: {message}", "warn")
        ctx.progress(1.0, out["message"])
    return out


def _scope_done(ctx: JobContext | None, datasheet_id: str, proposal: PartProposal, scope: CommitScope, *, table: str,
                symbols: list[str], footprints: list[str], failed: Mapping[str, str], warnings: list[str],
                step: Callable[[float, str, str], None]) -> dict[str, Any]:
    """End of a commit of only the symbols (footprints): record it with the datasheet (no parts, no part numbers)."""
    step(0.95, "save", "Datenblatt wird verknüpft …")
    errors = {key.split(":", 1)[1]: reason for key, reason in failed.items()}  # name (casefold) -> reason
    info = CommitInfo(ts=store.now_iso(), table=table, scope=scope, symbols=symbols, footprints=footprints,
                      errors=dict(errors), warnings=list(warnings))

    def record(_rec: Any, meta: Any) -> None:
        meta.committed.append(info)

    store.update_meta(datasheet_id, record)
    written = symbols if scope == "symbols" else footprints
    items = _scope_items(proposal, scope)
    libraries = sorted({lib for lib in (_library_of(scope, name) for name in written) if lib})
    out: dict[str, Any] = {
        "scope": scope,
        "table": table,
        "created": [],
        "updated": [],
        "skipped": [],
        "unchanged": [],
        "errors": errors,
        "symbols": symbols,
        "footprints": footprints,
        "libraries": libraries,
        "warnings": warnings,
        "fingerprint": proposal.fingerprint,
        # already in the library and not written again (a proposal with several symbols/footprints)
        "reused": [item.name for item in items if item.name and item.name not in written
                   and item.name.casefold() not in errors],
    }
    out["message"] = commit_outcome(out)
    if ctx is not None:
        if libraries:
            ctx.log(f"In {', '.join(libraries)}", "info")
        for name, message in list(errors.items())[:10]:
            ctx.log(f"{name}: {message}", "warn")
        ctx.progress(1.0, out["message"])
    return out


def _library_of(scope: CommitScope, name: str) -> str | None:
    """Library file (relative) a just written symbol/footprint is registered in."""
    rec = registry.get_symbol(name) if scope == "symbols" else registry.get_footprint(name)
    return rec.library if rec is not None and rec.library else None
