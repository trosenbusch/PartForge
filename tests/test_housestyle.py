"""Stapelbearbeitung (``partforge.altium.housestyle`` + API): rules, check, apply and undo.

The end-to-end tests write "foreign" libraries with PartForge's own Rust writer in a second workspace whose house
style differs (other mechanical layers, stroke texts 1 mm, Times New Roman, 200-mil pins, prefix ``IC``), copy them
into the library under test as imported libraries and convert them to its house style.
"""
from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from test_writer_samples import chip_0603, ic8_symbol, resistor_symbol, soic8

from partforge.altium import compound, libwriter, stackup, sync
from partforge.altium import housestyle as H
from partforge.altium import conform as C
from partforge.altium import pcbrecords as R
from partforge.altium import schrecords as S
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.db import meta as db_meta
from partforge.db import registry
from partforge.workspace import FootprintStyle, LayerMap, SymbolStyle, Workspace

FOREIGN_LAYERS = LayerMap(
    assembly="Mechanical 13", designator="Mechanical 13", comment="Mechanical 13", component_center="Mechanical 13",
    component_outline="Mechanical 13", courtyard="Mechanical 15", body3d="Mechanical 1",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_job(client, job: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} nicht fertig")


# --------------------------------------------------------------------------- rules and API (no writer)


def test_rules_are_remembered_per_library(client):
    assert client.get("/api/housestyle/rules").json() == C.ConformRules().model_dump(mode="json")
    rules = C.ConformRules(symbols=C.SymbolRules(prefix_map={"IC": "U", "TR": "Q"}, colors=True),
                           footprints=C.FootprintRules(add_center=False,
                                                       roles={"Footprints\\A.PcbLib": {"Mechanical 13": "assembly"}}))
    response = client.put("/api/housestyle/rules", json=rules.model_dump(mode="json"))
    assert response.status_code == 200
    assert client.get("/api/housestyle/rules").json() == rules.model_dump(mode="json")
    assert H.saved_rules() == rules


def test_unreadable_saved_rules_fall_back_to_the_defaults(workspace):
    db_meta.set_meta(H.RULES_META_KEY, "{not json")
    assert H.saved_rules() == C.ConformRules()
    H.remember_rules(C.ConformRules(symbols=C.SymbolRules(fonts=False)))
    assert not H.saved_rules().symbols.fonts


def test_rules_reject_unknown_roles(client):
    body = C.ConformRules().model_dump(mode="json")
    body["footprints"]["roles"] = {"A.PcbLib": {"Mechanical 13": "silkscreen-ish"}}
    assert client.put("/api/housestyle/rules", json=body).status_code == 422


def test_no_undo_without_a_conversion(client):
    assert client.get("/api/housestyle/undo").json() is None
    response = client.post("/api/housestyle/undo")
    assert response.status_code == 404 and "rückgängig" in response.json()["detail"]


def test_check_of_an_empty_selection(workspace):
    report = H.check(H.ConformSelection(), C.ConformRules())
    assert report.checked == 0 and report.affected == 0 and report.libraries == [] and report.message


def test_learn_needs_a_library(client, tmp_path: Path):
    assert client.post("/api/housestyle/learn", json={"paths": []}).status_code == 400
    response = client.post("/api/housestyle/learn", json={"paths": [str(tmp_path / "missing.SchLib")]})
    assert response.status_code == 400 and "Keine Symbol- oder Footprint-Bibliothek" in response.json()["detail"]


# --------------------------------------------------------------------------- end to end (Rust writer)


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture
def _no_altium(monkeypatch):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()


@pytest.fixture
def house(workspace: Workspace, _no_altium) -> Workspace:
    """The library under test with a house style that differs from the foreign libraries."""
    workspace.settings.symbol = SymbolStyle(font="Verdana", font_size=10, ic_pin_length=100)
    workspace.settings.footprint = FootprintStyle(text_font="truetype", text_font_name="Arial", text_height=0.8,
                                                  center_cross=False)
    workspace.save()
    return workspace


@pytest.fixture
def foreign(house: Workspace, tmp_path: Path) -> dict[str, Path]:
    """Foreign SchLib/PcbLib copied into ``Import\\Fremd`` of the house library and registered as imported."""
    other = Workspace.create(tmp_path / "Fremd", name="Fremd")
    other.settings.layers = FOREIGN_LAYERS
    other.settings.footprint = FootprintStyle(text_height=1.0)
    other.save()
    # no stack of its own: the header declares the kinds of the foreign mapping (Mech 13 assembly …)
    ops = RustLibraryOps(workspace=other, layer_stack=stackup.LayerStack(name="Fremd"))
    ic = ic8_symbol("FOREIGN_TIMER").model_copy(update={"designator_prefix": "IC"})
    schlib = other.symbols_dir / "Fremd.SchLib"
    pcblib = other.footprints_dir / "Fremd.PcbLib"
    assert not ops.upsert_symbols(schlib, [ic, resistor_symbol("FOREIGN_RES")]).errors
    assert not ops.upsert_footprints(pcblib, [chip_0603("FOREIGN_0603"), soic8("FOREIGN_SOIC8")]).errors
    target_s = house.symbols_dir / "Import" / "Fremd" / "Fremd.SchLib"
    target_f = house.footprints_dir / "Import" / "Fremd" / "Fremd.PcbLib"
    target_s.parent.mkdir(parents=True)
    target_f.parent.mkdir(parents=True)
    shutil.copyfile(schlib, target_s)
    shutil.copyfile(pcblib, target_f)
    result = sync.scan_workspace(register=True)
    assert result["unreadable"] == []
    names = {r.name: r.source for r in registry.list_symbols()} | {r.name: r.source for r in registry.list_footprints()}
    assert {names[n] for n in ("FOREIGN_TIMER", "FOREIGN_RES", "FOREIGN_0603", "FOREIGN_SOIC8")} == {"imported"}
    return {"schlib": target_s, "pcblib": target_f}


def _footprint_records(path: Path) -> dict[str, R.FootprintRecords]:
    return {name: records for name, (_storage, records) in R.read_footprints(path).items()}


def _symbol_records(path: Path, name: str) -> list[S.SchRecord]:
    tree = compound.read_tree_file(path)
    for key, data in tree.items():
        if data is not None and key.endswith("/Data") and key.count("/") == 1:
            records = S.parse_records(data)
            head = next((r for r in records if not r.binary and r.get("RECORD") == "1"), None)
            if head is not None and head.get("LibReference") == name:
                return records
    raise AssertionError(f"{name} nicht in {path.name}")


@pytest.mark.rustwriter
def test_check_apply_recheck_undo(house: Workspace, foreign: dict[str, Path]):
    before = {kind: _sha(path) for kind, path in foreign.items()}
    report = H.check(H.ConformSelection(), C.ConformRules())
    assert report.checked == 4
    affected = {c.name: {ch.rule for ch in c.changes} for c in report.components if c.changes}
    assert {"fonts", "pin_length", "prefix"} <= affected["FOREIGN_TIMER"]
    assert {"layers", "texts"} <= affected["FOREIGN_0603"] and {"layers", "texts"} <= affected["FOREIGN_SOIC8"]
    pcblib = next(lib for lib in report.libraries if lib.kind == "pcblib")
    roles = {r.layer: r.role for r in pcblib.roles}
    assert roles["Mechanical 13"] == "assembly" and roles["Mechanical 15"] == "courtyard"
    schlib = next(lib for lib in report.libraries if lib.kind == "schlib")
    assert any("Verdana" in font for font in schlib.fonts)
    assert {kind: _sha(path) for kind, path in foreign.items()} == before  # the check reads only

    out = H.apply(H.ConformSelection(), C.ConformRules())
    assert out["errors"] == [] and out["skipped"] == [], out
    assert out["components"] == report.affected and len(out["libraries"]) == 2 and out["undo"]

    # footprints: house layers, TrueType texts, no foreign mechanical layer left
    converted = _footprint_records(foreign["pcblib"])
    for records in converted.values():
        layers = {p.layer for p in records.primitives if p.kind in ("track", "arc", "text")}
        assert "Mechanical 13" not in layers and {"Mechanical 9", "Mechanical 17"} <= layers
        for t in records.of_kind("text"):
            if t.text in (".Designator", ".Comment"):
                assert t.font_kind == "truetype" and t.font_name == "Arial"
    # the chip has a courtyard cross and a centre cross: only the centre moves to the centre layer
    def through_origin(t: R.Primitive) -> bool:
        x1, y1, x2, y2 = t.coords
        return abs(x1 + x2) < 1e-3 and abs(y1 + y2) < 1e-3 and (max(abs(y1), abs(y2)) < 1e-3 or max(abs(x1), abs(x2)) < 1e-3)

    chip_tracks = converted["foreign_0603"].of_kind("track")
    crosses = [(t.layer, round(R.track_length(t), 3)) for t in chip_tracks if through_origin(t)]
    assert sorted(crosses) == [("Mechanical 15", 1.0), ("Mechanical 15", 1.0),
                               ("Mechanical 17", 0.95), ("Mechanical 17", 0.95)]
    # symbols: house font in the table, 100-mil pins on the IC, prefix U
    header = S.parse_header(compound.read_tree_file(foreign["schlib"])["FileHeader"])  # type: ignore[arg-type]
    assert any(f.name == "Verdana" for f in header.fonts())
    timer = _symbol_records(foreign["schlib"], "FOREIGN_TIMER")
    assert {S.PinView(r).length for r in timer if r.is_pin} == {10}
    assert next(r for r in timer if not r.binary and r.get("RECORD") == "34").get("Text") == "U?"
    # the registry follows (imported components are read again)
    spec = next(r for r in registry.list_symbols() if r.name == "FOREIGN_TIMER").spec
    assert spec is not None and spec.designator_prefix == "U"
    # nothing left to do
    again = H.check(H.ConformSelection(), C.ConformRules())
    assert again.affected == 0, [(c.name, [ch.message for ch in c.changes]) for c in again.components]
    # the Rust reader still lists every component
    ops = RustLibraryOps(workspace=house)
    assert sorted(ops.list_components(foreign["schlib"])) == ["FOREIGN_RES", "FOREIGN_TIMER"]
    assert sorted(ops.list_components(foreign["pcblib"])) == ["FOREIGN_0603", "FOREIGN_SOIC8"]

    info = H.undo_info()
    assert info is not None and len(info["libraries"]) == 2
    undone = H.undo_last()
    assert sorted(undone["restored"]) == sorted(out["libraries"]) and undone["skipped"] == []
    assert {kind: _sha(path) for kind, path in foreign.items()} == before
    spec = next(r for r in registry.list_symbols() if r.name == "FOREIGN_TIMER").spec
    assert spec is not None and spec.designator_prefix == "IC"
    assert H.undo_info() is None


@pytest.mark.rustwriter
def test_selection_and_rules_limit_the_conversion(house: Workspace, foreign: dict[str, Path]):
    pcb_before = _sha(foreign["pcblib"])
    rules = C.ConformRules(symbols=C.SymbolRules(fonts=False, pin_length=False))
    out = H.apply(H.ConformSelection(kinds=["symbol"], names=["FOREIGN_TIMER"]), rules)
    assert out["components"] == 1 and out["errors"] == []
    assert _sha(foreign["pcblib"]) == pcb_before
    timer = _symbol_records(foreign["schlib"], "FOREIGN_TIMER")
    assert {S.PinView(r).length for r in timer if r.is_pin} == {20}  # pin length rule was off
    assert next(r for r in timer if not r.binary and r.get("RECORD") == "34").get("Text") == "U?"


@pytest.mark.rustwriter
def test_manual_role_overrides_the_detection(house: Workspace, foreign: dict[str, Path]):
    rel = house.rel(foreign["pcblib"])
    rules = C.ConformRules(footprints=C.FootprintRules(roles={rel: {"Mechanical 13": "component_outline"}}))
    report = H.check(H.ConformSelection(kinds=["footprint"]), rules)
    roles = {r.layer: (r.role, r.reason) for r in report.libraries[0].roles}
    assert roles["Mechanical 13"] == ("component_outline", "manual")
    H.apply(H.ConformSelection(kinds=["footprint"]), rules)
    for records in _footprint_records(foreign["pcblib"]).values():
        layers = {p.layer for p in records.of_kind("track")}
        assert "Mechanical 21" in layers and "Mechanical 9" not in layers


@pytest.mark.rustwriter
def test_api_check_and_apply_jobs(client, house: Workspace, foreign: dict[str, Path]):
    body = {"selection": H.ConformSelection().model_dump(mode="json"), "rules": C.ConformRules().model_dump(mode="json")}
    job = wait_job(client, client.post("/api/housestyle/check", json=body).json()["job"])
    assert job["status"] == "done" and job["kind"] == "housestyle.check"
    assert job["result"]["affected"] >= 3 and job["result"]["checked"] == 4
    job = wait_job(client, client.post("/api/housestyle/apply", json=body).json()["job"])
    assert job["status"] == "done" and job["kind"] == "libraries.conform", job.get("error")
    assert job["result"]["errors"] == [] and job["result"]["undo"]
    assert client.get("/api/housestyle/rules").json() == body["rules"]
    undo = client.get("/api/housestyle/undo").json()
    assert undo is not None and len(undo["libraries"]) == 2
    job = wait_job(client, client.post("/api/housestyle/undo").json()["job"])
    assert job["status"] == "done" and len(job["result"]["restored"]) == 2


# --------------------------------------------------------------------------- cancel, partial undo, refusal


def _cancel_on(call: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """``session.check_cancelled`` raises ``JobCancelled`` on its ``call``-th call (as a library switch would)."""
    from partforge.jobs import JobCancelled

    calls = {"n": 0}
    original = sync._Session.check_cancelled

    def check(self: sync._Session) -> None:
        calls["n"] += 1
        if calls["n"] >= call:
            raise JobCancelled()
        original(self)

    monkeypatch.setattr(sync._Session, "check_cancelled", check)


def _refuse(paths: set[Path], monkeypatch: pytest.MonkeyPatch) -> None:
    """Altium "has" these libraries open with unsaved changes."""
    wanted = {str(p).casefold() for p in paths}
    monkeypatch.setattr(sync._AltiumGuard, "refusal",
                        lambda self, library: sync.ALTIUM_MODIFIED_MESSAGE if str(library).casefold() in wanted else None)


@pytest.mark.rustwriter
def test_cancelled_conversion_stays_undoable(house: Workspace, foreign: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    from partforge.jobs import JobCancelled

    before = {kind: _sha(path) for kind, path in foreign.items()}
    _cancel_on(2, monkeypatch)  # the first library (footprints, sorted by kind) is written, then the job is cancelled
    with pytest.raises(JobCancelled):
        H.apply(H.ConformSelection(), C.ConformRules())
    monkeypatch.undo()
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    info = H.undo_info()
    assert info is not None and info["libraries"] == [house.rel(foreign["pcblib"])]
    assert _sha(foreign["pcblib"]) != before["pcblib"] and _sha(foreign["schlib"]) == before["schlib"]
    undone = H.undo_last()
    assert undone["restored"] == [house.rel(foreign["pcblib"])]
    assert {kind: _sha(path) for kind, path in foreign.items()} == before and H.undo_info() is None


@pytest.mark.rustwriter
def test_partial_undo_keeps_the_rest_undoable(house: Workspace, foreign: dict[str, Path], monkeypatch: pytest.MonkeyPatch):
    before = {kind: _sha(path) for kind, path in foreign.items()}
    assert len(H.apply(H.ConformSelection(), C.ConformRules())["libraries"]) == 2
    _refuse({foreign["schlib"]}, monkeypatch)
    first = H.undo_last()
    assert first["restored"] == [house.rel(foreign["pcblib"])]
    assert [s["library"] for s in first["skipped"]] == [house.rel(foreign["schlib"])]
    info = H.undo_info()
    assert info is not None and info["libraries"] == [house.rel(foreign["schlib"])]  # only what is left
    monkeypatch.setattr(sync._AltiumGuard, "refusal", lambda self, library: None)  # saved/closed in Altium
    second = H.undo_last()
    assert second["restored"] == [house.rel(foreign["schlib"])] and second["skipped"] == []
    assert {kind: _sha(path) for kind, path in foreign.items()} == before and H.undo_info() is None


@pytest.mark.rustwriter
def test_check_names_libraries_apply_would_skip(house: Workspace, foreign: dict[str, Path],
                                                monkeypatch: pytest.MonkeyPatch):
    _refuse({foreign["pcblib"]}, monkeypatch)
    report = H.check(H.ConformSelection(), C.ConformRules())
    refusals = {lib.kind: lib.refusal for lib in report.libraries}
    assert refusals == {"pcblib": sync.ALTIUM_MODIFIED_MESSAGE, "schlib": None}
    out = H.apply(H.ConformSelection(), C.ConformRules())
    assert [s["library"] for s in out["skipped"]] == [house.rel(foreign["pcblib"])]


def test_change_messages_use_the_german_decimal_comma():
    from records_support import chip

    plan = C.plan_footprint(chip("A"), C.infer_layer_roles([chip("A")]), C.FootprintRules(),
                            FootprintStyle(text_font="truetype", text_height=0.8, center_cross=False), LayerMap())
    messages = " ".join(c.message for c in plan.changes)
    assert "Linienbreite 0,1 mm" in messages and "Arial 0,5 mm" not in messages and "0.1 mm" not in messages
    assert "±0,5 mm" in messages
