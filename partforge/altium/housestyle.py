"""Stapelbearbeitung: check and convert the symbols and footprints of the open library to the house style.

:func:`check` (job ``housestyle.check``, reads only) plans the rules of :mod:`.conform` for a selection of
registered components (default: everything imported) and reports per component what would change, per
footprint library the detected roles of its layers and whether its header deviates. :func:`apply` (job
``libraries.conform``, holds the library) does the same and writes the changed records library by library:

* under :func:`~partforge.altium.rustwriter.library_lock`; a library that is open **and modified** in Altium is
  skipped (one bridge run per 200 files: :meth:`~partforge.altium.sync._AltiumGuard.prefetch`), an open,
  unmodified one is reloaded afterwards;
* the old file goes to ``Backups\\lib`` first; the new streams are written into a checked copy
  (:func:`~partforge.altium.compound.replace_streams`: every other stream byte-identical, the Rust reader must
  list the same components) that then replaces the library – all or nothing per file;
* footprint libraries get the workspace layer stack and layer set in their header – patched where possible,
  otherwise (older or Altium-saved headers) renewed from the Rust writer's template
  (:func:`~partforge.altium.stackup.renew_library_data`);
* the registry follows: PartForge's own components (generated, datasheet) get the same change on their spec
  (their generator data stay), imported ones are read again from the file; the library manifest marks every
  component as PartForge's with unknown content (later writes only replace single components);
* an undo record ``Backups\\lib\\stapelbearbeitung_<time>.json`` (backups + old registry entries) lets
  :func:`undo_last` restore the libraries – only those still unchanged since the conversion.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import shutil
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from ..db import meta as db_meta
from ..db import registry
from ..db.models import FootprintRecord, RecordSource, SymbolRecord
from ..domain.text import plural
from ..geometry.model import FootprintSpec, FpText, SymbolSpec, SymRect, Track
from ..jobs import JobContext
from ..workspace import FootprintStyle, LayerMap, SymbolStyle, Workspace, current
from . import compound
from . import conform as C
from . import pcbrecords as R
from . import schrecords as S
from . import schstyle, stackup
from .libwriter import RustLibraryWriter, WriterUnavailable, library_file_kind
from .rustwriter import RustLibraryOps, RustWriterError, is_inside, store_backup
from .sync import (
    _file_state,
    _library_held,
    _load_manifest,
    _Manifest,
    _rel_key,
    _Session,
    _store_manifest,
    SyncError,
)

log = logging.getLogger(__name__)

__all__ = [
    "ConformSelection",
    "ComponentReport",
    "LibraryReport",
    "ConformReport",
    "check",
    "apply",
    "undo_last",
    "undo_info",
    "saved_rules",
    "remember_rules",
    "UNDO_META_KEY",
    "RULES_META_KEY",
    "symbol_spec_after",
    "footprint_spec_after",
]

Kind = Literal["symbol", "footprint"]
UNDO_META_KEY: Final = "housestyle.last"
RULES_META_KEY: Final = "housestyle.rules"
UNDO_PREFIX: Final = "stapelbearbeitung_"
MAX_REPORTED: Final = 5000
_OWN_SOURCES: Final = frozenset({"generated", "datasheet"})


# --------------------------------------------------------------------------- models


class ConformSelection(BaseModel):
    """Which registered components the batch edit covers."""

    kinds: list[Kind] = Field(default_factory=lambda: ["symbol", "footprint"])
    sources: list[RecordSource] | None = Field(
        default_factory=lambda: ["imported"], description="Herkunft (None = alle außer extern)")
    libraries: list[str] | None = Field(default=None, description="Bibliotheksdateien (relativ), None = alle")
    names: list[str] | None = Field(default=None, description="Einzelne Symbole/Footprints, None = alle")


class ComponentReport(BaseModel):
    kind: Kind
    name: str
    library: str
    source: str
    changes: list[C.Change] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class LibraryReport(BaseModel):
    library: str
    kind: Literal["schlib", "pcblib"]
    components: int = 0
    selected: int = 0
    affected: int = 0
    roles: list[C.LayerRole] = Field(default_factory=list)
    header: list[str] = Field(default_factory=list, description="Abweichungen des Lagen-Kopfs")
    fonts: list[str] = Field(default_factory=list, description="Schrifttabelle nach der Umstellung")
    refusal: str | None = None
    problem: str | None = None


class ConformReport(BaseModel):
    checked: int = 0
    affected: int = 0
    summary: dict[str, int] = Field(
        default_factory=dict, description="Regel -> betroffene Bauteile (header: Bibliotheken mit abweichendem Kopf)")
    libraries: list[LibraryReport] = Field(default_factory=list)
    components: list[ComponentReport] = Field(default_factory=list, description="Bauteile mit Änderungen/Problemen")
    truncated: bool = False
    message: str = ""


# --------------------------------------------------------------------------- rules of the library


def saved_rules() -> C.ConformRules:
    """The rules last used in the open library (``pf_meta``), else the defaults."""
    raw = db_meta.get_meta(RULES_META_KEY)
    if raw:
        try:
            return C.ConformRules.model_validate(json.loads(raw))
        except (ValueError, TypeError):
            log.info("Gespeicherte Regeln der Stapelbearbeitung nicht lesbar – Standardregeln.")
    return C.ConformRules()


def remember_rules(rules: C.ConformRules) -> None:
    """Keep ``rules`` as the library's rules (convenience: a failure is only logged)."""
    try:
        db_meta.set_meta(RULES_META_KEY, rules.model_dump_json())
    except Exception as exc:  # noqa: BLE001 - remembering the rules is a convenience
        log.info("Regeln der Stapelbearbeitung nicht gespeichert: %s", exc)


