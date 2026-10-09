"""Altium mechanical layer stacks (``.stackup``) and the PcbLib layer header patch.

Two jobs:

1. **Layer stacks.** :func:`parse_stackup` reads an Altium ``.stackup`` file (the user's
   standard: ``C:\\PartForge-Examples\\Altium_Templates\\Mechanical_Stackup_Standard\\mechanical_layer.stackup``)
   into a :class:`LayerStack` – mechanical layers ``{n: MechLayer(name, kind, enabled)}`` plus
   the layer pairs. :func:`default_stack` is a built-in copy of that standard,
   :func:`suggest_layer_map` derives a workspace :class:`~partforge.workspace.LayerMap` from the
   layer kinds, :func:`workspace_stack` resolves ``WorkspaceSettings.layer_stackup``.

2. **PcbLib header patch.** The Rust writer stores a fixed template in ``Library/Data`` of
   every PcbLib it writes: Mech 2-7 typed as assembly/courtyard/3D body (``AssemblyTop`` …)
   and only Mech 1-7, 13 and 15 enabled (VERIFIED, altium-verify-2 §3.2/8). The mechanical
   layers are stored three times in that header (altium-verify-rust §3.11), every one keyed
   by the layer id ``0x01020000 + n``:

   * ``V9_CACHE_LAYER<k>_NAME / _MECHENABLED / _MECHKIND`` (Mech 1-16 = k 69-84, 17-32 = 86-101),
   * ``LAYER_V8_<k>NAME / MECHENABLED / MECHKIND`` (Mech 1-16 = k 11-26, 17-32 = 40-55),
   * legacy ``LAYER<56+n>NAME / MECHENABLED / MECHKIND`` (Mech 1-16) and
     ``LAYERV7_<n-17>NAME / MECHENABLED / MECHKIND`` (Mech 17-32),

   plus the layer pairs ``MECHPAIR<i>L1/L2`` and the layer sets "&All Layers" /
   "&Mechanical Layers" (every enabled mechanical layer; in "&All Layers" Mech 1-16 before and
   Mech 17-32 after ``DrillDrawing``, as Altium writes them). :func:`patch_pcblib_layers`
   rewrites exactly those values so the library shows the workspace stack (names, enabled
   flags, kinds) – every other byte of the file stays identical. The binary
   ``Library/LayerKindMapping`` is left as the Rust writer creates it (empty; Altium then takes
   the kinds from the text header, VERIFIED with the Rust files); a non-empty mapping (a file
   saved by Altium) is an unexpected structure.

   The patch works on a copy through Windows structured storage (``pythoncom``
   ``StgOpenStorageEx`` + ``IStorage``/``IStream``, read-modify-write, transacted commit), checks
   the copy (ole32 re-read: every other stream byte-identical; optional ``verify`` callback,
   e.g. the Rust reader) and only then replaces the library atomically. Any unexpected
   structure leaves the file untouched and returns a German warning – a patch never fails a
   library write. ``HEADER_PATCH_ENABLED`` (or the environment variable
   ``PARTFORGE_LAYER_PATCH=0``) switches the patch off, e.g. if Altium rejects patched headers.
"""
from __future__ import annotations

import logging
import os
import re
import struct
import threading
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

from ..domain.text import TRANSLITERATION, clean_free_text
from ..workspace import LayerMap, Workspace
from . import compound
from . import layers as L

log = logging.getLogger(__name__)

__all__ = [
    "HEADER_PATCH_ENABLED",
    "PATCH_ENV",
    "MECH_LAYER_ID_BASE",
    "HEADER_MECH_LAYERS",
    "LAYER_MAP_KINDS",
    "ROLE_NAMES",
    "StackupError",
    "MechLayer",
    "LayerStack",
    "default_stack",
    "parse_stackup",
    "parse_stackup_text",
    "suggest_layer_map",
    "layer_map_issues",
    "effective_stack",
    "workspace_stack",
    "header_patch_enabled",
    "patch_pcblib_layers",
    "read_pcblib_layers",
    "pcblib_layer_problems",
    "read_library_data",
]

#: Module-level switch for the PcbLib header patch (the Altium E2E stage turns it off if
#: Altium rejects patched headers). Checked at call time, like ``PARTFORGE_LAYER_PATCH``.
HEADER_PATCH_ENABLED: bool = True
PATCH_ENV: Final = "PARTFORGE_LAYER_PATCH"

#: Layer id of ``Mechanical n`` is ``MECH_LAYER_ID_BASE + n`` (V7/V8/V9 layer ids).
MECH_LAYER_ID_BASE: Final = 0x01020000
MAX_MECH_LAYER: Final = 1024
#: Mechanical layers a PcbLib header represents (and the Rust writer can address).
HEADER_MECH_LAYERS: Final = L.MECHANICAL_LAYER_COUNT
#: First legacy layer number of the mechanical layers (``LAYER57`` = Mechanical 1).
LEGACY_MECH_OFFSET: Final = 56
LEGACY_MECH_LAYERS: Final = 16

#: LayerMap role -> Altium layer kind (``MECHKIND``) of the top-side layer of that role.
LAYER_MAP_KINDS: Final[dict[str, str]] = {
    "assembly": "AssemblyTop",
    "designator": "DesignatorTop",
    "body3d": "3DBodyTop",
    "courtyard": "CourtyardTop",
    "component_center": "ComponentCenterTop",
    "comment": "ValueTop",
    "component_outline": "ComponentOutlineTop",
}
#: Layer names used when a LayerMap role points at a layer the stack does not define.
ROLE_NAMES: Final[dict[str, str]] = {
    "assembly": "Top Assembly",
    "designator": "Top Designator",
    "body3d": "Top 3D Body",
    "courtyard": "Top Courtyard",
    "component_center": "Top Component Center",
    "comment": "Top Value",
    "component_outline": "Top Component Outline",
}
ROLE_LABELS: Final[dict[str, str]] = {
    "assembly": "Bestückungsumriss",
    "designator": "Bezeichner (.Designator)",
    "body3d": "3D-Körper",
    "courtyard": "Courtyard",
    "component_center": "Bauteilmitte",
    "comment": "Wert (.Comment)",
    "component_outline": "Bauteilumriss",
}

