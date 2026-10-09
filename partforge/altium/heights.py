"""Footprint heights in PcbLib files (Altium's footprint property *Height*).

Altium stores ``IPCB_LibComponent.Height`` per component in ``<storage>/Parameters``
(``u32 length`` + ``|PATTERN=<name>|HEIGHT=21.6535mil|DESCRIPTION=…|ITEMGUID=|REVISIONGUID=`` +
NUL) and repeats it in the library's parameter table of contents
``Library/ComponentParamsTOC/Data`` (``u32 length`` + one line
``Name=<name>|Pad Count=2|Height=21.6535|Description=…`` CRLF per component + NUL). The value
is the height in Altium's internal unit (1/10000 mil, rounded) written in mil with at most
four decimals – with the unit in ``Parameters``, without it in the table of contents.
VERIFIED with libraries Altium 26.10 saved itself: 0.55 mm -> ``21.6535``, 1.75 mm ->
``68.8976``, 8.5 mm -> ``334.6457`` (altium-e2e.md, Welle 3).

The Rust writer has no field for the height: every footprint it writes gets ``HEIGHT=0mil``,
and **every** mutation (append, update or delete – also of another footprint) rewrites all
components with ``HEIGHT=0mil`` (VERIFIED). :class:`~partforge.altium.rustwriter.RustLibraryOps`
therefore reads the heights before each PcbLib mutation (:func:`read_footprint_heights`) and
afterwards sets every component to its height (:func:`patch_footprint_heights`): the
footprints of the call get theirs from the spec (:func:`footprint_height`), every other
component keeps the height it had (also footprints Altium saved – a write never loses them).

The patch works like the layer header patch (:mod:`partforge.altium.stackup`): the new
streams are planned and self-checked, written into a copy through structured storage
(transacted commit), the re-read copy must differ only in the planned streams, an optional
``verify`` callback (Rust reader) must accept it, then it replaces the library atomically
(:func:`partforge.altium.compound.replace_streams`). Any unexpected structure leaves the
library untouched and returns a German warning – a patch never fails a library write.
Idempotent: matching heights are not rewritten. Switch: ``HEIGHT_PATCH_ENABLED`` or the
environment variable ``PARTFORGE_HEIGHT_PATCH=0``.
"""
from __future__ import annotations

import logging
import math
import os
import re
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ..geometry.model import FootprintSpec
from . import compound

log = logging.getLogger(__name__)

__all__ = [
    "HEIGHT_PATCH_ENABLED",
    "PATCH_ENV",
    "TOC_STREAM",
    "MAX_HEIGHT_MM",
    "HeightError",
    "mm_to_coord",
    "coord_to_mm",
    "format_mil",
    "parse_height",
    "footprint_height",
    "height_of",
    "height_patch_enabled",
    "read_footprint_heights",
    "patch_footprint_heights",
]

#: Module-level switch of the height patch (checked at call time, like ``PARTFORGE_HEIGHT_PATCH``).
HEIGHT_PATCH_ENABLED: bool = True
PATCH_ENV: Final = "PARTFORGE_HEIGHT_PATCH"
#: Altium's internal unit: 1/10000 mil.
COORDS_PER_MIL: Final = 10_000
MM_PER_MIL: Final = 0.0254
#: Upper bound of a height (Altium coordinates are 32-bit: about 5450 mm).
MAX_HEIGHT_MM: Final = 5000.0
TOC_STREAM: Final = "Library/ComponentParamsTOC/Data"
PARAMETERS: Final = "Parameters"
#: Name of the patched copy beside the library (``<stem>.pfhgt<hex8><suffix>``).
COPY_TAG: Final = "pfhgt"

_VALUE_RE: Final = re.compile(rb"^\s*(\d{1,7}(?:\.\d{1,12})?)\s*(mil|mm)?\s*$", re.IGNORECASE)


class HeightError(ValueError):
    """A height cannot be written or read (German message). ``unreadable``: the file could not be read at all
    (COM or program error, e.g. an incomplete installation) – not merely an unexpected structure."""

    def __init__(self, message: str, *, unreadable: bool = False):
        super().__init__(message)
        self.unreadable = unreadable


