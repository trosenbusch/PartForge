"""Example content for a new library ("Beispielinhalte").

Nineteen real parts across the common categories, each with a real symbol and footprint
generated in the workspace's house style:

* symbols from :mod:`partforge.symbols` (standard kinds; the LDO gets an IC symbol from its
  pin list), footprints from :mod:`partforge.footprints` (``chip_request`` sizes, family
  presets, the Bourns land pattern of the power inductor);
* names come from the generators, so they follow the workspace conventions: an
  anode-first workspace (``SymbolStyle.diode_pin1 = "anode"``) gets "Diode (AK)"-style
  symbols together with the reversed ("…RN", cathode on pad 2) footprints;
* symbols and footprints are registered in ``pf_symbols``/``pf_footprints`` with their spec
  and status ``pending`` in the library files of
  :func:`partforge.altium.libwriter.symbol_library_path` / ``footprint_library_path``
  (workspace-relative, backslashes); :func:`partforge.altium.sync.sync_pending` writes them;
* parts reference these names and library paths; every part carries a note in ``Notes``
  and the status "Entwurf"; existing parts, symbols and footprints are kept;
* part numbers follow the workspace scheme: ``mpn`` = the manufacturer part number,
  ``internal`` = generated internal numbers (an example whose MPN already exists in its
  category is not added again).

PartForge has no crystal or chip-fuse footprint family yet: the 3215 crystal and the 1206
fuse use the IPC-7351B chip land (table 3-5) of their body under an explicit name –
IPC style ``XTAL3215X90N``/``FUSC3216X60N`` (also their ``ipc_name``; the last letter follows
the density) or, with house naming, ``XTAL 1.5x3.2MM``/``FUSE 1206_3216``.

Nothing here touches the database or imports the generators at import time.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..workspace import FootprintStyle, Workspace
from . import categories, core, registry
from .errors import CategoryNotFound
from .models import FootprintRecord, SymbolRecord
from .templates import ensure_default_symbol_kinds

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..footprints.models import FootprintRequest
    from ..geometry.model import FootprintSpec, SymbolSpec
    from ..symbols.models import SymbolRequest

log = logging.getLogger(__name__)

__all__ = [
    "EXAMPLE_AUTHOR",
    "EXAMPLE_NOTE",
    "EXAMPLE_PARTS",
    "EXAMPLE_STATUS",
    "PENDING_MESSAGE",
    "ExampleContent",
    "ExamplePart",
    "FootprintDef",
    "SymbolDef",
    "build_examples",
    "seed_examples",
]

EXAMPLE_AUTHOR = "PartForge (Beispiele)"
EXAMPLE_NOTE = "Beispielbauteil von PartForge – Werte vor der Verwendung mit dem Datenblatt prüfen."
EXAMPLE_STATUS = "Entwurf"
PENDING_MESSAGE = "Beispiel – wird beim Synchronisieren in die Bibliothek geschrieben."


# --------------------------------------------------------------------------- definitions


@dataclass(frozen=True, slots=True)
class SymbolDef:
    """Generator request of an example symbol (plain data, converted when seeding)."""

    kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    name: str | None = None
    description: str | None = None
    pins: tuple[tuple[str, str, str], ...] = ()  # (designator, name, electrical type) for kind "ic"

    def request(self) -> SymbolRequest:
        from ..symbols.models import IcPin, SymbolRequest

        return SymbolRequest(
            kind=self.kind,
            params=dict(self.params),
            name=self.name,
            description=self.description,
            pins=[IcPin.model_validate({"designator": d, "name": n, "electrical": e}) for d, n, e in self.pins],
        )


@dataclass(frozen=True, slots=True)
class FootprintDef:
    """Generator request of an example footprint (plain data, converted when seeding).

    ``chip`` = (kind, EIA size) for :func:`partforge.footprints.chip_request`; otherwise
    ``family`` + ``params`` (a family preset or package dimensions). ``name`` is only set
    for packages without their own generator family: the IPC-style name (``{density}``
    becomes the IPC density letter of the workspace style), which is also the spec's
    ``ipc_name``; ``house_name`` is the base of the name with house naming (the density
    suffix of :func:`partforge.footprints.naming.house` is appended).
    """

    family: str
    params: Mapping[str, Any] = field(default_factory=dict)
    chip: tuple[str, str] | None = None
    land_pattern: Mapping[str, float] | None = None
    name: str | None = None
    house_name: str | None = None
    description: str | None = None

    def ipc_name(self, density: str) -> str | None:
        """The explicit IPC-style name for ``density`` (``None`` = generator name)."""
        return self.name.format(density=density) if self.name else None

    def explicit_name(self, style: FootprintStyle) -> str | None:
        """The explicit name in the naming scheme of ``style`` (``None`` = generator name)."""
        if style.naming == "house" and self.house_name:
            from ..footprints.naming import house

            return house(self.house_name, style.density)
        return self.ipc_name(style.density)

    def request(self, style: FootprintStyle) -> FootprintRequest:
        from ..footprints import chip_request
        from ..footprints.models import FootprintRequest

        if self.chip is not None:
            req = chip_request(*self.chip)
        else:
            req = FootprintRequest(
                family=self.family,
                params=_deep_copy(self.params),
                land_pattern=dict(self.land_pattern) if self.land_pattern else None,
            )
        updates: dict[str, Any] = {}
        name = self.explicit_name(style)
        if name:
            updates["name"] = name
        if self.description:
            updates["description"] = self.description
        return req.model_copy(update=updates) if updates else req


@dataclass(frozen=True, slots=True)
class ExamplePart:
    """One example part: category, field values and the symbol/footprint it uses.

    ``unused_pads`` documents footprint pads without a symbol pin (none so far: the LDO's
    NC pin is part of its symbol, like in the house libraries).
    """

    table: str
    values: Mapping[str, str]
    symbol: SymbolDef
    footprint: FootprintDef
    unused_pads: tuple[str, ...] = ()

    @property
    def part_number(self) -> str:
        return self.values["Part Number"]


def _deep_copy(params: Mapping[str, Any]) -> dict[str, Any]:
    return {k: dict(v) if isinstance(v, Mapping) else v for k, v in params.items()}


def _tol(lo: float, hi: float) -> dict[str, float]:
    return {"min": lo, "max": hi}


# --- symbols (kinds of partforge.symbols; names come from the generator) ----------------
_RESISTOR = SymbolDef("resistor")
_CAPACITOR = SymbolDef("capacitor")
_INDUCTOR = SymbolDef("inductor")
_FERRITE = SymbolDef("ferrite_bead")
_SCHOTTKY = SymbolDef("schottky")
_ZENER = SymbolDef("zener")
_LED = SymbolDef("led")
_NPN = SymbolDef("npn")  # SOT-23: 1 = B, 2 = E, 3 = C
_NMOS = SymbolDef("nmos")  # SOT-23: 1 = G, 2 = S, 3 = D
_OPAMP_DUAL = SymbolDef("opamp_dual")  # standard SOIC-8 dual op-amp pinout (LM358)
_OPAMP_SOT23_5 = SymbolDef("opamp", {"pinmap": "SOT23-5"})  # 1 = OUT, 2 = V-, 3 = +IN, 4 = -IN, 5 = V+
_CRYSTAL = SymbolDef("crystal_2")
_FUSE = SymbolDef("fuse")
_CONNECTOR_1X04 = SymbolDef("connector", {"pins": 4, "rows": "1"})
_LDO_AP2112K = SymbolDef(
    "ic",
    name="AP2112K",
    description="LDO voltage regulator 600mA with enable",
    pins=(("1", "VIN", "power"), ("2", "GND", "power"), ("3", "EN", "input"), ("4", "NC", "passive"),
          ("5", "VOUT", "power")),
)

# --- footprints (partforge.footprints) ----------------------------------------------------
_CHIP_R0603 = FootprintDef("chip", chip=("R", "0603"))
_CHIP_C0603 = FootprintDef("chip", chip=("C", "0603"))
_CHIP_C0805 = FootprintDef("chip", chip=("C", "0805"))
_CHIP_FB0603 = FootprintDef("chip", chip=("FB", "0603"))
_CHIP_LED0603 = FootprintDef("chip", chip=("LED", "0603"))
_SOD123 = FootprintDef("sod", {"preset": "SOD-123"})
_SOT23_3 = FootprintDef("sot23", {"preset": "SOT-23-3"})
_SOT23_5 = FootprintDef("sot23", {"preset": "SOT-23-5"})
_SOIC8 = FootprintDef("gullwing", {"preset": "SOIC-8"})
_HEADER_1X04 = FootprintDef("pin_header", {"preset": "1x04-P2.54"})
# Bourns SRR1260 (datasheet REV 03/26): body 12.5 x 12.5 x 6.0 mm, terminals 5.0 wide with a
# 7.0 mm inner gap; recommended layout 2.9 x 5.4 mm pads, 9.7 mm centre distance.
_SRR1260 = FootprintDef(
    "molded",
    {"kind": "INDM", "L": _tol(12.2, 12.8), "W": _tol(12.2, 12.8), "H": _tol(5.5, 6.5), "F": _tol(4.7, 5.3),
     "S": _tol(2.6, 2.9)},
    land_pattern={"pad_length": 2.9, "pad_width": 5.4, "row_spacing": 9.7},
)
# Abracon ABS07: 3.2 x 1.5 x 0.9 mm ceramic SMD crystal, two pads (IPC chip land).
_XTAL_3215 = FootprintDef(
    "chip",
    {"kind": "C", "L": _tol(3.1, 3.3), "W": _tol(1.4, 1.6), "T": _tol(0.6, 0.9), "H": _tol(0.8, 0.9)},
    name="XTAL3215X90{density}",
    house_name="XTAL 1.5x3.2MM",  # house_body(width, length) like "SOIC-8 3.9x4.9MM"
    description="Crystal, 2-Pads, Body 3.20x1.50mm, IPC-7351B chip land",
)
# 1206 chip fuse: IPC chip land of the EIA 1206 body.
_FUSE_1206 = FootprintDef(
    "chip",
    chip=("R", "1206"),
    name="FUSC3216X60{density}",
    house_name="FUSE 1206_3216",  # like "RES 0603_1608"
    description="Chip Fuse, 2-Leads, Body 3.20x1.60mm, IPC-7351B chip land",
)

_SMD = "SMD"
_ACTIVE = {"Lifecycle": "Aktiv", "RoHS": "Ja"}


def _yageo(pn: str, resistance: str) -> ExamplePart:
    return ExamplePart(
        "Resistors",
        {
            "Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn,
            "Resistance": resistance, "Tolerance": "1%", "Power": "0.1W", "Voltage": "75V", "TCR": "±100ppm/K",
            "Technology": "Dickschicht", "Size": "0603", "Package": "0603", "Mounting": _SMD, "Height": "0.55",
            "Operating Temperature": "-55 … 155", **_ACTIVE,
        },
        _RESISTOR,
        _CHIP_R0603,
    )


EXAMPLE_PARTS: tuple[ExamplePart, ...] = (
    _yageo("RC0603FR-0710KL", "10k"),
    _yageo("RC0603FR-074K7L", "4k7"),
    _yageo("RC0603FR-071KL", "1k"),
    _yageo("RC0603FR-07100RL", "100R"),
    ExamplePart(
        "Capacitors",
        {
            "Part Number": "GRM188R71H104KA93D", "Manufacturer": "Murata", "Manufacturer Part Number": "GRM188R71H104KA93D",
            "Capacitance": "100n", "Voltage": "50V", "Tolerance": "10%", "Dielectric": "X7R", "Type": "MLCC",
            "Size": "0603", "Package": "0603", "Mounting": _SMD, "Height": "0.87", "Operating Temperature": "-55 … 125",
            **_ACTIVE,
        },
        _CAPACITOR,
        _CHIP_C0603,
    ),
    ExamplePart(
        "Capacitors",
        {
            "Part Number": "GRM21BR61E106KA73L", "Manufacturer": "Murata", "Manufacturer Part Number": "GRM21BR61E106KA73L",
            "Capacitance": "10u", "Voltage": "25V", "Tolerance": "10%", "Dielectric": "X5R", "Type": "MLCC",
            "Size": "0805", "Package": "0805", "Mounting": _SMD, "Height": "1.35", "Operating Temperature": "-55 … 85",
            **_ACTIVE,
        },
        _CAPACITOR,
        _CHIP_C0805,
    ),
    ExamplePart(
        "Inductors",
        {
            "Part Number": "SRR1260-100M", "Manufacturer": "Bourns", "Manufacturer Part Number": "SRR1260-100M",
            "Inductance": "10µH", "Tolerance": "20%", "Current Rating": "5.5A", "Saturation Current": "5.5A",
            "DCR": "20mΩ", "SRF": "21MHz", "Shielding": "geschirmt", "Size": "12.5x12.5mm", "Package": "SRR1260",
            "Mounting": _SMD, "Height": "6.5", "Operating Temperature": "-40 … 125",
            "ComponentLink1URL": "https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf", **_ACTIVE,
        },
        _INDUCTOR,
        _SRR1260,
    ),
    ExamplePart(
        "Ferrite Beads",
        {
            "Part Number": "BLM18PG221SN1D", "Manufacturer": "Murata", "Manufacturer Part Number": "BLM18PG221SN1D",
            "Impedance": "220", "Current Rating": "1.4A", "DCR": "0.1", "Size": "0603", "Package": "0603",
            "Mounting": _SMD, "Height": "0.95", **_ACTIVE,
        },
        _FERRITE,
        _CHIP_FB0603,
    ),
    ExamplePart(
        "Diodes",
        {
            "Part Number": "MBR0520LT1G", "Manufacturer": "onsemi", "Manufacturer Part Number": "MBR0520LT1G",
            "Diode Type": "Schottky", "Reverse Voltage": "20V", "Forward Current": "0.5A", "Configuration": "Einzeln",
            "Package": "SOD-123", "Mounting": _SMD, "Height": "1.35",
            "ComponentLink1URL": "https://www.onsemi.com/pdf/datasheet/mbr0520lt1-d.pdf", **_ACTIVE,
        },
        _SCHOTTKY,
        _SOD123,
    ),
    ExamplePart(
        "Diodes",
        {
            "Part Number": "MMSZ5231B-7-F", "Manufacturer": "Diodes Incorporated",
            "Manufacturer Part Number": "MMSZ5231B-7-F", "Diode Type": "Z-Diode", "Zener Voltage": "5.1V",
            "Power": "0.5W", "Configuration": "Einzeln", "Package": "SOD-123", "Mounting": _SMD, "Height": "1.35",
            **_ACTIVE,
        },
        _ZENER,
        _SOD123,
    ),
    ExamplePart(
        "LEDs",
        {
            "Part Number": "150060RS75000", "Manufacturer": "Würth Elektronik", "Manufacturer Part Number": "150060RS75000",
            "Color": "Rot", "Forward Voltage": "2V", "Forward Current": "20mA", "Viewing Angle": "140°", "Size": "0603",
            "Package": "0603", "Mounting": _SMD,
            "ComponentLink1URL": "https://www.we-online.com/components/products/datasheet/150060RS75000.pdf",
            **_ACTIVE,
        },
        _LED,
        _CHIP_LED0603,
    ),
    ExamplePart(
        "Transistors BJT",
        {
            "Part Number": "MMBT3904LT1G", "Manufacturer": "onsemi", "Manufacturer Part Number": "MMBT3904LT1G",
            "Polarity": "NPN", "VCEO": "40V", "IC": "200mA", "hFE": "100 … 300", "Power": "225mW", "fT": "300MHz",
            "Package": "SOT-23", "Mounting": _SMD, "Height": "1.11",
            "ComponentLink1URL": "https://www.onsemi.com/pdf/datasheet/mmbt3904lt1-d.pdf", **_ACTIVE,
        },
        _NPN,
        _SOT23_3,
    ),
    ExamplePart(
        "Transistors FET",
        {
            "Part Number": "2N7002,215", "Manufacturer": "Nexperia", "Manufacturer Part Number": "2N7002,215",
            "Channel": "N", "FET Type": "MOSFET", "VDS": "60V", "ID": "300mA", "RDS(on)": "5", "Package": "SOT-23",
            "Mounting": _SMD, "Height": "1.1",
            "ComponentLink1URL": "https://assets.nexperia.com/documents/data-sheet/2N7002.pdf", **_ACTIVE,
        },
        _NMOS,
        _SOT23_3,
    ),
    ExamplePart(
        "Amplifiers",
        {
            "Part Number": "LM358DR", "Manufacturer": "Texas Instruments", "Manufacturer Part Number": "LM358DR",
            "Amplifier Type": "Operationsverstärker", "Channels": "2", "GBW": "700kHz", "Slew Rate": "0.3V/µs",
            "Supply Voltage": "3V … 32V", "Input Offset": "3mV", "Rail-to-Rail": "Nein", "Package": "SOIC-8",
            "Mounting": _SMD, "Height": "1.75", "Operating Temperature": "0 … 70",
            "ComponentLink1URL": "https://www.ti.com/lit/ds/symlink/lm358.pdf", **_ACTIVE,
        },
        _OPAMP_DUAL,
        _SOIC8,
    ),
    ExamplePart(
        "Amplifiers",
        {
            "Part Number": "TLV9001IDBVR", "Manufacturer": "Texas Instruments", "Manufacturer Part Number": "TLV9001IDBVR",
            "Amplifier Type": "Operationsverstärker", "Channels": "1", "GBW": "1MHz", "Slew Rate": "2V/µs",
            "Supply Voltage": "1.8V … 5.5V", "Input Offset": "0.4mV", "Rail-to-Rail": "Ein-/Ausgang",
            "Package": "SOT-23-5", "Mounting": _SMD, "Height": "1.45", "Operating Temperature": "-40 … 125",
            "ComponentLink1URL": "https://www.ti.com/lit/ds/symlink/tlv9001.pdf", **_ACTIVE,
        },
        _OPAMP_SOT23_5,
        _SOT23_5,
    ),
    ExamplePart(
        "Power Linear",
        {
            "Part Number": "AP2112K-3.3TRG1", "Manufacturer": "Diodes Incorporated",
            "Manufacturer Part Number": "AP2112K-3.3TRG1", "Regulator Type": "LDO", "Input Voltage": "2.5 … 6",
            "Output Voltage": "3.3V", "Output Current": "600mA", "Dropout Voltage": "250mV", "Accuracy": "1.5%",
            "Package": "SOT-23-5", "Mounting": _SMD, "Operating Temperature": "-40 … 85",
            "ComponentLink1URL": "https://www.diodes.com/assets/Datasheets/AP2112.pdf", **_ACTIVE,
        },
        _LDO_AP2112K,
        _SOT23_5,
    ),
    ExamplePart(
        "Oscillators",
        {
            "Part Number": "ABS07-32.768KHZ-T", "Manufacturer": "Abracon", "Manufacturer Part Number": "ABS07-32.768KHZ-T",
            "Oscillator Type": "Quarz", "Frequency": "32.768kHz", "Frequency Tolerance": "20", "Load Capacitance": "12.5p",
            "ESR": "70k", "Package": "3215", "Mounting": _SMD, "Height": "0.9", "Operating Temperature": "-40 … 85",
            **_ACTIVE,
        },
        _CRYSTAL,
        _XTAL_3215,
    ),
    ExamplePart(
        "Fuses",
        {
            "Part Number": "0466001.NR", "Manufacturer": "Littelfuse", "Manufacturer Part Number": "0466001.NR",
            "Protection Type": "Sicherung", "Current Rating": "1A", "Voltage Rating": "63V", "Breaking Capacity": "50A",
            "Characteristic": "superflink", "Package": "1206", "Mounting": _SMD, "Operating Temperature": "-55 … 125",
            **_ACTIVE,
        },
        _FUSE,
        _FUSE_1206,
    ),
    ExamplePart(
        "Connectors",
        {
            "Part Number": "61300411121", "Manufacturer": "Würth Elektronik", "Manufacturer Part Number": "61300411121",
            "Connector Type": "Stiftleiste", "Pins": "4", "Rows": "1", "Pitch": "2.54", "Orientation": "gerade",
            "Gender": "Stecker", "Current Rating": "3A", "Series": "WR-PHD", "Package": "THT 1x04 2.54mm",
            "Mounting": "THT",
            "ComponentLink1URL": "https://www.we-online.com/components/products/datasheet/61300411121.pdf",
            **_ACTIVE,
        },
        _CONNECTOR_1X04,
        _HEADER_1X04,
    ),
)


# --------------------------------------------------------------------------- generation


@dataclass(slots=True)
class ExampleContent:
    """The example content generated for one workspace (no database access).

    ``symbols``/``footprints`` map names to registry records (spec, library, ``pending``);
    ``parts`` are ``(table, values)`` with Library/Footprint Ref and Path, note and status;
    ``skipped`` lists part numbers whose symbol or footprint could not be generated with the
    workspace style (with the reason).
    """

    symbols: dict[str, SymbolRecord] = field(default_factory=dict)
    footprints: dict[str, FootprintRecord] = field(default_factory=dict)
    parts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)


def _height_text(height: float | None) -> str | None:
    return None if height is None else f"{round(height, 3):g}"


def build_examples(ws: Workspace, *, tables: Sequence[str] | None = None) -> ExampleContent:
    """Generate the example symbols, footprints and part rows in the styles of ``ws``.

    ``tables`` restricts the parts to these categories (``None`` = all). Generation errors
    (e.g. an exotic house style) skip the affected part instead of failing.
    """
    from ..altium.libwriter import footprint_library_path, symbol_library_path
    from ..footprints import generate as generate_footprint
    from ..symbols import SymbolError
    from ..symbols import generate as generate_symbol

    symbol_style = ws.settings.symbol
    footprint_style = ws.settings.footprint
    wanted = set(tables) if tables is not None else None
    content = ExampleContent()
    symbol_specs: dict[int, SymbolSpec | str] = {}  # id(definition) -> spec or error text
    footprint_specs: dict[int, FootprintSpec | str] = {}

    for part in EXAMPLE_PARTS:
        if wanted is not None and part.table not in wanted:
            continue
        key = id(part.symbol)
        if key not in symbol_specs:
            try:
                symbol_specs[key] = generate_symbol(part.symbol.request(), symbol_style)
            except (SymbolError, ValueError) as exc:
                symbol_specs[key] = f"Symbol: {exc}"
        key = id(part.footprint)
        if key not in footprint_specs:
            try:
                spec = generate_footprint(
                    part.footprint.request(footprint_style),
                    footprint_style,
                    diode_pin1=symbol_style.diode_pin1,
                )
                ipc_name = part.footprint.ipc_name(footprint_style.density)
                if ipc_name and spec.ipc_name != ipc_name:  # the chip land's own name ("CAPC…") is not this package
                    spec = spec.model_copy(update={"ipc_name": ipc_name})
                footprint_specs[key] = spec
            except ValueError as exc:
                footprint_specs[key] = f"Footprint: {exc}"
        symbol = symbol_specs[id(part.symbol)]
        footprint = footprint_specs[id(part.footprint)]
        if isinstance(symbol, str) or isinstance(footprint, str):
            reason = symbol if isinstance(symbol, str) else str(footprint)
            content.skipped[part.part_number] = reason
            log.warning("Beispielbauteil %s übersprungen: %s", part.part_number, reason)
            continue
        sym_rec = content.symbols.get(symbol.name)
        if sym_rec is None:
            sym_rec = SymbolRecord(
                name=symbol.name,
                library=ws.rel(symbol_library_path(ws, symbol, part.table)),
                source="generated",
                spec=symbol,
                kind=str((symbol.generator or {}).get("kind") or part.symbol.kind),
                status="pending",
                status_message=PENDING_MESSAGE,
            )
            content.symbols[symbol.name] = sym_rec
        fp_rec = content.footprints.get(footprint.name)
        if fp_rec is None:
            fp_rec = FootprintRecord(
                name=footprint.name,
                library=ws.rel(footprint_library_path(ws, footprint)),
                source="generated",
                spec=footprint,
                family=footprint.family or None,
                ipc_name=footprint.ipc_name,
                height=footprint.height,
                status="pending",
                status_message=PENDING_MESSAGE,
            )
            content.footprints[footprint.name] = fp_rec
        values: dict[str, Any] = {
            **part.values,
            "Library Ref": symbol.name,
            "Library Path": sym_rec.library,
            "Footprint Ref": footprint.name,
            "Footprint Path": fp_rec.library,
            "Notes": EXAMPLE_NOTE,
            "PF Status": EXAMPLE_STATUS,
        }
        height = _height_text(footprint.height)
        if height is not None:
            values.setdefault("Height", height)
        content.parts.append((part.table, values))
    return content


def _existing_tables(names: Sequence[str]) -> dict[str, str]:
    """Example table -> actual category table (spelling of the database) for existing categories."""
    found: dict[str, str] = {}
    for table in names:
        try:
            found[table] = categories.get_category(table).table
        except CategoryNotFound:
            log.info("Beispiele für %s übersprungen (Kategorie fehlt)", table)
    return found


def _existing_mpns(table: str, mpns: Sequence[str]) -> set[str]:
    """Casefolded manufacturer part numbers of ``mpns`` that already exist in ``table``."""
    from .parts import query_parts

    if not mpns:
        return set()
    rows, _total = query_parts(
        table, filters=[{"column": "Manufacturer Part Number", "op": "in", "value": list(mpns)}], limit=None
    )
    return {str(row["Manufacturer Part Number"]).casefold() for row in rows if row.get("Manufacturer Part Number")}


def _internal_numbering(table: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the part-number scheme ``internal``: without ``Part Number`` (the database
    assigns the next internal number) and without examples whose MPN the category already has."""
    present = _existing_mpns(table, [str(r["Manufacturer Part Number"]) for r in rows])
    out: list[dict[str, Any]] = []
    for row in rows:
        if str(row["Manufacturer Part Number"]).casefold() in present:
            continue
        out.append({k: v for k, v in row.items() if k != "Part Number"})
    return out


