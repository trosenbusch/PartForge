""""In Altium bearbeiten" (``partforge.altium.editing``): signature, classification, watcher and take-over.

The take-over tests use the real Rust writer (marker ``rustwriter``) to stand in for Altium: they change the
library file behind PartForge's back – as a save in Altium does – and check what PartForge takes over.
No test reaches Altium: the bridge is a fake that records ``edit_component``.
"""
from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_writer_samples import chip_0603

from partforge.altium import editing, libwriter, sync
from partforge.altium.bridge.core import ComponentFocus
from partforge.altium.editing import (
    AltiumEditService,
    ComponentMark,
    EditError,
    FileBaseline,
    classify,
    edit_signature,
)
from partforge.db import registry
from partforge.geometry.model import FootprintSpec, Point, Region, Track
from partforge.jobs import Job, jobs

# --------------------------------------------------------------------------- signature


def _variant(spec: FootprintSpec) -> FootprintSpec:
    """What a plain save in Altium does to a footprint (VERIFIED, see the module docstring of editing)."""
    tracks = [Track(layer=t.layer, x1=t.x2 + 1e-6, y1=t.y2, x2=t.x1, y2=t.y1 - 1e-6, width=t.width)
              for t in reversed(spec.tracks)]
    pads = [p.model_copy(update={"x": p.x + 4e-7, "rotation": p.rotation + 360}) for p in reversed(spec.pads)]
    return spec.model_copy(update={"tracks": tracks, "pads": pads, "bodies": [], "step": None,
                                   "height": (spec.height or 0) + 1e-6, "generator": None})


def test_signature_ignores_what_a_plain_altium_save_changes():
    spec = chip_0603()
    assert edit_signature(_variant(spec)) == edit_signature(spec)


def test_signature_sees_real_edits():
    spec = chip_0603()
    moved = spec.model_copy(update={"pads": [spec.pads[0].model_copy(update={"x": spec.pads[0].x - 0.1}),
                                             *spec.pads[1:]]})
    assert edit_signature(moved) != edit_signature(spec)
    wider = spec.model_copy(update={"tracks": [spec.tracks[0].model_copy(update={"width": 0.2}), *spec.tracks[1:]]})
    assert edit_signature(wider) != edit_signature(spec)
    described = spec.model_copy(update={"description": "neu"})
    assert edit_signature(described) != edit_signature(spec)


def test_signature_includes_the_height_stored_in_the_pcblib():
    """The reader derives spec.height from the 3D bodies; a height set in Altium is only in HEIGHT (VERIFIED)."""
    spec = chip_0603()
    assert edit_signature(spec, height=0.95) == edit_signature(spec, height=0.9500006)
    assert edit_signature(spec, height=1.25) != edit_signature(spec, height=0.95)


def test_signature_of_regions_does_not_depend_on_start_point_or_direction():
    square = [Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1), Point(x=0, y=1)]
    a = chip_0603().model_copy(update={"regions": [Region(layer="courtyard", points=square)]})
    turned = square[2:] + square[:2]
    b = a.model_copy(update={"regions": [Region(layer="courtyard", points=list(reversed(turned)) + [turned[-1]])]})
    assert edit_signature(a) == edit_signature(b)
    other = [Point(x=0, y=0), Point(x=2, y=0), Point(x=2, y=1), Point(x=0, y=1)]
    c = a.model_copy(update={"regions": [Region(layer="courtyard", points=other)]})
    assert edit_signature(c) != edit_signature(a)


def test_listed_names_stay_short():
    assert editing._listed("Aus Altium übernommen", ["A"]) == "Aus Altium übernommen: A."
    names = [f"N{i}" for i in range(7)]
    assert editing._listed("Aus Altium übernommen", names) == "Aus Altium übernommen: N0, N1, N2, N3 und 3 weitere."


# --------------------------------------------------------------------------- classification


def _marks(**items: tuple[str, str | None]) -> dict[str, ComponentMark]:
    return {k: ComponentMark(name=k.upper(), bytes=b, sig=s) for k, (b, s) in items.items()}


def _rec(name: str, library: str = r"Footprints\PF_CHIP.PcbLib", fingerprint: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, library=library, source="generated",
                           spec=SimpleNamespace(fp=fingerprint) if fingerprint else None)


