"""Library import (``partforge.altium.libimport`` and ``/api/library-import/*``).

* ZIP and IntLib extraction, target paths, folder names, messages, the parts table and the API error paths run
  without the library writer (IntLibs are built with ole32 through ``test_sync_support.build_compound``).
* Scanning and importing real libraries need ``altium-designer-mcp.exe`` (marker ``rustwriter``): the source
  libraries are written once per module by PartForge's own writer into a scratch library and then placed
  outside every workspace (:func:`sources`).

The import cache (unpacked ZIP/IntLib members) of every test lives under its ``tmp_path`` (``cache_dir``).
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import time
import zipfile
import zlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_sync_support import build_compound
from test_writer_samples import chip_0603, ic8_symbol, resistor_symbol, soic8

from partforge.altium import housestyle, libimport, libwriter, sync
from partforge.altium.libimport import ImportError_, ImportScan, LibraryImportOptions, SourceFile
from partforge.altium.rustwriter import RustLibraryOps, is_inside, shutdown_client
from partforge.db import registry
from partforge.db.models import FootprintRecord, RecordSource, SymbolRecord
from partforge.geometry.model import FootprintLink, FootprintSpec, SymbolSpec
from partforge.importers import spreadsheet
from partforge.workspace import Workspace

rust = pytest.mark.rustwriter

#: Targets of the shared source folder "Vendor Libs" (default target folder = the folder name).
CHIPS_TARGET = "Footprints\\Import\\Vendor Libs\\Footprints\\Chips.PcbLib"
PASSIVES_TARGET = "Symbols\\Import\\Vendor Libs\\Symbols\\Passives.SchLib"
EXTRA_TARGET = "Symbols\\Import\\Vendor Libs\\Symbols\\Zusatz\\Extra.SchLib"
#: A symbol PartForge generated in the library (registered before the scan: its name is taken).
GENERATED_LIBRARY = "Symbols\\PF_Passives.SchLib"
DBLIB_TEXT = (
    "[OutputDatabaseLinkFile]\r\nVersion=1.1\r\n[DatabaseLinks]\r\n"
    "ConnectionString=Download from https://portal.altiumlibrary.com/\r\n"
)
#: A realistic vendor file name longer than 60 characters (74).
LONG_FILE_NAME = "Texas_Instruments_LM358DR_Dual_Operational_Amplifier_SOIC-8_Symbols.SchLib"


# --------------------------------------------------------------------------- fixtures and helpers


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module() -> Iterator[None]:
    yield
    shutdown_client()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """No Altium, a fresh component-name cache and an empty scan cache in every test."""
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    monkeypatch.setattr(libimport, "_scans", {})
    libwriter.forget_component_names()


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The import cache of this test (never PartForge's local data folder)."""
    folder = tmp_path / "import-cache"
    folder.mkdir()
    monkeypatch.setattr(libimport, "_cache_dir", lambda: folder)
    return folder


@dataclass(frozen=True)
class Sources:
    """Real libraries (written by the Rust writer) and a source folder that holds them.

    ``folder`` ("Vendor Libs", outside every workspace)::

        Footprints\\Chips.PcbLib      LI_0603, LI_SOIC8
        Symbols\\Passives.SchLib      LI_RES, LI_TIMER (parameters, footprint link LI_SOIC8)
        Symbols\\Zusatz\\Extra.SchLib  LI_RES (a second time), LI_CAP
        History\\Passives~1.SchLib    no library (the History folder is never read)
        Vendor.DbLib, readme.txt
    """

    folder: Path
    passives: bytes
    passives_v2: bytes  # Passives.SchLib with another description of LI_RES
    extra: bytes
    chips: bytes


@pytest.fixture(scope="module")
def sources(tmp_path_factory: pytest.TempPathFactory) -> Sources:
    """Four writer calls per module; every test copies what it changes into its own ``tmp_path``."""
    base = tmp_path_factory.mktemp("libimport-sources")
    scratch = Workspace.create(base / "scratch", name="Quellen")
    ops = RustLibraryOps(workspace=scratch)

    def write(name: str, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]) -> bytes:
        path = scratch.root / "Exports" / name
        result = ops.write_library_full(path, specs)
        assert result.ok, result
        return path.read_bytes()

    timer = ic8_symbol("LI_TIMER")
    timer.parameters = {"Manufacturer": "Texas Instruments", "Manufacturer Part Number": "NE555DR", "Supply": "+5V"}
    timer.footprints = [FootprintLink(name="LI_SOIC8", description="SOIC-8")]
    cap = resistor_symbol("LI_CAP")
    cap.description = "Kondensator, generisch"
    res_v2 = resistor_symbol("LI_RES")
    res_v2.description = "Widerstand, Version 2"
    passives = write("Passives.SchLib", [resistor_symbol("LI_RES"), timer])
    passives_v2 = write("Passives_v2.SchLib", [res_v2, timer])
    extra = write("Extra.SchLib", [resistor_symbol("LI_RES"), cap])
    chips = write("Chips.PcbLib", [chip_0603("LI_0603"), soic8("LI_SOIC8")])
    folder = base / "Vendor Libs"
    _write_files(folder, {
        "Footprints/Chips.PcbLib": chips,
        "Symbols/Passives.SchLib": passives,
        "Symbols/Zusatz/Extra.SchLib": extra,
        "History/Passives~1.SchLib": b"an Altium backup copy, never read",
        "Vendor.DbLib": DBLIB_TEXT.encode("cp1252"),
        "readme.txt": b"Vendor library",
    })
    return Sources(folder=folder, passives=passives, passives_v2=passives_v2, extra=extra, chips=chips)


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _zip(path: Path, members: Mapping[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _packed(data: bytes) -> bytes:
    """An IntLib member: ``0x02`` + zlib of the whole library file."""
    return b"\x02" + zlib.compress(data)


def _compound(tmp_path: Path, name: str, marker: bytes) -> bytes:
    """A small compound file (stands in for a SchLib/PcbLib where only the container matters)."""
    return build_compound(tmp_path / name, {"FileHeader": marker}).read_bytes()


def _abs(ws: Workspace, rel: str) -> Path:
    path = ws.abs(rel)
    assert path is not None
    return path


def _register_symbol(name: str, library: str, *, source: RecordSource = "generated") -> None:
    registry.upsert_symbol(SymbolRecord(name=name, library=library, source=source, status="ok"))


def _states(scan: ImportScan) -> dict[tuple[str, str], tuple[str, str | None]]:
    return {(f.rel, c.name): (c.state, c.registered_library) for f in scan.files for c in f.components}


def _csv_rows(data: bytes) -> list[list[str]]:
    assert data.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM: Excel opens umlauts correctly
    text = data[3:].decode("utf-8")
    assert "\r\n" in text
    return list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))


def _wait_job(client: TestClient, job: Mapping[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job['id']} did not finish")


# --------------------------------------------------------------------------- folder names and targets


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Murata", "Murata"),
        ('Vendor: "Libs" <2024>?', "Vendor_ _Libs_ _2024__"),
        ("a/b\\c", "a_b_c"),
        ("a   b\tc", "a b_c"),  # control characters become "_", runs of blanks one blank
        ("Bibliothek...", "Bibliothek"),
        ("  ..  ", "Import"),
        ("", "Import"),
        ("x" * 100, "x" * 60),
    ],
)
def test_safe_folder_name(raw: str, expected: str) -> None:
    assert libimport.safe_folder_name(raw) == expected


