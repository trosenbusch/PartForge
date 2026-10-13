"""AltiumBridge with a fake exchange partner (no Altium needed)."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from test_writer_samples import chip_0603, resistor_symbol

from partforge.altium.bridge.core import (
    PROJECT_FILE,
    RECOVERY_HINT,
    RESOLVE_BATCH_SIZE,
    SCRIPT_UNITS,
    AltiumBridge,
    AltiumNotRunning,
    BridgeBusyError,
    BridgeCommandError,
    BridgeError,
    BridgeWedgedError,
    altium_safe_path,
    canonical_path,
    default_exchange_dir,
    parse_db_parameters,
)
from partforge.altium.bridge.protocol import escape_field, unescape_field

X2 = r"C:\Program Files\Altium\AD22\X2.EXE"

Handler = Callable[[str, dict[str, str]], list[str]]


class FakeAltium:
    """Plays the Pascal side: reads request.txt, writes the step log and the response."""

    def __init__(self, exchange: Path, handler: Handler | None = None, *, mode: str = "ok", delay: float = 0.02):
        self.exchange = exchange
        self.handler = handler or (lambda command, args: [])
        self.mode = mode
        self.delay = delay
        self.command_lines: list[str] = []
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.errors: list[BaseException] = []

    def __call__(self, command_line: str) -> None:
        self.command_lines.append(command_line)
        if self.mode == "dead":
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _write(self, path: Path, lines: list[str]) -> None:
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))

    def _run(self) -> None:
        try:
            time.sleep(self.delay)
            request = (self.exchange / "request.txt").read_text(encoding="ascii").splitlines()
            rid = command = ""
            args: dict[str, str] = {}
            for line in request:
                tag, _, rest = line.partition("|")
                if tag == "ID":
                    rid = rest
                elif tag == "COMMAND":
                    command = rest
                elif tag == "ARG":
                    key, _, value = rest.partition("|")
                    args[key] = unescape_field(value)
            assert request[-1] == f"END|{rid}"
            self.requests.append((command, args))
            log = self.exchange / f"log_{rid}.txt"
            self._write(log, ["100 started", f"101 command {command}", "102 create free SCHLIB"])
            if self.mode == "wedge":
                return
            try:
                body = self.handler(command, args)
                status = ["STATUS|OK"]
            except Exception as exc:  # noqa: BLE001 - becomes an ERROR response
                body = []
                status = ["STATUS|ERROR", "ERROR|" + escape_field(str(exc))]
            lines = ["PFRES|1", f"ID|{rid}", *status, *body]
            response = self.exchange / f"response_{rid}.txt"
            if self.mode == "partial":
                self._write(response, lines)
                time.sleep(0.4)
            self._write(response, [*lines, f"END|{rid}"])
            self._write(log, ["100 started", f"101 command {command}", "103 finished"])
        except BaseException as exc:  # noqa: BLE001 - surfaced by the tests
            self.errors.append(exc)


def make_bridge(tmp_path: Path, fake: FakeAltium | None = None, *, running: Callable[[], bool] | None = None, **kw) -> tuple[AltiumBridge, FakeAltium]:
    exchange = tmp_path / "exchange"
    fake = fake or FakeAltium(exchange)
    fake.exchange = exchange
    bridge = AltiumBridge(
        exchange_dir=exchange,
        x2_path=X2,
        timeout_s=kw.pop("timeout_s", 5.0),
        start_timeout_s=kw.pop("start_timeout_s", 2.0),
        poll_interval_s=0.02,
        lock_timeout_s=kw.pop("lock_timeout_s", 5.0),
        launcher=fake,
        process_check=running or (lambda: True),
        process_check_interval_s=0.1,
        **kw,
    )
    return bridge, fake


def test_default_exchange_dir_is_own_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_exchange_dir() == tmp_path / "PartForge" / "bridge"
    assert "altium_mcp" not in str(default_exchange_dir())


def test_command_line_format(tmp_path):
    bridge, _ = make_bridge(tmp_path)
    prj = Path(r"C:\Users\X\AppData\Local\PartForge\bridge\script\PartForgeBridge.PrjScr")
    assert bridge.command_line(prj) == (
        '"C:\\Program Files\\Altium\\AD22\\X2.EXE" -RScriptingSystem:RunScript('
        'ProjectName="C:\\Users\\X\\AppData\\Local\\PartForge\\bridge\\script\\PartForgeBridge.PrjScr"'
        '|ProcName="PartForgeBridge>Run")'
    )
    no_x2 = AltiumBridge(exchange_dir=tmp_path / "e", x2_path=None)
    with pytest.raises(BridgeError, match=r"X2\.EXE"):
        no_x2.command_line(prj)


def test_ensure_scripts_deploys_project(tmp_path):
    bridge, _ = make_bridge(tmp_path)
    prj = bridge.ensure_scripts()
    assert prj == bridge.exchange_dir / "script" / PROJECT_FILE
    for name in (*SCRIPT_UNITS, PROJECT_FILE):
        data = (prj.parent / name).read_bytes()
        assert data.isascii() and b"\r\n" in data and b"@@PF_EXCHANGE_DIR@@" not in data
    utils = (prj.parent / "PFUtils.pas").read_text(encoding="ascii")
    expected = str(bridge.exchange_dir.resolve()) + "\\"
    assert f"PF_EXCHANGE_DIR = '{expected}';" in utils
    project = (prj.parent / PROJECT_FILE).read_text(encoding="ascii")
    assert [line.split("=", 1)[1] for line in project.splitlines() if line.startswith("DocumentPath=")] == list(SCRIPT_UNITS)
    stamps = {n: (prj.parent / n).stat().st_mtime_ns for n in SCRIPT_UNITS}
    time.sleep(0.02)
    bridge.ensure_scripts()
    assert stamps == {n: (prj.parent / n).stat().st_mtime_ns for n in SCRIPT_UNITS}


def test_ensure_scripts_escapes_quotes_in_path(tmp_path):
    bridge = AltiumBridge(exchange_dir=tmp_path / "O'Brien" / "bridge", x2_path=X2)
    utils = (bridge.ensure_scripts().parent / "PFUtils.pas").read_text(encoding="ascii")
    assert "O''Brien" in utils


def test_ping_roundtrip_and_cleanup(tmp_path):
    bridge, fake = make_bridge(
        tmp_path, FakeAltium(tmp_path, lambda c, a: ["KV|version|26.10.1.5", "KV|pcb_server|1"])
    )
    assert bridge.ping() == "26.10.1.5"
    assert not fake.errors
    assert fake.requests == [("ping", {})]
    assert fake.command_lines == [bridge.command_line(bridge.project_path)]
    leftovers = {p.name for p in bridge.exchange_dir.iterdir() if p.is_file()}
    assert leftovers <= {"bridge.lock"}  # request, response and log removed after success


def test_arguments_survive_escaping(tmp_path):
    captured: dict[str, str] = {}

    def handler(command: str, args: dict[str, str]) -> list[str]:
        captured.update(args)
        return ["KV|installed|1"]

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    target = tmp_path / "Widerstände | 100%.DbLib"
    assert bridge.install_library(target) is True
    assert captured["path"] == str(canonical_path(target))


def test_error_response_raises_command_error_and_keeps_log(tmp_path):
    def handler(command, args):
        raise RuntimeError("library file not found: X.DbLib")

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    with pytest.raises(BridgeCommandError) as exc:
        bridge.install_library(tmp_path / "X.DbLib")
    assert "library file not found" in str(exc.value) and exc.value.command == "install_library"
    assert list(bridge.exchange_dir.glob("log_*.txt"))


def test_not_running_never_launches(tmp_path):
    bridge, fake = make_bridge(tmp_path, running=lambda: False)
    with pytest.raises(AltiumNotRunning, match="nicht gestartet"):
        bridge.ping()
    assert fake.command_lines == []
    status = bridge.status()
    assert not status.available and status.message == "Altium Designer ist nicht gestartet."


def test_script_never_started_is_reported_as_wedge(tmp_path):
    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, mode="dead"), start_timeout_s=0.3)
    started = time.monotonic()
    with pytest.raises(BridgeWedgedError) as exc:
        bridge.ping()
    assert time.monotonic() - started < 3
    assert exc.value.kind == "never_started"
    assert "Strg+F3" in str(exc.value) and RECOVERY_HINT in str(exc.value)
    assert bridge.last_wedge is not None and bridge.last_wedge["kind"] == "never_started"


def test_script_started_but_not_finished(tmp_path):
    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, mode="wedge"), timeout_s=0.6)
    with pytest.raises(BridgeWedgedError) as exc:
        bridge.ping()
    assert exc.value.kind == "did_not_finish"
    assert exc.value.last_step == "create free SCHLIB"
    assert "letzter Schritt: create free SCHLIB" in str(exc.value)
    # a later successful call clears the wedge marker
    bridge._launcher = FakeAltium(bridge.exchange_dir, lambda c, a: ["KV|version|26"])
    assert bridge.ping() == "26"
    assert bridge.last_wedge is None


def test_partial_response_is_not_read_early(tmp_path):
    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, lambda c, a: ["KV|version|26.10"], mode="partial"))
    assert bridge.ping() == "26.10"


def test_altium_closed_during_wait(tmp_path):
    calls = {"n": 0}

    def running() -> bool:
        calls["n"] += 1
        return calls["n"] == 1

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, mode="wedge"), running=running, timeout_s=3)
    with pytest.raises(AltiumNotRunning, match="beendet"):
        bridge.ping()


LOCK_HOLDER = textwrap.dedent(
    """
    import msvcrt, sys, time
    fh = open(sys.argv[1], "a+b")
    fh.seek(0)
    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    print("locked", flush=True)
    time.sleep(20)
    """
)


@pytest.mark.skipif(os.name != "nt", reason="Windows-Dateisperre")
def test_cross_process_lock(tmp_path):
    bridge, fake = make_bridge(tmp_path, lock_timeout_s=0.4)
    bridge.exchange_dir.mkdir(parents=True, exist_ok=True)
    holder = subprocess.Popen(
        [sys.executable, "-c", LOCK_HOLDER, str(bridge.exchange_dir / "bridge.lock")],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "locked"
        with pytest.raises(BridgeBusyError, match="anderen PartForge"):
            bridge.ping()
        assert fake.command_lines == []
    finally:
        holder.kill()
        holder.wait()
    fake.handler = lambda c, a: ["KV|version|26"]
    assert bridge.ping() == "26"


def test_write_schlib_flow(tmp_path):
    seen: dict[str, str] = {}

    def handler(command: str, args: dict[str, str]) -> list[str]:
        spec_path = Path(args["spec"])
        seen["spec"] = spec_path.read_bytes().decode("ascii")
        seen["keep_open"] = args["keep_open"]
        Path(args["path"]).write_bytes(b"fake schlib")
        return ["ITEM|written|PF_RES", "KV|created|1", "KV|save_result|-1", "WARN|Hinweis aus Altium"]

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    target = tmp_path / "out" / "PF_Test.SchLib"
    result = bridge.write_schlib(target, [resistor_symbol()])
    assert target.read_bytes() == b"fake schlib"
    assert result.written == ["PF_RES"] and result.created == 1
    assert "Hinweis aus Altium" in result.warnings
    assert seen["spec"].startswith("PFSPEC|1|SCHLIB\r\nSYMBOL|PF_RES|")
    assert seen["keep_open"] == "0"
    assert not list(bridge.exchange_dir.glob("spec_*.txt"))
    with pytest.raises(BridgeError, match="existiert bereits"):
        bridge.write_schlib(target, [resistor_symbol()])


def test_write_pcblib_reports_missing_components(tmp_path):
    def handler(command: str, args: dict[str, str]) -> list[str]:
        Path(args["path"]).write_bytes(b"fake pcblib")
        return ["KV|created|0"]

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    result = bridge.write_pcblib(tmp_path / "PF_CHIP.PcbLib", [chip_0603()])
    assert result.written == [] and any("nicht erzeugt" in w for w in result.warnings)


def _res_row(index: int, *fields: str) -> str:
    """``ROW|res|<index>|loaded|pins|symbol_path|symbol_ref|lib_ref|item|description|designator|comment|hidden``."""
    assert len(fields) == 10
    return "|".join(["ROW", "res", str(index), *(escape_field(f) for f in fields)])


def resolve_answer(keys: list[tuple[str, str]], known: dict[str, list[str]]) -> list[str]:
    """What PFCmdResolveDbComponents answers: ``known`` key -> extra rows of that key (index filled in)."""
    lines = ["KV|temporarily_installed|0"]
    for index, (_table, key) in enumerate(keys):
        lines.append(f"ROW|raw|{index}|")
        if key in known:
            lines.append(_res_row(index, "1", "2", "C:/Lib/Symbols/PF_Passives.SchLib", "Resistor", "Resistor", key,
                                  "RES", "R?", key + "-Comment", "0"))
            lines.extend(row.replace("{i}", str(index)) for row in known[key])
        else:
            lines.append(_res_row(index, "0", "", "", "", "", "", "", "", "", ""))
    lines.append(f"KV|count|{len(keys)}")
    return lines


def _keys_of(args: dict[str, str]) -> list[tuple[str, str]]:
    return [(args[f"table{i}"], args[f"key{i}"]) for i in range(int(args["count"]))]


def test_resolve_db_component(tmp_path):
    def handler(command: str, args: dict[str, str]) -> list[str]:
        assert command == "resolve_db_components" and args["count"] == "1"
        assert (args["table0"], args["key0"]) == ("Resistors", "RC0603FR-0710KL")
        raw = "ParameterName0=Part Number|ParameterValue0=RC0603FR-0710KL|ModelType0=PCBLIB|ModelName0=RESC1608X55N|ParameterName1=Value|ParameterValue1=10k"
        return [
            "KV|temporarily_installed|1",
            f"ROW|raw|0|{escape_field(raw)}",
            _res_row(0, "1", "2", "C:/Lib/Symbols/PF_Passives.SchLib", "PF_RES", "PF_RES", "RC0603FR-0710KL",
                     "RES 0603", "R?", "10k", "0"),
            "ROW|models|0|PCBLIB|RESC1608X55N|1",
            "ROW|models|0|PCBLIB|RESC1608X55L|0",
            "ROW|models|0|SIM|R_SIM|0",
            "ROW|parameters|0|Value|10k|1",
            f"ROW|parameters|0|Tolerance|{escape_field('±1 %')}|1",
            "ROW|parameters|0|Datasheet|x|0",
            "KV|count|1",
            "KV|released|1",
        ]

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    res = bridge.resolve_db_component(tmp_path / "PartForge.DbLib", "Resistors", "RC0603FR-0710KL")
    assert res.loaded and res.symbol_ref == "PF_RES" and res.pin_count == 2
    assert res.symbol_path == "C:/Lib/Symbols/PF_Passives.SchLib" and res.design_item_id == "RC0603FR-0710KL"
    assert res.footprints == ["RESC1608X55N", "RESC1608X55L"] and res.current_footprint == "RESC1608X55N"
    assert res.parameters == {"Value": "10k", "Tolerance": "±1 %", "Datasheet": "x"}
    assert res.visible_parameters == ["Datasheet"]
    assert res.temporarily_installed and res.designator == "R?" and res.description == "RES 0603"
    assert res.comment == "10k" and res.comment_visible is True
    assert res.released is True  # hidden DbLib document closed before the temporary uninstall


def test_resolve_db_component_installed_dblib_reports_no_release(tmp_path):
    def handler(command: str, args: dict[str, str]) -> list[str]:
        return resolve_answer(_keys_of(args), {})

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    res = bridge.resolve_db_component(tmp_path / "PartForge.DbLib", "Resistors", "X")
    assert not res.temporarily_installed and res.released is None and not res.loaded
    assert res.comment_visible is None and res.pin_count is None and res.footprints == []
    params_only = parse_db_parameters("ParameterName0=Value|ParameterValue0=1k|ModelName0=FP1")
    assert params_only == ({"Value": "1k"}, ["FP1"])


def test_resolve_db_components_batches_and_keeps_the_order(tmp_path):
    runs: list[list[tuple[str, str]]] = []

    def handler(command: str, args: dict[str, str]) -> list[str]:
        assert command == "resolve_db_components" and args["dblib"].endswith("PartForge.DbLib")
        keys = _keys_of(args)
        runs.append(keys)
        known = {key: ["ROW|models|{i}|PCBLIB|FP-" + key + "|1"] for _, key in keys if not key.endswith("7")}
        return resolve_answer(keys, known)

    bridge, fake = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    keys = [("Resistors" if i % 2 else "Capacitors", f"PN-{i:03d}") for i in range(RESOLVE_BATCH_SIZE * 2 + 7)]
    results = bridge.resolve_db_components(tmp_path / "PartForge.DbLib", keys)
    assert [len(run) for run in runs] == [RESOLVE_BATCH_SIZE, RESOLVE_BATCH_SIZE, 7]  # one script run per batch
    assert [(r.table, r.key) for r in results] == keys
    for result in results:
        if result.key.endswith("7"):
            assert not result.loaded and result.footprints == []  # unknown key: not loaded, no error
        else:
            assert result.loaded and result.footprints == ["FP-" + result.key] and result.design_item_id == result.key
            assert result.comment == result.key + "-Comment" and result.comment_visible is True
    assert len(fake.command_lines) == 3
    assert bridge.resolve_db_components(tmp_path / "PartForge.DbLib", []) == [] and len(fake.command_lines) == 3


def test_resolve_db_components_escapes_keys(tmp_path):
    seen: list[dict[str, str]] = []

    def handler(command: str, args: dict[str, str]) -> list[str]:
        seen.append(args)
        return resolve_answer(_keys_of(args), {})

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    bridge.resolve_db_components(tmp_path / "PartForge.DbLib", [("Widerstände", "R|1 µ"), ("Caps", "C 1")])
    assert (seen[0]["table0"], seen[0]["key0"], seen[0]["key1"]) == ("Widerstände", "R|1 µ", "C 1")


@pytest.mark.parametrize(
    "answer",
    [
        ["KV|temporarily_installed|0", "KV|count|1"],  # key without a result row
        ["KV|temporarily_installed|0"],  # script stopped before reporting the count
        ["KV|count|2", _res_row(0, "0", "", "", "", "", "", "", "", "", "")],  # count of another request
        ["KV|count|1", "ROW|res|0|1|2"],  # truncated result row
    ],
)
def test_incomplete_batch_answer_is_an_error(tmp_path, answer):
    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, lambda command, args: answer))
    with pytest.raises(BridgeCommandError, match="resolve_db_components"):
        bridge.resolve_db_components(tmp_path / "PartForge.DbLib", [("Resistors", "X")])


def test_batch_failure_is_reported(tmp_path):
    def handler(command: str, args: dict[str, str]) -> list[str]:
        raise RuntimeError("DbLib not found: C:\\x\\PartForge.DbLib")

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    with pytest.raises(BridgeCommandError, match="DbLib not found"):
        bridge.resolve_db_components(tmp_path / "PartForge.DbLib", [("Resistors", "X")])


def test_parse_db_parameters():
    params, models = parse_db_parameters(
        "ParameterName0=Part Number|ParameterValue0=X1|ModelType0=PCBLIB|ModelName0=FP1|Description=d|"
        "ParameterName1=Value|ParameterValue1=1k|ModelName1=FP2|PlacingFromDatabase=TRUE"
    )
    assert params == {"Part Number": "X1", "Value": "1k"}
    assert models == ["FP1", "FP2"]
    assert parse_db_parameters("") == ({}, [])


def test_open_and_close_own_documents(tmp_path):
    state = {"open": set()}

    def handler(command: str, args: dict[str, str]) -> list[str]:
        if command == "open_document":
            state["open"].add(args["path"])
            return ["KV|was_open|0"]
        if command == "close_own_documents":
            lines = []
            for i in range(int(args["count"])):
                path = args[f"path{i}"]
                lines.append(f"ITEM|closed|{escape_field(path)}")
            return lines
        if command == "list_components":
            return ["ROW|components|A|2", "ROW|components|B|8"]
        raise AssertionError(command)

    bridge, fake = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    lib = tmp_path / "Lib.SchLib"
    assert bridge.open_document(lib) is False
    assert fake.requests[-1] == ("open_document", {"path": str(canonical_path(lib)), "kind": "SCHLIB"})
    assert bridge.list_components(lib) == ["A", "B"]
    closed = bridge.close_own_documents()
    assert closed["closed"] == [str(canonical_path(lib))]
    assert bridge.close_own_documents() == {"closed": [], "modified": [], "not_open": []}
    with pytest.raises(BridgeError, match="Dokumenttyp"):
        bridge.open_document(tmp_path / "x.txt")


def test_edit_component_shows_the_component_and_is_no_own_document(tmp_path):
    def handler(command: str, args: dict[str, str]) -> list[str]:
        assert command == "edit_component"
        return ["KV|was_open|1", "KV|found|1", f"KV|current|{escape_field(args['name'])}", "KV|modified|0"]

    bridge, fake = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    lib = tmp_path / "PF_CHIP.PcbLib"
    focus = bridge.edit_component(lib, "RESC1608X50N")
    assert fake.requests[-1] == ("edit_component", {"path": str(canonical_path(lib)), "kind": "PCBLIB",
                                                    "name": "RESC1608X50N"})
    assert focus.found and focus.was_open and focus.current == "RESC1608X50N" and not focus.modified
    # the user works in it: PartForge must never close it as one of its own documents
    assert bridge.close_own_documents() == {"closed": [], "modified": [], "not_open": []}
    with pytest.raises(BridgeError, match="keine SchLib oder PcbLib"):
        bridge.edit_component(tmp_path / "PartForge.DbLib", "X")


def test_altium_safe_path(tmp_path):
    latin = tmp_path / "Bibliothek ÄÖÜ"
    assert altium_safe_path(latin) == str(canonical_path(latin))
    odd = tmp_path / "Ω-Ordner"
    odd.mkdir()
    try:
        value = altium_safe_path(odd / "PF.SchLib")
    except BridgeError as exc:  # 8.3 names disabled on this volume
        assert "Sonderzeichen" in str(exc)
    else:
        assert all(ord(c) <= 0xFF for c in value) and value.endswith("PF.SchLib")


@pytest.mark.windows
def test_paths_are_sent_in_one_canonical_spelling(tmp_path):
    folder = tmp_path / "Lib"
    folder.mkdir()
    (folder / "X.SchLib").write_bytes(b"")  # existing files resolve to their real case
    spellings = [folder / "X.SchLib", folder / "sub" / ".." / "X.SchLib", Path(str(folder / "X.SchLib").upper())]
    assert len({altium_safe_path(p) for p in spellings}) == 1


def test_status_when_running(tmp_path, monkeypatch):
    monkeypatch.setattr("partforge.altium.bridge.core.file_version", lambda path: "26.10.1.5")
    bridge, _ = make_bridge(tmp_path)
    status = bridge.status()
    assert status.available and status.version == "26.10.1.5" and "26.10.1.5" in status.message
    assert AltiumBridge(exchange_dir=tmp_path / "e", x2_path=None).status().available is False


def test_document_state_and_refresh(tmp_path):
    states = {"open": "1", "modified": "0", "state": "reloaded"}

    def handler(command: str, args: dict[str, str]) -> list[str]:
        if command == "document_state":
            return [f"KV|open|{states['open']}", f"KV|modified|{states['modified']}"]
        if command == "refresh_document":
            assert args["kind"] == "PCBLIB"
            return [f"KV|state|{states['state']}"]
        raise AssertionError(command)

    bridge, _ = make_bridge(tmp_path, FakeAltium(tmp_path, handler))
    lib = tmp_path / "PF_CHIP.PcbLib"
    state = bridge.document_state(lib)
    assert state.open and not state.modified and state.path == str(canonical_path(lib))
    assert bridge.refresh_document(lib) == "reloaded"
    states.update(modified="1", state="modified")
    assert bridge.document_state(lib).modified
    assert bridge.refresh_document(lib) == "modified"
    states["state"] = "bogus"
    with pytest.raises(BridgeCommandError, match="unerwarteter Zustand"):
        bridge.refresh_document(lib)


def test_launcher_failure_is_reported_and_cleaned_up(tmp_path):
    def broken(command_line: str) -> None:
        raise FileNotFoundError("X2.EXE fehlt")

    bridge, _ = make_bridge(tmp_path)
    bridge._launcher = broken
    with pytest.raises(BridgeError, match="nicht angesprochen"):
        bridge.ping()
    assert not (bridge.exchange_dir / "request.txt").exists()
    no_x2 = AltiumBridge(exchange_dir=tmp_path / "e2", x2_path=None, process_check=lambda: True)
    with pytest.raises(BridgeError, match=r"X2\.EXE"):
        no_x2.ping()