_KIND_RE: Final = re.compile(r"^[A-Za-z0-9]{1,40}$")
_MECHPAIR_VALUE_RE: Final = re.compile(r"^MECHANICAL(\d{1,4})$", re.IGNORECASE)
_MAX_NAME_LENGTH: Final = 100

# --------------------------------------------------------------------------- models


class StackupError(ValueError):
    """A ``.stackup`` file cannot be used (German message)."""


class MechLayer(BaseModel):
    """One mechanical layer of a stack."""

    number: int = Field(ge=1, le=MAX_MECH_LAYER)
    name: str
    kind: str | None = Field(default=None, description="Altium-Lagentyp (MECHKIND), z. B. AssemblyTop")
    enabled: bool = True


class LayerStack(BaseModel):
    """Mechanical layers ``{n: MechLayer}`` and layer pairs of an Altium layer stack."""

    name: str = ""
    source: str = "builtin"  # "builtin" or the .stackup path
    layers: dict[int, MechLayer] = Field(default_factory=dict)
    pairs: list[tuple[int, int]] = Field(default_factory=list)

    def layer(self, number: int) -> MechLayer | None:
        return self.layers.get(number)

    def by_kind(self, kind: str, *, limit: int | None = HEADER_MECH_LAYERS) -> MechLayer | None:
        """Enabled layer with this kind (lowest number first), else a disabled one."""
        found = [
            layer
            for n, layer in sorted(self.layers.items())
            if layer.kind == kind and (limit is None or n <= limit)
        ]
        enabled = [layer for layer in found if layer.enabled]
        if enabled:
            return enabled[0]
        return found[0] if found else None

    def header_layers(self) -> dict[int, MechLayer]:
        """Mechanical 1..32 as written into a PcbLib header (undefined ones: plain, disabled)."""
        out: dict[int, MechLayer] = {}
        for n in range(1, HEADER_MECH_LAYERS + 1):
            layer = self.layers.get(n)
            out[n] = layer if layer is not None else MechLayer(number=n, name=f"Mechanical {n}", enabled=False)
        return out

    def header_pairs(self) -> list[tuple[int, int]]:
        """Layer pairs representable in a PcbLib header (both layers 1..32, distinct, unique)."""
        out: list[tuple[int, int]] = []
        used: set[int] = set()
        for a, b in self.pairs:
            if a == b or not (1 <= a <= HEADER_MECH_LAYERS and 1 <= b <= HEADER_MECH_LAYERS):
                continue
            if a in used or b in used:
                continue
            used.update((a, b))
            out.append((a, b))
        return out


# --------------------------------------------------------------------------- built-in standard

#: The user's standard stack (mechanical_layer.stackup, 2026-08-22): number, name, kind, enabled.
_STANDARD_LAYERS: Final[tuple[tuple[int, str, str | None, bool], ...]] = (
    (1, "Board Shape", "BoardShape", True),
    (2, "Route Tool Path", "RouteToolPath", True),
    (3, "Dimensions", "Dimensions", True),
    (4, "Hole Detail", None, True),
    (5, "DXF Import", None, True),
    (6, "V Cut", "VCut", True),
    (7, "Board (Details)", "Board", True),
    (8, "User Info", None, True),
    (9, "Top Assembly", "AssemblyTop", True),
    (10, "Bottom Assembly", "AssemblyBottom", True),
    (11, "Top Designator", "DesignatorTop", True),
    (12, "Bottom Designator", "DesignatorBottom", True),
    (13, "Top 3D Body", "3DBodyTop", True),
    (14, "Bottom 3D Body", "3DBodyBottom", True),
    (15, "Top Courtyard", "CourtyardTop", True),
    (16, "Bottom Courtyard", "CourtyardBottom", True),
    (17, "Top Component Center", "ComponentCenterTop", True),
    (18, "Bottom Component Center", "ComponentCenterBottom", True),
    (19, "Top Value", "ValueTop", True),
    (20, "Bottom Value", "ValueBottom", True),
    (21, "Top Component Outline", "ComponentOutlineTop", True),
    (22, "Bottom Component Outline", "ComponentOutlineBottom", True),
    (23, "Top Dimensions", "DimensionsTop", True),
    (24, "Bottom Dimensions", "DimensionsBottom", True),
    (25, "Top Gold Plating", "GoldPlatingTop", True),
    (26, "Bottom Gold Plating", "GoldPlatingBottom", True),
    (27, "Top Glue Points", "GluePointsTop", True),
    (28, "Bottom Glue Points", "GluePointsBottom", True),
    (29, "Top Conformal Coat", "CoatingTop", True),
    (30, "Bottom Conformal Coat", "CoatingBottom", True),
    (31, "Component Cavity (Embedded Components)", None, True),
    (32, "Mechanical 32", None, False),
    (33, "Bottom Stiffener", None, False),
    (34, "Fabrication Notes", "FabNotes", True),
    (35, "Assembly Notes", "AssemblyNotes", True),
    (36, "Title Block", "Sheet", True),
    (37, "Title Block Mirrored", None, True),
    (38, "Continuation Block", None, True),
    (39, "Continuation Block Mirrored", None, True),
    (41, "Panel Dimension", None, True),
    (42, "Panel Fabrication Notes", None, True),
    (43, "Panel Assembly Notes", None, True),
    (44, "Panel Title Block", None, True),
    (45, "Panel Title Block Mirrored", None, True),
    (46, "Panel Continuation Block", None, True),
    (47, "Panel Continuation Block Mirrored", None, True),
    (49, "Top PSA (Pressure Sensitive Adhesive)", None, True),
    (50, "Bottom PSA (Pressure Sensitive Adhesive)", None, True),
    (51, "Top Stiffener", None, True),
    (52, "Bottom Stiffener", None, True),
    (53, "Flex Bend Lines", None, True),
)
_STANDARD_PAIRS: Final[tuple[tuple[int, int], ...]] = (
    (15, 16), (13, 14), (9, 10), (11, 12), (17, 18), (19, 20), (21, 22),
    (23, 24), (25, 26), (27, 28), (29, 30), (49, 50), (51, 52),
)


