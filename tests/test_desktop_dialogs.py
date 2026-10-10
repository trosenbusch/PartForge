"""File dialogs of the desktop window (``partforge.desktop``): every file filter of the web UI reaches pywebview in a
form it accepts – one filter it rejects (``ValueError``) made the whole "Durchsuchen …" button look dead."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from webview.util import parse_file_type

from partforge import config, desktop

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"
ALL_FILES_DE = "Alle Dateien (*.*)"


@pytest.fixture
def german_settings():
    config.save_settings(config.load_settings().model_copy(update={"language": "de"}))


def frontend_filters() -> list[str]:
    """Every file filter literal the frontend passes to a file dialog (``fileFilters={[…]}``, ``…_FILE_FILTERS``)."""
    found: list[str] = []
    for file in FRONTEND.rglob("*.ts*"):
        text = file.read_text(encoding="utf-8")
        for block in re.findall(r"fileFilters=\{\[(.*?)\]\}|_FILE_FILTERS\s*=\s*\[(.*?)\]", text, re.DOTALL):
            for _quote, literal in re.findall(r"(['\"])(.*?)\1", "".join(block)):
                found.append(literal)
    return found


def test_the_frontend_uses_file_filters():
    filters = frontend_filters()
    assert "Programme (*.exe)" in filters
    assert any(f.startswith("Altium-Bibliotheken") for f in filters)  # the import page's library file dialog


@pytest.mark.parametrize("raw", sorted(set(frontend_filters())))
@pytest.mark.parametrize("language", ["en", "de"])
def test_every_frontend_filter_is_accepted_by_pywebview(raw: str, language: str):
    types = desktop.file_types([raw], language=language)
    assert len(types) == 2 or raw in {desktop.ALL_FILES, ALL_FILES_DE}, types
    for entry in types:
        parse_file_type(entry)  # raises ValueError for anything pywebview would reject


def test_descriptions_and_patterns_are_repaired(german_settings):
    assert desktop.file_types(["Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)"]) == (
        "Altium Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)", ALL_FILES_DE)
    assert desktop.file_types(["Altium Designer (X2.EXE)"]) == ("Altium Designer (*.EXE)", ALL_FILES_DE)
    assert desktop.file_types(["Lagensätze/Vorlagen (*.layerset; *.layerset)"]) == (
        "Lagensätze Vorlagen (*.layerset)", ALL_FILES_DE)


def test_unusable_filters_are_left_out_and_all_files_comes_last_once(german_settings):
    assert desktop.file_types(None) == (ALL_FILES_DE,)
    assert desktop.file_types(["kein Filter", "Leer ()", "(*.txt)", desktop.ALL_FILES, ALL_FILES_DE, "Text (*.txt)"]) == (
        "Dateien (*.txt)", "Text (*.txt)", ALL_FILES_DE)


class _Window:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.localization: dict[str, str] = {}

    def create_file_dialog(self, dialog_type: Any, **kwargs: Any) -> Any:
        self.calls.append({"type": dialog_type, **kwargs})
        for entry in kwargs.get("file_types", ()):
            parse_file_type(entry)  # what pywebview's window does first
        return ("C:\\Quelle\\ACME.IntLib",)


def test_pick_file_hands_valid_filters_to_the_dialog(monkeypatch: pytest.MonkeyPatch, german_settings):
    window = _Window()
    monkeypatch.setattr(desktop.DesktopApi, "_window", lambda self: window)
    picked = desktop.DesktopApi().pick_file(None, ["Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)"])
    assert picked == "C:\\Quelle\\ACME.IntLib"
    assert window.calls[0]["file_types"] == (
        "Altium Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.LibPkg;*.zip)", ALL_FILES_DE)


def test_a_failing_dialog_is_logged(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, german_settings):
    class Broken(_Window):
        def create_file_dialog(self, dialog_type: Any, **kwargs: Any) -> Any:
            raise RuntimeError("kein Dialog")

    monkeypatch.setattr(desktop.DesktopApi, "_window", lambda self: Broken())
    with pytest.raises(RuntimeError):
        desktop.DesktopApi().pick_file(None, None)
    assert "Dateidialog fehlgeschlagen" in caplog.text


def test_new_settings_use_english_native_labels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("PARTFORGE_HOME", str(tmp_path))
    assert config.load_settings(reload=True).language == "en"
    assert desktop.file_types(["(*.txt)", ALL_FILES_DE, desktop.ALL_FILES]) == (
        "Files (*.txt)", "All files (*.*)")
    assert desktop.webview_localization()["global.cancel"] == "Cancel"


def test_open_window_uses_new_language_on_next_dialog(monkeypatch: pytest.MonkeyPatch):
    import webview

    window = _Window()
    monkeypatch.setattr(webview, "windows", [window])
    api = desktop.DesktopApi()
    config.save_settings(config.load_settings().model_copy(update={"language": "de"}))
    api.pick_file()
    assert window.calls[-1]["file_types"] == (ALL_FILES_DE,)
    assert window.localization["global.cancel"] == "Abbrechen"
    localization = window.localization

    config.save_settings(config.load_settings().model_copy(update={"language": "en"}))
    api.pick_file()
    assert window.calls[-1]["file_types"] == (desktop.ALL_FILES,)
    assert window.localization is localization  # native backends retain the dictionary reference
    assert window.localization["global.cancel"] == "Cancel"


@pytest.mark.parametrize(("language", "message"), [("en", "Path not found:"), ("de", "Pfad nicht gefunden:")])
@pytest.mark.parametrize("method", ["open_path", "reveal_path"])
def test_missing_path_uses_selected_language(language: str, message: str, method: str, tmp_path: Path):
    config.save_settings(config.load_settings().model_copy(update={"language": language}))
    path = tmp_path / "not-present.txt"
    with pytest.raises(FileNotFoundError, match=re.escape(f"{message} {path}")):
        getattr(desktop.DesktopApi(), method)(str(path))


@pytest.mark.parametrize(("language", "cancel"), [("en", "Cancel"), ("de", "Abbrechen")])
def test_window_and_webview_start_receive_selected_language(
    language: str, cancel: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
):
    import webview

    from partforge import __main__ as main_mod

    calls: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(webview, "create_window", lambda *args, **kwargs: calls.update(window=kwargs))
    monkeypatch.setattr(webview, "start", lambda **kwargs: calls.update(start=kwargs))
    monkeypatch.setattr(webview, "settings", {})
    monkeypatch.setattr(main_mod, "_webview_storage", lambda: tmp_path)
    server = SimpleNamespace(started=True, should_exit=False, run=lambda **kwargs: None)
    args = SimpleNamespace(server_only=False, dev=False, browser=False)

    assert main_mod._serve(args, None, server, None, "http://127.0.0.1:48765/", config.AppSettings(language=language)) == 0
    assert calls["window"]["localization"]["global.cancel"] == cancel
    assert calls["start"]["localization"]["global.cancel"] == cancel
    assert server.should_exit
