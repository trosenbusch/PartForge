"""Plausibility checks for footprints (generated or imported).

* pad overlap / copper clearance between pads with different designators
* silkscreen over pads (must be zero) and silk-to-copper clearance
* courtyard present and enclosing all pads and 3D bodies
* degenerate lands (G <= 0) from the calculation record
* THT annular ring, paste windows inside their pad, name rules
"""
from __future__ import annotations

import itertools
import math
import re
from collections.abc import Mapping
from typing import Any

from ..geometry.model import Arc, FootprintSpec, Pad
from ..workspace import FootprintStyle
from . import geom
from .ipc7351 import DEFAULT_MIN_COPPER_GAP, THT_ANNULAR_RING_MIN, fmt_mm
from .models import CheckIssue
from .naming import name_problems

_EPS = 1e-4  # mm tolerance (quantisation of writers, float noise)


def _issue(severity: str, code: str, message: str) -> CheckIssue:
    return CheckIssue(severity=severity, code=code, message=message)  # type: ignore[arg-type]


def _pad_shape_poly(p: Pad) -> list[geom.XY]:
    if p.shape in ("circle",) and abs(p.width - p.height) < 1e-9 and not p.rotation:
        return geom.circle_points(p.x, p.y, p.width / 2, 24)
    return geom.pad_polygon(p)


def _arc_segments(a: Arc) -> list[tuple[geom.XY, geom.XY]]:
    full = abs((a.end - a.start) % 360) < 1e-9 and a.end != a.start
    pts = geom.circle_points(a.cx, a.cy, a.r, 36, start=a.start, end=a.end if not full else a.start + 360)
    if full:
        pts.append(pts[0])
    return list(itertools.pairwise(pts))


def _candidate_pairs(boxes: list[geom.Rect], margin: float) -> list[tuple[int, int]]:
    """Index pairs (i < j) whose boxes come closer than ``margin`` (sort and sweep along X)."""
    order = sorted(range(len(boxes)), key=lambda k: boxes[k][0])
    pairs: list[tuple[int, int]] = []
    for pos, i in enumerate(order):
        x_limit = boxes[i][2] + margin
        for j in order[pos + 1:]:
            if boxes[j][0] > x_limit:
                break
            if geom.rects_overlap(boxes[i], boxes[j], margin):
                pairs.append((min(i, j), max(i, j)))
    pairs.sort()
    return pairs


def check_pads(spec: FootprintSpec, min_gap: float) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    pads = spec.pads
    boxes = [geom.pad_bbox(p) for p in pads]
    polys: dict[int, list[geom.XY]] = {}

    def poly(k: int) -> list[geom.XY]:
        if k not in polys:
            polys[k] = _pad_shape_poly(pads[k])
        return polys[k]

    reported: set[tuple[str, str]] = set()
    for i, j in _candidate_pairs(boxes, min_gap):
        a, b = pads[i], pads[j]
        if a.designator == b.designator:
            continue
        if not (a.side == b.side or "through" in (a.side, b.side)):
            continue
        key = (a.designator, b.designator)
        if key in reported:
            continue
        d = geom.dist_polygon_polygon(poly(i), poly(j))
        if d <= _EPS:
            reported.add(key)
            issues.append(_issue("error", "pad_overlap", f"Pads {a.designator} und {b.designator} überlappen."))
        elif d < min_gap - _EPS:
            reported.add(key)
            issues.append(_issue("warning", "pad_clearance",
                                 f"Kupferabstand zwischen Pad {a.designator} und {b.designator} nur "
                                 f"{fmt_mm(d)} mm (Minimum {fmt_mm(min_gap)} mm)."))
    seen: dict[str, int] = {}
    for p in pads:
        seen[p.designator] = seen.get(p.designator, 0) + 1
    dups = sorted(d for d, n in seen.items() if n > 1)
    if dups:
        issues.append(_issue("info", "duplicate_designator",
                             f"Mehrfach vergebene Pad-Bezeichner: {', '.join(dups)} (Altium erlaubt das).")
                      )
    for p in pads:
        if p.hole is not None:
            ring = (min(p.width, p.height) - p.hole) / 2
            if ring < THT_ANNULAR_RING_MIN - _EPS:
                issues.append(_issue("error", "annular_ring",
                                     f"Pad {p.designator}: Restring {fmt_mm(ring)} mm < "
                                     f"{fmt_mm(THT_ANNULAR_RING_MIN)} mm."))
        if p.width <= 0 or p.height <= 0:
            issues.append(_issue("error", "pad_size", f"Pad {p.designator} hat keine gültige Größe."))
    return issues