def seed_examples(ws: Workspace) -> dict[str, int]:
    """Add the example symbols, footprints and parts (existing entries are kept).

    Opens the database of ``ws`` if it is not the open one. Returns counts
    ``{"parts", "symbols", "footprints"}`` of the newly added items."""
    if not core.is_open() or core.current_workspace().root != ws.root:
        from .lifecycle import open_database

        open_database(ws)
    ensure_default_symbol_kinds()  # read-only unless an older library still stores symbol names

    tables = _existing_tables(list(dict.fromkeys(p.table for p in EXAMPLE_PARTS)))
    content = build_examples(ws, tables=list(tables))

    known_symbols = {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)}
    known_footprints = {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)}
    new_symbols = [rec for name, rec in content.symbols.items() if name.casefold() not in known_symbols]
    new_footprints = [rec for name, rec in content.footprints.items() if name.casefold() not in known_footprints]
    if new_symbols:
        registry.upsert_symbols(new_symbols)
    if new_footprints:
        registry.upsert_footprints(new_footprints)

    from .parts import upsert_parts

    rows_by_table: dict[str, list[dict[str, Any]]] = {}
    for table, values in content.parts:
        row = dict(values)
        # an entry registered before under the same name lives in its own library
        existing_symbol = known_symbols.get(str(row["Library Ref"]).casefold())
        if existing_symbol is not None and existing_symbol.library:
            row["Library Path"] = existing_symbol.library
        existing_footprint = known_footprints.get(str(row["Footprint Ref"]).casefold())
        if existing_footprint is not None and existing_footprint.library:
            row["Footprint Path"] = existing_footprint.library
        rows_by_table.setdefault(tables[table], []).append(row)
    internal = ws.settings.part_number_scheme == "internal"
    created = 0
    for table, rows in rows_by_table.items():
        if internal:
            rows = _internal_numbering(table, rows)
            if not rows:
                continue
        result = upsert_parts(table, rows, mode="skip", author=EXAMPLE_AUTHOR)
        if result.errors:
            log.warning("Beispiele in %s mit Fehlern: %s", table, result.errors)
        if result.warnings:
            log.warning("Beispiele in %s mit Hinweisen: %s", table, result.warnings)
        created += len(result.created)
    log.info(
        "Beispielinhalte angelegt: %d Bauteile, %d Symbole, %d Footprints%s",
        created,
        len(new_symbols),
        len(new_footprints),
        f" ({len(content.skipped)} übersprungen)" if content.skipped else "",
    )
    return {"parts": created, "symbols": len(new_symbols), "footprints": len(new_footprints)}
