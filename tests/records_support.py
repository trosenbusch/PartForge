"""Builders for synthetic Altium library records (PcbLib footprints, SchLib symbols) – no writer needed.

``PAD_RECORD`` is a complete SMD pad record written by PartForge's own Rust library writer (captured once from a
generated 0.8 × 0.9 mm pad); :func:`pad` copies it and sets designator, centre and size. Tracks and texts come
from :func:`partforge.altium.pcbrecords.new_track` / :func:`~partforge.altium.pcbrecords.new_text`.
"""
from __future__ import annotations

import struct
from collections.abc import Iterable, Sequence

from partforge.altium import pcbrecords as R
from partforge.altium import schrecords as S
from partforge.altium.rustwriter import STROKE_CHAR_ADVANCE, truetype_text_box

PAD_RECORD = bytes.fromhex(
    "02020000000131010000000005000000047c267c300100000000ca000000010c00ffffffffffffffffffff947efbff0000000051ce04"
    "001b68050051ce04001b68050051ce04001b6805000000000001010100000000000000000100000000000000a08601000400a0860100"
    "400d0300400d03000000000000000000000000000000000000000000000000000000000001000001000000409c000000be3bd7e345bc"
    "4708aa5adf2d7ceee8a1a128ef32ebcf4e07955db341be8714ff00000000ffffff7fffffff7f00011a00000000000000000000000103"
    "000000000000000000000000000000008b02000051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce"
    "040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce040051ce0400"
    "51ce040051ce040051ce040051ce040051ce040051ce040051ce04001b6805001b6805001b6805001b6805001b6805001b6805001b68"
    "05001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b680500"
    "1b6805001b6805001b6805001b6805001b6805001b6805001b6805001b6805001b680500010101010101010101010101010101010101"
    "010101010101010101010100000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "000000000000000000000001090909090909090909090909090909090909090909090909090909090909090932323232323232323232"
    "323232323232323232323232323232323232323232320000000000000000000000000000000000000000000000000000000000000000"
    "010000000f000000040080010951ce04001b6805003200"
)


# --------------------------------------------------------------------------- PcbLib


def footprint(name: str, primitives: Iterable[R.Primitive] = ()) -> R.FootprintRecords:
    """``<footprint>/Data`` records: the name prefix (u32 length + pascal name) and ``primitives``."""
    raw = name.encode("cp1252")
    prefix = struct.pack("<I", len(raw) + 1) + bytes([len(raw)]) + raw
    return R.FootprintRecords(prefix=prefix, name=name, primitives=list(primitives))


def pad(designator: str, x: float, y: float, width: float = 0.8, height: float = 0.9) -> R.Primitive:
    """SMD pad (copy of :data:`PAD_RECORD`) with designator, centre and top size in mm."""
    record = R.parse_footprint(footprint("X").prefix + PAD_RECORD).primitives[0]
    raw = designator.encode("cp1252")
    record.blocks[0] = bytearray(bytes([len(raw)]) + raw)
    geometry = record.blocks[4]
    struct.pack_into("<iiii", geometry, 13, R.units(x), R.units(y), R.units(width), R.units(height))
    return record


def track(layer: str, x1: float, y1: float, x2: float, y2: float, width: float = 0.1) -> R.Primitive:
    return R.new_track(layer, x1, y1, x2, y2, width)


def rect(layer: str, x1: float, y1: float, x2: float, y2: float, width: float = 0.1) -> list[R.Primitive]:
    """Closed outline of four tracks."""
    return [
        track(layer, x1, y1, x2, y1, width),
        track(layer, x2, y1, x2, y2, width),
        track(layer, x2, y2, x1, y2, width),
        track(layer, x1, y2, x1, y1, width),
    ]


def text(layer: str, content: str, *, x: float = 0.0, y: float = 0.0, height: float = 1.0,
         font: str = "stroke", font_name: str = "Arial") -> R.Primitive:
    """Text whose box (as Altium measures it) is centred on (x, y)."""
    if font == "truetype":
        width, box_height = truetype_text_box(content, height, font_name)
    else:
        width, box_height = len(content) * STROKE_CHAR_ADVANCE * height, height
    return R.new_text(layer, content, x=x - width / 2, y=y - box_height / 2, height=height,
                      stroke_width=0.15 * height, font=font, font_name=font_name,  # type: ignore[arg-type]
                      box=(width, box_height))


