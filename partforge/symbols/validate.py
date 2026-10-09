"""Consistency checks for :class:`~partforge.geometry.model.SymbolSpec` (any source).

The rules mirror what the library writers need (``rust-writer.md`` §6, ``altium-verify-rust.md``):
integer pin coordinates on the 10 mil raster, pin tips on the symbol grid, string
designators unique within every part, valid part numbers, ASCII names and #RRGGBB colours.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from ..geometry.model import SymArc, SymbolSpec, SymEllipse, SymGraphic, SymLine, SymPolygon, SymRect, SymText
from .style import RASTER
from .util import MAX_PART_COUNT, NAME_RE, PREFIX_RE

__all__ = ["COORD_LIMIT", "check_spec", "spec_warnings"]

COORD_LIMIT = 50_000  # mil; far beyond any sensible symbol, well inside the writer limit
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _non_latin1(text: str) -> list[str]:
    """Distinct characters of ``text`` outside Latin-1 (U+0000…U+00FF), in order of appearance."""
    return list(dict.fromkeys(ch for ch in text if ord(ch) > 0xFF))


def _graphic_values(g: SymGraphic) -> list[float]:
    """Every coordinate-like number of a graphic primitive."""
    if isinstance(g, SymRect):
        return [g.x1, g.y1, g.x2, g.y2, g.corner_radius]
    if isinstance(g, (SymLine, SymPolygon)):
        return [c for pt in g.points for c in (pt.x, pt.y)]
    if isinstance(g, SymArc):
        return [g.cx, g.cy, g.r, g.start, g.end]
    if isinstance(g, SymEllipse):
        return [g.cx, g.cy, g.rx, g.ry]
    if isinstance(g, SymText):
        return [g.x, g.y]
    return []  # pragma: no cover - SymGraphic is a closed union


def check_spec(spec: SymbolSpec, *, grid: int = 100) -> list[str]:
    """Problems of ``spec`` as German messages (empty list = valid)."""
    problems: list[str] = []
    name = spec.name or ""
    if not NAME_RE.match(name) or name != name.strip():
        problems.append(f"Symbolname {name!r} ist ungültig (ASCII A–Z, 0–9, Leerzeichen, _ . - + ( ), max. 64).")
    if not PREFIX_RE.match(spec.designator_prefix or ""):
        problems.append(f"Bezeichner-Präfix {spec.designator_prefix!r} ist ungültig.")
    count = spec.part_count
    if not 1 <= count <= MAX_PART_COUNT:
        problems.append(f"Teileanzahl {count} ist ungültig (1–{MAX_PART_COUNT}).")
        count = max(1, min(count, MAX_PART_COUNT))

    per_part: dict[int, list[str]] = {p: [] for p in range(1, count + 1)}
    for pin in spec.pins:
        where = f"Pin {pin.designator or '?'}"
        if not pin.designator or pin.designator != pin.designator.strip():
            problems.append(f"{where}: Pin-Nummer fehlt oder hat Leerzeichen am Rand.")
        tip_x, tip_y = pin.tip()
        for label, value in (
            ("x", pin.x),
            ("y", pin.y),
            ("Länge", pin.length),
            ("Spitze x", tip_x),
            ("Spitze y", tip_y),
        ):
            if value % RASTER:
                problems.append(f"{where}: {label} = {value} mil liegt nicht im {RASTER}-mil-Raster.")
        if pin.length <= 0:
            problems.append(f"{where}: Länge {pin.length} mil ist nicht positiv.")
        if not pin.hidden and (tip_x % grid or tip_y % grid):
            problems.append(f"{where}: Anschlusspunkt ({tip_x}, {tip_y}) liegt nicht im {grid}-mil-Raster.")
        if max(abs(pin.x), abs(pin.y), abs(tip_x), abs(tip_y)) > COORD_LIMIT:
            problems.append(f"{where}: Koordinaten außerhalb von ±{COORD_LIMIT} mil.")
        if not 0 <= pin.part <= count:
            problems.append(f"{where}: Teil {pin.part} existiert nicht (0 = alle Teile, 1–{count}).")
            continue
        targets = range(1, count + 1) if pin.part == 0 else (pin.part,)
        for part in targets:
            per_part[part].append(pin.designator)
    for part, designators in per_part.items():
        dupes = sorted(d for d, n in Counter(designators).items() if n > 1)
        if dupes:
            problems.append(f"Teil {part}: Pin-Nummern doppelt: {', '.join(dupes)}.")

    used_parts: set[int] = set()
    for idx, g in enumerate(spec.graphics, start=1):
        if not 0 <= g.part <= count:
            problems.append(f"Grafik {idx} ({g.kind}): Teil {g.part} existiert nicht.")
        if not all(math.isfinite(v) and abs(v) <= COORD_LIMIT for v in _graphic_values(g)):
            problems.append(f"Grafik {idx} ({g.kind}): Koordinaten ungültig (NaN, unendlich oder zu groß).")
        used_parts.add(g.part)
        for label, color in (("Linienfarbe", g.color), ("Füllfarbe", g.fill_color)):
            if color is not None and not _HEX_RE.match(color):
                problems.append(f"Grafik {idx} ({g.kind}): {label} {color!r} ist kein #RRGGBB-Wert.")
    used_parts.update(p.part for p in spec.pins)
    if count > 1 and 0 not in used_parts:
        empty = [p for p in range(1, count + 1) if p not in used_parts]
        if empty:
            problems.append(f"Teil {', '.join(map(str, empty))} ist leer.")
    x1, y1, x2, y2 = spec.bbox()
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or max(abs(x1), abs(y1), abs(x2), abs(y2)) > COORD_LIMIT:
        problems.append("Die Abmessungen des Symbols sind ungültig.")
    return problems


def spec_warnings(spec: SymbolSpec, *, grid: int = 100) -> list[str]:
    """:func:`check_spec` problems plus soft hints (shown with previews, not blocking)."""
    out = check_spec(spec, grid=grid)
    odd = sorted({p.name for p in spec.pins if p.name and not p.name.isascii()})
    if odd:
        out.append(
            "Pinnamen mit Sonderzeichen ("
            + ", ".join(odd[:5])
            + ("…" if len(odd) > 5 else "")
            + "): Darstellung in Altium ist noch nicht geprüft – besser ASCII verwenden (z. B. u statt µ)."
        )
    foreign = _non_latin1(spec.description or "")
    if foreign:  # Latin-1 (ä, ö, ü, ß, µ, °, ±) is VERIFIED: Altium 26.10 reads it intact from the SchLib
        out.append(
            f"Die Beschreibung enthält Zeichen außerhalb von Latin-1 ({' '.join(foreign[:5])}"
            + (" …" if len(foreign) > 5 else "")
            + "); Altium zeigt sie im SchLib eventuell falsch an."
        )
    hidden = [p.designator for p in spec.pins if p.hidden]
    if hidden:
        out.append(
            f"Verborgene Pins ({', '.join(hidden[:8])}{'…' if len(hidden) > 8 else ''}) werden in Altium "
            "nur über ihren Netznamen verbunden."
        )
    return out
