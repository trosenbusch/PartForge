"""API tests of /api/altium/* with a fake bridge (no Altium) and a real database."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_refresh_support import FakeBridge, wait_for, wait_job

from partforge import events
from partforge.altium import dblib, libwriter, refresh
from partforge.altium.bridge.core import (
    AltiumNotRunning,
    BridgeBusyError,
    BridgeCommandError,
    BridgeError,
    BridgeWedgedError,
    DbComponentResolution,
    DbLibInstallState,
)
from partforge.altium.dblib import DbLibError, remember_install_state
from partforge.altium.refresh import AltiumRefreshService
from partforge.api import routes_altium
from partforge.app import TOKEN_HEADER, create_app
from partforge.db import categories, parts
from partforge.workspace import Workspace, WorkspaceNotOpen

TOKEN = "altium-test-token"
PART = {"Manufacturer": "YAGEO", "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Description": "RES",
        "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}


@pytest.fixture(autouse=True)
def clean_install_cache():
    dblib._cache_path().unlink(missing_ok=True)
    libwriter.forget_component_names()
    yield
    dblib._cache_path().unlink(missing_ok=True)
    libwriter.forget_component_names()


class BatchFakeBridge(FakeBridge):
    """:class:`FakeBridge` with ``resolve_db_components`` – one call per Altium script run.

    Like the real script, an unknown key is not an error (``loaded=False``); a key in
    ``failing_keys`` fails the whole run (a :class:`BridgeCommandError` of the batch).
    ``on_batch(index)`` runs before each batch (e.g. to cancel the job between runs).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.batches: list[list[tuple[str, str]]] = []
        self.failing_keys: set[str] = set()
        self.on_batch = None

    def resolve_db_components(self, dblib, keys, *, timeout_s=None):
        wanted = [(str(table), str(key)) for table, key in keys]
        if self.on_batch is not None:
            self.on_batch(len(self.batches))
        self._call("resolve_db_components", dblib, tuple(wanted))
        self.batches.append(wanted)
        bad = [key for _, key in wanted if key in self.failing_keys]
        if bad:
            raise BridgeCommandError("resolve_db_components", f"Altium meldet einen Fehler bei {bad[0]}")
        return [self.resolutions.get((table, key))
                or DbComponentResolution(dblib=str(dblib), table=table, key=key, loaded=False)
                for table, key in wanted]


@pytest.fixture
def bridge() -> BatchFakeBridge:
    return BatchFakeBridge()


@pytest.fixture
def service(bridge):
    svc = AltiumRefreshService(debounce_s=0.05, bridge_factory=lambda: bridge, session_provider=lambda: None,
                               probe_install_state=True)  # fake bridge: probing is safe here
    previous = refresh.set_refresh_service(svc)
    yield svc
    refresh.set_refresh_service(previous)
    svc.stop()
    svc.wait_idle(5)


def make_client(bridge: FakeBridge, service: AltiumRefreshService) -> TestClient:
    app = create_app(token=TOKEN)
    app.dependency_overrides[routes_altium.get_bridge] = lambda: bridge
    app.dependency_overrides[routes_altium.get_refresh_service] = lambda: service
    return TestClient(app, headers={TOKEN_HEADER: TOKEN})


@pytest.fixture
def api(workspace, bridge, service):
    with make_client(bridge, service) as c:
        assert service.wait_idle(5)  # the DbLib written at start-up is announced to Altium
        bridge.calls.clear()
        yield c


@pytest.fixture
def bare_api(bridge, service):
    from partforge.workspace import set_current

    set_current(None)
    with make_client(bridge, service) as c:
        yield c


def run_job(response) -> dict:
    assert response.status_code == 200, response.text
    return wait_job(response.json()["job"]["id"])


def copy_of_dblib(workspace: Workspace, folder: Path) -> str:
    """An old copy of this library's DbLib (same database) in another folder."""
    target = folder / workspace.settings.dblib_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(workspace.dblib_path.read_bytes())
    return str(target)


def foreign_dblib(tmp_path: Path, name: str = "Andere Bibliothek") -> str:
    """The DbLib of ANOTHER library that uses the default file name too."""
    other = Workspace.create(tmp_path / name)
    other.dblib_path.write_bytes(
        "[OutputDatabaseLinkFile]\r\nVersion=1.1\r\n[DatabaseLinks]\r\nConnectionString=Provider=MSDASQL.1;"
        f'Extended Properties="DRIVER=SQLite3 ODBC Driver;Database={other.sqlite_path};NoCreat=1;"\r\n'.encode("cp1252")
    )
    return str(other.dblib_path)


def missing_drive() -> str:
    for letter in "ZYXWVUTSRQPONMLKJIHG":
        if not Path(f"{letter}:\\").exists():
            return f"{letter}:\\"
    pytest.skip("kein freier Laufwerksbuchstabe")


# --------------------------------------------------------------------------- status / DbLib


def test_status_without_workspace(bare_api, bridge):
    data = bare_api.get("/api/altium/status").json()
    assert data["workspace_open"] is False and data["dblib"] is None
    assert data["altium_running"] is True and data["altium_exe"] == bridge.x2_path
    assert {b["name"] for b in data["backends"]} == {"rust", "altium"}
    assert data["refresh"]["auto_refresh"] is True and data["refresh"]["pending"] is False
    assert data["refresh"]["manual_pending"] is False
    for url in ("/api/altium/dblib", "/api/altium/dblib/preview"):
        assert bare_api.get(url).status_code == 409
    for url in ("/api/altium/dblib/regenerate", "/api/altium/install", "/api/altium/refresh", "/api/altium/verify",
                "/api/altium/open", "/api/altium/odbc-test", "/api/altium/uninstall", "/api/altium/install-state"):
        assert bare_api.post(url).status_code == 409, url


def test_app_start_brings_the_dblib_up_to_date(workspace, bridge, service):
    assert not workspace.dblib_path.exists()
    with make_client(bridge, service):
        assert workspace.dblib_path.is_file()  # the launcher opens the library before the lifespan runs
        assert service.wait_idle(5)
    # the install state was unknown: a read-only check (nothing installed -> nothing touched, no refresh)
    assert bridge.names() == ["install_state"]
    assert dblib.cached_install_state(workspace.dblib_path).installed is False  # type: ignore[union-attr]


def test_status_with_workspace(api, bridge, workspace):
    bridge.running = False
    data = api.get("/api/altium/status").json()
    assert data["workspace_open"] is True and data["altium_running"] is False
    assert data["dblib"]["exists"] is True and data["dblib"]["up_to_date"] is True
    workspace.dblib_path.unlink()
    data = api.get("/api/altium/status").json()
    assert data["dblib"]["exists"] is False and data["dblib"]["file_name"] == "PartForge.DbLib"
    assert "missing" in {i["code"] for i in data["dblib"]["issues"]}
    bridge.last_wedge = {"kind": "never_started"}
    assert api.get("/api/altium/status").json()["bridge_wedged"] == {"kind": "never_started"}


def test_regenerate_and_status(api, workspace):
    workspace.dblib_path.unlink()
    out = api.post("/api/altium/dblib/regenerate").json()
    assert out["written"] is True and out["reason"] == "missing" and out["path"] == str(workspace.dblib_path)
    assert out["status"]["up_to_date"] and out["status"]["db_path_ok"]
    assert [i for i in out["status"]["issues"] if i["severity"] != "info"] == []
    assert out["reason_text"] == "Die DbLib fehlte und wurde neu angelegt."
    again = api.post("/api/altium/dblib/regenerate").json()
    assert again["written"] is False and again["reason"] == "up_to_date"
    assert again["reason_text"] == "Die DbLib ist aktuell – nichts zu schreiben."
    status = api.get("/api/altium/dblib").json()
    assert status["exists"] and status["enabled_tables"][0] == "Resistors"


