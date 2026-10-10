"""House fonts in SchLib files: font table, ``FontID`` of the texts and custom pin fonts.

The workspace :class:`~partforge.workspace.SymbolStyle` names the house font (``font``/``font_size``) for
designator, Comment, parameters and free texts, and whether pin names and numbers use it too
(``pin_font = "house"``, Altium's "custom font" of a pin, stored in ``PinTextData``) or the sheet's system
font (``"system"``). The table follows Altium's convention (VERIFIED on the user's reference library
``Components - 09.10.26``): font 1 stays the system font (Times New Roman 10), the house font is added as
font 2 and its underlined variant (hyperlink parameters such as ``ComponentLink1URL``) as font 3::

    FontIdCount=3|Size1=10|FontName1=Times New Roman|Size2=10|FontName2=Verdana|Size3=10|Underline3=T|FontName3=Verdana

With the default house font (Times New Roman 10 = the system font) nothing changes in a file.

Two users:

* :func:`patch_written_symbols` – after every write of the Rust writer (which keeps only one font and drops
  the existing table): the table **before** the write is restored, so untouched components keep valid font
  references, and the written components get the house fonts (:class:`~partforge.altium.rustwriter.RustLibraryOps`).
* :mod:`partforge.altium.conform` – the house-style conversion of whole libraries (:func:`apply_fonts`).
"""
from __future__ import annotations

import logging
import os
import struct
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..workspace import SymbolStyle
from . import compound
from . import schrecords as S

log = logging.getLogger(__name__)

__all__ = [
    "SYSTEM_FONT",
    "FontIds",
    "house_font",
    "plan_font_table",
    "apply_fonts",
    "component_streams",
    "patch_written_symbols",
    "read_font_table",
]

#: Altium's system font of a schematic library (font 1 of every new SchLib).
SYSTEM_FONT: Final = S.SchFont("Times New Roman", 10)


def house_font(style: SymbolStyle) -> S.SchFont:
    size = int(style.font_size) if 4 <= int(style.font_size) <= 72 else 10
    return S.SchFont((style.font or SYSTEM_FONT.name).strip() or SYSTEM_FONT.name, size)


def _same(a: S.SchFont, b: S.SchFont) -> bool:
    return a.key() == b.key()


@dataclass(frozen=True)
class FontIds:
    """Font ids of the roles in a planned table (``pin`` = ``None``: pins use the system font)."""

    text: int
    link: int
    pin: int | None


def plan_font_table(existing: Sequence[S.SchFont], style: SymbolStyle) -> tuple[list[S.SchFont], FontIds]:
    """The font table with the house fonts (existing entries are kept, missing ones appended) and the ids.

    An empty ``existing`` table starts with :data:`SYSTEM_FONT`. With the default house font no font is
    added (``text = link = 1``, pins on the system font)."""
    fonts = list(existing) or [SYSTEM_FONT]
    house = house_font(style)
    system = fonts[0]

    def find_or_add(font: S.SchFont) -> int:
        for index, entry in enumerate(fonts, start=1):
            if _same(entry, font):
                return index
        fonts.append(font)
        return len(fonts)

    if _same(house, system):
        return fonts, FontIds(text=1, link=1, pin=None)
    text = find_or_add(house)
    link = find_or_add(S.SchFont(house.name, house.size, underline=True))
    pin = text if style.pin_font == "house" else None
    return fonts, FontIds(text=text, link=link, pin=pin)


def _font_role(record: S.SchRecord) -> str | None:
    """``text`` / ``link`` for records whose font the house style sets, else ``None``."""
    if record.binary:
        return None
    kind = record.get("RECORD")
    if kind not in S.TEXT_RECORD_FONTS:
        return None
    if kind == "41" and S.HYPERLINK_RE.match(record.get("Name") or ""):
        return "link"
    return "text"


def apply_fonts(
    records: list[S.SchRecord],
    pin_text: dict[int, S.PinText],
    ids: FontIds,
    *,
    pin_color: int = 0,
) -> tuple[bool, dict[int, S.PinText]]:
    """Set the house fonts on one component (records changed in place). Returns (changed, PinTextData).

    Pins keep a custom text position of their own; ``ids.pin = None`` removes custom pin fonts again."""
    changed = False
    for record in records:
        role = _font_role(record)
        if role is None:
            continue
        wanted = str(ids.link if role == "link" else ids.text)
        if record.get("FontID") != wanted:
            record.set("FontID", wanted, after=("Color", "Location.Y", "Location.X", "OwnerPartId"))
            changed = True
    pins = [r for r in records if r.is_pin]
    new_text: dict[int, S.PinText] = {}
    for index in range(len(pins)):
        old = pin_text.get(index, S.PinText())
        if ids.pin is None:
            name = S.PinTextPart(margin=old.name.margin, position_flags=old.name.position_flags)
            designator = S.PinTextPart(margin=old.designator.margin, position_flags=old.designator.position_flags)
        else:
            name = S.PinTextPart(font_id=ids.pin, color=pin_color, margin=old.name.margin,
                                 position_flags=old.name.position_flags)
            designator = S.PinTextPart(font_id=ids.pin, color=pin_color, margin=old.designator.margin,
                                       position_flags=old.designator.position_flags)
        new_text[index] = S.PinText(name=name, designator=designator)
    normalized_old = {i: t for i, t in pin_text.items() if t != S.PinText() and i < len(pins)}
    normalized_new = {i: t for i, t in new_text.items() if t != S.PinText()}
    if normalized_old != normalized_new or len(pin_text) != len(normalized_old):
        changed = True
    return changed, normalized_new


