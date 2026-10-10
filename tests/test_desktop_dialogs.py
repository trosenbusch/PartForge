"""File dialogs of the desktop window (``partforge.desktop``): every file filter of the web UI reaches pywebview in a
form it accepts – one filter it rejects (``ValueError``) made the whole "Durchsuchen …" button look dead."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from webview.util import parse_file_type

from partforge import desktop

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"


def frontend_filters() -> list[str]:
    """Every file filter literal the frontend passes to a file dialog (``fileFilters={[…]}``, ``…_FILE_FILTERS``)."""
    found: list[str] = []
    for file in FRONTEND.rglob("*.ts*"):
        text = file.read_text(encoding="utf-8")
        for block in re.findall(r"fileFilters=\{\[(.*?)\]\}|_FILE_FILTERS\s*=\s*\[(.*?)\]", text, re.DOTALL):
            for literal in re.findall(r"'([^']*)'", "".join(block)):
                found.append(literal)
    return found


def test_the_frontend_uses_file_filters():
    filters = frontend_filters()
    assert "Programme (*.exe)" in filters
    assert any(f.startswith("Altium-Bibliotheken") for f in filters)  # the import page's library file dialog


@pytest.mark.parametrize("raw", sorted(set(frontend_filters())))
def test_every_frontend_filter_is_accepted_by_pywebview(raw: str):
    types = desktop.file_types([raw])
    assert len(types) == 2 or raw == desktop.ALL_FILES, types  # the filter itself is kept, plus "Alle Dateien"
    for entry in types:
        parse_file_type(entry)  # raises ValueError for anything pywebview would reject


def test_descriptions_and_patterns_are_repaired():
    assert desktop.file_types(["Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)"]) == (
        "Altium Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)", desktop.ALL_FILES)
    assert desktop.file_types(["Altium Designer (X2.EXE)"]) == ("Altium Designer (*.EXE)", desktop.ALL_FILES)
    assert desktop.file_types(["Lagensätze/Vorlagen (*.layerset; *.layerset)"]) == (
        "Lagensätze Vorlagen (*.layerset)", desktop.ALL_FILES)


def test_unusable_filters_are_left_out_and_all_files_comes_last_once():
    assert desktop.file_types(None) == (desktop.ALL_FILES,)
    assert desktop.file_types(["kein Filter", "Leer ()", "(*.txt)", desktop.ALL_FILES, "Text (*.txt)"]) == (
        "Dateien (*.txt)", "Text (*.txt)", desktop.ALL_FILES)


class _Window:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create_file_dialog(self, dialog_type: Any, **kwargs: Any) -> Any:
        self.calls.append({"type": dialog_type, **kwargs})
        for entry in kwargs.get("file_types", ()):
            parse_file_type(entry)  # what pywebview's window does first
        return ("C:\\Quelle\\ACME.IntLib",)


def test_pick_file_hands_valid_filters_to_the_dialog(monkeypatch: pytest.MonkeyPatch):
    window = _Window()
    monkeypatch.setattr(desktop.DesktopApi, "_window", lambda self: window)
    picked = desktop.DesktopApi().pick_file(None, ["Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)"])
    assert picked == "C:\\Quelle\\ACME.IntLib"
    assert window.calls[0]["file_types"] == (
        "Altium Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)", desktop.ALL_FILES)


def test_a_failing_dialog_is_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    class Broken(_Window):
        def create_file_dialog(self, dialog_type: Any, **kwargs: Any) -> Any:
            raise RuntimeError("kein Dialog")

    monkeypatch.setattr(desktop.DesktopApi, "_window", lambda self: Broken())
    with pytest.raises(RuntimeError):
        desktop.DesktopApi().pick_file(None, None)
    assert "Dateidialog fehlgeschlagen" in caplog.text