# --------------------------------------------------------------------------- selection


@dataclass
class _Target:
    rel: str
    path: Path
    kind: Literal["schlib", "pcblib"]
    records: dict[str, SymbolRecord | FootprintRecord] = field(default_factory=dict)  # casefolded name


def _targets(ws: Workspace, selection: ConformSelection) -> list[_Target]:
    """Registered components of the selection grouped by library file (inside the workspace, existing)."""
    sources = set(selection.sources) if selection.sources else None
    names = {n.casefold() for n in selection.names} if selection.names else None
    libraries = {_rel_key(lib) for lib in selection.libraries} if selection.libraries else None
    targets: dict[str, _Target] = {}
    kinds: list[tuple[Kind, Iterable[SymbolRecord | FootprintRecord]]] = []
    if "symbol" in selection.kinds:
        kinds.append(("symbol", registry.list_symbols(with_spec=False, with_usage=False)))
    if "footprint" in selection.kinds:
        kinds.append(("footprint", registry.list_footprints(with_spec=False, with_usage=False)))
    for kind, records in kinds:
        for rec in records:
            if rec.source == "external" or not rec.library:
                continue
            if sources is not None and rec.source not in sources:
                continue
            if names is not None and rec.name.casefold() not in names:
                continue
            if libraries is not None and _rel_key(rec.library) not in libraries:
                continue
            path = ws.abs(rec.library)
            if path is None or not path.is_file() or not is_inside(path, ws.root):
                continue
            file_kind = library_file_kind(path)
            if file_kind != ("schlib" if kind == "symbol" else "pcblib"):
                continue
            key = _rel_key(rec.library)
            target = targets.setdefault(key, _Target(rel=ws.rel(path), path=path, kind=file_kind))
            target.records[rec.name.casefold()] = rec
    return sorted(targets.values(), key=lambda t: (t.kind, t.rel.casefold()))


# --------------------------------------------------------------------------- planning per library


@dataclass
class _LibraryPlan:
    target: _Target
    report: LibraryReport
    components: list[ComponentReport] = field(default_factory=list)
    streams: dict[str, bytes] = field(default_factory=dict)
    symbol_plans: dict[str, C.SymbolPlan] = field(default_factory=dict)
    footprint_plans: dict[str, C.FootprintPlan] = field(default_factory=dict)
    header_changed: bool = False


def _plan_schlib(target: _Target, rules: C.ConformRules, style: SymbolStyle) -> _LibraryPlan:
    report = LibraryReport(library=target.rel, kind="schlib")
    plan = _LibraryPlan(target=target, report=report)
    tree = compound.read_tree_file(target.path)
    header_raw = tree.get("FileHeader")
    if header_raw is None:
        raise SyncError(f"{target.path.name}: kein Bibliothekskopf.")
    header = S.parse_header(header_raw)
    fonts_before = header.fonts()
    font_ids: schstyle.FontIds | None = None
    fonts = fonts_before
    if rules.symbols.fonts:
        fonts, font_ids = schstyle.plan_font_table(fonts_before, style)
    report.fonts = [f.label() for f in fonts]
    storages = schstyle.component_streams(tree)
    report.components = len(storages)
    for storage, name in storages.items():
        rec = target.records.get(name.casefold())
        if rec is None:
            continue
        report.selected += 1
        data = tree.get(f"{storage}/Data")
        assert data is not None
        try:
            records = S.parse_records(data)
            pin_raw = tree.get(f"{storage}/PinTextData")
            pin_text = S.parse_pin_text_data(pin_raw)
            symbol_plan = C.plan_symbol(name, records, pin_text, rules.symbols, style, font_ids)
        except (S.SchRecordError, ValueError) as exc:
            plan.components.append(ComponentReport(kind="symbol", name=name, library=target.rel, source=rec.source,
                                                   problems=[f"Nicht lesbar: {exc}"]))
            continue
        if not symbol_plan.modified:
            continue
        report.affected += 1
        plan.symbol_plans[name] = symbol_plan
        plan.components.append(ComponentReport(kind="symbol", name=name, library=target.rel, source=rec.source,
                                               changes=symbol_plan.changes))
        plan.streams[f"{storage}/Data"] = S.build_records(symbol_plan.records)
        built = S.build_pin_text_data(symbol_plan.pin_text)
        if built is not None:
            if built != pin_raw:
                plan.streams[f"{storage}/PinTextData"] = built
        elif pin_raw is not None and S.parse_pin_text_data(pin_raw):
            plan.streams[f"{storage}/PinTextData"] = schstyle._empty_pin_text_data()
    if plan.symbol_plans and [f.key() for f in fonts] != [f.key() for f in fonts_before]:
        header.set_fonts(fonts)
        plan.streams["FileHeader"] = header.to_bytes()
    return plan


