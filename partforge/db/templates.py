"""Built-in category templates (one database table per category, Altium DbLib style).

The taxonomy follows the user's existing integrated libraries (TR_Passives, TR_BJT,
TR_FET, TR_Opamp, TR_Power-Linear, TR_Power-Switchmode, ...), with passives split
into dedicated tables because they are generated in bulk.

Every value is stored as TEXT (Altium parameters are strings); the field ``kind``
and ``unit`` tell PartForge how to parse, validate, sort and format it.

Schematic texts (house style, user-lib-style.md §3.6: "Comment is the only visible
parameter"): only ``Comment`` is shown on the schematic (``show_on_schematic`` = DbLib
``VisibleOnAdd``; VERIFIED in Altium 26.10, altium-e2e.md §3.4). The comment templates
therefore carry the essential value – ``4k7``, ``100n 50V``, ``10u``, ``220R@100MHz``,
``Rot``, ``32.768kHz``, ``1A`` or the MPN of semiconductors and ICs. Libraries created by
older versions (value fields visible, Comment hidden, shorter comment templates) are
migrated once when they are opened (:data:`LEGACY_VISIBLE_FIELDS`,
:data:`LEGACY_COMMENT_TEMPLATES`, :mod:`partforge.db.lifecycle`).

Default symbols: ``default_symbol`` of a category (template and ``CategoryDef``) is a
symbol **kind key** of :mod:`partforge.symbols` (``resistor``, ``opamp_dual``,
``crystal_2`` …), never a symbol name: names depend on the house style (an anode-first
workspace calls its diode "Diode (AK)"). :func:`resolve_default_symbol` turns it into a
generated symbol at runtime; :func:`migrate_default_symbols` converts the symbol names
that older versions stored ("Resistor", "Op-Amp" …) idempotently – every way of opening a
library runs it (:func:`partforge.db.lifecycle.open_database`) – and
:func:`ensure_default_symbol_kinds` repeats the check on the open database (cheap read,
writes only when needed).

Category labels: older versions wrote "&" in four labels ("Quarze & Oszillatoren" …);
:func:`migrate_category_labels` renames them to the current "und" spelling – only labels that
still equal the old built-in text and that the user never changed explicitly (``pf_audit``).
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - typing only (no heavy imports at import time)
    from sqlalchemy import Connection

    from ..geometry.model import FootprintSpec, SymbolSpec
    from ..symbols.models import SymbolRequest
    from ..workspace import SymbolStyle

log = logging.getLogger(__name__)

FieldKind = Literal["text", "quantity", "enum", "bool", "int", "url", "path", "date", "range"]


class FieldTemplate(BaseModel):
    column: str  # physical column name == Altium parameter name
    label: str  # German UI label
    kind: FieldKind = "text"
    unit: str | None = None  # canonical unit for kind="quantity"/"range" (Ω, F, H, V, A, W, Hz, %, ppm/K, °C, ...)
    options: list[str] = Field(default_factory=list)  # for kind="enum" (free text still allowed)
    required: bool = False
    show_on_schematic: bool = False  # DbLib VisibleOnAdd
    add_to_design: bool = True  # DbLib: add as component parameter when placed
    system: bool = False  # Altium link fields / PartForge bookkeeping (not user parameters)
    grid_width: int | None = None
    help: str | None = None


class CategoryTemplate(BaseModel):
    table: str  # database table == Altium library name in the Components panel
    label: str  # German UI label
    prefix: str  # designator prefix
    icon: str  # lucide icon name for the UI
    color: str  # accent colour for the UI
    default_symbol: str | None = None  # symbol kind key (partforge.symbols.kinds()), resolved at runtime
    value_field: str | None = None  # field whose formatted value goes into "Value"
    description_template: str = "{Manufacturer Part Number}"
    comment_template: str = "{Value}"
    fields: list[FieldTemplate] = Field(default_factory=list)


def F(column: str, label: str, kind: FieldKind = "text", unit: str | None = None, **kw) -> FieldTemplate:
    return FieldTemplate(column=column, label=label, kind=kind, unit=unit, **kw)


# --------------------------------------------------------------------------- common fields
# Order = default column order in the grid and in the DbLib.
COMMON_FIELDS: list[FieldTemplate] = [
    F("Part Number", "Teilenummer", required=True, system=False, grid_width=190,
      help="Eindeutiger Schlüssel der Datenbank (Standard: Hersteller-Teilenummer)."),
    F("Manufacturer", "Hersteller", required=True, grid_width=140),
    F("Manufacturer Part Number", "Hersteller-Teilenummer", required=True, grid_width=190),
    F("Value", "Wert", show_on_schematic=False, grid_width=100),
    F("Description", "Beschreibung", required=True, grid_width=320),
    F("Comment", "Kommentar (Schaltplan)", show_on_schematic=True, grid_width=120,
      help="Wird im Schaltplan als Comment angezeigt – der einzige sichtbare Parameter (Wert bzw. MPN)."),
    F("Package", "Gehäuse", grid_width=110),
    F("Mounting", "Montage", "enum", options=["SMD", "THT", "Hybrid", "Chassis"], grid_width=90),
    F("Height", "Bauhöhe max.", "quantity", "mm", grid_width=90),
    F("Operating Temperature", "Betriebstemperatur", "range", "°C", grid_width=140),
    F("Library Ref", "Symbol", required=True, system=True, add_to_design=False, grid_width=150),
    F("Library Path", "Symbol-Bibliothek", "path", system=True, add_to_design=False, grid_width=180),
    F("Footprint Ref", "Footprint", required=True, system=True, add_to_design=False, grid_width=170),
    F("Footprint Path", "Footprint-Bibliothek", "path", system=True, add_to_design=False, grid_width=180),
    F("Footprint Ref 2", "Footprint (Alternative)", system=True, add_to_design=False),
    F("Footprint Path 2", "Footprint-Bibliothek (Alternative)", "path", system=True, add_to_design=False),
    F("ComponentLink1Description", "Link-Beschriftung", system=True, grid_width=120),
    F("ComponentLink1URL", "Datenblatt", "url", system=True, grid_width=200),
    F("Supplier 1", "Lieferant 1", "enum", options=["Digi-Key", "Mouser", "Farnell", "RS", "LCSC", "Reichelt", "TME", "Arrow"]),
    F("Supplier Part Number 1", "Bestellnummer 1"),
    F("Supplier 2", "Lieferant 2", "enum", options=["Digi-Key", "Mouser", "Farnell", "RS", "LCSC", "Reichelt", "TME", "Arrow"]),
    F("Supplier Part Number 2", "Bestellnummer 2"),
    F("Lifecycle", "Lebenszyklus", "enum", options=["Aktiv", "NRND", "Abgekündigt", "Obsolet", "Unbekannt"], grid_width=100),
    F("RoHS", "RoHS", "enum", options=["Ja", "Nein", "Unbekannt"], grid_width=70),
    F("PF Status", "Freigabe", "enum", options=["Entwurf", "Geprüft", "Freigegeben", "Gesperrt"], system=True,
      add_to_design=False, grid_width=100, help="PartForge-Freigabestatus"),
    F("Notes", "Notizen", add_to_design=False),
    F("PF Created", "Angelegt", "date", system=True, add_to_design=False),
    F("PF Modified", "Geändert", "date", system=True, add_to_design=False),
    F("PF Author", "Bearbeiter", system=True, add_to_design=False),
]

SIZES_CHIP = ["01005", "0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010", "2512"]

CATEGORIES: list[CategoryTemplate] = [
    CategoryTemplate(
        table="Resistors", label="Widerstände", prefix="R", icon="activity", color="#FF8A3D",
        default_symbol="resistor", value_field="Resistance",
        description_template="RES {Size} {Resistance} {Tolerance} {Power} {Technology}",
        comment_template="{Resistance:rkm}",  # house style: "4k7", "100R"
        fields=[
            F("Resistance", "Widerstand", "quantity", "Ω", required=True),
            F("Tolerance", "Toleranz", "quantity", "%", required=True),
            F("Power", "Leistung", "quantity", "W", required=True),
            F("Voltage", "Max. Spannung", "quantity", "V"),
            F("TCR", "Temperaturkoeffizient", "quantity", "ppm/K"),
            F("Technology", "Technologie", "enum",
              options=["Dickschicht", "Dünnschicht", "Metallfilm", "Kohleschicht", "Drahtwiderstand", "Metallstreifen (Shunt)", "Netzwerk"]),
            F("Size", "Baugröße", "enum", options=SIZES_CHIP),
        ],
    ),
    CategoryTemplate(
        table="Capacitors", label="Kondensatoren", prefix="C", icon="square-split-horizontal", color="#38BDF8",
        default_symbol="capacitor", value_field="Capacitance",
        description_template="CAP {Type} {Size} {Capacitance} {Voltage} {Tolerance} {Dielectric}",
        comment_template="{Capacitance:rkm} {Voltage}",  # house style: "100n 50V", "4u7 6.3V"
        fields=[
            F("Capacitance", "Kapazität", "quantity", "F", required=True),
            F("Voltage", "Nennspannung", "quantity", "V", required=True),
            F("Tolerance", "Toleranz", "quantity", "%"),
            F("Dielectric", "Dielektrikum", "enum",
              options=["C0G/NP0", "X7R", "X5R", "X6S", "X7S", "X8R", "Y5V", "Z5U", "Tantal", "Aluminium", "Polymer", "Folie"]),
            F("Type", "Bauart", "enum", options=["MLCC", "Tantal", "Aluminium-Elko", "Polymer", "Folie", "Superkondensator"]),
            F("Polarized", "Gepolt", "bool"),
            F("Size", "Baugröße", "enum", options=SIZES_CHIP + ["3216-18", "3528-21", "6032-28", "7343-31"]),
            F("ESR", "ESR", "quantity", "Ω"),
            F("Ripple Current", "Rippelstrom", "quantity", "A"),
            F("Lifetime", "Lebensdauer", "text"),
        ],
    ),
    CategoryTemplate(
        table="Inductors", label="Induktivitäten", prefix="L", icon="waves", color="#A78BFA",
        default_symbol="inductor", value_field="Inductance",
        description_template="IND {Size} {Inductance} {Current Rating} {Tolerance} {Shielding}",
        comment_template="{Inductance:rkm}",  # house style: "10u", "4u7", "100n"
        fields=[
            F("Inductance", "Induktivität", "quantity", "H", required=True),
            F("Tolerance", "Toleranz", "quantity", "%"),
            F("Current Rating", "Nennstrom", "quantity", "A"),
            F("Saturation Current", "Sättigungsstrom", "quantity", "A"),
            F("DCR", "DC-Widerstand", "quantity", "Ω"),
            F("SRF", "Eigenresonanz", "quantity", "Hz"),
            F("Shielding", "Schirmung", "enum", options=["geschirmt", "halbgeschirmt", "ungeschirmt"]),
            F("Size", "Baugröße", "text"),
        ],
    ),
    CategoryTemplate(
        table="Ferrite Beads", label="Ferrite", prefix="FB", icon="magnet", color="#94A3B8",
        default_symbol="ferrite_bead", value_field="Impedance",
        description_template="FERRITE {Size} {Impedance}@100MHz {Current Rating}",
        comment_template="{Impedance:rkm}@100MHz",  # house style: "180R@100MHz"
        fields=[
            F("Impedance", "Impedanz @100 MHz", "quantity", "Ω", required=True),
            F("Current Rating", "Nennstrom", "quantity", "A"),
            F("DCR", "DC-Widerstand", "quantity", "Ω"),
            F("Size", "Baugröße", "enum", options=SIZES_CHIP),
        ],
    ),
    CategoryTemplate(
        table="Diodes", label="Dioden", prefix="D", icon="triangle-right", color="#F2555A",
        default_symbol="diode", value_field="Manufacturer Part Number",
        description_template="DIODE {Diode Type} {Reverse Voltage} {Forward Current} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Diode Type", "Diodentyp", "enum",
              options=["Gleichrichter", "Schottky", "Z-Diode", "TVS", "Schaltdiode", "Kapazitätsdiode", "Brückengleichrichter"]),
            F("Reverse Voltage", "Sperrspannung", "quantity", "V"),
            F("Forward Current", "Durchlassstrom", "quantity", "A"),
            F("Forward Voltage", "Flussspannung", "quantity", "V"),
            F("Zener Voltage", "Z-Spannung", "quantity", "V"),
            F("Power", "Verlustleistung", "quantity", "W"),
            F("Configuration", "Konfiguration", "enum",
              options=["Einzeln", "Doppel gem. Kathode", "Doppel gem. Anode", "Doppel in Serie", "Bidirektional"]),
        ],
    ),
    CategoryTemplate(
        table="LEDs", label="LEDs", prefix="D", icon="lightbulb", color="#3DD68C",
        default_symbol="led", value_field="Color",
        description_template="LED {Color} {Wavelength} {Size} {Luminous Intensity}",
        comment_template="{Color}",
        fields=[
            F("Color", "Farbe", "enum", options=["Rot", "Grün", "Blau", "Gelb", "Orange", "Weiß", "RGB", "IR", "UV"],
              required=True),
            F("Wavelength", "Wellenlänge", "quantity", "nm"),
            F("Luminous Intensity", "Lichtstärke", "quantity", "cd"),
            F("Forward Voltage", "Flussspannung", "quantity", "V"),
            F("Forward Current", "Nennstrom", "quantity", "A"),
            F("Viewing Angle", "Abstrahlwinkel", "quantity", "°"),
            F("Size", "Baugröße", "text"),
        ],
    ),
    CategoryTemplate(
        table="Transistors BJT", label="Bipolartransistoren", prefix="Q", icon="git-fork", color="#F5B544",
        default_symbol="npn", value_field="Manufacturer Part Number",
        description_template="BJT {Polarity} {VCEO} {IC} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Polarity", "Polarität", "enum", options=["NPN", "PNP", "NPN+PNP", "Dual NPN", "Dual PNP", "Darlington NPN", "Darlington PNP"],
              required=True),
            F("VCEO", "U_CEO", "quantity", "V"),
            F("IC", "I_C max.", "quantity", "A"),
            F("hFE", "Stromverstärkung hFE"),
            F("Power", "Verlustleistung", "quantity", "W"),
            F("fT", "Transitfrequenz", "quantity", "Hz"),
        ],
    ),
    CategoryTemplate(
        table="Transistors FET", label="Feldeffekttransistoren", prefix="Q", icon="git-merge", color="#F59E0B",
        default_symbol="nmos", value_field="Manufacturer Part Number",
        description_template="MOSFET {Channel} {VDS} {ID} {RDS(on)} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Channel", "Kanal", "enum", options=["N", "P", "N+P", "Dual N", "Dual P"], required=True),
            F("FET Type", "Typ", "enum", options=["MOSFET", "JFET", "GaN", "SiC"]),
            F("VDS", "U_DS", "quantity", "V"),
            F("ID", "I_D", "quantity", "A"),
            F("RDS(on)", "R_DS(on)", "quantity", "Ω"),
            F("VGS(th)", "U_GS(th)", "quantity", "V"),
            F("Qg", "Gate-Ladung", "quantity", "C"),
            F("Power", "Verlustleistung", "quantity", "W"),
        ],
    ),
    CategoryTemplate(
        table="Amplifiers", label="Verstärker", prefix="U", icon="triangle", color="#E8467C",
        default_symbol="opamp_dual", value_field="Manufacturer Part Number",
        description_template="IC OPAMP {Channels}CH {GBW} {Slew Rate} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Amplifier Type", "Typ", "enum",
              options=["Operationsverstärker", "Komparator", "Instrumentenverstärker", "Differenzverstärker", "Stromshunt-Verstärker",
                       "Audioverstärker", "Video/HF"]),
            F("Channels", "Kanäle", "int"),
            F("GBW", "Verstärkungs-Bandbreite", "quantity", "Hz"),
            F("Slew Rate", "Slew-Rate", "text", help="z. B. 290V/µs"),
            F("Supply Voltage", "Versorgung", "range", "V"),
            F("Input Offset", "Offsetspannung", "quantity", "V"),
            F("Rail-to-Rail", "Rail-to-Rail", "enum", options=["Nein", "Eingang", "Ausgang", "Ein-/Ausgang"]),
        ],
    ),
    CategoryTemplate(
        table="Power Linear", label="Linearregler und Referenzen", prefix="U", icon="gauge", color="#22C55E",
        value_field="Manufacturer Part Number",
        description_template="IC REG LINEAR {Output Voltage} {Output Current} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Regulator Type", "Typ", "enum", options=["LDO", "Linearregler", "Spannungsreferenz", "Shunt-Regler", "Stromquelle"]),
            F("Input Voltage", "Eingangsspannung", "range", "V"),
            F("Output Voltage", "Ausgangsspannung", "text"),
            F("Output Current", "Ausgangsstrom", "quantity", "A"),
            F("Dropout Voltage", "Dropout", "quantity", "V"),
            F("Accuracy", "Genauigkeit", "quantity", "%"),
        ],
    ),
    CategoryTemplate(
        table="Power Switchmode", label="Schaltregler", prefix="U", icon="zap", color="#EAB308",
        value_field="Manufacturer Part Number",
        description_template="IC REG {Topology} {Input Voltage} {Output Current} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Topology", "Topologie", "enum",
              options=["Buck", "Boost", "Buck-Boost", "Inverter", "SEPIC", "Flyback", "Controller", "Gate-Treiber", "Ladungspumpe", "PMIC"]),
            F("Input Voltage", "Eingangsspannung", "range", "V"),
            F("Output Voltage", "Ausgangsspannung", "text"),
            F("Output Current", "Ausgangsstrom", "quantity", "A"),
            F("Switching Frequency", "Schaltfrequenz", "quantity", "Hz"),
            F("Integrated Switch", "Integrierter Schalter", "bool"),
        ],
    ),
    CategoryTemplate(
        table="Data Converters", label="Datenwandler", prefix="U", icon="binary", color="#06B6D4",
        value_field="Manufacturer Part Number",
        description_template="IC {Converter Type} {Resolution}BIT {Sample Rate} {Interface} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Converter Type", "Typ", "enum", options=["ADC", "DAC", "Digitalpotentiometer", "AFE", "Codec"]),
            F("Resolution", "Auflösung (Bit)", "int"),
            F("Sample Rate", "Abtastrate", "quantity", "Hz"),
            F("Channels", "Kanäle", "int"),
            F("Interface", "Schnittstelle", "enum", options=["SPI", "I²C", "Parallel", "LVDS", "JESD204", "I²S", "Analog"]),
            F("Supply Voltage", "Versorgung", "range", "V"),
        ],
    ),
    CategoryTemplate(
        table="Integrated Circuits", label="ICs", prefix="U", icon="cpu", color="#818CF8",
        value_field="Manufacturer Part Number",
        description_template="IC {Function} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Function", "Funktion", "enum",
              options=["Mikrocontroller", "FPGA/CPLD", "Speicher", "Schnittstelle", "Logik", "Sensor", "Treiber", "Timer", "Schalter/Multiplexer",
                       "Funk/RF", "Audio", "Video", "Uhr/Takt", "Sonstiges"],
              required=True),
            F("Supply Voltage", "Versorgung", "range", "V"),
            F("Interface", "Schnittstelle"),
            F("Channels", "Kanäle", "int"),
            F("Core", "Kern/Architektur"),
            F("Memory Size", "Speichergröße"),
        ],
    ),
    CategoryTemplate(
        table="Optocouplers", label="Optokoppler und Optoelektronik", prefix="U", icon="sun-medium", color="#FB7185",
        value_field="Manufacturer Part Number",
        description_template="OPTO {Opto Type} {Isolation Voltage} {Output Type} {Package}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Opto Type", "Typ", "enum", options=["Optokoppler", "Fotodiode", "Fototransistor", "Lichtschranke", "Digitaler Isolator"]),
            F("Output Type", "Ausgang", "enum", options=["Transistor", "Darlington", "Logik", "Triac", "MOSFET", "Analog"]),
            F("Isolation Voltage", "Isolationsspannung", "quantity", "V"),
            F("CTR", "CTR", "text"),
            F("Data Rate", "Datenrate", "text"),
        ],
    ),
    CategoryTemplate(
        table="Oscillators", label="Quarze und Oszillatoren", prefix="Y", icon="audio-waveform", color="#2DD4BF",
        default_symbol="crystal_2", value_field="Frequency",
        description_template="{Oscillator Type} {Frequency} {Frequency Tolerance} {Load Capacitance} {Package}",
        comment_template="{Frequency}",
        fields=[
            F("Oscillator Type", "Typ", "enum", options=["Quarz", "Oszillator", "Keramikresonator", "MEMS-Oszillator", "TCXO", "VCXO"],
              required=True),
            F("Frequency", "Frequenz", "quantity", "Hz", required=True),
            F("Frequency Tolerance", "Frequenztoleranz", "quantity", "ppm"),
            F("Frequency Stability", "Frequenzstabilität", "quantity", "ppm"),
            F("Load Capacitance", "Lastkapazität", "quantity", "F"),
            F("ESR", "ESR", "quantity", "Ω"),
            F("Supply Voltage", "Versorgung", "range", "V"),
        ],
    ),
    CategoryTemplate(
        table="Connectors", label="Steckverbinder", prefix="J", icon="plug", color="#60A5FA",
        default_symbol="connector", value_field="Manufacturer Part Number",
        description_template="CONN {Connector Type} {Pins}POS {Pitch} {Orientation} {Gender}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Connector Type", "Typ", "enum",
              options=["Stiftleiste", "Buchsenleiste", "USB", "RJ45", "D-Sub", "Klemme", "Koax", "FFC/FPC", "Rundsteckverbinder",
                       "Platine-zu-Platine", "Kartenhalter", "Sonstiges"],
              required=True),
            F("Pins", "Pole", "int", required=True),
            F("Rows", "Reihen", "int"),
            F("Pitch", "Raster", "quantity", "mm"),
            F("Orientation", "Ausrichtung", "enum", options=["gerade", "gewinkelt", "liegend"]),
            F("Gender", "Geschlecht", "enum", options=["Stecker", "Buchse", "Zwitter"]),
            F("Current Rating", "Nennstrom", "quantity", "A"),
            F("Series", "Serie"),
        ],
    ),
    CategoryTemplate(
        table="Electromechanical", label="Elektromechanik", prefix="S", icon="toggle-left", color="#C084FC",
        value_field="Manufacturer Part Number",
        description_template="{Electromech Type} {Contact Configuration} {Current Rating} {Voltage Rating}",
        comment_template="{Manufacturer Part Number}",
        fields=[
            F("Electromech Type", "Typ", "enum",
              options=["Taster", "Schalter", "DIP-Schalter", "Drehgeber", "Relais", "Summer/Lautsprecher", "Batteriehalter", "Lüfter",
                       "Potentiometer", "Sonstiges"],
              required=True),
            F("Contact Configuration", "Kontaktart", "enum", options=["SPST", "SPDT", "DPST", "DPDT", "SPST-NO", "SPST-NC"]),
            F("Current Rating", "Nennstrom", "quantity", "A"),
            F("Voltage Rating", "Nennspannung", "quantity", "V"),
            F("Coil Voltage", "Spulenspannung", "quantity", "V"),
        ],
    ),
    CategoryTemplate(
        table="Fuses", label="Sicherungen und Schutz", prefix="F", icon="shield", color="#F97316",
        default_symbol="fuse", value_field="Current Rating",
        description_template="FUSE {Protection Type} {Current Rating} {Voltage Rating} {Characteristic} {Package}",
        comment_template="{Current Rating}",
        fields=[
            F("Protection Type", "Typ", "enum", options=["Sicherung", "PTC (rückstellend)", "Varistor", "Gasableiter", "ESD-Schutz"],
              required=True),
            F("Current Rating", "Nennstrom", "quantity", "A"),
            F("Voltage Rating", "Nennspannung", "quantity", "V"),
            F("Breaking Capacity", "Schaltvermögen", "quantity", "A"),
            F("Characteristic", "Charakteristik", "enum", options=["superflink", "flink", "mittelträge", "träge", "superträge"]),
        ],
    ),
    CategoryTemplate(
        table="Mechanical", label="Mechanik", prefix="MH", icon="wrench", color="#9CA3AF",
        default_symbol="mounting_hole", value_field="Mechanical Type",
        description_template="{Mechanical Type} {Size}",
        comment_template="{Mechanical Type}",
        fields=[
            F("Mechanical Type", "Typ", "enum",
              options=["Befestigungsloch", "Fiducial", "Testpunkt", "Kühlkörper", "Abstandsbolzen", "Schirmblech", "Logo", "Sonstiges"],
              required=True),
            F("Size", "Größe"),
        ],
    ),
]


def category_by_table(table: str) -> CategoryTemplate | None:
    return next((c for c in CATEGORIES if c.table == table), None)


def template_for(table: str, columns: Iterable[str] = (), *, builtin: bool = False) -> CategoryTemplate | None:
    """The built-in template a category was made from, or ``None``.

    Same table name (any letter case); for a category created from a template under another
    name (``builtin``, e.g. "Resistors THT") the only template whose own fields all exist in
    ``columns``. Ambiguous or unknown categories give ``None``."""
    folded = (table or "").casefold()
    same = next((c for c in CATEGORIES if c.table.casefold() == folded), None)
    if same is not None or not builtin:
        return same
    present = {str(c).casefold() for c in columns}
    matches = [c for c in CATEGORIES if c.fields and all(f.column.casefold() in present for f in c.fields)]
    return matches[0] if len(matches) == 1 else None


# --------------------------------------------------------------------------- defaults of older versions

#: Value fields that older versions showed on the schematic (DbLib ``VisibleOnAdd``) together
#: with a hidden Comment. Opening such a library hides them once and shows the Comment
#: instead (:func:`partforge.db.lifecycle.open_database`) – fields the user changed are kept.
LEGACY_VISIBLE_FIELDS: dict[str, tuple[str, ...]] = {
    "Resistors": ("Resistance",),
    "Capacitors": ("Capacitance", "Voltage"),
    "Inductors": ("Inductance",),
    "Ferrite Beads": ("Impedance",),
    "LEDs": ("Color",),
    "Oscillators": ("Frequency",),
    "Fuses": ("Current Rating",),
}

#: Comment templates that older versions created for built-in categories (table -> templates).
#: A library still using one of them gets the current template when it is opened, and the
#: Comments of its parts that still show the generated text follow.
LEGACY_COMMENT_TEMPLATES: dict[str, tuple[str, ...]] = {
    "Capacitors": ("{Capacitance}", "{Capacitance:rkm}"),
    "Inductors": ("{Inductance}",),
    "Ferrite Beads": ("{Impedance}",),
}


#: Labels that older versions gave built-in categories (table -> labels). A library still using one
#: of them gets the current label when it is opened (:func:`migrate_category_labels`).
LEGACY_CATEGORY_LABELS: dict[str, tuple[str, ...]] = {
    "Power Linear": ("Linearregler & Referenzen",),
    "Optocouplers": ("Optokoppler & Opto", "Optokoppler und Opto"),
    "Oscillators": ("Quarze & Oszillatoren",),
    "Fuses": ("Sicherungen & Schutz",),
}


def _explicit_label_tables(conn: Connection) -> set[str]:
    """Tables (casefolded) whose label the user changed through PartForge (``pf_audit``)."""
    import json

    from sqlalchemy import select

    from .schema import pf_audit  # runtime import: schema imports this module

    tables: set[str] = set()
    rows = conn.execute(select(pf_audit.c.table_name, pf_audit.c.changes).where(pf_audit.c.action == "schema"))
    for table, raw in rows:
        try:
            changes = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if table and isinstance(changes, dict) and changes.get("op") == "update_category" and "label" in changes:
            tables.add(str(table).casefold())
    return tables


def migrate_category_labels(conn: Connection, *, author: str = "PartForge") -> list[str]:
    """Idempotent data migration: built-in category labels of older versions -> current labels.

    Changes ``pf_categories.label`` only where it still equals an old built-in label of the same
    table (:data:`LEGACY_CATEGORY_LABELS`) and the user never changed the label explicitly; writes a
    ``schema`` audit entry per category. Runs inside the caller's write transaction; returns German
    notes (empty when nothing had to change). Callers invalidate the category cache afterwards.
    """
    from sqlalchemy import select, update

    from . import audit
    from .schema import now_iso, pf_categories  # runtime import: schema imports this module

    rows = conn.execute(select(pf_categories.c.table_name, pf_categories.c.label)).all()
    pending: list[tuple[str, str, str]] = []
    for table, label in rows:
        template = template_for(str(table))
        old_labels = LEGACY_CATEGORY_LABELS.get(template.table, ()) if template is not None else ()
        if template is not None and label in old_labels and label != template.label:
            pending.append((str(table), str(label), template.label))
    if not pending:
        return []
    explicit = _explicit_label_tables(conn)
    notes: list[str] = []
    for table, old, new in pending:
        if table.casefold() in explicit:
            continue
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == table)
                     .values(label=new, modified=now_iso()))
        audit.record(conn, "schema", table, None, {"op": "migrate_category_label", "label": [old, new]}, author)
        notes.append(f"Bezeichnung der Kategorie „{table}“: „{old}“ → „{new}“.")
    for note in notes:
        log.info("Datenmigration: %s", note)
    return notes


# --------------------------------------------------------------------------- default symbols

#: ``default_symbol`` of the built-in categories as stored by older PartForge versions
#: (table -> symbol *name*); :func:`default_symbol_kind` maps them to the current template
#: kind (``Amplifiers`` "Op-Amp" -> ``opamp_dual``, the dual op-amp of the house libraries).
LEGACY_DEFAULT_SYMBOLS: dict[str, str] = {
    "Resistors": "Resistor",
    "Capacitors": "Capacitor",
    "Inductors": "Inductor",
    "Ferrite Beads": "Ferrite Bead",
    "Diodes": "Diode",
    "LEDs": "LED",
    "Transistors BJT": "NPN",
    "Transistors FET": "NMOS",
    "Amplifiers": "Op-Amp",
    "Oscillators": "Crystal",
    "Fuses": "Fuse",
}

_IC_KIND = "ic"  # needs a pin list: never a category default
DefaultSymbolSource = Literal["values", "category"]


class CategoryLike(Protocol):
    """What :func:`resolve_default_symbol` needs of a category (``CategoryDef`` or ``CategoryTemplate``)."""

    table: str
    default_symbol: str | None


@dataclass(frozen=True, slots=True)
class DefaultSymbol:
    """A generated standard symbol for a category (see :func:`resolve_default_symbol`).

    ``source`` tells where it comes from: ``"values"`` = the symbol mapping of
    :mod:`partforge.symbols` chose it from the part's values (pinout certain),
    ``"category"`` = the category's ``default_symbol`` kind.
    """

    kind: str
    request: SymbolRequest
    spec: SymbolSpec
    source: DefaultSymbolSource

    @property
    def name(self) -> str:
        """Symbol name (``Library Ref``) in the house style that generated it."""
        return self.spec.name


@functools.cache
def _kind_lookup() -> dict[str, str]:
    """Casefolded kind key or default symbol name -> kind key (standard kinds, without ``ic``)."""
    from ..symbols import kinds  # runtime import: the db package must stay light to import

    infos = [info for info in kinds() if info.key != _IC_KIND]
    lookup = {info.default_name.casefold(): info.key for info in infos}
    lookup.update({info.key.casefold(): info.key for info in infos})  # keys win over names
    return lookup


def default_symbol_kind(value: str | None, table: str | None = None) -> str | None:
    """The symbol kind key a ``default_symbol`` value stands for, or ``None``.

    Accepts kind keys (any letter case) and symbol names of older versions: the legacy
    default of a built-in table maps to that template's current kind, any other name of
    a standard symbol ("Op-Amp", "Crystal 4-Pin") to its kind. Unknown values (e.g. a
    house-style name like "Diode (AK)" or an IC) give ``None``.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
    if not text:
        return None
    if table is not None and LEGACY_DEFAULT_SYMBOLS.get(table) == text:
        template = category_by_table(table)
        if template is not None and template.default_symbol:
            return template.default_symbol
    return _kind_lookup().get(text.casefold())