def default_stack() -> LayerStack:
    """Built-in copy of the user's standard stack (fresh object, safe to modify)."""
    return LayerStack(
        name="PartForge-Standard (Mechanical_Stackup_Standard)",
        source="builtin",
        layers={n: MechLayer(number=n, name=name, kind=kind, enabled=enabled) for n, name, kind, enabled in _STANDARD_LAYERS},
        pairs=list(_STANDARD_PAIRS),
    )


# --------------------------------------------------------------------------- parsing


def _layer_number(raw: str | None) -> int | None:
    """Mechanical layer number of a V7/V8/V9 layer id (``16908289`` -> 1), else ``None``."""
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except ValueError:
        return None
    number = value - MECH_LAYER_ID_BASE
    return number if 1 <= number <= MAX_MECH_LAYER else None


def _clean_value(value: str) -> str:
    return value.replace("\x00", "").strip()


def _key_values(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for segment in text.replace("\x00", "").split("|"):
        key, sep, value = segment.partition("=")
        key = key.strip()
        if sep and key:
            pairs.append((key, _clean_value(value)))
    return pairs


_STACK_GROUP_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("v9", re.compile(r"^V9_CACHE_LAYER(\d+)_([A-Z0-9_]+)$")),
    ("v9stack", re.compile(r"^V9_STACK_LAYER(\d+)_([A-Z0-9_]+)$")),
    ("v8", re.compile(r"^LAYER_V8_(\d+)([A-Z_]+)$")),
    ("v7", re.compile(r"^LAYERV7_(\d+)([A-Z_]+)$")),
    ("legacy", re.compile(r"^LAYER(\d+)([A-Z_]+)$")),
)


def _stack_groups(pairs: Iterable[tuple[str, str]]) -> dict[str, dict[int, dict[str, str]]]:
    groups: dict[str, dict[int, dict[str, str]]] = {}
    for key, value in pairs:
        for kind, pattern in _STACK_GROUP_PATTERNS:
            m = pattern.match(key)
            if m:
                groups.setdefault(kind, {}).setdefault(int(m.group(1)), {})[m.group(2)] = value
                break
    return groups


def _layers_from_groups(groups: Mapping[str, Mapping[int, Mapping[str, str]]]) -> dict[int, MechLayer]:
    """Mechanical layers, preferring the V9 cache, then the V8 stack, then the legacy keys."""
    found: dict[int, MechLayer] = {}

    def add(number: int, fields: Mapping[str, str]) -> None:
        if number in found or not 1 <= number <= MAX_MECH_LAYER:
            return
        name = fields.get("NAME", "").strip() or f"Mechanical {number}"
        kind = fields.get("MECHKIND", "").strip() or None
        if kind is not None and not _KIND_RE.match(kind):
            kind = None
        enabled = fields.get("MECHENABLED", "FALSE").strip().upper() == "TRUE"
        found[number] = MechLayer(number=number, name=name, kind=kind, enabled=enabled)

    for kind in ("v9", "v9stack", "v8", "v7"):
        for _index, fields in sorted(groups.get(kind, {}).items()):
            number = _layer_number(fields.get("LAYERID"))
            if number is not None:
                add(number, fields)
    for index, fields in sorted(groups.get("legacy", {}).items()):
        number = index - LEGACY_MECH_OFFSET
        if 1 <= number <= LEGACY_MECH_LAYERS and "NAME" in fields:
            add(number, fields)
    return dict(sorted(found.items()))


def _pairs_from(pairs: Iterable[tuple[str, str]]) -> list[tuple[int, int]]:
    by_index: dict[int, dict[str, int]] = {}
    for key, value in pairs:
        m = re.match(r"^MECHPAIR(\d+)L([12])$", key)
        if not m:
            continue
        v = _MECHPAIR_VALUE_RE.match(value.strip())
        if v:
            by_index.setdefault(int(m.group(1)), {})[m.group(2)] = int(v.group(1))
    out: list[tuple[int, int]] = []
    for _index, sides in sorted(by_index.items()):
        a, b = sides.get("1"), sides.get("2")
        if a is not None and b is not None and a != b and 1 <= a <= MAX_MECH_LAYER and 1 <= b <= MAX_MECH_LAYER:
            out.append((a, b))
    return out


def parse_stackup_text(text: str, *, source: str = "", name: str = "") -> LayerStack:
    """Parse the ``KEY=VALUE|…`` text of an Altium ``.stackup`` file (or a PcbLib/PcbDoc header).

    Mechanical layers are identified by their layer id (``0x01020000 + n``); raises
    :class:`StackupError` if the text contains none.
    """
    pairs = _key_values(text)
    layers = _layers_from_groups(_stack_groups(pairs))
    if not layers:
        raise StackupError(
            f"In {source or 'der Lagen-Datei'} wurden keine Mechanik-Lagen gefunden. Bitte eine in Altium "
            "exportierte .stackup-Datei wählen (Layer Stack Manager › Datei › Speichern)."
        )
    return LayerStack(name=name, source=source or "text", layers=layers, pairs=_pairs_from(pairs))


def parse_stackup(path: str | os.PathLike[str]) -> LayerStack:
    """Read an Altium ``.stackup`` file (ANSI text, one line of ``KEY=VALUE|…``)."""
    file = Path(path)
    try:
        raw = file.read_bytes()
    except FileNotFoundError as exc:
        raise StackupError(f"Die Lagen-Datei {file} wurde nicht gefunden.") from exc
    except OSError as exc:
        raise StackupError(f"Die Lagen-Datei {file} konnte nicht gelesen werden: {exc}") from exc
    if len(raw) > 20_000_000:
        raise StackupError(f"Die Lagen-Datei {file.name} ist zu groß für eine .stackup-Datei.")
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "=" not in text or "|" not in text:
        raise StackupError(f"{file.name} ist keine Altium-Lagen-Datei (.stackup).")
    return parse_stackup_text(text, source=str(file), name=file.stem)