def test_classify_sorts_every_kind_of_change():
    baseline = FileBaseline(components=_marks(
        same=("b1", "s1"), target=("b2", "s2"), resaved=("b3", "s3"), edited=("b4", "s4"), own=("b5", "s5"),
        gone=("b6", "s6"),
    ))
    now = _marks(
        same=("b1", "s1"),  # bytes unchanged
        target=("x2", "s2"),  # opened for editing: bytes changed -> edited even with the same signature
        resaved=("x3", "s3"),  # Altium re-serialised it: same signature -> unchanged
        edited=("x4", "t4"),  # geometry changed
        own=("x5", "t5"),  # PartForge wrote it since the baseline
        new=("x7", "t7"),  # added in Altium
        taken=("x8", "t8"),  # added, but registered in another library
    )
    manifest = sync._Manifest(rel=r"Footprints\PF_CHIP.PcbLib", components={"own": "fp-own"})
    records = {
        "own": _rec("OWN", fingerprint="fp-own"),
        "taken": _rec("TAKEN", library=r"Footprints\PF_SOT23.PcbLib"),
        "gone": _rec("GONE"),
    }
    found = classify(baseline, now, targets=["TARGET"], rel=r"Footprints\PF_CHIP.PcbLib", manifest=manifest,
                     records=records, fingerprint=lambda spec: spec.fp)
    assert found.edited == ["target", "edited"]
    assert found.added == ["new"]
    assert found.own == ["own"]
    assert found.conflicts == ["taken"]
    assert found.removed == ["gone"]
    assert found.taken == ["target", "edited", "new"]


def test_classify_without_valid_manifest_treats_partforge_writes_as_edits():
    baseline = FileBaseline(components=_marks(a=("b1", "s1")))
    now = _marks(a=("x1", "t1"))
    found = classify(baseline, now, targets=[], rel="x", manifest=None, records={"a": _rec("A", library="x",
                     fingerprint="t1")}, fingerprint=lambda spec: spec.fp)
    assert found.edited == ["a"] and found.own == []


# --------------------------------------------------------------------------- watcher (no files read)


class FakeJobs:
    """Job manager whose jobs only finish when the test says so."""

    def __init__(self) -> None:
        self.submitted: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.jobs: list[Job] = []

    def submit(self, kind: str, title: str, fn: Any, *args: Any, **kwargs: Any) -> Job:
        job = Job(id=f"job{len(self.jobs)}", kind=kind, title=title)
        self.submitted.append((kind, args, kwargs))
        self.jobs.append(job)
        return job


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def watched(workspace):
    """A service with one stored session on a dummy library file (nothing is read: the take-over is faked)."""
    lib = workspace.root / "Footprints" / "PF_CHIP.PcbLib"
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_bytes(b"v1")
    st = lib.stat()
    fake, clock = FakeJobs(), Clock()
    service = AltiumEditService(job_manager=fake, clock=clock, settle_s=1.0, retry_s=10.0, max_idle_s=3600,
                                altium_running=None)
    service.load(workspace)
    session = editing.EditSession(id="s1", kind="footprint", library=r"Footprints\PF_CHIP.PcbLib", targets=["A"],
                                  started=editing._now(), last_activity=editing._now(),
                                  baseline=FileBaseline(size=st.st_size, mtime_ns=st.st_mtime_ns))
    service.put(session, sync._Session(workspace, None))
    return SimpleNamespace(ws=workspace, lib=lib, fake=fake, clock=clock, service=service)


def _touch(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    stat = path.stat()
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))


def test_watcher_waits_until_the_saved_file_settles(watched):
    s = watched
    assert s.service.poll() == []
    _touch(s.lib, b"v2-longer")
    assert s.service.poll() == []  # first sight of the change
    s.clock.now += 0.5
    assert s.service.poll() == []  # not settled yet
    s.clock.now += 0.6
    started = s.service.poll()
    assert len(started) == 1 and s.fake.submitted[0][0] == editing.TAKE_OVER_JOB_KIND
    assert s.fake.submitted[0][1][1] == "s1"
    s.clock.now += 5
    assert s.service.poll() == []  # the job is still running: no second one
    assert s.service.info(s.ws)[0].state == "checking"


