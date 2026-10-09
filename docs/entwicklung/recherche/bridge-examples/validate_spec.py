"""Faithful Python port of the field handling in altium-mcp's DelphiScript batch
parsers (schematic_utils.pas CreateSymbolsBatch/CreateSchematicSymbol and
pcb_utils.pas CreateFootprintsBatch). It does NOT talk to Altium. It flags every
value that would make StrToInt/StrToFloat raise inside Altium (which can leave
the script paused in the debugger) and prints what each record turns into.

Usage: python -I validate_spec.py symbols|footprints <spec_file>
"""
import re
import sys

INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
ELEC = {"eElectricHiZ", "eElectricInput", "eElectricIO", "eElectricOpenCollector",
        "eElectricOpenEmitter", "eElectricOutput", "eElectricPassive", "eElectricPower"}
ORIENT = {"eRotate0": 0, "eRotate90": 90, "eRotate180": 180, "eRotate270": 270}
STRING2LAYER_SEEN_ON_AD22 = {  # names proven by the GetPCBLayers dump on this machine
    "Top Overlay", "Bottom Overlay", "Top Solder Mask", "Bottom Solder Mask",
    "Top Paste", "Bottom Paste", "Drill Guide", "Drill Drawing", "Multi Layer",
    "Keep Out Layer"}


def field(s, i):
    """GetFieldFromPipeString: i-th (0-based) '|' field or ''."""
    parts = s.split("|")
    return parts[i] if i < len(parts) else ""


class Checker:
    def __init__(self):
        self.errors = []

    def int_(self, v, where):
        if not INT_RE.match(v):
            self.errors.append(f"{where}: StrToInt({v!r}) would raise")
            return 0
        return int(v)

    def float_(self, v, where):
        if not FLOAT_RE.match(v):
            self.errors.append(f"{where}: StrToFloat({v!r}) would raise")
            return 0.0
        return float(v)


def check_symbol(name, desc, part_count, pins, graphics, c):
    where = f"SYMBOL {name}"
    for p in pins:
        v = field(p, 6).strip()
        if v:
            part_count = max(part_count, c.int_(v, where + " pin owner"))
    for g in graphics:
        v = field(g, 1).strip()
        if v:
            part_count = max(part_count, c.int_(v, where + " graphic part"))
    for p in pins:  # bounding-box pass
        x = field(p, 4).strip()
        if not x:
            continue
        c.int_(x, where + " pin x")
        c.int_(field(p, 5).strip(), where + " pin y")
    for g in graphics:
        e = g.strip()
        if not e:
            continue
        gtype = field(e, 0).strip().lower()
        v = field(e, 1).strip()
        if v:
            c.int_(v, where + f" {gtype} part")
        v = field(e, 2).strip()
        if v:  # NOTE: for 'label' this is the X coordinate
            c.int_(v, where + f" {gtype} field2(width or label x)")
        fl = lambda i: c.float_(field(e, i), where + f" {gtype} f{i}")
        if gtype == "line":
            [fl(i) for i in range(3, 7)]
        elif gtype in ("polyline", "polygon"):
            start = 3 if gtype == "polyline" else 4
            n = 0
            while field(e, start + n).strip():
                n += 1
            if n % 2:
                c.errors.append(f"{where} {gtype}: odd coordinate count, last value dropped")
            [fl(start + k) for k in range(n - n % 2)]
        elif gtype == "rectangle":
            [fl(i) for i in range(4, 8)]
        elif gtype == "arc":
            [fl(i) for i in range(3, 8)]
        elif gtype == "elliptical_arc":
            [fl(i) for i in range(3, 9)]
        elif gtype == "ellipse":
            [fl(i) for i in range(4, 8)]
        elif gtype == "label":
            fl(2), fl(3)
        else:
            c.errors.append(f"{where}: unknown graphic type {gtype!r} silently ignored")
    out = []
    for p in pins:
        y = field(p, 5).strip()
        if not y:
            c.errors.append(f"{where}: pin without y silently skipped: {p!r}")
            continue
        num, pname = field(p, 0).strip(), field(p, 1)
        etype, orient = field(p, 2).strip(), field(p, 3).strip()
        if etype not in ELEC:
            c.errors.append(f"{where} pin {num}: unknown type {etype!r} -> eElectricPassive")
        if orient not in ORIENT:
            c.errors.append(f"{where} pin {num}: unknown orientation {orient!r} -> eRotate0")
        x, yy = c.int_(field(p, 4).strip(), where), c.int_(y, where)
        length = field(p, 7).strip()
        length = c.float_(length, where + " pin length") if length else 300.0  # repo docstring default
        ang = ORIENT.get(orient, 0)
        dx, dy = {0: (1, 0), 90: (0, 1), 180: (-1, 0), 270: (0, -1)}[ang]
        out.append(f"    pin {num:>3} {pname!r:12} {etype:22} base=({x},{yy}) "
                   f"hotspot~({x + dx * length:.0f},{yy + dy * length:.0f}) [assumes Location=body end]")
    print(f"SYMBOL {name!r} desc={desc!r} part_count={part_count} pins={len(pins)} graphics={len(graphics)}")
    print("\n".join(out))


