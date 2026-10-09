"""standard_symbol_for / suggest_symbol: category table + field values (+ pins, footprint) -> standard symbol."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from partforge.geometry.model import FootprintSpec, Pad, check_symbol_footprint
from partforge.symbols import (
    SymbolRequest,
    SymbolSuggestion,
    check_spec,
    generate,
    standard_symbol_for,
    suggest_symbol,
)
from partforge.symbols.models import IcPin
from partforge.workspace import SymbolStyle

CASES: list[tuple[str, dict[str, Any], str | None, dict[str, Any]]] = [
    # table, values, expected kind of the ready request (None = no safe request), expected params (subset)
    ("Resistors", {"Resistance": "10k"}, "resistor", {}),
    ("Resistors", {"Resistance": "10k", "Package": "0603"}, "resistor", {}),
    ("Resistors", {"Technology": "Netzwerk"}, None, {}),
    ("Resistors", {"Package": "4-SMD"}, None, {}),  # 4-terminal (Kelvin) shunt
    ("Capacitors", {"Capacitance": "100n", "Type": "MLCC"}, "capacitor", {}),
    ("Capacitors", {"Polarized": "Ja"}, "capacitor_polarized", {}),
    ("Capacitors", {"Polarized": "true"}, "capacitor_polarized", {}),
    ("Capacitors", {"Type": "Tantal"}, "capacitor_polarized", {}),
    ("Capacitors", {"Type": "Aluminium-Elko"}, "capacitor_polarized", {}),
    ("Capacitors", {"Type": "Polymer"}, "capacitor_polarized", {}),
    ("Capacitors", {"Dielectric": "Tantal"}, "capacitor_polarized", {}),
    ("Capacitors", {"Type": "Aluminium-Elko", "Polarized": "Nein"}, "capacitor", {}),  # bipolar elko
    ("Capacitors", {"Type": "Folie"}, "capacitor", {}),
    ("Capacitors", {"Package": "3-SMD"}, None, {}),  # feed-through filter
    ("Inductors", {}, "inductor", {}),
    ("Inductors", {"Package": "4-SMD"}, None, {}),  # coupled inductor / common-mode choke
    ("Ferrite Beads", {"Impedance": "600"}, "ferrite_bead", {}),
    ("Diodes", {"Diode Type": "Gleichrichter"}, "diode", {}),
    ("Diodes", {"Diode Type": "Gleichrichter", "Package": "SMA"}, "diode", {}),
    ("Diodes", {"Diode Type": "Schaltdiode", "Package": "SOT-23"}, "diode", {"pinmap": "AxK"}),
    ("Diodes", {"Diode Type": "Schottky", "Package": "SOD-123"}, "schottky", {}),
    ("Diodes", {"Diode Type": "Z-Diode", "Package": "SOT-23-3"}, "zener", {"pinmap": "AxK"}),
    ("Diodes", {"Diode Type": "Schottky", "Footprint Ref": "SOT95P280X145-3N"}, "schottky", {"pinmap": "AxK"}),
    ("Diodes", {"Diode Type": "Schottky", "Package": "TO-220AC"}, None, {}),  # power package: ask
    ("Diodes", {"Diode Type": "Schottky", "Package": "D2PAK"}, None, {}),
    ("Diodes", {"Diode Type": "TVS"}, "tvs_uni", {}),
    ("Diodes", {"Diode Type": "TVS", "Configuration": "Bidirektional"}, "tvs_bi", {}),
    ("Diodes", {"Diode Type": "TVS", "Manufacturer Part Number": "SMAJ24CA"}, "tvs_bi", {}),
    ("Diodes", {"Diode Type": "TVS", "Manufacturer Part Number": "SMAJ24A"}, "tvs_uni", {}),
    ("Diodes", {"Diode Type": "TVS", "Description": "TVS DIODE 5V BIDIRECTIONAL"}, "tvs_bi", {}),
    ("Diodes", {"Diode Type": "TVS", "Configuration": "Bidirektional", "Package": "SOT-23"}, None, {}),
    ("Diodes", {"Diode Type": "Brückengleichrichter", "Package": "GBU"}, "bridge_rectifier", {}),
    ("Diodes", {"Diode Type": "Brückengleichrichter"}, None, {}),  # SMD bridges differ: ask
    ("Diodes", {"Diode Type": "Kapazitätsdiode"}, "diode", {}),
    ("Diodes", {"Diode Type": "Schottky", "Configuration": "Doppel gem. Kathode"}, None, {}),
    ("Diodes", {}, "diode", {}),
    ("LEDs", {"Color": "Rot"}, "led", {}),
    ("LEDs", {"Color": "Rot", "Package": "5mm"}, "led", {}),
    ("LEDs", {"Color": "Rot", "Package": "PLCC-2"}, "led", {}),
    ("LEDs", {"Color": "Rot", "Package": "PLCC-4"}, None, {}),
    ("LEDs", {"Color": "Grün", "Package": "SOT-23"}, "led", {"pinmap": "AxK"}),
    ("LEDs", {"Color": "RGB"}, None, {}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "SOT-23"}, "npn", {}),
    ("Transistors BJT", {"Polarity": "NPN", "Footprint Ref": "SOT95P237X112-3N"}, "npn", {}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "SOT-223"}, "npn", {"pinmap": "BCEC"}),
    ("Transistors BJT", {"Polarity": "PNP", "Package": "SOT-89"}, "pnp", {"pinmap": "BCE"}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-220", "Manufacturer Part Number": "TIP31C"}, "npn",
     {"pinmap": "BCE"}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "DPAK", "Manufacturer Part Number": "MJD31C"}, "npn",
     {"pinmap": "BCE"}),
    ("Transistors BJT", {"Polarity": "NPN", "Footprint Ref": "TO229P991X239-4N"}, "npn", {"pinmap": "BCEC"}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92", "Manufacturer Part Number": "2N3904"}, None, {}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92", "Manufacturer Part Number": "BC547"}, None, {}),
    ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-126"}, None, {}),
    ("Transistors BJT", {"Polarity": "PNP"}, None, {}),  # no package: pinout unknown
    ("Transistors BJT", {"Polarity": "Darlington NPN", "Package": "SOT-23"}, "npn", {}),
    ("Transistors BJT", {"Polarity": "NPN+PNP"}, None, {}),
    ("Transistors BJT", {"Polarity": "Dual NPN"}, None, {}),
    ("Transistors BJT", {}, None, {}),
    ("Transistors FET", {"Channel": "N", "Package": "SOT-23"}, "nmos", {}),
    ("Transistors FET", {"Channel": "N", "Package": "SOT95P280X145-3N"}, "nmos", {}),
    ("Transistors FET", {"Channel": "P", "Package": "SOT-23"}, "pmos", {}),
    ("Transistors FET", {"Channel": "N", "Package": "SO-8"}, "nmos", {"pinmap": "SSSGDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "PowerPAK SO-8"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "DFN-8"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "DFN-8 5x6"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "SON-8 5x6"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "VSON-8"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Footprint Ref": "SON65P300X300X100-9N"}, "nmos", {"pinmap": "SSSGDDDDD"}),
    ("Transistors FET", {"Channel": "N", "Package": "TO-252 (DPAK)"}, "nmos", {"pinmap": "GDS"}),
    ("Transistors FET", {"Channel": "N", "Footprint Ref": "TO229P991X239-4N"}, "nmos", {"pinmap": "GDSD"}),
    ("Transistors FET", {"Channel": "N", "Package": "TO-220AB"}, "nmos", {"pinmap": "GDS"}),
    ("Transistors FET", {"Channel": "P", "Package": "SOT-223"}, "pmos", {"pinmap": "GDSD"}),
    ("Transistors FET", {"Channel": "N", "Package": "TO-92", "Manufacturer Part Number": "2N7000"}, None, {}),
    ("Transistors FET", {"Channel": "N", "Package": "SOT-23-6", "Manufacturer Part Number": "Si3442"}, None, {}),
    ("Transistors FET", {"Channel": "N", "Package": "TO-247-4"}, None, {}),  # Kelvin source
    ("Transistors FET", {"Channel": "N", "Package": "LFPAK56"}, None, {}),
    ("Transistors FET", {"Channel": "N", "Package": "Source-Down PQFN 3.3x3.3"}, None, {}),
    ("Transistors FET", {"Channel": "N"}, None, {}),
    ("Transistors FET", {"Channel": "N", "FET Type": "JFET"}, None, {}),
    ("Transistors FET", {"Channel": "N", "FET Type": "GaN"}, None, {}),
    ("Transistors FET", {"Channel": "Dual N"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Quarz", "Package": "HC-49/US"}, "crystal_2", {}),
    ("Oscillators", {"Oscillator Type": "Quarz", "Package": "3225"}, "crystal_4", {}),
    ("Oscillators", {"Oscillator Type": "Quarz", "Package": "5032-2"}, "crystal_2", {}),
    ("Oscillators", {"Oscillator Type": "Quarz", "Package": "5032"}, None, {}),  # 2- and 4-pad versions exist
    ("Oscillators", {"Oscillator Type": "Quarz"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Keramikresonator", "Package": "CSTCE (3-SMD)"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Keramikresonator", "Manufacturer Part Number": "CSTCE8M00G55"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Keramikresonator", "Package": "2-SMD"}, "crystal_2", {}),
    ("Oscillators", {"Oscillator Type": "Keramikresonator"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Oszillator"}, "oscillator", {}),
    ("Oscillators", {"Oscillator Type": "Oszillator", "Package": "3225"}, "oscillator", {}),
    ("Oscillators", {"Oscillator Type": "Oszillator", "Package": "6-SMD"}, None, {}),
    ("Oscillators", {"Oscillator Type": "Oszillator", "Description": "XO LVDS 100MHz"}, None, {}),
    ("Oscillators", {"Oscillator Type": "MEMS-Oszillator"}, "oscillator", {}),
    ("Oscillators", {"Oscillator Type": "TCXO"}, "oscillator", {}),
    ("Oscillators", {}, None, {}),
    ("Fuses", {"Protection Type": "Sicherung"}, "fuse", {}),
    ("Fuses", {"Protection Type": "PTC (rückstellend)"}, "ptc", {}),
    ("Fuses", {"Protection Type": "Varistor"}, "varistor", {}),
    ("Fuses", {"Protection Type": "Gasableiter"}, None, {}),
    ("Fuses", {"Protection Type": "ESD-Schutz"}, None, {}),
    ("Fuses", {}, "fuse", {}),
    ("Amplifiers", {"Channels": 1, "Package": "SOIC-8"}, "opamp", {"pinmap": "SOIC8"}),
    ("Amplifiers", {"Channels": "1", "Package": "MSOP-8"}, "opamp", {"pinmap": "SOIC8"}),
    ("Amplifiers", {"Channels": "1"}, None, {}),  # single op-amp pinouts vary: ask
    ("Amplifiers", {"Channels": "1", "Package": "SOT-23-5"}, None, {}),
    ("Amplifiers", {"Channels": "2", "Amplifier Type": "Operationsverstärker"}, "opamp_dual", {}),
    ("Amplifiers", {"Channels": "2", "Package": "SOIC-8"}, "opamp_dual", {}),
    ("Amplifiers", {"Channels": "2", "Package": "DFN-8"}, "opamp_dual", {}),
    ("Amplifiers", {"Channels": "2", "Package": "X2QFN-10"}, None, {}),
    ("Amplifiers", {"Channels": "2", "Package": "DSBGA-8"}, None, {}),
    ("Amplifiers", {"Channels": "4.0"}, "opamp_quad", {}),
    ("Amplifiers", {"Channels": "4", "Package": "TSSOP-14"}, "opamp_quad", {}),
    ("Amplifiers", {"Channels": "4", "Package": "QFN-16"}, None, {}),
    ("Amplifiers", {"Channels": "3"}, None, {}),
    ("Amplifiers", {}, None, {}),
    ("Amplifiers", {"Channels": "2", "Amplifier Type": "Komparator"}, "comparator", {"channels": "2"}),
    ("Amplifiers", {"Channels": "4", "Amplifier Type": "Komparator", "Description": "open-collector"}, "comparator",
     {"channels": "4", "output": "open_drain"}),
    ("Amplifiers", {"Channels": "1", "Amplifier Type": "Komparator", "Package": "SOIC-8",
                    "Manufacturer Part Number": "LM311D"}, None, {}),
    ("Amplifiers", {"Channels": "1", "Amplifier Type": "Instrumentenverstärker"}, None, {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Output Type": "Transistor", "Package": "SOP-4"}, "optocoupler_4",
     {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Package": "DIP-4"}, "optocoupler_4", {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Package": "DIP-6"}, "optocoupler_6", {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Package": "SMD-6"}, "optocoupler_6", {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Output Type": "Transistor", "Package": "DIP-8",
                      "Manufacturer Part Number": "PC827"}, None, {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Output Type": "Transistor", "Package": "SOP-16",
                      "Manufacturer Part Number": "TLP291-4"}, None, {}),
    ("Optocouplers", {"Opto Type": "Optokoppler", "Output Type": "Transistor"}, None, {}),  # 4 or 6 pins?
    ("Optocouplers", {"Opto Type": "Optokoppler", "Output Type": "Triac"}, None, {}),
    ("Optocouplers", {"Opto Type": "Fotodiode"}, "photodiode", {}),
    ("Optocouplers", {"Opto Type": "Digitaler Isolator"}, None, {}),
    ("Connectors", {"Pins": "8"}, "connector", {"pins": 8, "rows": "1"}),
    ("Connectors", {"Pins": 20, "Rows": 2}, "connector", {"pins": 20, "rows": "2"}),
    ("Connectors", {"Pins": 120, "Rows": 2}, "connector", {"pins": 120, "rows": "2"}),
    ("Connectors", {"Pins": "120"}, None, {}),  # 120 in one row cannot be generated
    ("Connectors", {"Pins": "7", "Rows": "2"}, None, {}),
    ("Connectors", {"Pins": "8", "Rows": "3"}, None, {}),
    ("Connectors", {}, None, {}),
    ("Electromechanical", {"Electromech Type": "Relais", "Contact Configuration": "SPDT"}, None, {}),
    ("Electromechanical", {"Electromech Type": "Relais", "Contact Configuration": "DPDT"}, None, {}),
    ("Electromechanical", {"Electromech Type": "Summer/Lautsprecher"}, "buzzer", {}),
    ("Electromechanical", {"Electromech Type": "Batteriehalter"}, "battery", {}),
    ("Electromechanical", {"Electromech Type": "Potentiometer"}, "potentiometer", {}),
    ("Electromechanical", {"Electromech Type": "Schalter", "Contact Configuration": "SPST"}, "switch_2", {}),
    ("Electromechanical", {"Electromech Type": "Taster"}, None, {}),
    ("Electromechanical", {"Electromech Type": "Taster", "Package": "2-SMD"}, "switch_2", {}),
    ("Electromechanical", {"Electromech Type": "Taster", "Package": "4-SMD"}, None, {}),
    ("Mechanical", {"Mechanical Type": "Befestigungsloch"}, "mounting_hole", {}),
    ("Mechanical", {"Mechanical Type": "Fiducial"}, "fiducial", {}),
    ("Mechanical", {"Mechanical Type": "Testpunkt"}, "test_point", {}),
    ("Mechanical", {"Mechanical Type": "Kühlkörper"}, None, {}),
    ("Integrated Circuits", {"Function": "Mikrocontroller"}, None, {}),
    ("Power Linear", {}, None, {}),
    ("Unbekannt", {"Resistance": "1k"}, None, {}),
    ("", {}, None, {}),
]


@pytest.mark.parametrize(
    ("table", "values", "kind", "params"), CASES, ids=[f"{c[0]}-{c[2]}-{i}" for i, c in enumerate(CASES)]
)
def test_standard_symbol_for(table: str, values: dict[str, Any], kind: str | None, params: dict[str, Any]) -> None:
    req = standard_symbol_for(table, values)
    if kind is None:
        assert req is None
        return
    assert isinstance(req, SymbolRequest)
    assert req.kind == kind
    for key, value in params.items():
        assert req.params.get(key) == value, (key, req.params)
    if not params:
        assert "pinmap" not in req.params  # no package hint -> default map
    spec = generate(req, SymbolStyle())  # every suggestion must be generatable
    assert check_spec(spec) == []


def test_lookup_is_case_insensitive_and_tolerant() -> None:
    assert standard_symbol_for("resistors", {}) is not None
    req = standard_symbol_for(" Capacitors ", {"polarized": " JA ", "ignored": None})
    assert req is not None and req.kind == "capacitor_polarized"
    assert standard_symbol_for("Diodes", None) is not None
    assert standard_symbol_for("Transistors BJT", {"polarity": "npn", "package": "sot23"}) is not None


# ---------------------------------------------------------------------------------- review regressions
def pinout(req: SymbolRequest | None, style: SymbolStyle | None = None) -> dict[str, str]:
    assert req is not None
    return {p.designator: p.name for p in generate(req, style or SymbolStyle()).pins}


def test_power_transistors_get_their_datasheet_pinout() -> None:
    """Review finding: TO-220/DPAK BJTs fell back to the SOT-23 map (collector and emitter swapped)."""
    tip31 = standard_symbol_for("Transistors BJT", {"Polarity": "NPN", "Package": "TO-220"})
    assert pinout(tip31) == {"1": "B", "2": "C", "3": "E"}
    mjd31 = standard_symbol_for("Transistors BJT", {"Polarity": "NPN", "Package": "DPAK"})
    assert pinout(mjd31) == {"1": "B", "2": "C", "3": "E"}


@pytest.mark.parametrize(
    ("table", "values", "kind", "options"),
    [
        ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92"}, "npn", {"EBC", "CBE"}),
        ("Transistors BJT", {"Polarity": "PNP", "Package": "TO-126"}, "pnp", {"ECB"}),
        ("Transistors BJT", {"Polarity": "NPN"}, "npn", {"BEC", "EBC", "CBE", "BCE"}),
        ("Transistors FET", {"Channel": "N", "Package": "TO-92"}, "nmos", {"SGD", "DGS"}),
        ("Transistors FET", {"Channel": "N", "Package": "SOT-23-6"}, "nmos", {"DDGSDD"}),
        ("Transistors FET", {"Channel": "P", "Package": "TSOP-6"}, "pmos", {"DDGSDD"}),
        ("Amplifiers", {"Channels": "1", "Package": "SOT-23-5"}, "opamp", {"SOT23-5", "SOT23-5R", "SOT23-5U"}),
        ("Amplifiers", {"Channels": "1", "Amplifier Type": "Komparator", "Package": "SOIC-8"}, "comparator",
         {"SOIC8"}),
        ("Electromechanical", {"Electromech Type": "Relais"}, "relay_spdt", {"STANDARD"}),
        ("Electromechanical", {"Electromech Type": "Taster", "Package": "4-SMD"}, "pushbutton_4", {"LLRR", "LRLR"}),
        ("Diodes", {"Diode Type": "Brückengleichrichter", "Package": "MBS"}, "bridge_rectifier", {"+AA-", "AA+-"}),
    ],
)
def test_ambiguous_packages_ask_for_a_pin_map(
    table: str, values: dict[str, Any], kind: str, options: set[str]
) -> None:
    suggestion = suggest_symbol(table, values)
    assert suggestion.request is None and suggestion.name is None
    assert suggestion.kind == kind and suggestion.needs_pinmap
    assert options <= set(suggestion.pinmap_options)
    assert suggestion.messages and all(isinstance(m, str) and m for m in suggestion.messages)
    for option in suggestion.pinmap_options:  # every offered option can be generated
        params = {"pinmap": option}
        if kind == "comparator":
            params["channels"] = "1"
        assert check_spec(generate(SymbolRequest(kind=kind, params=params), SymbolStyle())) == []


def test_ambiguous_kinds_offer_alternatives() -> None:
    xtal = suggest_symbol("Oscillators", {"Oscillator Type": "Quarz"})
    assert xtal.request is None and xtal.kind is None and xtal.alternatives == ["crystal_2", "crystal_4"]
    opto = suggest_symbol("Optocouplers", {"Opto Type": "Optokoppler"})
    assert opto.alternatives == ["optocoupler_4", "optocoupler_6"] and opto.messages
    button = suggest_symbol("Electromechanical", {"Electromech Type": "Taster"})
    assert button.alternatives == ["switch_2", "pushbutton_4"]


def test_exposed_drain_pad_follows_footprint_style(tmp_path) -> None:
    """Review finding: SSSGDDDD left the exposed drain pad (pad 9 / EP) of DFN MOSFETs without a net."""
    from partforge.workspace import Workspace, WorkspaceSettings, current_or_none, set_current

    values = {"Channel": "N", "Package": "DFN-8 5x6"}
    assert pinout(standard_symbol_for("Transistors FET", values))["9"] == "D"
    previous = current_or_none()
    settings = WorkspaceSettings()
    settings.footprint.exposed_pad_designator = "EP"
    set_current(Workspace.create(tmp_path / "Lib", settings=settings))
    try:
        req = standard_symbol_for("Transistors FET", values)
        assert req is not None and req.params["pinmap"] == "SSSGDDDD+EP"
        pins = pinout(req)
        assert pins["EP"] == "D" and "9" not in pins
    finally:
        set_current(previous)


def test_sot23_schottky_from_ipc_footprint_name() -> None:
    req = standard_symbol_for("Diodes", {"Diode Type": "Schottky", "Footprint Ref": "SOT95P237X112-3N"})
    assert pinout(req) == {"1": "A", "3": "K"}


def test_footprint_ref_wins_over_package_text() -> None:
    values = {"Channel": "N", "Package": "DPAK", "Footprint Ref": "TO229P991X239-4N"}
    req = standard_symbol_for("Transistors FET", values)
    assert req is not None and req.params["pinmap"] == "GDSD"


def test_every_suggestion_is_generatable_and_valid() -> None:
    """Invariant over a value matrix: a returned request always generates a writer-valid symbol."""
    packages = ["", "SOT-23", "SOT-23-5", "SOT-23-6", "SOT-89", "SOT-223", "DPAK", "TO-220", "TO-92", "SO-8",
                "DFN-8", "DIP-4", "DIP-6", "DIP-8", "SOD-123", "3225", "HC-49", "4-SMD", "X2QFN-10", "Unbekannt"]
    tables = {
        "Diodes": [{"Diode Type": t} for t in ("Gleichrichter", "Schottky", "Z-Diode", "TVS", "Brückengleichrichter")],
        "LEDs": [{"Color": "Rot"}],
        "Transistors BJT": [{"Polarity": p} for p in ("NPN", "PNP")],
        "Transistors FET": [{"Channel": c} for c in ("N", "P")],
        "Amplifiers": [{"Channels": c, "Amplifier Type": t} for c in ("1", "2", "4") for t in ("", "Komparator")],
        "Optocouplers": [{"Opto Type": "Optokoppler"}],
        "Oscillators": [{"Oscillator Type": t} for t in ("Quarz", "Oszillator", "Keramikresonator")],
        "Resistors": [{}],
        "Capacitors": [{"Type": "Tantal"}],
    }
    count = 0
    for (table, variants), package in itertools.product(tables.items(), packages):
        for values in variants:
            suggestion = suggest_symbol(table, {**values, "Package": package})
            assert isinstance(suggestion, SymbolSuggestion)
            if suggestion.request is None:
                continue
            count += 1
            spec = generate(suggestion.request, SymbolStyle())
            assert check_spec(spec) == [], (table, values, package)
            assert spec.name == suggestion.name
            assert not suggestion.needs_pinmap
    assert count > 50


# ---------------------------------------------------------------------------------- pin tables
def table(*rows: tuple[str, str]) -> list[IcPin]:
    return [IcPin(designator=d, name=n) for d, n in rows]


@pytest.mark.parametrize(
    ("category", "values", "rows", "expected"),
    [
        ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92"},
         table(("1", "E"), ("2", "B"), ("3", "C")), {"1": "E", "2": "B", "3": "C"}),
        ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92"},
         table(("1", "Collector"), ("2", "Base"), ("3", "Emitter")), {"1": "C", "2": "B", "3": "E"}),
        ("Transistors FET", {"Channel": "N", "Package": "TO-92"},
         table(("1", "S"), ("2", "G"), ("3", "D")), {"1": "S", "2": "G", "3": "D"}),
        ("Transistors FET", {"Channel": "N", "Package": "SOT-23-6"},
         table(("1", "D"), ("2", "D"), ("3", "G"), ("4", "S"), ("5", "D"), ("6", "D")),
         {"1": "D", "2": "D", "3": "G", "4": "S", "5": "D", "6": "D"}),
        ("Transistors FET", {"Channel": "N", "Package": "DFN-8"},
         [*table(("1", "S"), ("2", "S"), ("3", "S"), ("4", "G"), ("5", "D"), ("6", "D"), ("7", "D"), ("8", "D")),
          IcPin(designator="9", name="EP", description="Exposed pad, drain")],
         {"1": "S", "2": "S", "3": "S", "4": "G", "5": "D", "6": "D", "7": "D", "8": "D", "9": "D"}),
        ("Amplifiers", {"Channels": "1", "Package": "SOT-23-5"},
         table(("1", "+IN"), ("2", "V-"), ("3", "-IN"), ("4", "OUT"), ("5", "V+")),
         {"1": "+IN", "2": "V-", "3": "-IN", "4": "OUT", "5": "V+"}),
        ("Amplifiers", {"Channels": "1", "Package": "SOIC-8"},
         table(("1", "NC"), ("2", "Inverting Input"), ("3", "Noninverting Input"), ("4", "-VS"), ("5", "NC"),
               ("6", "Output"), ("7", "+VS"), ("8", "NC")),
         {"2": "-IN", "3": "+IN", "4": "V-", "6": "OUT", "7": "V+"}),
        ("Diodes", {"Diode Type": "Schottky", "Package": "SOD-123"},
         table(("1", "Cathode"), ("2", "Anode")), {"1": "K", "2": "A"}),
        ("Optocouplers", {"Opto Type": "Optokoppler", "Package": "DIP-6"},
         table(("1", "A"), ("2", "K"), ("3", "NC"), ("4", "E"), ("5", "C"), ("6", "NC")),
         {"1": "A", "2": "K", "4": "E", "5": "C"}),
        ("Electromechanical", {"Electromech Type": "Relais"},
         table(("1", "Coil"), ("16", "Coil"), ("4", "COM"), ("6", "NC"), ("8", "NO")),
         {"1": "A1", "16": "A2", "4": "COM", "6": "NC", "8": "NO"}),
        ("Oscillators", {"Oscillator Type": "Quarz", "Package": "3225"},
         table(("1", "XTAL"), ("2", "GND"), ("3", "XTAL"), ("4", "GND")),
         {"1": "XTAL1", "2": "GND", "3": "XTAL2", "4": "GND"}),
        ("Oscillators", {"Oscillator Type": "Quarz", "Package": "3225"},
         table(("1", "GND"), ("2", "X1"), ("3", "GND"), ("4", "X2")),
         {"1": "GND", "2": "XTAL1", "3": "GND", "4": "XTAL2"}),
    ],
)
def test_pin_map_from_pin_table(
    category: str, values: dict[str, Any], rows: list[IcPin], expected: dict[str, str]
) -> None:
    suggestion = suggest_symbol(category, values, pins=rows)
    assert suggestion.request is not None, suggestion.messages
    assert suggestion.source == "pins" and not suggestion.needs_pinmap
    assert pinout(suggestion.request) == expected
    assert any("Pinliste" in m for m in suggestion.messages)


def test_pin_table_accepts_plain_dicts_and_channel_names() -> None:
    lm358 = [
        {"designator": "1", "name": "OUT1"},
        {"designator": "2", "name": "IN1-"},
        {"designator": "3", "name": "IN1+"},
        {"designator": "4", "name": "GND"},
        {"designator": "5", "name": "IN2+"},
        {"designator": "6", "name": "IN2-"},
        {"designator": "7", "name": "OUT2"},
        {"designator": "8", "name": "VCC"},
    ]
    suggestion = suggest_symbol("Amplifiers", {"Channels": "2"}, pins=lm358)
    assert suggestion.request is not None and suggestion.request.kind == "opamp_dual"
    assert suggestion.source == "pins"


@pytest.mark.parametrize(
    ("category", "values", "rows", "needs_pinmap"),
    [
        # supplies swapped against the standard dual pinout
        ("Amplifiers", {"Channels": "2"},
         table(("1", "OUTA"), ("2", "-INA"), ("3", "+INA"), ("4", "V+"), ("5", "+INB"), ("6", "-INB"),
               ("7", "OUTB"), ("8", "V-")), False),
        # extra shutdown pin: the 5-pin op-amp symbol does not fit
        ("Amplifiers", {"Channels": "1", "Package": "SOT-23-5"},
         table(("1", "OUT"), ("2", "V-"), ("3", "+IN"), ("4", "-IN"), ("5", "V+"), ("6", "SHDN")), True),
        ("Oscillators", {"Oscillator Type": "Oszillator"},
         table(("1", "VDD"), ("2", "GND"), ("3", "OUT"), ("4", "OE")), False),
        ("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92"}, table(("1", "E"), ("2", "B")), True),
        ("Resistors", {}, table(("A", "1"), ("B", "2")), False),
    ],
)
def test_pin_table_contradiction_blocks_the_request(
    category: str, values: dict[str, Any], rows: list[IcPin], needs_pinmap: bool
) -> None:
    suggestion = suggest_symbol(category, values, pins=rows)
    assert suggestion.request is None
    assert suggestion.kind is not None and suggestion.needs_pinmap is needs_pinmap
    assert any("Pinliste" in m for m in suggestion.messages)


# ---------------------------------------------------------------------------------- footprints
def footprint(name: str, pads: list[str], *, family: str = "", thermal: tuple[str, ...] = (),
              params: dict[str, Any] | None = None) -> FootprintSpec:
    return FootprintSpec(
        name=name,
        family=family,
        pads=[Pad(designator=d, x=i, y=0, width=0.5, height=0.5, thermal=d in thermal) for i, d in enumerate(pads)],
        generator={"family": family, "params": params or {}} if family else None,
    )


def test_footprint_thermal_pad_joins_the_drain() -> None:
    son = footprint("SON65P300X300X100-9N", [str(i) for i in range(1, 10)], family="nolead", thermal=("9",))
    suggestion = suggest_symbol("Transistors FET", {"Channel": "N", "Package": "SON-8"}, footprint=son)
    assert suggestion.request is not None and suggestion.source == "footprint"
    assert suggestion.request.params["pinmap"] == "SSSGDDDDD"
    spec = generate(suggestion.request, SymbolStyle())
    assert check_symbol_footprint(spec, son) == []
    ep_named = footprint("SON-EP", [*(str(i) for i in range(1, 9)), "EP"], family="nolead", thermal=("EP",))
    suggestion = suggest_symbol("Transistors FET", {"Channel": "N"}, footprint=ep_named)
    assert suggestion.request is not None and suggestion.request.params["pinmap"] == "SSSGDDDD+EP"


def test_footprint_tab_pad_joins_the_collector() -> None:
    dpak3 = footprint("TO229P991X239-4N", ["1", "2", "3", "4"], family="dpak", thermal=("4",))
    suggestion = suggest_symbol("Transistors BJT", {"Polarity": "NPN"}, footprint=dpak3)
    assert suggestion.request is not None
    assert pinout(suggestion.request) == {"1": "B", "2": "C", "3": "E", "4": "C"}
    dpak2 = footprint("TO229P991X239-3N", ["1", "3", "2"], family="dpak", thermal=("2",))
    suggestion = suggest_symbol("Transistors FET", {"Channel": "N"}, footprint=dpak2)
    assert suggestion.request is not None and pinout(suggestion.request) == {"1": "G", "2": "D", "3": "S"}


def test_pad_list_only_assumes_a_single_extra_pad_is_the_tab() -> None:
    suggestion = suggest_symbol("Transistors FET", {"Channel": "N", "Package": "DPAK"}, footprint=["1", "2", "3", "4"])
    assert suggestion.request is not None and suggestion.request.params["pinmap"] == "GDSD"
    many = suggest_symbol("Transistors FET", {"Channel": "N", "Package": "DPAK"}, footprint=["1", "2", "3", "4", "5"])
    assert many.request is None and many.needs_pinmap  # 5 pads: not a 3-terminal DPAK
    so8 = suggest_symbol("Transistors FET", {"Channel": "N", "Package": "SO-8"}, footprint=[*"12345678", "9"])
    assert so8.request is not None and so8.request.params["pinmap"] == "SSSGDDDDD"  # single extra pad = tab
    assert any("als D angeschlossen" in m for m in so8.messages)


def test_footprint_without_matching_pads_blocks_the_request() -> None:
    four_pad = footprint("XTAL3225", ["1", "2", "3", "4"])
    suggestion = suggest_symbol("Oscillators", {"Oscillator Type": "Quarz", "Package": "HC-49/US"},
                                footprint=four_pad)
    # the footprint wins over the package text: 4 pads -> 4-pin crystal
    assert suggestion.request is not None and suggestion.request.kind == "crystal_4"
    two_pin_symbol_on_four_pads = suggest_symbol("Capacitors", {}, footprint=four_pad)
    assert two_pin_symbol_on_four_pads.request is None
    named = footprint("ODD", ["A", "K"])
    diode = suggest_symbol("Diodes", {"Diode Type": "Schottky"}, footprint=named)
    assert diode.request is None and diode.needs_pinmap and any("Pad" in m for m in diode.messages)


def test_diode_polarity_follows_the_footprint_cathode_pad() -> None:
    sod_k2 = footprint("SOD3716X135N", ["1", "2"], family="sod", params={"cathode_pad": "2"})
    sod_k1 = footprint("SOD3716X135N", ["1", "2"], family="sod", params={"cathode_pad": "1"})
    for style in (SymbolStyle(diode_pin1="cathode"), SymbolStyle(diode_pin1="anode")):
        k2 = suggest_symbol("Diodes", {"Diode Type": "Schottky"}, footprint=sod_k2, style=style)
        k1 = suggest_symbol("Diodes", {"Diode Type": "Schottky"}, footprint=sod_k1, style=style)
        assert pinout(k2.request, style) == {"1": "A", "2": "K"} and k2.name == "Schottky Diode (AK)"
        assert pinout(k1.request, style) == {"1": "K", "2": "A"} and k1.name == "Schottky Diode"
    conflict = suggest_symbol("Diodes", {"Diode Type": "Gleichrichter"}, footprint=sod_k1,
                              pins=table(("1", "A"), ("2", "K")))
    assert pinout(conflict.request) == {"1": "K", "2": "A"}  # the footprint numbering wins
    assert any("Footprint" in m for m in conflict.messages)


def test_sot23_diode_footprint_keeps_pad_2_free() -> None:
    sot = footprint("SOT95P237X112-3N", ["1", "2", "3"], family="sot23")
    suggestion = suggest_symbol("Diodes", {"Diode Type": "Z-Diode"}, footprint=sot)
    assert suggestion.request is not None and pinout(suggestion.request) == {"1": "A", "3": "K"}


def test_opamp_footprint_with_unused_pads() -> None:
    soic = footprint("SOIC127P600X175-8N", [str(i) for i in range(1, 9)], family="gullwing",
                     params={"variant": "SOIC"})
    suggestion = suggest_symbol("Amplifiers", {"Channels": "1"}, footprint=soic)
    assert suggestion.request is not None and suggestion.request.params["pinmap"] == "SOIC8"
    assert any("nicht verbunden" in m for m in suggestion.messages)
    dfn = footprint("DFN200X200X60-9N", [str(i) for i in range(1, 10)], family="nolead", thermal=("9",))
    dual = suggest_symbol("Amplifiers", {"Channels": "2"}, footprint=dfn)
    assert dual.request is not None and any("Thermal-Pad" in m for m in dual.messages)


def test_with_generated_footprints() -> None:
    """Integration with the footprint generator: suggested symbols cover every pad."""
    from partforge.footprints import generate as generate_footprint
    from partforge.footprints.models import FootprintRequest

    cases = [
        ("Transistors FET", {"Channel": "N"}, FootprintRequest(family="nolead", params={"variant": "SON", "pins": 8})),
        ("Transistors BJT", {"Polarity": "NPN"}, FootprintRequest(family="dpak", params={"leads": "3"})),
        ("Transistors BJT", {"Polarity": "PNP"}, FootprintRequest(family="sot223", params={})),
        ("Transistors FET", {"Channel": "P"}, FootprintRequest(family="sot23", params={"pins": "3"})),
    ]
    for category, values, request in cases:
        fp = generate_footprint(request)
        suggestion = suggest_symbol(category, values, footprint=fp)
        assert suggestion.request is not None, (category, fp.name, suggestion.messages)
        assert check_symbol_footprint(generate(suggestion.request, SymbolStyle()), fp) == []
