"""STEP AP214 writer: file structure, references, B-rep topology and geometry of the extruded bodies."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from partforge.footprints import FootprintRequest, generate, step_text, write_step
from partforge.geometry.model import Body3D, FootprintSpec, Point

_ENTITY = re.compile(r"^#(\d+)=(.*);$")


def parse_step(text: str) -> dict[int, str]:
    assert text.startswith("ISO-10303-21;\nHEADER;\n")
    assert "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));" in text
    assert text.endswith("ENDSEC;\nEND-ISO-10303-21;\n")
    assert text.isascii()
    data = text.split("DATA;\n", 1)[1].rsplit("ENDSEC;", 1)[0]
    entities: dict[int, str] = {}
    for line in data.strip().splitlines():
        m = _ENTITY.match(line)
        assert m, line
        entities[int(m.group(1))] = m.group(2)
    assert sorted(entities) == list(range(1, len(entities) + 1)), "fortlaufende Entity-Nummern"
    for ident, body in entities.items():
        for ref in re.findall(r"#(\d+)", body):
            assert int(ref) in entities, f"#{ident} verweist auf fehlendes #{ref}"
    return entities


def etype(body: str) -> str:
    return body.split("(", 1)[0].strip() if not body.startswith("(") else "COMPLEX"


def refs(body: str) -> list[int]:
    return [int(r) for r in re.findall(r"#(\d+)", body)]


def point(entities: dict[int, str], ident: int) -> tuple[float, float, float]:
    body = entities[ident]
    assert etype(body) == "CARTESIAN_POINT"
    nums = re.findall(r"[-+]?\d+\.\d*(?:E[-+]?\d+)?", body.split("(", 2)[2])
    return tuple(float(n) for n in nums[:3])  # type: ignore[return-value]


def check_solid(entities: dict[int, str], brep: int) -> float:
    """Validate one MANIFOLD_SOLID_BREP; returns its (positive) volume."""
    shell = refs(entities[brep])[-1]
    assert etype(entities[shell]) == "CLOSED_SHELL"
    faces = refs(entities[shell])
    edge_uses: Counter[tuple[int, bool]] = Counter()
    vertices: set[int] = set()
    volume = 0.0
    for face in faces:
        assert etype(entities[face]) == "ADVANCED_FACE"
        bound, plane = refs(entities[face])
        assert etype(entities[bound]) == "FACE_OUTER_BOUND"
        loop = refs(entities[bound])[0]
        assert etype(entities[loop]) == "EDGE_LOOP"
        chain: list[tuple[int, int]] = []
        for oe in refs(entities[loop]):
            assert etype(entities[oe]) == "ORIENTED_EDGE"
            edge = refs(entities[oe])[0]
            sense = entities[oe].rstrip(")").endswith(".T.")
            v1, v2, line = refs(entities[edge])
            assert etype(entities[line]) == "LINE"
            edge_uses[(edge, sense)] += 1
            chain.append((v1, v2) if sense else (v2, v1))
        for (_, b), (c, _) in zip(chain, chain[1:] + chain[:1], strict=True):
            assert b == c, "Kantenschleife ist geschlossen und zusammenhängend"
        loop_pts = [point(entities, refs(entities[v])[0]) for v, _ in chain]
        vertices.update(v for v, _ in chain)
        # loop orientation agrees with the plane normal (Newell normal)
        nx = ny = nz = 0.0
        for (x1, y1, z1), (x2, y2, z2) in zip(loop_pts, loop_pts[1:] + loop_pts[:1], strict=True):
            nx += (y1 - y2) * (z1 + z2)
            ny += (z1 - z2) * (x1 + x2)
            nz += (x1 - x2) * (y1 + y2)
        axis = refs(entities[refs(entities[plane])[0]])
        direction = [float(v) for v in re.findall(r"[-+]?\d+\.\d*", entities[axis[1]])]
        assert nx * direction[0] + ny * direction[1] + nz * direction[2] > 0
        # divergence theorem: fan triangulation of the (planar, possibly concave) loop
        p0 = loop_pts[0]
        for p1, p2 in zip(loop_pts[1:], loop_pts[2:], strict=False):
            volume += (p0[0] * (p1[1] * p2[2] - p1[2] * p2[1]) - p0[1] * (p1[0] * p2[2] - p1[2] * p2[0])
                       + p0[2] * (p1[0] * p2[1] - p1[1] * p2[0])) / 6
    edges = {e for e, _ in edge_uses}
    for edge in edges:
        assert edge_uses[(edge, True)] == 1 and edge_uses[(edge, False)] == 1, "manifold, konsistent orientiert"
    assert len(vertices) - len(edges) + len(faces) == 2, "Euler-Charakteristik eines Prismas"
    return volume


def solids(entities: dict[int, str]) -> list[int]:
    return [i for i, b in entities.items() if etype(b) == "MANIFOLD_SOLID_BREP"]


def _prism_area(outline: list[Point]) -> float:
    n = len(outline)
    return abs(sum(outline[i].x * outline[(i + 1) % n].y - outline[(i + 1) % n].x * outline[i].y
                   for i in range(n))) / 2


@pytest.mark.parametrize(("family", "preset"), [
    ("chip", "R-0603"), ("chip", "C-1210"), ("molded", "Tantal-B"), ("gullwing", "SOIC-8"),
    ("nolead", "QFN-16-3x3-P0.5"), ("bga", "BGA-64-8x8-P0.8"), ("radial", "D6.3x11-P2.5"), ("to92", "TO-92-P1.27"),
    ("pin_header", "2x05-P2.54"), ("dpak", "DPAK-2"), ("to220", "TO-220-3"),
])
def test_step_structure_and_topology(family, preset):
    spec = generate(FootprintRequest(family=family, params={"preset": preset}))
    entities = parse_step(step_text(spec))
    breps = solids(entities)
    assert len(breps) == len(spec.bodies)
    for brep, body in zip(breps, spec.bodies, strict=True):
        volume = check_solid(entities, brep)
        expected = _prism_area(body.outline) * (body.z_top - body.z_bottom)
        assert volume == pytest.approx(expected, rel=1e-4, abs=1e-6)
    styled = [b for b in entities.values() if etype(b) == "STYLED_ITEM"]
    assert len(styled) == len(spec.bodies)
    colours = [b for b in entities.values() if etype(b) == "COLOUR_RGB"]
    assert len(colours) == len({b.color for b in spec.bodies})
    types = Counter(etype(b) for b in entities.values())
    for required in ("APPLICATION_PROTOCOL_DEFINITION", "PRODUCT", "PRODUCT_DEFINITION_SHAPE",
                     "ADVANCED_BREP_SHAPE_REPRESENTATION", "SHAPE_DEFINITION_REPRESENTATION",
                     "MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION"):
        assert types[required] == 1, required
    rep = next(b for b in entities.values() if etype(b) == "ADVANCED_BREP_SHAPE_REPRESENTATION")
    assert set(breps) <= set(refs(rep))


def test_concave_prism_and_colour():
    l_shape = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 2), (0, 2)]
    spec = FootprintSpec(name="L-Form", bodies=[
        Body3D(name="L", outline=[Point(x=x, y=y) for x, y in l_shape], z_bottom=0.5, z_top=1.5, color="#FF8000"),
        # clockwise outline and a duplicate closing point are normalised
        Body3D(name="Box", outline=[Point(x=0, y=0), Point(x=0, y=1), Point(x=1, y=1), Point(x=1, y=0),
                                    Point(x=0, y=0)], z_top=2.0, color="#00F"),
    ])
    entities = parse_step(step_text(spec))
    breps = solids(entities)
    assert check_solid(entities, breps[0]) == pytest.approx(4.0)
    assert check_solid(entities, breps[1]) == pytest.approx(2.0)
    colours = sorted(b for b in entities.values() if etype(b) == "COLOUR_RGB")
    assert "COLOUR_RGB('',0.,0.,1.)" in colours
    assert "COLOUR_RGB('',1.,0.502,0.)" in colours


def test_write_step_file(tmp_path: Path):
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}))
    target = write_step(spec, tmp_path / "3D" / "SOIC-8.step")
    assert target == tmp_path / "3D" / "SOIC-8.step"
    text = target.read_text(encoding="ascii")
    assert text == step_text(spec)
    assert "SOIC127P600X175-8N" in text
    assert not list(tmp_path.rglob("*.tmp"))


def test_step_is_deterministic():
    spec = generate(FootprintRequest(family="qfp", params={"preset": "LQFP-48-7x7-P0.5"}))
    assert step_text(spec) == step_text(spec)
    assert "2026-01-01T00:00:00" in step_text(spec)
    assert "1999-12-31T23:59:59" in step_text(spec, timestamp="1999-12-31T23:59:59")


def test_step_without_bodies_raises():
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}, with_3d=False))
    with pytest.raises(ValueError, match="keine 3D-Körper"):
        step_text(spec)


def test_step_escapes_quotes_and_non_ascii_text():
    spec = FootprintSpec(name="Größe A", description="10 kΩ, Ø 'B' \\x", bodies=[
        Body3D(name="Kopf 'X'", outline=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)], z_top=1.0)])
    text = step_text(spec)
    parse_step(text)
    assert "'Groesse A'" in text
    assert "'10 kOhm, D ''B'' /x'" in text
    assert "MANIFOLD_SOLID_BREP('Kopf ''X''',#" in text