def run_symbols(path, c):
    lines = open(path, encoding="cp1252").read().splitlines()
    cur = None
    for ln in lines:
        kind = field(ln, 0).strip().upper()
        if kind == "LIBRARY":
            print(f"LIBRARY -> open/focus {field(ln, 1).strip()!r} only if the file EXISTS (else silently ignored)")
        elif kind == "SYMBOL":
            if cur:
                check_symbol(*cur, c)
            pc = field(ln, 3).strip()
            cur = [field(ln, 1).strip(), field(ln, 2), c.int_(pc, "SYMBOL part_count") if pc else 1, [], []]
        elif kind == "PIN":
            if cur:
                cur[3].append(ln[4:])
        elif kind == "GRAPHIC":
            if cur:
                cur[4].append(ln[8:])
    if cur:
        check_symbol(*cur, c)


def run_footprints(path, c):
    lines = open(path, encoding="cp1252").read().splitlines()
    have_fp = False
    layers = set()
    for n, ln in enumerate(lines, 1):
        kind = field(ln, 0).strip().upper()
        w = f"line {n} {kind}"
        F = lambda i: c.float_(field(ln, i).strip(), w + f" f{i}")
        I = lambda i: c.int_(field(ln, i).strip(), w + f" f{i}")
        L = lambda i: layers.add(field(ln, i).strip())
        if kind == "FPLIB":
            print(f"FPLIB -> open/focus {field(ln, 1)!r} (NOT trimmed) only if the file EXISTS")
        elif kind == "FOOTPRINT":
            have_fp = True
            print(f"FOOTPRINT {field(ln, 1).strip()!r} desc={field(ln, 2)!r}")
        elif not have_fp:
            continue
        elif kind == "PAD":
            mode = field(ln, 15).strip()
            if mode:
                I(15)
            [F(i) for i in (2, 3, 7, 9, 10, 11, 12)]
            L(5)
            I(8), I(13)
            if field(ln, 14).strip():
                I(14)
            if mode and mode != "0":
                [F(i) for i in (16, 17, 19, 20)]
                I(18), I(21)
            F(4)
            print(f"    pad {field(ln, 1)!r} at ({field(ln, 2)},{field(ln, 3)}) layer={field(ln, 5)!r} "
                  f"hole={field(ln, 7)} type={field(ln, 8)} size={field(ln, 11)}x{field(ln, 12)} shape={field(ln, 13)}")
        elif kind == "TRACK":
            [F(i) for i in range(1, 6)], L(6)
        elif kind == "ARC":
            [F(i) for i in range(1, 7)], L(7)
        elif kind == "FILL":
            [F(i) for i in range(1, 6)], L(6)
        elif kind == "VIA":
            [F(i) for i in range(1, 5)], L(5), L(6)
        elif kind == "REGION":
            L(1), I(2)
            v = 3
            while field(ln, v).strip():
                F(v), F(v + 1)
                v += 2
        elif kind == "TEXT":
            [F(i) for i in (1, 2, 3, 4, 5)], L(6)
    unproven = sorted(l for l in layers if l not in STRING2LAYER_SEEN_ON_AD22)
    print("layers used:", sorted(layers))
    print("layer names NOT yet proven as String2Layer input on this AD22:", unproven)


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    chk = Checker()
    (run_symbols if mode == "symbols" else run_footprints)(path, chk)
    print("ERRORS:" if chk.errors else "no parser errors", *chk.errors, sep="\n  ")