def _has_values(values: Mapping[str, Any] | None) -> bool:
    if not values:
        return False
    return any(v is not None and str(v).strip() for v in values.values())


def resolve_default_symbol(
    category: CategoryLike | str,
    values: Mapping[str, Any] | None = None,
    style: SymbolStyle | None = None,
    *,
    footprint: FootprintSpec | Sequence[str] | None = None,
) -> DefaultSymbol | None:
    """Standard symbol for a part of ``category`` (a ``CategoryDef``/template or a built-in table name).

    * Without values (or for categories without symbol mapping rules, i.e. custom
      categories): the category's ``default_symbol`` kind, generated in ``style``
      (``None`` = open workspace / defaults) – e.g. "Diode" or "Diode (AK)".
    * With values of a built-in category: the suggestion of
      :func:`partforge.symbols.standard_symbol_for` (``footprint`` = spec or pad list to
      check against), or ``None`` when no symbol is certain (pin map to choose, dual
      transistor, IC …). The category default is never used to guess a pinout.
    """
    from ..symbols import SymbolError, generate, standard_symbol_for
    from ..symbols.models import SymbolRequest

    if isinstance(category, str):
        table = category
        template = category_by_table(category)
        default = template.default_symbol if template is not None else None
    else:
        table, default = category.table, category.default_symbol
    request: SymbolRequest | None
    source: DefaultSymbolSource
    if _has_values(values) and category_by_table(table) is not None:
        request = standard_symbol_for(table, values, footprint=footprint, style=style)
        source = "values"
    else:
        kind = default_symbol_kind(default, table)
        request = SymbolRequest(kind=kind) if kind is not None else None
        source = "category"
    if request is None:
        return None
    try:
        spec = generate(request, style)
    except SymbolError as exc:
        log.warning("Standardsymbol für %s nicht erzeugbar (%s): %s", table, request.kind, exc)
        return None
    return DefaultSymbol(kind=request.kind, request=request, spec=spec, source=source)