def test_regenerate_in_folder_with_special_characters(bridge, service, tmp_path: Path):
    from partforge.db import close_database, open_database
    from partforge.workspace import set_current

    ws = Workspace.create(tmp_path / "Bib;Alt")
    open_database(ws)
    set_current(ws)
    try:
        with make_client(bridge, service) as c:
            response = c.post("/api/altium/dblib/regenerate")
            assert response.status_code == 400 and "Ordner ohne Sonderzeichen" in response.json()["detail"]
            status = c.get("/api/altium/dblib").json()
            assert "db_path_chars" in {i["code"] for i in status["issues"]} and status["exists"] is False
            assert c.get("/api/altium/dblib/preview").status_code == 400
    finally:
        close_database()
        set_current(None)
    assert not ws.dblib_path.exists()


def test_preview(api, workspace):
    workspace.dblib_path.unlink()
    data = api.get("/api/altium/dblib/preview").json()
    assert data["text"].startswith("[OutputDatabaseLinkFile]\r\nVersion=1.1\r\n") and data["current"] is None
    assert data["up_to_date"] is False and data["file_name"] == "PartForge.DbLib"
    missing = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "file"})
    assert missing.status_code == 404 and "DbLib neu erzeugen" in missing.json()["detail"]
    target = api.get("/api/altium/dblib/preview", params={"raw": "true"})  # target state without a file
    assert target.status_code == 200 and target.content == data["text"].encode("cp1252")
    api.post("/api/altium/dblib/regenerate")
    data = api.get("/api/altium/dblib/preview").json()
    assert data["current"] == data["text"] and data["up_to_date"] is True


def test_dblib_download_is_the_exact_file(api, workspace):
    """The download: exact bytes (cp1252, CRLF) of the file on disk or of the target state."""
    api.post("/api/altium/dblib/regenerate")
    on_disk = workspace.dblib_path.read_bytes()
    raw = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "file"})
    assert raw.status_code == 200 and raw.content == on_disk and b"\r\n" in raw.content
    assert raw.headers["content-type"] == "text/plain; charset=windows-1252"
    disposition = raw.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="PartForge.DbLib"')
    assert "filename*=UTF-8''PartForge.DbLib" in disposition
    assert raw.headers["cache-control"] == "no-store"
    # the file on disk differs from the target (a table disabled by hand)
    enabled, disabled = b"TableName=Fuses\r\nEnabled=True", b"TableName=Fuses\r\nEnabled=False"
    workspace.dblib_path.write_bytes(on_disk.replace(enabled, disabled))
    file_bytes = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "file"}).content
    target_bytes = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "target"}).content
    assert file_bytes == workspace.dblib_path.read_bytes() and disabled in file_bytes
    assert target_bytes == dblib.encode_dblib(dblib.build_dblib(workspace).text) and enabled in target_bytes
    assert target_bytes == api.get("/api/altium/dblib/preview", params={"raw": "true"}).content  # default: target
    assert api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "x"}).status_code == 422
    # umlauts in the DbLib name: ASCII fallback plus the UTF-8 name
    workspace.settings.dblib_file = "Bibliothek Müller.DbLib"
    api.post("/api/altium/dblib/regenerate")
    named = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": "file"})
    assert named.headers["content-disposition"] == (
        "attachment; filename=\"Bibliothek M_ller.DbLib\"; filename*=UTF-8''Bibliothek%20M%C3%BCller.DbLib"
    )


def test_preview_masks_the_postgres_password(api, workspace):
    workspace.settings.db.kind = "postgres"
    workspace.settings.db.postgres_odbc = "SERVER=db.local;DATABASE=parts;UID=altium;PWD={ge;heim}"
    dblib.ensure_dblib(workspace)
    assert b"PWD={ge;heim}" in workspace.dblib_path.read_bytes()  # Altium needs it in the file …
    data = api.get("/api/altium/dblib/preview").json()
    for text in (data["text"], data["current"]):  # … the preview never shows it
        assert "geheim" not in text and "ge;heim" not in text and "PWD=***" in text
    assert data["text"] == data["current"]
    # … the download is the file itself (an exact copy: Altium needs the password in it)
    for which in ("file", "target"):
        raw = api.get("/api/altium/dblib/preview", params={"raw": "true", "which": which}).content
        assert raw == workspace.dblib_path.read_bytes() and b"PWD={ge;heim}" in raw


def test_regenerate_triggers_refresh_when_installed(api, workspace, bridge, service):
    bridge.installed = [str(workspace.dblib_path)]
    remember_install_state(DbLibInstallState(path=str(workspace.dblib_path), file_name="PartForge.DbLib",
                                             installed=True), dblib=workspace.dblib_path)
    assert api.post("/api/altium/dblib/regenerate").json()["written"] is False  # unchanged: nothing to re-read
    assert service.wait_idle(5) and bridge.calls == []
    enabled, disabled = b"TableName=Fuses\r\nEnabled=True", b"TableName=Fuses\r\nEnabled=False"
    workspace.dblib_path.write_bytes(workspace.dblib_path.read_bytes().replace(enabled, disabled))
    out = api.post("/api/altium/dblib/regenerate").json()
    assert out["written"] is True and out["reason"] == "outdated"  # the real cause, although forced
    assert wait_for(lambda: ("refresh_dblib", ("PartForge.DbLib", True)) in bridge.calls, 5)


def test_regenerate_reasons(api, workspace):
    """Stable reason ids (and the German text) of POST /altium/dblib/regenerate."""
    original = workspace.dblib_path.read_bytes()

    def regenerate(content: bytes | None) -> dict:
        if content is not None:
            workspace.dblib_path.write_bytes(content)
        out = api.post("/api/altium/dblib/regenerate").json()
        assert out["reason_text"] in dblib.REASON_TEXTS.values()
        assert out["written"] is (out["reason"] != "up_to_date")
        return out

    moved = original.replace(str(workspace.sqlite_path).encode("cp1252"), rb"D:\Alt\PartForge.sqlite")
    out = regenerate(moved)
    assert out["reason"] == "wrong_database" and "andere Datenbank" in out["reason_text"]
    assert workspace.dblib_path.read_bytes() == original
    out = regenerate(original.replace(b"NoCreat=1;", b""))  # same database, other connection
    assert out["reason"] == "settings_changed" and "Datenbankeinstellungen" in out["reason_text"]
    out = regenerate(original.replace(b"\r\n", b"\n"))  # same content, not in Altium's format
    assert out["reason"] == "outdated" and "Altium-Format" in out["reason_text"]
    out = regenerate(original.replace(b"[DatabaseLinks]\r\n", b"[DatabaseLinks]\r\nUnbekannt=1\r\n"))
    assert out["reason"] == "forced" and "inhaltlich unverändert" in out["reason_text"]  # rewritten on request only
    assert regenerate(None)["reason"] == "up_to_date"
    workspace.dblib_path.unlink()
    assert regenerate(None)["reason"] == "missing"
    assert workspace.dblib_path.read_bytes() == original


# --------------------------------------------------------------------------- jobs


@pytest.mark.skipif(dblib.SQLITE_ODBC_DRIVER not in __import__("pyodbc").drivers(), reason="SQLite-ODBC-Treiber fehlt")
def test_odbc_test_job(api):
    snap = run_job(api.post("/api/altium/odbc-test", json={"max_rows": 100}))
    assert snap["status"] == "done" and snap["kind"] == "altium.odbc_test"
    assert snap["result"]["connected"] is True and snap["result"]["driver"] == "SQLite3 ODBC Driver"
    assert any("Verbindung hergestellt" in entry["text"] for entry in snap["log"])


