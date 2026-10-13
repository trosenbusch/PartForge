"""Bridge additions for the DbLib refresh: ``install_state`` / ``refresh_dblib`` (no Altium).

The Python side is exercised through the real :class:`AltiumBridge` exchange with a fake
script partner; the DelphiScript side is checked statically against the procedure that
was VERIFIED in Altium 26.10 (``recherche/altium-refresh.md`` §7.4).
"""
from __future__ import annotations

import re

import pytest
from test_refresh_support import script_bridge

from partforge.altium.bridge.core import (
    SCRIPTS_DIR,
    BridgeCommandError,
    BridgeError,
    canonical_path,
    dblib_file_name,
)
from partforge.altium.bridge.protocol import escape_field


def _procedure(unit: str, name: str) -> str:
    """Code of one procedure without comments and string contents (``'…'`` kept as quotes)."""
    text = (SCRIPTS_DIR / unit).read_text(encoding="ascii")
    start = text.index(f"procedure {name}(")
    end = text.find("\nprocedure ", start + 10)
    body = text[start:] if end < 0 else text[start:end]
    body = re.sub(r"\{[^}]*\}", " ", body)
    return re.sub(r"//[^\n]*", "", body)


# --------------------------------------------------------------------------- python side


def test_dblib_file_name_validation(tmp_path):
    assert dblib_file_name("PartForge.DbLib") == "PartForge.DbLib"
    assert dblib_file_name(tmp_path / "Sub" / "Bibliothek.dblib") == "Bibliothek.dblib"
    assert dblib_file_name("Bauteile ÄÖÜ.DbLib") == "Bauteile ÄÖÜ.DbLib"  # Latin-1 is fine
    for bad in ("PartForge.SchLib", "", "Ω-Teile.DbLib", "Tab\x01.DbLib"):
        with pytest.raises(BridgeError):
            dblib_file_name(bad)


@pytest.mark.windows
def test_install_state_parses_same_name_entries(tmp_path):
    ours = tmp_path / "Bib" / "PartForge.DbLib"
    ours.parent.mkdir()
    ours.write_text("x")
    other = r"D:\Alt\PartForge.DbLib"
    seen: dict[str, str] = {}

    def handler(command: str, args: dict[str, str]) -> list[str]:
        seen.update(args, command=command)
        mine = escape_field(str(canonical_path(ours)).upper())  # Altium may report another spelling
        return [
            f"ROW|same_name|3|{escape_field(other)}|0|1|0|0",
            f"ROW|same_name|7|{mine}|1|1|0|0",
            "ROW|same_name|broken",
            "KV|installed|1",
            "KV|position|7",
            "KV|same_name_count|2",
            "KV|installed_count|22",
        ]

    bridge, fake = script_bridge(tmp_path, handler)
    state = bridge.install_state(ours)
    assert seen["command"] == "dblib_install_state"
    assert seen["path"] == str(canonical_path(ours)) and seen["file_name"] == "PartForge.DbLib"
    assert state.installed and state.position == 7 and state.installed_count == 22
    assert [e.index for e in state.same_name] == [3, 7]
    assert state.same_name[0].document_open and not state.same_name[0].same_file
    assert state.duplicates == [other]
    assert state.first_match == other and state.resolves_to_this is False
    assert not fake.errors


def test_install_state_not_installed(tmp_path):
    bridge, _ = script_bridge(tmp_path, lambda c, a: ["KV|installed|0", "KV|position|-1", "KV|installed_count|20"])
    state = bridge.install_state(tmp_path / "PartForge.DbLib")
    assert not state.installed and state.position is None and state.same_name == []
    assert state.first_match is None and not state.resolves_to_this and state.installed_count == 20


def test_refresh_dblib_values_only(tmp_path):
    seen: dict[str, str] = {}
    lib = r"C:\Bib\PartForge.DbLib"

    def handler(command: str, args: dict[str, str]) -> list[str]:
        seen.update(args, command=command)
        return [
            f"ITEM|matched|{escape_field(lib)}",
            f"ROW|docs|0|{escape_field(lib)}|closed|313",
            "KV|refreshed|0",
            "KV|matched_count|1",
        ]

    bridge, _ = script_bridge(tmp_path, handler)
    result = bridge.refresh_dblib("PartForge.DbLib")
    assert seen == {"command": "refresh_dblib", "file_name": "PartForge.DbLib", "rebuild": "0"}
    assert result.matched == [lib] and result.closed == [lib] and result.installed
    assert result.refreshed_index is False and result.refresh_ms is None and result.skipped == {}
    assert result.duration_s >= 0