def test_target_rel_keeps_the_source_structure_below_the_import_folder(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    target = libimport._target_rel
    assert target(ws, "Murata", "Passives.SchLib", "schlib") == "Symbols\\Import\\Murata\\Passives.SchLib"
    assert target(ws, "Murata", "sub\\deep\\Chips.PcbLib", "pcblib") == (
        "Footprints\\Import\\Murata\\sub\\deep\\Chips.PcbLib")
    # IntLib members: the IntLib segment is dropped, the folder of the IntLib is kept
    assert target(ws, "Murata", "Murata.IntLib/Murata.SchLib", "schlib") == "Symbols\\Import\\Murata\\Murata.SchLib"
    assert target(ws, "Murata", "sub\\Murata.IntLib\\Murata_2.PcbLib", "pcblib") == (
        "Footprints\\Import\\Murata\\sub\\Murata_2.PcbLib")
    # the target folder and every segment are sanitised; without a name the file gets a default one
    assert target(ws, 'Bad: "Name"?', "a<b>.SchLib", "schlib") == "Symbols\\Import\\Bad_ _Name__\\a_b_.SchLib"
    assert target(ws, "Murata", "", "pcblib") == "Footprints\\Import\\Murata\\Bibliothek.PcbLib"
    # nothing leaves the import folder: no "..", no drive
    for rel in ("..\\..\\evil\\x.PcbLib", "C:\\abs\\x.PcbLib", "\\\\server\\share\\x.PcbLib"):
        result = target(ws, "Murata", rel, "pcblib")
        parts = PureWindowsPath(result).parts
        assert parts[:3] == ("Footprints", "Import", "Murata") and parts[-1] == "x.PcbLib", result
        assert ".." not in parts and ":" not in result and not PureWindowsPath(result).is_absolute()
    # the library's own folder names are used
    ws.settings.folders.symbols = "Bauteile\\Symbole"
    assert target(ws, "Murata", "a.SchLib", "schlib") == "Bauteile\\Symbole\\Import\\Murata\\a.SchLib"


def test_target_rel_keeps_the_extension_of_long_file_names(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "ws")
    target = libimport._target_rel(ws, "TI", LONG_FILE_NAME, "schlib")
    assert PureWindowsPath(target).suffix == ".SchLib", target


# --------------------------------------------------------------------------- ZIP archives


def test_extract_zip_unpacks_library_members_with_their_paths(tmp_path: Path, cache_dir: Path) -> None:
    archive = tmp_path / "ACME.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ACME/Symbols/Passives.SchLib", b"schlib bytes")
        zf.writestr("ACME/empty/", b"")  # a folder entry
        zf.writestr("ACME/Footprints/Chips.PcbLib", b"pcblib bytes")
        zf.writestr("ACME/Datasheet.pdf", b"%PDF-1.4")
        zf.writestr("ACME/ACME.PrjPcb", b"[Design]")
        zf.writestr("readme.txt", b"hello")
        zf.writestr("Top.schlib", b"lower-case extension")
    out = libimport.extract_zip(archive)
    assert [(rel, kind) for rel, _, kind in out] == [
        ("ACME\\Symbols\\Passives.SchLib", "schlib"),
        ("ACME\\Footprints\\Chips.PcbLib", "pcblib"),
        ("Top.schlib", "schlib"),
    ]
    assert [path.read_bytes() for _, path, _ in out] == [b"schlib bytes", b"pcblib bytes", b"lower-case extension"]
    # one folder per archive inside the cache, the archive's structure below it; other files are not unpacked
    folders = {path.relative_to(cache_dir).parts[0] for _, path, _ in out}
    assert len(folders) == 1
    folder = cache_dir / folders.pop()
    assert [path.relative_to(folder).as_posix() for _, path, _ in out] == [
        "ACME/Symbols/Passives.SchLib", "ACME/Footprints/Chips.PcbLib", "Top.schlib",
    ]
    assert sorted(p.relative_to(cache_dir).as_posix() for p in cache_dir.rglob("*") if p.is_file()) == sorted(
        path.relative_to(cache_dir).as_posix() for _, path, _ in out
    )
    # a second scan of the same archive finds its members in the cache (not unpacked again)
    stamps = [path.stat().st_mtime_ns for _, path, _ in out]
    again = libimport.extract_zip(archive)
    assert again == out and [path.stat().st_mtime_ns for _, path, _ in again] == stamps


def test_extract_zip_never_writes_outside_the_cache(tmp_path: Path, cache_dir: Path) -> None:
    hostile = {
        "../evil.SchLib": "evil.SchLib",
        "../../outside/evil2.PcbLib": "outside\\evil2.PcbLib",
        "C:/abs.PcbLib": "abs.PcbLib",
        "a/../../b.PcbLib": "a\\b.PcbLib",
        "/rooted/x.SchLib": "rooted\\x.SchLib",
        'bad:na*me?"<>|.SchLib': "bad_na_me_____.SchLib",
        "ctrl\x07char.PcbLib": "ctrl_char.PcbLib",
        "dots. /lib.SchLib. ": "dots\\lib.SchLib",
        "//server/share/unc.PcbLib": None,  # a UNC path is dropped
    }
    archive = _zip(tmp_path / "hostile.zip", {name: name.encode("utf-8") for name in hostile})
    out = libimport.extract_zip(archive)
    assert [rel for rel, _, _ in out] == [rel for rel in hostile.values() if rel is not None]
    for (rel, path, _kind), name in zip(out, (n for n, r in hostile.items() if r is not None), strict=True):
        assert is_inside(path, cache_dir) and path.is_file(), (name, path)
        assert path.read_bytes() == name.encode("utf-8")
        parts = PureWindowsPath(rel).parts
        assert ".." not in parts and not PureWindowsPath(rel).drive and not re.search(r'[<>:"|?*\x00-\x1f]', rel)
    stray = [p for p in tmp_path.rglob("*") if p.is_file() and not is_inside(p, cache_dir) and p != archive]
    assert stray == []


def test_extract_zip_expands_an_intlib(tmp_path: Path, cache_dir: Path) -> None:
    sch, pcb = _compound(tmp_path, "sch.bin", b"SchLib"), _compound(tmp_path, "pcb.bin", b"PcbLib")
    intlib = build_compound(tmp_path / "Murata.IntLib", {
        "SchLib/0.schlib": _packed(sch),
        "PCBLib/0.pcblib": _packed(pcb),
    })
    archive = _zip(tmp_path / "Murata.zip", {
        "Murata/Murata.IntLib": intlib.read_bytes(),
        "Murata/Broken.IntLib": b"no compound file",  # logged and left out
        "Murata/Extra.SchLib": b"plain library",
    })
    out = libimport.extract_zip(archive)
    assert [(rel, kind) for rel, _, kind in out] == [
        ("Murata\\Murata.IntLib\\Murata.PcbLib", "pcblib"),
        ("Murata\\Murata.IntLib\\Murata.SchLib", "schlib"),
        ("Murata\\Extra.SchLib", "schlib"),
    ]
    assert [path.read_bytes() for _, path, _ in out] == [pcb, sch, b"plain library"]
    assert all(is_inside(path, cache_dir) for _, path, _ in out)


def test_extract_zip_errors(tmp_path: Path) -> None:
    cases = [
        (_zip(tmp_path / "Doku.zip", {"readme.txt": b"x", "Docs/Datenblatt.pdf": b"%PDF"}),
         "Doku.zip enthält keine .SchLib, .PcbLib oder .IntLib."),
        (_zip(tmp_path / "IntLib.zip", {"Lib.IntLib": b"no compound file"}),
         "IntLib.zip enthält keine .SchLib, .PcbLib oder .IntLib."),
        (_zip(tmp_path / "Leer.zip", {}), "Leer.zip enthält keine .SchLib, .PcbLib oder .IntLib."),
    ]
    broken = tmp_path / "kaputt.zip"
    broken.write_bytes(b"PK\x03\x04 this is not a zip archive")
    for path, message in cases:
        with pytest.raises(ImportError_) as info:
            libimport.extract_zip(path)
        assert info.value.status == 400 and str(info.value) == message
    with pytest.raises(ImportError_) as info:
        libimport.extract_zip(broken)
    assert info.value.status == 400 and str(info.value).startswith("kaputt.zip ist kein lesbares ZIP-Archiv")