def test_install_flow(api, workspace, bridge):
    workspace.dblib_path.unlink()
    snap = run_job(api.post("/api/altium/install"))
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["state"]["installed"] is True and snap["result"]["dblib_written"] is True
    assert workspace.dblib_path.is_file() and bridge.installed == [str(workspace.dblib_path)]
    assert [c for c in bridge.names()] == ["install_state", "install_library", "install_state"]
    status = api.get("/api/altium/dblib").json()
    assert status["installed_in_altium"] is True and status["install"]["resolves_to_this"] is True
    again = run_job(api.post("/api/altium/install"))
    assert again["status"] == "done" and bridge.names().count("install_library") == 1


def test_install_rereads_a_changed_dblib_when_already_installed(api, workspace, bridge):
    bridge.installed = [str(workspace.dblib_path)]
    enabled, disabled = b"TableName=Fuses\r\nEnabled=True", b"TableName=Fuses\r\nEnabled=False"
    workspace.dblib_path.write_bytes(workspace.dblib_path.read_bytes().replace(enabled, disabled))
    snap = run_job(api.post("/api/altium/install"))
    assert snap["status"] == "done" and snap["result"]["dblib_written"] is True
    assert ("refresh_dblib", ("PartForge.DbLib", True)) in bridge.calls and "install_library" not in bridge.names()
    assert enabled in workspace.dblib_path.read_bytes()


def test_install_replaces_an_old_copy_of_this_library(api, workspace, bridge, tmp_path: Path):
    old = copy_of_dblib(workspace, tmp_path / "Alter Ordner")
    bridge.installed = [old]
    snap = run_job(api.post("/api/altium/install"))
    assert snap["status"] == "failed" and "Ersetzen" in snap["error"] and old in snap["error"]
    assert "Datenbank dieser Bibliothek" in snap["error"] and bridge.installed == [old]
    status = api.get("/api/altium/dblib").json()
    assert status["install"]["duplicates"] == [old] and status["install"]["duplicate_kinds"] == {old: "same_database"}
    issue = next(i for i in status["issues"] if i["code"] == "duplicates")
    assert "nicht installiert, aber eine andere DbLib" in issue["message"] and "Ersetzen" in issue["message"]
    snap = run_job(api.post("/api/altium/install", json={"replace_others": True}))
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["removed"] == [old] and bridge.installed == [str(workspace.dblib_path)]
    names = bridge.names()
    assert names.index("refresh_dblib") < names.index("uninstall_library") < names.index("install_library")


def test_install_never_replaces_the_dblib_of_another_library(api, workspace, bridge, tmp_path: Path):
    """Regression: every library defaults to PartForge.DbLib – "Ersetzen" uninstalled another
    library's DbLib, whose placed parts then resolved to this database."""
    foreign = foreign_dblib(tmp_path)
    bridge.installed = [foreign]
    for body in (None, {"replace_others": True}):
        snap = run_job(api.post("/api/altium/install", json=body))
        assert snap["status"] == "failed" and "anderen Bibliothek" in snap["error"]
        assert "eigenen DbLib-Dateinamen" in snap["error"] and foreign in snap["error"]
    assert bridge.installed == [foreign] and "uninstall_library" not in bridge.names()
    assert "refresh_dblib" not in bridge.names()  # not even its database is touched
    status = api.get("/api/altium/dblib").json()
    issue = next(i for i in status["issues"] if i["code"] == "duplicates")
    assert "anderen Bibliothek" in issue["message"] and status["install"]["duplicate_kinds"] == {foreign: "other_database"}


def test_install_replaces_a_dead_entry_but_not_an_unreachable_one(api, workspace, bridge, tmp_path: Path):
    dead = str(tmp_path / "Verschoben" / "PartForge.DbLib")  # drive there, file gone
    bridge.installed = [dead]
    snap = run_job(api.post("/api/altium/install", json={"replace_others": True}))
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["removed"] == [dead] and bridge.installed == [str(workspace.dblib_path)]
    offline = missing_drive() + "Team\\PartForge.DbLib"  # could be another library on an offline drive
    bridge.installed = [offline, str(workspace.dblib_path)]
    snap = run_job(api.post("/api/altium/install", json={"replace_others": True}))
    assert snap["status"] == "failed" and "nicht erreichbar" in snap["error"] and "ließ sich nicht prüfen" in snap["error"]
    assert offline in bridge.installed


def test_uninstall_flow(api, workspace, bridge):
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["status"] == "done" and "nicht installiert" in snap["result"]["message"]
    run_job(api.post("/api/altium/install"))
    bridge.calls.clear()
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["status"] == "done" and snap["result"]["state"]["installed"] is False
    assert bridge.names() == ["install_state", "refresh_dblib", "uninstall_library", "install_state"]
    assert str(workspace.dblib_path) not in bridge.hidden_open  # database released before uninstalling
    assert api.get("/api/altium/dblib").json()["installed_in_altium"] is False


def test_install_state_job(api, workspace, bridge, tmp_path: Path):
    snap = run_job(api.post("/api/altium/install-state"))
    assert snap["status"] == "done" and snap["result"]["state"]["installed"] is False
    assert api.get("/api/altium/dblib").json()["installed_in_altium"] is False
    copy = copy_of_dblib(workspace, tmp_path / "Kopie")
    bridge.installed = [str(workspace.dblib_path), copy]
    snap = run_job(api.post("/api/altium/install-state"))
    assert snap["result"]["message"].startswith("Achtung: Neben dieser DbLib ist in Altium eine weitere DbLib")
    assert snap["result"]["duplicates"] == [{"path": copy, "kind": "same_database", "database": str(workspace.sqlite_path)}]
    codes = {i["code"] for i in api.get("/api/altium/dblib").json()["issues"]}
    assert "duplicates" in codes


def test_refresh_endpoint(api, workspace, bridge):
    bridge.installed = [str(workspace.dblib_path)]
    bridge.hidden_open.add(str(workspace.dblib_path))
    snap = run_job(api.post("/api/altium/refresh", json={"rebuild_index": True}))
    assert snap["status"] == "done" and snap["kind"] == "altium.refresh"
    assert snap["result"]["rebuild_index"] is True and snap["result"]["installed"] is True
    assert ("refresh_dblib", ("PartForge.DbLib", True)) in bridge.calls
    assert api.get("/api/altium/status").json()["refresh"]["refresh_count"] >= 1
    bridge.running = False
    response = api.post("/api/altium/refresh")
    assert response.status_code == 503 and "nicht gestartet" in response.json()["detail"]
    bridge.x2_path = None
    assert api.post("/api/altium/refresh").status_code == 503


@pytest.mark.parametrize("url", ["/api/altium/install", "/api/altium/uninstall", "/api/altium/verify",
                                 "/api/altium/install-state", "/api/altium/open"])
def test_bridge_jobs_need_running_altium(api, bridge, url):
    bridge.running = False
    response = api.post(url)
    assert response.status_code == 503 and "Altium" in response.json()["detail"]
    bridge.running, bridge.x2_path = True, None
    response = api.post(url)
    assert response.status_code == 503 and "X2.EXE" in response.json()["detail"]


# --------------------------------------------------------------------------- verify


def resolution(workspace, table: str, pn: str, *, loaded: bool = True, footprints: list[str] | None = None,
               pins: int = 2, ref: str = "RES") -> DbComponentResolution:
    return DbComponentResolution(dblib=str(workspace.dblib_path), table=table, key=pn, loaded=loaded,
                                 lib_reference=ref if loaded else "", symbol_ref=ref, pin_count=pins if loaded else None,
                                 footprints=footprints or [], symbol_path="C:\\Bib\\Symbols\\PF_Passives.SchLib")


