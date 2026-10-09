"""Spec files for the DelphiScript library builder (``write_schlib`` / ``write_pcblib``).

Format (one record per line, ``|``-separated, text fields escaped with
:func:`~partforge.altium.bridge.protocol.escape_field`, numbers via
:func:`~partforge.altium.bridge.protocol.fmt_num`)::

    PFSPEC|1|SCHLIB                     (symbol coordinates in mil)
    SYMBOL|name|description|part_count|prefix|comment
    TEXTPOS|designator|x|y|justification                   (position of the designator text)
    TEXTPOS|comment|x|y|justification                      (position of the Comment text)
    RECT|part|width|solid|x1|y1|x2|y2|color|fill           (graphics first, in the
    ROUNDRECT|part|width|solid|x1|y1|x2|y2|rx|ry|color|fill  order of spec.graphics)
    LINE|part|width|color|x1|y1|x2|y2
    POLYLINE|part|width|color|n|x1|y1|…
    POLYGON|part|width|solid|color|fill|n|x1|y1|…
    ARC|part|width|color|cx|cy|r|start|end
    ELLIPSE|part|width|solid|color|fill|cx|cy|rx|ry
    LABEL|part|color|x|y|orientation|justification|text
    PIN|designator|name|electrical|orientation|x|y|part|length|show_name|show_designator|hidden|description|inner_edge|outer_edge
    PARAM|name|value|hidden
    FPLINK|name|library_path|description|current
    END

    PFSPEC|1|PCBLIB                     (footprint coordinates in mm)
    FOOTPRINT|name|description|height
    PAD|designator|x|y|rotation|layer|shape|xsize|ysize|corner_pct|hole|hole_type|slot_length|hole_rotation|plated
    TRACK|layer|width|x1|y1|x2|y2
    ARC|layer|width|cx|cy|r|start|end
    REGION|layer|n|x1|y1|…
    TEXT|layer|x|y|height|stroke|rotation|text
    BODY|layer|standoff|overall|color|opacity|n|x1|y1|…
    END

The DelphiScript adds the objects in record order and Altium paints symbol records in
that order: the graphics therefore come **before** the pins, otherwise a filled body
hides the pin names (VERIFIED in Altium 26.10, altium-verify-2 §3.3; altium-mcp's
``CreateSchematicSymbol`` adds the body first as well).

Enumerations are sent as Altium integer values (``TPinElectrical``, ``TRotationBy90``,
``TTextJustification``, ``TShape``, ``THoleType``, ``TIeeeSymbol`` for the pin edge
decorations); layers as ``L<TLayer>`` or ``M<mechanical number>``
(:func:`partforge.altium.layers.bridge_layer_token`). The designator and Comment positions
are always sent (``SymbolSpec`` defaults (-50, 50) / (-50, -150) mil, like the Rust writer),
so both backends place them identically.
Colours are COLORREF integers (``0x00BBGGRR``). Free text with ``|`` or control
characters is rejected like for the Rust writer
(:func:`~partforge.altium.rustwriter.free_text_issues`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Final

from ...geometry.model import (
    FootprintSpec,
    SymArc,
    SymbolSpec,
    SymEllipse,
    SymLine,
    SymPolygon,
    SymRect,
    SymText,
)
from ...workspace import FootprintStyle, LayerMap, SymbolStyle
from .. import layers as L
from ..rustwriter import (
    DEFAULT_BODY_COLOR,
    DEFAULT_COMMENT_POS,
    DEFAULT_DESIGNATOR_POS,
    LINE_WIDTHS,
    free_text_issues,
    hex_to_bgr,
    latin1_text,
    stroke_text_anchor,
    symbol_palette,
    synthesize_body,
    validate_component_name,
)
from .protocol import escape_field, fmt_num

__all__ = [
    "BridgeSpecError",
    "RenderedSpec",
    "ELECTRICAL_CODES",
    "ORIENTATION_CODES",
    "JUSTIFY_CODES",
    "PAD_SHAPE_CODES",
    "IEEE_SYMBOL_CODES",
    "bridge_limitations",
    "render_schlib_spec",
    "render_pcblib_spec",
]

#: ``TPinElectrical`` (eElectricInput = 0 … eElectricPower = 7).
ELECTRICAL_CODES: Final[dict[str, int]] = {
    "input": 0,
    "io": 1,
    "output": 2,
    "open_collector": 3,
    "passive": 4,
    "hiz": 5,
    "open_emitter": 6,
    "power": 7,
}
#: ``TRotationBy90``: direction the pin points (eRotate0 = right … eRotate270 = down).
ORIENTATION_CODES: Final[dict[str, int]] = {"right": 0, "up": 1, "left": 2, "down": 3}
#: ``TTextJustification`` (eJustify_BottomLeft = 0 … eJustify_TopRight = 8).
JUSTIFY_CODES: Final[dict[str, int]] = {
    "bottom_left": 0,
    "bottom_center": 1,
    "bottom_right": 2,
    "middle_left": 3,
    "middle_center": 4,
    "middle_right": 5,
    "top_left": 6,
    "top_center": 7,
    "top_right": 8,
}
#: ``TShape`` values (eRounded = 1, eRectangular = 2, eOctagonal = 3, eRoundedRectangular = 9).
PAD_SHAPE_CODES: Final[dict[str, int]] = {"circle": 1, "oval": 1, "rect": 2, "octagon": 3, "roundrect": 9}
#: ``TIeeeSymbol`` ordinals of the pin edge decorations PartForge supports (eNoSymbol = 0,
#: eDot = 1, eRightLeftSignalFlow = 2, eClock = 3, eActiveLowInput = 4, eAnalogSignalIn = 5,
#: eNotLogicConnection = 6 – the seven values verified in Altium, altium-verify-rust §3.1).
IEEE_SYMBOL_CODES: Final[dict[str, int]] = {
    "none": 0,
    "dot": 1,
    "right_left_signal_flow": 2,
    "clock": 3,
    "active_low_input": 4,
    "analog_signal_in": 5,
    "not_logic_connection": 6,
}
HOLE_ROUND: Final = 0
HOLE_SLOT: Final = 2


class BridgeSpecError(ValueError):
    """Data that cannot be sent to the bridge (German message, nothing was sent)."""

    def __init__(self, issues: Sequence[str]):
        self.issues = list(issues)
        super().__init__(
            "Ungültige Daten für die Altium-Brücke – es wurde nichts gesendet:\n"
            + "\n".join(f"• {issue}" for issue in self.issues[:25])
        )


@dataclass
class RenderedSpec:
    text: str
    names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _b(value: bool) -> str:
    return "1" if value else "0"


def _color(value: str | None, default: int, issues: list[str], where: str) -> int:
    if not value:
        return default
    try:
        return hex_to_bgr(value)
    except ValueError as exc:
        issues.append(f"{where}: {exc}")
        return default


def _check_names(names: Sequence[str], what: str, issues: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        issues.extend(validate_component_name(name, what))
        if name in seen:
            issues.append(f"{what} {name!r} ist mehrfach enthalten.")
        seen.add(name)


def _mask_overrides(spec: FootprintSpec) -> bool:
    return any(
        (not pad.paste and pad.side != "through") or pad.paste_expansion is not None or pad.mask_expansion is not None
        for pad in spec.pads
    )


def bridge_limitations(spec: SymbolSpec | FootprintSpec) -> list[str]:
    """What the Altium bridge cannot reproduce of ``spec`` (German, empty = nothing)."""
    limits: list[str] = []
    if isinstance(spec, FootprintSpec):
        if spec.step is not None:
            limits.append("eingebettetes STEP-Modell (nur extrudierte 3D-Körper möglich)")
        if _mask_overrides(spec):
            limits.append("Pasten-/Lötstopp-Einstellungen der Pads (es gelten die Regelwerte aus Altium)")
    else:
        if any(isinstance(g, SymText) and g.size != 10 for g in spec.graphics):
            limits.append("Schriftgrößen von Texten (Standardschrift)")
    return limits


def _symbol_text_issues(spec: SymbolSpec) -> list[str]:
    where = f"Symbol {spec.name}"
    issues = [
        *free_text_issues(spec.description, where, "Beschreibung"),
        *free_text_issues(spec.comment, where, "Kommentar"),
    ]
    for pin in spec.pins:
        pw = f"{where}, Pin {pin.designator or '?'}"
        issues += free_text_issues(pin.designator, pw, "Pin-Nummer")
        issues += free_text_issues(pin.name, pw, "Pin-Name")
        issues += free_text_issues(pin.description, pw, "Pin-Beschreibung")
    for idx, g in enumerate(spec.graphics):
        if isinstance(g, SymText):
            issues += free_text_issues(g.text, f"{where}, Grafik {idx + 1} (text)", "Text")
    for name, value in spec.parameters.items():
        issues += free_text_issues(name, where, "Parametername")
        issues += free_text_issues(value, f"{where}, Parameter {name!r}", "Wert")
    for link in spec.footprints:
        lw = f"{where}: Footprint-Verknüpfung"
        issues += free_text_issues(link.library_path, lw, "Bibliothekspfad")
        issues += free_text_issues(link.description, lw, "Beschreibung")
    return issues


def _footprint_text_issues(spec: FootprintSpec) -> list[str]:
    where = f"Footprint {spec.name}"
    issues = free_text_issues(spec.description, where, "Beschreibung")
    for pad in spec.pads:
        issues += free_text_issues(pad.designator, f"{where}, Pad {pad.designator or '?'}", "Pad-Bezeichner")
    for i, tx in enumerate(spec.texts):
        issues += free_text_issues(tx.text, f"{where}, Text {i + 1}", "Text")
    return issues


def render_schlib_spec(
    symbols: Sequence[SymbolSpec],
    *,
    style: SymbolStyle | None = None,
) -> RenderedSpec:
    """Spec text for ``write_schlib`` (raises :class:`BridgeSpecError` on invalid data).

    Per symbol the graphics are written before the pins (z-order, see module docs).
    """
    issues: list[str] = []
    warnings: list[str] = []
    if not symbols:
        issues.append("Keine Symbole angegeben.")
    _check_names([s.name for s in symbols], "Symbol", issues)
    style = style or SymbolStyle()

    def e(text: str | None) -> str:
        return escape_field(text or "")

    lines = ["PFSPEC|1|SCHLIB"]
    for spec in symbols:
        issues.extend(_symbol_text_issues(spec))
        line_default, fill_default = symbol_palette(spec, style)
        prefix = (spec.designator_prefix or "U").strip() or "U"
        comment = spec.comment if (spec.comment or "").strip() not in ("", "*") else ""
        if not 1 <= spec.part_count <= 64:
            issues.append(f"Symbol {spec.name}: Teileanzahl {spec.part_count} ungültig.")
        lines.append(f"SYMBOL|{e(spec.name)}|{e(spec.description)}|{spec.part_count}|{e(prefix)}|{e(comment)}")
        for target, pos, default in (
            ("designator", spec.designator_pos, DEFAULT_DESIGNATOR_POS),
            ("comment", spec.comment_pos, DEFAULT_COMMENT_POS),
        ):
            x, y = (pos.x, pos.y) if pos is not None else default
            justify = JUSTIFY_CODES[pos.justify] if pos is not None else JUSTIFY_CODES["bottom_left"]
            lines.append(f"TEXTPOS|{target}|{fmt_num(x)}|{fmt_num(y)}|{justify}")
        for idx, g in enumerate(spec.graphics):
            where = f"Symbol {spec.name}, Grafik {idx + 1}"
            if not 0 <= g.part <= spec.part_count:
                issues.append(f"{where}: Teil {g.part} existiert nicht.")
            width = str(LINE_WIDTHS.get(g.line_width, 1))
            color = str(_color(g.color, line_default, issues, where))
            fill = str(_color(g.fill_color, fill_default, issues, where))
            part = str(int(g.part))
            if isinstance(g, SymRect):
                coords = [fmt_num(v) for v in (g.x1, g.y1, g.x2, g.y2)]
                if g.corner_radius and g.corner_radius > 0:
                    r = fmt_num(g.corner_radius)
                    lines.append("|".join(["ROUNDRECT", part, width, _b(g.filled), *coords, r, r, color, fill]))
                else:
                    lines.append("|".join(["RECT", part, width, _b(g.filled), *coords, color, fill]))
            elif isinstance(g, SymLine):
                if len(g.points) < 2:
                    issues.append(f"{where}: eine Linie braucht mindestens 2 Punkte.")
                elif len(g.points) == 2:
                    a, b = g.points
                    lines.append("|".join(["LINE", part, width, color, *(fmt_num(v) for v in (a.x, a.y, b.x, b.y))]))
                else:
                    pts = [fmt_num(v) for p in g.points for v in (p.x, p.y)]
                    lines.append("|".join(["POLYLINE", part, width, color, str(len(g.points)), *pts]))
            elif isinstance(g, SymPolygon):
                if len(g.points) < 3:
                    issues.append(f"{where}: ein Polygon braucht mindestens 3 Punkte.")
                pts = [fmt_num(v) for p in g.points for v in (p.x, p.y)]
                lines.append("|".join(["POLYGON", part, width, _b(g.filled), color, fill, str(len(g.points)), *pts]))
            elif isinstance(g, SymArc):
                vals = [fmt_num(v) for v in (g.cx, g.cy, g.r, g.start, g.end)]
                lines.append("|".join(["ARC", part, width, color, *vals]))
            elif isinstance(g, SymEllipse):
                vals = [fmt_num(v) for v in (g.cx, g.cy, g.rx, g.ry)]
                lines.append("|".join(["ELLIPSE", part, width, _b(g.filled), color, fill, *vals]))
            elif isinstance(g, SymText):
                if g.size != 10:
                    warnings.append(f"Symbol {spec.name}: Schriftgröße {g.size} pt wird nicht übernommen (Standardschrift).")
                lines.append(
                    "|".join(
                        [
                            "LABEL",
                            part,
                            color,
                            fmt_num(g.x),
                            fmt_num(g.y),
                            str((int(g.rotation) // 90) % 4),
                            str(JUSTIFY_CODES[g.justify]),
                            e(g.text),
                        ]
                    )
                )
        for pin in spec.pins:
            if not pin.designator.strip():
                issues.append(f"Symbol {spec.name}: Pin ohne Pin-Nummer.")
            if not 0 <= pin.part <= spec.part_count:
                issues.append(f"Symbol {spec.name}, Pin {pin.designator}: Teil {pin.part} existiert nicht.")
            lines.append(
                "PIN|"
                + "|".join(
                    [
                        e(pin.designator),
                        e(pin.name),
                        str(ELECTRICAL_CODES[pin.electrical]),
                        str(ORIENTATION_CODES[pin.orientation]),
                        str(int(pin.x)),
                        str(int(pin.y)),
                        str(int(pin.part)),
                        str(max(0, int(pin.length))),
                        _b(pin.show_name),
                        _b(pin.show_designator),
                        _b(pin.hidden),
                        e(pin.description),
                        str(IEEE_SYMBOL_CODES[pin.inner_edge or "none"]),
                        str(IEEE_SYMBOL_CODES[pin.outer_edge or "none"]),
                    ]
                )
            )
        for name, value in spec.parameters.items():
            if name == "Comment":
                continue
            lines.append(f"PARAM|{e(name)}|{e(value)}|1")
        for i, link in enumerate(spec.footprints):
            issues.extend(validate_component_name(link.name, f"Symbol {spec.name}: Footprint-Verknüpfung"))
            lines.append(f"FPLINK|{e(link.name)}|{e(link.library_path)}|{e(link.description)}|{_b(i == 0)}")
    lines.append("END")
    if issues:
        raise BridgeSpecError(issues)
    return RenderedSpec(text="\r\n".join(lines) + "\r\n", names=[s.name for s in symbols], warnings=warnings)


def render_pcblib_spec(
    footprints: Sequence[FootprintSpec],
    *,
    layer_map: LayerMap | None = None,
    style: FootprintStyle | None = None,
) -> RenderedSpec:
    """Spec text for ``write_pcblib`` (raises :class:`BridgeSpecError` on invalid data).

    Not supported by the bridge (reported as warnings, see :func:`bridge_limitations`):
    STEP embedding, paste/solder mask overrides. Stroke text is placed with a
    compensated bottom-left anchor (:func:`~partforge.altium.rustwriter.stroke_text_anchor`).
    """
    issues: list[str] = []
    warnings: list[str] = []
    if not footprints:
        issues.append("Keine Footprints angegeben.")
    _check_names([f.name for f in footprints], "Footprint", issues)
    style = style or FootprintStyle()
    layer_map = layer_map or LayerMap()

    def e(text: str | None) -> str:
        return escape_field(text or "")

    def token(logical: str, where: str) -> str:
        try:
            return L.bridge_layer_token(L.logical_to_altium(logical, layer_map))
        except L.LayerError as exc:
            issues.append(f"{where}: {exc}")
            return "L33"

    lines = ["PFSPEC|1|PCBLIB"]
    for spec in footprints:
        issues.extend(_footprint_text_issues(spec))
        bodies = list(spec.bodies)
        if spec.step is not None:
            warnings.append(
                f"Footprint {spec.name}: STEP-Modell wird vom Altium-Backend nicht eingebettet "
                "(nur extrudierte 3D-Körper)."
            )
            if not bodies:
                synth = synthesize_body(spec)
                if synth is not None:
                    bodies.append(synth)
        height = spec.height or max((b.z_top for b in bodies), default=0.0)
        lines.append(f"FOOTPRINT|{e(spec.name)}|{e(spec.description)}|{fmt_num(height)}")
        for pad in spec.pads:
            where = f"Footprint {spec.name}, Pad {pad.designator}"
            if not pad.designator.strip():
                issues.append(f"Footprint {spec.name}: Pad ohne Bezeichner.")
            if pad.width <= 0 or pad.height <= 0:
                issues.append(f"{where}: Breite und Höhe müssen größer als 0 sein.")
            hole = pad.hole or 0.0
            if pad.side == "through" and hole <= 0:
                issues.append(f"{where}: Durchsteck-Pad ohne Bohrung.")
            if pad.side != "through" and hole > 0:
                issues.append(f"{where}: Bohrungen sind nur bei Durchsteck-Pads möglich.")
            slot = pad.hole_length is not None and hole > 0 and pad.hole_length > hole + 1e-9
            corner = 0
            if pad.shape == "roundrect":
                corner = pad.corner_radius_pct if pad.corner_radius_pct is not None else style.pad_corner_radius_pct
            lines.append(
                "|".join(
                    [
                        "PAD",
                        e(pad.designator),
                        fmt_num(pad.x),
                        fmt_num(pad.y),
                        fmt_num(pad.rotation),
                        L.bridge_layer_token(L.pad_layer(pad.side)),
                        str(PAD_SHAPE_CODES[pad.shape]),
                        fmt_num(pad.width),
                        fmt_num(pad.height),
                        str(int(corner)),
                        fmt_num(hole),
                        str(HOLE_SLOT if slot else HOLE_ROUND),
                        fmt_num(pad.hole_length if slot and pad.hole_length else 0.0),
                        fmt_num(90.0 if slot and pad.height > pad.width else 0.0),
                        _b(pad.plated),
                    ]
                )
            )
        if _mask_overrides(spec):
            warnings.append(
                f"Footprint {spec.name}: Pasten-/Lötstopp-Erweiterungen werden vom Altium-Backend nicht gesetzt "
                "(Regelwerte aus Altium gelten)."
            )
        for i, t in enumerate(spec.tracks):
            where = f"Footprint {spec.name}, Linie {i + 1}"
            lines.append(
                "|".join(["TRACK", token(t.layer, where), fmt_num(t.width), *(fmt_num(v) for v in (t.x1, t.y1, t.x2, t.y2))])
            )
        for i, a in enumerate(spec.arcs):
            where = f"Footprint {spec.name}, Bogen {i + 1}"
            lines.append(
                "|".join(
                    ["ARC", token(a.layer, where), fmt_num(a.width), *(fmt_num(v) for v in (a.cx, a.cy, a.r, a.start, a.end))]
                )
            )
        for i, rg in enumerate(spec.regions):
            where = f"Footprint {spec.name}, Fläche {i + 1}"
            if len(rg.points) < 3:
                issues.append(f"{where}: eine Fläche braucht mindestens 3 Punkte.")
            pts = [fmt_num(v) for p in rg.points for v in (p.x, p.y)]
            lines.append("|".join(["REGION", token(rg.layer, where), str(len(rg.points)), *pts]))
        for i, tx in enumerate(spec.texts):
            where = f"Footprint {spec.name}, Text {i + 1}"
            # Altium anchors stroke text bottom-left: place the anchor so the text appears justified
            content = latin1_text(tx.text)
            ax, ay = stroke_text_anchor(content, tx.x, tx.y, tx.height, tx.rotation, tx.justify)
            lines.append(
                "|".join(
                    [
                        "TEXT",
                        token(tx.layer, where),
                        fmt_num(ax),
                        fmt_num(ay),
                        fmt_num(tx.height),
                        fmt_num(tx.stroke),
                        fmt_num(tx.rotation),
                        e(content),
                    ]
                )
            )
        body_token = token("body3d", f"Footprint {spec.name}, 3D-Körper")
        for i, body in enumerate(bodies):
            where = f"Footprint {spec.name}, 3D-Körper {i + 1}"
            if len(body.outline) < 3:
                issues.append(f"{where}: Umriss braucht mindestens 3 Punkte.")
            if body.z_top <= body.z_bottom:
                issues.append(f"{where}: Oberkante muss über der Unterkante liegen.")
            pts = [fmt_num(v) for p in body.outline for v in (p.x, p.y)]
            lines.append(
                "|".join(
                    [
                        "BODY",
                        body_token,
                        fmt_num(body.z_bottom),
                        fmt_num(body.z_top),
                        str(_color(body.color, DEFAULT_BODY_COLOR, issues, where)),
                        fmt_num(min(1.0, max(0.0, body.opacity))),
                        str(len(body.outline)),
                        *pts,
                    ]
                )
            )
    lines.append("END")
    if issues:
        raise BridgeSpecError(issues)
    return RenderedSpec(text="\r\n".join(lines) + "\r\n", names=[f.name for f in footprints], warnings=warnings)
