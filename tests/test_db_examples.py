"""Example content of a new library (partforge.db.examples)."""
from __future__ import annotations

from pathlib import Path

import pytest

from partforge import db
from partforge.db import categories, examples, health, parts, registry
from partforge.db.models import SymbolRecord
from partforge.workspace import FootprintStyle, Workspace, WorkspaceSettings, set_current

EXPECTED_SYMBOLS = {
    "Resistor", "Capacitor", "Inductor", "Ferrite Bead", "Schottky Diode", "Zener Diode", "LED", "NPN", "NMOS",
    "Op-Amp Dual", "Op-Amp", "AP2112K", "Crystal", "Fuse", "Connector 1x04",
}
EXPECTED_FOOTPRINTS = {
    "RESC1608X50N", "CAPC1608X87N", "CAPC2012X145N", "INDM125125X650N_6E43", "INDC1608X95N", "SOD3716X135N",
    "LEDC1608X80N", "SOT95P237X112-3N", "SOIC127P600X175-8N", "SOT95P280X145-5N", "XTAL3215X90N", "FUSC3216X60N",
    "HDRV4W64P254_1X4_1016X254X854B",
}


def test_example_definitions_are_consistent() -> None:
    pns = [p.part_number for p in examples.EXAMPLE_PARTS]
    assert len(pns) == len(set(pns)) == 19
    tables = {p.table for p in examples.EXAMPLE_PARTS}
    assert {"Resistors", "Capacitors", "Inductors", "Ferrite Beads", "Diodes", "LEDs", "Transistors BJT",
            "Transistors FET", "Amplifiers", "Power Linear", "Oscillators", "Fuses", "Connectors"} == tables
    for part in examples.EXAMPLE_PARTS:
        assert part.values["Manufacturer Part Number"] == part.part_number
        assert "Library Ref" not in part.values and "Footprint Ref" not in part.values  # come from the generators
        assert part.symbol.request().kind == part.symbol.kind
    kinds = {p.symbol.kind for p in examples.EXAMPLE_PARTS}
    assert {"schottky", "zener", "opamp_dual", "ic", "crystal_2", "fuse", "connector"} <= kinds