def _plan_pcblib(
    target: _Target,
    rules: C.ConformRules,
    style: FootprintStyle,
    layer_map: LayerMap,
    stack: stackup.LayerStack,
    ops: RustLibraryOps | None,
) -> _LibraryPlan:
    report = LibraryReport(library=target.rel, kind="pcblib")
    plan = _LibraryPlan(target=target, report=report)
    footprints = R.read_footprints(target.path)
    report.components = len(footprints)
    try:
        header_layers: Mapping[int, Any] = stackup.read_pcblib_layers(target.path)
    except Exception:  # noqa: BLE001 - older headers: roles come from names/content only
        header_layers = {}
    manual = rules.footprints.roles.get(target.rel) or next(
        (v for k, v in rules.footprints.roles.items() if _rel_key(k) == _rel_key(target.rel)), None)
    roles = C.infer_layer_roles([rec for _storage, rec in footprints.values()], header_layers, manual)
    report.roles = list(roles.values())
    side_names = ("PrimitiveGuids/Data", "UniqueIDPrimitiveInformation/Data")
    for key, (storage, records) in footprints.items():
        rec = target.records.get(key)
        if rec is None:
            continue
        report.selected += 1
        fp_plan = C.plan_footprint(records, roles, rules.footprints, style, layer_map)
        if not fp_plan.modified:
            continue
        report.affected += 1
        plan.footprint_plans[records.name] = fp_plan
        plan.components.append(ComponentReport(kind="footprint", name=records.name, library=target.rel,
                                               source=rec.source, changes=fp_plan.changes))
        if fp_plan.new:
            current = compound.read_streams(target.path, [f"{storage}/{n}" for n in side_names])
            side = R.insert_primitives(fp_plan.records, fp_plan.new,
                                       {n: current.get(f"{storage}/{n}") for n in side_names})
            for name, data in side.items():
                if name.startswith("PrimitiveGuids/") and current.get(f"{storage}/PrimitiveGuids/Data") is None:
                    continue
                plan.streams[f"{storage}/{name}"] = data
        plan.streams[f"{storage}/Data"] = fp_plan.records.to_bytes()
    if rules.footprints.header:
        header_streams = _header_streams(target.path, stack, ops)
        if header_streams:
            plan.header_changed = True
            plan.streams.update(header_streams)
            report.header = stackup.pcblib_layer_problems(target.path, stack) or ["Lagen-Kopf wird erneuert."]
    return plan


def _header_streams(path: Path, stack: stackup.LayerStack, ops: RustLibraryOps | None) -> dict[str, bytes]:
    """New ``Library/Data`` (+ empty layer kind table) when the header deviates from the stack/layer set."""
    streams = compound.read_streams(path, ["Library/Data", "Library/LayerKindMapping/Data"])
    data = streams.get("Library/Data")
    if data is None:
        return {}
    kind_mapping = streams.get("Library/LayerKindMapping/Data")
    try:
        new = stackup.plan_library_data(data, kind_mapping, stack)
        return {"Library/Data": new} if new is not None else {}
    except stackup.HeaderStructureError:
        if ops is None:
            return {}
        template = ops.template_library_data()
        renewed = stackup.renew_library_data(data, template, stack)
        out = {"Library/Data": renewed}
        if kind_mapping is not None and kind_mapping != stackup.EMPTY_KIND_MAPPING:
            out["Library/LayerKindMapping/Data"] = stackup.EMPTY_KIND_MAPPING
        return out