@pytest.fixture
def no_reader(monkeypatch):
    """Footprint libraries are listed by (fake) Altium – independent of the Rust writer on this PC."""
    monkeypatch.setattr(routes_altium, "_library_reader", lambda ws: None)


def test_verify_job(api, workspace, bridge, no_reader):
    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    chip.write_bytes(b"x")
    bridge.set_components(chip, ["RESC1608X55N", "CAPC1608X87N"])
    lib = "Footprints\\PF_CHIP.PcbLib"
    parts.create_part("Resistors", {"Part Number": "R-OK", **PART, "Footprint Path": lib})
    parts.create_part("Resistors", {"Part Number": "R-NOSYM", **PART, "Footprint Path": lib})
    parts.create_part("Resistors", {"Part Number": "R-NOFP", **PART, "Footprint Path": "Footprints\\Fehlt.PcbLib"})
    parts.create_part("Resistors", {"Part Number": "R-PINS", **PART, "Footprint Path": lib})
    parts.create_part("Resistors", {"Part Number": "R-TYPO", **PART, "Footprint Ref": "RESC1608X55X", "Footprint Path": lib})
    from partforge.db import registry
    from partforge.db.models import SymbolRecord

    registry.upsert_symbol(SymbolRecord(name="RES", library="Symbols\\PF_Passives.SchLib", pin_count=2, status="ok"))
    bridge.resolutions = {
        ("Resistors", "R-OK"): resolution(workspace, "Resistors", "R-OK", footprints=["RESC1608X55N"]),
        ("Resistors", "R-NOSYM"): resolution(workspace, "Resistors", "R-NOSYM", loaded=False),
        ("Resistors", "R-NOFP"): resolution(workspace, "Resistors", "R-NOFP", footprints=["RESC1608X55N"]),
        ("Resistors", "R-PINS"): resolution(workspace, "Resistors", "R-PINS", footprints=["RESC1608X55N"], pins=3),
        # Altium builds the implementation from [Footprint Ref] whether or not the PcbLib contains it
        ("Resistors", "R-TYPO"): resolution(workspace, "Resistors", "R-TYPO", footprints=["RESC1608X55X"]),
    }
    snap = run_job(api.post("/api/altium/verify", json={"tables": ["resistors"], "limit": 10}))
    assert snap["status"] == "done", snap["error"]
    result = snap["result"]
    assert result["checked"] == 5 and result["total"] == 5 and result["temporarily_installed"] is True
    by_pn = {p["part_number"]: p for p in result["parts"]}
    ok = by_pn["R-OK"]
    assert ok["status"] == "ok" and ok["symbol_found"] and ok["footprint_found"] and ok["footprint"] == "RESC1608X55N"
    assert ok["footprint_checks"] == [{"column": "Footprint Ref", "footprint": "RESC1608X55N", "library": lib,
                                       "assigned": True, "library_found": True, "in_library": True}]
    assert by_pn["R-NOSYM"]["status"] == "error" and "nicht gefunden" in by_pn["R-NOSYM"]["messages"][0]
    assert by_pn["R-NOFP"]["status"] == "error" and "fehlt" in by_pn["R-NOFP"]["messages"][0]
    assert by_pn["R-PINS"]["status"] == "warning" and by_pn["R-PINS"]["expected_pins"] == 2
    typo = by_pn["R-TYPO"]  # regression: was "ok" because only the file's existence was checked
    assert typo["status"] == "error" and not typo["footprint_found"]
    assert typo["messages"] == ["Footprint „RESC1608X55X“ fehlt in „Footprints\\PF_CHIP.PcbLib“."]
    assert typo["footprint_checks"][0]["in_library"] is False and typo["footprint_checks"][0]["assigned"] is True
    assert (result["ok"], result["warnings"], result["errors"]) == (1, 1, 3)
    names = bridge.names()
    assert names[:2] == ["install_state", "install_library"] and names[-2:] == ["refresh_dblib", "uninstall_library"]
    assert names.count("list_components") == 1  # each library is read once per verification
    assert names.count("resolve_db_components") == 1 and result["altium_runs"] == 1  # one script run for 5 parts
    assert "resolve_db_component" not in names
    assert bridge.installed == []  # temporary installation removed again


def test_verify_checks_every_footprint_link(api, workspace, bridge, no_reader):
    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    alt = workspace.footprints_dir / "PF_ALT.PcbLib"
    for lib in (chip, alt):
        lib.write_bytes(b"x")
    bridge.set_components(chip, ["RESC1608X55N"])
    bridge.set_components(alt, ["RESC1608X60N"])
    parts.create_part("Resistors", {"Part Number": "R-2FP", **PART, "Footprint Path": "Footprints\\PF_CHIP.PcbLib",
                                    "Footprint Ref 2": "RESC1608X65N", "Footprint Path 2": "Footprints\\PF_ALT.PcbLib"})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-2FP"): resolution(workspace, "Resistors", "R-2FP",
                                                             footprints=["RESC1608X55N"])}
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-2FP"]}))
    part = snap["result"]["parts"][0]
    assert [c["column"] for c in part["footprint_checks"]] == ["Footprint Ref", "Footprint Ref 2"]
    second = part["footprint_checks"][1]
    assert second["library"] == "Footprints\\PF_ALT.PcbLib" and second["in_library"] is False and not second["assigned"]
    assert part["status"] == "error" and not part["footprint_found"] and part["footprint"] == "RESC1608X55N"
    assert "Footprint „RESC1608X65N“ ist dem Bauteil in Altium nicht zugeordnet." in part["messages"]
    assert "Footprint „RESC1608X65N“ fehlt in „Footprints\\PF_ALT.PcbLib“." in part["messages"]


class FakeReader:
    """Rust-reader stand-in for :func:`libwriter.cached_component_names`."""

    name = "rust"

    def __init__(self, names: dict[str, list[str]] | None = None, fail: Exception | None = None):
        self.names = names or {}
        self.fail = fail
        self.calls: list[str] = []

    def list_components(self, library: Path) -> list[str]:
        self.calls.append(Path(library).name)
        if self.fail is not None:
            raise self.fail
        return self.names[Path(library).name]


def test_verify_prefers_the_rust_reader_and_falls_back_to_altium(api, workspace, bridge, monkeypatch):
    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    chip.write_bytes(b"x")
    parts.create_part("Resistors", {"Part Number": "R-RD", **PART, "Footprint Path": "Footprints\\PF_CHIP.PcbLib"})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-RD"): resolution(workspace, "Resistors", "R-RD", footprints=["RESC1608X55N"])}
    reader = FakeReader({"PF_CHIP.PcbLib": ["RESC1608X55N"]})
    monkeypatch.setattr(routes_altium, "_library_reader", lambda ws: reader)
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-RD"]}))
    assert snap["result"]["parts"][0]["status"] == "ok" and reader.calls == ["PF_CHIP.PcbLib"]
    assert "list_components" not in bridge.names()  # no Altium script for reading the library

    libwriter.forget_component_names()
    broken = FakeReader(fail=OSError("Datei gesperrt"))
    monkeypatch.setattr(routes_altium, "_library_reader", lambda ws: broken)
    bridge.set_components(chip, ["RESC1608X55N"])
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-RD"]}))
    assert snap["result"]["parts"][0]["status"] == "ok" and "list_components" in bridge.names()

    libwriter.forget_component_names()
    bridge.components.clear()  # Altium cannot read it either
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-RD"]}))
    part = snap["result"]["parts"][0]
    assert part["status"] == "warning" and part["footprint_checks"][0]["in_library"] is None
    assert "konnte nicht gelesen werden (Datei gesperrt)" in part["messages"][0] and not part["footprint_found"]


