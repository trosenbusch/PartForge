"""AltiumLibraryWriter (bridge backend) with a fake bridge and a stub reader."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from test_writer_samples import chip_0603, chip_with_step, ic8_symbol, qfn16, resistor_symbol, soic8, write_step

from partforge.altium.bridge import (
    AltiumDataLossError,
    AltiumLibraryWriter,
    AltiumWriterError,
    BridgeCommandError,
    BridgeSpecError,
)
from partforge.altium.bridge.core import BridgeWriteResult
from partforge.altium.bridge.spec import render_pcblib_spec, render_schlib_spec
from partforge.altium.libwriter import LibraryWriter
from partforge.altium.models import BackendStatus, ComponentInfo, WriteResult
from partforge.altium.rustwriter import LOCK_FILE_NAME
from partforge.workspace import Workspace


class FakeBridge:
    def __init__(self, existing: list[str] | None = None, *, fail: bool = False):
        self.existing = existing or []
        self.fail = fail
        self.writes: list[tuple[str, list[str]]] = []

    def status(self) -> BackendStatus:
        return BackendStatus(name="altium", available=True, message="Altium Designer 26.10.1.5 läuft.")

    def _write(self, target: Path, specs, render) -> BridgeWriteResult:
        render(specs)  # validates like the real bridge
        if self.fail:
            raise BridgeCommandError("write_x", "save failed")
        names = [s.name for s in specs]
        self.writes.append((target.suffix, names))
        target.write_text("NEW:" + ",".join(names), encoding="utf-8")
        return BridgeWriteResult(path=str(target), written=names, warnings=["Hinweis"], created=len(names))

    def write_schlib(self, target, symbols, *, style=None, keep_open=False):
        return self._write(Path(target), symbols, render_schlib_spec)

    def write_pcblib(self, target, footprints, *, layer_map=None, style=None, keep_open=False):
        return self._write(Path(target), footprints, render_pcblib_spec)

    def list_components(self, path):
        return list(self.existing)


class StubReader:
    def __init__(self, specs):
        self.specs = list(specs)

    def read_all(self, library):
        return list(self.specs)

    def list_components(self, library):
        return [s.name for s in self.specs]

    def read_symbol(self, library, name):
        return next((s for s in self.specs if s.name == name), None)

    def read_footprint(self, library, name):
        return next((s for s in self.specs if s.name == name), None)

    def scan(self, library):
        return [ComponentInfo(name=s.name, library=str(library), kind="symbol") for s in self.specs]


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "Bibliothek", name="Bridge")


def test_is_a_library_writer(ws):
    writer = AltiumLibraryWriter(FakeBridge(), workspace=ws)  # type: ignore[arg-type]
    assert isinstance(writer, LibraryWriter)
    assert writer.available() == (True, "Altium Designer 26.10.1.5 läuft.")


def test_full_write_replaces_library_with_backup(ws):
    bridge = FakeBridge()
    writer = AltiumLibraryWriter(bridge, workspace=ws)  # type: ignore[arg-type]
    lib = ws.symbols_dir / "PF_Passives.SchLib"
    lib.write_text("OLD", encoding="utf-8")
    result = writer.write_library_full(lib, [resistor_symbol(), ic8_symbol()])
    assert result.ok and result.backend == "altium"
    assert result.written == ["PF_RES", "NE555DR"] and "Hinweis" in result.warnings
    assert lib.read_text(encoding="utf-8") == "NEW:PF_RES,NE555DR"
    backups = list((ws.backups_dir / "lib").glob("PF_Passives.SchLib.*.bak"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "OLD"
    assert _files(ws.symbols_dir) == ["PF_Passives.SchLib"]  # no temp files left


def test_upsert_merges_with_existing_components(ws):
    lib = ws.symbols_dir / "PF_ICs.SchLib"
    lib.write_text("OLD", encoding="utf-8")
    old_res = resistor_symbol()
    old_res.description = "alt"
    bridge = FakeBridge()
    writer = AltiumLibraryWriter(bridge, reader=StubReader([old_res, ic8_symbol()]), workspace=ws)  # type: ignore[arg-type]
    new_res = resistor_symbol()
    result = writer.write_symbols(lib, [new_res, resistor_symbol("PF_RES2")])
    assert result.ok
    assert bridge.writes == [(".SchLib", ["PF_RES", "NE555DR", "PF_RES2"])]
    assert result.written == ["PF_RES", "PF_RES2"]


def test_upsert_without_reader(ws):
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    lib.write_text("OLD", encoding="utf-8")
    writer = AltiumLibraryWriter(FakeBridge(existing=["OTHER", "RESC1608X55N"]), workspace=ws)  # type: ignore[arg-type]
    with pytest.raises(AltiumWriterError, match="OTHER"):
        writer.write_footprints(lib, [chip_0603()])
    writer = AltiumLibraryWriter(FakeBridge(existing=["RESC1608X55N"]), workspace=ws)  # type: ignore[arg-type]
    assert writer.write_footprints(lib, [chip_0603()]).written == ["RESC1608X55N"]
    with pytest.raises(AltiumWriterError, match="Symbolbibliothek"):
        writer.write_symbols(lib, [resistor_symbol()])


def test_delete_components(ws):
    lib = ws.footprints_dir / "PF_SOIC.PcbLib"
    lib.write_text("OLD", encoding="utf-8")
    bridge = FakeBridge()
    writer = AltiumLibraryWriter(bridge, reader=StubReader([soic8("A"), soic8("B")]), workspace=ws)  # type: ignore[arg-type]
    result = writer.delete_components(lib, ["B", "NOPE"])
    assert result.deleted == ["B"] and any("NOPE" in w for w in result.warnings)
    assert bridge.writes == [(".PcbLib", ["A"])]
    writer = AltiumLibraryWriter(bridge, reader=StubReader([soic8("A")]), workspace=ws)  # type: ignore[arg-type]
    result = writer.delete_components(lib, ["A"])
    assert result.deleted == ["A"] and not lib.exists()
    assert any("entfernt" in w for w in result.warnings)
    lib.write_text("X", encoding="utf-8")
    with pytest.raises(AltiumWriterError, match="Bibliotheks-Writer"):
        AltiumLibraryWriter(bridge, workspace=ws).delete_components(lib, ["A"])  # type: ignore[arg-type]


def test_bridge_failure_becomes_result_errors(ws):
    lib = ws.symbols_dir / "PF_X.SchLib"
    lib.write_text("OLD", encoding="utf-8")
    writer = AltiumLibraryWriter(FakeBridge(fail=True), workspace=ws)  # type: ignore[arg-type]
    result = writer.write_library_full(lib, [resistor_symbol()])
    assert not result.ok and "save failed" in result.errors["PF_RES"]
    assert lib.read_text(encoding="utf-8") == "OLD"
    assert _files(ws.symbols_dir) == ["PF_X.SchLib"]


def test_invalid_specs_raise_before_anything_happens(ws):
    bad = resistor_symbol()
    bad.name = "bad/name"
    bridge = FakeBridge()
    writer = AltiumLibraryWriter(bridge, workspace=ws)  # type: ignore[arg-type]
    with pytest.raises(BridgeSpecError):
        writer.write_library_full(ws.symbols_dir / "PF_Y.SchLib", [bad])
    assert bridge.writes == []
    with pytest.raises(AltiumWriterError, match="leere"):
        writer.write_library_full(ws.symbols_dir / "PF_Y.SchLib", [])
    with pytest.raises(AltiumWriterError, match="absolut"):
        writer.write_library_full(Path("relative.SchLib"), [resistor_symbol()])


def test_reading_requires_reader(ws):
    writer = AltiumLibraryWriter(FakeBridge(existing=["A"]), workspace=ws)  # type: ignore[arg-type]
    lib = ws.symbols_dir / "PF_R.SchLib"
    assert writer.read_symbol(lib, "A") is None and writer.read_footprint(lib, "A") is None
    assert writer.list_components(lib) == ["A"]
    assert [i.name for i in writer.scan_library(lib)] == ["A"]
    reader_writer = AltiumLibraryWriter(FakeBridge(), reader=StubReader([resistor_symbol()]), workspace=ws)  # type: ignore[arg-type]
    assert reader_writer.read_symbol(lib, "PF_RES") is not None
    assert reader_writer.list_components(lib) == ["PF_RES"]



def _files(folder: Path) -> list[str]:
    """File names in a library folder (without the hidden lock file of the library lock)."""
    return sorted(p.name for p in folder.iterdir() if p.name != LOCK_FILE_NAME)

# --------------------------------------------------------------------------- review regressions


class LossyBridge(FakeBridge):
    """Altium builds the library but silently skips some components."""

    def __init__(self, skip: set[str]):
        super().__init__()
        self.skip = skip

    def _write(self, target: Path, specs, render) -> BridgeWriteResult:
        render(specs)
        names = [s.name for s in specs if s.name not in self.skip]
        self.writes.append((target.suffix, names))
        target.write_text("NEW:" + ",".join(names), encoding="utf-8")
        return BridgeWriteResult(path=str(target), written=names, warnings=[], created=len(names))


class DetailedReader(StubReader):
    """Reader with per-component loss notes (like RustLibraryOps.read_all_detailed)."""

    def __init__(self, specs, notes: dict[str, list[str]]):
        super().__init__(specs)
        self.notes = notes
        self.extract_step: list[bool] = []

    def read_all_detailed(self, library, *, extract_step=True):
        self.extract_step.append(extract_step)
        return [(s, list(self.notes.get(s.name, []))) for s in self.specs]


def test_partially_built_library_is_not_replaced(ws):
    lib = ws.symbols_dir / "PF_P.SchLib"
    lib.write_text("OLD:OLD_A,OLD_B", encoding="utf-8")
    reader = StubReader([resistor_symbol("OLD_A"), resistor_symbol("OLD_B")])
    writer = AltiumLibraryWriter(LossyBridge({"OLD_B"}), reader=reader, workspace=ws)  # type: ignore[arg-type]
    result = writer.write_symbols(lib, [resistor_symbol("NEW_C")])
    assert not result.ok and result.written == []
    assert set(result.errors) == {"OLD_A", "OLD_B", "NEW_C"}  # errors of untouched components are kept
    assert "nicht erzeugt" in result.errors["OLD_B"] and "OLD_B" in result.errors["NEW_C"]
    assert all("unverändert" in message for message in result.errors.values())
    assert lib.read_text(encoding="utf-8") == "OLD:OLD_A,OLD_B"
    assert list(ws.backups_dir.glob("lib/*.bak")) == []  # nothing replaced -> no backup
    assert _files(ws.symbols_dir) == ["PF_P.SchLib"]  # temp file removed
    # a full write with a skipped component keeps the old library as well
    full = writer.write_library_full(lib, [resistor_symbol("OLD_B"), resistor_symbol("X")])
    assert not full.ok and set(full.errors) == {"OLD_B", "X"}
    assert lib.read_text(encoding="utf-8") == "OLD:OLD_A,OLD_B"


def test_delete_with_partially_built_library_keeps_everything(ws):
    lib = ws.footprints_dir / "PF_SOIC.PcbLib"
    lib.write_text("OLD", encoding="utf-8")
    reader = StubReader([soic8("A"), soic8("B"), soic8("C")])
    writer = AltiumLibraryWriter(LossyBridge({"C"}), reader=reader, workspace=ws)  # type: ignore[arg-type]
    result = writer.delete_components(lib, ["A"])
    assert result.deleted == [] and set(result.errors) == {"A", "B", "C"}
    assert result.errors["A"].startswith("Nicht gelöscht")
    assert lib.read_text(encoding="utf-8") == "OLD"


def test_upsert_refuses_to_drop_data_of_untouched_components(ws):
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    lib.write_text("OLD", encoding="utf-8")
    bridge = FakeBridge()
    reader = DetailedReader(
        [chip_with_step("3D/box.step", name="WITH_STEP"), qfn16("QFN"), soic8("VIAS"), chip_0603("PLAIN")],
        {"VIAS": ["Footprint VIAS: 2 Durchkontaktierung(en) werden nicht übernommen."]},
    )
    writer = AltiumLibraryWriter(bridge, reader=reader, workspace=ws)  # type: ignore[arg-type]
    with pytest.raises(AltiumDataLossError) as exc:
        writer.write_footprints(lib, [chip_0603("NEW_ONE")])
    assert isinstance(exc.value, AltiumWriterError)
    assert set(exc.value.losses) == {"WITH_STEP", "QFN", "VIAS"}
    message = str(exc.value)
    assert "WITH_STEP" in message and "STEP" in message
    assert "QFN" in message and "Pasten" in message  # exposed pad without paste
    assert "VIAS" in message and "Durchkontaktierung" in message
    assert "PLAIN" not in message and "Bibliotheks-Writer" in message and "nichts geändert" in message
    assert bridge.writes == [] and lib.read_text(encoding="utf-8") == "OLD"
    assert reader.extract_step == [False]  # no STEP extraction just for the check
    # replacing the affected components themselves is fine (their new data is what counts)
    reader.specs = [chip_0603("WITH_STEP"), chip_0603("PLAIN")]
    result = writer.write_footprints(lib, [chip_0603("WITH_STEP")])
    assert result.ok and bridge.writes[-1] == (".PcbLib", ["WITH_STEP", "PLAIN"])


def test_upsert_with_explicit_degradation_reports_losses(ws):
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    lib.write_text("OLD", encoding="utf-8")
    bridge = FakeBridge()
    reader = DetailedReader([chip_with_step("3D/box.step", name="WITH_STEP")], {})
    writer = AltiumLibraryWriter(bridge, reader=reader, workspace=ws, allow_degradation=True)  # type: ignore[arg-type]
    result = writer.write_footprints(lib, [chip_0603("NEW_ONE")])
    assert result.ok and result.written == ["NEW_ONE"]
    assert any(w.startswith("WITH_STEP: beim Neuaufbau durch Altium nicht übernommen") for w in result.warnings)


def test_delete_refuses_to_drop_data_of_remaining_components(ws):
    lib = ws.symbols_dir / "PF_ICs.SchLib"
    lib.write_text("OLD", encoding="utf-8")
    reader = DetailedReader(
        [ic8_symbol("KEEP"), resistor_symbol("GONE")],
        {"KEEP": ["Symbol KEEP: nicht übernommen: Pin-Symbole (z. B. Takt, Negation) an 1 Pin(s)."]},
    )
    bridge = FakeBridge()
    writer = AltiumLibraryWriter(bridge, reader=reader, workspace=ws)  # type: ignore[arg-type]
    with pytest.raises(AltiumWriterError, match="KEEP"):
        writer.delete_components(lib, ["GONE"])
    assert bridge.writes == [] and lib.read_text(encoding="utf-8") == "OLD"
    # notes of the component being deleted do not matter
    reader.notes = {"GONE": ["Symbol GONE: nicht übernommen: Textrahmen (1)."]}
    result = writer.delete_components(lib, ["GONE"])
    assert result.deleted == ["GONE"] and bridge.writes == [(".SchLib", ["KEEP"])]


class FileReader(StubReader):
    """Reads the component names the fake bridge wrote into the library file."""

    def __init__(self) -> None:
        super().__init__([])

    def read_all(self, library):
        text = Path(library).read_text(encoding="utf-8")
        names = [n for n in text.split(":", 1)[1].split(",") if n] if ":" in text else []
        return [resistor_symbol(n) for n in names]


class SlowBridge(FakeBridge):
    def _write(self, target: Path, specs, render) -> BridgeWriteResult:
        time.sleep(0.15)
        return super()._write(target, specs, render)


def test_concurrent_upserts_do_not_lose_each_other(ws):
    lib = ws.symbols_dir / "PF_RACE.SchLib"
    lib.write_text("NEW:BASE", encoding="utf-8")
    writer = AltiumLibraryWriter(SlowBridge(), reader=FileReader(), workspace=ws)  # type: ignore[arg-type]
    results: dict[str, WriteResult] = {}

    def upsert(name: str) -> None:
        results[name] = writer.write_symbols(lib, [resistor_symbol(name)])

    threads = [threading.Thread(target=upsert, args=(name,)) for name in ("T1", "T2", "T3")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(results) == ["T1", "T2", "T3"] and all(r.ok for r in results.values())
    names = lib.read_text(encoding="utf-8").split(":", 1)[1].split(",")
    assert sorted(names) == ["BASE", "T1", "T2", "T3"]


def test_backups_have_unique_names_and_hold_the_previous_state(ws):
    lib = ws.symbols_dir / "PF_B.SchLib"
    lib.write_text("NEW:V0", encoding="utf-8")
    writer = AltiumLibraryWriter(FakeBridge(), workspace=ws)  # type: ignore[arg-type]
    for i in range(1, 4):  # several writes within one second
        assert writer.write_library_full(lib, [resistor_symbol(f"V{i}")]).ok
    backups = sorted((ws.backups_dir / "lib").glob("PF_B.SchLib.*.bak"))
    assert sorted(b.read_text(encoding="utf-8") for b in backups) == ["NEW:V0", "NEW:V1", "NEW:V2"]
    assert len({b.name for b in backups}) == 3


@pytest.mark.rustwriter
def test_upsert_loss_check_with_real_rust_reader(ws):
    from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
    from partforge.workspace import set_current

    set_current(ws)
    try:
        write_step(ws.models_dir / "box.step")
        ops = RustLibraryOps(workspace=ws)
        lib = ws.footprints_dir / "PF_CHIP.PcbLib"
        assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="WITH_STEP"), chip_0603("PLAIN")]).ok
        before = lib.read_bytes()
        bridge = FakeBridge()
        writer = AltiumLibraryWriter(bridge, reader=ops, workspace=ws)  # type: ignore[arg-type]
        with pytest.raises(AltiumWriterError, match="WITH_STEP"):
            writer.write_footprints(lib, [chip_0603("NEW_ONE")])
        assert bridge.writes == [] and lib.read_bytes() == before
        # the read for the check does not extract STEP models into the workspace
        assert sorted(p.name for p in ws.models_dir.iterdir()) == ["box.step"]
        sym_lib = ws.symbols_dir / "PF_S.SchLib"
        assert ops.upsert_symbols(sym_lib, [ic8_symbol("U1")]).ok
        result = writer.write_symbols(sym_lib, [resistor_symbol("R1")])  # Rust-written symbols: loss-free
        assert result.ok and bridge.writes[-1] == (".SchLib", ["U1", "R1"])
    finally:
        set_current(None)
        shutdown_client()