def _plan(target: _Target, rules: C.ConformRules, ws: Workspace, stack: stackup.LayerStack,
          ops: RustLibraryOps | None) -> _LibraryPlan:
    if target.kind == "schlib":
        return _plan_schlib(target, rules, ws.settings.symbol)
    return _plan_pcblib(target, rules, ws.settings.footprint, ws.settings.layers, stack, ops)


def _ops(session: _Session) -> RustLibraryOps | None:
    try:
        writer = session.writer()
    except WriterUnavailable:
        return None
    return writer.ops if isinstance(writer, RustLibraryWriter) else None


def _workspace_stack(ws: Workspace) -> stackup.LayerStack:
    base, _notes = stackup.workspace_stack(ws)
    return stackup.effective_stack(base, ws.settings.layers)


# --------------------------------------------------------------------------- report


def _finish_report(report: ConformReport, components: list[ComponentReport]) -> ConformReport:
    affected = [c for c in components if c.changes]
    report.affected = len(affected)
    counts: Counter[str] = Counter()
    for comp in affected:
        for rule in {ch.rule for ch in comp.changes}:
            counts[rule] += 1
    for lib in report.libraries:
        if lib.header:
            counts["header"] += 1
    report.summary = dict(sorted(counts.items()))
    shown = [c for c in components if c.changes or c.problems]
    report.truncated = len(shown) > MAX_REPORTED
    report.components = shown[:MAX_REPORTED]
    return report


def check_message(report: ConformReport) -> str:
    if not report.checked:
        return "Keine passenden Symbole oder Footprints gefunden."
    if not report.affected and not any(lib.header for lib in report.libraries):
        return f"Alles im Hausstil: {plural(report.checked, 'Bauteil', 'Bauteile')} geprüft."
    headers = sum(1 for lib in report.libraries if lib.header)
    extra = f", {plural(headers, 'Lagen-Kopf', 'Lagen-Köpfe')}" if headers else ""
    return (f"{plural(report.checked, 'Bauteil', 'Bauteile')} geprüft – {report.affected} weichen vom Hausstil ab"
            f"{extra}.")


def check(selection: ConformSelection, rules: C.ConformRules, *, ctx: JobContext | None = None) -> ConformReport:
    """What :func:`apply` would change (reads only)."""
    ws = current()
    session = _Session(ws, ctx)
    report = ConformReport()
    components: list[ComponentReport] = []
    try:
        targets = _targets(ws, selection)
        stack = _workspace_stack(ws)
        ops = _ops(session) if rules.footprints.header else None
        session.altium.prefetch([t.path for t in targets])  # one bridge run per 200 files (only if Altium runs)
        for index, target in enumerate(targets):
            session.check_cancelled()
            session.progress(index / max(1, len(targets)), f"Prüfe {target.path.name} …")
            try:
                plan = _plan(target, rules, ws, stack, ops)
            except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the check
                log.warning("Hausstil-Prüfung von %s nicht möglich: %s", target.path, exc)
                lib_report = LibraryReport(library=target.rel, kind=target.kind, selected=len(target.records),
                                           problem=f"Nicht lesbar: {exc}")
                report.libraries.append(lib_report)
                report.checked += len(target.records)
                continue
            plan.report.refusal = session.altium.refusal(target.path) if plan.streams else None
            report.libraries.append(plan.report)
            report.checked += plan.report.selected
            components.extend(plan.components)
        _finish_report(report, components)
        report.message = check_message(report)
        session.progress(1.0, report.message)
    finally:
        session.finish()
    return report


# --------------------------------------------------------------------------- spec transforms (own components)


def _spec_is_box(spec: SymbolSpec) -> bool:
    rects = [g for g in spec.graphics if isinstance(g, SymRect)]
    pins = [p for p in spec.pins]
    if not rects or not pins:
        return False

    def on_edge(pin: Any) -> bool:
        for r in rects:
            x1, x2 = min(r.x1, r.x2), max(r.x1, r.x2)
            y1, y2 = min(r.y1, r.y2), max(r.y1, r.y2)
            if pin.orientation == "left" and abs(pin.x - x1) < 0.5 and y1 <= pin.y <= y2:
                return True
            if pin.orientation == "right" and abs(pin.x - x2) < 0.5 and y1 <= pin.y <= y2:
                return True
            if pin.orientation == "down" and abs(pin.y - y1) < 0.5 and x1 <= pin.x <= x2:
                return True
            if pin.orientation == "up" and abs(pin.y - y2) < 0.5 and x1 <= pin.x <= x2:
                return True
        return False

    return sum(1 for p in pins if on_edge(p)) * 10 >= len(pins) * 8