class _Unexpected(Exception):
    """Internal: the PcbLib does not have the structure the patch expects."""


# --------------------------------------------------------------------------- units


def mm_to_coord(mm: float) -> int:
    """Height in mm -> Altium coordinate (1/10000 mil), rounded like Altium's ``MMsToCoord``."""
    value = float(mm)
    if not math.isfinite(value) or value < 0 or value > MAX_HEIGHT_MM:
        raise HeightError(f"Bauhöhe {mm!r} mm liegt außerhalb von 0…{MAX_HEIGHT_MM:g} mm.")
    return round(value / MM_PER_MIL * COORDS_PER_MIL)


def coord_to_mm(coord: int) -> float:
    return coord * MM_PER_MIL / COORDS_PER_MIL


def format_mil(coord: int) -> str:
    """Altium's text of a coordinate in mil: at most four decimals, no trailing zeros (``21.6535``)."""
    if coord < 0:
        raise HeightError(f"Negative Bauhöhe ({coord}) ist nicht zulässig.")
    whole, frac = divmod(int(coord), COORDS_PER_MIL)
    text = f"{whole}.{frac:04d}".rstrip("0").rstrip(".")
    return text or "0"


def parse_height(value: str | bytes) -> int | None:
    """Coordinate of a stored height (``21.6535mil``, ``0mil``, ``21.6535``, ``0.55mm``), else ``None``."""
    raw = value.encode("latin-1", "replace") if isinstance(value, str) else bytes(value)
    m = _VALUE_RE.match(raw)
    if m is None:
        return None
    number = float(m.group(1))
    if (m.group(2) or b"mil").lower() == b"mm":
        return round(number / MM_PER_MIL * COORDS_PER_MIL)
    return round(number * COORDS_PER_MIL)


def footprint_height(spec: FootprintSpec) -> float | None:
    """Height Altium shall show for a footprint (mm): ``spec.height``, else the top of the
    highest 3D body (the rule of the Altium backend), else ``None`` (unknown)."""
    return height_of(spec.height, [b.z_top for b in spec.bodies])


def height_of(height: object, body_tops: Iterable[object] = ()) -> float | None:
    """:func:`footprint_height` from raw values (e.g. a spec read as JSON): ``height`` if it is a positive
    finite number, else the highest positive body top, else ``None``."""

    def number(value: object) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value) if math.isfinite(value) and value > 0 else None

    direct = number(height)
    if direct is not None:
        return direct
    tops = [t for t in (number(v) for v in body_tops) if t is not None]
    return max(tops) if tops else None


