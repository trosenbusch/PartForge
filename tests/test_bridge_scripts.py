"""Static checks of the DelphiScript templates (a runtime error would wedge Altium).

Rules from altium-live.md / bridge-study.md: no ``Exit``, no indexing of interface
string properties, ASCII only, no dialogs, only verified constants, only ``Run`` visible
in the Run Script dialog.
"""
from __future__ import annotations

import re

import pytest

from partforge.altium.bridge.core import (
    EXCHANGE_PLACEHOLDER,
    PROJECT_FILE,
    SCRIPT_UNITS,
    SCRIPTS_DIR,
    AltiumBridge,
)

#: Altium constants used by the templates; each one appears in a script that ran on
#: Altium 26.10 (altium-live.md, altium-verify-2 kit) or in altium-mcp's production code.
VERIFIED_CONSTANTS = {
    "eSchComponent",
    "eCreate_Default",
    "ePin",
    "eRectangle",
    "eRoundRectangle",
    "eLine",
    "ePolyline",
    "ePolygon",
    "eArc",
    "eEllipse",
    "eLabel",
    "eParameter",
    "eImplementation",
    "ePadObject",
    "eTrackObject",
    "eArcObject",
    "eRegionObject",
    "eTextObject",
    "eComponentBodyObject",
    "eNoDimension",
    "ePadMode_Simple",
    "eTopLayer",
    "eBottomLayer",
    "eBoardSide_Top",
    "c_BroadCast",
    "c_Broadcast",
    "SCHM_PrimitiveRegistration",
    "PCBM_BoardRegisteration",
}
ALLOWED_INDEXED_PROPERTIES = {"StackCRPctOnLayer", "Vertex"}


def strip_pascal(text: str) -> str:
    """Remove comments and string literals (keeps line structure roughly)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            end = text.find("}", i)
            i = n if end < 0 else end + 1
            out.append(" ")
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append("''")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


@pytest.fixture(scope="module")
def units() -> dict[str, str]:
    return {name: (SCRIPTS_DIR / name).read_bytes().decode("ascii") for name in SCRIPT_UNITS}


@pytest.fixture(scope="module")
def code(units) -> dict[str, str]:
    return {name: strip_pascal(text) for name, text in units.items()}


def test_files_are_ascii_and_deployed_with_crlf(tmp_path):
    """The templates are ASCII (LF in the repository, .gitattributes); Altium gets CRLF – ``ensure_scripts``
    writes every file with CRLF, whatever the line endings of the template."""
    for name in (*SCRIPT_UNITS, PROJECT_FILE, "THIRD_PARTY_NOTICES.txt"):
        assert (SCRIPTS_DIR / name).read_bytes().isascii(), name
    bridge = AltiumBridge(exchange_dir=tmp_path / "exchange", x2_path=None)
    deployed = bridge.ensure_scripts().parent
    for name in (*SCRIPT_UNITS, PROJECT_FILE, "THIRD_PARTY_NOTICES.txt"):
        data = (deployed / name).read_bytes()
        assert data.isascii() and b"\r\n" in data, name
        assert b"\n" not in data.replace(b"\r\n", b""), f"{name}: LF ohne CR"


def test_no_exit_and_no_dialogs(code):
    for name, text in code.items():
        assert not re.search(r"\bexit\b", text, re.IGNORECASE), name
        for forbidden in ("ShowMessage", "MessageDlg", "InputBox", "SendKeys", "PostMessage", "WM_CLOSE", "Halt"):
            assert forbidden.lower() not in text.lower(), (name, forbidden)


def test_no_indexing_of_interface_properties(code):
    for name, text in code.items():
        for prop in re.findall(r"\b\w+\.(\w+)\s*\[", text):
            assert prop in ALLOWED_INDEXED_PROPERTIES, (name, prop)


def test_begin_end_balance(code):
    for name, text in code.items():
        lower = text.lower()
        opens = len(re.findall(r"\bbegin\b", lower)) + len(re.findall(r"\btry\b", lower))
        closes = len(re.findall(r"\bend\b", lower))
        assert opens == closes, f"{name}: {opens} begin/try vs {closes} end"


def test_only_run_is_parameterless(code):
    parameterless = [m for text in code.values() for m in re.findall(r"\bprocedure\s+(\w+)\s*;", text, re.IGNORECASE)]
    assert parameterless == ["Run"]


def test_only_verified_constants(code):
    for name, text in code.items():
        for const in set(re.findall(r"\b(e[A-Z]\w*|c_\w+|SCHM_\w+|PCBM_\w+)\b", text)):
            assert const in VERIFIED_CONSTANTS, (name, const)


def test_all_pf_routines_are_defined(code):
    everything = "\n".join(code.values())
    defined = set(re.findall(r"\b(?:procedure|function)\s+(PF\w+)", everything, re.IGNORECASE))
    declared = set(re.findall(r"\b(PF\w+)\s*(?::|=)", everything))  # globals and constants
    used = set(re.findall(r"\b(PF\w+)\b", everything))
    assert used <= defined | declared, sorted(used - defined - declared)


def test_dispatch_covers_every_command(code, units):
    commands = set(re.findall(r"\bprocedure\s+(PFCmd\w+)", "\n".join(code.values())))
    dispatch = code["PartForgeBridge.pas"]
    dispatched = set(re.findall(r"\b(PFCmd\w+)\(0\)", dispatch))
    assert commands == dispatched
    # every command the Python client sends has a dispatch branch – and no branch is dead
    names = set(re.findall(r"\bCmd = '(\w+)'", units["PartForgeBridge.pas"]))
    assert len(names) == len(commands)
    client = (SCRIPTS_DIR.parent / "core.py").read_text(encoding="utf-8")
    sent = set(re.findall(r"\bexecute\(\s*\"(\w+)\"", client))
    sent |= set(re.findall(r"_write_library\(\s*\"(\w+)\"", client))
    assert sent == names


def _procedure(text: str, name: str) -> str:
    start = text.index(f"procedure {name}(")
    end = text.find("\nprocedure ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_refresh_document_keeps_hidden_documents_hidden(code):
    """A library Altium holds open without an editor tab is reopened hidden (VERIFIED in Altium
    26.10, altium-e2e.md): ShowDocument only for a document that was shown before."""
    body = " ".join(_procedure(code["PFLibraries.pas"], "PFCmdRefreshDocument").split())
    assert "if Doc.IsShown then WasShown := True;" in body
    assert "if WasShown then Client.ShowDocument(Doc);" in body
    assert body.count("ShowDocument") == 1


def test_temporary_install_releases_the_database_before_uninstall(code):
    """UninstallLibrary alone leaves the hidden DbLib document (and its database connection)
    open – reproduced in Altium 26.10 (altium-e2e.md); the lookup closes it first."""
    body = " ".join(_procedure(code["PFLibraries.pas"], "PFCmdResolveDbComponents").split())
    temp = body[body.index("if TempInstalled then begin Doc := Client.GetDocumentByPath(DbLib);"):]
    assert temp.index("Client.CloseDocument(Doc);") < temp.index("IntMan.UninstallLibrary(DbLib);")
    for guard in ("if not Doc.Modified then", "if not Doc.IsShown then", "if UpperCase(Kind) = '' then"):
        assert guard in temp, guard


def test_batch_resolve_installs_once_and_reports_every_key(code, units):
    """resolve_db_components: one temporary installation around the whole loop, one
    PFResolveOne per key, the count only after the loop (a run that died midway is never
    read as "not found"), and a hard limit above PartForge's batch size."""
    from partforge.altium.bridge.core import RESOLVE_BATCH_SIZE

    body = " ".join(_procedure(code["PFLibraries.pas"], "PFCmdResolveDbComponents").split())
    install = body.index("IntMan.InstallLibrary(DbLib);")
    loop = body.index("for I := 0 to Count - 1 do")
    resolve = body.index("PFResolveOne(DbLib, Table, Key, Idx);")
    count = body.index("PFOutKV('', IntToStr(Count));")
    uninstall = body.index("IntMan.UninstallLibrary(DbLib);")
    assert install < loop < resolve < count < uninstall
    assert body.count("IntMan.InstallLibrary(DbLib);") == 1 and body.count("IntMan.UninstallLibrary(DbLib);") == 1
    assert body.count("PFResolveOne(") == 1
    assert "else if Count > PF_MAX_RESOLVE then PFFail(" in body
    limit = re.search(r"PF_MAX_RESOLVE = (\d+);", units["PFUtils.pas"])
    assert limit is not None and int(limit.group(1)) >= RESOLVE_BATCH_SIZE