# --------------------------------------------------------------------------- layer map


def suggest_layer_map(stack: LayerStack, base: LayerMap | None = None) -> LayerMap:
    """A :class:`LayerMap` whose roles sit on the stack's layers of the matching kind.

    ``AssemblyTop`` -> assembly, ``DesignatorTop`` -> designator, ``3DBodyTop`` -> body3d,
    ``CourtyardTop`` -> courtyard, ``ComponentCenterTop`` -> component_center, ``ValueTop`` ->
    comment, ``ComponentOutlineTop`` -> component_outline. Roles without a matching layer in
    Mechanical 1..32 keep the value of ``base`` (default: the built-in LayerMap).
    """
    result = (base or LayerMap()).model_copy(deep=True)
    for role, kind in LAYER_MAP_KINDS.items():
        layer = stack.by_kind(kind)
        if layer is not None:
            setattr(result, role, L.mechanical_name(layer.number))
    return result


def _role_layers(layer_map: LayerMap) -> dict[str, int]:
    """LayerMap role -> mechanical layer number (roles on non-mechanical layers omitted)."""
    out: dict[str, int] = {}
    for role in LAYER_MAP_KINDS:
        number = L.mechanical_number(getattr(layer_map, role))
        if number is not None:
            out[role] = number
    return out


def layer_map_issues(stack: LayerStack, layer_map: LayerMap) -> list[str]:
    """German hints where the workspace LayerMap and the layer stack disagree."""
    issues: list[str] = []
    for role, number in _role_layers(layer_map).items():
        label = ROLE_LABELS[role]
        expected = LAYER_MAP_KINDS[role]
        layer = stack.layer(number)
        if layer is None:
            issues.append(
                f"{label}: Mechanical {number} ist im Lagenaufbau nicht definiert – PartForge legt sie in den "
                f"Bibliotheken als „{ROLE_NAMES[role]}“ an."
            )
            continue
        if layer.kind and layer.kind != expected:
            issues.append(
                f"{label}: Mechanical {number} ist im Lagenaufbau „{layer.name}“ (Typ {layer.kind}), erwartet wird "
                f"Typ {expected}. Bitte die Lagenzuordnung prüfen."
            )
        if not layer.enabled:
            issues.append(
                f"{label}: Mechanical {number} ({layer.name}) ist im Lagenaufbau deaktiviert – PartForge aktiviert sie "
                "in den Footprint-Bibliotheken."
            )
    counts: dict[int, list[str]] = {}
    for role, number in _role_layers(layer_map).items():
        counts.setdefault(number, []).append(ROLE_LABELS[role])
    for number, roles in sorted(counts.items()):
        if len(roles) > 1:
            issues.append(f"Mechanical {number} trägt mehrere Rollen: {', '.join(roles)}.")
    return issues


def effective_stack(stack: LayerStack, layer_map: LayerMap) -> LayerStack:
    """Copy of ``stack`` in which every mechanical layer the LayerMap writes to is enabled.

    Layers the stack does not define get the role's standard name (and its kind when no
    other header layer has that kind yet).
    """
    result = stack.model_copy(deep=True)
    for role, number in _role_layers(layer_map).items():
        if number > HEADER_MECH_LAYERS:
            continue
        layer = result.layers.get(number)
        if layer is None:
            kind = LAYER_MAP_KINDS[role]
            taken = any(other.kind == kind for n, other in result.layers.items() if n <= HEADER_MECH_LAYERS)
            result.layers[number] = MechLayer(number=number, name=ROLE_NAMES[role], kind=None if taken else kind)
        elif not layer.enabled:
            result.layers[number] = layer.model_copy(update={"enabled": True})
    result.layers = dict(sorted(result.layers.items()))
    return result


_stack_cache: dict[tuple[str, int, int], LayerStack] = {}
_stack_cache_lock = threading.Lock()


def _cached_parse(path: Path) -> LayerStack:
    stat = path.stat()
    key = (os.path.normcase(str(path.resolve())), stat.st_mtime_ns, stat.st_size)
    with _stack_cache_lock:
        cached = _stack_cache.get(key)
    if cached is not None:
        return cached.model_copy(deep=True)
    stack = parse_stackup(path)
    with _stack_cache_lock:
        if len(_stack_cache) > 32:
            _stack_cache.clear()
        _stack_cache[key] = stack
    return stack.model_copy(deep=True)


def workspace_stack(ws: Workspace | None) -> tuple[LayerStack, list[str]]:
    """The layer stack of a workspace (``layer_stackup`` file or the built-in standard).

    A configured file that cannot be read falls back to the standard with a German warning.
    """
    if ws is None or not ws.settings.layer_stackup:
        return default_stack(), []
    path = ws.abs(ws.settings.layer_stackup)
    assert path is not None
    try:
        return _cached_parse(path), []
    except (StackupError, OSError) as exc:
        log.warning("Lagen-Datei %s nicht lesbar: %s", path, exc)
        return default_stack(), [
            f"Die Lagen-Datei {path} ist nicht lesbar ({exc}) – es wird der eingebaute Standard-Lagenaufbau verwendet."
        ]


# --------------------------------------------------------------------------- header text model


class _Unexpected(Exception):
    """Internal: the PcbLib does not have the structure the patch expects."""


@dataclass
class _Segment:
    raw: bytes

    @property
    def key(self) -> bytes | None:
        key, sep, _ = self.raw.partition(b"=")
        return key if sep else None

    @property
    def value(self) -> bytes:
        return self.raw.partition(b"=")[2]

    def with_value(self, value: bytes) -> _Segment:
        """Same key with a new value; a trailing CR of the old value (record break) is kept."""
        key = self.key or b""
        suffix = b"\r" if self.value.endswith(b"\r") else b""
        return _Segment(key + b"=" + value + suffix)


