"""Minimal STEP AP214 (ISO 10303-21, AUTOMOTIVE_DESIGN) writer for the extruded 3D bodies.

Every ``Body3D`` becomes one MANIFOLD_SOLID_BREP made of planar faces (bottom, top, one side face
per outline edge) with a ``STYLED_ITEM`` colour. All solids share one product and one
ADVANCED_BREP_SHAPE_REPRESENTATION (structure as in recherche/rust-writer/make_step_box.py, which
the Rust library writer embedded successfully). Units: millimetre. Output is deterministic.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from pathlib import Path

from ..geometry.model import Body3D, FootprintSpec
from .naming import ascii_name, ascii_text

log = logging.getLogger(__name__)

DEFAULT_TIMESTAMP = "2026-01-01T00:00:00"


def _real(v: float) -> str:
    """STEP real literal, always with a decimal point: 1.0 -> "1.", -0.25 -> "-0.25", 0 -> "0."."""
    v = round(float(v), 6)
    if v == 0:
        return "0."
    return f"{v:.6f}".rstrip("0")


def _string(text: str) -> str:
    """STEP string literal: printable ASCII, apostrophes doubled, no backslash (encoding directives)."""
    clean = ascii_text(text).replace("\\", "/")[:200]
    return "'" + clean.replace("'", "''") + "'"


def _rgb(color: str) -> tuple[float, float, float]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return (0.5, 0.5, 0.5)
    return (round(r / 255, 4), round(g / 255, 4), round(b / 255, 4))


def _clean_outline(body: Body3D) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for p in body.outline:
        q = (round(p.x, 6), round(p.y, 6))
        if not pts or abs(q[0] - pts[-1][0]) > 1e-6 or abs(q[1] - pts[-1][1]) > 1e-6:
            pts.append(q)
    if len(pts) > 1 and abs(pts[0][0] - pts[-1][0]) < 1e-6 and abs(pts[0][1] - pts[-1][1]) < 1e-6:
        pts.pop()
    area = 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts))) if len(pts) >= 3 else 0.0
    if area < 0:
        pts.reverse()
    return pts if abs(area) > 1e-9 else []


class _Writer:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self._directions: dict[tuple[str, str, str], int] = {}
        self._styles: dict[str, int] = {}

    def add(self, entity: str) -> int:
        self.lines.append(entity)
        return len(self.lines)

    def point(self, x: float, y: float, z: float) -> int:
        return self.add(f"CARTESIAN_POINT('',({_real(x)},{_real(y)},{_real(z)}))")

    def direction(self, x: float, y: float, z: float) -> int:
        key = (_real(x), _real(y), _real(z))
        if key not in self._directions:
            self._directions[key] = self.add(f"DIRECTION('',({key[0]},{key[1]},{key[2]}))")
        return self._directions[key]

    def style(self, color: str) -> int:
        if color not in self._styles:
            r, g, b = _rgb(color)
            rgb = self.add(f"COLOUR_RGB('',{_real(r)},{_real(g)},{_real(b)})")
            fill_c = self.add(f"FILL_AREA_STYLE_COLOUR('',#{rgb})")
            fas = self.add(f"FILL_AREA_STYLE('',(#{fill_c}))")
            ssfa = self.add(f"SURFACE_STYLE_FILL_AREA(#{fas})")
            sss = self.add(f"SURFACE_SIDE_STYLE('',(#{ssfa}))")
            ssu = self.add(f"SURFACE_STYLE_USAGE(.BOTH.,#{sss})")
            self._styles[color] = self.add(f"PRESENTATION_STYLE_ASSIGNMENT((#{ssu}))")
        return self._styles[color]

    def prism(self, name: str, pts: list[tuple[float, float]], z0: float, z1: float) -> int:
        n = len(pts)
        bottom = [self.point(x, y, z0) for x, y in pts]
        top = [self.point(x, y, z1) for x, y in pts]
        vb = [self.add(f"VERTEX_POINT('',#{p})") for p in bottom]
        vt = [self.add(f"VERTEX_POINT('',#{p})") for p in top]

        def edge(p_from: int, p_to: int, v_from: int, v_to: int, a: tuple[float, float, float],
                 b: tuple[float, float, float]) -> int:
            dx, dy, dz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
            ln = math.sqrt(dx * dx + dy * dy + dz * dz)
            d = self.direction(dx / ln, dy / ln, dz / ln)
            vec = self.add(f"VECTOR('',#{d},{_real(ln)})")
            line = self.add(f"LINE('',#{p_from},#{vec})")
            return self.add(f"EDGE_CURVE('',#{v_from},#{v_to},#{line},.T.)")

        e_bottom, e_top, e_vert = [], [], []
        for i in range(n):
            j = (i + 1) % n
            (x0, y0), (x1, y1) = pts[i], pts[j]
            e_bottom.append(edge(bottom[i], bottom[j], vb[i], vb[j], (x0, y0, z0), (x1, y1, z0)))
            e_top.append(edge(top[i], top[j], vt[i], vt[j], (x0, y0, z1), (x1, y1, z1)))
            e_vert.append(edge(bottom[i], top[i], vb[i], vt[i], (x0, y0, z0), (x0, y0, z1)))

        def face(loop: list[tuple[int, bool]], origin: int, normal: tuple[float, float, float],
                 ref: tuple[float, float, float]) -> int:
            oes = [self.add(f"ORIENTED_EDGE('',*,*,#{e},{'.T.' if sense else '.F.'})") for e, sense in loop]
            el = self.add("EDGE_LOOP('',(" + ",".join(f"#{o}" for o in oes) + "))")
            bound = self.add(f"FACE_OUTER_BOUND('',#{el},.T.)")
            axis = self.add(f"AXIS2_PLACEMENT_3D('',#{origin},#{self.direction(*normal)},#{self.direction(*ref)})")
            plane = self.add(f"PLANE('',#{axis})")
            return self.add(f"ADVANCED_FACE('',(#{bound}),#{plane},.T.)")

        faces = [
            # bottom (normal -Z): outline traversed clockwise seen from above
            face([(e_bottom[i], False) for i in reversed(range(n))], bottom[0], (0, 0, -1), (1, 0, 0)),
            # top (normal +Z): counter-clockwise
            face([(e_top[i], True) for i in range(n)], top[0], (0, 0, 1), (1, 0, 0)),
        ]
        for i in range(n):
            j = (i + 1) % n
            (x0, y0), (x1, y1) = pts[i], pts[j]
            ln = math.hypot(x1 - x0, y1 - y0)
            ux, uy = (x1 - x0) / ln, (y1 - y0) / ln
            loop = [(e_bottom[i], True), (e_vert[j], True), (e_top[i], False), (e_vert[i], False)]
            faces.append(face(loop, bottom[i], (round(uy, 9), round(-ux, 9), 0.0), (round(ux, 9), round(uy, 9), 0.0)))
        shell = self.add("CLOSED_SHELL('',(" + ",".join(f"#{f}" for f in faces) + "))")
        return self.add(f"MANIFOLD_SOLID_BREP({_string(name)},#{shell})")


#: Part of :func:`step_digest` – bump when :func:`step_text` writes differently.
STEP_WRITER_VERSION = "1"
_DIGEST_RE = re.compile(r"FILE_NAME\([^;]*'pf:([0-9a-f]{16})'\);")


def step_digest(spec: FootprintSpec) -> str:
    """16 hex digits over everything :func:`step_text` writes (name, description, bodies, writer version) – stored in
    the file (``FILE_NAME`` authorisation ``pf:<digest>``), so an unchanged model is recognised without generating it."""
    data = {
        "v": STEP_WRITER_VERSION,
        "name": spec.name,
        "description": spec.description,
        "bodies": [b.model_dump(mode="json") for b in spec.bodies],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def file_digest(head: str | None) -> str | None:
    """The :func:`step_digest` recorded in a STEP text (its first few KB suffice), ``None`` if there is none."""
    match = _DIGEST_RE.search(head or "")
    return match.group(1) if match else None


def step_text(spec: FootprintSpec, *, timestamp: str = DEFAULT_TIMESTAMP) -> str:
    """STEP AP214 text of all extruded bodies of ``spec`` (raises ValueError if it has none)."""
    bodies = [(b, _clean_outline(b)) for b in spec.bodies]
    bodies = [(b, pts) for b, pts in bodies if len(pts) >= 3 and b.z_top - b.z_bottom > 1e-6]
    if not bodies:
        raise ValueError(f"Footprint „{spec.name}“ hat keine 3D-Körper – STEP-Export nicht möglich.")
    name = ascii_name(spec.name or "PartForge", 200) or "PartForge"
    w = _Writer()
    app = w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,#{app})")
    pctx = w.add(f"PRODUCT_CONTEXT('',#{app},'mechanical')")
    prod = w.add(f"PRODUCT({_string(name)},{_string(name)},{_string(spec.description or name)},(#{pctx}))")
    pdf = w.add(f"PRODUCT_DEFINITION_FORMATION('','',#{prod})")
    pdctx = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',#{app},'design')")
    pd = w.add(f"PRODUCT_DEFINITION('design','',#{pdf},#{pdctx})")
    pds = w.add(f"PRODUCT_DEFINITION_SHAPE('','',#{pd})")
    w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,(#{prod}))")
    len_u = w.add("( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) )")
    ang_u = w.add("( NAMED_UNIT(*) PLANE_ANGLE_UNIT() SI_UNIT($,.RADIAN.) )")
    sol_u = w.add("( NAMED_UNIT(*) SI_UNIT($,.STERADIAN.) SOLID_ANGLE_UNIT() )")
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),#{len_u},'distance_accuracy_value',"
                "'confusion accuracy')")
    ctx = w.add(f"( GEOMETRIC_REPRESENTATION_CONTEXT(3) GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT((#{unc})) "
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT((#{len_u},#{ang_u},#{sol_u})) "
                "REPRESENTATION_CONTEXT('Context #1','3D Context with UNIT and UNCERTAINTY') )")
    origin = w.point(0, 0, 0)
    axis = w.add(f"AXIS2_PLACEMENT_3D('',#{origin},#{w.direction(0, 0, 1)},#{w.direction(1, 0, 0)})")
    solids: list[tuple[int, str]] = []
    for index, (body, pts) in enumerate(bodies, start=1):
        brep = w.prism(body.name or f"Body{index}", pts, body.z_bottom, body.z_top)
        solids.append((brep, body.color))
    rep = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({_string(name)},(#{axis},"
                + ",".join(f"#{s}" for s, _ in solids) + f"),#{ctx})")
    w.add(f"SHAPE_DEFINITION_REPRESENTATION(#{pds},#{rep})")
    styled = [w.add(f"STYLED_ITEM('color',(#{w.style(color)}),#{brep})") for brep, color in solids]
    w.add("MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',(" + ",".join(f"#{s}" for s in styled)
          + f"),#{ctx})")
    head = (
        "ISO-10303-21;\nHEADER;\n"
        f"FILE_DESCRIPTION(({_string('PartForge 3D model of ' + name)}),'2;1');\n"
        f"FILE_NAME({_string(name + '.step')},'{timestamp}',('PartForge'),('PartForge'),"
        f"'PartForge STEP writer','PartForge','pf:{step_digest(spec)}');\n"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n"
    )
    data = "".join(f"#{i}={s};\n" for i, s in enumerate(w.lines, 1))
    return head + data + "ENDSEC;\nEND-ISO-10303-21;\n"


def write_step(spec: FootprintSpec, path: Path | str) -> Path:
    """Write the STEP file (ASCII, LF line ends); creates parent folders. Returns the path."""
    target = Path(path)
    text = step_text(spec)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(text, encoding="ascii", newline="\n")
    tmp.replace(target)
    log.debug("STEP geschrieben: %s (%d Körper)", target, len(spec.bodies))
    return target