def test_extract_zip_rejects_a_damaged_member(tmp_path: Path, cache_dir: Path) -> None:
    payload = b"L" * 64
    archive = tmp_path / "beschaedigt.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("Vendor/Lib.SchLib", payload)
    raw = bytearray(archive.read_bytes())
    raw[raw.find(payload)] ^= 0xFF  # the CRC no longer matches
    archive.write_bytes(bytes(raw))
    with pytest.raises(ImportError_) as info:
        libimport.extract_zip(archive)
    assert info.value.status == 400 and "Vendor/Lib.SchLib nicht entpackbar" in str(info.value)
    assert [p for p in cache_dir.rglob("*") if p.is_file()] == []  # neither the member nor a partial file


def test_extract_zip_size_and_member_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with zipfile.ZipFile(tmp_path / "gross.zip", "w") as zf:
        zf.writestr("a.SchLib", b"a" * 60)
        zf.writestr("docs/", b"")  # folders are no members
        zf.writestr("big.txt", b"t" * 1000)  # only library files count towards the size
        zf.writestr("b.PcbLib", b"b" * 40)
    archive = tmp_path / "gross.zip"
    monkeypatch.setattr(libimport, "ZIP_MAX_BYTES", 100)
    monkeypatch.setattr(libimport, "ZIP_MAX_MEMBERS", 3)
    assert [rel for rel, _, _ in libimport.extract_zip(archive)] == ["a.SchLib", "b.PcbLib"]  # exactly at both limits
    monkeypatch.setattr(libimport, "ZIP_MAX_BYTES", 99)
    with pytest.raises(ImportError_) as info:
        libimport.extract_zip(archive)
    assert info.value.status == 400 and "gross.zip: die Bibliotheken im Archiv sind größer als" in str(info.value)
    assert "bitte entpacken und den Ordner wählen" in str(info.value)
    monkeypatch.setattr(libimport, "ZIP_MAX_BYTES", 1 << 30)
    monkeypatch.setattr(libimport, "ZIP_MAX_MEMBERS", 2)
    with pytest.raises(ImportError_) as info:
        libimport.extract_zip(archive)
    assert info.value.status == 400 and str(info.value).startswith("gross.zip enthält zu viele Dateien")


def test_extract_zip_keeps_members_whose_names_differ_only_in_case(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "case.zip", {"Lib.SchLib": b"first library", "LIB.SCHLIB": b"second, longer library"})
    out = libimport.extract_zip(archive)
    # Windows paths ignore case: the second member gets its own name (its import target must differ as well)
    assert [rel for rel, _, _ in out] == ["Lib.SchLib", "LIB_2.SCHLIB"]
    assert [path.read_bytes() for _, path, _ in out] == [b"first library", b"second, longer library"]


# --------------------------------------------------------------------------- IntLib


def test_extract_intlib_members(tmp_path: Path, cache_dir: Path) -> None:
    sch = _compound(tmp_path, "sch.bin", b"SchLib")
    pcb1, pcb2 = _compound(tmp_path, "pcb1.bin", b"PcbLib 1"), _compound(tmp_path, "pcb2.bin", b"PcbLib 2")
    intlib = build_compound(tmp_path / "Murata.IntLib", {
        "Version": b"1",  # no library storage
        "SchLib/0.schlib": _packed(sch),
        "SchLib/1.schlib": sch,  # not marked 0x02
        "SchLib/2.schlib": _packed(b"no compound file"),
        "PCBLib/0.pcblib": _packed(pcb1),
        "PCBLib/1.pcblib": b"\x02 no zlib data",
        "PCBLib/2.pcblib": _packed(pcb2),
        "Models/0.step": _packed(b"ISO-10303-21;"),
    })
    members = libimport.extract_intlib(intlib)
    assert [(rel, kind) for rel, _, kind in members] == [
        ("Murata.IntLib\\Murata.PcbLib", "pcblib"),
        ("Murata.IntLib\\Murata_2.PcbLib", "pcblib"),
        ("Murata.IntLib\\Murata.SchLib", "schlib"),
    ]
    assert [path.read_bytes() for _, path, _ in members] == [pcb1, pcb2, sch]
    assert all(is_inside(path, cache_dir) for _, path, _ in members)
    assert libimport.extract_intlib(intlib) == members  # cached


def test_extract_intlib_errors(tmp_path: Path) -> None:
    text = tmp_path / "Text.IntLib"
    text.write_bytes(b"hello")
    with pytest.raises(ImportError_) as info:
        libimport.extract_intlib(text)
    assert info.value.status == 400
    assert str(info.value).startswith("Text.IntLib ist keine lesbare integrierte Bibliothek")
    empty = build_compound(tmp_path / "Leer.IntLib", {"Version": b"1", "Models/0.step": _packed(b"step")})
    with pytest.raises(ImportError_) as info:
        libimport.extract_intlib(empty)
    assert info.value.status == 400
    assert str(info.value) == "Leer.IntLib enthält keine Symbol- oder Footprint-Bibliothek."


# --------------------------------------------------------------------------- source files (no writer)


def test_source_files_of_a_folder(tmp_path: Path) -> None:
    root = tmp_path / "Libs"
    _write_files(root, {
        "a.SchLib": b"x",
        "B.PCBLIB": b"x",
        "sub/c.schlib": b"x",
        "history2/d.PcbLib": b"x",
        "History/a~1.SchLib": b"x",  # Altium's local history
        "__Previews/e.SchLib": b"x",
        ".git/f.SchLib": b"x",
        "notes.txt": b"x",
        "Project.PrjPcb": b"x",
        "Vendor.DbLib": b"[DatabaseLinks]\r\nConnectionString=Provider=MSDASQL.1;Persist Security Info=False\r\n",
    })
    files, notes = libimport._source_files(root)
    assert files == [
        ("a.SchLib", root / "a.SchLib", "schlib"),
        ("B.PCBLIB", root / "B.PCBLIB", "pcblib"),
        ("history2\\d.PcbLib", root / "history2" / "d.PcbLib", "pcblib"),
        ("sub\\c.schlib", root / "sub" / "c.schlib", "schlib"),
    ]
    assert notes == [
        "Vendor.DbLib: Datenbankbibliothek – ihre Bauteildaten liegen in der Datenbank und werden nicht übernommen; "
        "importiert werden die Symbole und Footprints der Bibliotheksdateien."
    ]  # a connection string with "=" (ODBC) is not shown


def test_source_files_of_single_files_and_library_packages(tmp_path: Path) -> None:
    _write_files(tmp_path, {
        "one.SchLib": b"x",
        "Pkg/Symbols/Passives.SchLib": b"x",
        "Shared/Chips.PcbLib": b"x",
        "Pkg/Readme.txt": b"x",
        "Vendor.DbLib": DBLIB_TEXT.encode("cp1252"),
        "notes.txt": b"x",
    })
    assert libimport._source_files(tmp_path / "one.SchLib") == ([("one.SchLib", tmp_path / "one.SchLib", "schlib")], [])
    package = tmp_path / "Pkg" / "Vendor.LibPkg"
    package.write_text(
        "[Design]\r\nVersion=1.0\r\n[Document1]\r\nDocumentPath=Symbols\\Passives.SchLib\r\n"
        "[Document2]\r\nDocumentPath=..\\Shared\\Chips.PcbLib\r\n[Document3]\r\nDocumentPath=Fehlt.SchLib\r\n"
        "[Document4]\r\nDocumentPath=Readme.txt\r\n",
        encoding="utf-8-sig",
    )
    files, notes = libimport._source_files(package)
    assert notes == []
    assert [(rel, path.resolve(), kind) for rel, path, kind in files] == [
        ("Symbols\\Passives.SchLib", (tmp_path / "Pkg" / "Symbols" / "Passives.SchLib").resolve(), "schlib"),
        ("..\\Shared\\Chips.PcbLib", (tmp_path / "Shared" / "Chips.PcbLib").resolve(), "pcblib"),
    ]
    empty = tmp_path / "Pkg" / "Leer.LibPkg"
    empty.write_text("[Document1]\r\nDocumentPath=Fehlt.SchLib\r\n", encoding="utf-8")
    refusals = {
        empty: "Leer.LibPkg nennt keine vorhandenen SchLib-/PcbLib-Dateien.",
        tmp_path / "Vendor.DbLib": "Bitte den Ordner mit den Bibliotheksdateien wählen.",
        tmp_path / "notes.txt": "notes.txt: bitte einen Ordner, eine .SchLib, .PcbLib, .IntLib, .LibPkg oder .zip "
                                "wählen.",
    }
    for path, message in refusals.items():
        with pytest.raises(ImportError_) as info:
            libimport._source_files(path)
        assert info.value.status == 400 and message in str(info.value), str(info.value)
    with pytest.raises(ImportError_) as info:
        libimport._source_files(tmp_path / "Vendor.DbLib")
    assert str(info.value).startswith("Vendor.DbLib: Datenbankbibliothek (Verbindung: „Download from "
                                      "https://portal.altiumlibrary.com/“)")