def test_watcher_backs_off_after_failures_and_waits_for_the_next_save(watched):
    s = watched
    _touch(s.lib, b"v2-longer")
    s.service.poll()
    s.clock.now += 2
    for attempt in range(editing.MAX_ATTEMPTS):
        started = s.service.poll()
        assert len(started) == 1, attempt
        job = started[0]
        job.status, job.error = "failed", "kaputt"
        s.clock.now += 1
        assert s.service.poll() == []  # backing off
        s.clock.now += 10 * (attempt + 1)
    assert s.service.poll() == []  # gave up on this file version
    info = s.service.info(s.ws)[0]
    assert info.state == "error" and info.error == "kaputt"
    _touch(s.lib, b"v3-even-longer")  # the next save is tried again
    s.service.poll()
    s.clock.now += 2
    assert len(s.service.poll()) == 1


def test_idle_sessions_end_and_altium_exit_ends_them(watched):
    s = watched
    s.clock.now += 3601
    s.service.poll()
    assert s.service.sessions() == [] and editing._load_sessions() == []

    gone = AltiumEditService(job_manager=FakeJobs(), clock=s.clock, altium_running=lambda: False,
                             altium_gone_s=30, altium_check_s=1)
    session = editing.EditSession(id="s2", kind="footprint", library=r"Footprints\PF_CHIP.PcbLib", targets=["A"],
                                  started=editing._now(), last_activity=editing._now(),
                                  baseline=FileBaseline(size=s.lib.stat().st_size, mtime_ns=s.lib.stat().st_mtime_ns))
    gone.put(session, sync._Session(s.ws, None))
    gone.poll()
    assert gone.sessions()  # not long enough
    s.clock.now += 31
    gone.poll()
    assert gone.sessions() == []


def test_sessions_are_stored_in_the_library_and_loaded_again(watched):
    s = watched
    again = AltiumEditService(job_manager=FakeJobs(), altium_running=None)
    assert [x.id for x in again.load(s.ws)] == ["s1"]
    assert again.session_for(r"footprints\pf_chip.pcblib").targets == ["A"]


def test_end_without_a_save_ends_at_once_and_with_a_save_takes_it_over_first(watched):
    s = watched
    _touch(s.lib, b"v2-longer")
    job = s.service.end(s.ws, "s1")
    assert job is not None and s.fake.submitted[-1][2]["final"] is True
    job.status = "done"
    s.service.poll()
    with pytest.raises(KeyError):
        s.service.end(s.ws, "nope")


# --------------------------------------------------------------------------- take-over with the real writer


class FakeBridge:
    def __init__(self, *, found: bool = True) -> None:
        self.found = found
        self.calls: list[tuple[Path, str, str | None]] = []

    def edit_component(self, path: Path, name: str, kind: str | None = None) -> ComponentFocus:
        self.calls.append((Path(path), name, kind))
        return ComponentFocus(path=str(path), name=name, was_open=False, found=self.found, current=name)


@pytest.fixture
def chip_library(workspace, monkeypatch):
    """Two generated chip footprints written by the real Rust writer."""
    from partforge.footprints import FootprintRequest
    from partforge.footprints import generate as generate_footprint

    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    specs = [generate_footprint(FootprintRequest(family="chip", params={"preset": p})) for p in ("R-0603", "R-0805")]
    records = sync.ensure_footprints(specs)
    assert [r.status for r in records] == ["ok", "ok"], [r.status_message for r in records]
    path = workspace.abs(records[0].library)
    assert path is not None and path.is_file()
    service = AltiumEditService(altium_running=None)
    service.load(workspace)
    yield SimpleNamespace(ws=workspace, path=path, rel=records[0].library, names=[r.name for r in records],
                          service=service, writer=libwriter.get_writer(workspace=workspace))
    service.stop()


def _start(lib: SimpleNamespace, name: str, bridge: FakeBridge | None = None) -> dict[str, Any]:
    bridge = bridge or FakeBridge()
    job = jobs.run_sync(editing.START_JOB_KIND, "t", editing.start_editing, str(lib.ws.root), "footprint", name,
                        bridge, service=lib.service)
    assert job.status == "done", (job.error, job.log[-3:])
    return job.result


def _take_over(lib: SimpleNamespace, session_id: str, **kwargs: Any) -> dict[str, Any]:
    job = jobs.run_sync(editing.TAKE_OVER_JOB_KIND, "t", editing.take_over, str(lib.ws.root), session_id,
                        service=lib.service, **kwargs)
    assert job.status == "done", (job.error, job.log[-3:])
    return job.result


def _save_in_altium(lib: SimpleNamespace, spec: FootprintSpec) -> None:
    """Change the library file the way a save in Altium does: behind PartForge's back (no manifest)."""
    time.sleep(0.02)
    result = lib.writer.write_footprints(lib.path, [spec])
    assert not result.errors, result.errors
    libwriter.forget_component_names(lib.path)