def test_seed_examples(workspace: Workspace) -> None:
    counts = db.seed_examples(workspace)
    assert counts == {"parts": 19, "symbols": len(EXPECTED_SYMBOLS), "footprints": len(EXPECTED_FOOTPRINTS)}
    assert parts.stats()["total_parts"] == 19
    assert {s.name for s in registry.list_symbols()} == EXPECTED_SYMBOLS
    assert {f.name for f in registry.list_footprints()} == EXPECTED_FOOTPRINTS

    r = parts.get_part("Resistors", "RC0603FR-0710KL")
    assert r and r["Resistance"] == "10kΩ" and r["Comment"] == "10k" and r["Value"] == "10kΩ"
    assert r["Library Ref"] == "Resistor" and r["Library Path"] == r"Symbols\PF_Passives.SchLib"
    assert r["Footprint Ref"] == "RESC1608X50N" and r["Footprint Path"] == r"Footprints\PF_CHIP.PcbLib"
    assert r["Notes"] == examples.EXAMPLE_NOTE and r["PF Status"] == examples.EXAMPLE_STATUS
    assert r["Operating Temperature"] == "-55°C … 155°C" and r["Height"] == "0.55mm"
    assert r["TCR"] == "±100ppm/K" and r["Tolerance"] == "±1%" and r["Power"] == "0.1W"
    assert r["PF Author"] == examples.EXAMPLE_AUTHOR
    assert parts.get_part("Resistors", "RC0603FR-07100RL")["Comment"] == "100R"  # type: ignore[index]
    mlcc = parts.get_part("Capacitors", "GRM188R71H104KA93D")
    assert mlcc and mlcc["Comment"] == "100n 50V" and mlcc["Value"] == "100nF"  # the Comment carries the voltage
    big = parts.get_part("Capacitors", "GRM21BR61E106KA73L")
    assert big and big["Comment"] == "10u 25V" and big["Footprint Ref"] == "CAPC2012X145N" and big["Height"] == "1.35mm"
    bead = parts.get_part("Ferrite Beads", "BLM18PG221SN1D")
    assert bead and bead["Comment"] == "220R@100MHz" and bead["Description"] == "FERRITE 0603 220Ω@100MHz 1.4A"
    inductor = parts.get_part("Inductors", "SRR1260-100M")
    assert inductor and inductor["DCR"] == "20mΩ" and inductor["Comment"] == "10u" and inductor["Value"] == "10µH"
    led = parts.get_part("LEDs", "150060RS75000")
    assert led and led["Comment"] == "Rot"
    assert inductor["Footprint Path"] == r"Footprints\PF_MOLDED.PcbLib" and inductor["Height"] == "6.5mm"
    opamp = parts.get_part("Amplifiers", "LM358DR")
    assert opamp and opamp["Library Ref"] == "Op-Amp Dual" and opamp["Footprint Ref"] == "SOIC127P600X175-8N"
    assert opamp["Library Path"] == r"Symbols\PF_Analog.SchLib"
    assert opamp["Description"] == "IC OPAMP 2CH 700kHz 0.3V/µs SOIC-8" and opamp["Comment"] == "LM358DR"
    assert opamp["Supply Voltage"] == "3V … 32V"
    single = parts.get_part("Amplifiers", "TLV9001IDBVR")
    assert single and single["Library Ref"] == "Op-Amp" and single["Footprint Ref"] == "SOT95P280X145-5N"
    ldo = parts.get_part("Power Linear", "AP2112K-3.3TRG1")
    assert ldo and ldo["Library Ref"] == "AP2112K" and ldo["Library Path"] == r"Symbols\PF_Power.SchLib"
    assert ldo["Input Voltage"] == "2.5V … 6V" and ldo["Accuracy"] == "±1.5%" and ldo["Height"] == "1.45mm"
    crystal = parts.get_part("Oscillators", "ABS07-32.768KHZ-T")
    assert crystal and crystal["Frequency Tolerance"] == "±20ppm" and crystal["Load Capacitance"] == "12.5pF"
    assert crystal["Comment"] == "32.768kHz" and crystal["Footprint Ref"] == "XTAL3215X90N"
    fuse = parts.get_part("Fuses", "0466001.NR")
    assert fuse and fuse["Comment"] == "1A" and fuse["Description"] == "FUSE Sicherung 1A 63V superflink 1206"
    header = parts.get_part("Connectors", "61300411121")
    assert header and header["Library Ref"] == "Connector 1x04" and header["Pitch"] == "2.54mm"
    assert header["Footprint Path"] == r"Footprints\PF_PIN_HEADER.PcbLib" and header["Height"] == "8.54mm"
    assert parts.get_part("Transistors FET", "2N7002,215")["RDS(on)"] == "5Ω"  # type: ignore[index]

    assert all(s.status == "pending" and s.spec is not None for s in registry.list_symbols())
    assert all(f.status == "pending" and f.spec is not None for f in registry.list_footprints())
    soic = registry.get_footprint("SOIC127P600X175-8N")
    assert soic and soic.family == "gullwing" and soic.pad_count == 8 and soic.usage == 1
    assert soic.library == r"Footprints\PF_GULLWING.PcbLib" and soic.status_message == examples.PENDING_MESSAGE
    res = registry.get_symbol("Resistor")
    assert res and res.usage == 4 and res.kind == "resistor" and res.pin_count == 2
    dual = registry.get_symbol("Op-Amp Dual")
    assert dual and dual.part_count == 3 and dual.pin_count == 8
    assert registry.get_footprint("SOT95P237X112-3N").usage == 2  # type: ignore[union-attr]

    report = health.health_report()
    assert report["counts"]["error"] == 0 and report["counts"]["warning"] == 0, report["issues"][:5]
    # seeding twice adds nothing
    assert db.seed_examples(workspace) == {"parts": 0, "symbols": 0, "footprints": 0}