@pytest.mark.rustwriter
def test_verify_against_a_real_pcblib(api, workspace, bridge, monkeypatch):
    """Integration with the library sync and the real Rust writer: the footprint check reads
    the PcbLib the sync wrote (no Altium script for it)."""
    from test_writer_samples import chip_0603

    from partforge.altium import sync
    from partforge.altium.rustwriter import shutdown_client

    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    try:
        record = sync.ensure_footprints([chip_0603("RESC1608X55N")])[0]
        assert record.status == "ok", record.status_message
        parts.create_part("Resistors", {"Part Number": "R-REAL", **PART, "Footprint Path": record.library})
        parts.create_part("Resistors", {"Part Number": "R-TYPO", **PART, "Footprint Ref": "RESC1608X55X",
                                        "Footprint Path": record.library})
        bridge.installed = [str(workspace.dblib_path)]
        bridge.resolutions = {
            ("Resistors", "R-REAL"): resolution(workspace, "Resistors", "R-REAL", footprints=["RESC1608X55N"]),
            ("Resistors", "R-TYPO"): resolution(workspace, "Resistors", "R-TYPO", footprints=["RESC1608X55X"]),
        }
        snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-REAL", "R-TYPO"]}))
        assert snap["status"] == "done", snap["error"]
        by_pn = {p["part_number"]: p for p in snap["result"]["parts"]}
        assert by_pn["R-REAL"]["status"] == "ok" and by_pn["R-REAL"]["footprint_found"]
        assert by_pn["R-TYPO"]["status"] == "error" and "fehlt in" in by_pn["R-TYPO"]["messages"][0]
        assert "list_components" not in bridge.names()
    finally:
        shutdown_client()


def test_verify_selection_and_errors(api, workspace, bridge, no_reader, tmp_path: Path):
    parts.create_part("Resistors", {"Part Number": "R-A", **PART})
    parts.create_part("Capacitors", {"Part Number": "C-A", "Manufacturer": "KEMET", "Capacitance": "100n",
                                     "Voltage": "50V", "Description": "CAP", "Library Ref": "CAP",
                                     "Footprint Ref": "CAPC1608X87N"})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-A"): resolution(workspace, "Resistors", "R-A", footprints=["RESC1608X55N"])}
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-A", "C-A"]}))
    assert snap["status"] == "done" and snap["result"]["temporarily_installed"] is False
    by_pn = {p["part_number"]: p for p in snap["result"]["parts"]}
    assert "keine Footprint-Bibliothek eingetragen (Footprint Path)" in " ".join(by_pn["R-A"]["messages"])
    # unknown to Altium: nothing loaded – an error of this part only
    assert by_pn["C-A"]["status"] == "error" and by_pn["C-A"]["messages"][0] == (
        "Symbol „CAP“ nicht gefunden (keine Symbolbibliothek)."
    )
    assert bridge.names()[:2] == ["install_state", "refresh_dblib"]  # fresh data before resolving

    one = run_job(api.post("/api/altium/verify", json={"limit": 1, "sample": "first"}))
    assert one["result"]["checked"] == 1 and one["result"]["total"] == 2 and one["result"]["sample"] == "first"
    spread = run_job(api.post("/api/altium/verify", json={"limit": 1}))  # default: at least one per category
    assert spread["result"]["checked"] == 2 and spread["result"]["sample"] == "spread"
    assert spread["result"]["categories"] == 2 and spread["result"]["scope"] == "sample"
    every = run_job(api.post("/api/altium/verify", json={"all": True}))
    assert every["result"]["checked"] == 2
    missing = run_job(api.post("/api/altium/verify", json={"part_numbers": ["GIBT-ES-NICHT"]}))
    assert missing["status"] == "failed" and "nicht gefunden" in missing["error"]
    unknown = run_job(api.post("/api/altium/verify", json={"tables": ["Gibtsnicht"]}))
    assert unknown["status"] == "failed" and "Gibtsnicht".casefold() in unknown["error"]

    old = copy_of_dblib(workspace, tmp_path / "Alt")
    bridge.installed = [old, str(workspace.dblib_path)]
    clash = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-A"]}))
    assert clash["status"] == "failed" and "nicht aussagekräftig" in clash["error"] and "Ersetzen" in clash["error"]
    foreign = foreign_dblib(tmp_path)
    bridge.installed = [foreign, str(workspace.dblib_path)]
    clash = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-A"]}))
    assert clash["status"] == "failed" and "anderen Bibliothek" in clash["error"]


def test_verify_without_parts(api, bridge):
    snap = run_job(api.post("/api/altium/verify"))
    assert snap["status"] == "done" and snap["result"]["checked"] == 0
    assert snap["message"] == "Keine Bauteile zum Prüfen – die Auswahl ist leer."
    assert bridge.calls == []


def _many_resistors(workspace, count: int) -> list[str]:
    rows = [{"Part Number": f"R-{i:03d}", **PART, "Footprint Path": "Footprints\\PF_CHIP.PcbLib"} for i in range(count)]
    result = parts.upsert_parts("Resistors", rows)
    assert len(result.created) == count, result
    return [row["Part Number"] for row in rows]


def test_verify_resolves_in_batches(api, workspace, bridge, no_reader):
    """Regression (altium-e2e.md §6.3): one Altium script per part took ~1.4 s – now one run per 50."""
    from partforge.altium.bridge.core import RESOLVE_BATCH_SIZE

    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    chip.write_bytes(b"x")
    bridge.set_components(chip, ["RESC1608X55N"])
    pns = _many_resistors(workspace, RESOLVE_BATCH_SIZE * 2 + 20)
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", pn): resolution(workspace, "Resistors", pn, footprints=["RESC1608X55N"])
                          for pn in pns}
    snap = run_job(api.post("/api/altium/verify", json={"all": True}))
    assert snap["status"] == "done", snap["error"]
    result = snap["result"]
    assert [len(b) for b in bridge.batches] == [RESOLVE_BATCH_SIZE, RESOLVE_BATCH_SIZE, 20]
    assert result["altium_runs"] == 3 and result["checked"] == len(pns) and result["ok"] == len(pns)
    assert [p["part_number"] for p in result["parts"]] == pns  # selection order kept
    assert [key for batch in bridge.batches for _, key in batch] == pns
    assert bridge.names().count("resolve_db_components") == 3 and "resolve_db_component" not in bridge.names()


def test_verify_batch_failure_only_affects_its_parts(api, workspace, bridge, no_reader):
    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    chip.write_bytes(b"x")
    bridge.set_components(chip, ["RESC1608X55N"])
    pns = _many_resistors(workspace, 60)
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", pn): resolution(workspace, "Resistors", pn, footprints=["RESC1608X55N"])
                          for pn in pns}
    bridge.failing_keys = {pns[55]}  # second run (parts 51–60)
    snap = run_job(api.post("/api/altium/verify", json={"all": True}))
    assert snap["status"] == "done", snap["error"]
    by_pn = {p["part_number"]: p for p in snap["result"]["parts"]}
    assert all(by_pn[pn]["status"] == "ok" for pn in pns[:50])
    for pn in pns[50:]:
        assert by_pn[pn]["status"] == "error" and "Altium meldet einen Fehler bei R-055" in by_pn[pn]["messages"][0]
    assert (snap["result"]["ok"], snap["result"]["errors"]) == (50, 10)


