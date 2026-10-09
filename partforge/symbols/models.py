"""Request/description models of the symbol generator (contract).

Extended backward-compatibly by the symbols module (all additions are optional fields
with defaults): ``SymbolParamSpec.option_labels/minimum/maximum/allow_custom``,
``SymbolKindInfo.description/prefix/thumbnail_svg`` and the new :class:`SymbolSuggestion`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..geometry.model import ElectricalType


class SymbolParamSpec(BaseModel):
    name: str
    label: str
    kind: Literal["int", "bool", "enum", "text"] = "enum"
    default: Any = None
    options: list[str] = Field(default_factory=list)
    help: str | None = None
    # -- extensions (symbols module) ---------------------------------------------------
    option_labels: dict[str, str] = Field(default_factory=dict, description="Deutsche Beschriftung je Option")
    minimum: int | None = None  # kind="int"
    maximum: int | None = None  # kind="int"
    allow_custom: bool = Field(
        default=False,
        description="Neben den Optionen sind eigene Werte erlaubt (z. B. Pinbelegung 'SSSGDDDD' oder ein Objekt)",
    )


class SymbolKindInfo(BaseModel):
    key: str  # "resistor", "capacitor", "capacitor_polarized", "inductor", "diode", "zener", ...
    label: str  # German UI label
    group: str  # "Passiv", "Halbleiter", "ICs", "Verbinder", "Sonstige"
    default_name: str  # generated symbol name, e.g. "Resistor"
    params: list[SymbolParamSpec] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)  # category tables this symbol suits
    # -- extensions (symbols module) ---------------------------------------------------
    description: str = ""  # German help text for the UI
    prefix: str = "U"  # default designator prefix
    thumbnail_svg: str | None = None  # filled by GET /symbols/kinds?thumbnails=true


class IcPin(BaseModel):
    designator: str
    name: str = ""
    electrical: ElectricalType = "passive"
    side: Literal["left", "right", "top", "bottom"] | None = None  # None = automatic
    group: str | None = None  # functional group; pins of one group stay together
    part: int = 1  # 1..n, 0 = all parts (shared power)
    hidden: bool = False
    description: str | None = None


class SymbolRequest(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    name: str | None = None
    description: str | None = None
    pins: list[IcPin] = Field(default_factory=list)  # for kind="ic" (and connectors with custom names)
    designator_prefix: str | None = None


SuggestionSource = Literal["standard", "package", "pins", "footprint"]


class SymbolSuggestion(BaseModel):
    """Standard symbol suggested for a part (:func:`partforge.symbols.suggest_symbol`).

    ``request`` is only set when the pinout is safe: either the kind has no package-dependent
    pin map, or the pin map follows from the package, the pin table or the footprint pads.
    Otherwise ``kind`` may still name the fitting symbol, with ``needs_pinmap`` and the
    candidate ``pinmap_options`` for the user to choose from.
    """

    request: SymbolRequest | None = None  # ready to generate; None = nothing safe to suggest
    name: str | None = None  # resulting symbol name in the given house style
    kind: str | None = None  # fitting standard kind (also when the pin map is still open)
    needs_pinmap: bool = False  # the kind fits, but the pin map has to be chosen
    pinmap_options: list[str] = Field(default_factory=list)  # presets that come into question
    alternatives: list[str] = Field(default_factory=list)  # other kinds that may fit
    package: str | None = None  # recognised package (display label, e.g. "SOT-23", "TO-92")
    source: SuggestionSource | None = None  # where the pin map comes from
    messages: list[str] = Field(default_factory=list)  # German hints for the UI
