"""Altium layer names for the library writers.

PartForge footprints use logical layers (:data:`partforge.geometry.model.FpLayer`). The
workspace :class:`~partforge.workspace.LayerMap` decides which Altium layer each logical
layer lands on (default: assembly = Mechanical 9, designator = Mechanical 11, courtyard =
Mechanical 15, ...; Mechanical 2–7 stay free because the Rust writer declares them as
typed assembly/courtyard/3D-body layers).

Two consumers need different spellings of the same layer:

* **Rust writer** (``altium-designer-mcp.exe``) accepts exactly these names (case-sensitive,
  VERIFIED in ``recherche/rust-writer.md`` §4): ``Top Layer``, ``Bottom Layer``,
  ``Mid-Layer N``, ``Internal Plane N``, ``Multi-Layer``, ``Top Overlay``,
  ``Bottom Overlay``, ``Top Paste``, ``Bottom Paste``, ``Top Solder``, ``Bottom Solder``,
  ``Keep-Out Layer``, ``Drill Guide``, ``Drill Drawing``, ``Mechanical 1`` … ``Mechanical 32``
  and the aliases ``Top Assembly`` (= Mechanical 2), ``Bottom Assembly`` (3),
  ``Top Courtyard`` (4), ``Bottom Courtyard`` (5), ``Top 3D Body`` (6) and
  ``Bottom 3D Body`` (7). Reading always returns the alias for Mechanical 2..7, so the
  reverse mapping must accept them.
* **DelphiScript bridge** sets ``Layer`` properties from numeric ``TLayer`` values
  (``eTopLayer = 1`` …) or ``ILayer.MechanicalLayer(n)``; see :func:`bridge_layer_token`.

Canonical names produced here always use ``Mechanical N`` (never the aliases), so a
layer map with ``Mechanical 5`` (older TR_* libraries) is written exactly to Mechanical 5.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final, Literal, get_args

from ..geometry.model import FpLayer
from ..workspace import LayerMap

__all__ = [
    "LayerError",
    "TOP_LAYER",
    "BOTTOM_LAYER",
    "MULTI_LAYER",
    "TOP_OVERLAY",
    "BOTTOM_OVERLAY",
    "TOP_PASTE",
    "BOTTOM_PASTE",
    "TOP_SOLDER",
    "BOTTOM_SOLDER",
    "KEEP_OUT",
    "DRILL_GUIDE",
    "DRILL_DRAWING",
    "MECHANICAL_LAYER_COUNT",
    "RUST_MECHANICAL_ALIASES",
    "ALTIUM_LAYER_IDS",
    "LOGICAL_LAYERS",
    "PadSide",
    "mechanical_name",
    "mechanical_number",
    "normalize_layer_name",
    "is_rust_layer",
    "logical_to_altium",
    "altium_to_logical",
    "layer_map_table",
    "pad_layer",
    "pad_side",
    "bridge_layer_token",
]


class LayerError(ValueError):
    """Unknown or unsupported layer name (German message for the UI)."""


TOP_LAYER: Final = "Top Layer"
BOTTOM_LAYER: Final = "Bottom Layer"
MULTI_LAYER: Final = "Multi-Layer"
TOP_OVERLAY: Final = "Top Overlay"
BOTTOM_OVERLAY: Final = "Bottom Overlay"
TOP_PASTE: Final = "Top Paste"
BOTTOM_PASTE: Final = "Bottom Paste"
TOP_SOLDER: Final = "Top Solder"
BOTTOM_SOLDER: Final = "Bottom Solder"
KEEP_OUT: Final = "Keep-Out Layer"
DRILL_GUIDE: Final = "Drill Guide"
DRILL_DRAWING: Final = "Drill Drawing"

MECHANICAL_LAYER_COUNT: Final = 32
MID_LAYER_COUNT: Final = 30
INTERNAL_PLANE_COUNT: Final = 16

#: Rust writer aliases for the typed mechanical layers (raw layer = Mechanical N).
RUST_MECHANICAL_ALIASES: Final[dict[str, int]] = {
    "Top Assembly": 2,
    "Bottom Assembly": 3,
    "Top Courtyard": 4,
    "Bottom Courtyard": 5,
    "Top 3D Body": 6,
    "Bottom 3D Body": 7,
}

_FIXED_LAYERS: Final[tuple[str, ...]] = (
    TOP_LAYER,
    BOTTOM_LAYER,
    MULTI_LAYER,
    TOP_OVERLAY,
    BOTTOM_OVERLAY,
    TOP_PASTE,
    BOTTOM_PASTE,
    TOP_SOLDER,
    BOTTOM_SOLDER,
    KEEP_OUT,
    DRILL_GUIDE,
    DRILL_DRAWING,
)

#: Altium ``TLayer`` (V6) values of the fixed layers (Constants.md, VERIFIED ids for
#: overlay/paste/solder/keep-out/multi from altium-mcp's String2Layer dump on this PC).
ALTIUM_LAYER_IDS: Final[dict[str, int]] = {
    TOP_LAYER: 1,
    BOTTOM_LAYER: 32,
    TOP_OVERLAY: 33,
    BOTTOM_OVERLAY: 34,
    TOP_PASTE: 35,
    BOTTOM_PASTE: 36,
    TOP_SOLDER: 37,
    BOTTOM_SOLDER: 38,
    DRILL_GUIDE: 55,
    KEEP_OUT: 56,
    DRILL_DRAWING: 73,
    MULTI_LAYER: 74,
}

#: Logical layers in the order of the geometry contract.
LOGICAL_LAYERS: Final[tuple[str, ...]] = get_args(FpLayer)

# Logical layers with a fixed Altium layer.
_FIXED_LOGICAL: Final[dict[str, str]] = {
    "top_copper": TOP_LAYER,
    "bottom_copper": BOTTOM_LAYER,
    "bottom_silk": BOTTOM_OVERLAY,
    "top_paste": TOP_PASTE,
    "bottom_paste": BOTTOM_PASTE,
    "top_mask": TOP_SOLDER,
    "bottom_mask": BOTTOM_SOLDER,
    "keepout": KEEP_OUT,
}

# Logical layers resolved through the workspace LayerMap (logical name -> LayerMap field).
_MAPPED_LOGICAL: Final[dict[str, str]] = {
    "top_silk": "silkscreen",
    "assembly": "assembly",
    "courtyard": "courtyard",
    "body3d": "body3d",
    "designator": "designator",
    "comment": "comment",
    "component_center": "component_center",
    "component_outline": "component_outline",
}

# Reverse lookup priority when several logical layers share one Altium layer.
_REVERSE_PRIORITY: Final[tuple[str, ...]] = (
    "top_copper",
    "bottom_copper",
    "top_silk",
    "bottom_silk",
    "top_paste",
    "bottom_paste",
    "top_mask",
    "bottom_mask",
    "keepout",
    "assembly",
    "courtyard",
    "body3d",
    "designator",
    "comment",
    "component_center",
    "component_outline",
)

# Tolerant spellings (lower-case, separators removed) -> canonical name.
_SYNONYMS: Final[dict[str, str]] = {
    "toplayer": TOP_LAYER,
    "topcopper": TOP_LAYER,
    "bottomlayer": BOTTOM_LAYER,
    "bottomcopper": BOTTOM_LAYER,
    "multilayer": MULTI_LAYER,
    "topoverlay": TOP_OVERLAY,
    "topsilk": TOP_OVERLAY,
    "topsilkscreen": TOP_OVERLAY,
    "bottomoverlay": BOTTOM_OVERLAY,
    "bottomsilk": BOTTOM_OVERLAY,
    "bottomsilkscreen": BOTTOM_OVERLAY,
    "toppaste": TOP_PASTE,
    "bottompaste": BOTTOM_PASTE,
    "topsolder": TOP_SOLDER,
    "topsoldermask": TOP_SOLDER,
    "bottomsolder": BOTTOM_SOLDER,
    "bottomsoldermask": BOTTOM_SOLDER,
    "keepoutlayer": KEEP_OUT,
    "keepout": KEEP_OUT,
    "drillguide": DRILL_GUIDE,
    "drilldrawing": DRILL_DRAWING,
}

_MECH_RE = re.compile(r"^(?:mechanical|mech|m)\s*(?:layer)?\s*(\d{1,2})$", re.IGNORECASE)
_MID_RE = re.compile(r"^mid-?\s*layer\s*(\d{1,2})$", re.IGNORECASE)
_PLANE_RE = re.compile(r"^internal\s*plane\s*(\d{1,2})$", re.IGNORECASE)

PadSide = Literal["top", "bottom", "through"]


def mechanical_name(number: int) -> str:
    """``Mechanical <n>`` for 1..32 (raises :class:`LayerError` otherwise)."""
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= MECHANICAL_LAYER_COUNT:
        raise LayerError(f"Ungültige Mechanik-Lage {number!r}: erlaubt sind 1 bis {MECHANICAL_LAYER_COUNT}.")
    return f"Mechanical {number}"


def _squash(name: str) -> str:
    return re.sub(r"[\s_\-]+", "", name).lower()


def normalize_layer_name(name: str) -> str:
    """Canonical Rust-writer name for a user/foreign spelling.

    Accepts the exact Rust names, the Rust aliases (returned as ``Mechanical N``),
    Altium ``Layer2String`` spellings (``Multi Layer``, ``Top Solder Mask``,
    ``Keep Out Layer``, ``Mechanical Layer 15``) and short forms (``Mech 15``, ``M15``).
    """
    if not isinstance(name, str) or not name.strip():
        raise LayerError("Leerer Lagenname.")
    text = " ".join(name.split())
    if text in _FIXED_LAYERS:
        return text
    if text in RUST_MECHANICAL_ALIASES:
        return mechanical_name(RUST_MECHANICAL_ALIASES[text])
    for alias, number in RUST_MECHANICAL_ALIASES.items():
        if text.lower() == alias.lower():
            return mechanical_name(number)
    m = _MECH_RE.match(text)
    if m:
        return mechanical_name(int(m.group(1)))
    m = _MID_RE.match(text)
    if m:
        number = int(m.group(1))
        if not 1 <= number <= MID_LAYER_COUNT:
            raise LayerError(f"Ungültige Innenlage {name!r}: erlaubt sind 1 bis {MID_LAYER_COUNT}.")
        return f"Mid-Layer {number}"
    m = _PLANE_RE.match(text)
    if m:
        number = int(m.group(1))
        if not 1 <= number <= INTERNAL_PLANE_COUNT:
            raise LayerError(f"Ungültige Versorgungslage {name!r}: erlaubt sind 1 bis {INTERNAL_PLANE_COUNT}.")
        return f"Internal Plane {number}"
    canonical = _SYNONYMS.get(_squash(text))
    if canonical:
        return canonical
    raise LayerError(
        f"Unbekannte Altium-Lage {name!r}. Erlaubt sind z. B. 'Top Overlay', 'Mechanical 15', 'Multi-Layer'."
    )


def is_rust_layer(name: object) -> bool:
    """True if ``name`` is accepted verbatim by the Rust writer (exact spelling)."""
    if not isinstance(name, str):
        return False
    if name in _FIXED_LAYERS or name in RUST_MECHANICAL_ALIASES:
        return True
    m = re.fullmatch(r"Mechanical (\d{1,2})", name)
    if m:
        return 1 <= int(m.group(1)) <= MECHANICAL_LAYER_COUNT and not m.group(1).startswith("0")
    m = re.fullmatch(r"Mid-Layer (\d{1,2})", name)
    if m:
        return 1 <= int(m.group(1)) <= MID_LAYER_COUNT and not m.group(1).startswith("0")
    m = re.fullmatch(r"Internal Plane (\d{1,2})", name)
    if m:
        return 1 <= int(m.group(1)) <= INTERNAL_PLANE_COUNT and not m.group(1).startswith("0")
    return False


def mechanical_number(name: str) -> int | None:
    """Mechanical layer number of a (canonical, alias or tolerant) name, else ``None``."""
    try:
        canonical = normalize_layer_name(name)
    except LayerError:
        return None
    m = re.fullmatch(r"Mechanical (\d{1,2})", canonical)
    return int(m.group(1)) if m else None


def logical_to_altium(layer: str, layer_map: LayerMap | None = None) -> str:
    """Canonical Altium (Rust-writer) layer name for a logical footprint layer."""
    fixed = _FIXED_LOGICAL.get(layer)
    if fixed is not None:
        return fixed
    field = _MAPPED_LOGICAL.get(layer)
    if field is None:
        raise LayerError(f"Unbekannte logische Footprint-Lage {layer!r}.")
    mapping = layer_map or LayerMap()
    configured = getattr(mapping, field)
    try:
        return normalize_layer_name(configured)
    except LayerError as exc:
        raise LayerError(
            f"Lagenzuordnung '{field}' = {configured!r} ist ungültig: {exc} "
            "Bitte unter Einstellungen › Hausstil › Lagen korrigieren."
        ) from exc


def layer_map_table(layer_map: LayerMap | None = None) -> dict[str, str]:
    """Logical layer -> canonical Altium name for every logical layer (for UI/diagnostics)."""
    return {layer: logical_to_altium(layer, layer_map) for layer in LOGICAL_LAYERS}


def altium_to_logical(
    name: str,
    layer_map: LayerMap | None = None,
    *,
    prefer: Sequence[str] = (),
) -> FpLayer | None:
    """Logical layer for an Altium layer name read from a library (``None`` if unmapped).

    Rust aliases are resolved to their mechanical number first (``Bottom Courtyard`` is
    Mechanical 5, the assembly layer of the older TR_* libraries). ``prefer`` lists
    logical layers to try first when several logical layers share one Altium layer
    (e.g. texts prefer ``designator``/``comment``).
    """
    try:
        canonical = normalize_layer_name(name)
    except LayerError:
        return None
    order = [p for p in prefer if p in LOGICAL_LAYERS]
    order += [p for p in _REVERSE_PRIORITY if p not in order]
    for logical in order:
        try:
            if logical_to_altium(logical, layer_map) == canonical:
                return logical  # type: ignore[return-value]
        except LayerError:
            continue
    return None


def pad_layer(side: PadSide) -> str:
    """Altium pad layer for a pad side."""
    try:
        return {"top": TOP_LAYER, "bottom": BOTTOM_LAYER, "through": MULTI_LAYER}[side]
    except KeyError as exc:
        raise LayerError(f"Ungültige Pad-Seite {side!r} (erlaubt: top, bottom, through).") from exc


def pad_side(layer_name: str, *, has_hole: bool = False) -> PadSide:
    """Pad side from an Altium pad layer (a hole always means through-hole)."""
    if has_hole:
        return "through"
    try:
        canonical = normalize_layer_name(layer_name)
    except LayerError:
        return "top"
    if canonical == BOTTOM_LAYER:
        return "bottom"
    if canonical == MULTI_LAYER:
        return "through"
    return "top"


def bridge_layer_token(name: str) -> str:
    """Layer token for the DelphiScript spec: ``L<TLayer id>`` or ``M<mechanical number>``."""
    canonical = normalize_layer_name(name)
    number = mechanical_number(canonical)
    if number is not None:
        return f"M{number}"
    layer_id = ALTIUM_LAYER_IDS.get(canonical)
    if layer_id is None:
        raise LayerError(f"Die Lage {canonical!r} wird von der Altium-Brücke nicht unterstützt.")
    return f"L{layer_id}"
