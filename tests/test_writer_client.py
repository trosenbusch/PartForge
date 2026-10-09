"""RustMcpClient protocol handling against a fake MCP server (no real writer needed)."""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from partforge.altium.rustwriter import (
    RustMcpClient,
    RustProcessError,
    RustTimeoutError,
    RustToolError,
    RustWriterUnavailable,
    audit_log_path,
    parse_tool_result,
)

FAKE_SERVER = textwrap.dedent(
    r'''
    import json, os, sys, time

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    config_path = sys.argv[-1]
    with open(config_path, encoding="utf-8") as fh:
        config = json.load(fh)
    state_dir = os.path.dirname(os.path.abspath(__file__))

    def bump(name):
        path = os.path.join(state_dir, name + ".count")
        count = int(open(path).read()) if os.path.exists(path) else 0
        count += 1
        with open(path, "w") as fh:
            fh.write(str(count))
        return count

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()

    def text_result(rid, payload, is_error=False):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        result = {"content": [{"type": "text", "text": text}]}
        if is_error:
            result["isError"] = True
        send({"jsonrpc": "2.0", "id": rid, "result": result})

    sys.stderr.write("fake server banner\n")
    sys.stderr.flush()
    initialized = False
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        rid = msg.get("id")
        if method == "initialize":
            initialized = True
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fake", "version": "9.9.9"}}})
            continue
        if method == "notifications/initialized" or rid is None:
            continue
        if not initialized:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32600, "message": "Server not initialised"}})
            continue
        if method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": [{"name": "echo", "inputSchema": {}}]}})
            continue
        if method != "tools/call":
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})
            continue
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        if name == "echo":
            text_result(rid, {"status": "success", "args": args, "pid": os.getpid()})
        elif name == "config":
            text_result(rid, {"status": "success", "config": config, "config_path": config_path})
        elif name == "fail":
            text_result(rid, "Access denied: path is outside the configured allowed directories", is_error=True)
        elif name == "fail_json":
            text_result(rid, {"error": "Duplicate symbol name: 'P0'", "details": "unique names", "status": "error"}, is_error=True)
        elif name == "status_error":
            text_result(rid, {"status": "error", "error": "something broke"})
        elif name == "plain":
            text_result(rid, "just text")
        elif name == "slow":
            time.sleep(5)
            text_result(rid, {"status": "success"})
        elif name == "list_components":  # read-only: crash on the first call only
            if bump("list") == 1:
                os._exit(3)
            text_result(rid, {"status": "success", "components": ["A"]})
        elif name == "write_pcblib":  # mutating: always crash
            os._exit(4)
        elif name == "write_schlib":  # rate limited twice
            if bump("rate") <= 2:
                text_result(rid, "Rate limit exceeded: too many write operations in a short period.", is_error=True)
            else:
                text_result(rid, {"status": "success", "symbol_names": ["X"]})
        elif name == "pingme":
            send({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
            reply = json.loads(sys.stdin.readline())
            text_result(rid, {"status": "success", "reply": reply})
        else:
            text_result(rid, "Unknown tool: " + name, is_error=True)
    '''
)


@pytest.fixture
def fake_server(tmp_path: Path) -> Path:
    script = tmp_path / "fake_server" / "server.py"
    script.parent.mkdir()
    script.write_text(FAKE_SERVER, encoding="utf-8")
    return script


@pytest.fixture
def client(fake_server: Path, tmp_path: Path):
    allowed = tmp_path / "lib"
    allowed.mkdir()
    c = RustMcpClient(
        sys.executable,
        extra_args=[str(fake_server)],
        allowed_dirs=[allowed],
        runtime_dir=tmp_path / "runtime",
        request_timeout=10,
    )
    try:
        yield c
    finally:
        c.close()


def test_handshake_and_call(client):
    result = client.call_tool("echo", {"a": 1, "text": "Ω µ ±"})
    assert result["args"] == {"a": 1, "text": "Ω µ ±"}
    assert client.server_version == "9.9.9"
    assert client.running
    assert "fake server banner" in "\n".join(client.stderr_tail)
    assert client.list_tools()[0]["name"] == "echo"