def _split_library_data(data: bytes) -> tuple[list[_Segment], bytes]:
    """``Library/Data`` = u32 length + ``|KEY=VALUE…`` text + NUL, then the component list."""
    if len(data) < 6:
        raise _Unexpected("Library/Data ist zu kurz")
    (length,) = struct.unpack_from("<I", data, 0)
    if length < 2 or 4 + length > len(data):
        raise _Unexpected("ungültige Längenangabe im Kopf von Library/Data")
    text = data[4 : 4 + length]
    if not text.endswith(b"\x00") or b"\x00" in text[:-1]:
        raise _Unexpected("Kopftext von Library/Data ist nicht nullterminiert")
    if not text.startswith(b"|"):
        raise _Unexpected("Kopftext von Library/Data beginnt nicht mit '|'")
    segments = [_Segment(raw) for raw in text[1:-1].split(b"|")]
    return segments, data[4 + length :]


def _join_library_data(segments: list[_Segment], trailer: bytes) -> bytes:
    text = b"|" + b"|".join(s.raw for s in segments) + b"\x00"
    return struct.pack("<I", len(text)) + text + trailer


_HEADER_GROUPS: Final[tuple[tuple[str, re.Pattern[bytes]], ...]] = (
    ("v9", re.compile(rb"^V9_CACHE_LAYER(\d+)_([A-Z0-9_]+)$")),
    ("v8", re.compile(rb"^LAYER_V8_(\d+)([A-Z_]+)$")),
    ("v7", re.compile(rb"^LAYERV7_(\d+)([A-Z_]+)$")),
    ("legacy", re.compile(rb"^LAYER(\d+)([A-Z_]+)$")),
    ("layerset", re.compile(rb"^LAYERSET(\d+)([A-Z_.0-9]+)$")),
)
_MECHPAIR_KEY: Final = re.compile(rb"^MECHPAIR(\d+)L([12])$")
#: Field after which ``MECHKIND`` is inserted when a layer gets a kind (Altium/Rust key order).
_KIND_AFTER: Final[dict[str, tuple[bytes, ...]]] = {
    "v9": (b"MECHENABLED",),
    "v8": (b"MECHENABLED",),
    "legacy": (b"COPTHICK", b"MECHENABLED"),
    "v7": (b"COPTHICK", b"MECHENABLED"),
}
_MECH_SET_NAMES: Final = (b"&All Layers", b"&Mechanical Layers")


@dataclass
class _Group:
    fields: dict[bytes, int]  # field -> segment index


class _Header:
    """Index of the layer-related groups of a ``Library/Data`` header."""

    def __init__(self, segments: list[_Segment]):
        self.segments = segments
        self.groups: dict[str, dict[int, _Group]] = {}
        self.mechpairs: list[int] = []
        for index, segment in enumerate(segments):
            key = segment.key
            if key is None:
                continue
            if _MECHPAIR_KEY.match(key):
                self.mechpairs.append(index)
                continue
            for kind, pattern in _HEADER_GROUPS:
                m = pattern.match(key)
                if m:
                    group = self.groups.setdefault(kind, {}).setdefault(int(m.group(1)), _Group(fields={}))
                    if m.group(2) in group.fields:
                        raise _Unexpected(f"doppelter Schlüssel {key.decode('ascii', 'replace')}")
                    group.fields[m.group(2)] = index
                    break

    def value(self, group: _Group, field: bytes) -> bytes | None:
        index = group.fields.get(field)
        return None if index is None else self.segments[index].value.rstrip(b"\r")

    def by_layer_id(self, kind: str) -> dict[int, _Group]:
        out: dict[int, _Group] = {}
        for _index, group in sorted(self.groups.get(kind, {}).items()):
            raw = self.value(group, b"LAYERID")
            number = _layer_number(raw.decode("ascii", "replace")) if raw is not None else None
            if number is None or number > HEADER_MECH_LAYERS:
                continue
            if number in out:
                raise _Unexpected(f"Mechanical {number} ist in der {kind}-Darstellung mehrfach vorhanden")
            out[number] = group
        return out

    def mech_groups(self) -> dict[int, list[tuple[str, _Group]]]:
        """Mechanical 1..32 -> every representation (kind, group); raises if one is missing."""
        v9 = self.by_layer_id("v9")
        v8 = self.by_layer_id("v8")
        v7 = self.by_layer_id("v7")
        legacy = self.groups.get("legacy", {})
        out: dict[int, list[tuple[str, _Group]]] = {}
        for number in range(1, HEADER_MECH_LAYERS + 1):
            reps: list[tuple[str, _Group]] = []
            for kind, table in (("v9", v9), ("v8", v8)):
                if number not in table:
                    raise _Unexpected(f"Mechanical {number} fehlt in der {kind}-Darstellung")
                reps.append((kind, table[number]))
            if number <= LEGACY_MECH_LAYERS:
                group = legacy.get(LEGACY_MECH_OFFSET + number)
                if group is None or b"NAME" not in group.fields:
                    raise _Unexpected(f"Mechanical {number} fehlt in der alten Lagen-Darstellung (LAYER{56 + number})")
                reps.append(("legacy", group))
            else:
                if number not in v7:
                    raise _Unexpected(f"Mechanical {number} fehlt in der V7-Darstellung")
                reps.append(("v7", v7[number]))
            for kind, group in reps:
                for field in (b"NAME", b"MECHENABLED"):
                    if field not in group.fields:
                        raise _Unexpected(
                            f"Mechanical {number}: Feld {field.decode()} fehlt in der {kind}-Darstellung"
                        )
            out[number] = reps
        return out


# --------------------------------------------------------------------------- header patch


