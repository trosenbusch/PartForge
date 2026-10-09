"""Footprint / symbol builders producing write_pcblib / write_schlib JSON.

All PCB numbers are millimetres; origin = component centre (IPC-7351 convention),
+Y up, pin 1 top-left for dual-row parts.  Layers use the server's friendly names
(Top Assembly = Mechanical 2, Top Courtyard = Mechanical 4, Top 3D Body = Mechanical 6).
"""
from __future__ import annotations

SILK_W = 0.12
ASSY_W = 0.10
CRTYD_W = 0.05


def rect_tracks(x1, y1, x2, y2, width, layer):
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    return [{"x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "width": width, "layer": layer}
            for a, b in zip(pts, pts[1:])]


def poly_tracks(pts, width, layer, close=True):
    if close:
        pts = list(pts) + [pts[0]]
    return [{"x1": a[0], "y1": a[1], "x2": b[0], "y2": b[1], "width": width, "layer": layer}
            for a, b in zip(pts, pts[1:])]


def r(v, g=0.01):  # NOTE: Python round() is banker's rounding; use math.ceil for IPC courtyard rounding
    return round(round(v / g) * g, 4)


def chip_footprint(name, body_l, body_w, height, pad_x, pad_y, c, description="",
                   courtyard_excess=0.25, shape="rounded_rectangle", corner=25,
                   step_model=None, with_body=True):
    """2-terminal chip (RES/CAP/IND). pads centred at x = +-c/2."""
    hx = c / 2
    fp = {
        "name": name,
        "description": description,
        "pads": [
            {"designator": "1", "x": -hx, "y": 0, "width": pad_x, "height": pad_y,
             "shape": shape, "corner_radius_percent": corner, "layer": "Top Layer"},
            {"designator": "2", "x": hx, "y": 0, "width": pad_x, "height": pad_y,
             "shape": shape, "corner_radius_percent": corner, "layer": "Top Layer"},
        ],
    }
    # silkscreen: two lines along the long sides, outside the pad rows
    sy = r(max(pad_y / 2, body_w / 2) + 0.15 + SILK_W / 2, 0.01)
    sx = r(hx - pad_x / 2, 0.01)  # inner pad edge
    fp["tracks"] = [
        {"x1": -sx, "y1": sy, "x2": sx, "y2": sy, "width": SILK_W, "layer": "Top Overlay"},
        {"x1": -sx, "y1": -sy, "x2": sx, "y2": -sy, "width": SILK_W, "layer": "Top Overlay"},
    ]
    # assembly outline (body) + courtyard
    fp["tracks"] += rect_tracks(-body_l / 2, -body_w / 2, body_l / 2, body_w / 2, ASSY_W, "Top Assembly")
    cx = r(max(hx + pad_x / 2, body_l / 2) + courtyard_excess, 0.05)
    cy = r(max(pad_y / 2, body_w / 2) + courtyard_excess, 0.05)
    fp["tracks"] += rect_tracks(-cx, -cy, cx, cy, CRTYD_W, "Top Courtyard")
    fp["text"] = [{"x": 0, "y": 0, "text": ".Designator", "height": min(0.5, body_w * 0.5),
                   "layer": "Top Assembly", "justification": "middle_center", "stroke_width": 0.05}]
    if with_body:
        fp["component_bodies"] = [{
            "overall_height": height, "standoff_height": 0.0, "layer": "Top 3D Body",
            "outline": [{"x": -body_l / 2, "y": -body_w / 2}, {"x": body_l / 2, "y": -body_w / 2},
                        {"x": body_l / 2, "y": body_w / 2}, {"x": -body_l / 2, "y": body_w / 2}],
        }]
    if step_model:
        fp["step_model"] = step_model
    return fp


def soic_footprint(name, pins, pitch, pad_x, pad_y, row_c, body_x, body_y, height, standoff,
                   description="", courtyard_excess=0.25):
    """Dual-row gull-wing. Pin 1 top-left, counter-clockwise numbering (seen from top)."""
    n = pins // 2
    hx = row_c / 2
    ys = [r((n - 1) / 2 * pitch - i * pitch, 0.0001) for i in range(n)]
    pads = []
    for i, y in enumerate(ys):  # left column, top -> bottom: 1..n
        pads.append({"designator": str(i + 1), "x": -hx, "y": y, "width": pad_x, "height": pad_y,
                     "shape": "rectangle" if i == 0 else "rounded_rectangle",
                     "corner_radius_percent": 0 if i == 0 else 25, "layer": "Top Layer"})
    for i, y in enumerate(reversed(ys)):  # right column, bottom -> top: n+1..2n
        pads.append({"designator": str(n + i + 1), "x": hx, "y": y, "width": pad_x, "height": pad_y,
                     "shape": "rounded_rectangle", "corner_radius_percent": 25, "layer": "Top Layer"})
    bx, by = body_x / 2, body_y / 2
    pad_top = ys[0] + pad_y / 2
    sy = r(max(by, pad_top + 0.15 + SILK_W / 2) + SILK_W / 2, 0.01)
    pin1_outer = -(hx + pad_x / 2)
    tracks = [
        # top silk line extended to the outer edge of pin 1 (pin-1 indicator)
        {"x1": r(pin1_outer, 0.01), "y1": sy, "x2": bx, "y2": sy, "width": SILK_W, "layer": "Top Overlay"},
        {"x1": -bx, "y1": -sy, "x2": bx, "y2": -sy, "width": SILK_W, "layer": "Top Overlay"},
    ]
    ch = min(1.0, bx * 0.5)
    tracks += poly_tracks([(-bx + ch, by), (bx, by), (bx, -by), (-bx, -by), (-bx, by - ch)], ASSY_W, "Top Assembly")
    cx = r(max(hx + pad_x / 2, bx) + courtyard_excess, 0.05)
    cy = r(max(pad_top, by) + courtyard_excess, 0.05)
    tracks += rect_tracks(-cx, -cy, cx, cy, CRTYD_W, "Top Courtyard")
    return {
        "name": name,
        "description": description,
        "pads": pads,
        "tracks": tracks,
        "arcs": [{"x": r(-bx + 0.6), "y": r(by - 0.6), "radius": 0.2, "start_angle": 0, "end_angle": 360,
                  "width": ASSY_W, "layer": "Top Assembly"}],
        "text": [{"x": 0, "y": 0, "text": ".Designator", "height": 0.8, "layer": "Top Assembly",
                  "justification": "middle_center", "stroke_width": 0.1}],
        "component_bodies": [{
            "overall_height": height, "standoff_height": standoff, "layer": "Top 3D Body",
            "outline": [{"x": -bx, "y": -by}, {"x": bx, "y": -by}, {"x": bx, "y": by}, {"x": -bx, "y": by}],
        }],
    }


def header_1xn_tht(name, n, pitch=2.54, pad=1.7, drill=1.0, body_w=2.54, height=2.54, description=""):
    """Straight 1xN pin header, origin at body centre, pin 1 left (square pad)."""
    x0 = -(n - 1) * pitch / 2
    pads = []
    for i in range(n):
        pads.append({"designator": str(i + 1), "x": r(x0 + i * pitch, 0.0001), "y": 0,
                     "width": pad, "height": pad, "shape": "rectangle" if i == 0 else "round",
                     "hole_size": drill, "is_plated": True, "layer": "Multi-Layer"})
    bx, by = n * pitch / 2, body_w / 2
    sx, sy = r(bx + 0.08, 0.01), r(by + 0.08, 0.01)
    cx, cy = r(bx + 0.25, 0.05), r(by + 0.25, 0.05)
    tracks = rect_tracks(-sx, -sy, sx, sy, 0.15, "Top Overlay")
    tracks += rect_tracks(-bx, -by, bx, by, ASSY_W, "Top Assembly")
    tracks += rect_tracks(-cx, -cy, cx, cy, CRTYD_W, "Top Courtyard")
    return {
        "name": name,
        "description": description,
        "pads": pads,
        "tracks": tracks,
        "text": [{"x": 0, "y": 0, "text": ".Designator", "height": 1.0, "layer": "Top Assembly",
                  "justification": "middle_center", "stroke_width": 0.1}],
        "component_bodies": [{
            "overall_height": height, "standoff_height": 0, "layer": "Top 3D Body",
            "outline": [{"x": -bx, "y": -by}, {"x": bx, "y": -by}, {"x": bx, "y": by}, {"x": -bx, "y": by}],
        }],
    }
