"""Shared pytest fixtures.

* Every test session uses an isolated PARTFORGE_HOME (never the user's real settings); an inherited
  PARTFORGE_AI_REPLAY_DIR is dropped (the replay tests switch the mode on themselves).
* ``workspace`` creates a fresh workspace (library folder) in a temp dir and opens it.
* ``client`` is a FastAPI TestClient that sends the session token automatically.
* Tests that need Altium Designer, the Rust library writer or the Claude API are marked
  ``altium``, ``rustwriter`` or ``ai`` and are skipped unless enabled via environment:
  PARTFORGE_TEST_ALTIUM=1, PARTFORGE_TEST_RUST=1 (default: on if the exe exists), PARTFORGE_TEST_AI=1.
* Tests that only work on Windows (pythoncom/COM, Windows file locks, Windows path spellings, .exe/.cmd/PowerShell)
  are marked ``windows`` and are skipped on other platforms; on Windows they always run.
* Creating a library never starts the background job "Bibliotheken schreiben" (which would write
  with the real library writer behind the test's back): ``routes_system.start_library_sync``
  returns a finished, skipped job – unless the test is marked ``library_job`` (every test of
  :data:`LIBRARY_JOB_MODULES` is).
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

_HOME = Path(tempfile.mkdtemp(prefix="partforge-home-"))
os.environ["PARTFORGE_HOME"] = str(_HOME)
# Starlette's TestClient sends Host "testserver". The host guard (partforge.app) only accepts loopback
# hosts in the real program; this test-only hook (read by create_app when no allowed_hosts is passed)
# lets the fixtures' TestClient through without ever allowing "testserver" in the shipped program.
os.environ["PARTFORGE_TEST_HOSTS"] = "testserver"
# The replay mode (recorded Claude answers) is switched on per test (test_datasheet_replay.py: monkeypatch.setenv);
# a value inherited from the calling shell (isolated agents run with it) would make "no key" tests see the replay
# key. Without it no test reaches the API either: isolated runs never pick up a real key (config._real_key_allowed).
os.environ.pop("PARTFORGE_AI_REPLAY_DIR", None)

TOKEN = "test-token"

#: Test modules that check the job "Bibliotheken schreiben" itself: all their tests are ``library_job``.
LIBRARY_JOB_MODULES = frozenset({"test_integration_workspace.py"})
#: Result of the job that stands in for "Bibliotheken schreiben" in tests without ``library_job``.
LIBRARY_JOB_SKIPPED = (
    "Im Test nicht gestartet (Marker „library_job“ fehlt) – Symbole und Footprints bleiben „ausstehend“."
)


def pytest_configure(config):
    config.addinivalue_line("markers", "altium: needs a running Altium Designer (PARTFORGE_TEST_ALTIUM=1)")
    config.addinivalue_line("markers", "rustwriter: needs altium-designer-mcp.exe")
    config.addinivalue_line("markers", "ai: calls the Claude API (PARTFORGE_TEST_AI=1)")
    config.addinivalue_line("markers", "slow: long-running test")
    config.addinivalue_line(
        "markers", "windows: needs Windows (pythoncom, Windows file locks or paths, .exe/.cmd); skipped elsewhere"
    )
    config.addinivalue_line(
        "markers",
        "library_job: creating a library starts the real background job 'Bibliotheken schreiben' "
        "(otherwise a finished, skipped stand-in)",
    )


def pytest_collection_modifyitems(config, items):
    from partforge.config import detect_rust_writer

    run_altium = os.environ.get("PARTFORGE_TEST_ALTIUM") == "1"
    run_ai = os.environ.get("PARTFORGE_TEST_AI") == "1"
    rust_env = os.environ.get("PARTFORGE_TEST_RUST")
    run_rust = (rust_env == "1") or (rust_env is None and detect_rust_writer() is not None)
    on_windows = sys.platform == "win32"
    for item in items:
        if item.get_closest_marker("windows") is not None and not on_windows:
            item.add_marker(pytest.mark.skip(reason="Nur unter Windows lauffähig"))
        if item.path.name in LIBRARY_JOB_MODULES:
            item.add_marker(pytest.mark.library_job)
        if "altium" in item.keywords and not run_altium:
            item.add_marker(pytest.mark.skip(reason="Altium-Tests deaktiviert (PARTFORGE_TEST_ALTIUM=1)"))
        if "ai" in item.keywords and not run_ai:
            item.add_marker(pytest.mark.skip(reason="KI-Tests deaktiviert (PARTFORGE_TEST_AI=1)"))
        if "rustwriter" in item.keywords and not run_rust:
            item.add_marker(pytest.mark.skip(reason="altium-designer-mcp.exe nicht verfügbar"))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_background_library_job(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """API tests never start the background writer job "Bibliotheken schreiben": creating a library
    gets a finished job with ``{"skipped": True, "reason": …}`` instead (the examples stay
    ``pending``), unless the test is marked ``@pytest.mark.library_job``."""
    if request.node.get_closest_marker("library_job") is not None:
        return
    from partforge.api import routes_system
    from partforge.jobs import Job, JobContext, jobs

    def skipped(ctx: JobContext) -> dict[str, object]:
        ctx.log(LIBRARY_JOB_SKIPPED, "warn")
        return {"skipped": True, "reason": LIBRARY_JOB_SKIPPED}

    def start_library_sync(ws: object) -> Job:
        return jobs.run_sync(routes_system.LIBRARY_SYNC_JOB_KIND, routes_system.LIBRARY_SYNC_JOB_TITLE, skipped)

    monkeypatch.setattr(routes_system, "start_library_sync", start_library_sync)


@pytest.fixture(autouse=True)
def _restore_app_settings():
    """Settings a test saves (e.g. through PUT /api/settings) never leak into later tests: the session's
    settings.json is restored after every test and the cached settings are reloaded."""
    from partforge import config

    path = config.settings_path()
    before = path.read_bytes() if path.is_file() else None
    yield
    after = path.read_bytes() if path.is_file() else None
    if after == before:
        return
    if before is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(before)
    config.load_settings(reload=True)


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def workspace(tmp_path: Path):
    """A fresh, opened workspace (database created through partforge.db.open_database)."""
    from partforge.db import close_database, open_database
    from partforge.workspace import Workspace, set_current

    ws = Workspace.create(tmp_path / "Bibliothek", name="Testbibliothek")
    open_database(ws)
    set_current(ws)
    try:
        yield ws
    finally:
        close_database()
        set_current(None)


@pytest.fixture
def client(workspace):
    """TestClient with token header and an open workspace."""
    from fastapi.testclient import TestClient

    from partforge.app import create_app

    app = create_app(token=TOKEN)
    with TestClient(app, headers={"X-PartForge-Token": TOKEN}) as c:
        yield c


@pytest.fixture
def bare_client():
    """TestClient without an open workspace."""
    from fastapi.testclient import TestClient

    from partforge.app import create_app
    from partforge.workspace import set_current

    set_current(None)
    app = create_app(token=TOKEN)
    with TestClient(app, headers={"X-PartForge-Token": TOKEN}) as c:
        yield c
