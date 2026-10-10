"""Security regressions for the QA findings:

1. Host-header validation (DNS rebinding) – the SPA index that carries the token and every /api route only
   answer loopback hosts (421 otherwise, never the token); cross-site unsafe requests are refused (403).
2. Executable/key path validation on PUT /api/settings and at resolve time (no UNC/device paths, .exe,
   X2.EXE by name; a hand-edited UNC path is ignored, never executed). A key file is only read when it is a
   small local file whose content looks like an Anthropic key.
4. The session token is redacted from logs.
5. Verifier pass 2 (sec-spa-crosssite-aktion): the SPA index only carries the token for the user's own top-level
   navigations (``Sec-Fetch-Site: none``/``same-origin``, ``Sec-Fetch-Dest: document`` or no such headers) – a foreign
   website's link, redirect or frame gets a 403 page without token and query; every response forbids framing.

The live tests run the real server (``python -m partforge --server-only --verbose`` resp. uvicorn with the
program's protocol) on a free loopback port: the host guard must hold for raw HTTP requests too (absolute-form
targets), and neither ``partforge.log`` nor the console may ever contain the token.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.responses import Response

from partforge import config
from partforge.app import create_app, deny_framing, host_is_allowed, navigation_may_carry_token, request_host_name
from partforge.config import AltiumSettings, AppSettings
from partforge.logsafe import RedactTokenFilter, redact_token

TOKEN = "sec-token"


def _client(allowed_hosts=None, base_url="http://127.0.0.1") -> TestClient:
    app = create_app(token=TOKEN, allowed_hosts=allowed_hosts)
    return TestClient(app, headers={"X-PartForge-Token": TOKEN}, base_url=base_url)


# --------------------------------------------------------------------------- 1. host validation


def test_request_host_name_normalisation() -> None:
    assert request_host_name("127.0.0.1:48765") == "127.0.0.1"
    assert request_host_name("LocalHost:5173") == "localhost"
    assert request_host_name("[::1]:8901") == "::1"
    assert request_host_name("::1") == "::1"
    # rejected: trailing dot, empty, embedded path/scheme, non-numeric port
    for bad in ("", "   ", "localhost.", "127.0.0.1.", "evil/x", "http://127.0.0.1", "a@b", "host:xx", "[::1"):
        assert request_host_name(bad) is None, bad


def test_host_allowed_set() -> None:
    allowed = frozenset({"127.0.0.1", "localhost", "::1"})
    assert host_is_allowed("127.0.0.1:48765", allowed)
    assert host_is_allowed("localhost", allowed)
    assert host_is_allowed("[::1]:1", allowed)
    assert not host_is_allowed("rebind.attacker.example:8901", allowed)
    assert not host_is_allowed("localhost.", allowed)
    assert not host_is_allowed(None, allowed)


def test_loopback_hosts_are_accepted() -> None:
    c = _client()
    assert c.get("/api/health").status_code == 200
    for host in ("127.0.0.1:48765", "localhost:5173", "LOCALHOST", "[::1]:48765"):
        assert c.get("/api/health", headers={"host": host}).status_code == 200, host


def test_foreign_host_is_rejected_with_421_and_no_token() -> None:
    """A DNS-rebinding page sends the attacker's Host; / must not leak the token (QA sec finding 1)."""
    c = _client()
    foreign = "rebind.attacker.example:8901"
    health = c.get("/api/health", headers={"host": foreign})
    assert health.status_code == 421
    assert TOKEN not in health.text and "token" not in health.json()
    index = c.get("/", headers={"host": foreign})
    assert index.status_code == 421
    assert TOKEN not in index.text and "partforge-token" not in index.text
    # the authenticated route the PoC drives is refused before the token is even checked
    settings = c.get("/api/settings", headers={"host": foreign})
    assert settings.status_code == 421 and TOKEN not in settings.text


def test_trailing_dot_and_empty_host_rejected() -> None:
    c = _client()
    assert c.get("/api/health", headers={"host": "localhost."}).status_code == 421
    assert c.get("/api/health", headers={"host": "127.0.0.1."}).status_code == 421
    assert c.get("/api/health", headers={"host": ""}).status_code == 421


def test_the_real_program_never_allows_testserver() -> None:
    """The shipped program accepts only loopback – not the TestClient's default host (QA sec finding 1)."""
    app = create_app(token=TOKEN, allowed_hosts=frozenset())  # explicit empty: env hook ignored
    c = TestClient(app, headers={"X-PartForge-Token": TOKEN})  # base_url http://testserver
    assert c.get("/api/health").status_code == 421