@pytest.mark.rustwriter
def test_start_records_the_baseline_and_shows_the_component(chip_library):
    lib = chip_library
    bridge = FakeBridge()
    result = _start(lib, lib.names[0], bridge)
    assert bridge.calls == [(lib.path, lib.names[0], "PCBLIB")]
    assert result["found"] and "nach dem Speichern" in result["message"]
    session = lib.service.session(result["session"])
    assert session is not None and session.targets == [lib.names[0]]
    assert set(session.baseline.components) == {n.casefold() for n in lib.names}
    assert all(m.bytes and m.sig for m in session.baseline.components.values())
    # the same file again: the session continues with a second target
    again = _start(lib, lib.names[1])
    assert again["session"] == result["session"] and again["continued"]
    assert lib.service.session(result["session"]).targets == lib.names
    info = lib.service.info(lib.ws)
    assert len(info) == 1 and info[0].state == "watching" and info[0].library_abs == str(lib.path)


@pytest.mark.rustwriter
def test_saved_edit_is_taken_over_as_altium_version(chip_library):
    lib = chip_library
    session_id = _start(lib, lib.names[0])["session"]
    before = registry.get_footprint(lib.names[0])
    other_before = registry.get_footprint(lib.names[1])
    assert before is not None and before.spec is not None and other_before is not None
    pads = [p.model_copy(update={"width": p.width + 0.1}) for p in before.spec.pads]
    _save_in_altium(lib, before.spec.model_copy(update={"pads": pads, "generator": None}))

    result = _take_over(lib, session_id)
    assert result["edited"] == [lib.names[0]] and not result["quiet"]
    assert result["message"] == f"Aus Altium übernommen: {lib.names[0]}."
    rec = registry.get_footprint(lib.names[0])
    assert rec is not None and rec.source == "altium" and rec.status == "ok" and rec.spec is not None
    assert [round(p.width, 3) for p in rec.spec.pads] == [round(p.width, 3) for p in pads]
    generator = rec.spec.generator or {}
    assert generator["family"] == "chip" and "params" in generator  # "Bearbeiten" still works
    assert "geometry_hash" not in generator and "land_hash" not in generator
    assert generator["altium_edit"]["previous_source"] == "generated"
    assert rec.family == before.family and rec.ipc_name == before.ipc_name
    other = registry.get_footprint(lib.names[1])
    assert other is not None and other.source == "generated" and other.spec == other_before.spec
    # the manifest holds the saved file; nothing in it is "exactly PartForge's" any more
    manifest = sync._load_manifest(lib.rel)
    assert manifest is not None and manifest.matches(lib.path)
    assert manifest.components[lib.names[0].casefold()] is None
    assert not any(f.external_changes for f in sync.library_files(check_layers=False) if f.rel == lib.rel)
    # the session goes on from the saved file
    session = lib.service.session(session_id)
    assert session is not None and session.last_result is not None and session.last_result.edited == [lib.names[0]]
    assert _take_over(lib, session_id)["quiet"]  # nothing new


@pytest.mark.rustwriter
def test_partforge_writes_are_no_altium_edits(chip_library):
    lib = chip_library
    from partforge.footprints import FootprintRequest
    from partforge.footprints import generate as generate_footprint

    session_id = _start(lib, lib.names[0])["session"]
    extra = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-1206"}))
    assert sync.ensure_footprints([extra])[0].status == "ok"
    result = _take_over(lib, session_id)
    assert result["quiet"] and result["edited"] == [] and result["added"] == []
    # a new component in PartForge's own, unchanged file regenerates the whole file: every footprint is new bytes,
    # all of them PartForge's own writes
    assert extra.name in result["own"]
    assert {r.source for r in registry.list_footprints()} == {"generated"}
    assert extra.name.casefold() in lib.service.session(session_id).baseline.components


