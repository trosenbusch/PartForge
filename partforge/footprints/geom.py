"""Small 2D geometry helpers for footprint building and checking (mm, +Y up)."""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from ..geometry.model import Pad, Point

Rect = tuple[float, float, float, float]  # x1, y1, x2, y2 with x1 <= x2, y1 <= y2
XY = tuple[float, float]
Segment = tuple[XY, XY]

EPS = 1e-6


def r6(v: float) -> float:
    """Round to 1e-6 mm and normalise -0.0 (removes float noise in the output)."""
    v = round(v, 6)
    return 0.0 if v == 0 else v


# --------------------------------------------------------------------------- rectangles


def rect(x1: float, y1: float, x2: float, y2: float) -> Rect:
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def rect_centered(cx: float, cy: float, w: float, h: float) -> Rect:
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def rect_union(rects: Iterable[Rect]) -> Rect | None:
    out: Rect | None = None
    for r in rects:
        out = r if out is None else (min(out[0], r[0]), min(out[1], r[1]), max(out[2], r[2]), max(out[3], r[3]))
    return out


def rect_inflate(r: Rect, d: float) -> Rect:
    return (r[0] - d, r[1] - d, r[2] + d, r[3] + d)


def rect_contains(outer: Rect, inner: Rect, eps: float = EPS) -> bool:
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps
            and outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


def rect_points(r: Rect) -> list[XY]:
    return [(r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])]


def bbox_points(points: Iterable[XY]) -> Rect | None:
    pts = list(points)
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- pads


def pad_polygon(p: Pad) -> list[XY]:
    """Conservative copper outline of a pad (bounding rectangle, rotation applied)."""
    hw, hh = p.width / 2, p.height / 2
    a = math.radians(p.rotation or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    return [(p.x + x * ca - y * sa, p.y + x * sa + y * ca) for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def pad_bbox(p: Pad) -> Rect:
    b = bbox_points(pad_polygon(p))
    assert b is not None
    return b


# --------------------------------------------------------------------------- distances


def dist_point_segment(p: XY, a: XY, b: XY) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    if ll <= 0:
        return math.hypot(p[0] - ax, p[1] - ay)
    t = max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / ll))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _orient(a: XY, b: XY, c: XY) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def segments_intersect(a: XY, b: XY, c: XY, d: XY) -> bool:
    """Proper crossing (touching/collinear cases are covered by the point distances)."""
    d1, d2 = _orient(c, d, a), _orient(c, d, b)
    d3, d4 = _orient(a, b, c), _orient(a, b, d)
    return d1 * d2 < 0 and d3 * d4 < 0


def dist_segment_segment(a: XY, b: XY, c: XY, d: XY) -> float:
    if segments_intersect(a, b, c, d):
        return 0.0
    return min(dist_point_segment(a, c, d), dist_point_segment(b, c, d),
               dist_point_segment(c, a, b), dist_point_segment(d, a, b))


def point_in_polygon(p: XY, poly: Sequence[XY]) -> bool:
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def dist_point_polygon(p: XY, poly: Sequence[XY]) -> float:
    """0 if inside, else distance to the outline."""
    if point_in_polygon(p, poly):
        return 0.0
    n = len(poly)
    return min(dist_point_segment(p, poly[i], poly[(i + 1) % n]) for i in range(n))


def dist_segment_polygon(a: XY, b: XY, poly: Sequence[XY]) -> float:
    if point_in_polygon(a, poly) or point_in_polygon(b, poly):
        return 0.0
    n = len(poly)
    return min(dist_segment_segment(a, b, poly[i], poly[(i + 1) % n]) for i in range(n))


def dist_polygon_polygon(p: Sequence[XY], q: Sequence[XY]) -> float:
    if any(point_in_polygon(v, q) for v in p) or any(point_in_polygon(v, p) for v in q):
        return 0.0
    best = math.inf
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        for j in range(len(q)):
            best = min(best, dist_segment_segment(a, b, q[j], q[(j + 1) % len(q)]))
            if best == 0:
                return 0.0
    return best


def dist_point_rect(p: XY, r: Rect) -> float:
    dx = max(r[0] - p[0], 0.0, p[0] - r[2])
    dy = max(r[1] - p[1], 0.0, p[1] - r[3])
    return math.hypot(dx, dy)


def rects_overlap(a: Rect, b: Rect, margin: float = 0.0) -> bool:
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or a[3] + margin < b[1] or b[3] + margin < a[1])


# --------------------------------------------------------------------------- clipping


def _inside_interval(p1: XY, p2: XY, r: Rect) -> tuple[float, float] | None:
    """Parameter interval [t0, t1] of segment p1->p2 strictly inside the open rectangle (Liang-Barsky)."""
    x1, y1, x2, y2 = r[0] + EPS, r[1] + EPS, r[2] - EPS, r[3] - EPS
    if x1 >= x2 or y1 >= y2:
        return None
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    t0, t1 = 0.0, 1.0
    for pk, qk in ((-dx, p1[0] - x1), (dx, x2 - p1[0]), (-dy, p1[1] - y1), (dy, y2 - p1[1])):
        if abs(pk) < 1e-15:
            if qk < 0:
                return None
            continue
        t = qk / pk
        if pk < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return None
    return (t0, t1) if t1 - t0 > 1e-12 else None


def clip_segment_outside(p1: XY, p2: XY, keepouts: Sequence[Rect], min_len: float = 0.0) -> list[Segment]:
    """Parts of the segment outside all keep-out rectangles (shorter than ``min_len`` dropped)."""
    intervals: list[tuple[float, float]] = [(0.0, 1.0)]
    for r in keepouts:
        cut = _inside_interval(p1, p2, r)
        if cut is None:
            continue
        nxt: list[tuple[float, float]] = []
        for a, b in intervals:
            if cut[1] <= a or cut[0] >= b:
                nxt.append((a, b))
                continue
            if cut[0] > a:
                nxt.append((a, cut[0]))
            if cut[1] < b:
                nxt.append((cut[1], b))
        intervals = nxt
        if not intervals:
            break
    length = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    out: list[Segment] = []
    for a, b in intervals:
        if (b - a) * length + 1e-9 < min_len or (b - a) * length < 1e-6:
            continue
        out.append(((p1[0] + (p2[0] - p1[0]) * a, p1[1] + (p2[1] - p1[1]) * a),
                    (p1[0] + (p2[0] - p1[0]) * b, p1[1] + (p2[1] - p1[1]) * b)))
    return out


# --------------------------------------------------------------------------- polygons


def circle_points(cx: float, cy: float, r: float, n: int = 32, start: float = 0.0, end: float = 360.0) -> list[XY]:
    """Points on a circle/arc (CCW, degrees). Full circles do not repeat the first point."""
    full = abs((end - start) % 360) < 1e-9 and end != start
    count = n if full else max(2, math.ceil(n * abs(end - start) / 360.0) + 1)
    pts: list[XY] = []
    for i in range(count):
        a = math.radians(start + (end - start) * i / (count if full else count - 1))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def polygon_area(pts: Sequence[XY]) -> float:
    n = len(pts)
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def to_points(pts: Iterable[XY]) -> list[Point]:
    return [Point(x=r6(x), y=r6(y)) for x, y in pts]


def from_points(pts: Iterable[Point]) -> list[XY]:
    return [(p.x, p.y) for p in pts]