def test_allowed_hosts_are_configurable_for_tests() -> None:
    c = _client(allowed_hosts={"testserver"})
    assert TestClient(c.app, headers={"X-PartForge-Token": TOKEN}).get("/api/health").status_code == 200


# --------------------------------------------------------------------------- 1. cross-site guard


def test_cross_site_unsafe_requests_are_refused() -> None:
    c = _client(allowed_hosts={"testserver"})
    # same-origin / no-origin keep working
    assert c.post("/api/jobs/none/cancel", headers={"origin": "http://127.0.0.1:48765"}).status_code == 200
    assert c.post("/api/jobs/none/cancel").status_code == 200
    assert c.post("/api/jobs/none/cancel", headers={"sec-fetch-site": "same-origin"}).status_code == 200
    # cross-site (foreign Origin, Sec-Fetch-Site or null Origin) is refused
    assert c.post("/api/jobs/none/cancel", headers={"origin": "http://evil.example"}).status_code == 403
    assert c.post("/api/jobs/none/cancel", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.post("/api/jobs/none/cancel", headers={"origin": "null"}).status_code == 403
    # a safe method with a foreign Origin is not blocked (it carries no token-changing power)
    assert c.get("/api/health", headers={"origin": "http://evil.example"}).status_code == 200


def test_token_still_required_and_health_public() -> None:
    app = create_app(token=TOKEN, allowed_hosts={"testserver"})
    anon = TestClient(app)  # no token header
    assert anon.get("/api/health").status_code == 200  # public
    assert anon.get("/api/settings").status_code == 401  # token required


# --------------------------------------------------------------------------- 5. SPA only for own navigations, no framing

#: Requests of a foreign website (or of a frame/fetch) for a SPA page – measured headers of Chrome/WebView2.
FOREIGN_SPA_REQUESTS = {
    # <script>location.href='http://127.0.0.1:48765/altium?aktion=dblib'</script>, link, redirect
    "cross-site navigation": {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"},
    # another server on the loopback interface (other port = other origin, same site)
    "same-site navigation": {"sec-fetch-site": "same-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "document"},
    # <iframe src="http://127.0.0.1:48765/altium?aktion=dblib" style="opacity:0">
    "cross-site iframe": {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "iframe"},
    # a frame never gets the token, whoever embeds it
    "same-origin iframe": {"sec-fetch-site": "same-origin", "sec-fetch-mode": "navigate", "sec-fetch-dest": "iframe"},
    "object": {"sec-fetch-site": "cross-site", "sec-fetch-mode": "navigate", "sec-fetch-dest": "object"},
    "fetch": {"sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "sec-fetch-dest": "empty"},
}
#: The user's own navigations: desktop window start, address bar, bookmark, webbrowser.open (none); reload or a link
#: of PartForge itself (same-origin); clients without Fetch Metadata (no headers).
OWN_SPA_REQUESTS = {
    "none (desktop window, address bar)": {"sec-fetch-site": "none", "sec-fetch-mode": "navigate",
                                           "sec-fetch-user": "?1", "sec-fetch-dest": "document"},
    "same-origin (reload, own link)": {"sec-fetch-site": "same-origin", "sec-fetch-mode": "navigate",
                                       "sec-fetch-dest": "document"},
    "no Fetch Metadata": {},
}
SPA_PATHS = ["/altium?aktion=sync", "/altium?aktion=installieren", "/", "/bauteile"]


@pytest.fixture
def spa(monkeypatch, tmp_path) -> TestClient:
    """A client whose SPA is a minimal frontend build (independent of partforge/web)."""
    from partforge import app as app_module

    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text(
        "<!doctype html><html><head><title>PartForge</title></head><body><div id=root></div></body></html>",
        encoding="utf-8")
    (web / "assets" / "index-abc.js").write_text("console.log('pf')", encoding="utf-8")
    monkeypatch.setattr(app_module, "WEB_DIR", web)
    return _client()


@pytest.mark.parametrize("kind", FOREIGN_SPA_REQUESTS)
@pytest.mark.parametrize("language, heading, open_label", [
    ("en", "PartForge was opened from another website", "Open PartForge"),
    ("de", "PartForge wurde von einer anderen Website aufgerufen", "PartForge öffnen"),
])
def test_foreign_navigation_or_frame_gets_no_token(spa, kind, language, heading, open_label) -> None:
    """A foreign website navigating to /altium?aktion=… (or framing it) must not get the SPA with the token: the
    page would run the action without a click (verifier finding sec-spa-crosssite-aktion)."""
    from partforge.config import load_settings, save_settings

    settings = load_settings().model_copy(update={"language": language})
    save_settings(settings)
    for path in SPA_PATHS:
        r = spa.get(path, headers=FOREIGN_SPA_REQUESTS[kind])
        assert r.status_code == 403, (kind, path, r.status_code)
        assert "partforge-token" not in r.text and TOKEN not in r.text, (kind, path)
        assert "aktion" not in r.text and "installieren" not in r.text, "query reflected"
        assert heading in r.text and f'<a href="/">{open_label}</a>' in r.text
        assert f'<html lang="{language}">' in r.text
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("language, message", [
    ("en", "The frontend has not been built."),
    ("de", "Frontend ist nicht gebaut."),
])
def test_missing_frontend_is_localized_and_foreign_navigation_still_gets_no_token(monkeypatch, tmp_path, language, message) -> None:
    from partforge import app as app_module
    from partforge.config import load_settings, save_settings

    monkeypatch.setattr(app_module, "WEB_DIR", tmp_path / "missing-web")
    save_settings(load_settings().model_copy(update={"language": language}))
    client = _client()
    own = client.get("/altium?aktion=sync", headers=OWN_SPA_REQUESTS["none (desktop window, address bar)"])
    assert own.status_code == 503
    assert f'<html lang="{language}">' in own.text and message in own.text
    assert "npm run build" in own.text and "frontend" in own.text
    assert TOKEN not in own.text and "partforge-token" not in own.text and "aktion" not in own.text
    assert own.headers["cache-control"] == "no-store"
    assert own.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in own.headers["content-security-policy"]

    foreign = client.get("/altium?aktion=sync", headers=FOREIGN_SPA_REQUESTS["cross-site navigation"])
    assert foreign.status_code == 403
    assert f'<html lang="{language}">' in foreign.text
    assert TOKEN not in foreign.text and "partforge-token" not in foreign.text and "aktion" not in foreign.text
    assert '<a href="/">' in foreign.text and "npm run build" not in foreign.text


@pytest.mark.parametrize("kind", OWN_SPA_REQUESTS)
def test_own_navigation_gets_the_spa_with_token(spa, kind) -> None:
    for path in SPA_PATHS:
        r = spa.get(path, headers=OWN_SPA_REQUESTS[kind])
        assert r.status_code == 200, (kind, path, r.status_code)
        assert f'<meta name="partforge-token" content="{TOKEN}">' in r.text, (kind, path)


def test_navigation_may_carry_token_rules() -> None:
    assert navigation_may_carry_token({})
    assert navigation_may_carry_token({"sec-fetch-site": "none", "sec-fetch-dest": "document"})
    assert navigation_may_carry_token({"sec-fetch-site": "Same-Origin"})  # tokens compared case-insensitively
    for site in ("cross-site", "same-site", "bogus"):
        assert not navigation_may_carry_token({"sec-fetch-site": site, "sec-fetch-dest": "document"}), site
    for dest in ("iframe", "frame", "object", "embed", "empty", "script"):
        assert not navigation_may_carry_token({"sec-fetch-site": "same-origin", "sec-fetch-dest": dest}), dest


def test_static_assets_still_load_for_any_site(spa) -> None:
    """Assets carry no token: they stay reachable (the browser loads them for the SPA with dest=script/style)."""
    r = spa.get("/assets/index-abc.js", headers={"sec-fetch-site": "same-origin", "sec-fetch-dest": "script"})
    assert r.status_code == 200 and "pf" in r.text
    raw = spa.get("/index.html", headers={"sec-fetch-site": "cross-site", "sec-fetch-dest": "document"})
    assert "partforge-token" not in raw.text  # the raw file never carries the token


def test_every_response_forbids_framing(spa) -> None:
    """X-Frame-Options and CSP frame-ancestors on every response – SPA, 403 page, assets, API, refusals."""
    own = OWN_SPA_REQUESTS["none (desktop window, address bar)"]
    anon = TestClient(spa.app, base_url="http://127.0.0.1")  # no token header
    responses = {
        "index": spa.get("/altium", headers=own),
        "foreign page": spa.get("/altium?aktion=sync", headers=FOREIGN_SPA_REQUESTS["cross-site iframe"]),
        "asset": spa.get("/assets/index-abc.js"),
        "api": spa.get("/api/settings"),
        "health": spa.get("/api/health"),
        "api 404": spa.get("/api/does-not-exist"),
        "401": anon.get("/api/settings"),
        "421": spa.get("/", headers={"host": "rebind.attacker.example"}),
        "403 cross-site write": spa.post("/api/jobs/none/cancel", headers={"origin": "http://evil.example"}),
    }
    for name, r in responses.items():
        assert r.headers.get("x-frame-options") == "DENY", name
        assert "frame-ancestors 'none'" in r.headers.get("content-security-policy", ""), name


def test_frame_policy_is_merged_into_a_routes_own_csp() -> None:
    """The SVG previews send a sandbox policy of their own: it stays, frame-ancestors is added."""
    from partforge.api.routes_libraries import _SVG_POLICY

    merged = deny_framing(Response("<svg/>", headers={"Content-Security-Policy": _SVG_POLICY}))
    assert merged.headers["content-security-policy"] == f"{_SVG_POLICY}; frame-ancestors 'none'"
    assert merged.headers["x-frame-options"] == "DENY"
    plain = deny_framing(Response("x"))
    assert plain.headers["content-security-policy"] == "frame-ancestors 'none'"


# --------------------------------------------------------------------------- 2. executable/key path validation


def _exe(tmp_path, name="altium-designer-mcp.exe"):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"MZ")
    return str(p)


UNC_SPELLINGS = [
    r"\\attacker-host\share\evil.exe",
    "//attacker-host/share/evil.exe",
    r"\/attacker-host/share/evil.exe",  # Windows treats / and \ alike
    r"\\?\UNC\attacker-host\share\evil.exe",
    r"\\?\C:\Windows\System32\calc.exe",
    r"\\.\C:\evil.exe",
]


def test_put_settings_rejects_unsafe_writer_paths(bare_client, tmp_path) -> None:
    base = bare_client.get("/api/settings").json()["settings"]
    for bad in UNC_SPELLINGS:
        body = {**base, "altium": {**base["altium"], "rust_writer_path": bad}}
        r = bare_client.put("/api/settings", json=body)
        assert r.status_code == 400, (bad, r.status_code)
        assert "UNC" in r.json()["detail"] or "lokal" in r.json()["detail"]
    # a non-.exe or relative path is refused, a valid local .exe is accepted
    for bad in (str(tmp_path / "writer.bat"), "writer.exe", "C:writer.exe"):
        body = {**base, "altium": {**base["altium"], "rust_writer_path": bad}}
        assert bare_client.put("/api/settings", json=body).status_code == 400, bad
    good = _exe(tmp_path)
    body = {**base, "altium": {**base["altium"], "rust_writer_path": good}}
    r = bare_client.put("/api/settings", json=body)
    assert r.status_code == 200 and r.json()["rust_writer"] == good


def test_put_settings_requires_x2_exe_named_x2(bare_client, tmp_path) -> None:
    base = bare_client.get("/api/settings").json()["settings"]
    other = _exe(tmp_path, "AltiumNX.exe")  # exists, .exe, but not named X2.EXE
    body = {**base, "altium": {**base["altium"], "x2_path": other}}
    r = bare_client.put("/api/settings", json=body)
    assert r.status_code == 400 and "X2.EXE" in r.json()["detail"]
    # UNC is refused too
    body = {**base, "altium": {**base["altium"], "x2_path": r"\\host\share\X2.EXE"}}
    assert bare_client.put("/api/settings", json=body).status_code == 400
    good = _exe(tmp_path / "AD", "X2.EXE")
    body = {**base, "altium": {**base["altium"], "x2_path": good}}
    assert bare_client.put("/api/settings", json=body).status_code == 200


def test_put_settings_rejects_unc_key_file(bare_client, tmp_path) -> None:
    base = bare_client.get("/api/settings").json()["settings"]
    body = {**base, "ai": {**base["ai"], "api_key_file": r"\\host\share\key.txt"}}
    r = bare_client.put("/api/settings", json=body)
    assert r.status_code == 400 and ("UNC" in r.json()["detail"] or "lokal" in r.json()["detail"])
    # a relative path is refused (it would depend on the working directory)
    body = {**base, "ai": {**base["ai"], "api_key_file": "key.txt"}}
    r = bare_client.put("/api/settings", json=body)
    assert r.status_code == 400 and "absoluter Pfad" in r.json()["detail"]
    # a local path is accepted (existence/content are checked at read time)
    body = {**base, "ai": {**base["ai"], "api_key_file": str(tmp_path / "key.txt")}}
    assert bare_client.put("/api/settings", json=body).status_code == 200


def test_bridge_exchange_dir_must_be_local(bare_client, tmp_path) -> None:
    """Altium runs the script project PartForge writes into the exchange folder: never from a share."""
    base = bare_client.get("/api/settings").json()["settings"]
    for bad in (r"\\attacker-host\share\bridge", "//attacker-host/share/bridge", "relative\\bridge"):
        body = {**base, "altium": {**base["altium"], "bridge_exchange_dir": bad}}
        r = bare_client.put("/api/settings", json=body)
        assert r.status_code == 400 and "Austauschverzeichnis" in r.json()["detail"], bad
    body = {**base, "altium": {**base["altium"], "bridge_exchange_dir": str(tmp_path / "bridge")}}
    assert bare_client.put("/api/settings", json=body).status_code == 200
    # a hand-edited UNC folder is ignored at resolve time (the default folder is used)
    s = AppSettings(altium=AltiumSettings(bridge_exchange_dir=r"\\attacker-host\share\bridge"))
    assert s.resolved_bridge_exchange_dir() is None
    assert AppSettings(altium=AltiumSettings(bridge_exchange_dir=str(tmp_path))).resolved_bridge_exchange_dir() == tmp_path


def test_resolved_paths_ignore_unc_configured_values(monkeypatch, tmp_path) -> None:
    """A hand-edited settings.json with a UNC writer/X2 path is ignored, never executed (QA sec finding 2)."""
    monkeypatch.setattr(config, "detect_rust_writer", lambda: None)
    monkeypatch.setattr(config, "detect_altium_exe", lambda: None)
    s = AppSettings(altium=AltiumSettings(
        rust_writer_path=r"\\attacker-host\share\evil.exe", x2_path="//attacker-host/share/X2.EXE"))
    assert s.resolved_rust_writer() is None
    assert s.resolved_altium_exe() is None  # falls back to detection (None here), the UNC value is dropped


def test_altium_status_reports_an_ignored_unc_writer(client, monkeypatch) -> None:
    from partforge.config import load_settings

    monkeypatch.setattr(config, "detect_rust_writer", lambda: None)
    settings = load_settings()
    monkeypatch.setattr(settings.altium, "rust_writer_path", r"\\attacker-host\share\evil.exe")
    status = client.get("/api/altium/status").json()
    rust = next(b for b in status["backends"] if b["name"] == "rust")
    assert not rust["available"] and ("UNC" in rust["message"] or "nicht verwendet" in rust["message"])


def test_altium_status_names_why_a_local_writer_is_ignored(client, monkeypatch, tmp_path) -> None:
    """A hand-edited writer path to an existing non-.exe file is not run; the status says why (not "missing")."""
    from partforge.config import load_settings

    script = tmp_path / "writer.cmd"
    script.write_text("@echo off\r\n", encoding="ascii")
    monkeypatch.setattr(config, "detect_rust_writer", lambda: None)
    monkeypatch.setattr(load_settings().altium, "rust_writer_path", str(script))
    rust = next(b for b in client.get("/api/altium/status").json()["backends"] if b["name"] == "rust")
    assert not rust["available"] and "nicht verwendet" in rust["message"] and ".exe" in rust["message"]


# --------------------------------------------------------------------------- 2. key file content


def test_key_file_only_used_when_it_looks_like_an_anthropic_key(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # arbitrary file content is never used (no exfiltration of other files to the API)
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET company data, not a key\n", encoding="utf-8")
    s = AppSettings(ai={"api_key_file": str(secret)})
    assert config.read_api_key(s) is None
    assert config.api_key_source(s) is None
    assert "gültigen Claude-Schlüssel" in (config.key_file_status(s) or "")
    # a small file with an sk-ant key is used
    key = tmp_path / "key.txt"
    key.write_text("sk-ant-abc123\n", encoding="utf-8")
    s = AppSettings(ai={"api_key_file": str(key)})
    assert config.read_api_key(s) == "sk-ant-abc123"
    assert config.api_key_source(s) == "file" and config.key_file_status(s) is None
    # a file over the size limit is not read even if it starts with sk-ant
    big = tmp_path / "big.txt"
    big.write_text("sk-ant-" + "x" * (config.KEY_FILE_MAX_BYTES + 10), encoding="utf-8")
    s = AppSettings(ai={"api_key_file": str(big)})
    assert config.read_api_key(s) is None
    assert "größer" in (config.key_file_status(s) or "")
    # Notepad saves UTF-8 with a BOM – such a key file works as well
    bom = tmp_path / "bom.txt"
    bom.write_bytes("﻿sk-ant-abc123\r\n".encode())
    s = AppSettings(ai={"api_key_file": str(bom)})
    assert config.read_api_key(s) == "sk-ant-abc123" and config.key_file_status(s) is None


def test_first_start_enters_the_developer_key_file_only_outside_isolated_runs(monkeypatch, tmp_path) -> None:
    """The user allowed the ExampleProject key file: a first start on that PC enters it (never in isolated runs)."""
    key = tmp_path / ".claude-api-key.txt"
    key.write_text("sk-ant-abc123", encoding="utf-8")
    monkeypatch.setattr(config, "LEGACY_KEY_FILE", str(key))
    monkeypatch.delenv("PARTFORGE_NO_AI_KEY", raising=False)
    monkeypatch.setenv("PARTFORGE_HOME", str(tmp_path / "home"))
    assert config._first_start_settings().ai.api_key_file is None  # isolated run
    monkeypatch.delenv("PARTFORGE_HOME")
    assert config._first_start_settings().ai.api_key_file == str(key)
    key.unlink()
    assert config._first_start_settings().ai.api_key_file is None  # any other PC: no such file


def test_ai_status_says_the_key_file_holds_no_key(bare_client, monkeypatch, tmp_path) -> None:
    """A key file that points at some other file: the AI status names the problem, the content goes nowhere."""
    from partforge.config import load_settings

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_DIR", raising=False)  # replay mode reports a key of its own
    other = tmp_path / "notes.txt"
    other.write_text("Vertraulich: Kundenliste 4711\n", encoding="utf-8")
    monkeypatch.setattr(load_settings().ai, "api_key_file", str(other))
    status = bare_client.get("/api/ai/status")
    assert status.status_code == 200
    assert not status.json()["key_configured"]
    assert "keinen gültigen Claude-Schlüssel" in status.json()["key_file_problem"]
    assert "Kundenliste" not in status.text and "Kundenliste" not in bare_client.get("/api/settings").text


# --------------------------------------------------------------------------- 4. token redaction in logs


def test_redact_token_in_text() -> None:
    assert redact_token("GET /api/x?token=SECRET123&y=1") == "GET /api/x?token=<redigiert>&y=1"
    assert redact_token("/api/jobs/events?brief=true&token=abcDEF.-_") == "/api/jobs/events?brief=true&token=<redigiert>"
    assert "token" not in redact_token("?TOKEN=Secret").lower().replace("token=<redigiert>", "")


def test_redact_token_filter_on_access_log_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", "/api/jobs/events?brief=true&token=SUPERSECRETVALUE", "1.1", 200),
        None,
    )
    assert RedactTokenFilter().filter(record) is True
    message = record.getMessage()
    assert "SUPERSECRETVALUE" not in message and "token=<redigiert>" in message


@pytest.mark.parametrize("token", ["plain-token", "with.dots-and_underscores"])
def test_redact_token_filter_covers_msg_and_dict_args(token) -> None:
    rec = logging.LogRecord("partforge", logging.INFO, __file__, 0, f"opened url ?token={token}", None, None)
    RedactTokenFilter().filter(rec)
    assert token not in rec.getMessage()


def test_redact_token_filter_covers_tracebacks() -> None:
    try:
        raise RuntimeError("GET /api/datasheets/1/file?token=TRACEBACKSECRET failed")
    except RuntimeError:
        rec = logging.LogRecord("partforge", logging.ERROR, __file__, 0, "Fehler", None, sys.exc_info())
    RedactTokenFilter().filter(rec)
    formatted = logging.Formatter().format(rec)
    assert "TRACEBACKSECRET" not in formatted and "token=<redigiert>" in formatted


# --------------------------------------------------------------------------- live server (real HTTP parser)

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _raw(port: int, request_line: str, host: str) -> tuple[int, str]:
    """Send one raw HTTP/1.1 request (the request line exactly as given) and return (status, body)."""
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"{request_line}\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode("latin-1"))
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body.decode("utf-8", errors="replace")


@pytest.mark.parametrize("http", ["program", "h11"])
def test_live_server_rejects_foreign_and_absolute_form_hosts(http: str) -> None:
    """Real uvicorn: the Host check holds for raw requests, including an absolute-form request target that
    names a foreign host while the Host header says 127.0.0.1 (RFC 9112: the target's host counts)."""
    from partforge.__main__ import server_config

    app = create_app(token=TOKEN, allowed_hosts=frozenset())  # the real program's set: loopback only
    port = _free_port()
    cfg = (server_config(app, port) if http == "program"
           else uvicorn.Config(app, host="127.0.0.1", port=port, http="h11", log_config=None))
    server = uvicorn.Server(cfg)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started
        local = f"127.0.0.1:{port}"
        assert _raw(port, "GET /api/health HTTP/1.1", local)[0] == 200
        assert _raw(port, "GET /api/health HTTP/1.1", f"localhost:{port}")[0] == 200
        status, body = _raw(port, "GET / HTTP/1.1", f"rebind.attacker.example:{port}")
        assert status == 421 and TOKEN not in body and "partforge-token" not in body
        for target in (f"http://rebind.attacker.example:{port}/", f"http://rebind.attacker.example:{port}/api/health"):
            status, body = _raw(port, f"GET {target} HTTP/1.1", local)
            assert status == 421 and TOKEN not in body, (target, status)
        # an absolute-form target naming the loopback host itself is not a foreign host
        assert _raw(port, f"GET http://{local}/api/health HTTP/1.1", local)[0] != 421
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_verbose_server_never_logs_the_token(tmp_path: Path) -> None:
    """``--verbose`` logs every request URL (uvicorn access log): ``?token=`` must be redacted in
    ``partforge.log`` and on the console (QA sec finding 4)."""
    secret = "LIVE-SECRET-token-4711"
    home = tmp_path / "home"
    port = _free_port()
    env = {**os.environ, "PARTFORGE_HOME": str(home), "PARTFORGE_NO_ALTIUM": "1", "PARTFORGE_TOKEN": secret,
           "PYTHONIOENCODING": "utf-8"}
    env["PARTFORGE_TEST_HOSTS"] = "rebind.attacker.example"  # the real program must ignore the test hook
    env.pop("PARTFORGE_ALLOW_REAL_AI", None)
    proc = subprocess.Popen([sys.executable, "-m", "partforge", "--server-only", "--verbose", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 30
        while True:
            try:
                if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            assert time.time() < deadline, "Server startet nicht"
            time.sleep(0.2)
        assert httpx.get(f"{base}/api/jobs", params={"token": secret, "brief": "true"}).status_code == 200
        assert httpx.get(f"{base}/api/settings?token={secret}").status_code == 200
        for host in ("rebind.attacker.example", "testserver"):  # loopback only, whatever the environment says
            assert httpx.get(f"{base}/", headers={"host": host}).status_code == 421, host
        # a foreign website's navigation to an action URL: 403 page, neither token nor query (sec-spa-crosssite-aktion)
        foreign = httpx.get(f"{base}/altium?aktion=dblib", headers={"sec-fetch-site": "cross-site",
                                                                      "sec-fetch-mode": "navigate",
                                                                      "sec-fetch-dest": "document"})
        assert foreign.status_code == 403 and secret not in foreign.text and "aktion" not in foreign.text
        assert foreign.headers["x-frame-options"] == "DENY"
        with httpx.stream("GET", f"{base}/api/jobs/events", params={"brief": "true", "token": secret},
                          timeout=10) as events:  # SSE: the browser's EventSource sends ?token=
            assert events.status_code == 200
            # the frame ban reaches streaming responses too
            assert "frame-ancestors 'none'" in events.headers["content-security-policy"]
            next(events.iter_raw())
        time.sleep(0.5)  # let the access log reach the file
    finally:
        proc.kill()
        out, _ = proc.communicate(timeout=30)
    log_text = (home / "logs" / "partforge.log").read_text(encoding="utf-8", errors="replace")
    console = out.decode("utf-8", errors="replace")
    assert "/api/jobs?" in log_text and "token=<redigiert>" in log_text  # the access log is there, redacted
    assert secret not in log_text, "Token im partforge.log"
    assert secret not in console, "Token in der Konsolenausgabe"
