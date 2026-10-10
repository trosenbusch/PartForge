"""Raw records of a SchLib: font table, component records, binary pins and ``PinTextData`` – read and edit
losslessly, without the library writer.

Format facts (VERIFIED on Altium 26.10 files, on Celestial libraries and on files of the Rust writer):

* ``FileHeader`` = u32 length + ``|KEY=VALUE|…`` (cp1252) + NUL. Fonts: ``FontIdCount=n`` and per font
  ``Size<i>``, ``FontName<i>`` and optionally ``Rotation<i>``, ``Underline<i>``, ``Italic<i>``, ``Bold<i>``,
  ``StrikeOut<i>`` (``T`` = on). Font 1 is the sheet's system font. The Rust writer stores only
  ``Times New Roman 10`` (every text ``FontID=1``) and drops existing fonts when it rewrites a file.
* ``<component>/Data`` = records of u32 (flags << 24 | length) + payload. Flags 0 = text record
  (``|RECORD=…|`` + NUL; designator 34, parameter/Comment 41, label 4, text frame 28 carry ``FontID``),
  flags 1 = binary record (pins: u32 type 2).
* Binary pin: type (u32) 0, ? 4, owner part (i16) 5, display mode 7, edge symbols 8–11, description
  (Pascal string) 12, then formal type, electrical type, flags (orientation in bits 0–1, ×90°), **length**
  (i16, 10-mil units), x, y (i16), colour (u32), name and designator (Pascal strings) and the rest.
* ``<component>/PinTextData`` (optional) = u32 length + ``|HEADER=PinTextData|Weight=<n>`` + NUL, then per
  pin a binary record (u32 ``0x01000000 | length``, ``0xD0``, Pascal name = zero-based pin index, u32 length +
  zlib data). The data are two records (pin name, pin designator): flags (``0x01`` custom position, ``0x02``
  relative to the component, ``0x0C`` rotation, ``0x10`` custom font), [i32 margin], [i16 font id + u32
  colour]. Altium's "custom font" of a pin lives here – e.g. ``10 02 00 00 00 00 00`` twice = name and
  designator in font 2, black.
"""
from __future__ import annotations

import re
import struct
import zlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

__all__ = [
    "SchRecordError",
    "SchFont",
    "FileHeader",
    "SchRecord",
    "PinView",
    "PinText",
    "parse_header",
    "parse_records",
    "build_records",
    "parse_pin_text_data",
    "build_pin_text_data",
    "TEXT_RECORD_FONTS",
    "HYPERLINK_RE",
]


class SchRecordError(ValueError):
    """A SchLib stream does not have the expected structure (German message)."""


#: Text records that carry a ``FontID`` (designator, parameter/Comment, label, text frame, note).
TEXT_RECORD_FONTS: Final = frozenset({"34", "41", "4", "28", "209"})
#: Parameter names Altium shows as hyperlinks (font with underline in the house style).
HYPERLINK_RE: Final = re.compile(r"^(ComponentLink\d+URL|Datasheet URL|Manufacturer URL|HelpURL)$", re.IGNORECASE)
_FONT_KEY_RE: Final = re.compile(r"^(FontIdCount|Size\d+|FontName\d+|Rotation\d+|Underline\d+|Italic\d+|Bold\d+|StrikeOut\d+)$",
                                 re.IGNORECASE)
_MAX_FONTS: Final = 255


def _text(raw: bytes) -> str:
    return raw.decode("cp1252", "replace")


def _bytes(text: str) -> bytes:
    return text.encode("cp1252", "replace")


# --------------------------------------------------------------------------- fonts / header


@dataclass(frozen=True)
class SchFont:
    """One entry of a SchLib font table."""

    name: str = "Times New Roman"
    size: int = 10
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    rotation: int = 0

    def key(self) -> tuple[str, int, bool, bool, bool, bool, int]:
        return (self.name.casefold(), self.size, self.bold, self.italic, self.underline, self.strikeout, self.rotation)

    def label(self) -> str:
        extras = [x for x, on in (("fett", self.bold), ("kursiv", self.italic), ("unterstrichen", self.underline)) if on]
        return f"{self.name} {self.size}" + (f" ({', '.join(extras)})" if extras else "")