def test_build_examples_is_pure_and_follows_the_style(tmp_path: Path) -> None:
    settings = WorkspaceSettings()
    settings.symbol.diode_pin1 = "anode"
    settings.footprint.density = "L"
    ws = Workspace.create(tmp_path / "Anode", settings=settings)
    content = examples.build_examples(ws)  # no database needed
    assert not content.skipped and len(content.parts) == 19
    assert {"Schottky Diode (AK)", "Zener Diode (AK)", "LED (AK)"} <= set(content.symbols)
    assert "Diode" not in content.symbols and "LED" not in content.symbols
    assert {"SOD3716X135RL", "LEDC1608X80RL", "XTAL3215X90L", "FUSC3216X60L"} <= set(content.footprints)
    lib_refs = {values["Library Ref"] for _, values in content.parts}
    fp_refs = {values["Footprint Ref"] for _, values in content.parts}
    assert lib_refs == set(content.symbols) and fp_refs == set(content.footprints)
    only_leds = examples.build_examples(ws, tables=["LEDs"])
    assert [v["Part Number"] for _, v in only_leds.parts] == ["150060RS75000"]
    assert set(only_leds.symbols) == {"LED (AK)"} and set(only_leds.footprints) == {"LEDC1608X80RL"}


def test_per_item_layout_uses_one_file_per_component(tmp_path: Path) -> None:
    settings = WorkspaceSettings(library_layout="per_item")
    ws = Workspace.create(tmp_path / "PerItem", settings=settings)
    content = examples.build_examples(ws)
    assert content.symbols["Op-Amp Dual"].library == r"Symbols\Op-Amp Dual.SchLib"
    assert content.footprints["SOIC127P600X175-8N"].library == r"Footprints\SOIC127P600X175-8N.PcbLib"


def test_generation_errors_skip_only_the_affected_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = Workspace.create(tmp_path / "Kaputt")
    original = examples.FootprintDef.request

    def broken(self: examples.FootprintDef, style: FootprintStyle):  # type: ignore[no-untyped-def]
        if self.family == "molded":
            raise ValueError("Testfehler")
        return original(self, style)

    monkeypatch.setattr(examples.FootprintDef, "request", broken)
    content = examples.build_examples(ws)
    assert content.skipped == {"SRR1260-100M": "Footprint: Testfehler"}
    assert len(content.parts) == 18 and "Inductor" not in content.symbols


def test_existing_entries_are_kept(workspace: Workspace) -> None:
    registry.upsert_symbol(SymbolRecord(name="Resistor", library=r"Symbols\Eigene.SchLib", status="ok"))
    counts = db.seed_examples(workspace)
    assert counts["symbols"] == len(EXPECTED_SYMBOLS) - 1 and counts["parts"] == 19
    kept = registry.get_symbol("Resistor")
    assert kept and kept.library == r"Symbols\Eigene.SchLib" and kept.status == "ok" and kept.spec is None
    r = parts.get_part("Resistors", "RC0603FR-071KL")
    assert r and r["Library Path"] == r"Symbols\Eigene.SchLib"  # the registered library wins