def test_verify_can_be_cancelled_between_runs(api, workspace, bridge, no_reader):
    import threading

    from partforge.jobs import jobs

    _many_resistors(workspace, 120)
    started = threading.Event()
    job_id: list[str] = []

    def cancel_after_first(index: int) -> None:
        if index == 1:  # the second run: the user cancels while it is in Altium
            assert started.wait(5)
            jobs.cancel(job_id[0])

    bridge.on_batch = cancel_after_first
    response = api.post("/api/altium/verify", json={"all": True})
    job_id.append(response.json()["job"]["id"])
    started.set()
    snap = run_job(response)
    assert snap["status"] == "cancelled"
    assert len(bridge.batches) == 2  # the running batch finished, the third never started
    names = bridge.names()
    assert names[-2:] == ["refresh_dblib", "uninstall_library"] and bridge.installed == []  # temporary install undone
    assert api.get("/api/altium/verify/last").json() is None  # a cancelled check is not stored


def test_verify_result_is_stored_per_library(api, workspace, bridge, no_reader, tmp_path: Path):
    from partforge.db import close_database, open_database
    from partforge.workspace import set_current

    assert api.get("/api/altium/verify/last").json() is None
    parts.create_part("Resistors", {"Part Number": "R-LAST", **PART})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-LAST"): resolution(workspace, "Resistors", "R-LAST",
                                                              footprints=["RESC1608X55N"])}
    snap = run_job(api.post("/api/altium/verify", json={"limit": 5}))
    assert snap["status"] == "done", snap["error"]
    assert snap["message"] == "1 Bauteil in Altium geprüft: 0 in Ordnung, 0 mit Hinweisen, 1 mit Fehlern."
    result = snap["result"]
    # F6: a "sample" of 5 in a library with 1 part checks every part – reported as such, not as "Stichprobe"
    assert (result["scope"], result["sample"], result["limit"], result["tables"]) == ("all", None, None, [])
    last = api.get("/api/altium/verify/last").json()
    assert (last["scope"], last["sample"], last["limit"], last["tables"]) == ("all", None, None, [])
    assert last["started"] == result["started"] and last["finished"] == result["finished"]
    assert last["started"] <= last["finished"]
    summary = last["summary"]
    assert summary["message"] == snap["message"] and summary["checked"] == 1 and summary["errors"] == 1
    assert summary["categories"] == 1 and summary["altium_runs"] == 1 and summary["total"] == 1
    assert last["results"] == result["parts"] and last["results"][0]["part_number"] == "R-LAST"
    # a failed check keeps the last result
    failed = run_job(api.post("/api/altium/verify", json={"part_numbers": ["GIBT-ES-NICHT"]}))
    assert failed["status"] == "failed" and api.get("/api/altium/verify/last").json() == last
    # survives a restart (stored in the library database) …
    close_database()
    open_database(workspace)
    assert api.get("/api/altium/verify/last").json() == last
    # … and belongs to this library: another one has none
    other = Workspace.create(tmp_path / "Andere Bibliothek")
    close_database()
    open_database(other)
    set_current(other)
    try:
        assert api.get("/api/altium/verify/last").json() is None
    finally:
        close_database()
        open_database(workspace)
        set_current(workspace)
    one = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-LAST"]}))
    assert one["status"] == "done"
    assert api.get("/api/altium/verify/last").json()["scope"] == "part_numbers"



def test_verify_title_names_scope_and_categories(api, workspace, bridge, no_reader):
    """F6: the job title said „(alle Bauteile)“ for a check of one category – it names scope and categories."""
    parts.create_part("Resistors", {"Part Number": "R-T1", **PART})
    parts.create_part("Resistors", {"Part Number": "R-T2", **PART})
    bridge.installed = [str(workspace.dblib_path)]
    label = categories.get_category("Resistors").label
    snap = run_job(api.post("/api/altium/verify", json={"tables": ["Resistors"], "limit": 1}))
    assert snap["title"] == f"Bibliothek in Altium prüfen (Stichprobe: {label})"
    assert snap["result"]["scope"] == "sample"
    snap = run_job(api.post("/api/altium/verify", json={"tables": ["Resistors"], "all": True}))
    assert snap["title"] == f"Bibliothek in Altium prüfen (alle Bauteile: {label})"
    snap = run_job(api.post("/api/altium/verify", json={"all": True}))
    assert snap["title"] == "Bibliothek in Altium prüfen (alle Bauteile)"
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-T1", "R-T2"]}))
    assert snap["title"] == "Bibliothek in Altium prüfen (2 Bauteile)"
    snap = run_job(api.post("/api/altium/verify", json={"limit": 20}))  # „Alle 2 Bauteile“ in the menu
    assert snap["result"]["scope"] == "all" and snap["result"]["checked"] == 2
    assert snap["title"] == "Bibliothek in Altium prüfen (alle Bauteile)"


def test_verify_does_not_count_a_cached_symbol_of_a_deleted_key(api, workspace, bridge, no_reader):
    """F5: after a delete Altium still loads the old symbol for the key (from its cache) – without a SchLib
    reference and without parameters that is no record."""
    parts.create_part("Resistors", {"Part Number": "R-GONE", **PART})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-GONE"): DbComponentResolution(
        dblib=str(workspace.dblib_path), table="Resistors", key="R-GONE", loaded=True, lib_reference="Resistor",
        symbol_ref="", pin_count=2, parameters={}, description="Generic resistor")}
    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-GONE"]}))
    part = snap["result"]["parts"][0]
    assert part["status"] == "error" and part["symbol_found"] is False
    assert "nicht gefunden" in part["messages"][0] and "zwischengespeichertes Symbol" in part["messages"][0]


def test_status_reports_the_odbc_driver(api, workspace, bridge, monkeypatch):
    """F4 (UX): without the SQLite ODBC driver Altium reads nothing – the status says so without a connection test."""
    from partforge.altium import odbc

    monkeypatch.setattr(odbc, "_installed_drivers", lambda: ["SQL Server"])
    data = api.get("/api/altium/status").json()["odbc"]
    assert data["installed"] is False and data["driver"] == "SQLite3 ODBC Driver" and data["kind"] == "sqlite"
    assert "nicht installiert" in data["message"] and "ch-werner.de" in data["message"] and data["download"]
    monkeypatch.setattr(odbc, "_installed_drivers", lambda: ["SQLite3 ODBC Driver"])
    data = api.get("/api/altium/status").json()["odbc"]
    assert data["installed"] is True and "installiert" in data["message"]
    monkeypatch.setattr(odbc, "_installed_drivers", lambda: None)
    assert api.get("/api/altium/status").json()["odbc"]["installed"] is None


def test_uninstall_reports_whether_altium_still_holds_the_database(api, workspace, bridge, monkeypatch):
    """F3: Altium keeps the SQLite database open after the uninstall – the job says so instead of leaving the user with
    „Zugriff verweigert“ when moving the folder."""
    from partforge.altium import holders

    bridge.installed = [str(workspace.dblib_path)]
    monkeypatch.setattr(holders, "file_holders", lambda paths: [holders.FileHolder(pid=81348, name="Altium Designer")])
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["status"] == "done" and snap["result"]["database_released"] is False
    assert snap["result"]["database_holders"] == [{"pid": 81348, "name": "Altium Designer"}]
    assert snap["message"].startswith("Die DbLib wurde in Altium deinstalliert.")
    assert "etwa einer Minute" in snap["message"] and "Altium neu starten" in snap["message"]
    bridge.installed = [str(workspace.dblib_path)]
    monkeypatch.setattr(holders, "file_holders", lambda paths: [])
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["result"]["database_released"] is True and snap["message"] == "Die DbLib wurde in Altium deinstalliert."