@dataclass
class FileHeader:
    """``FileHeader`` of a SchLib as ordered raw segments (round trip identical)."""

    segments: list[bytes]
    trailer: bytes = b""

    @classmethod
    def parse(cls, data: bytes) -> FileHeader:
        if len(data) < 5:
            raise SchRecordError("SchLib-Kopf ist zu kurz.")
        (length,) = struct.unpack_from("<I", data, 0)
        if 4 + length > len(data):
            raise SchRecordError("SchLib-Kopf: ungültige Länge.")
        text = data[4 : 4 + length]
        if not text.endswith(b"\x00"):
            raise SchRecordError("SchLib-Kopf ist nicht nullterminiert.")
        body = text[:-1]
        segments = body.split(b"|")
        return cls(segments=segments, trailer=data[4 + length :])

    def to_bytes(self) -> bytes:
        text = b"|".join(self.segments) + b"\x00"
        return struct.pack("<I", len(text)) + text + self.trailer

    def pairs(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for seg in self.segments:
            key, sep, value = seg.partition(b"=")
            if sep:
                out.append((_text(key), _text(value)))
        return out

    def get(self, key: str) -> str | None:
        wanted = key.casefold()
        for k, v in self.pairs():
            if k.casefold() == wanted:
                return v
        return None

    def fonts(self) -> list[SchFont]:
        """The font table (font id = index + 1)."""
        values = {k.casefold(): v for k, v in self.pairs()}
        try:
            count = int(values.get("fontidcount", "0"))
        except ValueError:
            count = 0
        out: list[SchFont] = []
        for i in range(1, max(0, min(count, _MAX_FONTS)) + 1):
            def flag(name: str, i: int = i) -> bool:
                return values.get(f"{name}{i}", "").strip().upper() == "T"

            try:
                size = int(values.get(f"size{i}", "10"))
            except ValueError:
                size = 10
            try:
                rotation = int(values.get(f"rotation{i}", "0"))
            except ValueError:
                rotation = 0
            out.append(SchFont(name=values.get(f"fontname{i}", "Times New Roman") or "Times New Roman", size=size,
                               bold=flag("bold"), italic=flag("italic"), underline=flag("underline"),
                               strikeout=flag("strikeout"), rotation=rotation))
        return out

    def set_fonts(self, fonts: Sequence[SchFont]) -> None:
        """Replace the font table (keys are written where ``FontIdCount`` was, Altium's key order)."""
        if not fonts:
            raise SchRecordError("Eine SchLib braucht mindestens eine Schrift.")
        block: list[bytes] = [f"FontIdCount={len(fonts)}".encode("ascii")]
        for i, font in enumerate(fonts, start=1):
            block.append(f"Size{i}={font.size}".encode("ascii"))
            if font.rotation:
                block.append(f"Rotation{i}={font.rotation}".encode("ascii"))
            if font.underline:
                block.append(f"Underline{i}=T".encode("ascii"))
            if font.italic:
                block.append(f"Italic{i}=T".encode("ascii"))
            if font.bold:
                block.append(f"Bold{i}=T".encode("ascii"))
            if font.strikeout:
                block.append(f"StrikeOut{i}=T".encode("ascii"))
            block.append(b"FontName" + str(i).encode("ascii") + b"=" + _bytes(font.name))
        out: list[bytes] = []
        inserted = False
        for seg in self.segments:
            key = _text(seg.partition(b"=")[0])
            if _FONT_KEY_RE.match(key):
                if not inserted:
                    out.extend(block)
                    inserted = True
                continue
            out.append(seg)
        if not inserted:  # no font table yet: after the header line(s)
            at = next((i + 1 for i, seg in enumerate(out) if seg.startswith(b"MinorVersion=")), min(len(out), 3))
            out[at:at] = block
        self.segments = out


def parse_header(data: bytes) -> FileHeader:
    return FileHeader.parse(data)


# --------------------------------------------------------------------------- component records


@dataclass
class SchRecord:
    """One record of ``<component>/Data``: ``binary`` (flags 1) or text (``|KEY=VALUE|…`` + NUL)."""

    binary: bool
    payload: bytearray
    flags: int = 0

    # -- text records -------------------------------------------------------------------------------
    def _segments(self) -> list[bytes]:
        body = bytes(self.payload)
        if body.endswith(b"\x00"):
            body = body[:-1]
        return body.split(b"|")

    def _store(self, segments: list[bytes]) -> None:
        self.payload = bytearray(b"|".join(segments) + b"\x00")

    def get(self, key: str) -> str | None:
        if self.binary:
            return None
        wanted = key.encode("ascii")
        for seg in self._segments():
            k, sep, v = seg.partition(b"=")
            if sep and k == wanted:
                return _text(v)
        return None

    def set(self, key: str, value: str | None, *, after: Iterable[str] = ()) -> bool:
        """Set ``key`` (``None`` removes it); a new key goes after the first present key of ``after``
        (else at the end). Returns whether the record changed."""
        if self.binary:
            raise SchRecordError("Binärer Datensatz hat keine Schlüssel.")
        wanted = key.encode("ascii")
        segments = self._segments()
        for i, seg in enumerate(segments):
            k, sep, v = seg.partition(b"=")
            if sep and k == wanted:
                if value is None:
                    del segments[i]
                else:
                    new = wanted + b"=" + _bytes(value)
                    if new == seg:
                        return False
                    segments[i] = new
                self._store(segments)
                return True
        if value is None:
            return False
        new = wanted + b"=" + _bytes(value)
        anchors = [a.encode("ascii") for a in after]
        position = len(segments)
        for anchor in anchors:
            found = next((i for i, seg in enumerate(segments) if seg.partition(b"=")[0] == anchor), None)
            if found is not None:
                position = found + 1
                break
        segments.insert(position, new)
        self._store(segments)
        return True

    @property
    def record_type(self) -> str:
        if self.binary:
            if len(self.payload) >= 4:
                return str(struct.unpack_from("<I", self.payload, 0)[0])
            return "?"
        return self.get("RECORD") or "?"

    @property
    def is_pin(self) -> bool:
        return self.binary and self.record_type == "2"

    def to_bytes(self) -> bytes:
        head = (self.flags << 24) | len(self.payload)
        return struct.pack("<I", head) + bytes(self.payload)


def parse_records(data: bytes) -> list[SchRecord]:
    """Split ``<component>/Data`` into records (raises :class:`SchRecordError`)."""
    out: list[SchRecord] = []
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise SchRecordError("Symboldaten sind abgeschnitten.")
        (head,) = struct.unpack_from("<I", data, offset)
        flags, length = head >> 24, head & 0xFFFFFF
        offset += 4
        if offset + length > len(data):
            raise SchRecordError("Symboldaten: Datensatz ist abgeschnitten.")
        out.append(SchRecord(binary=flags == 1, payload=bytearray(data[offset : offset + length]), flags=flags))
        offset += length
    return out


def build_records(records: Sequence[SchRecord]) -> bytes:
    return b"".join(r.to_bytes() for r in records)


# --------------------------------------------------------------------------- binary pins


Orientation = Literal["right", "up", "left", "down"]
_ORIENTATIONS: Final[tuple[Orientation, ...]] = ("right", "up", "left", "down")


class PinView:
    """Field access to a binary pin record (lengths in schematic units: 1 = 10 mil)."""

    def __init__(self, record: SchRecord):
        if not record.is_pin:
            raise SchRecordError("Kein Pin-Datensatz.")
        self.record = record
        payload = record.payload
        if len(payload) < 13:
            raise SchRecordError("Pin-Datensatz ist zu kurz.")
        description = payload[12]
        self._base = 13 + description  # offset of the formal type
        if len(payload) < self._base + 13:
            raise SchRecordError("Pin-Datensatz ist zu kurz.")
        name_at = self._base + 13
        name_length = payload[name_at]
        designator_at = name_at + 1 + name_length
        if designator_at >= len(payload):
            raise SchRecordError("Pin-Datensatz ist zu kurz.")
        self._name = (name_at, name_length)
        self._designator = (designator_at, payload[designator_at])

    @property
    def owner_part(self) -> int:
        return struct.unpack_from("<h", self.record.payload, 5)[0]

    @property
    def display_mode(self) -> int:
        return self.record.payload[7]

    @property
    def flags(self) -> int:
        return self.record.payload[self._base + 2]

    @property
    def orientation(self) -> Orientation:
        return _ORIENTATIONS[self.flags & 0x03]

    @property
    def show_name(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def show_designator(self) -> bool:
        return bool(self.flags & 0x10)

    @property
    def hidden(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def length(self) -> int:
        return struct.unpack_from("<h", self.record.payload, self._base + 3)[0]

    def set_length(self, units: int) -> None:
        if not 0 <= units <= 32767:
            raise SchRecordError(f"Ungültige Pinlänge {units}.")
        struct.pack_into("<h", self.record.payload, self._base + 3, units)

    @property
    def location(self) -> tuple[int, int]:
        return struct.unpack_from("<hh", self.record.payload, self._base + 5)

    @property
    def color(self) -> int:
        return struct.unpack_from("<I", self.record.payload, self._base + 9)[0]

    def set_color(self, value: int) -> None:
        struct.pack_into("<I", self.record.payload, self._base + 9, value & 0xFFFFFF)

    @property
    def name(self) -> str:
        at, length = self._name
        return _text(bytes(self.record.payload[at + 1 : at + 1 + length]))

    @property
    def designator(self) -> str:
        at, length = self._designator
        return _text(bytes(self.record.payload[at + 1 : at + 1 + length]))

    def tip(self) -> tuple[int, int]:
        """Electrical end (``location`` is the end at the body)."""
        x, y = self.location
        dx, dy = {"right": (1, 0), "up": (0, 1), "left": (-1, 0), "down": (0, -1)}[self.orientation]
        return x + dx * self.length, y + dy * self.length


# --------------------------------------------------------------------------- PinTextData


@dataclass(frozen=True)
class PinTextPart:
    """Custom settings of a pin's name or designator text."""

    font_id: int | None = None
    color: int = 0
    margin: int | None = None  # 1/10000 mil, custom position
    position_flags: int = 0  # bits 0x02 (relative to component) and 0x0C (rotation) of a custom position

    def encode(self) -> bytes:
        flags = 0
        out = bytearray()
        if self.margin is not None:
            flags |= 0x01 | (self.position_flags & 0x0E)
            out += struct.pack("<i", self.margin)
        if self.font_id is not None:
            flags |= 0x10
            out += struct.pack("<hI", self.font_id, self.color & 0xFFFFFFFF)
        return bytes([flags]) + bytes(out)


@dataclass(frozen=True)
class PinText:
    """PinTextData of one pin (name and designator settings)."""

    name: PinTextPart = field(default_factory=PinTextPart)
    designator: PinTextPart = field(default_factory=PinTextPart)

    def encode(self) -> bytes:
        return self.name.encode() + self.designator.encode()


def _decode_part(data: bytes, offset: int) -> tuple[PinTextPart, int]:
    if offset >= len(data):
        raise SchRecordError("PinTextData ist abgeschnitten.")
    flags = data[offset]
    offset += 1
    if flags & ~0x1F:
        raise SchRecordError("PinTextData enthält unbekannte Kennungen.")
    margin = None
    if flags & 0x01:
        if offset + 4 > len(data):
            raise SchRecordError("PinTextData ist abgeschnitten.")
        margin = struct.unpack_from("<i", data, offset)[0]
        offset += 4
    font_id = None
    color = 0
    if flags & 0x10:
        if offset + 6 > len(data):
            raise SchRecordError("PinTextData ist abgeschnitten.")
        font_id, color = struct.unpack_from("<hI", data, offset)
        offset += 6
    return PinTextPart(font_id=font_id, color=color, margin=margin, position_flags=flags & 0x0E), offset


def parse_pin_text_data(data: bytes | None) -> dict[int, PinText]:
    """``{zero-based pin index: PinText}`` of a ``PinTextData`` stream (empty for ``None``)."""
    if not data:
        return {}
    if len(data) < 4:
        raise SchRecordError("PinTextData ist zu kurz.")
    (length,) = struct.unpack_from("<I", data, 0)
    header = data[4 : 4 + length]
    if b"HEADER=PinTextData" not in header:
        raise SchRecordError("PinTextData hat einen unbekannten Kopf.")
    offset = 4 + length
    out: dict[int, PinText] = {}
    while offset < len(data):
        if offset + 4 > len(data):
            raise SchRecordError("PinTextData ist abgeschnitten.")
        (head,) = struct.unpack_from("<I", data, offset)
        size = head & 0xFFFFFF
        offset += 4
        record = data[offset : offset + size]
        offset += size
        if len(record) != size or len(record) < 7 or record[0] != 0xD0:
            raise SchRecordError("PinTextData enthält einen unbekannten Datensatz.")
        name_length = record[1]
        name = record[2 : 2 + name_length].decode("ascii", "replace")
        cursor = 2 + name_length
        (zlength,) = struct.unpack_from("<I", record, cursor)
        payload = zlib.decompress(record[cursor + 4 : cursor + 4 + zlength])
        part_name, at = _decode_part(payload, 0)
        part_designator, at = _decode_part(payload, at)
        if at != len(payload):
            raise SchRecordError("PinTextData enthält überzählige Daten.")
        if not name.isdigit():
            raise SchRecordError(f"PinTextData: unbekannter Pin-Schlüssel „{name}“.")
        out[int(name)] = PinText(name=part_name, designator=part_designator)
    return out


def build_pin_text_data(pins: dict[int, PinText]) -> bytes | None:
    """``PinTextData`` stream for ``pins`` (pins without custom settings are left out; ``None`` = no stream
    needed)."""
    entries = [(index, text) for index, text in sorted(pins.items()) if text != PinText()]
    if not entries:
        return None
    header = f"|HEADER=PinTextData|Weight={len(entries)}".encode("ascii") + b"\x00"
    out = bytearray(struct.pack("<I", len(header)) + header)
    for index, text in entries:
        name = str(index).encode("ascii")
        compressed = zlib.compress(text.encode())
        record = bytes([0xD0, len(name)]) + name + struct.pack("<I", len(compressed)) + compressed
        out += struct.pack("<I", 0x01000000 | len(record)) + record
    return bytes(out)