def _header_name(name: str, number: int) -> bytes:
    """ASCII layer name for the header (no '|', no control characters)."""
    text = clean_free_text(name)
    text = "".join(TRANSLITERATION.get(ch, ch) for ch in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if 32 <= ord(ch) < 127 and not unicodedata.combining(ch))
    text = re.sub(r"\s+", " ", text).replace("|", "/").strip()[:_MAX_NAME_LENGTH].strip()
    return (text or f"Mechanical {number}").encode("ascii")


def _kind_token(kind: str | None) -> bytes | None:
    if not kind:
        return None
    if not _KIND_RE.match(kind):
        raise StackupError(f"Ungültiger Lagentyp {kind!r} (erwartet z. B. AssemblyTop).")
    return kind.encode("ascii")


@dataclass
class _Plan:
    """Edits of the header segments (by original index); record breaks (CR) stay in place."""

    replace: dict[int, _Segment]
    insert_after: dict[int, list[_Segment]]
    delete: set[int]

    def touched_keys(self, segments: list[_Segment]) -> set[bytes]:
        keys = {segments[i].key for i in (*self.replace, *self.delete)}
        keys |= {s.key for items in self.insert_after.values() for s in items}
        return {k for k in keys if k is not None}

    def apply(self, segments: list[_Segment]) -> list[_Segment]:
        out: list[_Segment] = []
        for index, segment in enumerate(segments):
            if index in self.delete:
                if segment.raw.endswith(b"\r") and out:  # a removed segment's record break moves back
                    out[-1] = _Segment(out[-1].raw.rstrip(b"\r") + b"\r")
            else:
                out.append(self.replace.get(index, segment))
            inserted = [_Segment(s.raw.rstrip(b"\r")) for s in self.insert_after.get(index, [])]
            if inserted:
                if out and out[-1].raw.endswith(b"\r"):  # the record break follows the inserted keys
                    out[-1] = _Segment(out[-1].raw[:-1])
                    inserted[-1] = _Segment(inserted[-1].raw + b"\r")
                out.extend(inserted)
        return out


def _plan_patch(header: _Header, stack: LayerStack) -> _Plan:
    plan = _Plan(replace={}, insert_after={}, delete=set())
    wanted = stack.header_layers()
    segments = header.segments
    for number, reps in header.mech_groups().items():
        layer = wanted[number]
        name = _header_name(layer.name, number)
        enabled = b"TRUE" if layer.enabled else b"FALSE"
        kind = _kind_token(layer.kind)
        for rep_kind, group in reps:
            for field, value in ((b"NAME", name), (b"MECHENABLED", enabled)):
                index = group.fields[field]
                if segments[index].value.rstrip(b"\r") != value:
                    plan.replace[index] = segments[index].with_value(value)
            kind_index = group.fields.get(b"MECHKIND")
            if kind is None:
                if kind_index is not None:
                    plan.delete.add(kind_index)
            elif kind_index is not None:
                if segments[kind_index].value.rstrip(b"\r") != kind:
                    plan.replace[kind_index] = segments[kind_index].with_value(kind)
            else:
                anchor = next((group.fields[f] for f in _KIND_AFTER[rep_kind] if f in group.fields), None)
                if anchor is None:  # pragma: no cover - MECHENABLED is checked in mech_groups()
                    raise _Unexpected(f"Mechanical {number}: keine Einfügeposition für MECHKIND")
                prefix = segments[group.fields[b"NAME"]].key or b""
                key = prefix[: -len(b"NAME")] + b"MECHKIND"
                plan.insert_after.setdefault(anchor, []).append(_Segment(key + b"=" + kind))
    _plan_pairs(header, stack, plan)
    _plan_layer_sets(header, stack, plan)
    return plan


def _pair_segments(stack: LayerStack) -> list[bytes]:
    return [
        f"MECHPAIR{i}L{side}=MECHANICAL{number}".encode("ascii")
        for i, (a, b) in enumerate(stack.header_pairs())
        for side, number in ((1, a), (2, b))
    ]


def _plan_pairs(header: _Header, stack: LayerStack, plan: _Plan) -> None:
    """Replace the contiguous ``MECHPAIR`` block by the stack's pairs (Mechanical 1..32)."""
    new = _pair_segments(stack)
    old = header.mechpairs
    if [header.segments[i].raw.rstrip(b"\r") for i in old] == new:
        return
    if not old:
        if new:
            raise _Unexpected("keine Lagenpaare (MECHPAIR) im Kopf")
        return
    if old != list(range(old[0], old[-1] + 1)):
        raise _Unexpected("die Lagenpaare (MECHPAIR) stehen nicht zusammen")
    break_after = header.segments[old[-1]].raw.endswith(b"\r")
    for position, index in enumerate(old):
        if position < len(new):
            raw = new[position]
            if position == len(old) - 1 and break_after:
                raw += b"\r"  # apply() moves the record break behind pairs inserted after it
            plan.replace[index] = _Segment(raw)
        else:
            plan.delete.add(index)  # apply() moves the record break back to the last kept pair
    if len(new) > len(old):
        plan.insert_after[old[-1]] = [_Segment(raw) for raw in new[len(old) :]]


_MECH_TOKEN_RE: Final = re.compile(rb"Mechanical\d{1,2}")


def _mech_tokens(numbers: Iterable[int]) -> list[bytes]:
    return [f"Mechanical{n}".encode("ascii") for n in numbers]


def _rebuild_layer_set(name: bytes, tokens: list[bytes], low: list[int], high: list[int]) -> list[bytes]:
    """Layer list of a mechanical layer set with the enabled layers of the stack.

    Native layout (Altium example ``Harness Demo MB/Libs/PCB1.PcbLib``): "&All Layers" lists
    Mech 1-16 directly before ``DrillDrawing`` and Mech 17-32 directly after it;
    "&Mechanical Layers" lists every enabled mechanical layer in numeric order.
    """
    is_mech = [bool(_MECH_TOKEN_RE.fullmatch(t)) for t in tokens]
    others = [t for t, mech in zip(tokens, is_mech, strict=True) if not mech]
    position = len(others)
    if any(is_mech):
        first = is_mech.index(True)
        position = sum(1 for mech in is_mech[:first] if not mech)
    if name == b"&All Layers" and b"DrillDrawing" in others:
        at = others.index(b"DrillDrawing")
        return others[:at] + _mech_tokens(low) + [b"DrillDrawing"] + _mech_tokens(high) + others[at + 1 :]
    if name == b"&Mechanical Layers" and not any(is_mech):
        position = 0
    return others[:position] + _mech_tokens([*low, *high]) + others[position:]


