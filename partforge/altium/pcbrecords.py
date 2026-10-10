"""Raw footprint records of a PcbLib: read and edit primitives losslessly, without the library writer.

The Rust writer re-serialises whole libraries and reads primitives on Mechanical 17–32 that Altium saved
as "Mechanical 16" (Altium stores them with the legacy layer byte 72 plus the real V7 layer id, see
``recherche/user-lib-style.md`` §5). Converting imported footprints to the house style therefore works on
the records themselves: :func:`parse_footprint` splits the ``<footprint>/Data`` stream into
:class:`Primitive` records, the accessors decode the fields PartForge needs, the setters change exactly
those bytes, and :meth:`FootprintRecords.to_bytes` writes the stream back – every byte PartForge does not
touch stays as it was (round trip identical, tested).

Record layout (VERIFIED on Altium 26.10 files and on files of the Rust writer):

* ``Data`` = u32 length + Pascal string (name), then records: type byte + blocks (u32 length + bytes).
  Blocks per type: arc 1, pad 6, via 1, track 1, text 2 (properties, Pascal string), fill 1, region 1,
  component body 1 (:data:`BLOCK_COUNTS`).
* Every property block starts with the V6 layer byte; tracks, arcs, fills, texts and vias carry the V7
  layer id at a fixed offset (:data:`V7_OFFSETS`), regions and bodies a ``V7_LAYER=…`` key in their
  property text (u32 length at byte 18, text at 22). Altium writes Mechanical 17–32 as byte 72 + V7 id,
  the Rust writer as byte 186–201 + V7 id – both are read correctly here (:func:`layer_of`), new values
  are written the way Altium does (:func:`layer_codes`).
* Coordinates are i32 in 1/10000 mil (:data:`UNITS_PER_MM`); track x1/y1/x2/y2/width at 13/17/21/25/29;
  arc centre 13/17, radius 21, start/end angle (double) 25/33, width 41; fill x1/y1/x2/y2 13–25 and
  rotation (double) 29; text position 13/17, height 21, stroke font 25, rotation (double) 27, mirror 35,
  stroke width 36, font kind 43 (0 stroke, 1 TrueType, 2 barcode), bold 44, italic 45, TrueType font
  name 46–109 (UTF-16, NUL-terminated), WideStrings index 115, text box width/height 124/128 (the extent
  Altium measured; the stored position is the lower left corner of that box).

Per footprint, ``<footprint>/Header`` holds the primitive count, ``PrimitiveGuids/Data`` one 24-byte entry
(object kind, primitive index, GUID) per primitive plus the component itself, and
``UniqueIDPrimitiveInformation/Data`` ``|PRIMITIVEINDEX=…|`` records for pads; :func:`insert_primitives`
keeps all of them consistent when it adds records (e.g. a missing ``.Designator``).
"""
from __future__ import annotations

import math
import re
import struct
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from . import layers as L

__all__ = [
    "PcbRecordError",
    "PrimitiveKind",
    "Primitive",
    "FootprintRecords",
    "BLOCK_COUNTS",
    "KIND_CODES",
    "UNITS_PER_MM",
    "MECH_V7_BASE",
    "V7_FIXED",
    "layer_of",
    "layer_codes",
    "parse_footprint",
    "mm",
    "units",
    "new_track",
    "new_text",
    "insert_primitives",
    "guid_entries",
    "build_guid_stream",
    "count_stream",
    "NON_FOOTPRINT_STORAGES",
    "JSON_KINDS",
    "read_footprints",
    "correct_layers",
]


class PcbRecordError(ValueError):
    """A footprint stream does not have the expected record structure (German message)."""


PrimitiveKind = Literal["arc", "pad", "via", "track", "text", "fill", "region", "body"]

KIND_CODES: Final[dict[int, PrimitiveKind]] = {
    1: "arc", 2: "pad", 3: "via", 4: "track", 5: "text", 6: "fill", 11: "region", 12: "body",
}
CODE_OF: Final[dict[str, int]] = {kind: code for code, kind in KIND_CODES.items()}
BLOCK_COUNTS: Final[dict[int, int]] = {1: 1, 2: 6, 3: 1, 4: 1, 5: 2, 6: 1, 11: 1, 12: 1}
#: Object kind of the ``PrimitiveGuids`` entries (85 = the component itself, 90 = component body).
GUID_KINDS: Final[dict[str, int]] = {
    "arc": 1, "pad": 2, "via": 3, "track": 4, "text": 5, "fill": 6, "region": 11, "body": 90,
}
COMPONENT_GUID_KIND: Final = 85

