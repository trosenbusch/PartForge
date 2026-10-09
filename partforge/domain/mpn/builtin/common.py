"""Helpers shared by the built-in templates (size tables, field mappings, rule builders)."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from ..model import CodeOption, FootprintHint, SizeSpec, ValueRule

# imperial EIA size -> metric code (IPC / manufacturer metric names)
METRIC: dict[str, str] = {
    "01005": "0402", "0201": "0603", "0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216",
    "1210": "3225", "1218": "3246", "1805": "4513", "1808": "4520", "1812": "4532", "1825": "4564",
    "2010": "5025", "2220": "5750", "2225": "5664", "2512": "6332",
}

RESISTOR_FIELDS: dict[str, str] = {
    "Resistance": "{value}",
    "Tolerance": "{tolerance}",
    "Power": "{power}",
    "Voltage": "{voltage}",
    "TCR": "{tcr}",
    "Technology": "{technology}",
    "Size": "{size}",
    "Package": "{size}",
    "Mounting": "SMD",
    "Height": "{height}",
    "Operating Temperature": "{temperature}",
    # jumpers only (jumper_note): maximum resistance and rated current of the size, e.g.
    # "0-Ω-Brücke (Jumper) ≤ 20 mΩ, Nennstrom 2A"
    "Notes": "{jumper_note}, Nennstrom {jumper_current}",
}

CAPACITOR_FIELDS: dict[str, str] = {
    "Capacitance": "{value}",
    "Voltage": "{voltage}",
    "Tolerance": "{tolerance}",
    "Dielectric": "{dielectric}",
    "Type": "MLCC",
    "Polarized": "Nein",
    "Size": "{size}",
    "Package": "{size}",
    "Mounting": "SMD",
    "Height": "{height}",
    "Operating Temperature": "{temperature}",
}

JUMPER_NOTE = "0-Ω-Brücke (Jumper)"


def jumper_attrs(limit: str) -> dict[str, str]:
    """Row attributes of a 0-Ω jumper.

    The datasheets rate a jumper by its maximum resistance and its rated current per size (Vishay
    "Jumper, Imax. = 2.0 A ≤ 20 mΩ", Panasonic ERJ "【For Jumper】 Rated current", UNI-ROYAL "Rated
    Current of Jumper", YAGEO RC_L "Jumper criteria: Rated Current", Bourns CR "Zero Ohm Jumper …
    Rated Current"); tolerance, TCR, power rating and working voltage are specified for the resistors
    only (Vishay: "TCR is not specified for 0 Ω jumpers"). So a jumper row stores 0 Ω and a note with the resistance
    limit, completed by the size attribute ``jumper_current`` ("0-Ω-Brücke (Jumper) ≤ 20 mΩ,
    Nennstrom 2A"); the other ratings stay empty (:func:`partforge.db.values.not_applicable`)."""
    return {"jumper_note": f"{JUMPER_NOTE} {limit}", "tolerance": "", "tcr": "", "power": "", "voltage": ""}


def mm(value: float) -> str:
    """Height text in mm (``0.55mm``)."""
    return f"{round(value, 3):g}mm"


def size_options(sizes: Iterable[str], codes: dict[str, str] | None = None) -> list[CodeOption]:
    """Options of the ``size`` variable (code = size unless ``codes`` maps it)."""
    codes = codes or {}
    return [CodeOption(code=codes.get(s, s), value=s, label=f"{s} ({METRIC[s]} metrisch)" if s in METRIC else s)
            for s in sizes]


def chip_size(size: str, *, power: str | None = None, voltage: str | None = None, height: float | None = None,
              jumper_current: str | None = None, extra: dict[str, str] | None = None,
              footprint: FootprintHint | None = None) -> SizeSpec:
    """Size spec of a chip part (attributes as field texts)."""
    attrs: dict[str, str] = {}
    if size in METRIC:
        attrs["metric"] = METRIC[size]
    if power:
        attrs["power"] = power
    if voltage:
        attrs["voltage"] = voltage
    if height is not None:
        attrs["height"] = mm(height)
    if jumper_current:
        attrs["jumper_current"] = jumper_current
    attrs.update(extra or {})
    label = f"{size} ({METRIC[size]})" if size in METRIC else size
    return SizeSpec(size=size, label=label, attrs=attrs, footprint=footprint)


def custom_chip(kind: str, *, L: tuple[float, float], W: tuple[float, float], T: tuple[float, float],  # noqa: N803
                H: tuple[float, float]) -> FootprintHint:  # noqa: N803
    """Footprint hint for a chip size the footprint generator has no table for (datasheet dimensions)."""
    def tol(r: tuple[float, float]) -> dict[str, float]:
        return {"min": r[0], "max": r[1]}

    return FootprintHint(family="chip", kind=kind, params={"L": tol(L), "W": tol(W), "T": tol(T), "H": tol(H)})


def rule(when: dict[str, Sequence[str]], ranges: Sequence[tuple[str, str]], series: Sequence[str],
         *, sizes: Sequence[str] = (), **attrs: Any) -> ValueRule:
    """Compact :class:`ValueRule` constructor (``attrs`` become rule attributes, e.g. tcr="±100ppm/K")."""
    return ValueRule(sizes=list(sizes), when={k: list(v) for k, v in when.items()}, ranges=list(ranges),
                     series=list(series), attrs={k: str(v) for k, v in attrs.items()})


E24 = ["E24"]
E24_E96 = ["E24", "E96"]
