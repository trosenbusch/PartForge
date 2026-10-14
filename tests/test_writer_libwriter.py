"""Library layout, backend selection and status (libwriter.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_writer_samples import chip_0603, resistor_symbol

from partforge.altium import libwriter
from partforge.altium.bridge import AltiumLibraryWriter
from partforge.altium.libwriter import (
    LibraryWriter,
    RustLibraryWriter,
    WriterUnavailable,
    backend_status,
    footprint_family,
    footprint_library_path,
    get_writer,
    safe_file_stem,
    symbol_group,
    symbol_library_path,
)
from partforge.config import AltiumSettings, AppSettings
from partforge.workspace import Workspace


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "Bibliothek", name="Layout")


@pytest.mark.parametrize(
    ("category", "group"),
    [
        ("Resistors", "Passives"),
        ("Capacitors", "Passives"),
        ("Inductors", "Passives"),
        ("Ferrite Beads", "Passives"),
        ("Diodes", "Diodes"),
        ("LEDs", "Diodes"),
        ("Transistors BJT", "Transistors"),
        ("Transistors FET", "Transistors"),
        ("Amplifiers", "Analog"),
        ("Power Linear", "Power"),
        ("Power Switchmode", "Power"),
        ("Data Converters", "ICs"),
        ("Integrated Circuits", "ICs"),
        ("Optocouplers", "ICs"),
        ("Connectors", "Connectors"),
        ("Electromechanical", "Electromechanical"),
        ("Fuses", "Protection"),
        ("Oscillators", "Oscillators"),
        ("Mechanical", "Mechanical"),
        ("Sensoren & Aktoren", "Sensoren_Aktoren"),
        ("Ü", "Misc"),
    ],
)
def test_symbol_groups_by_category(category, group):
    assert symbol_group(category) == group


@pytest.mark.parametrize(("prefix", "group"), [("R", "Passives"), ("FB", "Passives"), ("Q", "Transistors"), ("U", "ICs"), ("SW", "Electromechanical"), ("MH", "Mechanical"), ("J", "Connectors"), ("XYZ", "Misc"), ("", "Misc")])
def test_symbol_groups_by_prefix(prefix, group):
    spec = resistor_symbol()
    spec.designator_prefix = prefix
    assert symbol_group(None, spec) == group


def test_symbol_library_paths(ws):
    spec = resistor_symbol()
    assert symbol_library_path(ws, spec, "Resistors") == ws.symbols_dir / "PF_Passives.SchLib"
    assert symbol_library_path(ws, spec) == ws.symbols_dir / "PF_Passives.SchLib"
    ws.settings.library_layout = "per_item"
    assert symbol_library_path(ws, spec, "Resistors") == ws.symbols_dir / "PF_RES.SchLib"


def test_footprint_library_paths(ws):
    spec = chip_0603()
    assert footprint_library_path(ws, spec) == ws.footprints_dir / "PF_CHIP.PcbLib"
    spec.family = "sot23-5"
    assert footprint_family(spec) == "SOT23_5"
    spec.family = ""
    assert footprint_library_path(ws, spec) == ws.footprints_dir / "PF_MISC.PcbLib"
    ws.settings.library_layout = "per_item"
    assert footprint_library_path(ws, spec) == ws.footprints_dir / "RESC1608X55N.PcbLib"
    ws.settings.folders.footprints = "FP"
    assert footprint_library_path(ws, spec).parent == ws.root / "FP"


@pytest.mark.parametrize(("name", "stem"), [("R 0603 (1608)", "R 0603 (1608)"), ("CON", "PF_CON"), ("com1.x", "PF_com1.x"), ("ABC. ", "ABC"), ("...", "Bauteil")])
def test_safe_file_stem(name, stem):
    assert safe_file_stem(name) == stem


# --------------------------------------------------------------------------- selection


@pytest.fixture
def fake_exe(tmp_path: Path) -> str:
    exe = tmp_path / "bin" / "altium-designer-mcp.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    return str(exe)


@pytest.fixture
def no_detection(monkeypatch):
    monkeypatch.setattr("partforge.config.detect_rust_writer", lambda: None)
    monkeypatch.setattr("partforge.config.detect_altium_exe", lambda: None)
    monkeypatch.setattr(libwriter, "rust_writer_version", lambda exe: "0.1.0")


def _settings(backend: str, *, rust: str | None = None, x2: str | None = None) -> AppSettings:
    return AppSettings(altium=AltiumSettings(library_backend=backend, rust_writer_path=rust, x2_path=x2))  # type: ignore[arg-type]


def _altium_running(monkeypatch, running: bool) -> None:
    monkeypatch.setattr("partforge.altium.bridge.core.is_process_running", lambda image="X2.EXE": running)
    monkeypatch.setattr("partforge.altium.bridge.process.is_process_running", lambda image="X2.EXE": running)


@pytest.mark.windows
def test_get_writer_rust_modes(no_detection, fake_exe):
    writer = get_writer(_settings("rust", rust=fake_exe))
    assert isinstance(writer, RustLibraryWriter) and writer.name == "rust"
    assert isinstance(writer, LibraryWriter)
    assert get_writer(_settings("auto", rust=fake_exe)).name == "rust"
    with pytest.raises(WriterUnavailable, match="Bibliotheks-Writer"):
        get_writer(_settings("rust"))


@pytest.mark.windows
def test_get_writer_altium_modes(no_detection, monkeypatch, fake_exe, tmp_path):
    x2 = tmp_path / "AD" / "X2.EXE"
    x2.parent.mkdir()
    x2.write_bytes(b"MZ")
    _altium_running(monkeypatch, False)
    with pytest.raises(WriterUnavailable, match="nicht gestartet"):
        get_writer(_settings("altium", x2=str(x2)))
    with pytest.raises(WriterUnavailable) as exc:
        get_writer(_settings("auto", x2=str(x2)))
    assert "Bibliotheks-Writer" in str(exc.value) and "Altium" in str(exc.value)
    _altium_running(monkeypatch, True)
    writer = get_writer(_settings("altium", rust=fake_exe, x2=str(x2)))
    assert isinstance(writer, AltiumLibraryWriter) and writer.reader is not None
    assert isinstance(writer, LibraryWriter)
    auto = get_writer(_settings("auto", x2=str(x2)))
    assert isinstance(auto, AltiumLibraryWriter) and auto.reader is None
    with pytest.raises(WriterUnavailable, match="nicht gefunden"):
        get_writer(_settings("altium"))


@pytest.mark.windows
def test_backend_status(no_detection, monkeypatch, fake_exe, tmp_path):
    _altium_running(monkeypatch, False)
    statuses = backend_status(_settings("auto", rust=fake_exe))
    assert [s.name for s in statuses] == ["rust", "altium"]
    rust, altium = statuses
    assert rust.available and rust.version == "0.1.0" and rust.path == fake_exe
    assert not altium.available and "nicht gefunden" in altium.message
    x2 = tmp_path / "X2.EXE"
    x2.write_bytes(b"MZ")
    statuses = backend_status(_settings("auto", x2=str(x2)))
    assert not statuses[0].available and "nicht gefunden" in statuses[0].message
    assert statuses[1].message == "Altium Designer ist nicht gestartet." and statuses[1].path == str(x2)
    _altium_running(monkeypatch, True)
    assert backend_status(_settings("auto", x2=str(x2)))[1].available


def test_rust_writer_available(no_detection, fake_exe, tmp_path):
    ok, message = RustLibraryWriter(fake_exe).available()
    assert ok and "0.1.0" in message
    ok, message = RustLibraryWriter(tmp_path / "missing.exe").available()
    assert not ok and "nicht gefunden" in message


@pytest.mark.rustwriter
def test_backend_status_with_real_executable():
    from partforge.config import detect_rust_writer

    exe = detect_rust_writer()
    status = backend_status(_settings("auto", rust=exe))[0]
    assert status.available and status.version and status.version[0].isdigit()


@pytest.mark.windows
def test_no_writer_message_puts_the_remedy_first(no_detection, monkeypatch, tmp_path):
    """Review finding F2 (UX): the remedy must survive a 200-character clip, name the real settings place
    and never end in ``(… gestartet.).``."""
    x2 = tmp_path / "X2.EXE"
    x2.write_bytes(b"MZ")
    _altium_running(monkeypatch, False)
    with pytest.raises(WriterUnavailable) as exc:
        get_writer(_settings("auto", x2=str(x2)))
    message = str(exc.value)
    remedy = "Einstellungen › Allgemein › Altium Designer"
    assert remedy in message[:200] and "Altium Designer starten" in message[:200]
    assert ".)." not in message and ".)" not in message and "»" not in message
    assert "Altium Designer ist nicht gestartet" in message


def test_backend_status_names_a_missing_configured_writer(no_detection, tmp_path):
    missing = tmp_path / "Programme" / "altium-designer-mcp.exe"
    rust = backend_status(_settings("auto", rust=str(missing)))[0]
    assert not rust.available and str(missing) in rust.message and "Einstellungen › Allgemein › Altium Designer" in rust.message
    rust = backend_status(_settings("auto"))[0]
    assert not rust.available and "Bibliotheks-Writer nicht gefunden" in rust.message