#: Byte offset of the V7 layer id in the first block (types with a fixed binary layout).
V7_OFFSETS: Final[dict[str, int]] = {"track": 41, "arc": 52, "fill": 42, "text": 226, "via": 203}
#: 1 mm in Altium's internal unit (1/10000 mil).
UNITS_PER_MM: Final = 1.0 / 0.00000254
MECH_V7_BASE: Final = 0x01020000
MECH_LEGACY_BASE: Final = 56  # V6 byte of Mechanical n (n <= 16) = 56 + n
MECH_LEGACY_LAST: Final = 72  # Altium stores Mechanical 17..32 with byte 72 (+ V7 id)
MECH_RUST_BASE: Final = 169  # Rust writer: Mechanical 17..32 = byte 186..201
#: V7 ids of the fixed layers PartForge moves primitives between (read from PcbLib headers).
V7_FIXED: Final[dict[str, int]] = {
    L.TOP_LAYER: 0x01000001,
    L.BOTTOM_LAYER: 0x0100FFFF,
    L.TOP_OVERLAY: 0x01030006,
    L.BOTTOM_OVERLAY: 0x01030007,
    L.TOP_PASTE: 0x01030008,
    L.BOTTOM_PASTE: 0x01030009,
    L.TOP_SOLDER: 0x0103000A,
    L.BOTTOM_SOLDER: 0x0103000B,
    L.MULTI_LAYER: 0x0103000F,
}
_V7_NAMES: Final[dict[int, str]] = {v: k for k, v in V7_FIXED.items()}
_V6_NAMES: Final[dict[int, str]] = {v: k for k, v in L.ALTIUM_LAYER_IDS.items()}
#: ``V7_LAYER=`` tokens of regions and bodies for the fixed layers.
_V7_TOKENS: Final[dict[str, str]] = {
    L.TOP_LAYER: "TOP", L.BOTTOM_LAYER: "BOTTOM", L.TOP_OVERLAY: "TOPOVERLAY", L.BOTTOM_OVERLAY: "BOTTOMOVERLAY",
    L.TOP_PASTE: "TOPPASTE", L.BOTTOM_PASTE: "BOTTOMPASTE", L.TOP_SOLDER: "TOPSOLDER", L.BOTTOM_SOLDER: "BOTTOMSOLDER",
    L.MULTI_LAYER: "MULTILAYER", L.KEEP_OUT: "KEEPOUT", L.DRILL_GUIDE: "DRILLGUIDE", L.DRILL_DRAWING: "DRILLDRAWING",
}
_TOKEN_NAMES: Final[dict[str, str]] = {v: k for k, v in _V7_TOKENS.items()}
_V7_KEY_RE: Final = re.compile(rb"(^|\|)V7_LAYER=([^|\x00]*)")
_MECH_TOKEN_RE: Final = re.compile(r"^MECHANICAL(\d{1,2})$")
_TEXT_MIN: Final = 230  # properties block of a text with V7 id and TrueType fields
_FONT_NAME_BYTES: Final = 64


def units(value_mm: float) -> int:
    """Millimetres -> internal units (rounded)."""
    return int(round(value_mm * UNITS_PER_MM))


def mm(value_units: float) -> float:
    """Internal units -> millimetres (rounded to 6 digits)."""
    return round(value_units / UNITS_PER_MM, 6)


# --------------------------------------------------------------------------- layers


def _mech_name(number: int) -> str | None:
    return f"Mechanical {number}" if 1 <= number <= L.MECHANICAL_LAYER_COUNT else None


def _from_v7(v7: int | None) -> str | None:
    if v7 is None:
        return None
    if MECH_V7_BASE < v7 <= MECH_V7_BASE + L.MECHANICAL_LAYER_COUNT:
        return _mech_name(v7 - MECH_V7_BASE)
    return _V7_NAMES.get(v7)


def _from_v6(byte: int) -> str | None:
    if MECH_LEGACY_BASE < byte <= MECH_LEGACY_LAST:
        return _mech_name(byte - MECH_LEGACY_BASE)
    if MECH_RUST_BASE + 17 <= byte <= MECH_RUST_BASE + L.MECHANICAL_LAYER_COUNT:
        return _mech_name(byte - MECH_RUST_BASE)
    if 2 <= byte <= 31:
        return f"Mid-Layer {byte - 1}"
    if 39 <= byte <= 54:
        return f"Internal Plane {byte - 38}"
    return _V6_NAMES.get(byte)