def read_font_table(path: str | os.PathLike[str]) -> list[S.SchFont] | None:
    """Font table of a SchLib (``None`` if the file or its header cannot be read)."""
    try:
        data = compound.read_streams(path, ["FileHeader"]).get("FileHeader")
    except Exception as exc:  # noqa: BLE001 - COM errors: no table known
        log.debug("Schrifttabelle von %s nicht lesbar: %s", path, exc)
        return None
    if data is None:
        return None
    try:
        return S.parse_header(data).fonts()
    except S.SchRecordError:
        return None


def component_streams(tree: Mapping[str, bytes | None]) -> dict[str, str]:
    """``{storage: LibReference}`` of the components of a SchLib tree (``read_tree_file``)."""
    out: dict[str, str] = {}
    for key, data in tree.items():
        if data is None or not key.endswith("/Data") or key.count("/") != 1:
            continue
        storage = key.split("/", 1)[0]
        try:
            records = S.parse_records(data)
        except S.SchRecordError:
            continue
        head = next((r for r in records if not r.binary and r.get("RECORD") == "1"), None)
        name = head.get("LibReference") if head is not None else None
        out[storage] = name or storage
    return out


def _hex_color(value: str) -> int:
    """``#RRGGBB`` -> Win32 COLORREF."""
    text = value.strip().lstrip("#")
    try:
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except (ValueError, IndexError):
        return 0
    return r | (g << 8) | (b << 16)


def patch_written_symbols(
    library: str | os.PathLike[str],
    names: Collection[str],
    style: SymbolStyle,
    *,
    before: Sequence[S.SchFont] | None = None,
    verify: Callable[[Path], None] | None = None,
) -> list[str]:
    """House fonts for the components ``names`` just written into ``library`` (a working copy).

    ``before`` is the font table the file had before the write (the Rust writer replaces it with a single
    font): it is restored first, so every other component keeps its fonts. Returns German warnings; any
    unexpected structure leaves the file as it is (a font patch never fails a write)."""
    path = Path(os.path.abspath(os.fspath(library)))
    wanted = {n.casefold() for n in names}
    try:
        tree = compound.read_tree_file(path)
        header_raw = tree.get("FileHeader")
        if header_raw is None:
            return [f"{path.name}: kein Bibliothekskopf – Schriften nicht gesetzt."]
        header = S.parse_header(header_raw)
        base = list(before) if before else header.fonts()
        fonts, ids = plan_font_table(base, style)
        streams: dict[str, bytes] = {}
        if [f.key() for f in fonts] != [f.key() for f in header.fonts()]:
            header.set_fonts(fonts)
            streams["FileHeader"] = header.to_bytes()
        pin_color = _hex_color(style.pin_color)
        for storage, name in component_streams(tree).items():
            if name.casefold() not in wanted:
                continue
            data = tree.get(f"{storage}/Data")
            assert data is not None
            records = S.parse_records(data)
            pin_raw = tree.get(f"{storage}/PinTextData")
            pin_text = S.parse_pin_text_data(pin_raw)
            changed, new_text = apply_fonts(records, pin_text, ids, pin_color=pin_color)
            if not changed:
                continue
            streams[f"{storage}/Data"] = S.build_records(records)
            built = S.build_pin_text_data(new_text)
            if built is not None:
                streams[f"{storage}/PinTextData"] = built
            elif pin_raw is not None:  # no custom pin fonts any more: keep an empty table (never delete streams)
                streams[f"{storage}/PinTextData"] = _empty_pin_text_data()
    except (S.SchRecordError, compound.CompoundError) as exc:
        log.warning("Schriften in %s nicht gesetzt: %s", path, exc)
        return [f"{path.name}: Schriften nicht gesetzt – unerwarteter Aufbau ({exc})."]
    except Exception as exc:  # noqa: BLE001 - COM errors: never fail a write
        log.warning("Schriften in %s nicht gesetzt: %s", path, exc, exc_info=True)
        return [f"{path.name}: Schriften nicht gesetzt ({exc})."]
    if not streams:
        return []
    try:
        compound.replace_streams(path, streams, verify=verify, tag="pffont", create=True)
    except Exception as exc:  # noqa: BLE001 - COM, OS and verify errors leave the file untouched
        log.warning("Schriften in %s nicht gesetzt: %s", path, exc, exc_info=True)
        return [f"{path.name}: Schriften nicht gesetzt ({exc}) – Bibliothek unverändert."]
    return []


def _empty_pin_text_data() -> bytes:
    header = b"|HEADER=PinTextData\x00"
    import struct

    return struct.pack("<I", len(header)) + header
