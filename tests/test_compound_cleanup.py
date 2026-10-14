"""PKG-01: a failed PcbLib patch never leaves ``<stem>.pfhdr<hex>.PcbLib`` / ``.pfhgt`` copies behind (COM objects
held by the traceback are released first), and a missing ``win32timezone`` (incomplete program package) is a clear
error – the heights are then "unreadable", which refuses a write instead of resetting them to 0."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from test_sync_support import synthetic_pcblib

from partforge.altium import compound, heights, stackup


def _temp_copies(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir() if ".pf" in p.name)


@pytest.mark.windows
def test_failed_patch_releases_com_objects_and_removes_its_copy(tmp_path, monkeypatch):
    lib = synthetic_pcblib(tmp_path / "PF_CHIP.PcbLib", heights={"RESC1608X55N": "0mil", "SOIC-8": "0mil"})
    calls = {"n": 0}
    original = compound.read_all

    def failing_read_all(stream):
        calls["n"] += 1
        if calls["n"] == 3:  # inside read_tree's EnumElements loop of the copy: an enumerator is open
            raise RuntimeError("simulierter COM-Fehler")
        return original(stream)

    monkeypatch.setattr(compound, "read_all", failing_read_all)
    with pytest.raises(RuntimeError, match="simulierter"):
        compound.replace_streams(lib, {"Library/Data": b"x"}, tag="pfhdr")
    assert _temp_copies(tmp_path) == []


@pytest.mark.windows
def test_missing_win32timezone_is_a_clear_error_and_leaves_nothing_behind(tmp_path, monkeypatch):
    lib = synthetic_pcblib(tmp_path / "PF_CHIP.PcbLib", heights={"RESC1608X55N": "21.6535mil", "SOIC-8": "0mil"})
    monkeypatch.setitem(sys.modules, "win32timezone", None)  # "No module named 'win32timezone'" (frozen build)
    with pytest.raises(heights.HeightError) as exc:
        heights.read_footprint_heights(lib)
    assert exc.value.unreadable and "win32timezone" in str(exc.value)
    warnings = heights.patch_footprint_heights(lib, {"RESC1608X55N": 1.0})
    assert warnings and "win32timezone" in warnings[0]
    stack = stackup.default_stack()
    assert stackup.patch_pcblib_layers(lib, stack)  # a warning, the library stays untouched
    assert _temp_copies(tmp_path) == []
    monkeypatch.undo()
    assert heights.read_footprint_heights(lib)["RESC1608X55N"] == pytest.approx(0.55, abs=1e-4)