def _from_token(token: str | None) -> str | None:
    if not token:
        return None
    text = token.strip().upper()
    m = _MECH_TOKEN_RE.match(text)
    if m:
        return _mech_name(int(m.group(1)))
    return _TOKEN_NAMES.get(text)


def layer_of(v6: int, v7: int | None = None, token: str | None = None) -> str | None:
    """Canonical layer name (``Mechanical 17``, ``Top Overlay``) of a primitive.

    The V7 id (or the ``V7_LAYER`` token of regions/bodies) wins over the legacy byte – Altium stores
    Mechanical 17–32 with byte 72 ("Mechanical 16"). ``None`` = a layer PartForge does not model.
    """
    return _from_v7(v7) or _from_token(token) or _from_v6(v6)


def layer_codes(name: str) -> tuple[int, int, str]:
    """(V6 byte, V7 id, ``V7_LAYER`` token) Altium writes for a layer PartForge may move primitives to.

    Mechanical 1–32 and the fixed layers of :data:`V7_FIXED`; raises :class:`PcbRecordError` otherwise.
    """
    try:
        canonical = L.normalize_layer_name(name)
    except L.LayerError as exc:
        raise PcbRecordError(str(exc)) from exc
    number = L.mechanical_number(canonical)
    if number is not None:
        byte = MECH_LEGACY_BASE + number if number <= 16 else MECH_LEGACY_LAST
        return byte, MECH_V7_BASE + number, f"MECHANICAL{number}"
    if canonical in V7_FIXED and canonical in L.ALTIUM_LAYER_IDS:
        return L.ALTIUM_LAYER_IDS[canonical], V7_FIXED[canonical], _V7_TOKENS[canonical]
    raise PcbRecordError(f"Auf die Lage „{canonical}“ verschiebt PartForge keine Primitive.")


# --------------------------------------------------------------------------- primitives


