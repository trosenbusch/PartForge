"""Layer sets (Altium *View Configuration › Layer Sets*) for the PcbLibs PartForge writes.

Altium stores the layer sets of a document in its header – ``LAYERSETSCOUNT`` and per set
``LAYERSET<n>NAME``, ``…LAYERS`` (comma-separated layer tokens), ``…ACTIVELAYER.7``, ``…ISCURRENT``,
``…ISLOCKED``, ``…FLIPBOARD`` – and exports single sets as ``.layerset`` files with exactly these keys
(VERIFIED: ``C:\\PartForge-Examples\\Altium_Templates\\Layersets\\Component.layerset``)::

    LAYERSET6NAME=Component Layers|LAYERSET6LAYERS=MultiLayer,TopPaste,…,Mechanical21|
    LAYERSET6ACTIVELAYER.7=TOP|LAYERSET6ISCURRENT=TRUE|LAYERSET6ISLOCKED=FALSE|LAYERSET6FLIPBOARD=FALSE

The workspace setting :class:`~partforge.workspace.LayerSetSettings` chooses the set every footprint
library gets (``mode``): none, the one built from the layer map (:func:`builtin_layer_set` – for the
standard map exactly the user's "Component Layers") or one read from a ``.layerset`` file (its layers are
stored in the settings, so the library folder stays self-contained). With ``current`` the set is the
active one when Altium opens the library. :mod:`partforge.altium.stackup` writes it into the header
(:func:`partforge.altium.stackup.patch_pcblib_layers`).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

from ..workspace import LayerMap, LayerSetSettings, Workspace
from . import layers as L

__all__ = [
    "LayerSetError",
    "LayerSetDef",
    "BUILTIN_NAME",
    "FIXED_COMPONENT_TOKENS",
    "parse_layerset_text",
    "parse_layerset_file",
    "builtin_layer_set",
    "token_for_layer",
    "layer_for_token",
    "token_problem",
    "resolve_layer_set",
    "workspace_layer_set",
]


class LayerSetError(ValueError):
    """A layer set or ``.layerset`` file cannot be used (German message)."""


#: Name of the set built from the layer map (the name of the user's own Altium set).
BUILTIN_NAME: Final = "Component Layers"
#: Non-mechanical layers of the built-in set, in Altium's order (``Component.layerset``).
FIXED_COMPONENT_TOKENS: Final = (
    "MultiLayer", "TopPaste", "TopOverlay", "TopSolder", "TopLayer", "BottomLayer", "DrillGuide", "KeepOutLayer",
)
_TOKENS: Final[dict[str, str]] = {
    "TopLayer": L.TOP_LAYER,
    "BottomLayer": L.BOTTOM_LAYER,
    "TopOverlay": L.TOP_OVERLAY,
    "BottomOverlay": L.BOTTOM_OVERLAY,
    "TopPaste": L.TOP_PASTE,
    "BottomPaste": L.BOTTOM_PASTE,
    "TopSolder": L.TOP_SOLDER,
    "BottomSolder": L.BOTTOM_SOLDER,
    "DrillGuide": L.DRILL_GUIDE,
    "KeepOutLayer": L.KEEP_OUT,
    "DrillDrawing": L.DRILL_DRAWING,
    "MultiLayer": L.MULTI_LAYER,
}
_TOKEN_OF: Final[dict[str, str]] = {v: k for k, v in _TOKENS.items()}
#: Mid layers 1–30, internal planes 1–16, mechanical layers 1–1024 (``stackup.MAX_MECH_LAYER``), no leading zeros
_EXTRA_TOKEN_RE: Final = re.compile(
    r"^(MidLayer([1-9]|[12]\d|30)|InternalPlane([1-9]|1[0-6])|Mechanical([1-9]\d{0,2}|10[01]\d|102[0-4])|ConnectLayer)$"
)
_KEY_RE: Final = re.compile(r"^LAYERSET(\d+)(NAME|LAYERS|ACTIVELAYER\.7|ISCURRENT|ISLOCKED|FLIPBOARD)$", re.IGNORECASE)
_ACTIVE_RE: Final = re.compile(r"^[A-Z0-9]{2,40}$")
MAX_NAME: Final = 60


class LayerSetDef(BaseModel):
    """One layer set as Altium stores it."""

    name: str
    layers: list[str] = Field(default_factory=list, description="Altium-Lagenkürzel, z. B. TopOverlay, Mechanical9")
    active_layer: str = Field(default="TOP", description="Aktive Lage beim Wechsel auf den Lagensatz (ACTIVELAYER.7)")
    current: bool = Field(default=True, description="Beim Öffnen der Bibliothek in Altium aktiv")
    locked: bool = False
    flip_board: bool = False

    def header_values(self) -> dict[str, str]:
        """``field -> value`` as written into a PcbLib header (``NAME``, ``LAYERS`` …)."""
        return {
            "NAME": self.name,
            "LAYERS": ",".join(self.layers),
            "ACTIVELAYER.7": self.active_layer,
            "ISCURRENT": "TRUE" if self.current else "FALSE",
            "ISLOCKED": "TRUE" if self.locked else "FALSE",
            "FLIPBOARD": "TRUE" if self.flip_board else "FALSE",
        }


def token_for_layer(name: str) -> str | None:
    """Altium layer-set token of a canonical layer name (``Mechanical 9`` -> ``Mechanical9``)."""
    try:
        canonical = L.normalize_layer_name(name)
    except L.LayerError:
        return None
    number = L.mechanical_number(canonical)
    if number is not None:
        return f"Mechanical{number}"
    m = re.fullmatch(r"Mid-Layer (\d+)", canonical)
    if m:
        return f"MidLayer{m.group(1)}"
    m = re.fullmatch(r"Internal Plane (\d+)", canonical)
    if m:
        return f"InternalPlane{m.group(1)}"
    return _TOKEN_OF.get(canonical)


def layer_for_token(token: str) -> str | None:
    """Readable layer name of a token (``Mechanical9`` -> ``Mechanical 9``), ``None`` if unknown."""
    if token in _TOKENS:
        return _TOKENS[token]
    m = _EXTRA_TOKEN_RE.match(token)
    if not m:
        return None
    if token.startswith("MidLayer"):
        return f"Mid-Layer {token[8:]}"
    if token.startswith("InternalPlane"):
        return f"Internal Plane {token[13:]}"
    if token.startswith("Mechanical"):
        return f"Mechanical {token[10:]}"
    return "Connect Layer"


def token_problem(token: str) -> str | None:
    """German problem of a layer token, ``None`` if Altium knows it."""
    if token in _TOKENS or _EXTRA_TOKEN_RE.match(token):
        return None
    return f"Unbekannte Lage „{token}“ im Lagensatz."


def _header_char(ch: str) -> str:
    """``ch`` if a PcbLib header (Windows-1252) can hold it, else ``_``."""
    try:
        ch.encode("cp1252")
    except UnicodeEncodeError:
        return "_"
    return ch


def _clean_name(name: str) -> str:
    """Name as the PcbLib header holds it: Windows-1252 only (other characters – also U+FFFD of an undecodable
    byte – become ``_``, so the header and the set PartForge looks for always match), no separators or control
    characters, at most :data:`MAX_NAME` characters."""
    text = re.sub(r"[\x00-\x1f|=]", " ", name or "")
    text = "".join(_header_char(ch) for ch in text).strip()
    return re.sub(r"\s+", " ", text)[:MAX_NAME].strip()


def _check(definition: LayerSetDef) -> LayerSetDef:
    name = _clean_name(definition.name)
    if not name:
        raise LayerSetError("Der Lagensatz braucht einen Namen.")
    if name.startswith("&"):
        raise LayerSetError(f"„{name}“ ist ein Altium-Standardsatz – bitte einen eigenen Lagensatz wählen.")
    layers: list[str] = []
    for token in definition.layers:
        token = token.strip()
        if not token:
            continue
        problem = token_problem(token)
        if problem:
            raise LayerSetError(problem)
        if token not in layers:
            layers.append(token)
    if not layers:
        raise LayerSetError(f"Der Lagensatz „{name}“ enthält keine Lagen.")
    active = (definition.active_layer or "TOP").strip().upper()
    if not _ACTIVE_RE.match(active):
        active = "TOP"
    return definition.model_copy(update={"name": name, "layers": layers, "active_layer": active})


def parse_layerset_text(text: str, *, source: str = "") -> list[LayerSetDef]:
    """Every layer set of a ``.layerset`` text (any ``LAYERSET<n>`` numbering; user sets only)."""
    groups: dict[int, dict[str, str]] = {}
    text = text.lstrip("\ufeff")  # a UTF-8 BOM (hand-edited file) would hide the first key
    for segment in text.replace("\x00", "").replace("\r", "|").replace("\n", "|").split("|"):
        key, sep, value = segment.partition("=")
        m = _KEY_RE.match(key.strip())
        if sep and m:
            groups.setdefault(int(m.group(1)), {})[m.group(2).upper()] = value.strip()
    out: list[LayerSetDef] = []
    for _index, fields in sorted(groups.items()):
        name = fields.get("NAME", "")
        if not name or name.startswith("&"):
            continue
        layers = [t for t in fields.get("LAYERS", "").split(",") if t.strip()]
        definition = LayerSetDef(
            name=name,
            layers=layers,
            active_layer=fields.get("ACTIVELAYER.7", "TOP") or "TOP",
            current=fields.get("ISCURRENT", "TRUE").upper() == "TRUE",
            locked=fields.get("ISLOCKED", "FALSE").upper() == "TRUE",
            flip_board=fields.get("FLIPBOARD", "FALSE").upper() == "TRUE",
        )
        out.append(_check(definition))
    if not out:
        raise LayerSetError(
            f"In {source or 'der Datei'} wurde kein eigener Lagensatz gefunden. Bitte eine in Altium gespeicherte "
            ".layerset-Datei wählen (View Configuration › Layer Sets › Speichern)."
        )
    return out


def parse_layerset_file(path: str | os.PathLike[str]) -> list[LayerSetDef]:
    """Read a ``.layerset`` file (ANSI text)."""
    file = Path(path)
    try:
        raw = file.read_bytes()
    except FileNotFoundError as exc:
        raise LayerSetError(f"Die Lagensatz-Datei {file} wurde nicht gefunden.") from exc
    except OSError as exc:
        raise LayerSetError(f"Die Lagensatz-Datei {file} konnte nicht gelesen werden: {exc}") from exc
    if len(raw) > 1_000_000:
        raise LayerSetError(f"{file.name} ist zu groß für eine .layerset-Datei.")
    # Altium writes ANSI; a file saved by an editor as UTF-8 with BOM is read as such
    text = raw[3:].decode("utf-8", "replace") if raw.startswith(b"\xef\xbb\xbf") else raw.decode("cp1252", "replace")
    if "LAYERSET" not in text.upper():
        raise LayerSetError(f"{file.name} ist keine Altium-Lagensatz-Datei (.layerset).")
    return parse_layerset_text(text, source=file.name)


def builtin_layer_set(layer_map: LayerMap | None = None, *, current: bool = True) -> LayerSetDef:
    """The layer set of the layer map: copper, paste, overlay, solder, drill guide, keep-out and every
    mechanical layer PartForge draws on (``DrillDrawing`` between Mechanical 16 and 17, as Altium sorts)."""
    mapping = layer_map or LayerMap()
    numbers: set[int] = set()
    for value in mapping.model_dump().values():
        number = L.mechanical_number(value) if isinstance(value, str) else None
        if number is not None:
            numbers.add(number)
    low = [f"Mechanical{n}" for n in sorted(numbers) if n <= 16]
    high = [f"Mechanical{n}" for n in sorted(numbers) if n > 16]
    silk = token_for_layer(mapping.silkscreen) or "TopOverlay"
    fixed = [silk if t == "TopOverlay" else t for t in FIXED_COMPONENT_TOKENS]
    # a mechanical silkscreen layer is already among the mechanical layers: list every layer once
    layers = [t for t in fixed if t not in low and t not in high]
    return LayerSetDef(name=BUILTIN_NAME, layers=[*layers, *low, "DrillDrawing", *high], active_layer="TOP",
                       current=current)


def resolve_layer_set(settings: LayerSetSettings, layer_map: LayerMap | None = None) -> LayerSetDef | None:
    """The layer set the settings describe (``None`` = no own set). Raises :class:`LayerSetError` for an
    unusable stored definition."""
    if settings.mode == "none":
        return None
    if settings.mode == "builtin":
        built = builtin_layer_set(layer_map, current=settings.current)
        if settings.name and _clean_name(settings.name):
            built = built.model_copy(update={"name": _clean_name(settings.name)})
        return _check(built)
    return _check(LayerSetDef(name=settings.name or "", layers=list(settings.layers),
                              active_layer=settings.active_layer or "TOP", current=settings.current,
                              locked=settings.locked, flip_board=settings.flip_board))


def workspace_layer_set(ws: Workspace | None) -> tuple[LayerSetDef | None, list[str]]:
    """Layer set of a workspace with German notes (an unusable definition: no set + a note)."""
    if ws is None:
        return None, []
    try:
        return resolve_layer_set(ws.settings.layer_set, ws.settings.layers), []
    except LayerSetError as exc:
        return None, [f"Lagensatz nicht verwendet: {exc}"]