def test_uninstall_hint_says_what_to_do_first_and_fits_a_toast(api, workspace, bridge, monkeypatch):
    """E2EREG-2: the hint was cut at 200 characters in the toast and lost its advice („warten oder Altium neu
    starten“). Now the advice comes first, the outcome sentence fits a toast and the result carries the hint."""
    from partforge.altium import holders

    def uninstall_with(*names: str) -> dict:
        bridge.installed = [str(workspace.dblib_path)]
        found = [holders.FileHolder(pid=100 + i, name=n) for i, n in enumerate(names)]
        monkeypatch.setattr(holders, "file_holders", lambda paths: found)
        return run_job(api.post("/api/altium/uninstall"))

    snap = uninstall_with("Altium Designer")
    hint = snap["result"]["database_hint"]
    assert hint == ("Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen "
                    "(sonst Altium neu starten).")
    assert snap["message"] == f"Die DbLib wurde in Altium deinstalliert. {hint}" and len(snap["message"]) <= 200
    assert {"level": "warn", "text": hint} in [{"level": e["level"], "text": e["text"]} for e in snap["log"]]
    assert snap["result"]["outcome"] == "partial"  # job lists show it as „Fertig mit Hinweisen“ (jobResultProblem)
    snap = uninstall_with("DB Browser for SQLite")
    assert snap["result"]["database_hint"] == ("Ordner erst nach dem Schließen von DB Browser for SQLite verschiebbar – "
                                               "bis dahin hält das Programm die Datenbank offen.")
    assert len(snap["message"]) <= 200
    snap = uninstall_with("Excel", "DB Browser for SQLite")
    assert snap["result"]["database_hint"] == ("Ordner erst nach dem Schließen von DB Browser for SQLite, Excel "
                                               "verschiebbar – bis dahin halten diese Programme die Datenbank offen.")
    snap = uninstall_with()
    assert snap["result"]["database_released"] is True and snap["result"]["database_hint"] is None
    assert snap["result"]["outcome"] == "ok"

def test_verify_last_needs_a_library(bare_api):
    assert bare_api.get("/api/altium/verify/last").status_code == 409


def test_jobs_end_with_an_outcome_sentence(api, workspace, bridge):
    snap = run_job(api.post("/api/altium/install"))
    assert snap["message"] == "Die DbLib ist in Altium installiert."
    snap = run_job(api.post("/api/altium/install-state"))
    assert snap["message"] == "Die DbLib ist in Altium installiert."
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["message"] == "Die DbLib wurde in Altium deinstalliert."
    snap = run_job(api.post("/api/altium/uninstall"))
    assert snap["message"] == "Die DbLib war in Altium nicht installiert – nichts zu tun."
    snap = run_job(api.post("/api/altium/open"))
    assert snap["message"] == "„PartForge.DbLib“ ist in Altium geöffnet."


def test_verify_reports_the_comment(api, workspace, bridge, no_reader):
    parts.create_part("Resistors", {"Part Number": "R-CMT", **PART})
    bridge.installed = [str(workspace.dblib_path)]
    res = resolution(workspace, "Resistors", "R-CMT", footprints=["RESC1608X55N"])
    res.comment, res.comment_visible, res.visible_parameters = "10k", True, []
    bridge.resolutions = {("Resistors", "R-CMT"): res}
    part = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-CMT"]}))["result"]["parts"][0]
    assert (part["comment"], part["comment_visible"], part["visible_parameters"]) == ("10k", True, [])


def design_columns(table: str) -> list[str]:
    """Columns the DbLib adds to the design as parameters of the same name (not [Library Ref] …, not AddMode 1)."""
    from partforge.altium.dblib import ADD_MODE_DO_NOT_ADD, field_map_for

    category = categories.get_category(table)
    columns = []
    for field in category.fields:
        mapping = field_map_for(category.table, field)
        if mapping is None or not (mapping.parameter_name.startswith("[") or mapping.add_mode == ADD_MODE_DO_NOT_ADD):
            columns.append(field.column)
    return columns


def placed_values(table: str, pn: str) -> tuple[dict[str, str], str]:
    """What Altium places with a part (the real bridge reports it): every non-blank field the DbLib adds to the
    design as a parameter of the same name, as stored – and the Description ([Description])."""
    row = parts.get_part(table, pn)
    assert row is not None
    params = {column: str(row[column]) for column in design_columns(table) if row.get(column) not in (None, "")}
    return params, str(row.get("Description") or "")


def test_verify_compares_the_parameter_values_with_the_database(api, workspace, bridge, no_reader):
    """E2EREG-3: „In Altium prüfen“ compares the parameters and the Description Altium places with the database row
    (fields added to the design); each difference is a warning – equivalent spellings (micro sign/Greek mu, ohm sign/Greek Omega, ±/+/-, blanks) and a
    blank value that Altium leaves out (AddMode 3) are none."""
    pcblib = workspace.footprints_dir / "PF_GULLWING.PcbLib"
    pcblib.write_bytes(b"x")
    bridge.set_components(pcblib, ["SOIC127P600X175-8N"])
    chip = workspace.footprints_dir / "PF_CHIP.PcbLib"
    chip.write_bytes(b"x")
    bridge.set_components(chip, ["RESC1608X55N"])
    amp = {"Manufacturer": "Texas Instruments", "Library Ref": "Op-Amp", "Footprint Ref": "SOIC127P600X175-8N",
           "Footprint Path": "Footprints\\PF_GULLWING.PcbLib", "Package": "SOIC-8", "Channels": "1", "GBW": "230MHz",
           "Input Offset": "±250µV"}
    parts.create_part("Amplifiers", {"Part Number": "OPA656U", "Manufacturer Part Number": "OPA656U", **amp,
                                     "Slew Rate": "290V/µs", "Notes": "Rails, 100"})
    parts.create_part("Amplifiers", {"Part Number": "OPA657U", "Manufacturer Part Number": "OPA657U", **amp,
                                     "Slew Rate": "700V/µs"})
    parts.create_part("Resistors", {"Part Number": "R-OHM", **PART, "Footprint Path": "Footprints\\PF_CHIP.PcbLib"})
    bridge.installed = [str(workspace.dblib_path)]

    def placed(table: str, pn: str, ref: str, footprint: str) -> DbComponentResolution:
        params, description = placed_values(table, pn)
        return DbComponentResolution(dblib=str(workspace.dblib_path), table=table, key=pn, loaded=True, symbol_ref=ref,
                                     lib_reference=ref, footprints=[footprint], parameters=params,
                                     description=description, comment=params.get("Comment", ""))

    stale = placed("Amplifiers", "OPA656U", "Op-Amp", "SOIC127P600X175-8N")
    stored_description = stale.description
    assert "290V/µs" in stored_description and stale.parameters["Slew Rate"] == "290V/µs"
    del stale.parameters["Slew Rate"]  # Altium still has the record from before the Slew Rate was typed in
    stale.description = "IC OPAMP 1CH 230MHz SOIC-8"
    stale.parameters["Rail-to-Rail"] = "Ausgang"  # blank in the database
    stale.parameters["Notes"] = "Rails, 100"  # no design parameter (add_to_design=False): only listed
    same = placed("Amplifiers", "OPA657U", "Op-Amp", "SOIC127P600X175-8N")
    same.parameters["Input Offset"] = "+/-250\u03bcV"  # ASCII plus-minus, Greek mu
    same.parameters["GBW"] = " 230MHz\u00a0"
    same.parameters["Mounting"] = ""  # blank = absent
    ohm = placed("Resistors", "R-OHM", "RES", "RESC1608X55N")
    assert ohm.parameters["Resistance"] == "10kΩ"
    ohm.parameters["Resistance"] = "10k\u2126"  # OHM SIGN instead of GREEK CAPITAL OMEGA
    bridge.resolutions = {("Amplifiers", "OPA656U"): stale, ("Amplifiers", "OPA657U"): same, ("Resistors", "R-OHM"): ohm}

    snap = run_job(api.post("/api/altium/verify", json={"part_numbers": ["OPA656U", "OPA657U", "R-OHM"]}))
    assert snap["status"] == "done", snap["error"]
    by_pn = {p["part_number"]: p for p in snap["result"]["parts"]}
    checked = by_pn["OPA657U"]["parameters_checked"]
    assert checked == len(design_columns("Amplifiers")) + 1  # every design field (blank ones too) + Description
    assert "Library Ref" not in design_columns("Amplifiers") and "Notes" not in design_columns("Amplifiers")
    for pn in ("OPA657U", "R-OHM"):
        assert by_pn[pn]["status"] == "ok" and by_pn[pn]["parameter_diffs"] == [] and by_pn[pn]["messages"] == [], pn
        assert by_pn[pn]["extra_parameters"] == []
    part = by_pn["OPA656U"]
    assert part["status"] == "warning" and part["parameters_checked"] == checked
    assert part["parameter_diffs"] == [  # in field order, the Description (generated from the fields) last
        {"parameter": "Slew Rate", "database": "290V/µs", "altium": None},
        {"parameter": "Rail-to-Rail", "database": None, "altium": "Ausgang"},
        {"parameter": "Description", "database": stored_description, "altium": "IC OPAMP 1CH 230MHz SOIC-8"},
    ]
    assert part["messages"] == [
        "Altium liefert für „Slew Rate“ keinen Wert – in der Datenbank steht „290V/µs“.",
        "Altium liefert für „Rail-to-Rail“ „Ausgang“ – in der Datenbank ist das Feld leer.",
        f"Altium liefert für „Description“ „IC OPAMP 1CH 230MHz SOIC-8“ – in der Datenbank steht „{stored_description}“.",
    ]
    assert part["extra_parameters"] == ["Notes"]
    assert part["description"] == "IC OPAMP 1CH 230MHz SOIC-8" and part["parameters"]["Notes"] == "Rails, 100"
    assert "Slew Rate" not in part["parameters"] and part["parameters"]["Part Number"] == "OPA656U"
    assert (snap["result"]["ok"], snap["result"]["warnings"], snap["result"]["errors"]) == (2, 1, 0)
    stored = {p["part_number"]: p for p in api.get("/api/altium/verify/last").json()["results"]}
    assert stored["OPA656U"]["parameter_diffs"] == part["parameter_diffs"]  # the saved result keeps the details