def _plan_layer_sets(header: _Header, stack: LayerStack, plan: _Plan) -> None:
    layers = stack.header_layers()
    low = [n for n, layer in layers.items() if layer.enabled and n <= LEGACY_MECH_LAYERS]
    high = [n for n, layer in layers.items() if layer.enabled and n > LEGACY_MECH_LAYERS]
    for _index, group in sorted(header.groups.get("layerset", {}).items()):
        name = header.value(group, b"NAME")
        if name not in _MECH_SET_NAMES or b"LAYERS" not in group.fields:
            continue
        index = group.fields[b"LAYERS"]
        raw_value = header.segments[index].value.rstrip(b"\r")
        tokens = [t for t in raw_value.split(b",") if t] if raw_value else []
        value = b",".join(_rebuild_layer_set(name, tokens, low, high))
        if value != raw_value:
            plan.replace[index] = header.segments[index].with_value(value)


def _expected_values(layer: MechLayer) -> tuple[bytes, bytes, bytes | None]:
    return _header_name(layer.name, layer.number), b"TRUE" if layer.enabled else b"FALSE", _kind_token(layer.kind)


def _check_patched(original: list[_Segment], patched: list[_Segment], stack: LayerStack, touched: set[bytes]) -> None:
    """Self-check: every representation has the wanted values and only touched keys changed."""
    header = _Header(patched)
    wanted = stack.header_layers()
    for number, reps in header.mech_groups().items():
        expected = _expected_values(wanted[number])
        for rep_kind, group in reps:
            values = (header.value(group, b"NAME"), header.value(group, b"MECHENABLED"), header.value(group, b"MECHKIND"))
            if values != expected:
                raise _Unexpected(f"Selbstprüfung: Mechanical {number} ({rep_kind}) stimmt nach dem Ändern nicht")
    if header.mechpairs and [header.segments[i].raw.rstrip(b"\r") for i in header.mechpairs] != _pair_segments(stack):
        raise _Unexpected("Selbstprüfung: Lagenpaare stimmen nach dem Ändern nicht")

    def untouched(segments: list[_Segment]) -> list[bytes]:
        return [s.raw.rstrip(b"\r") for s in segments if s.key is None or s.key not in touched]

    if untouched(original) != untouched(patched):
        raise _Unexpected("Selbstprüfung: außerhalb der Mechanik-Lagen wurde etwas verändert")
    if sum(s.raw.count(b"\r") for s in original) != sum(s.raw.count(b"\r") for s in patched):
        raise _Unexpected("Selbstprüfung: Datensatzgrenzen im Kopf verschoben")


# --------------------------------------------------------------------------- structured storage I/O
# Shared with the footprint-height patch (:mod:`partforge.altium.compound`); the private names
# stay for the tests and for :func:`_replace_with_patched`.

_open_root = compound.open_root
_read_tree_file = compound.read_tree_file
_read_streams = compound.read_streams


def read_library_data(path: str | os.PathLike[str]) -> bytes:
    """Raw ``Library/Data`` stream of a PcbLib (ole32, read-only)."""
    data = _read_streams(Path(path), ["Library/Data"]).get("Library/Data")
    if data is None:
        raise StackupError(f"{Path(path).name} enthält keinen Bibliothekskopf (Library/Data).")
    return data


def _write_library_data(path: Path, data: bytes) -> None:
    """Replace ``Library/Data`` of ``path`` (transacted read-modify-write commit)."""
    compound.write_streams(path, {"Library/Data": data})


def _check_kind_mapping(raw: bytes | None) -> None:
    """``Library/LayerKindMapping/Data`` must be absent or the empty form the Rust writer writes."""
    if raw is None:
        return
    if len(raw) < 12:
        raise _Unexpected("Library/LayerKindMapping ist zu kurz")
    (size,) = struct.unpack_from("<I", raw, 0)
    offset = 4 + size
    if size > 64 or len(raw) < offset + 8:
        raise _Unexpected("Library/LayerKindMapping hat ein unbekanntes Format")
    (count,) = struct.unpack_from("<I", raw, offset + 4)
    if count:
        raise _Unexpected(
            "die Datei enthält eine von Altium gespeicherte Lagentyp-Tabelle (LayerKindMapping) – sie wird nicht verändert"
        )