@pytest.mark.rustwriter
def test_saving_from_partforge_replaces_the_altium_version(chip_library):
    lib = chip_library
    session_id = _start(lib, lib.names[0])["session"]
    original = registry.get_footprint(lib.names[0])
    assert original is not None and original.spec is not None
    pads = [p.model_copy(update={"width": p.width + 0.1}) for p in original.spec.pads]
    _save_in_altium(lib, original.spec.model_copy(update={"pads": pads, "generator": None}))
    _take_over(lib, session_id)
    assert registry.get_footprint(lib.names[0]).source == "altium"
    # "Neu generieren": the generator spec again – written, even though PartForge had it before
    records = sync.ensure_footprints([original.spec], source="generated")
    assert records[0].status == "ok" and records[0].source == "generated"
    assert [p.width for p in records[0].spec.pads] == [p.width for p in original.spec.pads]
    read_back = lib.writer.read_footprint(lib.path, lib.names[0])
    assert read_back is not None and [round(p.width, 3) for p in read_back.pads] == [
        round(p.width, 3) for p in original.spec.pads]


@pytest.mark.rustwriter
def test_rename_in_altium_is_reported_and_the_new_name_registered(chip_library):
    lib = chip_library
    session_id = _start(lib, lib.names[0])["session"]
    spec = registry.get_footprint(lib.names[0]).spec
    renamed = spec.model_copy(update={"name": "MY_CHIP", "generator": None})
    time.sleep(0.02)
    lib.writer.delete_components(lib.path, [lib.names[0]])
    _save_in_altium(lib, renamed)
    result = _take_over(lib, session_id)
    assert result["renamed"] == lib.names[0] and result["added"] == ["MY_CHIP"]
    assert "vermutlich in „MY_CHIP“ umbenannt" in result["message"]
    old = registry.get_footprint(lib.names[0])
    assert old is not None and old.status == "missing" and "MY_CHIP" in (old.status_message or "")
    new = registry.get_footprint("MY_CHIP")
    assert new is not None and new.source == "altium" and new.library == lib.rel
    assert lib.service.session(session_id).targets == ["MY_CHIP"]


@pytest.mark.rustwriter
def test_end_takes_a_pending_save_over_and_removes_the_session(chip_library):
    lib = chip_library
    session_id = _start(lib, lib.names[0])["session"]
    spec = registry.get_footprint(lib.names[0]).spec
    _save_in_altium(lib, spec.model_copy(update={"description": "In Altium geändert", "generator": None}))
    result = _take_over(lib, session_id, final=True)
    assert result["ended"] and result["edited"] == [lib.names[0]]
    assert lib.service.session(session_id) is None and editing._load_sessions() == []
    assert registry.get_footprint(lib.names[0]).spec.description == "In Altium geändert"


@pytest.mark.rustwriter
def test_watcher_takes_a_save_over_on_its_own(chip_library):
    lib = chip_library
    clock = Clock()
    service = AltiumEditService(altium_running=None, clock=clock, settle_s=0.5)
    lib.service = service
    service.load(lib.ws)
    session_id = _start(lib, lib.names[1])["session"]
    spec = registry.get_footprint(lib.names[1]).spec
    _save_in_altium(lib, spec.model_copy(update={"description": "gespeichert", "generator": None}))
    assert service.poll() == []
    clock.now += 1
    started = service.poll()
    assert len(started) == 1
    assert service.wait_idle(60)
    job = started[0]
    assert job.status == "done", job.error
    assert job.result["edited"] == [lib.names[1]]
    assert registry.get_footprint(lib.names[1]).source == "altium"
    service.poll()
    assert service.info(lib.ws)[0].state == "watching"


@pytest.mark.rustwriter
def test_components_that_cannot_be_edited(chip_library):
    lib = chip_library
    with pytest.raises(EditError) as exc:
        editing._editable(lib.ws, "footprint", "GIBT_ES_NICHT")
    assert exc.value.status == 404
    sync._set_status("footprint", lib.names[0], "pending", None)
    with pytest.raises(EditError, match="Synchronisieren"):
        editing._editable(lib.ws, "footprint", lib.names[0])


@pytest.mark.rustwriter
def test_bridge_failure_leaves_no_session(chip_library):
    lib = chip_library

    class Broken(FakeBridge):
        def edit_component(self, path: Path, name: str, kind: str | None = None) -> ComponentFocus:
            from partforge.altium.bridge.core import AltiumNotRunning

            raise AltiumNotRunning("Altium Designer ist nicht gestartet.")

    job = jobs.run_sync(editing.START_JOB_KIND, "t", editing.start_editing, str(lib.ws.root), "footprint",
                        lib.names[0], Broken(), service=lib.service)
    assert job.status == "failed" and "nicht gestartet" in (job.error or "")
    assert lib.service.sessions() == [] and editing._load_sessions() == []