def test_generated_config(client, tmp_path):
    data = client.call_tool("config", {})
    config = data["config"]
    assert config["allowed_paths"] == [(tmp_path / "lib").as_posix()]
    assert config["logging"]["audit_log_path"] == audit_log_path().as_posix()
    assert config["rate_limit"]["max_burst"] >= 120
    config_file = Path(data["config_path"])
    assert config_file.exists() and config_file.parent == tmp_path / "runtime"
    client.close()
    assert not config_file.exists()


def test_tool_errors_are_german_and_keep_details(client):
    with pytest.raises(RustToolError) as exc:
        client.call_tool("fail", {})
    assert "Zugriff verweigert" in str(exc.value)
    assert exc.value.tool == "fail"
    with pytest.raises(RustToolError) as exc:
        client.call_tool("fail_json", {})
    assert exc.value.details and exc.value.details["error"].startswith("Duplicate")
    assert "Duplicate symbol name" in str(exc.value)
    with pytest.raises(RustToolError, match="something broke"):
        client.call_tool("status_error", {})
    with pytest.raises(RustToolError, match="Unknown tool"):
        client.call_tool("no_such_tool", {})
    assert client.call_tool("plain", {}) == {"text": "just text"}


def test_timeout_kills_and_next_call_restarts(client):
    first_pid = client.call_tool("echo", {})["pid"]
    with pytest.raises(RustTimeoutError) as exc:
        client.call_tool("slow", {}, timeout=0.5)
    assert "nicht innerhalb" in str(exc.value)
    assert not client.running
    second_pid = client.call_tool("echo", {})["pid"]
    assert second_pid != first_pid
    assert client.restarts == 1


def test_read_only_tool_is_retried_after_crash(client):
    assert client.call_tool("list_components", {})["components"] == ["A"]
    assert client.restarts == 1


def test_mutating_tool_crash_is_reported(client):
    with pytest.raises(RustProcessError) as exc:
        client.call_tool("write_pcblib", {})
    assert "unerwartet beendet" in str(exc.value)
    assert client.call_tool("echo", {"ok": True})["args"] == {"ok": True}


def test_rate_limit_is_retried(client):
    result = client.call_tool("write_schlib", {})
    assert result["symbol_names"] == ["X"]


def test_server_ping_request_is_answered(client):
    reply = client.call_tool("pingme", {})["reply"]
    assert reply == {"jsonrpc": "2.0", "id": "srv-1", "result": {}}


def test_ensure_allowed_restarts_only_when_needed(client, tmp_path):
    pid = client.call_tool("echo", {})["pid"]
    client.ensure_allowed([tmp_path / "lib" / "sub"])  # covered -> no restart
    assert client.call_tool("echo", {})["pid"] == pid
    other = tmp_path / "other"
    other.mkdir()
    client.ensure_allowed([other])
    data = client.call_tool("config", {})
    assert other.as_posix() in data["config"]["allowed_paths"]
    assert client.call_tool("echo", {})["pid"] != pid
    client.ensure_allowed([other], exact=True)
    assert client.call_tool("config", {})["config"]["allowed_paths"] == [other.as_posix()]


def test_missing_executable(tmp_path):
    c = RustMcpClient(tmp_path / "missing.exe", allowed_dirs=[tmp_path], runtime_dir=tmp_path / "rt")
    with pytest.raises(RustWriterUnavailable) as exc:
        c.call_tool("echo", {})
    assert "nicht gestartet" in str(exc.value)


def test_parse_tool_result_defensive():
    assert parse_tool_result("t", {"content": [{"type": "text", "text": json.dumps({"status": "success", "a": 1})}]}) == {
        "status": "success",
        "a": 1,
    }
    assert parse_tool_result("t", {"content": [{"type": "text", "text": "[1, 2]"}]}) == {"data": [1, 2]}
    assert parse_tool_result("t", {"structuredContent": {"x": 1}, "content": []}) == {"x": 1}
    with pytest.raises(RustProcessError):
        parse_tool_result("t", ["not a dict"])
    with pytest.raises(RustToolError) as exc:
        parse_tool_result("t", {"isError": True, "content": [{"type": "text", "text": "Rate limit exceeded: slow down"}]})
    assert exc.value.rate_limited
    with pytest.raises(RustToolError) as exc:
        parse_tool_result("t", {"isError": True, "content": [{"type": "text", "text": "Component 'X' not found in library"}]})
    assert exc.value.not_found