def header_patch_enabled() -> bool:
    """``HEADER_PATCH_ENABLED`` and not switched off by ``PARTFORGE_LAYER_PATCH=0``."""
    return HEADER_PATCH_ENABLED and os.environ.get(PATCH_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def patch_pcblib_layers(
    path: str | os.PathLike[str],
    stack: LayerStack,
    *,
    verify: Callable[[Path], None] | None = None,
) -> list[str]:
    """Rewrite the mechanical layers in the ``Library/Data`` header of a PcbLib to ``stack``.

    Names, ``MECHENABLED`` and ``MECHKIND`` of Mechanical 1..32 in every representation
    (V9 cache, V8 stack, legacy/V7), the layer pairs and the mechanical layer sets are set
    from ``stack``; everything else stays byte-identical. Idempotent: an already matching
    header is not rewritten.

    The change is made on a copy beside the library, checked (ole32 re-read of the whole
    file; ``verify(copy)`` – e.g. a Rust-reader listing – may raise to reject it) and then
    moved over the library. Returns German warnings; on any problem the library is left
    untouched and the warning explains why.
    """
    library = Path(os.path.abspath(os.fspath(path)))
    if library.suffix.lower() != ".pcblib":
        return [f"{library.name}: Lagen-Kopf nur bei Footprint-Bibliotheken (.PcbLib) – nichts geändert."]
    if not library.is_file():
        return [f"{library.name}: Bibliothek nicht gefunden – Lagen-Kopf nicht geändert."]
    try:
        streams = _read_streams(library, ["Library/Data", "Library/LayerKindMapping/Data"])
        data = streams.get("Library/Data")
        if data is None:
            raise _Unexpected("Library/Data fehlt")
        _check_kind_mapping(streams.get("Library/LayerKindMapping/Data"))
        segments, trailer = _split_library_data(data)
        header = _Header(segments)
        plan = _plan_patch(header, stack)
        patched = plan.apply(segments)
        if [s.raw for s in patched] == [s.raw for s in segments]:
            return []
        _check_patched(segments, patched, stack, plan.touched_keys(segments))
        new_data = _join_library_data(patched, trailer)
    except StackupError as exc:
        return [f"{library.name}: Lagen-Kopf nicht geändert – {exc}"]
    except _Unexpected as exc:
        log.warning("Lagen-Kopf von %s nicht geändert: %s", library, exc)
        return [f"{library.name}: Lagen-Kopf nicht an den Lagenaufbau angepasst – unerwarteter Aufbau ({exc})."]
    except Exception as exc:  # noqa: BLE001 - pywintypes.com_error and friends: never fail a write
        log.warning("Lagen-Kopf von %s nicht lesbar: %s", library, exc, exc_info=True)
        return [f"{library.name}: Lagen-Kopf nicht lesbar ({exc}) – nichts geändert."]
    return _replace_with_patched(library, new_data, verify)


def _replace_with_patched(library: Path, new_data: bytes, verify: Callable[[Path], None] | None) -> list[str]:
    try:
        compound.replace_streams(
            library,
            {"Library/Data": new_data},
            verify=verify,
            tag="pfhdr",
            write=lambda copy, streams: _write_library_data(copy, streams["Library/Data"]),
        )
    except (compound.CompoundError, _Unexpected) as exc:
        log.warning("Lagen-Kopf von %s nicht geändert: %s", library, exc)
        return [f"{library.name}: Lagen-Kopf nicht an den Lagenaufbau angepasst – {exc}."]
    except Exception as exc:  # noqa: BLE001 - COM, OS and verify errors leave the library untouched
        log.warning("Lagen-Kopf von %s nicht geändert: %s", library, exc, exc_info=True)
        return [f"{library.name}: Lagen-Kopf nicht an den Lagenaufbau angepasst ({exc}) – Bibliothek unverändert."]
    log.info("Lagen-Kopf von %s an den Lagenaufbau angepasst", library)
    return []


# --------------------------------------------------------------------------- reading


def read_pcblib_layers(path: str | os.PathLike[str]) -> dict[int, MechLayer]:
    """Mechanical layers 1..32 as the PcbLib header defines them (V9 cache preferred)."""
    segments, _ = _split_library_data_or_raise(path)
    text = b"|".join(s.raw for s in segments).decode("cp1252", "replace")
    layers = _layers_from_groups(_stack_groups(_key_values(text)))
    return {n: layer for n, layer in layers.items() if n <= HEADER_MECH_LAYERS}


def _split_library_data_or_raise(path: str | os.PathLike[str]) -> tuple[list[_Segment], bytes]:
    try:
        return _split_library_data(read_library_data(path))
    except _Unexpected as exc:
        raise StackupError(f"{Path(path).name}: unerwarteter Bibliothekskopf ({exc}).") from exc


def pcblib_layer_problems(path: str | os.PathLike[str], stack: LayerStack | None = None) -> list[str]:
    """German problems of a PcbLib layer header: representations that disagree with each
    other, and (with ``stack``) layers that differ from the stack. Empty = consistent."""
    try:
        segments, _ = _split_library_data_or_raise(path)
        header = _Header(segments)
        groups = header.mech_groups()
    except (StackupError, _Unexpected) as exc:
        return [str(exc)]
    except Exception as exc:  # noqa: BLE001 - COM errors on damaged files
        return [f"{Path(path).name}: Bibliothekskopf nicht lesbar ({exc})."]
    problems: list[str] = []
    wanted = stack.header_layers() if stack is not None else None
    for number, reps in groups.items():
        seen = {
            (header.value(g, b"NAME"), header.value(g, b"MECHENABLED"), header.value(g, b"MECHKIND")) for _k, g in reps
        }
        if len(seen) > 1:
            problems.append(f"Mechanical {number}: die Darstellungen im Bibliothekskopf widersprechen sich.")
            continue
        if wanted is not None:
            layer = wanted[number]
            name, enabled, kind = next(iter(seen))
            try:
                expected = _expected_values(layer)
            except StackupError as exc:
                problems.append(f"Mechanical {number}: {exc}")
                continue
            if (name, enabled, kind) != expected:
                found = (name or b"").decode("cp1252", "replace")
                detail = " (Typ/Aktivierung abweichend)" if (enabled, kind) != expected[1:] else ""
                problems.append(f"Mechanical {number}: „{found}“ statt „{layer.name}“{detail}.")
    if stack is not None:
        problems.extend(_pair_and_set_problems(header, stack))
    return problems


def _pair_and_set_problems(header: _Header, stack: LayerStack) -> list[str]:
    """Layer pairs and mechanical layer sets that a patch would still change."""
    problems: list[str] = []
    pairs = _Plan(replace={}, insert_after={}, delete=set())
    try:
        _plan_pairs(header, stack, pairs)
    except _Unexpected as exc:
        problems.append(f"Lagenpaare: {exc}.")
    else:
        if pairs.replace or pairs.insert_after or pairs.delete:
            problems.append("Die Lagenpaare im Bibliothekskopf weichen vom Lagenaufbau ab.")
    sets = _Plan(replace={}, insert_after={}, delete=set())
    _plan_layer_sets(header, stack, sets)
    if sets.replace:
        problems.append("Die Lagensätze „&All Layers“/„&Mechanical Layers“ weichen vom Lagenaufbau ab.")
    return problems