def test_resolve_one_tags_every_row_with_the_key_index(code):
    body = " ".join(_procedure(code["PFLibraries.pas"], "PFResolveOne").split())
    for row in ("'' + Idx + ''", "PFOutLines.Add('' + Idx + '' + PFEncode(S1) + '' + PFEncode(S2) + '' + PFBoolStr("):
        assert row in body, row
    assert body.count("PFOutLines.Add(") == 5  # raw, res (not loaded / loaded), models, parameters
    # Comment visibility is read nil-safe through a local (never chained on a possibly nil object)
    assert "Obj := Comp.Comment; if Obj = Nil then" in body and "Hidden := Obj.IsHidden;" in body


def test_placeholder_and_exchange_constant(units):
    placeholders = sum(text.count(EXCHANGE_PLACEHOLDER) for text in units.values())
    assert placeholders == 1
    assert f"PF_EXCHANGE_DIR = '{EXCHANGE_PLACEHOLDER}';" in units["PFUtils.pas"]
    assert "altium_mcp" not in "".join(units.values()).lower()


def test_project_lists_units_in_order():
    project = (SCRIPTS_DIR / PROJECT_FILE).read_text(encoding="ascii")
    paths = [line.split("=", 1)[1] for line in project.splitlines() if line.startswith("DocumentPath=")]
    assert paths == list(SCRIPT_UNITS)
    assert paths[0] == "PFUtils.pas" and paths[-1] == "PartForgeBridge.pas"


def test_mit_attribution_present(units):
    for name, text in units.items():
        assert "altium-mcp" in text and "MIT" in text, name
    notice = (SCRIPTS_DIR / "THIRD_PARTY_NOTICES.txt").read_text(encoding="ascii")
    assert "Copyright (c) 2025 Siddharth Ahuja" in notice and "Permission is hereby granted" in notice


def test_strip_pascal_helper():
    stripped = strip_pascal("a := 'it''s {x}'; { comment's } b; // Exit\nc")
    assert " ".join(stripped.split()) == "a := ''; b; c"
    assert "Exit" not in stripped and "comment" not in stripped