def chip(name: str = "CHIP", *, assembly: str = "Mechanical 13", courtyard: str = "Mechanical 15",
         texts_on: str | None = "Mechanical 13", width: float = 0.05) -> R.FootprintRecords:
    """A 0603-like chip footprint drawn the way foreign libraries do it: assembly outline and courtyard on the
    given layers, ``.Designator``/``.Comment`` on ``texts_on`` (``None`` = no texts), no centre cross."""
    prims: list[R.Primitive] = [pad("1", -0.75, 0.0), pad("2", 0.75, 0.0)]
    prims += rect(assembly, -0.8, -0.4, 0.8, 0.4, width)
    prims += rect(courtyard, -1.45, -0.75, 1.45, 0.75, width)
    if texts_on:
        prims.append(text(texts_on, ".Designator", height=0.5))
        prims.append(text(texts_on, ".Comment", height=0.5))
    return footprint(name, prims)


# --------------------------------------------------------------------------- SchLib


def text_record(**fields: str | int) -> S.SchRecord:
    """Text record ``|KEY=VALUE|…`` + NUL (keys in the given order, ``RECORD`` first)."""
    body = b"".join(b"|" + key.encode("ascii") + b"=" + str(value).encode("cp1252") for key, value in fields.items())
    return S.SchRecord(binary=False, payload=bytearray(body + b"\x00"))


def pin_record(designator: str, name: str, *, x: int, y: int, length: int = 20, orientation: str = "left",
               part: int = 1, color: int = 0, show_name: bool = True, show_designator: bool = True) -> S.SchRecord:
    """Binary pin record (RECORD 2) in schematic units (1 = 10 mil); ``(x, y)`` is the end at the body."""
    flags = ("right", "up", "left", "down").index(orientation)
    flags |= 0x08 if show_name else 0
    flags |= 0x10 if show_designator else 0
    payload = bytearray(struct.pack("<I", 2))
    payload += b"\x00" + struct.pack("<h", part) + b"\x00"  # unknown byte, owner part, display mode
    payload += b"\x00\x00\x00\x00"  # inner/outer edges
    payload += b"\x00"  # empty description
    payload += bytes([0, 4, flags]) + struct.pack("<hhhI", length, x, y, color)  # formal, electrical (passive), flags
    raw_name, raw_designator = name.encode("cp1252"), designator.encode("cp1252")
    payload += bytes([len(raw_name)]) + raw_name + bytes([len(raw_designator)]) + raw_designator
    payload += b"\x03|&|"  # swap ids as Altium writes them
    return S.SchRecord(binary=True, payload=payload, flags=1)


def box_symbol(name: str = "IC1", *, pins: int = 4, length: int = 20, prefix: str = "IC?", font_id: int = 1,
               pin_color: int = 0) -> list[S.SchRecord]:
    """IC-like symbol: component, rectangle 0..40 × -(rows+1)*10..0, pins on its left/right edges, designator,
    comment and a parameter (all texts in font ``font_id``)."""
    half = (pins + 1) // 2
    records = [
        text_record(RECORD=1, LibReference=name, PartCount=2, DisplayModeCount=1, CurrentPartId=1),
        text_record(RECORD=14, OwnerPartId=1, **{"Location.X": 0, "Location.Y": -(half + 1) * 10, "Corner.X": 40,
                                                "Corner.Y": 0}, Color=128, AreaColor=11599871),
    ]
    for i in range(pins):
        left = i < half
        row = i if left else i - half
        records.append(pin_record(str(i + 1), f"P{i + 1}", x=0 if left else 40, y=-10 - row * 10, length=length,
                                  orientation="left" if left else "right", color=pin_color))
    records += [
        text_record(RECORD=34, OwnerPartId=-1, FontID=font_id, Text=prefix, Name="Designator"),
        text_record(RECORD=41, OwnerPartId=-1, FontID=font_id, Text="*", Name="Comment"),
        text_record(RECORD=41, OwnerPartId=-1, FontID=font_id, Text="ACME", Name="Manufacturer"),
    ]
    return records


def file_header(fonts: Sequence[S.SchFont] = (S.SchFont(),), components: Sequence[str] = ("IC1",)) -> bytes:
    """``FileHeader`` of a SchLib with the given font table and component list."""
    segments = [b"", b"HEADER=Protel for Windows - Schematic Library Editor Binary File Version 5.0", b"Weight=10",
                b"MinorVersion=9"]
    header = S.FileHeader(segments=segments)
    header.set_fonts(list(fonts))
    header.segments += [b"UseMBCS=T", b"IsBOC=T", f"CompCount={len(components)}".encode("ascii")]
    for i, comp in enumerate(components):
        header.segments.append(f"LibRef{i}={comp}".encode("cp1252"))
    return header.to_bytes()