# --------------------------------------------------------------------------- scan cache, refusals, messages


def test_scan_refuses_sources_it_cannot_read(workspace: Workspace, tmp_path: Path) -> None:
    inside = workspace.symbols_dir / "Eigen.SchLib"
    inside.write_bytes(b"x")
    cases = [
        ("", 400, "Bitte einen Ordner oder eine Bibliotheksdatei angeben."),
        ('  ""  ', 400, "Bitte einen Ordner oder eine Bibliotheksdatei angeben."),
        ("Bibliotheken\\Hersteller", 400, "Der Pfad muss absolut sein: Bibliotheken\\Hersteller"),
        (str(tmp_path / "fehlt"), 404, "wurde nicht gefunden"),
        (str(workspace.root), 400, "Die Quelle liegt im Bibliotheksordner selbst"),
        (f'"{inside}"', 400, "Die Quelle liegt im Bibliotheksordner selbst"),
    ]
    for raw, status, message in cases:
        with pytest.raises(ImportError_) as info:
            libimport.scan(raw)
        assert info.value.status == status and message in str(info.value), (raw, str(info.value))
    assert issubclass(ImportError_, sync.SyncError)  # the API maps it like every library error


def test_scan_cache_keeps_the_newest_scans(monkeypatch: pytest.MonkeyPatch) -> None:
    made = [ImportScan(id=f"scan{i}", source="C:\\Quelle", name="Quelle", created="")
            for i in range(libimport.MAX_SCANS + 1)]
    for scan in made:
        libimport._remember(scan)
    with pytest.raises(ImportError_) as info:
        libimport.get_scan("scan0")
    assert info.value.status == 404 and "bitte erneut „Einlesen“ wählen" in str(info.value)
    assert [libimport.get_scan(scan.id) for scan in made[1:]] == made[1:]
    monkeypatch.setattr(libimport, "SCAN_TTL_S", -1.0)  # every kept scan has expired
    fresh = ImportScan(id="fresh", source="C:\\Quelle", name="Quelle", created="")
    libimport._remember(fresh)
    assert libimport.get_scan("fresh") is fresh
    with pytest.raises(ImportError_):
        libimport.get_scan("scan8")


def test_scan_and_import_messages() -> None:
    scan = ImportScan(id="a", source="C:\\Q", name="Q", created="", symbols=1,
                      files=[SourceFile(rel="a.SchLib", kind="schlib", path="C:\\Q\\a.SchLib")])
    assert libimport.scan_message(scan) == "1 Bibliothek gelesen: 1 Symbol, 0 Footprints."
    scan.imported, scan.taken, scan.duplicates = 2, 3, 4
    assert libimport.scan_message(scan) == (
        "1 Bibliothek gelesen: 1 Symbol, 0 Footprints (2 schon importiert, 3 Namen schon vergeben, 4 doppelt)."
    )
    assert libimport.import_message({}) == "Bibliotheksimport: nichts übernommen."
    assert libimport.import_message({"copied": 0, "unchanged": 3}) == (
        "Bibliotheksimport: nichts übernommen (3 Dateien unverändert).")
    assert libimport.import_message({"copied": 0, "unchanged": 2, "symbols": 2}) == (
        "Bibliotheksimport fertig: 2 Symbole und 0 Footprints aus 2 Dateien (alle unverändert).")
    assert libimport.import_message({"copied": 1, "unchanged": 1, "footprints": 1, "conflicts": [{}],
                                     "removed": [{}]}) == (
        "Bibliotheksimport fertig: 0 Symbole und 1 Footprint aus 2 Dateien (davon 1 unverändert, 1 Name nicht "
        "übernommen, 1 nicht mehr enthaltener Name abgemeldet).")
    out = {"copied": 1, "symbols": 1, "footprints": 2, "conflicts": [{}, {}], "errors": [{}, {}],
           "conversion": {"message": "Hausstil angewendet: 3 Bauteile in 2 Bibliotheken."}}
    assert libimport.import_message(out) == (
        "Bibliotheksimport fertig: 1 Symbol und 2 Footprints aus 1 Datei (2 Namen nicht übernommen, 2 Fehler). "
        "Hausstil angewendet: 3 Bauteile in 2 Bibliotheken."
    )


# --------------------------------------------------------------------------- parts table (registry only)


def _symbol_record(name: str, library: str, *, source: RecordSource = "imported", comment: str = "*",
                   description: str = "", parameters: dict[str, str] | None = None,
                   footprints: Sequence[str] = ()) -> SymbolRecord:
    spec = SymbolSpec(name=name, description=description, comment=comment, parameters=parameters or {},
                      footprints=[FootprintLink(name=f) for f in footprints])
    return SymbolRecord(name=name, library=library, source=source, spec=spec, status="ok")


LIB_A = "Symbols\\Import\\ACME\\A.SchLib"
LIB_B = "Symbols\\Import\\ACME\\B.SchLib"
FP_LIB = "Footprints\\Import\\ACME\\FP.PcbLib"


def _register_parts_table_symbols() -> None:
    registry.upsert_footprint(FootprintRecord(name="FP_A", library=FP_LIB, source="imported", status="ok"))
    registry.upsert_symbols([
        _symbol_record("IMP_A", LIB_A, comment="=Value", description="Timer", footprints=["FP_A", "FP_B", "FP_C"],
                       parameters={"Manufacturer Part Number": "MPN-A", "Value": "=Formel", "Supply": "+5V",
                                   "Macro": "@SUM(A1)", "Temperature": "-55°C", "Switch": "-x", "Empty": "",
                                   "Star": "*"}),
        _symbol_record("IMP_B", LIB_B, comment="LM358"),
        _symbol_record("IMP_C", LIB_B),
        _symbol_record("+5V_REF", LIB_B, description='=HYPERLINK("http://x")'),
        _symbol_record("GEN", GENERATED_LIBRARY, source="generated", comment="10k"),
        _symbol_record("EXT", "C:\\Hersteller\\Ext.SchLib", source="external"),
    ])
    registry.upsert_symbol(SymbolRecord(name="NOSPEC", library=LIB_B, source="imported", status="ok"))