def symbol_spec_after(spec: SymbolSpec, rules: C.SymbolRules, style: SymbolStyle) -> SymbolSpec:
    """The spec-level equivalent of :func:`conform.plan_symbol` (fonts are no part of the model)."""
    update: dict[str, Any] = {}
    box = _spec_is_box(spec)
    if rules.pin_length and box:
        wanted = max(10, round(int(style.ic_pin_length) / 10) * 10)
        update["pins"] = [p.model_copy(update={"length": wanted}) for p in spec.pins]
    if rules.prefix and rules.prefix_map:
        new = rules.prefix_map.get(spec.designator_prefix.upper())
        if new:
            update["designator_prefix"] = new
    if rules.colors and box:
        update["graphics"] = [
            g.model_copy(update={"color": style.ic_line_color, "fill_color": style.ic_fill_color})
            if isinstance(g, SymRect) else g
            for g in spec.graphics
        ]
    return spec.model_copy(update=update) if update else spec


def _spec_bounds(spec: FootprintSpec, layer: str) -> tuple[float, float, float, float] | None:
    box = spec.bbox({layer})
    return None if box == (0.0, 0.0, 0.0, 0.0) else box


def footprint_spec_after(spec: FootprintSpec, rules: C.FootprintRules, style: FootprintStyle) -> FootprintSpec:
    """The spec-level equivalent of :func:`conform.plan_footprint` for PartForge's own footprints (their layers
    are logical: the layer rule needs no change)."""
    update: dict[str, Any] = {}
    widths = {"assembly": style.assembly_width, "component_outline": style.assembly_width,
              "courtyard": style.courtyard_width, "component_center": C.CROSS_WIDTH}
    if rules.silk_width:
        widths["top_silk"] = style.silk_width
    if rules.widths:
        update["tracks"] = [t.model_copy(update={"width": widths[t.layer]}) if t.layer in widths else t
                            for t in spec.tracks]
        update["arcs"] = [a.model_copy(update={"width": widths[a.layer]})
                          if a.layer in widths and a.width < 1.5 * a.r else a for a in spec.arcs]
    courtyard = _spec_bounds(spec, "courtyard")
    pads = spec.bbox({"copper"}) if spec.pads else None
    height = C.text_height_for(courtyard or pads, style)
    font = style.text_font
    font_name = (style.text_font_name or "Arial") if font == "truetype" else None
    stroke = round(max(0.05, round(0.15 * height / 0.01) * 0.01), 4)
    texts = list(spec.texts)
    if rules.texts:
        texts = [t.model_copy(update={"font": font, "font_name": font_name, "height": height, "stroke": stroke})
                 if t.layer in ("designator", "comment") else t for t in texts]
    if rules.add_texts:
        for layer, content in (("designator", ".Designator"), ("comment", ".Comment")):
            if not any(t.layer == layer for t in texts):
                texts.append(FpText(layer=layer, x=0, y=0, text=content, height=height, stroke=stroke,  # type: ignore[arg-type]
                                    justify="middle_center", font=font, font_name=font_name))
    if texts != list(spec.texts):
        update["texts"] = texts
    if rules.add_center and not any(t.layer == "component_center" for t in spec.tracks):
        ref = _spec_bounds(spec, "assembly") or courtyard or pads
        half = C.center_cross_half(ref)
        tracks = list(update.get("tracks", spec.tracks))
        tracks += [Track(layer="component_center", x1=-half, y1=0, x2=half, y2=0, width=C.CROSS_WIDTH),
                   Track(layer="component_center", x1=0, y1=-half, x2=0, y2=half, width=C.CROSS_WIDTH)]
        update["tracks"] = tracks
    return spec.model_copy(update=update) if update else spec


# --------------------------------------------------------------------------- apply


def _verify(ops: RustLibraryOps | None, path: Path) -> Any:
    if ops is None:
        return None
    expected = ops.list_components(path)

    def verify(copy: Path) -> None:
        # the copy carries another name: list it like the library (the reader needs the right extension)
        if ops.list_components(copy) != expected:
            raise RustWriterError("Der Rust-Reader liest die angepasste Bibliothek nicht identisch.")

    return verify


def _undo_dir(ws: Workspace) -> Path:
    return ws.backups_dir / "lib"