def test_seed_examples_opens_database_and_skips_missing_categories(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Neu")
    db.open_database(ws)
    categories.delete_category("LEDs", backup=False)
    db.close_database()
    try:
        counts = db.seed_examples(ws)  # opens the database itself
        set_current(ws)
        assert counts == {"parts": 18, "symbols": len(EXPECTED_SYMBOLS) - 1, "footprints": len(EXPECTED_FOOTPRINTS) - 1}
        assert db.is_open() and registry.get_symbol("LED") is None and registry.get_footprint("LEDC1608X80N") is None
    finally:
        db.close_database()
        set_current(None)


def test_seed_examples_migrates_legacy_default_symbols(workspace: Workspace) -> None:
    from sqlalchemy import update

    from partforge.db import core
    from partforge.db.schema import pf_categories

    with core.connect() as conn:
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Amplifiers").values(default_symbol="Op-Amp"))
    categories.invalidate_cache()
    assert categories.get_category("Amplifiers").default_symbol == "Op-Amp"
    db.seed_examples(workspace)
    assert categories.get_category("Amplifiers").default_symbol == "opamp_dual"


def test_crystal_and_fuse_names_follow_the_naming_scheme(tmp_path: Path) -> None:
    """The two packages without own generator family get explicit names – IPC style (also their
    ``ipc_name``, not the chip land's "CAPC…"/"RESC…") or house style like the other footprints."""
    ipc = examples.build_examples(Workspace.create(tmp_path / "IPC"))
    for name in ("XTAL3215X90N", "FUSC3216X60N"):
        rec = ipc.footprints[name]
        assert rec.spec is not None and rec.spec.ipc_name == rec.ipc_name == name
    settings = WorkspaceSettings()
    settings.footprint.naming = "house"
    settings.footprint.density = "L"
    house = examples.build_examples(Workspace.create(tmp_path / "Haus", settings=settings))
    assert not house.skipped
    crystal, fuse = house.footprints["XTAL 1.5x3.2MM RF"], house.footprints["FUSE 1206_3216 RF"]
    assert crystal.spec is not None and crystal.spec.ipc_name == "XTAL3215X90L"
    assert fuse.spec is not None and fuse.spec.ipc_name == "FUSC3216X60L"
    assert {"RES 0603_1608 RF", "SOT-23-3 RF"} <= set(house.footprints)
    assert not any(name.startswith(("XTAL3215", "FUSC3216")) for name in house.footprints)
    refs = {values["Footprint Ref"] for _, values in house.parts}
    assert refs == set(house.footprints)


def test_internal_part_numbers(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Intern", settings=WorkspaceSettings(part_number_scheme="internal"))
    db.open_database(ws)
    set_current(ws)
    try:
        assert db.seed_examples(ws) == {"parts": 19, "symbols": 15, "footprints": 13}
        rows, total = parts.query_parts("Resistors", sort="Part Number", limit=None)
        assert total == 4 and [r["Part Number"] for r in rows] == ["R-000001", "R-000002", "R-000003", "R-000004"]
        assert {r["Manufacturer Part Number"] for r in rows} == {
            "RC0603FR-0710KL", "RC0603FR-074K7L", "RC0603FR-071KL", "RC0603FR-07100RL"}
        assert parts.find_part("RC0603FR-0710KL") is None  # the MPN is no part number here
        opamp, _ = parts.query_parts("Amplifiers", search="LM358DR", limit=None)
        assert len(opamp) == 1 and opamp[0]["Part Number"] == "U-000001" and opamp[0]["Library Ref"] == "Op-Amp Dual"
        # seeding again recognises the examples by their MPN
        assert db.seed_examples(ws) == {"parts": 0, "symbols": 0, "footprints": 0}
        assert parts.stats()["total_parts"] == 19
        manual = parts.create_part("Resistors", {
            "Manufacturer": "YAGEO", "Manufacturer Part Number": "RC0603FR-0722KL", "Resistance": "22k",
            "Tolerance": "1%", "Power": "0.1W", "Library Ref": "Resistor", "Footprint Ref": "RESC1608X50N"})
        assert manual["Part Number"] == "R-000005"
    finally:
        db.close_database()
        set_current(None)


def test_seed_examples_does_not_lock_the_database_without_migration(workspace: Workspace,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The default-symbol check is a read; a write transaction is only opened for an old library."""
    from partforge.db import core
    from partforge.db.templates import ensure_default_symbol_kinds

    def no_write() -> None:
        raise AssertionError("keine Schreibtransaktion erwartet")

    monkeypatch.setattr(core, "connect", no_write)
    assert ensure_default_symbol_kinds() == []
