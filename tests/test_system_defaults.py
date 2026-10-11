"""Neutral defaults (F6), DbLib name collisions (F10) and DbLib-safe database paths (INT-12)."""
from __future__ import annotations

from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from partforge import config
from partforge.workspace import Workspace


def test_no_developer_paths_in_new_settings() -> None:
    settings = config.AppSettings()
    assert settings.ai.api_key_file is None
    assert "Projekte" not in str(config.default_library_parent())


def test_language_defaults_to_english(bare_client: TestClient) -> None:
    assert config.AppSettings().language == "en"
    assert bare_client.get("/api/settings").json()["settings"]["language"] == "en"


def test_old_settings_gain_english_without_losing_preferences() -> None:
    old = config.AppSettings(author="Existing user", theme="light").model_dump()
    old.pop("language")
    config.settings_path().write_text(json.dumps(old), encoding="utf-8")
    loaded = config.load_settings(reload=True)
    assert loaded.language == "en"
    assert loaded.author == "Existing user"
    assert loaded.theme == "light"
    assert not config.settings_path().with_suffix(".corrupt.json").exists()


@pytest.mark.parametrize("language", ["en", "de"])
def test_language_is_saved_and_survives_reload(bare_client: TestClient, language: str) -> None:
    settings = bare_client.get("/api/settings").json()["settings"]
    settings["language"] = language
    response = bare_client.put("/api/settings", json=settings)
    assert response.status_code == 200, response.text
    assert response.json()["settings"]["language"] == language
    assert config.load_settings(reload=True).language == language
    assert json.loads(config.settings_path().read_text(encoding="utf-8"))["language"] == language


@pytest.mark.parametrize("language", ["fr", "EN", "", None])
def test_unsupported_language_is_rejected_without_changing_settings(bare_client: TestClient, language: str | None) -> None:
    settings = bare_client.get("/api/settings").json()["settings"]
    original = settings["language"]
    settings["language"] = language
    response = bare_client.put("/api/settings", json=settings)
    assert response.status_code == 422, response.text
    assert bare_client.get("/api/settings").json()["settings"]["language"] == original


def test_configured_writer_path_is_never_replaced_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    exe = tmp_path / "altium-designer-mcp.exe"
    exe.write_bytes(b"MZ")
    monkeypatch.setenv("PARTFORGE_RUST_WRITER", str(exe))
    settings = config.AppSettings()
    assert settings.resolved_rust_writer() == str(exe)  # nothing configured: detected
    settings.altium.rust_writer_path = str(tmp_path / "falsch" / "altium-designer-mcp.exe")
    assert settings.resolved_rust_writer() is None  # configured but missing: reported, not replaced
    settings.altium.rust_writer_path = str(exe)
    assert settings.resolved_rust_writer() == str(exe)