def _updated_records(
    session: _Session,
    plan: _LibraryPlan,
    rules: C.ConformRules,
    ops: RustLibraryOps | None,
) -> tuple[list[SymbolRecord], list[FootprintRecord], list[dict[str, Any]]]:
    """Registry records after the conversion and the old records (for undo)."""
    ws = session.ws
    symbols: list[SymbolRecord] = []
    footprints: list[FootprintRecord] = []
    old: list[dict[str, Any]] = []
    path = plan.target.path
    for name in plan.symbol_plans:
        rec = registry.get_symbol(name, with_usage=False)
        if rec is None:
            continue
        old.append({"kind": "symbol", "record": rec.model_dump(mode="json", exclude={"usage", "content_hash"})})
        spec = rec.spec
        if rec.source in _OWN_SOURCES and spec is not None:
            spec = symbol_spec_after(spec, rules.symbols, ws.settings.symbol)
        elif ops is not None:
            try:
                spec = ops.read_symbol(path, rec.name) or spec
            except RustWriterError as exc:
                log.info("%s nach der Umstellung nicht neu gelesen: %s", rec.name, exc)
        symbols.append(rec.model_copy(update={
            "spec": spec, "pin_count": len(spec.pins) if spec else rec.pin_count, "status": "ok", "status_message": None,
        }))
    for name in plan.footprint_plans:
        rec = registry.get_footprint(name, with_usage=False)
        if rec is None:
            continue
        old.append({"kind": "footprint", "record": rec.model_dump(mode="json", exclude={"usage", "content_hash"})})
        fp = rec.spec
        if rec.source in _OWN_SOURCES and fp is not None:
            fp = footprint_spec_after(fp, rules.footprints, ws.settings.footprint)
        elif ops is not None:
            try:
                fresh = ops.read_footprint(path, rec.name, extract_step=False)
            except RustWriterError as exc:
                log.info("%s nach der Umstellung nicht neu gelesen: %s", rec.name, exc)
                fresh = None
            if fresh is not None:
                fp = fresh.model_copy(update={"step": rec.spec.step if rec.spec else None,
                                              "height": fresh.height or (rec.spec.height if rec.spec else None)})
        footprints.append(rec.model_copy(update={"spec": fp, "status": "ok", "status_message": None}))
    return symbols, footprints, old


def _own_manifest(rel: str, path: Path, names: Iterable[str]) -> _Manifest | None:
    """Manifest after the conversion: every component PartForge's, content unknown (only upserts later)."""
    state = _file_state(path)
    if state is None:
        return None
    before = _load_manifest(rel)
    components: dict[str, str | None] = {n.casefold(): None for n in names}
    if before is not None:
        for key in before.components:
            components.setdefault(key, None)
    return _Manifest(rel=rel, size=state[0], mtime_ns=state[1], sha256=state[2], components=components)


def apply_message(out: Mapping[str, Any]) -> str:
    converted = int(out.get("components") or 0)
    libraries = len(out.get("libraries") or [])
    skipped = len(out.get("skipped") or [])
    errors = len(out.get("errors") or [])
    if not converted and not libraries:
        text = "Hausstil: nichts zu ändern."
    else:
        text = (f"Hausstil angewendet: {plural(converted, 'Bauteil', 'Bauteile')} in "
                f"{plural(libraries, 'Bibliothek', 'Bibliotheken')}")
        text += "."
    extra = []
    if skipped:
        extra.append(f"{plural(skipped, 'Bibliothek', 'Bibliotheken')} übersprungen")
    if errors:
        extra.append(plural(errors, "Fehler", "Fehler"))
    return text + (f" ({', '.join(extra)})" if extra else "")