def test_parts_table_columns_rows_and_formula_guard(workspace: Workspace) -> None:
    _register_parts_table_symbols()
    data, count = libimport.parts_table(libraries=[LIB_A, "symbols/import/acme/b.schlib"])
    header, *rows = _csv_rows(data)
    assert count == len(rows) == 4  # NOSPEC has no geometry
    assert header == ["Part Number", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path",
                      "Footprint Ref 2", "Comment", "Description",  # fixed columns, only those with a value
                      "Manufacturer Part Number", "Supply", "Macro", "Temperature", "Switch"]  # the parameters
    table = {row[1]: dict(zip(header, row, strict=True)) for row in rows}
    assert list(table) == ["'+5V_REF", "IMP_A", "IMP_B", "IMP_C"]  # sorted by name; a name may need the guard too
    assert table["IMP_A"] == {
        "Part Number": "MPN-A", "Library Ref": "IMP_A", "Library Path": LIB_A,
        "Footprint Ref": "FP_A", "Footprint Path": FP_LIB, "Footprint Ref 2": "FP_B",  # the third link is left out
        "Comment": "",  # "=Value" is an Altium parameter reference, never a value
        "Description": "Timer", "Manufacturer Part Number": "MPN-A",
        "Supply": "'+5V", "Macro": "'@SUM(A1)", "Temperature": "-55°C", "Switch": "'-x",
    }
    assert (table["IMP_B"]["Part Number"], table["IMP_B"]["Comment"]) == ("LM358", "LM358")  # comment as part number
    assert (table["IMP_C"]["Part Number"], table["IMP_C"]["Comment"]) == ("IMP_C", "")  # else the name
    assert table["'+5V_REF"]["Part Number"] == "'+5V_REF"
    assert table["'+5V_REF"]["Description"] == "'=HYPERLINK(\"http://x\")"
    # the spreadsheet import removes the guard again
    stored = workspace.root / "Exports" / "Bibliotheksimport.csv"
    stored.write_bytes(data)
    assert spreadsheet.read_table_file(stored).rows[0][:2] == ["+5V_REF", "+5V_REF"]
    # filters: names (case-insensitive) and libraries; generated symbols count, external ones and those without
    # geometry never
    everything = _csv_rows(libimport.parts_table()[0])[1:]
    assert [row[1] for row in everything] == ["'+5V_REF", "GEN", "IMP_A", "IMP_B", "IMP_C"]
    assert [row[1] for row in _csv_rows(libimport.parts_table(names=["imp_b", "GEN"])[0])[1:]] == ["GEN", "IMP_B"]
    for kwargs in ({"libraries": [LIB_A], "names": ["IMP_B"]}, {"libraries": [FP_LIB]}, {"names": ["EXT", "NOSPEC"]}):
        with pytest.raises(ImportError_) as info:
            libimport.parts_table(**kwargs)
        assert info.value.status == 400 and "Keine Symbole mit Geometrie in der Auswahl" in str(info.value)


# --------------------------------------------------------------------------- API without the writer


def test_api_scan_refuses_relative_and_missing_paths(client: TestClient, tmp_path: Path) -> None:
    for path in ("Bibliotheken\\Hersteller", "   ", '""'):
        resp = client.post("/api/library-import/scan", json={"path": path})
        assert resp.status_code == 400, path
        assert "absoluten Pfad" in resp.json()["detail"]
    resp = client.post("/api/library-import/scan", json={"path": str(tmp_path / "fehlt")})
    assert resp.status_code == 404 and "wurde nicht gefunden" in resp.json()["detail"]


def test_api_unknown_scan(client: TestClient) -> None:
    resp = client.get("/api/library-import/scans/0123456789ab")
    assert resp.status_code == 404 and "erneut „Einlesen“" in resp.json()["detail"]
    assert client.post("/api/library-import/run", json={"scan_id": "0123456789ab"}).status_code == 404
    params = {"scan_id": "0123456789ab", "rel": "a.SchLib", "name": "X"}
    assert client.get("/api/library-import/preview", params=params).status_code == 404