@pytest.mark.parametrize("frozen", [False, True])
def test_writer_detection_uses_only_neutral_install_locations(monkeypatch: pytest.MonkeyPatch,
                                                            tmp_path: Path, frozen: bool) -> None:
    monkeypatch.delenv("PARTFORGE_RUST_WRITER", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(config.sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(config.sys, "executable", str(tmp_path / "PartForge" / "PartForge.exe"))
    expected = [str(tmp_path / "Programs" / "altium-designer-mcp" / "altium-designer-mcp.exe")]
    if frozen:
        expected += [str(tmp_path / "PartForge" / "altium-designer-mcp.exe"),
                     str(tmp_path / "PartForge" / "altium-designer-mcp" / "altium-designer-mcp.exe")]
    assert config.rust_writer_candidates() == expected


def test_writer_environment_override_precedes_the_user_install(monkeypatch: pytest.MonkeyPatch,
                                                             tmp_path: Path) -> None:
    installed = tmp_path / "Programs" / "altium-designer-mcp" / "altium-designer-mcp.exe"
    installed.parent.mkdir(parents=True)
    installed.write_bytes(b"MZ")
    override = tmp_path / "custom" / "altium-designer-mcp.exe"
    override.parent.mkdir()
    override.write_bytes(b"MZ")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PARTFORGE_RUST_WRITER", str(override))
    monkeypatch.setattr(config.sys, "frozen", False, raising=False)
    assert config.detect_rust_writer() == str(override)
    monkeypatch.delenv("PARTFORGE_RUST_WRITER")
    assert config.detect_rust_writer() == str(installed)


def test_settings_reload_when_the_file_changes() -> None:
    first = config.load_settings()
    other = first.model_copy(deep=True)
    other.author = "Zweites Fenster"
    path = config.settings_path()
    path.write_text(other.model_dump_json(), encoding="utf-8")  # written by another PartForge process
    assert config.load_settings().author == "Zweites Fenster"
    config.save_settings(first)
    assert config.load_settings().author == first.author


def test_defaults_endpoint_suggests_a_neutral_unique_folder(bare_client: TestClient, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("partforge.api.routes_system.default_library_parent", lambda: tmp_path / "PartForge")
    body = bare_client.get("/api/workspace/defaults").json()
    assert body["parent"] == str(tmp_path / "PartForge")
    assert body["name"] == "PartForge-Bibliothek" and body["path"] == str(tmp_path / "PartForge" / "PartForge-Bibliothek")
    assert body["dblib_file"] == "PartForge-Bibliothek.DbLib"
    (tmp_path / "PartForge" / "PartForge-Bibliothek").mkdir(parents=True)
    (tmp_path / "PartForge" / "PartForge-Bibliothek" / "x.txt").write_text("belegt")
    again = bare_client.get("/api/workspace/defaults").json()
    assert again["name"] == "PartForge-Bibliothek 2"
    named = bare_client.get("/api/workspace/defaults", params={"name": "Meine: Teile"}).json()
    assert named["name"] == "Meine Teile" and named["dblib_file"] == "Meine Teile.DbLib"


def test_second_library_gets_a_unique_dblib_name_and_a_warning(bare_client: TestClient, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("partforge.api.routes_system.default_library_parent", lambda: tmp_path / "PartForge")
    monkeypatch.setattr("partforge.altium.dblib.cached_install_states", lambda: [])  # no Altium check known
    settings = config.load_settings()
    settings.recent_workspaces = []  # libraries of other tests in this session
    config.save_settings(settings)
    first = bare_client.post("/api/workspace/create", json={"path": str(tmp_path / "A"), "with_examples": False})
    assert first.status_code == 200, first.text
    assert first.json()["warnings"] == []
    defaults = bare_client.get("/api/workspace/defaults", params={"name": "B"}).json()
    taken = {u["file_name"] for u in defaults["dblib_taken"]}
    assert "PartForge.DbLib" in taken  # library A (recent) uses the default file name
    second = bare_client.post("/api/workspace/create", json={"path": str(tmp_path / "B"), "with_examples": False})
    assert second.status_code == 200, second.text
    warnings = second.json()["warnings"]
    assert len(warnings) == 1 and "PartForge.DbLib" in warnings[0] and "Dateinamen" in warnings[0]
    third = bare_client.post("/api/workspace/create", json={
        "path": str(tmp_path / "C"), "with_examples": False, "settings": {"dblib_file": "Teile C.DbLib"}})
    assert third.status_code == 200 and third.json()["warnings"] == []
    bare_client.post("/api/workspace/close")


@pytest.mark.parametrize("folder", ["Łukasz Ω lib", "Semi;kolon", "Emoji 😀"])
def test_new_library_in_a_folder_altium_cannot_reference_is_refused(bare_client: TestClient, tmp_path: Path,
                                                                     folder: str) -> None:
    target = tmp_path / folder
    r = bare_client.post("/api/workspace/create", json={"path": str(target), "with_examples": False})
    assert r.status_code == 400, r.text
    assert "Windows-1252" in r.json()["detail"]
    assert not target.exists()  # refused before anything was created


def test_opening_such_a_library_shows_a_warning(bare_client: TestClient, tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Łukasz lib", name="Alt")  # created by an older version
    r = bare_client.post("/api/workspace/open", json={"path": str(ws.root)})
    assert r.status_code == 200, r.text
    assert any("Windows-1252" in w for w in r.json()["warnings"])
    bare_client.post("/api/workspace/close")
