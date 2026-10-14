"""Temporary copies and ``.bak`` backups of library files: every temp tag PartForge uses is recognised (a crash
leaves them behind), and same-named libraries in different folders never share one backup pool."""
from __future__ import annotations

from pathlib import Path

import pytest

from partforge.altium.libwriter import is_temp_library_file, workspace_library_files
from partforge.altium.rustwriter import library_backup_dir, library_backups, store_backup, work_copy_files
from partforge.workspace import Workspace

TAGS = ["", "hdr", "hgt", "work", "std", "undo", "import", "font", "keep"]


@pytest.mark.parametrize("tag", TAGS)
def test_every_temp_copy_is_recognised(tag: str) -> None:
    assert is_temp_library_file(f"PF_Passives.pf{tag}1a2b3c4d.SchLib")
    assert is_temp_library_file(f"Vendor.pf{tag}DEADBEEF.PcbLib")


@pytest.mark.parametrize("name", ["PF_Passives.SchLib", "X.pfwork.SchLib", "Y.pf1a2b3c4.PcbLib", "Z.pfx.SchLib",
                                  "Backup.pf1a2b3c4d.SchLib.bak"])
def test_real_libraries_and_other_files_are_not_temp_files(name: str) -> None:
    assert not is_temp_library_file(name)


def test_temp_copies_never_surface_as_libraries(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Lib", name="Test")
    real = ws.symbols_dir / "PF_ICs.SchLib"
    real.write_bytes(b"x")
    for tag in TAGS:
        (ws.symbols_dir / f"PF_ICs.pf{tag}1a2b3c4d.SchLib").write_bytes(b"x")
    assert workspace_library_files(ws) == [real]


def test_work_copy_files_lists_the_leftovers_of_every_operation(tmp_path: Path) -> None:
    lib = tmp_path / "PF_ICs.SchLib"
    leftovers = ["PF_ICs.pfwork1a2b3c4d.SchLib", "PF_ICs.pfwork1a2b3c4d.SchLib.bak", "PF_ICs.pfstd0a0b0c0d.SchLib",
                 "PF_ICs.pfimportabcdef01.SchLib", "PF_ICs.pf12345678.SchLib", "PF_ICs.pfhdr11111111.SchLib"]
    others = ["PF_ICs.SchLib", "PF_ICs_old.SchLib", "PF_ICsX.pfwork12345678.SchLib", "PF_ICs.SchLib.bak",
              "PF_IC.pfwork12345678.SchLib"]
    for name in leftovers + others:
        (tmp_path / name).write_bytes(b"x")
    assert {p.name for p in work_copy_files(lib)} == set(leftovers)
    assert work_copy_files(tmp_path / "missing" / "X.SchLib") == []


def test_backups_of_same_named_libraries_never_mix(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Lib", name="Test")
    top = ws.symbols_dir / "Resistors.SchLib"
    a = ws.symbols_dir / "Import" / "VendorA" / "Resistors.SchLib"
    b = ws.symbols_dir / "Import" / "VendorB" / "Resistors.SchLib"
    assert library_backup_dir(ws, top) == ws.backups_dir / "lib"
    assert library_backup_dir(ws, ws.footprints_dir / "PF_CHIP.PcbLib") == ws.backups_dir / "lib"
    assert library_backup_dir(ws, a) == ws.backups_dir / "lib" / "Symbols" / "Import" / "VendorA"
    assert library_backup_dir(ws, str(a).upper()) == library_backup_dir(ws, a)
    assert library_backup_dir(ws, tmp_path / "elsewhere" / "X.SchLib") == ws.backups_dir / "lib"
    for lib, content in ((a, b"A"), (b, b"B")):
        lib.parent.mkdir(parents=True, exist_ok=True)
        lib.write_bytes(content)
    for _ in range(25):
        store_backup(a, a, library_backup_dir(ws, a), keep=20)
    store_backup(b, b, library_backup_dir(ws, b), keep=20)
    assert len(library_backups(a, library_backup_dir(ws, a))) == 20
    backups_b = library_backups(b, library_backup_dir(ws, b))
    assert len(backups_b) == 1 and backups_b[0].read_bytes() == b"B"
    assert library_backups(a, library_backup_dir(ws, a))[-1].read_bytes() == b"A"
    assert library_backups(top, library_backup_dir(ws, top)) == []