def apply(selection: ConformSelection, rules: C.ConformRules, *, ctx: JobContext | None = None) -> dict[str, Any]:
    """Convert the selection to the house style (see the module docstring). Result: ``components``,
    ``libraries`` (written), ``skipped`` ``[{library, message}]``, ``errors``, ``report`` (what changed),
    ``undo`` (record file), ``message``."""
    ws = current()
    session = _Session(ws, ctx, watch=True)
    out: dict[str, Any] = {"components": 0, "libraries": [], "skipped": [], "errors": [], "undo": None,
                           "report": None, "message": ""}
    undo: dict[str, Any] = {"version": 1, "created": _dt.datetime.now().isoformat(timespec="seconds"),
                            "libraries": [], "records": []}
    components: list[ComponentReport] = []
    report = ConformReport()
    try:
        session.ensure_current()
        targets = _targets(ws, selection)
        stack = _workspace_stack(ws)
        ops = _ops(session)
        session.altium.prefetch([t.path for t in targets])
        backups = _undo_dir(ws)
        try:
            for index, target in enumerate(targets):
                session.check_cancelled()
                session.progress(index / max(1, len(targets)), f"{target.path.name} …")
                with _library_held(target.path) as busy:
                    if busy:
                        out["skipped"].append({"library": target.rel, "message": busy})
                        continue
                    refusal = session.altium.refusal(target.path)
                    if refusal:
                        out["skipped"].append({"library": target.rel, "message": refusal})
                        session.log(f"{target.rel}: {refusal}", "warn")
                        continue
                    try:
                        plan = _plan(target, rules, ws, stack, ops)
                    except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the batch
                        out["errors"].append({"library": target.rel, "message": f"Nicht lesbar: {exc}"})
                        session.log(f"{target.rel}: nicht lesbar ({exc})", "error")
                        continue
                    report.libraries.append(plan.report)
                    report.checked += plan.report.selected
                    components.extend(plan.components)
                    if not plan.streams:
                        continue
                    names = [c.name for c in plan.components if c.changes]
                    try:
                        backup = store_backup(target.path, target.path, backups)
                        compound.replace_streams(target.path, plan.streams, verify=_verify(ops, target.path),
                                                 tag="pfstd", create=True)
                    except Exception as exc:  # noqa: BLE001 - COM, OS, verify: the library stays unchanged
                        log.warning("Hausstil für %s nicht angewendet: %s", target.path, exc, exc_info=True)
                        out["errors"].append({"library": target.rel, "message": f"Nicht geändert: {exc}"})
                        session.log(f"{target.rel}: nicht geändert ({exc})", "error")
                        continue
                    state = _file_state(target.path)
                    # undoable from here on – even if updating the registry fails below
                    undo["libraries"].append({"library": target.rel, "backup": ws.rel(backup),
                                              "sha256": state[2] if state else None})
                    symbols, footprints, old = _updated_records(session, plan, rules, ops)
                    undo["records"].extend(old)
                    all_names = (list(schstyle.component_streams(compound.read_tree_file(target.path)).values())
                                 if target.kind == "schlib" else
                                 [rec.name for _s, rec in R.read_footprints(target.path).values()])
                    with session.bound():
                        if symbols:
                            registry.upsert_symbols(symbols)
                        if footprints:
                            registry.upsert_footprints(footprints)
                        _store_manifest(target.rel, _own_manifest(target.rel, target.path, all_names))
                    out["libraries"].append(target.rel)
                    out["components"] += len(names)
                    session.written.append(str(target.path))
                    session.log(f"{target.rel}: {plural(len(names), 'Bauteil', 'Bauteile')} angepasst"
                                + (" (Lagen-Kopf erneuert)" if plan.header_changed else ""), "success")
                    note = session.altium.reload(target.path)
                    if note:
                        session.log(note)
        finally:
            # also after a cancel: what was written can be undone
            if undo["libraries"]:
                out["undo"] = _store_undo(session, backups, undo)
        _finish_report(report, components)
        report.message = check_message(report)
        out["report"] = report.model_dump(mode="json")
        out["message"] = apply_message(out)
        session.progress(1.0, out["message"])
    finally:
        session.finish()
    return out


# --------------------------------------------------------------------------- undo


def _store_undo(session: _Session, backups: Path, undo: Mapping[str, Any]) -> str | None:
    """Write the undo record of a conversion and make it the library's last one (``None`` if that failed – the
    backups in ``Backups\\lib`` stay)."""
    ws = session.ws
    try:
        backups.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        record = backups / f"{UNDO_PREFIX}{stamp}_{uuid.uuid4().hex[:6]}.json"
        record.write_text(json.dumps(undo, ensure_ascii=False), encoding="utf-8")
        with session.bound():
            db_meta.set_meta(UNDO_META_KEY, ws.rel(record))
        return ws.rel(record)
    except Exception as exc:  # noqa: BLE001 - never hide the result (or the cancel) of the conversion
        log.warning("Rückgängig-Datensatz der Stapelbearbeitung nicht gespeichert: %s", exc, exc_info=True)
        session.log(f"Rückgängig-Datensatz nicht gespeichert: {exc} – die Sicherungen liegen in Backups\\lib.", "warn")
        return None


def undo_info() -> dict[str, Any] | None:
    """The last conversion that can be undone: ``{created, libraries, file}`` or ``None``."""
    ws = current()
    rel = db_meta.get_meta(UNDO_META_KEY)
    if not rel:
        return None
    path = ws.abs(rel)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"created": data.get("created"), "libraries": [e.get("library") for e in data.get("libraries") or []],
            "file": rel}