def test_api_parts_table_is_an_upload_of_the_spreadsheet_import(
    client: TestClient, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(spreadsheet, "_upload_dir", lambda: uploads)
    _register_parts_table_symbols()
    resp = client.post("/api/library-import/parts-table", json={"libraries": [LIB_A, LIB_B]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file_name"] == "Bibliotheksimport.csv" and body["rows"] == 4
    preview = client.post(f"/api/import/preview/{body['token']}", json={"table": "Integrated Circuits"})
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["file_name"] == "Bibliotheksimport.csv" and data["delimiter"] == ";" and data["row_count"] == 4
    assert data["headers"][:3] == ["Part Number", "Library Ref", "Library Path"]
    assert data["rows"][0][:2] == ["+5V_REF", "+5V_REF"]  # the formula guard is gone again
    mapped = {m["header"]: m["column"] for m in data["mapping"]}
    assert mapped["Library Ref"] == "Library Ref" and mapped["Footprint Ref"] == "Footprint Ref"
    resp = client.post("/api/library-import/parts-table", json={"names": ["GIBT_ES_NICHT"]})
    assert resp.status_code == 400 and "Keine Symbole mit Geometrie" in resp.json()["detail"]


# --------------------------------------------------------------------------- scan and import (Rust writer)


@rust
def test_scan_of_a_folder(workspace: Workspace, sources: Sources) -> None:
    _register_symbol("LI_CAP", GENERATED_LIBRARY)  # a symbol of the library: the name is taken
    scan = libimport.scan(str(sources.folder))
    assert scan.source == str(sources.folder) and scan.name == "Vendor Libs" and scan.created
    assert [(f.rel, f.kind) for f in scan.files] == [
        ("Footprints\\Chips.PcbLib", "pcblib"),
        ("Symbols\\Passives.SchLib", "schlib"),
        ("Symbols\\Zusatz\\Extra.SchLib", "schlib"),
    ]
    assert [f.target for f in scan.files] == [CHIPS_TARGET, PASSIVES_TARGET, EXTRA_TARGET]
    for entry in scan.files:
        path = Path(entry.path)
        assert is_inside(path, sources.folder) and entry.size == path.stat().st_size > 0
        assert entry.problem is None and entry.exists == "no"
    assert [[c.name for c in f.components] for f in scan.files] == [
        ["LI_0603", "LI_SOIC8"], ["LI_RES", "LI_TIMER"], ["LI_RES", "LI_CAP"],
    ]
    assert _states(scan) == {
        ("Footprints\\Chips.PcbLib", "LI_0603"): ("new", None),
        ("Footprints\\Chips.PcbLib", "LI_SOIC8"): ("new", None),
        ("Symbols\\Passives.SchLib", "LI_RES"): ("new", None),
        ("Symbols\\Passives.SchLib", "LI_TIMER"): ("new", None),
        ("Symbols\\Zusatz\\Extra.SchLib", "LI_RES"): ("duplicate", "Symbols\\Passives.SchLib"),
        ("Symbols\\Zusatz\\Extra.SchLib", "LI_CAP"): ("taken", GENERATED_LIBRARY),
    }
    comps = {(f.rel, c.name): c for f in scan.files for c in f.components}
    timer = comps[("Symbols\\Passives.SchLib", "LI_TIMER")]
    assert (timer.count, timer.description, timer.has_3d) == (8, "Precision timer, SOIC-8", None)
    assert comps[("Symbols\\Passives.SchLib", "LI_RES")].count == 2
    assert comps[("Footprints\\Chips.PcbLib", "LI_SOIC8")].count == 8
    assert comps[("Footprints\\Chips.PcbLib", "LI_0603")].description == chip_0603().description
    assert (scan.symbols, scan.footprints, scan.new, scan.taken, scan.duplicates, scan.imported) == (4, 2, 4, 1, 1, 0)
    assert scan.notes == [
        "Vendor.DbLib: Datenbankbibliothek (Verbindung: „Download from https://portal.altiumlibrary.com/“) – ihre "
        "Bauteildaten liegen in der Datenbank und werden nicht übernommen; importiert werden die Symbole und "
        "Footprints der Bibliotheksdateien."
    ]
    assert scan.message.startswith("3 Bibliotheken gelesen: 4 Symbole, 2 Footprints (") and "doppelt" in scan.message
    assert libimport.get_scan(scan.id) is scan  # kept for the import
    assert not (workspace.symbols_dir / "Import").exists()  # a scan only reads


@rust
def test_import_copies_registers_and_reports_conflicts(workspace: Workspace, sources: Sources) -> None:
    _register_symbol("LI_CAP", GENERATED_LIBRARY)
    out = libimport.run_import(LibraryImportOptions(scan_id=libimport.scan(str(sources.folder)).id))
    assert (out["copied"], out["unchanged"], out["symbols"], out["footprints"]) == (2, 0, 2, 2)
    assert out["libraries"] == [CHIPS_TARGET, PASSIVES_TARGET]
    assert out["errors"] == [] and out["conversion"] is None
    # copied unchanged (lossless); a file without importable names is not copied
    assert _abs(workspace, CHIPS_TARGET).read_bytes() == sources.chips
    assert _abs(workspace, PASSIVES_TARGET).read_bytes() == sources.passives
    assert not _abs(workspace, EXTRA_TARGET).exists()
    assert out["skipped"] == [
        {"rel": "Symbols\\Zusatz\\Extra.SchLib", "reason": "Keine übernehmbaren Namen (alle schon vergeben)."}
    ]
    conflicts = {c["name"]: c for c in out["conflicts"]}
    assert set(conflicts) == {"LI_RES", "LI_CAP"}
    assert conflicts["LI_CAP"] == {"kind": "symbol", "name": "LI_CAP", "library": EXTRA_TARGET,
                                   "registered_library": GENERATED_LIBRARY, "reason": "Name schon registriert"}
    duplicate = conflicts["LI_RES"]  # its reason: see test_duplicate_name_conflict_says_it_is_a_duplicate
    assert (duplicate["kind"], duplicate["library"], duplicate["registered_library"]) == (
        "symbol", EXTRA_TARGET, PASSIVES_TARGET)
    assert out["message"].startswith("Bibliotheksimport fertig: 2 Symbole und 2 Footprints aus 2 Dateien (")
    # registered as "imported", with the geometry read back
    timer = registry.get_symbol("LI_TIMER")
    assert timer is not None
    assert (timer.source, timer.library, timer.status, timer.pin_count) == ("imported", PASSIVES_TARGET, "ok", 8)
    assert timer.spec is not None and timer.spec.parameters["Manufacturer Part Number"] == "NE555DR"
    assert [link.name for link in timer.spec.footprints] == ["LI_SOIC8"]
    soic = registry.get_footprint("LI_SOIC8")
    assert soic is not None and (soic.source, soic.library, soic.pad_count) == ("imported", CHIPS_TARGET, 8)
    assert soic.spec is not None and len(soic.spec.pads) == 8
    assert {r.name for r in registry.list_symbols(source="imported", with_usage=False)} == {"LI_RES", "LI_TIMER"}
    assert {r.name for r in registry.list_footprints(source="imported", with_usage=False)} == {"LI_0603", "LI_SOIC8"}
    cap = registry.get_symbol("LI_CAP")
    assert cap is not None and (cap.source, cap.library) == ("generated", GENERATED_LIBRARY)  # untouched

    # scanned again: the copies are known, the names imported
    again = libimport.scan(str(sources.folder))
    assert [f.exists for f in again.files] == ["same", "same", "no"]
    assert _states(again) == {
        ("Footprints\\Chips.PcbLib", "LI_0603"): ("imported", CHIPS_TARGET),
        ("Footprints\\Chips.PcbLib", "LI_SOIC8"): ("imported", CHIPS_TARGET),
        ("Symbols\\Passives.SchLib", "LI_RES"): ("imported", PASSIVES_TARGET),
        ("Symbols\\Passives.SchLib", "LI_TIMER"): ("imported", PASSIVES_TARGET),
        ("Symbols\\Zusatz\\Extra.SchLib", "LI_RES"): ("taken", PASSIVES_TARGET),
        ("Symbols\\Zusatz\\Extra.SchLib", "LI_CAP"): ("taken", GENERATED_LIBRARY),
    }
    assert (again.new, again.imported, again.taken, again.duplicates) == (0, 4, 2, 0)
    assert again.message == (
        "3 Bibliotheken gelesen: 4 Symbole, 2 Footprints (4 schon importiert, 2 Namen schon vergeben).")
    # imported again: nothing copied, nothing rewritten
    stamps = {rel: _abs(workspace, rel).stat().st_mtime_ns for rel in (CHIPS_TARGET, PASSIVES_TARGET)}
    second = libimport.run_import(LibraryImportOptions(scan_id=again.id))
    assert (second["copied"], second["unchanged"]) == (0, 2)
    assert second["libraries"] == [CHIPS_TARGET, PASSIVES_TARGET] and second["errors"] == []
    assert len(second["conflicts"]) == 2
    assert [s["rel"] for s in second["skipped"]] == ["Symbols\\Zusatz\\Extra.SchLib"]
    assert "aus 2 Dateien (alle unverändert" in second["message"]
    assert {rel: _abs(workspace, rel).stat().st_mtime_ns for rel in stamps} == stamps
    assert len(registry.list_symbols(source="imported", with_usage=False)) == 2


@rust
def test_changed_source_is_replaced_only_on_request(workspace: Workspace, sources: Sources, tmp_path: Path) -> None:
    folder = tmp_path / "Hersteller"
    folder.mkdir()
    library = folder / "Passives.SchLib"
    library.write_bytes(sources.passives)
    target = "Symbols\\Import\\Hersteller\\Passives.SchLib"
    first = libimport.run_import(LibraryImportOptions(scan_id=libimport.scan(str(folder)).id))
    assert first["copied"] == 1 and first["libraries"] == [target]
    library.write_bytes(sources.passives_v2)  # the vendor updated the library
    scan = libimport.scan(str(folder))
    entry = scan.files[0]
    assert (entry.rel, entry.target, entry.exists) == ("Passives.SchLib", target, "different")
    assert [c.state for c in entry.components] == ["imported", "imported"]
    kept = libimport.run_import(LibraryImportOptions(scan_id=scan.id))
    assert (kept["copied"], kept["unchanged"], kept["libraries"]) == (0, 0, [])
    assert kept["skipped"] == [
        {"rel": "Passives.SchLib", "reason": "Schon importiert und seither geändert – nicht überschrieben."}
    ]
    assert kept["message"] == "Bibliotheksimport: nichts übernommen."
    assert _abs(workspace, target).read_bytes() == sources.passives
    replaced = libimport.run_import(LibraryImportOptions(scan_id=scan.id, replace=True))
    assert (replaced["copied"], replaced["symbols"], replaced["libraries"]) == (1, 2, [target])
    assert replaced["skipped"] == [] and replaced["conflicts"] == []
    assert _abs(workspace, target).read_bytes() == sources.passives_v2
    res = registry.get_symbol("LI_RES")
    assert res is not None and res.spec is not None and res.spec.description == "Widerstand, Version 2"


@rust
def test_import_of_selected_files_into_a_named_target(
    workspace: Workspace, sources: Sources, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "Quelle"
    _write_files(folder, {
        "Footprints/Chips.PcbLib": sources.chips,
        "Passives.SchLib": sources.passives,
        "Broken.SchLib": b"this is no library",
    })
    calls: list[housestyle.ConformSelection] = []
    converted = "Hausstil angewendet: 2 Bauteile in 1 Bibliothek."

    def fake_apply(selection: housestyle.ConformSelection, rules: Any, *, ctx: Any = None) -> dict[str, Any]:
        calls.append(selection)
        return {"components": 2, "libraries": list(selection.libraries or []), "skipped": [], "errors": [],
                "undo": "undo.json", "report": {"not": "returned"}, "message": converted}

    monkeypatch.setattr(housestyle, "apply", fake_apply)  # the batch edit itself has its own tests
    scan = libimport.scan(str(folder))
    assert [f.rel for f in scan.files] == ["Broken.SchLib", "Passives.SchLib", "Footprints\\Chips.PcbLib"]
    broken = scan.files[0]
    assert broken.problem is not None and broken.problem.startswith("Nicht lesbar: ") and broken.components == []
    options = LibraryImportOptions(scan_id=scan.id, files=["footprints/chips.pcblib", "Broken.SchLib"],
                                   target='Hersteller: "ACME"?', convert=True)
    out = libimport.run_import(options)
    target = 'Footprints\\Import\\Hersteller_ _ACME__\\Footprints\\Chips.PcbLib'
    assert out["libraries"] == [target] and (out["copied"], out["symbols"], out["footprints"]) == (1, 0, 2)
    assert out["skipped"] == [{"rel": "Broken.SchLib", "reason": broken.problem}]
    assert _abs(workspace, target).read_bytes() == sources.chips
    assert not (workspace.symbols_dir / "Import").exists()  # Passives.SchLib was not chosen
    assert registry.get_symbol("LI_RES") is None and registry.get_footprint("LI_0603") is not None
    # the house style follows for the imported libraries only
    assert [(c.sources, c.libraries) for c in calls] == [(["imported"], [target])]
    assert out["conversion"] == {"components": 2, "libraries": [target], "skipped": [], "errors": [],
                                 "undo": "undo.json", "message": converted}
    assert out["message"] == f"Bibliotheksimport fertig: 0 Symbole und 2 Footprints aus 1 Datei. {converted}"
    # a source file that vanished after the scan is skipped (and nothing is converted)
    (folder / "Passives.SchLib").unlink()
    gone = libimport.run_import(LibraryImportOptions(scan_id=scan.id, files=["Passives.SchLib"], convert=True))
    assert gone["skipped"] == [{"rel": "Passives.SchLib", "reason": "Datei nicht mehr vorhanden."}]
    assert gone["libraries"] == [] and gone["conversion"] is None and len(calls) == 1


@rust
def test_zip_and_intlib_sources(workspace: Workspace, sources: Sources, tmp_path: Path, cache_dir: Path) -> None:
    archive = _zip(tmp_path / "ACME Download.zip", {
        "ACME/Symbols/Passives.SchLib": sources.passives,
        "ACME/Footprints/Chips.PcbLib": sources.chips,
        "ACME/Datasheet.pdf": b"%PDF-1.4",
    })
    scan = libimport.scan(str(archive))
    assert scan.name == "ACME Download" and scan.notes == []
    assert [(f.rel, f.kind) for f in scan.files] == [
        ("ACME\\Symbols\\Passives.SchLib", "schlib"),
        ("ACME\\Footprints\\Chips.PcbLib", "pcblib"),
    ]
    assert [f.target for f in scan.files] == [
        "Symbols\\Import\\ACME Download\\ACME\\Symbols\\Passives.SchLib",
        "Footprints\\Import\\ACME Download\\ACME\\Footprints\\Chips.PcbLib",
    ]
    assert all(is_inside(f.path, cache_dir) for f in scan.files)
    assert [[c.name for c in f.components] for f in scan.files] == [["LI_RES", "LI_TIMER"], ["LI_0603", "LI_SOIC8"]]
    assert (scan.symbols, scan.footprints, scan.new) == (2, 2, 4)

    intlib = build_compound(tmp_path / "Murata.IntLib", {
        "SchLib/0.schlib": _packed(sources.passives),
        "PCBLib/0.pcblib": _packed(sources.chips),
    })
    scan = libimport.scan(str(intlib))
    assert scan.name == "Murata"
    assert [(f.rel, f.kind, f.target) for f in scan.files] == [
        ("Murata.IntLib\\Murata.PcbLib", "pcblib", "Footprints\\Import\\Murata\\Murata.PcbLib"),
        ("Murata.IntLib\\Murata.SchLib", "schlib", "Symbols\\Import\\Murata\\Murata.SchLib"),
    ]
    assert [[c.name for c in f.components] for f in scan.files] == [["LI_0603", "LI_SOIC8"], ["LI_RES", "LI_TIMER"]]
    out = libimport.run_import(LibraryImportOptions(scan_id=scan.id))
    assert out["copied"] == 2 and out["libraries"] == ["Footprints\\Import\\Murata\\Murata.PcbLib",
                                                       "Symbols\\Import\\Murata\\Murata.SchLib"]
    assert _abs(workspace, "Symbols\\Import\\Murata\\Murata.SchLib").read_bytes() == sources.passives
    timer = registry.get_symbol("LI_TIMER")
    assert timer is not None and timer.library == "Symbols\\Import\\Murata\\Murata.SchLib"

    # an IntLib in a folder keeps the folder; an unreadable one becomes a note
    folder = tmp_path / "Gemischt"
    (folder / "Integriert").mkdir(parents=True)
    shutil.copyfile(intlib, folder / "Integriert" / "Murata.IntLib")
    (folder / "Broken.IntLib").write_bytes(b"no compound file")
    scan = libimport.scan(str(folder))
    assert [(f.rel, f.target) for f in scan.files] == [
        ("Integriert\\Murata.IntLib\\Murata.PcbLib", "Footprints\\Import\\Gemischt\\Integriert\\Murata.PcbLib"),
        ("Integriert\\Murata.IntLib\\Murata.SchLib", "Symbols\\Import\\Gemischt\\Integriert\\Murata.SchLib"),
    ]
    assert len(scan.notes) == 1 and scan.notes[0].startswith("Broken.IntLib ist keine lesbare integrierte Bibliothek")
    # the names came from the IntLib before: another target means "taken"
    assert {c.state for f in scan.files for c in f.components} == {"taken"} and scan.taken == 4


@rust
def test_duplicate_name_conflict_says_it_is_a_duplicate(workspace: Workspace, sources: Sources, tmp_path: Path) -> None:
    folder = tmp_path / "Doppelt"
    _write_files(folder, {"A.SchLib": sources.passives, "B.SchLib": sources.extra})  # LI_RES in both
    scan = libimport.scan(str(folder))
    assert _states(scan)[("B.SchLib", "LI_RES")] == ("duplicate", "A.SchLib")
    out = libimport.run_import(LibraryImportOptions(scan_id=scan.id))
    assert out["copied"] == 2 and [c["name"] for c in out["conflicts"]] == ["LI_RES"]
    conflict = out["conflicts"][0]
    assert (conflict["library"], conflict["registered_library"]) == (
        "Symbols\\Import\\Doppelt\\B.SchLib", "Symbols\\Import\\Doppelt\\A.SchLib")
    assert conflict["reason"] == "Name doppelt in der Quelle"


@rust
def test_import_of_a_library_with_a_long_file_name(workspace: Workspace, sources: Sources, tmp_path: Path) -> None:
    folder = tmp_path / "Lang"
    _write_files(folder, {LONG_FILE_NAME: sources.passives})
    out = libimport.run_import(LibraryImportOptions(scan_id=libimport.scan(str(folder)).id))
    assert out["copied"] == 1 and out["errors"] == []
    assert registry.get_footprint("LI_TIMER") is None
    timer = registry.get_symbol("LI_TIMER")
    assert timer is not None and timer.spec is not None and PureWindowsPath(timer.library).suffix == ".SchLib"


@rust
def test_parts_table_of_an_import(workspace: Workspace, sources: Sources) -> None:
    scan = libimport.scan(str(sources.folder))
    chosen = ["Footprints\\Chips.PcbLib", "Symbols\\Passives.SchLib"]
    assert libimport.run_import(LibraryImportOptions(scan_id=scan.id, files=chosen))["copied"] == 2
    data, count = libimport.parts_table(libraries=[PASSIVES_TARGET])
    header, *rows = _csv_rows(data)
    assert count == len(rows) == 2  # one row per imported symbol
    assert header == ["Part Number", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path", "Comment",
                      "Description", "Manufacturer", "Manufacturer Part Number", "Supply"]
    assert rows == [
        ["LI_RES", "LI_RES", PASSIVES_TARGET, "", "", "", "Widerstand, generisch (IEC)", "", "", ""],
        ["NE555DR", "LI_TIMER", PASSIVES_TARGET, "LI_SOIC8", CHIPS_TARGET, "NE555DR", "Precision timer, SOIC-8",
         "Texas Instruments", "NE555DR", "'+5V"],
    ]
    with pytest.raises(ImportError_) as info:
        libimport.parts_table(libraries=[CHIPS_TARGET])
    assert info.value.status == 400


@rust
def test_api_scan_preview_run_and_parts_table(
    client: TestClient, workspace: Workspace, sources: Sources, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    monkeypatch.setattr(spreadsheet, "_upload_dir", lambda: uploads)
    resp = client.post("/api/library-import/scan", json={"path": f'"{sources.folder}"'})  # quoted as Explorer copies it
    assert resp.status_code == 200, resp.text
    assert resp.json()["job"]["kind"] == "library-import.scan"
    snap = _wait_job(client, resp.json()["job"])
    assert snap["status"] == "done", snap
    summary = snap["result"]
    scan_id = summary.pop("id")
    assert summary == {
        "source": str(sources.folder), "name": "Vendor Libs", "files": 3, "symbols": 4, "footprints": 2, "new": 5,
        "taken": 0, "duplicates": 1, "imported": 0, "notes": [libimport._dblib_note(sources.folder / "Vendor.DbLib")],
        "message": "3 Bibliotheken gelesen: 4 Symbole, 2 Footprints (1 doppelt).",
    }
    assert snap["message"] == summary["message"]
    full = client.get(f"/api/library-import/scans/{scan_id}").json()
    assert [f["rel"] for f in full["files"]] == ["Footprints\\Chips.PcbLib", "Symbols\\Passives.SchLib",
                                                 "Symbols\\Zusatz\\Extra.SchLib"]
    assert [c["state"] for c in full["files"][2]["components"]] == ["duplicate", "new"]
    # previews of source components
    params = {"scan_id": scan_id, "rel": "Symbols\\Passives.SchLib", "name": "LI_TIMER"}
    svg = client.get("/api/library-import/preview", params=params)
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert svg.text.startswith("<svg")
    footprint = client.get("/api/library-import/preview", params={**params, "rel": "footprints\\chips.pcblib",
                                                                   "name": "LI_SOIC8", "theme": "light"})
    assert footprint.status_code == 200 and footprint.text.startswith("<svg")
    assert client.get("/api/library-import/preview", params={**params, "name": "NOPE"}).status_code == 404
    assert client.get("/api/library-import/preview", params={**params, "rel": "Fehlt.SchLib"}).status_code == 404
    # the import job
    resp = client.post("/api/library-import/run", json={"scan_id": scan_id, "files": ["Symbols\\Passives.SchLib",
                                                                                     "Footprints\\Chips.PcbLib"]})
    assert resp.status_code == 200 and resp.json()["job"]["kind"] == "libraries.import"
    snap = _wait_job(client, resp.json()["job"])
    assert snap["status"] == "done", snap
    result = snap["result"]
    assert (result["copied"], result["symbols"], result["footprints"]) == (2, 2, 2)
    assert result["libraries"] == [CHIPS_TARGET, PASSIVES_TARGET] and snap["message"] == result["message"]
    # the parts table continues in the spreadsheet import
    resp = client.post("/api/library-import/parts-table", json={"libraries": [PASSIVES_TARGET]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == 2
    preview = client.post(f"/api/import/preview/{body['token']}", json={})
    assert preview.status_code == 200, preview.text
    assert preview.json()["row_count"] == 2 and preview.json()["rows"][1][:2] == ["NE555DR", "LI_TIMER"]
    # a source the import cannot read fails the scan job with the German reason
    text = tmp_path / "Liste.txt"
    text.write_text("x", encoding="utf-8")
    snap = _wait_job(client, client.post("/api/library-import/scan", json={"path": str(text)}).json()["job"])
    assert snap["status"] == "failed" and "bitte einen Ordner, eine .SchLib" in (snap["error"] or "")


def test_parts_table_parameters_never_overwrite_the_fixed_columns(workspace: Workspace) -> None:
    registry.upsert_symbols([
        _symbol_record("FIX_A", LIB_A, parameters={"Library Ref": "anders", "Description": "aus Parameter",
                                                   "Part Number": "PN-1", "Footprint Path": "x"}),
        _symbol_record("FIX_B", LIB_A, description="aus dem Symbol", parameters={"description": "Parameter"}),
    ])
    header, *rows = _csv_rows(libimport.parts_table(libraries=[LIB_A])[0])
    table = {row[1]: dict(zip(header, row, strict=True)) for row in rows}
    assert header == ["Part Number", "Library Ref", "Library Path", "Description"]  # no parameter column duplicates
    assert table["FIX_A"] == {"Part Number": "PN-1", "Library Ref": "FIX_A", "Library Path": LIB_A,
                              "Description": "aus Parameter"}  # an empty fixed column takes the parameter
    assert table["FIX_B"]["Description"] == "aus dem Symbol"


@rust
def test_replaced_library_unregisters_components_it_no_longer_holds(
    workspace: Workspace, sources: Sources, tmp_path: Path
) -> None:
    folder = tmp_path / "Hersteller"
    folder.mkdir()
    library = folder / "Lib.SchLib"
    library.write_bytes(sources.extra)  # LI_RES, LI_CAP
    target = r"Symbols\Import\Hersteller\Lib.SchLib"
    first = libimport.run_import(LibraryImportOptions(scan_id=libimport.scan(str(folder)).id))
    assert first["symbols"] == 2 and registry.get_symbol("LI_CAP") is not None
    library.write_bytes(sources.passives)  # the new version: LI_RES, LI_TIMER – LI_CAP is gone
    replaced = libimport.run_import(LibraryImportOptions(scan_id=libimport.scan(str(folder)).id, replace=True))
    assert replaced["removed"] == [{"kind": "symbol", "name": "LI_CAP", "library": target}]
    assert registry.get_symbol("LI_CAP") is None
    assert {r.name for r in registry.list_symbols(source="imported", with_usage=False)} == {"LI_RES", "LI_TIMER"}
    assert "1 nicht mehr enthaltener Name abgemeldet" in replaced["message"]


@rust
def test_scan_for_another_target_folder(workspace: Workspace, sources: Sources, tmp_path: Path,
                                        client: TestClient) -> None:
    folder = tmp_path / "Hersteller"
    _write_files(folder, {"Passives.SchLib": sources.passives})
    scan = libimport.scan(str(folder))
    libimport.run_import(LibraryImportOptions(scan_id=scan.id))
    again = libimport.scan(str(folder))
    assert {c.state for c in again.files[0].components} == {"imported"} and again.files[0].exists == "same"
    # another folder: the names are registered from "Hersteller" – taken there, nothing exists yet
    other = libimport.scan_for_target(again.id, "Anderer Ordner")
    entry = other.files[0]
    assert entry.target == r"Symbols\Import\Anderer Ordner\Passives.SchLib" and entry.exists == "no"
    assert {c.state for c in entry.components} == {"taken"} and other.taken == len(entry.components)
    assert {c.registered_library for c in entry.components} == {r"Symbols\Import\Hersteller\Passives.SchLib"}
    # the stored scan is untouched; the proposal (or an empty target) gives it back
    assert libimport.get_scan(again.id).files[0].target == r"Symbols\Import\Hersteller\Passives.SchLib"
    assert libimport.scan_for_target(again.id, "  ") is libimport.get_scan(again.id)
    body = client.get(f"/api/library-import/scans/{again.id}", params={"target": "Anderer Ordner"}).json()
    assert body["files"][0]["target"] == r"Symbols\Import\Anderer Ordner\Passives.SchLib" and body["taken"] == 2


@rust
def test_stored_scan_follows_the_import(workspace: Workspace, sources: Sources, tmp_path: Path) -> None:
    folder = tmp_path / "Hersteller"
    _write_files(folder, {"Passives.SchLib": sources.passives})
    scan = libimport.scan(str(folder))
    assert {c.state for c in scan.files[0].components} == {"new"} and scan.files[0].exists == "no"
    libimport.run_import(LibraryImportOptions(scan_id=scan.id))
    stored = libimport.get_scan(scan.id)  # the page shows it again: up to date without a new scan
    assert {c.state for c in stored.files[0].components} == {"imported"} and stored.files[0].exists == "same"
    assert stored.imported == len(stored.files[0].components) and stored.new == 0