def test_refresh_dblib_with_index_rebuild(tmp_path):
    a, b, c = r"C:\A\PartForge.DbLib", r"C:\B\PartForge.DbLib", r"C:\C\PartForge.DbLib"

    def handler(command: str, args: dict[str, str]) -> list[str]:
        assert args["rebuild"] == "1"
        return [
            *(f"ITEM|matched|{escape_field(p)}" for p in (a, b, c)),
            f"ROW|docs|0|{escape_field(a)}|not_open|0",
            f"ROW|docs|0|{escape_field(b)}|shown|0",
            f"ROW|docs|0|{escape_field(c)}|modified|0",
            "KV|refresh_ms|2625",
            f"ROW|docs|1|{escape_field(a)}|closed|469",  # reopened by RefreshInstalledLibraries
            f"ROW|docs|1|{escape_field(b)}|shown|0",
            f"ROW|docs|1|{escape_field(c)}|other_kind|0",
            "KV|refreshed|1",
        ]

    bridge, _ = script_bridge(tmp_path, handler)
    result = bridge.refresh_dblib(r"C:\Irgendwo\PartForge.DbLib", rebuild_index=True)
    assert result.rebuild_index and result.refreshed_index and result.refresh_ms == 2625
    assert result.closed == [a] and result.not_open == []  # closed in pass 1 -> not "not open"
    assert result.skipped == {b: "shown", c: "other_kind"}


def test_refresh_dblib_not_installed_and_errors(tmp_path):
    bridge, _ = script_bridge(tmp_path, lambda c, a: ["KV|refreshed|0", "KV|matched_count|0"])
    result = bridge.refresh_dblib("PartForge.DbLib", rebuild_index=True)
    assert result.matched == [] and not result.installed and not result.refreshed_index

    def failing(command: str, args: dict[str, str]) -> list[str]:
        raise RuntimeError("integrated library manager not available")

    bridge, _ = script_bridge(tmp_path / "x", failing)
    with pytest.raises(BridgeCommandError, match="integrated library manager"):
        bridge.refresh_dblib("PartForge.DbLib")
    with pytest.raises(BridgeError, match="DbLib-Dateiname"):
        bridge.refresh_dblib("PartForge.SchLib")


# --------------------------------------------------------------------------- DelphiScript side


def test_new_commands_are_dispatched():
    dispatch = (SCRIPTS_DIR / "PartForgeBridge.pas").read_text(encoding="ascii")
    assert re.search(r"Cmd = 'dblib_install_state' then\s+PFCmdDbLibInstallState\(0\)", dispatch)
    assert re.search(r"Cmd = 'refresh_dblib' then\s+PFCmdRefreshDbLib\(0\)", dispatch)


def test_refresh_procedure_follows_verified_snippet():
    code = _procedure("PFLibraries.pas", "PFCmdRefreshDbLib")
    # matches installed libraries by FILE NAME (placed parts reference the DbLib by name)
    assert "UpperCase(ExtractFileName(S)) = UpperCase(FileName)" in code
    assert "IntMan.InstalledLibraryPath(I)" in code
    # never closes a shown or modified document; only DbLib server documents
    order = [code.index(s) for s in ("Client.GetDocumentByPath(S)", "Doc = Nil", "Doc.Modified", "Doc.IsShown",
                                     "'DATABASELIB'", "Client.CloseDocument(Doc)")]
    assert order == sorted(order)
    assert code.count("Client.CloseDocument(") == 1
    # rebuild: RunProcess after ResetParameters, then the loop closes the reopened document again
    assert "ResetParameters;" in code and "RunProcess('IntegratedLibrary:RefreshInstalledLibraries')" in code
    assert code.index("ResetParameters;") < code.index("RunProcess(")
    assert "for Pass := 0 to LastPass do" in code and "if Matches > 0 then" in code
    for forbidden in ("InstallLibrary(", "UninstallLibrary(", "OpenDocument(", "DisposeIfNotShowing", "SetConnectionString"):
        assert forbidden not in code, forbidden


def test_install_state_procedure_is_read_only():
    code = _procedure("PFLibraries.pas", "PFCmdDbLibInstallState")
    for forbidden in ("CloseDocument", "InstallLibrary(", "UninstallLibrary(", "OpenDocument(", "RunProcess", "ShowDocument"):
        assert forbidden not in code, forbidden
    assert "Client.GetDocumentByPath(S)" in code and "if Doc <> Nil then" in code
    assert "'ROW|same_name|'" in code


def test_python_and_pascal_agree_on_fields():
    refresh = _procedure("PFLibraries.pas", "PFCmdRefreshDbLib")
    for key in ("'file_name'", "'rebuild'", "'matched'", "'refresh_ms'", "'refreshed'", "'ROW|docs|'"):
        assert key in refresh, key
    for state in ("not_open|0", "modified|0", "shown|0", "other_kind|0", "closed|"):
        assert state in refresh, state
    state_code = _procedure("PFLibraries.pas", "PFCmdDbLibInstallState")
    for key in ("'path'", "'file_name'", "'installed'", "'position'", "'installed_count'"):
        assert key in state_code, key