def undo_last(*, ctx: JobContext | None = None) -> dict[str, Any]:
    """Undo the last conversion: libraries still unchanged since then get their backup back, the registry
    entries their old content. Result: ``restored``, ``skipped`` ``[{library, message}]``, ``message``."""
    ws = current()
    session = _Session(ws, ctx, watch=True)
    out: dict[str, Any] = {"restored": [], "skipped": [], "message": ""}
    try:
        rel = db_meta.get_meta(UNDO_META_KEY)
        path = ws.abs(rel) if rel else None
        if path is None or not path.is_file():
            raise SyncError("Es gibt keine Stapelbearbeitung, die sich rückgängig machen ließe.", status=404)
        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("libraries") or []
        session.altium.prefetch([p for p in (ws.abs(e.get("library", "")) for e in entries) if p is not None])
        restored_rels: set[str] = set()
        keep: list[dict[str, Any]] = []  # entries a later undo can still restore (busy, open in Altium, not reached)
        position = 0
        try:
            for position, entry in enumerate(entries):
                session.check_cancelled()
                library = ws.abs(entry.get("library", ""))
                backup = ws.abs(entry.get("backup", ""))
                label = entry.get("library", "?")
                session.progress(position / max(1, len(entries)), f"{label} …")
                if library is None or backup is None or not backup.is_file():
                    out["skipped"].append({"library": label, "message": "Sicherung nicht mehr vorhanden."})
                    continue
                with _library_held(library) as busy:
                    if busy:
                        out["skipped"].append({"library": label, "message": busy})
                        keep.append(entry)
                        continue
                    state = _file_state(library) if library.is_file() else None
                    if state is None or (entry.get("sha256") and state[2] != entry.get("sha256")):
                        out["skipped"].append({"library": label, "message": "Seit der Stapelbearbeitung geändert – "
                                                                              "nicht zurückgesetzt."})
                        continue
                    refusal = session.altium.refusal(library)
                    if refusal:
                        out["skipped"].append({"library": label, "message": refusal})
                        keep.append(entry)
                        continue
                    store_backup(library, library, _undo_dir(ws))
                    temp = library.with_name(f"{library.stem}.pfundo{uuid.uuid4().hex[:8]}{library.suffix}")
                    shutil.copyfile(backup, temp)
                    os.replace(temp, library)
                    restored_rels.add(_rel_key(entry.get("library")))
                    out["restored"].append(label)
                    session.written.append(str(library))
                    note = session.altium.reload(library)
                    if note:
                        session.log(note)
            position = len(entries)
        finally:
            # cancelled or failed: the rest stays undoable (a library restored just before stays restored)
            keep.extend(e for e in entries[position:] if _rel_key(e.get("library")) not in restored_rels)
            _finish_undo(session, path, data, restored_rels, out["restored"], keep)
        restored = len(out["restored"])
        out["message"] = (f"Stapelbearbeitung rückgängig gemacht: {plural(restored, 'Bibliothek', 'Bibliotheken')}"
                          + (f" ({len(out['skipped'])} übersprungen)" if out["skipped"] else "") + ".")
        session.progress(1.0, out["message"])
    finally:
        session.finish()
    return out


def _finish_undo(session: _Session, path: Path, data: dict[str, Any], restored_rels: set[str],
                 restored: list[str], keep: list[dict[str, Any]]) -> None:
    """After (part of) an undo: the restored libraries get their old registry entries and a fresh manifest; the
    record keeps only what a later undo can still restore (none left: no undo is offered any more)."""
    ws = session.ws
    try:
        symbols: list[SymbolRecord] = []
        footprints: list[FootprintRecord] = []
        records = data.get("records") or []
        for item in records:
            record = item.get("record") or {}
            if _rel_key(record.get("library")) not in restored_rels:
                continue
            if item.get("kind") == "symbol":
                symbols.append(SymbolRecord.model_validate(record))
            else:
                footprints.append(FootprintRecord.model_validate(record))
        with session.bound():
            if symbols:
                registry.upsert_symbols(symbols)
            if footprints:
                registry.upsert_footprints(footprints)
            for rel_lib in restored:
                lib_path = ws.abs(rel_lib)
                if lib_path is not None:
                    manifest = _load_manifest(rel_lib)
                    if manifest is not None:
                        state = _file_state(lib_path)
                        if state is not None:
                            _store_manifest(rel_lib, manifest.model_copy(update={
                                "size": state[0], "mtime_ns": state[1], "sha256": state[2],
                                "components": {k: None for k in manifest.components}}))
            if keep:
                kept = {_rel_key(e.get("library")) for e in keep}
                rest = dict(data, libraries=keep,
                            records=[r for r in records if _rel_key((r.get("record") or {}).get("library")) in kept])
                path.write_text(json.dumps(rest, ensure_ascii=False), encoding="utf-8")
            else:
                db_meta.set_meta(UNDO_META_KEY, None)
    except Exception as exc:  # noqa: BLE001 - never hide the result (or the cancel) of the undo
        log.warning("Rückgängig der Stapelbearbeitung nicht vollständig nachgetragen: %s", exc, exc_info=True)
        session.log(f"Registry nach dem Rückgängigmachen nicht vollständig nachgetragen: {exc}", "warn")
