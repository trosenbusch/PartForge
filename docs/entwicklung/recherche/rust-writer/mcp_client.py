"""Minimal stdlib-only MCP (stdio, JSON-RPC 2.0, newline-delimited) client
for the standalone Rust server ``altium-designer-mcp.exe`` (v0.1.0).

The server is GPL-3.0; it is only ever spawned as a separate process here.

Usage as a library::

    from mcp_client import McpClient
    with McpClient() as c:                      # spawns + initialize + initialized
        tools = c.list_tools()
        res = c.call_tool("list_components", {"filepath": ".../x.PcbLib"})

Usage from the command line::

    python mcp_client.py tools                  # dump tools/list (names)
    python mcp_client.py schema write_pcblib    # print one tool's inputSchema
    python mcp_client.py call <tool> '<json>'   # call a tool (or @file.json)
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from typing import Any

DEFAULT_EXE = "C:/PartForge-Examples/MCP/altium-designer-mcp-windows-x86_64/altium-designer-mcp.exe"
HERE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
DEFAULT_CONFIG = HERE + "/config.json"
OUT = HERE + "/out"


class McpError(Exception):
    """JSON-RPC level error (protocol / unknown tool / invalid params)."""

    def __init__(self, error: dict[str, Any]):
        self.error = error
        super().__init__(f"JSON-RPC error {error.get('code')}: {error.get('message')}")


class ToolError(Exception):
    """Tool executed but reported isError=true."""

    def __init__(self, tool: str, text: str, result: dict[str, Any]):
        self.tool = tool
        self.text = text
        self.result = result
        super().__init__(f"{tool} failed: {text}")


class McpClient:
    def __init__(
        self,
        exe: str = DEFAULT_EXE,
        config: str | None = DEFAULT_CONFIG,
        verbose: int = 0,
        timeout: float = 300.0,
        auto_init: bool = True,
        protocol_version: str = "2025-06-18",
    ):
        args = [exe]
        if verbose:
            args.append("-" + "v" * verbose)
        if config:
            args.append(config)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            creationflags=creationflags,
        )
        self.timeout = timeout
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue] = {}
        self.stderr_lines: list[str] = []
        self.server_messages: list[dict[str, Any]] = []  # notifications / server->client requests
        self.server_info: dict[str, Any] | None = None
        self._t_out = threading.Thread(target=self._read_stdout, daemon=True)
        self._t_err = threading.Thread(target=self._read_stderr, daemon=True)
        self._t_out.start()
        self._t_err.start()
        if auto_init:
            self.initialize(protocol_version)

    # ------------------------------------------------------------------ io
    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.stderr_lines.append("[non-json stdout] " + line)
                continue
            if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
                q = self._pending.pop(msg["id"], None)
                if q is not None:
                    q.put(msg)
                continue
            self.server_messages.append(msg)
            if "id" in msg and "method" in msg:  # server -> client request
                if msg["method"] == "ping":
                    self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                else:
                    self._send({"jsonrpc": "2.0", "id": msg["id"],
                                "error": {"code": -32601, "message": "Method not found"}})
        for q in list(self._pending.values()):  # EOF -> wake waiters
            q.put(None)

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for raw in self.proc.stderr:
            self.stderr_lines.append(raw.decode("utf-8", errors="replace").rstrip())

    def _send(self, obj: dict[str, Any]) -> None:
        data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
        assert self.proc.stdin is not None
        with self._write_lock:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()

    # ------------------------------------------------------------- jsonrpc
    def request(self, method: str, params: dict[str, Any] | None = None,
                timeout: float | None = None) -> dict[str, Any]:
        with self._id_lock:
            rid = self._next_id
            self._next_id += 1
        q: queue.Queue = queue.Queue(maxsize=1)
        self._pending[rid] = q
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)
        try:
            resp = q.get(timeout=timeout or self.timeout)
        except queue.Empty:
            self._pending.pop(rid, None)
            raise TimeoutError(f"{method}: no response within {timeout or self.timeout}s")
        if resp is None:
            raise McpError({"code": -1, "message": "server closed stdout",
                            "stderr_tail": self.stderr_lines[-20:]})
        if "error" in resp:
            raise McpError(resp["error"])
        return resp["result"]

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    # ----------------------------------------------------------------- mcp
    def initialize(self, protocol_version: str = "2025-06-18") -> dict[str, Any]:
        self.server_info = self.request("initialize", {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "partforge-probe", "version": "0.0.1"},
        })
        self.notify("notifications/initialized")
        return self.server_info

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = None
        while True:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(res.get("tools", []))
            cursor = res.get("nextCursor")
            if not cursor:
                return tools

    def call_tool_raw(self, name: str, arguments: dict[str, Any],
                      timeout: float | None = None) -> dict[str, Any]:
        """Return the raw MCP CallToolResult ({content:[...], isError, ...})."""
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout)

    def call_tool(self, name: str, arguments: dict[str, Any],
                  timeout: float | None = None) -> Any:
        """Call a tool; return parsed JSON payload (or text). Raise ToolError on isError."""
        res = self.call_tool_raw(name, arguments, timeout)
        text = "\n".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise ToolError(name, text, res)
        if "structuredContent" in res:
            return res["structuredContent"]
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return text

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def __enter__(self) -> "McpClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    with McpClient() as c:
        if argv[0] == "tools":
            for t in c.list_tools():
                print(t["name"])
        elif argv[0] == "schema":
            for t in c.list_tools():
                if t["name"] == argv[1]:
                    print(json.dumps(t, indent=2))
        elif argv[0] == "call":
            raw = argv[2]
            if raw.startswith("@"):
                with open(raw[1:], encoding="utf-8") as fh:
                    raw = fh.read()
            t0 = time.perf_counter()
            res = c.call_tool_raw(argv[1], json.loads(raw))
            dt = time.perf_counter() - t0
            print(json.dumps(res, indent=2, ensure_ascii=False))
            print(f"# {dt*1000:.1f} ms", file=sys.stderr)
        else:
            print(__doc__)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