def check_silk(spec: FootprintSpec, clearance: float) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    pads = [p for p in spec.pads if p.side in ("top", "through")]
    polys = [_pad_shape_poly(p) for p in pads]
    boxes = [geom.pad_bbox(p) for p in pads]
    overlaps: set[str] = set()
    close: dict[str, float] = {}

    def check_segment(a: geom.XY, b: geom.XY, width: float) -> None:
        seg_box = geom.rect(a[0], a[1], b[0], b[1])
        for pad, poly, box in zip(pads, polys, boxes, strict=False):
            if not geom.rects_overlap(seg_box, box, clearance + width):
                continue
            d = geom.dist_segment_polygon(a, b, poly) - width / 2
            if d < -_EPS or d <= 0:
                overlaps.add(pad.designator)
            elif d < clearance - _EPS:
                close[pad.designator] = min(close.get(pad.designator, math.inf), d)

    for t in spec.tracks:
        if t.layer == "top_silk":
            check_segment((t.x1, t.y1), (t.x2, t.y2), t.width)
    for arc in spec.arcs:
        if arc.layer == "top_silk":
            full = abs((arc.end - arc.start) % 360) < 1e-9 and arc.end != arc.start
            if full and arc.width >= 2 * arc.r - 1e-9:  # filled dot
                for pad, poly in zip(pads, polys, strict=False):
                    d = geom.dist_point_polygon((arc.cx, arc.cy), poly) - (arc.r + arc.width / 2)
                    if d < -_EPS or d <= 0:
                        overlaps.add(pad.designator)
                    elif d < clearance - _EPS:
                        close[pad.designator] = min(close.get(pad.designator, math.inf), d)
            else:
                for a, b in _arc_segments(arc):
                    check_segment(a, b, arc.width)
    for rg in spec.regions:
        if rg.layer == "top_silk":
            pts = geom.from_points(rg.points)
            for pad, poly in zip(pads, polys, strict=False):
                d = geom.dist_polygon_polygon(pts, poly)
                if d <= _EPS:
                    overlaps.add(pad.designator)
                elif d < clearance - _EPS:
                    close[pad.designator] = min(close.get(pad.designator, math.inf), d)
    if overlaps:
        issues.append(_issue("error", "silk_over_pad",
                             f"Bestückungsdruck liegt auf Pad(s) {', '.join(sorted(overlaps, key=_nat))}."))
    if close:
        worst = min(close.values())
        issues.append(_issue("warning", "silk_clearance",
                             f"Bestückungsdruck nur {fmt_mm(worst)} mm von Pad(s) "
                             f"{', '.join(sorted(close, key=_nat))} entfernt (Hausstil {fmt_mm(clearance)} mm)."))
    return issues


def courtyard_rect(spec: FootprintSpec) -> geom.Rect | None:
    pts: list[geom.XY] = []
    for t in spec.tracks:
        if t.layer == "courtyard":
            pts += [(t.x1, t.y1), (t.x2, t.y2)]
    for a in spec.arcs:
        if a.layer == "courtyard":
            pts += [(a.cx - a.r, a.cy - a.r), (a.cx + a.r, a.cy + a.r)]
    for rg in spec.regions:
        if rg.layer == "courtyard":
            pts += geom.from_points(rg.points)
    return geom.bbox_points(pts)


def check_courtyard(spec: FootprintSpec) -> list[CheckIssue]:
    cy = courtyard_rect(spec)
    if cy is None:
        return [_issue("error", "courtyard_missing", "Kein Courtyard vorhanden.")]
    issues: list[CheckIssue] = []
    outside = [p.designator for p in spec.pads if not geom.rect_contains(cy, geom.pad_bbox(p), _EPS)]
    if outside:
        issues.append(_issue("error", "courtyard",
                             f"Courtyard umschließt Pad(s) {', '.join(sorted(outside, key=_nat))} nicht."))
    bodies = [b for b in spec.bodies if b.outline]
    out_bodies = [b.name for b in bodies
                  if not geom.rect_contains(cy, geom.bbox_points(geom.from_points(b.outline)) or cy, 0.01)]
    if out_bodies:
        issues.append(_issue("error", "courtyard_body",
                             f"Courtyard umschließt den Bauteilkörper nicht ({', '.join(out_bodies[:3])})."))
    return issues


def check_paste(spec: FootprintSpec) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    thermal = [geom.pad_bbox(p) for p in spec.pads if p.thermal]
    for rg in spec.regions:
        if rg.layer != "top_paste" or not thermal:
            continue
        box = geom.bbox_points(geom.from_points(rg.points))
        if box and not any(geom.rect_contains(t, box, _EPS) for t in thermal):
            issues.append(_issue("warning", "paste_window", "Pastenfenster liegt außerhalb des Exposed Pads."))
            break
    return issues


def check_calc(calc: Mapping[str, Any] | None) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for land in (calc or {}).get("lands", []):
        g, z = land.get("g"), land.get("z")
        if g is not None and z is not None and land.get("table_key") not in ("flat_lug",):
            if g <= 0:
                issues.append(_issue("error", "gap", f"{land.get('label') or 'Pads'}: Innenabstand G = "
                                                     f"{fmt_mm(g)} mm (≤ 0)."))
            if z <= g:
                issues.append(_issue("error", "land", f"{land.get('label') or 'Pads'}: Z ≤ G."))
    return issues


def validate_footprint(spec: FootprintSpec, style: FootprintStyle | None = None, *,
                       calc: Mapping[str, Any] | None = None,
                       min_copper_gap: float = DEFAULT_MIN_COPPER_GAP) -> list[CheckIssue]:
    style = style or FootprintStyle()
    issues: list[CheckIssue] = []
    for problem in name_problems(spec.name):
        issues.append(_issue("error", "name", f"Footprint-Name „{spec.name}“: {problem}"))
    if not spec.pads:
        issues.append(_issue("error", "no_pads", "Footprint hat keine Pads."))
    issues += check_pads(spec, min_copper_gap)
    issues += check_silk(spec, style.silk_pad_clearance)
    issues += check_courtyard(spec)
    issues += check_paste(spec)
    issues += check_calc(calc)
    if spec.height is not None and spec.height <= 0:
        issues.append(_issue("warning", "height", "Bauhöhe ist nicht positiv."))
    return issues


def _nat(s: str) -> tuple:
    return tuple((0, int(t)) if t.isdigit() else (1, t) for t in re.split(r"(\d+)", s) if t)