@pytest.mark.rustwriter
def test_symbol_pin_change_in_altium_is_taken_over_with_a_hint(workspace, monkeypatch):
    from partforge.symbols import SymbolRequest
    from partforge.symbols import generate as generate_symbol

    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    spec = generate_symbol(SymbolRequest(kind="resistor"))
    rec = sync.ensure_symbols([spec])[0]
    assert rec.status == "ok", rec.status_message
    path = workspace.abs(rec.library)
    service = AltiumEditService(altium_running=None)
    service.load(workspace)
    lib = SimpleNamespace(ws=workspace, service=service)
    job = jobs.run_sync(editing.START_JOB_KIND, "t", editing.start_editing, str(workspace.root), "symbol", rec.name,
                        FakeBridge(), service=service)
    assert job.status == "done", job.error
    session_id = job.result["session"]
    pins = [p.model_copy(update={"name": "X"}) if p.designator == "1" else p for p in rec.spec.pins]
    time.sleep(0.02)
    writer = libwriter.get_writer(workspace=workspace)
    assert not writer.write_symbols(path, [rec.spec.model_copy(update={"pins": pins, "generator": None})]).errors
    libwriter.forget_component_names(path)
    result = _take_over(lib, session_id)
    assert result["edited"] == [rec.name]
    assert any("Pinbelegung in Altium geändert" in w for w in result["warnings"])
    taken = registry.get_symbol(rec.name)
    assert taken.source == "altium" and taken.spec.generator["kind"] == "resistor"
    assert {p.designator: p.name for p in taken.spec.pins}["1"] == "X"
    service.stop()


# --------------------------------------------------------------------------- API


@pytest.fixture
def edit_api(chip_library):
    from fastapi.testclient import TestClient
    from test_refresh_support import FakeBridge as RefreshBridge

    from partforge.api import routes_altium, routes_altium_edit
    from partforge.app import TOKEN_HEADER, create_app

    bridge = RefreshBridge()
    app = create_app(token="edit-token")
    app.dependency_overrides[routes_altium.get_bridge] = lambda: bridge
    app.dependency_overrides[routes_altium_edit.get_edit_service] = lambda: chip_library.service
    with TestClient(app, headers={TOKEN_HEADER: "edit-token"}) as client:
        yield SimpleNamespace(client=client, bridge=bridge, lib=chip_library)


def _job(client: Any, response: Any) -> dict[str, Any]:
    from test_refresh_support import wait_job

    assert response.status_code == 200, response.text
    return wait_job(response.json()["job"]["id"], timeout_s=60)


@pytest.mark.rustwriter
def test_api_edit_session_lifecycle(edit_api):
    c, lib = edit_api.client, edit_api.lib
    snap = _job(c, c.post("/api/altium/edit", json={"kind": "footprint", "name": lib.names[0]}))
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["found"] and edit_api.bridge.names() == ["edit_component"]
    sessions = c.get("/api/altium/edit/sessions").json()
    assert len(sessions) == 1 and sessions[0]["targets"] == [lib.names[0]] and sessions[0]["state"] == "watching"
    session_id = sessions[0]["id"]
    check = _job(c, c.post(f"/api/altium/edit/sessions/{session_id}/check"))
    assert check["status"] == "done" and check["result"]["quiet"]
    ended = c.post(f"/api/altium/edit/sessions/{session_id}/end").json()
    assert ended["ended"] and ended["job"] is None
    assert c.get("/api/altium/edit/sessions").json() == []
    assert c.post(f"/api/altium/edit/sessions/{session_id}/end").status_code == 404
    assert c.post(f"/api/altium/edit/sessions/{session_id}/check").status_code == 404


@pytest.mark.rustwriter
def test_api_edit_refusals(edit_api):
    c, lib = edit_api.client, edit_api.lib
    assert c.post("/api/altium/edit", json={"kind": "footprint", "name": "GIBT_ES_NICHT"}).status_code == 404
    sync._set_status("footprint", lib.names[1], "pending", None)
    pending = c.post("/api/altium/edit", json={"kind": "footprint", "name": lib.names[1]})
    assert pending.status_code == 409 and "Synchronisieren" in pending.json()["detail"]
    edit_api.bridge.running = False
    off = c.post("/api/altium/edit", json={"kind": "footprint", "name": lib.names[0]})
    assert off.status_code == 503 and "nicht gestartet" in off.json()["detail"]
    assert c.post("/api/altium/edit", json={"kind": "part", "name": "x"}).status_code == 422