def height_patch_enabled() -> bool:
    """``HEIGHT_PATCH_ENABLED`` and not switched off by ``PARTFORGE_HEIGHT_PATCH=0``."""
    return HEIGHT_PATCH_ENABLED and os.environ.get(PATCH_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


# --------------------------------------------------------------------------- stream records


def _split_record(data: bytes, what: str) -> tuple[list[bytes], bytes]:
    """``u32 length + '|' + KEY=VALUE|… + NUL`` (+ trailer) -> segments, trailer."""
    if len(data) < 6:
        raise _Unexpected(f"{what} ist zu kurz")
    (length,) = struct.unpack_from("<I", data, 0)
    if length < 2 or 4 + length > len(data):
        raise _Unexpected(f"ungültige Längenangabe in {what}")
    text = data[4 : 4 + length]
    if not text.endswith(b"\x00") or b"\x00" in text[:-1]:
        raise _Unexpected(f"{what} ist nicht nullterminiert")
    if not text.startswith(b"|"):
        raise _Unexpected(f"{what} beginnt nicht mit '|'")
    return text[1:-1].split(b"|"), data[4 + length :]


def _join_record(segments: list[bytes], trailer: bytes) -> bytes:
    text = b"|" + b"|".join(segments) + b"\x00"
    return struct.pack("<I", len(text)) + text + trailer


def _field_index(segments: list[bytes], key: bytes, what: str) -> int:
    """Index of the single ``KEY=`` segment (raises if missing or duplicated)."""
    found = [i for i, seg in enumerate(segments) if seg.partition(b"=")[0] == key and b"=" in seg]
    if len(found) != 1:
        state = "fehlt" if not found else "ist mehrfach vorhanden"
        raise _Unexpected(f"{key.decode('ascii')} {state} in {what}")
    return found[0]


@dataclass
class _Component:
    path: str  # "<storage>/Parameters"
    segments: list[bytes]
    trailer: bytes
    height_index: int

    @property
    def height(self) -> int | None:
        return parse_height(self.segments[self.height_index].partition(b"=")[2])


def _components(tree: Mapping[str, bytes | None]) -> dict[bytes, _Component]:
    """Every component of the library by its ``PATTERN`` (the full footprint name)."""
    out: dict[bytes, _Component] = {}
    for path, data in tree.items():
        parts = path.split("/")
        if data is None or len(parts) != 2 or parts[1] != PARAMETERS or parts[0] == "Library":
            continue
        segments, trailer = _split_record(data, path)
        name = segments[_field_index(segments, b"PATTERN", path)].partition(b"=")[2]
        if not name:
            raise _Unexpected(f"leerer PATTERN in {path}")
        if name in out:
            raise _Unexpected(f"Footprint {name.decode('latin-1')} ist mehrfach vorhanden")
        out[name] = _Component(path, segments, trailer, _field_index(segments, b"HEIGHT", path))
    return out


@dataclass
class _Toc:
    lines: list[bytes]  # CRLF-separated lines (the last one empty after the final CRLF)
    trailer: bytes
    by_name: dict[bytes, int]  # Name -> line index


def _split_toc(data: bytes) -> _Toc:
    if len(data) < 5:
        raise _Unexpected("Inhaltsverzeichnis (ComponentParamsTOC) ist zu kurz")
    (length,) = struct.unpack_from("<I", data, 0)
    if length < 1 or 4 + length > len(data):
        raise _Unexpected("ungültige Längenangabe im Inhaltsverzeichnis (ComponentParamsTOC)")
    text = data[4 : 4 + length]
    if not text.endswith(b"\x00") or b"\x00" in text[:-1]:
        raise _Unexpected("Inhaltsverzeichnis (ComponentParamsTOC) ist nicht nullterminiert")
    lines = text[:-1].split(b"\r\n")
    by_name: dict[bytes, int] = {}
    for index, line in enumerate(lines):
        if not line:
            continue
        first = line.split(b"|", 1)[0]
        key, sep, name = first.partition(b"=")
        if key != b"Name" or not sep:
            raise _Unexpected("Zeile im Inhaltsverzeichnis (ComponentParamsTOC) ohne Name")
        if name in by_name:
            raise _Unexpected(f"{name.decode('latin-1')} steht mehrfach im Inhaltsverzeichnis (ComponentParamsTOC)")
        by_name[name] = index
    return _Toc(lines=lines, trailer=data[4 + length :], by_name=by_name)


def _join_toc(toc: _Toc) -> bytes:
    text = b"\r\n".join(toc.lines) + b"\x00"
    return struct.pack("<I", len(text)) + text + toc.trailer


def _with_height(segments: list[bytes], index: int, value: bytes) -> list[bytes]:
    out = list(segments)
    out[index] = out[index].partition(b"=")[0] + b"=" + value
    return out


def _toc_line_height(line: bytes, what: bytes) -> tuple[list[bytes], int]:
    segments = line.split(b"|")
    found = [i for i, seg in enumerate(segments) if seg.partition(b"=")[0] == b"Height" and b"=" in seg]
    if len(found) != 1:
        raise _Unexpected(f"Height fehlt im Inhaltsverzeichnis bei {what.decode('latin-1')}")
    return segments, found[0]


# --------------------------------------------------------------------------- read


def _load(library: Path) -> dict[str, bytes | None]:
    """The streams the heights live in: every component's ``Parameters`` and the table of contents."""
    streams: dict[str, bytes | None] = dict(compound.read_child_streams(library, PARAMETERS))
    streams.update(compound.read_streams(library, [TOC_STREAM]))
    return streams


def read_footprint_heights(path: str | os.PathLike[str]) -> dict[str, float]:
    """``{footprint name: height in mm}`` of every component of a PcbLib (0 = not set).

    Read-only (ole32). Components whose ``HEIGHT`` cannot be parsed are left out; raises
    :class:`HeightError` if the file is no PcbLib with the expected component records.
    """
    library = Path(path)
    try:
        components = _components(_load(library))
    except _Unexpected as exc:
        raise HeightError(f"{library.name}: unerwarteter Aufbau ({exc}).") from exc
    except Exception as exc:  # noqa: BLE001 - pywintypes.com_error on damaged or foreign files, missing modules
        raise HeightError(f"{library.name}: nicht lesbar ({exc}).", unreadable=True) from exc
    out: dict[str, float] = {}
    for name, component in components.items():
        coord = component.height
        if coord is not None:
            out[name.decode("latin-1")] = coord_to_mm(coord)
    return out


# --------------------------------------------------------------------------- patch


def _plan(tree: Mapping[str, bytes | None], wanted: Mapping[bytes, int]) -> dict[str, bytes]:
    """New stream contents (``path -> data``) that give every wanted component its height."""
    components = _components(tree)
    targets = {name: coord for name, coord in wanted.items() if name in components}
    planned: dict[str, bytes] = {}
    for name, coord in targets.items():
        component = components[name]
        if component.height == coord:
            continue
        segments = _with_height(component.segments, component.height_index, format_mil(coord).encode("ascii") + b"mil")
        planned[component.path] = _join_record(segments, component.trailer)
    toc_data = tree.get(TOC_STREAM)
    if toc_data is not None and targets:
        toc = _split_toc(toc_data)
        changed = False
        for name, coord in targets.items():
            index = toc.by_name.get(name)
            if index is None:  # not listed: Altium rebuilds the table of contents when it saves
                continue
            segments, at = _toc_line_height(toc.lines[index], name)
            if parse_height(segments[at].partition(b"=")[2]) == coord:
                continue
            toc.lines[index] = b"|".join(_with_height(segments, at, format_mil(coord).encode("ascii")))
            changed = True
        if changed:
            planned[TOC_STREAM] = _join_toc(toc)
    return planned


def _check_plan(tree: Mapping[str, bytes | None], planned: Mapping[str, bytes], wanted: Mapping[bytes, int]) -> None:
    """Self-check: the planned streams carry the wanted heights and nothing else changed."""
    before = _components(tree)
    after = _components({**tree, **planned})
    if set(before) != set(after):
        raise _Unexpected("Selbstprüfung: die Footprint-Namen haben sich verändert")
    for name, component in after.items():
        old = before[name]
        expected = wanted.get(name, old.height)
        if component.height != expected:
            raise _Unexpected(f"Selbstprüfung: Bauhöhe von {name.decode('latin-1')} stimmt nicht")
        rest_old = [s for i, s in enumerate(old.segments) if i != old.height_index]
        rest_new = [s for i, s in enumerate(component.segments) if i != component.height_index]
        if rest_old != rest_new or old.trailer != component.trailer or old.path != component.path:
            raise _Unexpected(f"Selbstprüfung: außer der Bauhöhe wurde bei {name.decode('latin-1')} etwas verändert")
    if TOC_STREAM in planned:
        old_toc = _split_toc(tree[TOC_STREAM] or b"")
        new_toc = _split_toc(planned[TOC_STREAM])
        if len(old_toc.lines) != len(new_toc.lines) or old_toc.trailer != new_toc.trailer:
            raise _Unexpected("Selbstprüfung: Inhaltsverzeichnis (ComponentParamsTOC) verändert")
        for old_line, new_line in zip(old_toc.lines, new_toc.lines, strict=True):
            if old_line == new_line:
                continue
            old_segments, at = _toc_line_height(old_line, b"?")
            new_segments, at_new = _toc_line_height(new_line, b"?")
            name = old_segments[0].partition(b"=")[2]
            if at != at_new or [s for i, s in enumerate(old_segments) if i != at] != [
                s for i, s in enumerate(new_segments) if i != at_new
            ]:
                raise _Unexpected("Selbstprüfung: im Inhaltsverzeichnis wurde mehr als die Bauhöhe verändert")
            if parse_height(new_segments[at_new].partition(b"=")[2]) != wanted.get(name):
                raise _Unexpected("Selbstprüfung: Bauhöhe im Inhaltsverzeichnis stimmt nicht")


def _wanted(heights: Mapping[str, float], warnings: list[str], library: Path) -> dict[bytes, int]:
    out: dict[bytes, int] = {}
    for name, mm in heights.items():
        try:
            key = name.encode("latin-1")
        except UnicodeEncodeError:
            warnings.append(
                f"{library.name}: Footprint-Name {name!r} lässt sich nicht zuordnen – Bauhöhe nicht gesetzt."
            )
            continue
        try:
            out[key] = mm_to_coord(mm)
        except (HeightError, TypeError, ValueError) as exc:
            warnings.append(f"{library.name}: {name}: {exc} Bauhöhe nicht gesetzt.")
    return out


def patch_footprint_heights(
    path: str | os.PathLike[str],
    heights: Mapping[str, float],
    *,
    verify: Callable[[Path], None] | None = None,
) -> list[str]:
    """Set Altium's footprint height of the given components (``{name: height in mm}``).

    ``HEIGHT`` in each component's ``Parameters`` stream and ``Height`` in the table of
    contents are set to the height in Altium's format; every other byte of the library
    stays identical. Names the library does not contain are ignored. Idempotent: a library
    whose heights already match is not rewritten. Returns German warnings; on any problem
    the library is left untouched and the warning explains why.
    """
    library = Path(os.path.abspath(os.fspath(path)))
    if library.suffix.lower() != ".pcblib":
        return [f"{library.name}: Bauhöhen nur bei Footprint-Bibliotheken (.PcbLib) – nichts geändert."]
    if not library.is_file():
        return [f"{library.name}: Bibliothek nicht gefunden – Bauhöhen nicht gesetzt."]
    warnings: list[str] = []
    wanted = _wanted(heights, warnings, library)
    if not wanted:
        return warnings
    try:
        streams = _load(library)
        planned = _plan(streams, wanted)
        if not planned:
            return warnings
        _check_plan(streams, planned, wanted)
    except _Unexpected as exc:
        log.warning("Bauhöhen von %s nicht gesetzt: %s", library, exc)
        return [*warnings, f"{library.name}: Bauhöhen nicht gesetzt – unerwarteter Aufbau ({exc})."]
    except Exception as exc:  # noqa: BLE001 - pywintypes.com_error and friends: never fail a write
        log.warning("Bauhöhen von %s nicht lesbar: %s", library, exc, exc_info=True)
        return [*warnings, f"{library.name}: Bauhöhen nicht lesbar ({exc}) – nichts geändert."]
    try:
        compound.replace_streams(library, planned, verify=verify, tag=COPY_TAG)
    except compound.CompoundError as exc:
        log.warning("Bauhöhen von %s nicht gesetzt: %s", library, exc)
        return [*warnings, f"{library.name}: Bauhöhen nicht gesetzt – {exc}."]
    except Exception as exc:  # noqa: BLE001 - COM, OS and verify errors leave the library untouched
        log.warning("Bauhöhen von %s nicht gesetzt: %s", library, exc, exc_info=True)
        return [*warnings, f"{library.name}: Bauhöhen nicht gesetzt ({exc}) – Bibliothek unverändert."]
    changed = sum(1 for p in planned if p != TOC_STREAM)
    log.info("Bauhöhen von %s gesetzt (%d Footprints)", library, changed)
    return warnings