def _i32(block: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<i", block, offset)[0]


def _u32(block: bytes | bytearray, offset: int) -> int:
    return struct.unpack_from("<I", block, offset)[0]


def _f64(block: bytes | bytearray, offset: int) -> float:
    return struct.unpack_from("<d", block, offset)[0]


@dataclass
class Primitive:
    """One record of a footprint (type code + raw blocks) with field accessors.

    ``blocks`` are mutable copies; setters change exactly the bytes of the field.
    """

    code: int
    blocks: list[bytearray]

    @property
    def kind(self) -> PrimitiveKind:
        return KIND_CODES[self.code]

    @property
    def props(self) -> bytearray:
        """The property block (pads: the fifth block, which starts with the layer byte)."""
        return self.blocks[4] if self.kind == "pad" else self.blocks[0]

    def to_bytes(self) -> bytes:
        out = bytearray([self.code])
        for block in self.blocks:
            out += struct.pack("<I", len(block)) + block
        return bytes(out)

    # -- layer --------------------------------------------------------------------------------------
    def _v7(self) -> int | None:
        offset = V7_OFFSETS.get(self.kind)
        block = self.props
        if offset is None or len(block) < offset + 4:
            return None
        value = _u32(block, offset)
        return value if 0x01000000 <= value < 0x01050000 else None

    def _property_text(self) -> tuple[int, bytes] | None:
        """(length, text) of the property string of regions/bodies (u32 at 18, text at 22)."""
        if self.kind not in ("region", "body"):
            return None
        block = self.blocks[0]
        if len(block) < 22:
            return None
        length = _u32(block, 18)
        if 22 + length > len(block):
            return None
        return length, bytes(block[22 : 22 + length])

    def _v7_token(self) -> str | None:
        found = self._property_text()
        if found is None:
            return None
        m = _V7_KEY_RE.search(found[1])
        return m.group(2).decode("ascii", "replace") if m else None

    @property
    def layer(self) -> str | None:
        """Canonical layer name (see :func:`layer_of`)."""
        block = self.props
        if not block:
            return None
        return layer_of(block[0], self._v7(), self._v7_token())

    def set_layer(self, name: str) -> None:
        """Move the primitive to ``name`` (V6 byte, V7 id and ``V7_LAYER`` – whatever the record has)."""
        if self.kind in ("pad", "via"):
            raise PcbRecordError("Pads und Durchkontaktierungen verschiebt PartForge nicht auf andere Lagen.")
        byte, v7, token = layer_codes(name)
        block = self.blocks[0]
        block[0] = byte
        offset = V7_OFFSETS.get(self.kind)
        if offset is not None and len(block) >= offset + 4 and self._v7() is not None:
            struct.pack_into("<I", block, offset, v7)
        found = self._property_text()
        if found is not None:
            length, text = found
            m = _V7_KEY_RE.search(text)
            if m:
                new_text = text[: m.start(2)] + token.encode("ascii") + text[m.end(2) :]
            else:  # no V7 key yet: Altium puts it first
                new_text = b"V7_LAYER=" + token.encode("ascii") + (b"|" if text and not text.startswith(b"\x00") else b"") + text
            block[18:22] = struct.pack("<I", len(new_text))
            block[22 : 22 + length] = new_text

    # -- geometry -----------------------------------------------------------------------------------
    def _check(self, *kinds: str) -> None:
        if self.kind not in kinds:
            raise PcbRecordError(f"Feld für {self.kind} nicht vorhanden.")

    @property
    def coords(self) -> tuple[float, float, float, float]:
        """Track/fill corner points x1, y1, x2, y2 (mm)."""
        self._check("track", "fill")
        b = self.blocks[0]
        return mm(_i32(b, 13)), mm(_i32(b, 17)), mm(_i32(b, 21)), mm(_i32(b, 25))

    def set_coords(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self._check("track", "fill")
        struct.pack_into("<iiii", self.blocks[0], 13, units(x1), units(y1), units(x2), units(y2))

    @property
    def width(self) -> float:
        """Line width of tracks (offset 29) and arcs (offset 41) in mm."""
        self._check("track", "arc")
        return mm(_i32(self.blocks[0], 29 if self.kind == "track" else 41))

    def set_width(self, value: float) -> None:
        self._check("track", "arc")
        struct.pack_into("<i", self.blocks[0], 29 if self.kind == "track" else 41, units(value))

    @property
    def arc(self) -> tuple[float, float, float, float, float]:
        """Arc centre x, y, radius (mm), start and end angle (degrees)."""
        self._check("arc")
        b = self.blocks[0]
        return mm(_i32(b, 13)), mm(_i32(b, 17)), mm(_i32(b, 21)), _f64(b, 25), _f64(b, 33)

    @property
    def rotation(self) -> float:
        self._check("fill", "text")
        return _f64(self.blocks[0], 29 if self.kind == "fill" else 27)

    # -- pad ----------------------------------------------------------------------------------------
    @property
    def pad_designator(self) -> str:
        self._check("pad")
        raw = bytes(self.blocks[0])
        return raw[1 : 1 + raw[0]].decode("cp1252", "replace") if raw else ""

    @property
    def pad_geometry(self) -> tuple[float, float, float, float, float]:
        """Pad centre x, y, top size x, y (mm) and rotation (degrees) from the main property block."""
        self._check("pad")
        b = self.blocks[4]
        if len(b) < 60:
            raise PcbRecordError("Pad-Datensatz ist zu kurz.")
        rotation = _f64(b, 52)
        if not math.isfinite(rotation):
            rotation = 0.0
        return mm(_i32(b, 13)), mm(_i32(b, 17)), mm(_i32(b, 21)), mm(_i32(b, 25)), rotation

    def pad_bounds(self) -> tuple[float, float, float, float]:
        x, y, w, h, rotation = self.pad_geometry
        r = math.radians(rotation)
        ex = abs(w / 2 * math.cos(r)) + abs(h / 2 * math.sin(r))
        ey = abs(w / 2 * math.sin(r)) + abs(h / 2 * math.cos(r))
        return x - ex, y - ey, x + ex, y + ey

    # -- text ---------------------------------------------------------------------------------------
    @property
    def text(self) -> str:
        """The (8-bit) text of a text record (``.Designator``, ``.Comment`` …)."""
        self._check("text")
        raw = bytes(self.blocks[1])
        if not raw:
            return ""
        length = raw[0]
        return raw[1 : 1 + length].decode("cp1252", "replace")

    @property
    def position(self) -> tuple[float, float]:
        self._check("text")
        b = self.blocks[0]
        return mm(_i32(b, 13)), mm(_i32(b, 17))

    def set_position(self, x: float, y: float) -> None:
        self._check("text")
        struct.pack_into("<ii", self.blocks[0], 13, units(x), units(y))

    @property
    def height(self) -> float:
        self._check("text")
        return mm(_i32(self.blocks[0], 21))

    def set_height(self, value: float) -> None:
        self._check("text")
        struct.pack_into("<i", self.blocks[0], 21, units(value))

    @property
    def stroke_width(self) -> float:
        self._check("text")
        return mm(_i32(self.blocks[0], 36))

    def set_stroke_width(self, value: float) -> None:
        self._check("text")
        struct.pack_into("<i", self.blocks[0], 36, units(value))

    def _text_extended(self) -> bool:
        return self.kind == "text" and len(self.blocks[0]) >= _TEXT_MIN

    @property
    def font_kind(self) -> Literal["stroke", "truetype", "barcode"]:
        self._check("text")
        if not self._text_extended():
            return "stroke"
        return {1: "truetype", 2: "barcode"}.get(self.blocks[0][43], "stroke")  # type: ignore[return-value]

    @property
    def font_name(self) -> str:
        """TrueType font name (also stored for stroke texts)."""
        self._check("text")
        if not self._text_extended():
            return ""
        raw = bytes(self.blocks[0][46 : 46 + _FONT_NAME_BYTES]).decode("utf-16-le", "replace")
        return raw.split("\x00", 1)[0]

    @property
    def bold(self) -> bool:
        return self._text_extended() and bool(self.blocks[0][44])

    @property
    def italic(self) -> bool:
        return self._text_extended() and bool(self.blocks[0][45])

    def set_font(self, kind: Literal["stroke", "truetype"], name: str | None = None, *, bold: bool = False,
                 italic: bool = False) -> None:
        """Font kind (stroke/TrueType), TrueType font name, bold/italic of an extended text record."""
        self._check("text")
        if not self._text_extended():
            raise PcbRecordError("Der Text ist in einem alten Format gespeichert – Schrift nicht änderbar.")
        b = self.blocks[0]
        b[43] = 1 if kind == "truetype" else 0
        b[44] = 1 if bold else 0
        b[45] = 1 if italic else 0
        if name is not None:
            encoded = name.encode("utf-16-le")[: _FONT_NAME_BYTES - 2]
            b[46 : 46 + _FONT_NAME_BYTES] = encoded + b"\x00" * (_FONT_NAME_BYTES - len(encoded))

    @property
    def text_box(self) -> tuple[float, float]:
        """Extent of the text Altium measured (mm, width/height; 0 if unknown)."""
        self._check("text")
        b = self.blocks[0]
        if not self._text_extended():
            return 0.0, 0.0
        return mm(max(0, _i32(b, 124))), mm(max(0, _i32(b, 128)))

    def set_text_box(self, width: float, height: float) -> None:
        self._check("text")
        if self._text_extended():
            struct.pack_into("<ii", self.blocks[0], 124, units(max(0.0, width)), units(max(0.0, height)))

    @property
    def widestring_index(self) -> int | None:
        self._check("text")
        if not self._text_extended():
            return None
        value = _u32(self.blocks[0], 115)
        return None if value == 0xFFFFFFFF else value

    def set_widestring_index(self, index: int | None) -> None:
        self._check("text")
        if self._text_extended():
            struct.pack_into("<I", self.blocks[0], 115, 0xFFFFFFFF if index is None else index)

    # -- region/body ------------------------------------------------------------------------------------
    def property_text(self) -> str:
        """``KEY=VALUE|…`` properties of regions and bodies (decoded, without the trailing NUL)."""
        found = self._property_text()
        return found[1].rstrip(b"\x00").decode("cp1252", "replace") if found else ""

    def properties(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for segment in self.property_text().split("|"):
            key, sep, value = segment.partition("=")
            if sep and key:
                out.setdefault(key.strip().upper(), value)
        return out

    def region_vertices(self) -> list[tuple[float, float]]:
        """Outline of a region (mm); empty if the record uses an unknown vertex layout."""
        found = self._property_text()
        if found is None or self.kind != "region":
            return []
        block = self.blocks[0]
        start = 22 + found[0]
        if len(block) < start + 4:
            return []
        count = _u32(block, start)
        if count <= 0 or len(block) < start + 4 + count * 16:
            return []
        return [
            (mm(_f64(block, start + 4 + i * 16)), mm(_f64(block, start + 12 + i * 16)))
            for i in range(count)
        ]

    def bounds(self) -> tuple[float, float, float, float] | None:
        """Bounding box (mm) of tracks, arcs, fills, texts (position only) and regions."""
        if self.kind in ("track", "fill"):
            x1, y1, x2, y2 = self.coords
            half = self.width / 2 if self.kind == "track" else 0.0
            return min(x1, x2) - half, min(y1, y2) - half, max(x1, x2) + half, max(y1, y2) + half
        if self.kind == "arc":
            cx, cy, r, _s, _e = self.arc
            return cx - r, cy - r, cx + r, cy + r
        if self.kind == "text":
            x, y = self.position
            w, h = self.text_box
            return x, y, x + w, y + h
        if self.kind == "region":
            pts = self.region_vertices()
            if pts:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                return min(xs), min(ys), max(xs), max(ys)
        return None


@dataclass
class FootprintRecords:
    """The ``<footprint>/Data`` stream: name prefix and primitive records (+ unparsed trailer)."""

    prefix: bytes
    name: str
    primitives: list[Primitive] = field(default_factory=list)
    trailer: bytes = b""

    def to_bytes(self) -> bytes:
        return self.prefix + b"".join(p.to_bytes() for p in self.primitives) + self.trailer

    def of_kind(self, *kinds: str) -> list[Primitive]:
        return [p for p in self.primitives if p.kind in kinds]


def parse_footprint(data: bytes) -> FootprintRecords:
    """Split a ``<footprint>/Data`` stream into its records (raises :class:`PcbRecordError`)."""
    if len(data) < 5:
        raise PcbRecordError("Footprint-Daten sind zu kurz.")
    (length,) = struct.unpack_from("<I", data, 0)
    if length < 1 or 4 + length > len(data):
        raise PcbRecordError("Footprint-Daten: ungültige Namenslänge.")
    prefix = data[: 4 + length]
    name_length = data[4]
    name = data[5 : 5 + min(name_length, length - 1)].decode("cp1252", "replace")
    primitives: list[Primitive] = []
    offset = 4 + length
    while offset < len(data):
        code = data[offset]
        if code == 0:  # end marker of older files: keep the rest verbatim
            break
        count = BLOCK_COUNTS.get(code)
        if count is None:
            raise PcbRecordError(f"Footprint {name}: unbekannter Datensatztyp {code} an Position {offset}.")
        cursor = offset + 1
        blocks: list[bytearray] = []
        for _ in range(count):
            if cursor + 4 > len(data):
                raise PcbRecordError(f"Footprint {name}: Datensatz an Position {offset} ist abgeschnitten.")
            (size,) = struct.unpack_from("<I", data, cursor)
            cursor += 4
            if cursor + size > len(data):
                raise PcbRecordError(f"Footprint {name}: Datensatz an Position {offset} ist abgeschnitten.")
            blocks.append(bytearray(data[cursor : cursor + size]))
            cursor += size
        primitives.append(Primitive(code, blocks))
        offset = cursor
    return FootprintRecords(prefix=prefix, name=name, primitives=primitives, trailer=data[offset:])


# --------------------------------------------------------------------------- new records

#: Property block of a track saved by Altium 26.10 (49 bytes; layer, coordinates, width and V7 id are set per
#: use – everything else is Altium's default: no net, polygon or component, not locked, keep-out off).
_TRACK_TEMPLATE: Final = bytes.fromhex(
    "410c00ffffffffffffffffffff000000000000000000000000000000000000000000000000000000000900020100000000"
)
#: Property block of a TrueType ``.Designator`` text saved by Altium 26.10 (252 bytes; layer, position, height,
#: stroke width, fonts, text box, WideStrings index and V7 id are set per use).
_TEXT_TEMPLATE: Final = bytes.fromhex(
    "430c00ffffffffffffffffffff000000000000000051ce0400010000000000000000000010f600000000000100004100"
    "7200690061006c0000000000000000000000000000000000000000000000000000000000000000000000000000000000"
    "00000000000000000000000000000000000000ffffffff000000000000000000000000000500000000a037a000200b20"
    "00400d0300400d0300000000000001010141007200690061006c00000000000000000000000000000000000000000000"
    "000000000000000000000000000000000000000000000000000000000000000000010b00020100000000008000000080"
    "010000000000000000000000"
)


def _template(raw: bytes, size: int) -> bytearray:
    block = bytearray(raw)
    if len(block) != size:  # pragma: no cover - guarded by the tests of the templates
        raise PcbRecordError("interne Vorlage hat die falsche Länge")
    return block


def new_track(layer: str, x1: float, y1: float, x2: float, y2: float, width: float,
              template: Primitive | None = None) -> Primitive:
    """A track record (copied from ``template`` – another track of the footprint – if given)."""
    if template is not None and template.kind == "track":
        block = bytearray(template.blocks[0])
    else:
        block = _template(_TRACK_TEMPLATE, 49)
    track = Primitive(CODE_OF["track"], [block])
    track.set_coords(x1, y1, x2, y2)
    track.set_width(width)
    if len(block) >= V7_OFFSETS["track"] + 4 and track._v7() is None:
        struct.pack_into("<I", block, V7_OFFSETS["track"], MECH_V7_BASE + 1)  # set_layer only updates a valid id
    track.set_layer(layer)
    return track


def new_text(layer: str, text: str, *, x: float, y: float, height: float, stroke_width: float,
             font: Literal["stroke", "truetype"], font_name: str, box: tuple[float, float],
             template: Primitive | None = None) -> Primitive:
    """A text record (``x``/``y`` = lower left corner of ``box``), copied from ``template`` if given."""
    content = text.encode("cp1252", "replace")
    if len(content) > 255:
        raise PcbRecordError("Text ist zu lang (höchstens 255 Zeichen).")
    if template is not None and template.kind == "text" and template._text_extended():
        block = bytearray(template.blocks[0])
    else:
        block = _template(_TEXT_TEMPLATE, 252)
    record = Primitive(CODE_OF["text"], [block, bytearray(bytes([len(content)]) + content)])
    record.blocks[0][40] = 0  # not the designator/comment of a placed component
    record.blocks[0][41] = 0
    record.set_position(x, y)
    record.set_height(height)
    record.set_stroke_width(stroke_width)
    struct.pack_into("<d", record.blocks[0], 27, 0.0)  # rotation
    record.blocks[0][35] = 0  # not mirrored
    record.set_font(font, font_name)
    record.set_text_box(*box)
    record.set_widestring_index(None)
    record.set_layer(layer)
    return record


# --------------------------------------------------------------------------- side streams


def count_stream(count: int) -> bytes:
    """``<footprint>/Header`` (and ``PrimitiveGuids/Header``): the u32 count."""
    return struct.pack("<I", count)


def guid_entries(data: bytes | None) -> list[tuple[int, int, bytes]] | None:
    """``PrimitiveGuids/Data`` entries (object kind, primitive index, 16-byte GUID); ``None`` if malformed."""
    if data is None:
        return None
    if len(data) % 24:
        return None
    return [
        (struct.unpack_from("<I", data, i)[0], struct.unpack_from("<I", data, i + 4)[0], data[i + 8 : i + 24])
        for i in range(0, len(data), 24)
    ]


def build_guid_stream(entries: Sequence[tuple[int, int, bytes]]) -> bytes:
    return b"".join(struct.pack("<II", kind, index) + guid for kind, index, guid in entries)


_PRIMITIVE_INDEX_RE: Final = re.compile(rb"\|PRIMITIVEINDEX=(\d+)\|")


def _new_index(old: int, inserted: Sequence[int]) -> int:
    """Index of an existing primitive after inserting records at the (new) positions ``inserted``."""
    index = old
    for at in sorted(inserted):
        if at <= index:
            index += 1
    return index


def insert_primitives(
    records: FootprintRecords,
    new: Iterable[Primitive],
    streams: Mapping[str, bytes | None],
) -> dict[str, bytes]:
    """Insert ``new`` primitives behind the last record of their kind (canonical type order otherwise) and
    return the side streams that change with it (relative names: ``Header``, ``PrimitiveGuids/Header``,
    ``PrimitiveGuids/Data``, ``UniqueIDPrimitiveInformation/Data``). ``streams`` holds their current
    content (missing = ``None``); the record list of ``records`` is updated in place.
    """
    order = [1, 2, 3, 4, 5, 6, 11, 12]
    positions: list[int] = []
    for prim in new:
        same = [i for i, p in enumerate(records.primitives) if p.code == prim.code]
        if same:
            at = same[-1] + 1
        else:
            rank = order.index(prim.code) if prim.code in order else len(order)
            earlier = [i for i, p in enumerate(records.primitives) if (order.index(p.code) if p.code in order else len(order)) <= rank]
            at = earlier[-1] + 1 if earlier else 0
        records.primitives.insert(at, prim)
        positions = [p + 1 if p >= at else p for p in positions] + [at]
    out: dict[str, bytes] = {"Header": count_stream(len(records.primitives))}
    guids = guid_entries(streams.get("PrimitiveGuids/Data"))
    if guids is not None:
        moved = [(kind, index if kind == COMPONENT_GUID_KIND else _new_index(index, positions), guid)
                 for kind, index, guid in guids]
        for at in sorted(positions):
            prim = records.primitives[at]
            moved.append((GUID_KINDS[prim.kind], at, uuid.uuid4().bytes_le))
        component = [e for e in moved if e[0] == COMPONENT_GUID_KIND]
        rest = sorted((e for e in moved if e[0] != COMPONENT_GUID_KIND), key=lambda e: e[1])
        out["PrimitiveGuids/Data"] = build_guid_stream([*component, *rest])
        out["PrimitiveGuids/Header"] = count_stream(len(component) + len(rest))
    unique = streams.get("UniqueIDPrimitiveInformation/Data")
    if unique:
        out["UniqueIDPrimitiveInformation/Data"] = _shift_unique_ids_positions(unique, positions)
    return out


def _shift_unique_ids_positions(data: bytes, positions: Sequence[int]) -> bytes:
    """``UniqueIDPrimitiveInformation/Data`` with indexes renumbered for records inserted at ``positions``."""
    out = bytearray()
    offset = 0
    while offset + 4 <= len(data):
        (length,) = struct.unpack_from("<I", data, offset)
        record = data[offset + 4 : offset + 4 + length]
        if len(record) != length:
            raise PcbRecordError("UniqueIDPrimitiveInformation ist abgeschnitten.")
        new = _PRIMITIVE_INDEX_RE.sub(
            lambda m: b"|PRIMITIVEINDEX=" + str(_new_index(int(m.group(1)), positions)).encode("ascii") + b"|",
            record,
        )
        out += struct.pack("<I", len(new)) + new
        offset += 4 + length
    if offset != len(data):
        raise PcbRecordError("UniqueIDPrimitiveInformation hat einen unbekannten Aufbau.")
    return bytes(out)


# --------------------------------------------------------------------------- reading whole libraries

#: Storages of a PcbLib that are no footprints (the Rust reader lists some of them as components).
NON_FOOTPRINT_STORAGES: Final = frozenset({
    "library", "fileversioninfo", "extendedprimitiveinformation", "uniqueidprimitiveinformation",
})
#: Keys of a ``read_pcblib`` footprint -> record kind (same order as in the ``Data`` stream).
JSON_KINDS: Final[dict[str, PrimitiveKind]] = {
    "tracks": "track", "arcs": "arc", "fills": "fill", "text": "text", "regions": "region", "component_bodies": "body",
}


def read_footprints(path: str | object) -> dict[str, tuple[str, FootprintRecords]]:
    """``{casefolded footprint name: (storage name, records)}`` of a PcbLib (structured storage, read-only).

    Footprints whose ``Data`` cannot be parsed are left out (the caller then keeps what the Rust reader
    says)."""
    from . import compound

    out: dict[str, tuple[str, FootprintRecords]] = {}
    for key, data in compound.read_child_streams(path, "Data").items():  # type: ignore[arg-type]
        storage = key.split("/", 1)[0]
        if storage.casefold() in NON_FOOTPRINT_STORAGES:
            continue
        try:
            records = parse_footprint(data)
        except PcbRecordError:
            continue
        out.setdefault(records.name.casefold(), (storage, records))
    return out


def correct_layers(component: dict, records: FootprintRecords) -> int:
    """Set the true layer (V7 id) on every primitive of a ``read_pcblib`` footprint (in place).

    The Rust reader reports primitives Altium saved on Mechanical 17–32 as "Mechanical 16"; this fixes them
    from the records (matched per kind and order, only when the counts agree). Returns the number of
    corrected primitives."""
    fixed = 0
    for key, kind in JSON_KINDS.items():
        items = [item for item in component.get(key) or [] if isinstance(item, dict)]
        prims = records.of_kind(kind)
        if not items or len(items) != len(prims):
            continue
        for item, prim in zip(items, prims, strict=True):
            true = prim.layer
            if true is None:
                continue
            reported = item.get("layer")
            try:
                same = isinstance(reported, str) and L.normalize_layer_name(reported) == true
            except L.LayerError:
                same = False
            if not same:
                item["layer"] = true
                fixed += 1
    return fixed


def angle_close(a: float, b: float, tol: float = 1e-6) -> bool:
    """Angles equal modulo 360°."""
    return abs(((a - b) + 180.0) % 360.0 - 180.0) <= tol


def track_length(prim: Primitive) -> float:
    x1, y1, x2, y2 = prim.coords
    return math.hypot(x2 - x1, y2 - y1)