def test_verify_without_reported_parameters_leaves_them_unchecked(api, workspace, bridge, no_reader):
    """An older bridge script reports no parameters: nothing to compare – no warning for every field."""
    parts.create_part("Resistors", {"Part Number": "R-OLD", **PART})
    bridge.installed = [str(workspace.dblib_path)]
    bridge.resolutions = {("Resistors", "R-OLD"): resolution(workspace, "Resistors", "R-OLD", footprints=["RESC1608X55N"])}
    part = run_job(api.post("/api/altium/verify", json={"part_numbers": ["R-OLD"]}))["result"]["parts"][0]
    assert part["parameters_checked"] == 0 and part["parameter_diffs"] == [] and part["parameters"] == {}
    assert not any("Altium liefert" in m for m in part["messages"])


# --------------------------------------------------------------------------- open


def test_open_dblib_and_libraries(api, workspace, bridge):
    snap = run_job(api.post("/api/altium/open"))
    assert snap["status"] == "done" and snap["result"]["was_open"] is False
    assert bridge.opened == [str(workspace.dblib_path)] and workspace.dblib_path.is_file()
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    lib.write_bytes(b"x")
    snap = run_job(api.post("/api/altium/open", json={"path": "Symbols\\PF_Passives.SchLib"}))
    assert snap["result"]["path"] == str(lib)
    bad = api.post("/api/altium/open", json={"path": "Symbols\\notiz.txt"})
    assert bad.status_code == 400 and "keine Altium-Bibliothek" in bad.json()["detail"]
    missing = api.post("/api/altium/open", json={"path": str(workspace.root / "Fehlt.PcbLib")})
    assert missing.status_code == 400 and "existiert nicht" in missing.json()["detail"]


# --------------------------------------------------------------------------- errors / lifespan


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (BridgeBusyError("belegt"), 409),
        (AltiumNotRunning("Altium Designer ist nicht gestartet."), 503),
        (BridgeWedgedError("did_not_finish", last_step="x", seconds=3), 503),
        (libwriter.WriterUnavailable("kein Writer"), 503),
        (BridgeCommandError("refresh_dblib", "Fehler"), 400),
        (BridgeError("X2.EXE fehlt"), 503),
        (DbLibError("kaputt"), 400),
        (dblib.DbLibPathError("Sonderzeichen"), 400),
        (WorkspaceNotOpen("Es ist keine Bibliothek geöffnet."), 409),
    ],
)
def test_error_mapping(error, status):
    with pytest.raises(HTTPException) as exc, routes_altium.altium_errors():
        raise error
    assert exc.value.status_code == status and exc.value.detail
    if isinstance(error, BridgeWedgedError):
        assert "Strg+F3" in exc.value.detail


def test_lifespan_starts_services_and_parts_changes_reach_them(workspace, bridge, service):
    with make_client(bridge, service) as c:
        assert service.running and refresh.get_auto_writer() is not None
        assert service.wait_idle(5)
        assert bridge.names() == ["install_state"]  # unknown install state: read-only check first
        response = c.post("/api/parts/Resistors", json={"values": {"Part Number": "R-LIVE", **PART}})
        assert response.status_code in (200, 201), response.text
        assert wait_for(lambda: service.status().last_skip_reason is not None, 5)
        status = c.get("/api/altium/status").json()["refresh"]
        assert status["pending"] is False and "nicht installiert" in status["last_skip_reason"]
        assert bridge.names() == ["install_state"]  # known as not installed: no further script
        bridge.installed = [str(workspace.dblib_path)]
        remember_install_state(DbLibInstallState(path=str(workspace.dblib_path), file_name="PartForge.DbLib",
                                                 installed=True), dblib=workspace.dblib_path)
        c.post("/api/parts/Resistors", json={"values": {"Part Number": "R-LIVE-2", **PART}})
        assert wait_for(lambda: bridge.names().count("refresh_dblib") == 1, 5)
        assert bridge.calls[-1] == ("refresh_dblib", ("PartForge.DbLib", True))  # insert: index rebuild
    assert not service.running and refresh.get_auto_writer() is None
    before = service.status().last_request
    events.emit(events.PARTS_CHANGED, "Resistors", True)
    assert service.status().last_request == before  # unsubscribed after shutdown


def test_workspace_create_writes_the_dblib(workspace, bridge, service, tmp_path: Path):
    with make_client(bridge, service) as c:
        target = tmp_path / "Neu"
        response = c.post("/api/workspace/create", json={"path": str(target), "with_examples": False})
        assert response.status_code == 200, response.text
        assert (target / "PartForge.DbLib").is_file()
        status = c.get("/api/altium/dblib").json()
        assert status["up_to_date"] and status["path"] == str((target / "PartForge.DbLib").resolve())


def test_default_dependencies(service):
    from partforge.altium.bridge.core import AltiumBridge

    bridge = routes_altium.get_bridge()
    assert isinstance(bridge, AltiumBridge)
    if not refresh.live_altium_allowed():
        assert bridge.is_running() is False  # never the real Altium in the automated tests
    assert routes_altium.get_refresh_service() is service  # the process-wide service
    default = AltiumRefreshService()
    assert default._probe is False  # noqa: SLF001 - no automatic install-state probe from the test suite
