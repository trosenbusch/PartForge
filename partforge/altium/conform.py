"""House-style rules for existing symbols and footprints (batch edit, "Stapelbearbeitung") – the planning core.

Imported libraries (Celestial, vendor files, older own libraries) use other fonts, pin lengths and
mechanical layers than the house style. This module decides, per component, what has to change and applies
it to the **raw records** (:mod:`.schrecords`, :mod:`.pcbrecords`) – losslessly: everything a rule does not
touch keeps its bytes, names never change. The library-level job (reading files, backups, registry,
Altium safety) lives in :mod:`.housestyle`.

Rules (:class:`ConformRules`, every one can be switched off):

Symbols
    ``fonts``       house fonts: font table, ``FontID`` of designator/Comment/parameters/texts, custom pin
                    fonts (:mod:`.schstyle`).
    ``pin_length``  pins of box symbols (rectangle body, pins on its edges – ICs) get
                    ``SymbolStyle.ic_pin_length``; the end at the body stays, the tip moves.
    ``prefix``      designator prefixes after a map (``IC`` → ``U`` by default).
    ``colors``      box border/fill and pin colour of the house style.

Footprints
    ``layers``      every primitive moves to the layer of its **role** in the workspace ``LayerMap``. The
                    role of a source layer comes from the library header (layer kind, then name), else from
                    the content of all footprints of the library (outer outline enclosing the pads =
                    courtyard, inner = assembly), and can be set by hand (``FootprintRules.roles``). A centre
                    cross through the origin is the component centre (a second cross on the courtyard is the
                    courtyard cross of ``FootprintStyle.center_cross``: :func:`center_crosses`),
                    ``.Designator``/``.Comment`` texts the designator/value, 3D bodies the 3D layer – whatever
                    layer they sit on.
    ``widths``      line widths per role (assembly/outline 0.1, courtyard 0.05, crosses 0.1 mm – the style);
                    silkscreen only with ``silk_width``.
    ``texts``       ``.Designator``/``.Comment`` in the house text font and height (centre kept).
    ``add_texts``   missing ``.Designator``/``.Comment`` are added at the origin.
    ``add_center``  a missing component centre cross is added.
    ``header``      the PcbLib header gets the workspace layer stack and layer set.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from pydantic import BaseModel, Field

from ..workspace import FootprintStyle, LayerMap, SymbolStyle
from . import layers as L
from . import pcbrecords as R
from . import schrecords as S
from . import schstyle

__all__ = [
    "Role",
    "ROLE_LABELS",
    "MAPPED_ROLES",
    "RULE_LABELS",
    "SymbolRules",
    "FootprintRules",
    "ConformRules",
    "Change",
    "LayerRole",
    "FootprintPlan",
    "SymbolPlan",
    "infer_layer_roles",
    "primitive_roles",
    "plan_footprint",
    "plan_symbol",
    "is_box_symbol",
    "parse_prefix_map",
    "text_height_for",
    "center_cross_half",
    "center_crosses",
]

Role = Literal[
    "silkscreen", "assembly", "designator", "comment", "courtyard", "component_center", "component_outline",
    "body3d", "keep",
]
#: Roles PartForge moves to the layer of the workspace LayerMap (field of :class:`LayerMap` = role).
MAPPED_ROLES: Final[tuple[str, ...]] = (
    "assembly", "designator", "comment", "courtyard", "component_center", "component_outline", "body3d",
)
ROLE_LABELS: Final[dict[str, str]] = {
    "silkscreen": "Bestückungsdruck",
    "assembly": "Bestückungszeichnung",
    "designator": "Bezeichner",
    "comment": "Wert",
    "courtyard": "Courtyard",
    "component_center": "Bauteilmitte",
    "component_outline": "Bauteilumriss",
    "body3d": "3D-Körper",
    "keep": "unverändert",
}
RULE_LABELS: Final[dict[str, str]] = {
    "fonts": "Schriften",
    "pin_length": "Pinlängen",
    "prefix": "Bezeichner-Präfix",
    "colors": "Farben",
    "layers": "Lagen",
    "widths": "Linienbreiten",
    "texts": "Texte",
    "add_texts": "Fehlende Texte",
    "add_center": "Bauteilmitte",
    "header": "Lagen-Kopf",
}
#: Layer kind (MECHKIND) of the header -> role.
KIND_ROLES: Final[dict[str, str]] = {
    "AssemblyTop": "assembly",
    "DesignatorTop": "designator",
    "3DBodyTop": "body3d",
    "CourtyardTop": "courtyard",
    "ComponentCenterTop": "component_center",
    "ValueTop": "comment",
    "ComponentOutlineTop": "component_outline",
}
_NAME_ROLES: Final[tuple[tuple[str, str], ...]] = (
    ("courtyard", "courtyard"),
    ("component center", "component_center"),
    ("component centre", "component_center"),
    ("center", "component_center"),
    ("centre", "component_center"),
    ("bauteilmitte", "component_center"),
    ("component outline", "component_outline"),
    ("outline", "component_outline"),
    ("umriss", "component_outline"),
    ("designator", "designator"),
    ("refdes", "designator"),
    ("bezeichner", "designator"),
    ("value", "comment"),
    ("comment", "comment"),
    ("wert", "comment"),
    ("3d", "body3d"),
    ("body", "body3d"),
    ("assembly", "assembly"),
    ("assy", "assembly"),
    ("bestück", "assembly"),
    ("fab", "assembly"),
)
CROSS_WIDTH: Final = 0.1
_EPS: Final = 1e-4


# --------------------------------------------------------------------------- rules


class SymbolRules(BaseModel):
    fonts: bool = Field(default=True, description="Hausschrift für Bezeichner, Kommentar, Parameter und Pins")
    pin_length: bool = Field(default=True, description="Pinlänge von IC-/Box-Symbolen = Hausstil")
    prefix: bool = Field(default=True, description="Bezeichner-Präfixe nach prefix_map ersetzen")
    prefix_map: dict[str, str] = Field(default_factory=lambda: {"IC": "U"}, description="Alt -> neu, z. B. IC -> U")
    colors: bool = Field(default=False, description="Rahmen, Füllung und Pinfarbe von Box-Symbolen = Hausstil")


class FootprintRules(BaseModel):
    layers: bool = Field(default=True, description="Primitive nach Rolle auf die Lagen der Lagenzuordnung")
    widths: bool = Field(default=True, description="Linienbreiten je Rolle (Bestückung, Courtyard, Mitte, Umriss)")
    silk_width: bool = Field(default=False, description="Auch den Bestückungsdruck auf die Hausstil-Breite setzen")
    texts: bool = Field(default=True, description=".Designator/.Comment in Hausstil-Schrift und -Höhe")
    add_texts: bool = Field(default=True, description="Fehlende .Designator/.Comment ergänzen")
    add_center: bool = Field(default=True, description="Fehlendes Bauteilmitte-Kreuz ergänzen")
    header: bool = Field(default=True, description="Lagen-Kopf (Lagenaufbau und Lagensatz) der Bibliothek")
    roles: dict[str, dict[str, Role]] = Field(
        default_factory=dict,
        description="Eigene Rollen je Bibliothek: {Bibliothekspfad: {'Mechanical 13': 'assembly', …}}",
    )


class ConformRules(BaseModel):
    symbols: SymbolRules = Field(default_factory=SymbolRules)
    footprints: FootprintRules = Field(default_factory=FootprintRules)


class Change(BaseModel):
    """One change a rule makes to a component (German message)."""

    rule: str
    message: str


class LayerRole(BaseModel):
    """Role of a source layer of a footprint library."""

    layer: str
    role: Role
    reason: Literal["kind", "name", "content", "manual", "default"]
    primitives: int = 0
    name: str | None = Field(default=None, description="Lagenname im Bibliothekskopf")


def parse_prefix_map(text: str) -> dict[str, str]:
    """``"IC=U, TR=Q"`` -> ``{"IC": "U", "TR": "Q"}`` (letters only; empty entries ignored)."""
    out: dict[str, str] = {}
    for item in re.split(r"[,;\n]+", text or ""):
        old, sep, new = item.partition("=")
        old, new = old.strip().rstrip("?").upper(), new.strip().rstrip("?").upper()
        if sep and re.fullmatch(r"[A-Z]{1,8}", old) and re.fullmatch(r"[A-Z]{1,8}", new) and old != new:
            out[old] = new
    return out


# --------------------------------------------------------------------------- footprints: roles


def _is_overlay(layer: str | None) -> bool:
    return layer in (L.TOP_OVERLAY, L.BOTTOM_OVERLAY)


def _is_mech(layer: str | None) -> bool:
    return bool(layer) and L.mechanical_number(layer) is not None  # type: ignore[arg-type]


def _crosses(prims: Sequence[R.Primitive]) -> dict[str, list[int]]:
    """Crosses through the origin per mechanical layer: ``{layer: [horizontal, vertical]}`` – one horizontal and
    one vertical track, symmetric, at most 3 mm long (the first such pair of each layer)."""
    by_layer: dict[str, list[tuple[int, R.Primitive]]] = {}
    for index, prim in enumerate(prims):
        if prim.kind == "track" and _is_mech(prim.layer):
            by_layer.setdefault(prim.layer or "", []).append((index, prim))
    out: dict[str, list[int]] = {}
    for layer, items in by_layer.items():
        horizontal = vertical = None
        for index, prim in items:
            x1, y1, x2, y2 = prim.coords
            length = math.hypot(x2 - x1, y2 - y1)
            if length > 3.0 or length < 0.05:
                continue
            if abs(y1) < _EPS and abs(y2) < _EPS and abs(x1 + x2) < 0.01:
                horizontal = horizontal if horizontal is not None else index
            elif abs(x1) < _EPS and abs(x2) < _EPS and abs(y1 + y2) < 0.01:
                vertical = vertical if vertical is not None else index
        if horizontal is not None and vertical is not None:
            out[layer] = [horizontal, vertical]
    return out


def center_crosses(
    prims: Sequence[R.Primitive],
    layer_roles: Mapping[str, LayerRole],
    *,
    courtyard_cross: bool | None = None,
) -> tuple[list[int], list[int]]:
    """Indexes of the component centre cross and of the courtyard cross (``FootprintStyle.center_cross``: a cross
    on the courtyard *in addition* to the centre).

    The centre is the cross on the component-centre layer, else one on any other layer except the courtyard. A
    cross on the courtyard is the courtyard cross – unless it is the only one and the house style draws none
    (``courtyard_cross=False``): then it is the centre drawn on the courtyard. ``None`` (style unknown, e.g. when
    learning from an example) keeps a lone courtyard cross as courtyard cross."""
    crosses = _crosses(prims)
    if not crosses:
        return [], []

    def role(layer: str) -> str:
        entry = layer_roles.get(layer)
        return entry.role if entry is not None else "keep"

    courtyard = [layer for layer in crosses if role(layer) == "courtyard"]
    center = next((layer for layer in crosses if role(layer) == "component_center"), None)
    if center is None:
        center = next((layer for layer in crosses if layer not in courtyard), None)
    if center is None and courtyard and courtyard_cross is False:
        center = courtyard[0]
    court = next((layer for layer in courtyard if layer != center), None)
    return (crosses[center] if center else []), (crosses[court] if court else [])


def _union(a: tuple[float, float, float, float] | None, b: tuple[float, float, float, float] | None
           ) -> tuple[float, float, float, float] | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _area(box: tuple[float, float, float, float] | None) -> float:
    return 0.0 if box is None else max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _encloses(outer: tuple[float, float, float, float] | None, inner: tuple[float, float, float, float] | None,
              tol: float = 0.05) -> bool:
    if outer is None or inner is None:
        return False
    return (outer[0] <= inner[0] + tol and outer[1] <= inner[1] + tol
            and outer[2] >= inner[2] - tol and outer[3] >= inner[3] - tol)


def pads_bounds(records: R.FootprintRecords) -> tuple[float, float, float, float] | None:
    box = None
    for pad in records.of_kind("pad"):
        try:
            box = _union(box, pad.pad_bounds())
        except R.PcbRecordError:
            continue
    return box


def _special_text_role(prim: R.Primitive) -> str | None:
    if prim.kind != "text" or _is_overlay(prim.layer):
        return None
    text = prim.text.strip().casefold()
    if text == ".designator":
        return "designator"
    if text == ".comment":
        return "comment"
    return None


def _content_votes(records: R.FootprintRecords) -> dict[str, str]:
    """Per footprint: role votes for its mechanical layers from their outlines."""
    prims = records.primitives
    cross = {index for pair in _crosses(prims).values() for index in pair}
    boxes: dict[str, tuple[float, float, float, float] | None] = {}
    widths: dict[str, list[float]] = {}
    for index, prim in enumerate(prims):
        if index in cross or prim.kind not in ("track", "arc", "region", "fill") or not _is_mech(prim.layer):
            continue
        layer = prim.layer or ""
        boxes[layer] = _union(boxes.get(layer), prim.bounds())
        if prim.kind in ("track", "arc"):
            widths.setdefault(layer, []).append(prim.width)
    if not boxes:
        return {}
    pads = pads_bounds(records)
    ordered = sorted(boxes, key=lambda layer: _area(boxes[layer]), reverse=True)
    votes: dict[str, str] = {}
    if len(ordered) >= 2:
        outer, inner = ordered[0], ordered[1]
        if _encloses(boxes[outer], boxes[inner]) and (pads is None or _encloses(boxes[outer], pads)):
            votes[outer] = "courtyard"
            votes[inner] = "assembly"
            for extra in ordered[2:]:
                votes.setdefault(extra, "keep")
            return votes
    for layer in ordered:
        thin = bool(widths.get(layer)) and sorted(widths[layer])[len(widths[layer]) // 2] <= 0.06
        if pads is not None and _encloses(boxes[layer], pads) and thin:
            votes[layer] = "courtyard"
        else:
            votes[layer] = "assembly"
    return votes


def _name_role(name: str | None, number: int) -> str | None:
    if not name or re.fullmatch(rf"Mechanical\s*{number}", name.strip(), re.IGNORECASE):
        return None
    text = name.casefold()
    if "bottom" in text or "unten" in text:
        return None
    for key, role in _NAME_ROLES:
        if key in text:
            return role
    return None


def infer_layer_roles(
    footprints: Iterable[R.FootprintRecords],
    header_layers: Mapping[int, object] | None = None,
    manual: Mapping[str, str] | None = None,
) -> dict[str, LayerRole]:
    """Role of every mechanical layer used by the footprints of one library.

    Order: hand-set role (``manual``), layer kind of the header, layer name, content (majority of the
    footprints: the outer outline that encloses the pads is the courtyard, the inner one the assembly
    drawing). Layers only holding centre crosses, special texts or bodies get ``keep`` – those primitives
    have their own role anyway (:func:`primitive_roles`)."""
    counts: Counter[str] = Counter()
    votes: dict[str, Counter[str]] = {}
    for records in footprints:
        for prim in records.primitives:
            if prim.kind in ("pad", "via"):
                continue
            layer = prim.layer
            if _is_mech(layer):
                counts[layer or ""] += 1
        for layer, role in _content_votes(records).items():
            votes.setdefault(layer, Counter())[role] += 1
    out: dict[str, LayerRole] = {}
    for layer, count in sorted(counts.items(), key=lambda kv: L.mechanical_number(kv[0]) or 0):
        number = L.mechanical_number(layer) or 0
        entry = header_layers.get(number) if header_layers else None
        name = getattr(entry, "name", None)
        kind = getattr(entry, "kind", None)
        if manual and layer in manual:
            out[layer] = LayerRole(layer=layer, role=manual[layer], reason="manual", primitives=count, name=name)  # type: ignore[arg-type]
            continue
        if kind in KIND_ROLES:
            out[layer] = LayerRole(layer=layer, role=KIND_ROLES[kind], reason="kind", primitives=count, name=name)  # type: ignore[arg-type]
            continue
        by_name = _name_role(name, number)
        if by_name:
            out[layer] = LayerRole(layer=layer, role=by_name, reason="name", primitives=count, name=name)  # type: ignore[arg-type]
            continue
        vote = votes.get(layer)
        if vote:
            role, hits = vote.most_common(1)[0]
            total = sum(vote.values())
            if role != "keep" and hits * 10 >= total * 6:
                out[layer] = LayerRole(layer=layer, role=role, reason="content", primitives=count, name=name)  # type: ignore[arg-type]
                continue
        out[layer] = LayerRole(layer=layer, role="keep", reason="default", primitives=count, name=name)
    return out


def primitive_roles(
    records: R.FootprintRecords,
    layer_roles: Mapping[str, LayerRole],
    *,
    courtyard_cross: bool | None = None,
) -> list[str | None]:
    """Role of every primitive (``None`` = pads, vias and everything that stays where it is). Crosses: see
    :func:`center_crosses`."""
    prims = records.primitives
    center, court = center_crosses(prims, layer_roles, courtyard_cross=courtyard_cross)
    out: list[str | None] = []
    for index, prim in enumerate(prims):
        if prim.kind in ("pad", "via"):
            out.append(None)
            continue
        if prim.kind == "body":
            out.append("body3d")
            continue
        if index in center:
            out.append("component_center")
            continue
        if index in court:
            out.append("courtyard")
            continue
        special = _special_text_role(prim)
        if special:
            out.append(special)
            continue
        layer = prim.layer
        if _is_overlay(layer):
            out.append("silkscreen")
            continue
        entry = layer_roles.get(layer or "")
        role = entry.role if entry is not None else "keep"
        out.append(None if role == "keep" else role)
    return out


# --------------------------------------------------------------------------- footprints: plan


def _round_down(value: float, step: float) -> float:
    return math.floor(value / step + 1e-9) * step


def text_height_for(ref: tuple[float, float, float, float] | None, style: FootprintStyle) -> float:
    """Text height of ``.Designator``/``.Comment`` like the generator (scaled down for tiny parts)."""
    if ref is None:
        return round(style.text_height, 4)
    short = min(ref[2] - ref[0], ref[3] - ref[1])
    return round(min(style.text_height, max(0.3, _round_down(0.6 * short, 0.05))), 4)


def center_cross_half(ref: tuple[float, float, float, float] | None) -> float:
    """Half length of the component centre cross like the generator (±0.5 mm, smaller on tiny parts)."""
    if ref is None:
        return 0.5
    size = max(ref[2] - ref[0], ref[3] - ref[1])
    return round(max(0.1, min(0.5, _round_down(0.3 * size, 0.005))), 4)


def _text_box(prim_text: str, height: float, font: str, font_name: str) -> tuple[float, float]:
    from .rustwriter import STROKE_CHAR_ADVANCE, truetype_text_box

    if font == "truetype":
        return truetype_text_box(prim_text, height, font_name)
    return len(prim_text) * STROKE_CHAR_ADVANCE * height, height


def _text_center(prim: R.Primitive) -> tuple[float, float]:
    """Visual centre of an (unrotated) text: stored lower-left corner + half its extent."""
    x, y = prim.position
    width, height = prim.text_box
    font = prim.font_kind
    estimate = _text_box(prim.text, prim.height, "truetype" if font == "truetype" else "stroke",
                         prim.font_name or "Arial")
    if not (width > 0 and height > 0 and 0.7 <= width / estimate[0] <= 1.3):
        width, height = estimate
    angle = math.radians(prim.rotation)
    dx, dy = width / 2, height / 2
    return x + dx * math.cos(angle) - dy * math.sin(angle), y + dx * math.sin(angle) + dy * math.cos(angle)


def _place_text(prim: R.Primitive, center: tuple[float, float]) -> None:
    width, height = prim.text_box
    angle = math.radians(prim.rotation)
    dx, dy = width / 2, height / 2
    prim.set_position(center[0] - (dx * math.cos(angle) - dy * math.sin(angle)),
                      center[1] - (dx * math.sin(angle) + dy * math.cos(angle)))


@dataclass
class FootprintPlan:
    """What :func:`plan_footprint` changes in one footprint (the records are a modified copy)."""

    name: str
    records: R.FootprintRecords
    new: list[R.Primitive] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    modified: bool = False


def _copy_records(records: R.FootprintRecords) -> R.FootprintRecords:
    return R.FootprintRecords(
        prefix=records.prefix,
        name=records.name,
        primitives=[R.Primitive(p.code, [bytearray(b) for b in p.blocks]) for p in records.primitives],
        trailer=records.trailer,
    )


def _target_layer(role: str, layer_map: LayerMap) -> str | None:
    if role not in MAPPED_ROLES:
        return None
    try:
        return L.normalize_layer_name(getattr(layer_map, role))
    except (L.LayerError, AttributeError):
        return None


def _role_width(role: str, style: FootprintStyle, rules: FootprintRules) -> float | None:
    if role in ("assembly", "component_outline"):
        return style.assembly_width
    if role == "courtyard":
        return style.courtyard_width
    if role == "component_center":
        return CROSS_WIDTH
    if role == "silkscreen" and rules.silk_width:
        return style.silk_width
    return None


def plan_footprint(
    records: R.FootprintRecords,
    layer_roles: Mapping[str, LayerRole],
    rules: FootprintRules,
    style: FootprintStyle,
    layer_map: LayerMap,
) -> FootprintPlan:
    """Plan the footprint rules for one footprint (pure; ``records`` stay unchanged).

    The roles are determined once from the source layers, before anything moves."""
    work = _copy_records(records)
    plan = FootprintPlan(name=records.name, records=work)
    roles = primitive_roles(work, layer_roles, courtyard_cross=style.center_cross)
    center, court = center_crosses(work.primitives, layer_roles, courtyard_cross=style.center_cross)
    crosses = {*center, *court}
    moved: Counter[tuple[str, str, str]] = Counter()
    widened: Counter[tuple[str, float]] = Counter()
    for index, (prim, role) in enumerate(zip(work.primitives, roles, strict=True)):
        if role is None:
            continue
        if rules.layers and role != "silkscreen":
            target = _target_layer(role, layer_map)
            current = prim.layer
            if target and current and current != target:
                try:
                    prim.set_layer(target)
                    moved[(role, current, target)] += 1
                except R.PcbRecordError:
                    pass
        if rules.widths and prim.kind in ("track", "arc"):
            wanted = CROSS_WIDTH if index in crosses else _role_width(role, style, rules)
            if wanted is None or abs(prim.width - wanted) <= 1e-4:
                continue
            if prim.kind == "arc" and prim.width >= 1.5 * prim.arc[2]:
                continue  # a filled dot (pin 1 marker) keeps its width
            prim.set_width(wanted)
            widened[(role, round(wanted, 4))] += 1
    for (role, current, target), count in sorted(moved.items()):
        plan.changes.append(Change(rule="layers", message=f"{ROLE_LABELS[role]}: {current} → {target} ({count})"))
    for (role, wanted), count in sorted(widened.items()):
        plan.changes.append(Change(rule="widths", message=f"{ROLE_LABELS[role]}: Linienbreite {_mm(wanted)} ({count})"))

    courtyard = assembly = None
    for index, (prim, role) in enumerate(zip(work.primitives, roles, strict=True)):
        if role == "courtyard" and index not in crosses:
            courtyard = _union(courtyard, prim.bounds())
        elif role in ("assembly", "component_outline"):
            assembly = _union(assembly, prim.bounds())
    height = text_height_for(courtyard or pads_bounds(work), style)
    font = style.text_font
    font_name = (style.text_font_name or "Arial").strip() or "Arial"
    stroke = round(max(0.05, round(0.15 * height / 0.01) * 0.01), 4)
    texts = {role: [p for p, r in zip(work.primitives, roles, strict=True) if r == role]
             for role in ("designator", "comment")}
    if rules.texts:
        wanted_state = (font, font_name if font == "truetype" else None, round(height, 4))
        for prims in texts.values():
            for prim in prims:
                kind = "truetype" if prim.font_kind == "truetype" else "stroke"
                state = (kind, prim.font_name if kind == "truetype" else None, round(prim.height, 4))
                if state == wanted_state or not prim._text_extended():
                    continue
                center = _text_center(prim)
                prim.set_font(font, font_name if font == "truetype" else (prim.font_name or "Arial"))
                prim.set_height(height)
                prim.set_stroke_width(stroke)
                prim.set_text_box(*_text_box(prim.text, height, font, font_name))
                _place_text(prim, center)
                target = f"{font_name} {_mm(height)}" if font == "truetype" else f"Strichschrift {_mm(height)}"
                plan.changes.append(Change(rule="texts", message=f"{prim.text}: {target} (vorher {_font_label(state)})"))
    if rules.add_texts:
        template = next((p for p in work.of_kind("text") if p._text_extended()), None)
        for role, content in (("designator", ".Designator"), ("comment", ".Comment")):
            target = _target_layer(role, layer_map)
            if texts.get(role) or not target:
                continue
            box = _text_box(content, height, font, font_name)
            plan.new.append(R.new_text(target, content, x=-box[0] / 2, y=-box[1] / 2, height=height,
                                       stroke_width=stroke, font=font, font_name=font_name, box=box,
                                       template=template))
            plan.changes.append(Change(rule="add_texts", message=f"{content} auf {target} ergänzt ({_mm(height)})"))
    if rules.add_center and "component_center" not in roles:
        target = _target_layer("component_center", layer_map)
        if target:
            half = center_cross_half(assembly or courtyard or pads_bounds(work))
            template = next(iter(work.of_kind("track")), None)
            plan.new.append(R.new_track(target, -half, 0.0, half, 0.0, CROSS_WIDTH, template=template))
            plan.new.append(R.new_track(target, 0.0, -half, 0.0, half, CROSS_WIDTH, template=template))
            plan.changes.append(Change(rule="add_center", message=f"Kreuz ±{_mm(half)} auf {target} ergänzt"))
    plan.modified = bool(plan.changes)
    return plan


def _font_label(state: tuple[str, str | None, float]) -> str:
    kind, name, height = state
    return f"{name or 'Arial'} {_mm(height)}" if kind == "truetype" else f"Strichschrift {_mm(height)}"


def _mm(value: float) -> str:
    """``0.05`` -> ``0,05 mm`` (German decimal comma in the change messages)."""
    return f"{value:g}".replace(".", ",") + " mm"


# --------------------------------------------------------------------------- symbols


def _rects(records: Sequence[S.SchRecord]) -> list[tuple[int, int, int, int, int]]:
    """Rectangles (RECORD 14) as (x1, y1, x2, y2, owner part) in schematic units."""
    out: list[tuple[int, int, int, int, int]] = []
    for record in records:
        if record.binary or record.get("RECORD") != "14":
            continue

        def num(key: str, record: S.SchRecord = record) -> int:
            try:
                return int(record.get(key) or 0)
            except ValueError:
                return 0

        x1, y1, x2, y2 = num("Location.X"), num("Location.Y"), num("Corner.X"), num("Corner.Y")
        out.append((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2), num("OwnerPartId")))
    return out


def _pin_on_edge(pin: S.PinView, rects: Sequence[tuple[int, int, int, int, int]]) -> bool:
    x, y = pin.location
    for x1, y1, x2, y2, part in rects:
        if part not in (pin.owner_part, 0, -1) and pin.owner_part not in (0, -1):
            continue
        if pin.orientation == "left" and x == x1 and y1 <= y <= y2:
            return True
        if pin.orientation == "right" and x == x2 and y1 <= y <= y2:
            return True
        if pin.orientation == "down" and y == y1 and x1 <= x <= x2:
            return True
        if pin.orientation == "up" and y == y2 and x1 <= x <= x2:
            return True
    return False


def is_box_symbol(records: Sequence[S.SchRecord]) -> bool:
    """IC/box symbol: a rectangle body with (most of) the pins on its edges."""
    rects = _rects(records)
    if not rects:
        return False
    pins = [S.PinView(r) for r in records if r.is_pin]
    pins = [p for p in pins if p.display_mode == 0]
    if not pins:
        return False
    on_edge = sum(1 for p in pins if _pin_on_edge(p, rects))
    return on_edge * 10 >= len(pins) * 8


@dataclass
class SymbolPlan:
    name: str
    records: list[S.SchRecord]
    pin_text: dict[int, S.PinText]
    changes: list[Change] = field(default_factory=list)
    pin_text_changed: bool = False
    pin_lengths: dict[int, int] = field(default_factory=dict)  # pin index -> new length (units)
    prefix: str | None = None
    modified: bool = False


def _hex_color(value: str) -> int:
    text = value.strip().lstrip("#")
    try:
        return int(text[0:2], 16) | (int(text[2:4], 16) << 8) | (int(text[4:6], 16) << 16)
    except (ValueError, IndexError):
        return 0


def plan_symbol(
    name: str,
    records: Sequence[S.SchRecord],
    pin_text: Mapping[int, S.PinText],
    rules: SymbolRules,
    style: SymbolStyle,
    font_ids: schstyle.FontIds | None,
) -> SymbolPlan:
    """Plan the symbol rules for one symbol (pure; works on copies). ``font_ids`` = ids of the planned font
    table (``None``: fonts rule off)."""
    work = [S.SchRecord(binary=r.binary, payload=bytearray(r.payload), flags=r.flags) for r in records]
    plan = SymbolPlan(name=name, records=work, pin_text=dict(pin_text))
    if rules.fonts and font_ids is not None:
        pin_color = _hex_color(style.pin_color) if rules.colors else _pin_color_of(work)
        changed, new_text = schstyle.apply_fonts(work, dict(pin_text), font_ids, pin_color=pin_color)
        if changed:
            plan.pin_text_changed = new_text != {i: t for i, t in pin_text.items() if t != S.PinText()}
            plan.pin_text = new_text
            parts = [f"Texte in {schstyle.house_font(style).label()}"]
            if font_ids.pin is not None:
                parts.append("Pinnamen/-nummern in Hausschrift")
            elif any(t != S.PinText() for t in pin_text.values()):
                parts.append("Pins in Systemschrift")
            plan.changes.append(Change(rule="fonts", message=", ".join(parts)))
    box = is_box_symbol(work)
    if rules.pin_length and box:
        wanted = max(1, round(int(style.ic_pin_length) / 10))
        lengths: Counter[int] = Counter()
        for index, record in enumerate(r for r in work if r.is_pin):
            pin = S.PinView(record)
            if pin.length != wanted:
                lengths[pin.length] += 1
                pin.set_length(wanted)
                plan.pin_lengths[index] = wanted
        if lengths:
            old = ", ".join(f"{length * 10} mil" for length in sorted(lengths))
            plan.changes.append(Change(rule="pin_length",
                                       message=f"{sum(lengths.values())} Pins {old} → {wanted * 10} mil"))
    if rules.prefix and rules.prefix_map:
        designator = next((r for r in work if not r.binary and r.get("RECORD") == "34"), None)
        text = designator.get("Text") if designator is not None else None
        if designator is not None and text:
            stem = text.rstrip("?")
            new = rules.prefix_map.get(stem.upper())
            if new and new != stem:
                designator.set("Text", new + "?")
                plan.prefix = new
                plan.changes.append(Change(rule="prefix", message=f"Bezeichner {text} → {new}?"))
    if rules.colors and box:
        line, fill, pin_color = _hex_color(style.ic_line_color), _hex_color(style.ic_fill_color), _hex_color(style.pin_color)
        recolored = 0
        for record in work:
            if not record.binary and record.get("RECORD") == "14":
                a = record.set("Color", str(line))
                b = record.set("AreaColor", str(fill))
                recolored += int(a or b)
            elif record.is_pin:
                pin = S.PinView(record)
                if pin.color != pin_color:
                    pin.set_color(pin_color)
                    recolored += 1
        if recolored:
            plan.changes.append(Change(rule="colors", message=f"Farben von {recolored} Elementen an den Hausstil angepasst"))
    plan.modified = bool(plan.changes)
    return plan


def _pin_color_of(records: Sequence[S.SchRecord]) -> int:
    """Colour of the custom pin texts: the pins' own colour (black in Altium's default)."""
    for record in records:
        if record.is_pin:
            return S.PinView(record).color
    return 0
