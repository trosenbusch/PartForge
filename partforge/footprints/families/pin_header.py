"""Straight pin headers 1×N / 2×N with 2.54 / 2.00 / 1.27 mm pitch (through-hole).

Pins in columns along Y, pin 1 at the top left (square pad). Two-row numbering like KiCad:
odd pins in the left row, even pins in the right row. Holes from the square post diagonal (IPC-2222).
Post/plastic dimensions: KiCad data (Würth 6130xx11121, Harwin M50-353) (S5).
"""
from __future__ import annotations

import math

from ...geometry.model import FootprintSpec
from .. import ipc7351 as ipc
from .. import naming
from ..builder import GOLD, HEADER_PLASTIC
from ..geom import r6
from ..models import FamilyInfo, Preset
from .base import COMMON_THT, FamilyDef, GenContext, describe, dot_left, p_enum, p_float, p_int

PITCH_DATA: dict[str, dict[str, float]] = {
    "2.54": {"post": 0.64, "body_h": 2.54, "post_above": 6.0},
    "2.00": {"post": 0.50, "body_h": 1.8, "post_above": 4.2},
    "1.27": {"post": 0.40, "body_h": 1.0, "post_above": 4.0},
}


def _presets() -> list[Preset]:
    combos = [("1", n, "2.54") for n in (2, 3, 4, 5, 6, 8, 10)]
    combos += [("2", n, "2.54") for n in (3, 5, 8, 10, 20)]
    combos += [("1", 4, "2.00"), ("2", 5, "2.00"), ("1", 5, "1.27"), ("2", 5, "1.27")]
    return [
        Preset(key=f"{rows}x{n:02d}-P{pitch}", label=f"Stiftleiste {rows}×{n:02d}, Raster {pitch} mm".replace(".", ","),
               source="KiCad-Daten (Würth 6130xx11121 / Harwin M50-353)",
               params={"rows": rows, "pins_per_row": n, "pitch": pitch})
        for rows, n, pitch in combos
    ]


PARAMS = [
    p_enum("rows", "Reihen", ["1", "2"], default="1", group="Anschlüsse"),
    p_int("pins_per_row", "Pins je Reihe", default=4, minimum=1, maximum=50),
    p_enum("pitch", "Raster", list(PITCH_DATA), default="2.54", group="Anschlüsse", unit="mm"),
    p_float("post", "Stiftquerschnitt", minimum=0.2, maximum=1.5, help="Leer = Standardwert des Rasters."),
    p_float("body_h", "Höhe Isolierkörper", minimum=0.5, maximum=10.0),
    p_float("post_above", "Stiftlänge über Isolierkörper", minimum=0.0, maximum=30.0),
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="pin_header",
    label="Stiftleiste (1×N / 2×N)",
    group="Bedrahtet",
    description="Gerade Stiftleisten im Raster 2,54 / 2,00 / 1,27 mm.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="IPC-2222 / IPC-2221",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    rows = int(p.enum("rows", "1"))
    n = p.int("pins_per_row", 4)
    pitch_key = p.enum("pitch", "2.54")
    pitch = float(pitch_key)
    data = PITCH_DATA[pitch_key]
    post = p.float("post", data["post"])
    body_h = p.float("body_h", data["body_h"])
    post_above = p.float("post_above", data["post_above"])
    # every rows × pins × pitch combination with the standard post/body is a standard header (identity)
    ctx.references.append({"rows": str(rows), "pins_per_row": n, "pitch": pitch_key, **data})

    land = ctx.tht_land(post * math.sqrt(2), 0.0)
    d = land.width
    limit = ipc.round_down(pitch - ctx.min_gap, 0.01)
    if d > limit:
        if limit < land.hole + 2 * ipc.THT_ANNULAR_RING_MIN:
            raise ValueError(f"Raster {ipc.fmt_mm(pitch)} mm ist für Bohrung {ipc.fmt_mm(land.hole)} mm zu klein.")
        ctx.warn(f"Pad {ipc.fmt_mm(d)} mm passt nicht ins Raster {ipc.fmt_mm(pitch)} mm – auf {ipc.fmt_mm(limit)} mm "
                 "verkleinert.")
        d = limit
        ctx.extra_calc["tht"][-1].update({"pad_width": d, "pad_height": d, "pitch": pitch})
    b = ctx.builder()
    xs = [0.0] if rows == 1 else [-pitch / 2, pitch / 2]
    for k in range(n):
        y = r6(((n - 1) / 2 - k) * pitch)
        for r, x in enumerate(xs):
            number = k + 1 if rows == 1 else 2 * k + r + 1
            b.tht_pad(str(number), x, y, d, d, land.hole, shape="rect" if number == 1 else "circle")
    half_x, half_y = rows * pitch / 2, n * pitch / 2
    body = b.body((-half_x, -half_y, half_x, half_y))
    sw = b.silk_width
    pads_box = b.pads_bbox()
    assert pads_box is not None
    clear = b.style.silk_pad_clearance + sw / 2
    outline = (min(body[0] - sw / 2, pads_box[0] - clear), min(body[1] - sw / 2, pads_box[1] - clear),
               max(body[2] + sw / 2, pads_box[2] + clear), max(body[3] + sw / 2, pads_box[3] + clear))
    b.silk_rect(outline)
    pad1 = b.pads[0]
    b.pin1_dot([(outline[0] - sw / 2 - 0.1 - b.dot_radius(), pad1.y), dot_left(b, pad1)], push=(-1.0, 0.0))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    b.box("Plastic", body, 0.0, body_h, HEADER_PLASTIC)
    for pad in b.pads:
        b.box(f"Pin {pad.designator}", (pad.x - post / 2, pad.y - post / 2, pad.x + post / 2, pad.y + post / 2), 0.0,
              body_h + post_above, GOLD)

    total = rows * n
    level = ipc.THT_LEVEL[ctx.density]
    height = body_h + post_above
    ipc_name = naming.ipc_header(total, post, pitch, rows, n, n * pitch, rows * pitch, height, level)
    house_name = naming.house(f"HEADER {rows}x{n:02d} P{pitch_key}", ctx.density)
    description = describe("Header", total, n * pitch, rows * pitch, ctx.density, pitch=pitch)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"Stiftleiste {rows}x{n:02d} {pitch_key} mm", height=height, courtyard_kind="tht")


FAMILIES = [FamilyDef(INFO, build, aliases=("header", "pinheader", "stiftleiste", "hdrv", "connector_header"))]