def _default_symbol_rows(conn: Connection) -> list[tuple[str, str | None]]:
    from sqlalchemy import select

    from .schema import pf_categories  # runtime import: schema imports this module

    rows = conn.execute(select(pf_categories.c.table_name, pf_categories.c.default_symbol)).all()
    return [(str(table), value) for table, value in rows]


def _default_symbol_updates(rows: Sequence[tuple[str, str | None]]) -> list[tuple[str, str, str]]:
    """``(table, stored value, kind key)`` for every stored value that is not yet a kind key."""
    updates: list[tuple[str, str, str]] = []
    for table, value in rows:
        if value is None or not str(value).strip():
            continue
        kind = default_symbol_kind(value, table)
        if kind is not None and kind != value:
            updates.append((table, str(value), kind))
    return updates


def migrate_default_symbols(conn: Connection) -> list[str]:
    """Idempotent data migration: symbol names in ``pf_categories.default_symbol`` -> kind keys.

    Runs inside the caller's write transaction; returns German notes of the changes (empty
    when nothing had to change). Unknown values are kept (logged). Callers must invalidate
    the category cache (:func:`partforge.db.categories.invalidate_cache`) after changes.
    """
    from sqlalchemy import update

    from .schema import pf_categories  # runtime import: schema imports this module

    rows = _default_symbol_rows(conn)
    for table, value in rows:
        if value is not None and str(value).strip() and default_symbol_kind(value, table) is None:
            log.warning("Kategorie %s: Standardsymbol „%s“ ist kein bekannter Symboltyp – unverändert", table, value)
    notes: list[str] = []
    for table, value, kind in _default_symbol_updates(rows):
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == table).values(default_symbol=kind))
        notes.append(f"Standardsymbol der Kategorie „{table}“: „{value}“ → Symboltyp „{kind}“.")
    for note in notes:
        log.info("Datenmigration: %s", note)
    return notes


def ensure_default_symbol_kinds() -> list[str]:
    """Run :func:`migrate_default_symbols` on the open database if anything needs it.

    Opening a library migrates already (:func:`partforge.db.lifecycle.open_database`); this
    check catches symbol names written later (another program, a restored table). Reads
    ``pf_categories`` without the write lock and only opens a write transaction when a
    symbol name is found. Invalidates the category cache after changes. Returns the German
    notes.
    """
    from . import categories, core  # runtime import: core/categories import this module indirectly

    with core.read() as conn:
        pending = _default_symbol_updates(_default_symbol_rows(conn))
    if not pending:
        return []
    with core.connect() as conn:
        notes = migrate_default_symbols(conn)
    if notes:
        categories.invalidate_cache()
    return notes
