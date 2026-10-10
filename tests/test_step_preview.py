"""STEP preview resolves vendor geometry without altering imported libraries or specs."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import pytest

from partforge.altium.rustwriter import RustLibraryOps, RustWriterUnavailable
from partforge.db import registry
from partforge.db.models import FootprintRecord
from partforge.footprints import FootprintRequest, generate, step_text
from partforge.geometry.model import FootprintSpec, StepModel


def _url(name: str, suffix: str = "/step-models") -> str:
    return f"/api/libraries/footprints/{quote(name, safe='')}{suffix}"


def _step(path: Path, name: str = "Vendor model") -> Path:
    """A complete, coloured STEP solid with an ordinary vendor header."""
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    text = step_text(spec.model_copy(update={"name": name}))
    # A vendor file may describe exactly the same solid, without our generated-file marker.
    text = re.sub(r"pf:[a-f0-9]{16}", "vendor-model", text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="ascii")
    return path


def _register(workspace, name: str, *, step: StepModel | None = None, spec=None, source="imported"):
    record = FootprintRecord(
        name=name,
        library="Footprints\\Vendor.PcbLib",
        source=source,
        spec=spec if spec is not None else FootprintSpec(name=name, step=step),
        status="ok",
    )
    registry.upsert_footprint(record)
    return record


def _raw_models(monkeypatch, workspace, bodies: list[dict], files: dict[str, Path]):
    library = workspace.footprints_dir / "Vendor.PcbLib"
    library.write_bytes(b"original opaque vendor library")
    calls: list[dict[str, str]] = []

    def component(self, path, name, kind):
        assert Path(path) == library
        assert kind == "pcblib"
        return {"name": name, "component_bodies": bodies}

    def extract(self, path, wanted):
        assert Path(path) == library
        calls.append(dict(wanted))
        return {key: value for key, value in files.items() if key in wanted}

    monkeypatch.setattr(RustLibraryOps, "_get_component", component)
    monkeypatch.setattr(RustLibraryOps, "_extract_models", extract)
    return library, calls


def test_saved_step_preview_needs_no_writer_and_preserves_placement(client, workspace, monkeypatch):
    name = "Vendor/QFN 8 (EP+)"
    path = _step(workspace.models_dir / "vendor QFN.stp")
    placement = StepModel(file="3D\\vendor QFN.stp", rotation=(90, -15, 180), offset=(1.5, -2, 0.25))
    _register(workspace, name, step=placement)

    def unavailable(*args, **kwargs):
        raise RustWriterUnavailable("Writer deliberately unavailable")

    monkeypatch.setattr(RustLibraryOps, "client", unavailable)
    response = client.get(_url(name))
    assert response.status_code == 200, response.text
    models = response.json()["models"]
    assert len(models) == 1
    assert models[0]["rotation"] == [90, -15, 180]
    assert models[0]["offset"] == [1.5, -2, 0.25]
    assert models[0]["id"] and str(workspace.root) not in models[0]["url"]
    downloaded = client.get(models[0]["url"])
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-type"].startswith("model/step")
    assert downloaded.content == path.read_bytes()


def test_embedded_models_are_loaded_lazily_with_every_placement(client, workspace, monkeypatch, tmp_path):
    _register(workspace, "ASSEMBLY")  # import with extract3d=False: no saved spec.step
    body = _step(tmp_path / "cache" / "body.step", "Body")
    cap = _step(tmp_path / "cache" / "cap.step", "Cap")
    bodies = [
        {"model_id": "body-id", "model_name": "body.step", "embedded": True,
         "rotation_x": 90, "rotation_y": 15, "rotation_z": 180,
         "model_2d_x": 1.25, "model_2d_y": -2.5, "z_offset": 0.75},
        {"model_id": "cap-id", "model_name": "cap.step", "embedded": True,
         "model_2d_x": -1, "z_offset": 2},
        {"model_id": "cap-id", "model_name": "cap.step", "embedded": True,
         "rotation_z": 90, "model_2d_x": 1, "z_offset": 2},
    ]
    library, calls = _raw_models(monkeypatch, workspace, bodies, {"body-id": body, "cap-id": cap})
    original = library.read_bytes()
    response = client.get(_url("ASSEMBLY"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert not result["warnings"], result["warnings"]
    models = result["models"]
    assert len(models) == 3
    assert models[0]["rotation"] == [90, 15, 180]
    assert models[0]["offset"] == [1.25, -2.5, 0.75]
    assert models[1]["offset"] == [-1, 0, 2]
    assert models[2]["rotation"] == [0, 0, 90]
    assert len({model["id"] for model in models}) == 3
    assert calls[0] == {"body-id": "body.step", "cap-id": "cap.step"}
    assert [client.get(model["url"]).content for model in models] == [body.read_bytes(), cap.read_bytes(), cap.read_bytes()]
    # Preview and lazy extraction never rewrite the library or the saved editable spec.
    assert library.read_bytes() == original
    assert registry.get_footprint("ASSEMBLY").spec.step is None
    assert list(workspace.models_dir.iterdir()) == []
    assert client.get(_url("ASSEMBLY", "/step")).content == body.read_bytes()


def test_real_extraction_cache_is_reused_and_invalidated_by_library_changes(client, workspace, monkeypatch, tmp_path):
    from partforge.altium import rustwriter

    _register(workspace, "CACHED")
    library = workspace.footprints_dir / "Vendor.PcbLib"
    library.write_bytes(b"opaque vendor library revision A")
    original = library.read_bytes()
    stored = registry.get_footprint("CACHED").model_dump(mode="json")
    bodies = [
        {"model_id": "body-id", "model_name": "body.step", "embedded": True},
        {"model_id": "cap-id", "model_name": "cap.step", "embedded": True, "z_offset": 2},
    ]
    extraction_calls = []

    class FakeClient:
        def call_tool(self, tool, arguments):
            assert tool == "extract_step_model"
            assert Path(arguments["filepath"]) == library
            assert arguments["mode"] == "extract_all"
            extraction_calls.append(arguments)
            output = Path(arguments["output_path"])
            output.mkdir(parents=True)
            extracted = []
            for body in bodies:
                path = _step(output / body["model_name"], f"{body['model_id']} revision {len(extraction_calls)}")
                extracted.append({"id": body["model_id"], "output_path": str(path)})
            return {"extracted": extracted}

    def component(self, path, name, kind):
        assert Path(path) == library and name == "CACHED" and kind == "pcblib"
        return {"name": name, "component_bodies": bodies}

    monkeypatch.setattr(RustLibraryOps, "_get_component", component)
    monkeypatch.setattr(RustLibraryOps, "client", lambda self: FakeClient())
    monkeypatch.setattr(rustwriter, "step_cache_dir", lambda: tmp_path / "step-cache")

    first = client.get(_url("CACHED")).json()["models"]
    assert len(first) == 2
    first_contents = [client.get(model["url"]).content for model in first]
    assert all(data.startswith(b"ISO-10303-21;") for data in first_contents)
    assert client.get(_url("CACHED")).json()["models"] == first
    assert len(extraction_calls) == 1  # Both manifests and each binary reuse the same extraction.
    assert library.read_bytes() == original
    assert registry.get_footprint("CACHED").model_dump(mode="json") == stored
    assert list(workspace.models_dir.iterdir()) == []

    library.write_bytes(original + b" changed revision B")
    second = client.get(_url("CACHED")).json()["models"]
    second_contents = [client.get(model["url"]).content for model in second]
    assert len(extraction_calls) == 2
    assert second_contents != first_contents
    assert {model["id"] for model in second}.isdisjoint(model["id"] for model in first)
    assert client.get(first[0]["url"]).status_code == 404
    assert registry.get_footprint("CACHED").model_dump(mode="json") == stored


def test_linked_step_resolves_relative_to_the_source_library(client, workspace, monkeypatch):
    _register(workspace, "LINKED")
    path = _step(workspace.footprints_dir / "Models" / "linked.step")
    _raw_models(monkeypatch, workspace, [
        {"model_name": "Models\\linked.step", "embedded": False, "model_2d_y": 4, "rotation_z": 45},
    ], {})
    response = client.get(_url("LINKED"))
    assert response.status_code == 200, response.text
    models = response.json()["models"]
    assert len(models) == 1
    assert models[0]["rotation"] == [0, 0, 45]
    assert models[0]["offset"] == [0, 4, 0]
    assert client.get(models[0]["url"]).content == path.read_bytes()


def test_raw_board_rotation_is_added_to_step_rotation_without_rotating_offsets(client, workspace, monkeypatch, tmp_path):
    _register(workspace, "PLACED")
    path = _step(tmp_path / "placed.step")
    _raw_models(monkeypatch, workspace, [
        {"model_id": "placed-id", "model_name": "placed.step", "embedded": True,
         "rotation_x": 90, "rotation_y": -15, "rotation_z": 30, "model_2d_rotation": 45,
         "model_2d_x": 1.25, "model_2d_y": -2.5, "z_offset": 0.75},
    ], {"placed-id": path})
    response = client.get(_url("PLACED"))
    assert response.status_code == 200, response.text
    model = response.json()["models"][0]
    assert model["rotation"] == [90, -15, 75]
    assert model["offset"] == [1.25, -2.5, 0.75]
    assert client.get(model["url"]).content == path.read_bytes()


def test_missing_absolute_link_can_be_restored_in_workspace_3d_folder(client, workspace, monkeypatch, tmp_path):
    _register(workspace, "RESTORED")
    missing = tmp_path / "Original vendor location" / "linked.step"
    _raw_models(monkeypatch, workspace, [
        {"model_name": str(missing), "embedded": False, "rotation_x": 90,
         "model_2d_x": 1.5, "model_2d_y": -2, "z_offset": 0.25},
    ], {})
    first = client.get(_url("RESTORED")).json()
    assert first["models"] == []
    assert any("linked.step" in warning for warning in first["warnings"])

    recovered = _step(workspace.models_dir / "linked.step")
    second = client.get(_url("RESTORED")).json()
    assert second["warnings"] == []
    assert len(second["models"]) == 1
    model = second["models"][0]
    assert model["rotation"] == [90, 0, 0]
    assert model["offset"] == [1.5, -2, 0.25]
    assert client.get(model["url"]).content == recovered.read_bytes()
    assert not missing.exists()
    assert registry.get_footprint("RESTORED").spec.step is None


def test_unavailable_embedded_model_is_a_warning_and_saved_model_still_works(client, workspace, monkeypatch):
    path = _step(workspace.models_dir / "fallback.step")
    _register(workspace, "FALLBACK", step=StepModel(file="3D\\fallback.step"))
    library = workspace.footprints_dir / "Vendor.PcbLib"
    library.write_bytes(b"source library")

    def unavailable(*args, **kwargs):
        raise RustWriterUnavailable("Writer deliberately unavailable")

    monkeypatch.setattr(RustLibraryOps, "_get_component", unavailable)
    response = client.get(_url("FALLBACK"))
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["models"]) == 1
    assert result["warnings"]
    assert client.get(result["models"][0]["url"]).content == path.read_bytes()


def test_missing_embedded_model_does_not_hide_the_models_that_loaded(client, workspace, monkeypatch, tmp_path):
    _register(workspace, "PARTIAL")
    path = _step(tmp_path / "available.step")
    _raw_models(monkeypatch, workspace, [
        {"model_id": "available", "model_name": "available.step", "embedded": True},
        {"model_id": "missing", "model_name": "missing.step", "embedded": True},
    ], {"available": path})
    result = client.get(_url("PARTIAL")).json()
    assert len(result["models"]) == 1
    assert any("missing.step" in warning for warning in result["warnings"])
    assert client.get(result["models"][0]["url"]).content == path.read_bytes()


def test_generated_prisms_are_not_duplicated_by_their_automatic_step(client, workspace):
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    path = workspace.models_dir / "automatic.step"
    path.write_text(step_text(spec), encoding="ascii")
    spec.step = StepModel(file="3D\\automatic.step")
    _register(workspace, spec.name, spec=spec, source="generated")
    result = client.get(_url(spec.name)).json()
    assert result["models"] == []
    assert result["warnings"] == []
    assert client.get(_url(spec.name, "/step")).status_code == 200

    # The identical shape at another placement is intentional geometry, not a duplicate.
    spec.step.offset = (0, 0, 1.5)
    _register(workspace, spec.name, spec=spec, source="generated")
    placed = client.get(_url(spec.name)).json()["models"]
    assert len(placed) == 1 and placed[0]["offset"] == [0, 0, 1.5]
    spec.step.offset = (0, 0, 0)
    _register(workspace, spec.name, spec=spec, source="generated")

    # Files exported by PartForge for another footprint are still valid custom references.
    foreign = generate(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    path.write_text(step_text(foreign), encoding="ascii")
    result = client.get(_url(spec.name)).json()
    assert len(result["models"]) == 1

    # An explicitly assigned vendor model is not the automatic prism export.
    _step(path)
    result = client.get(_url(spec.name)).json()
    assert len(result["models"]) == 1


def test_preview_ids_change_when_model_content_or_placement_changes(client, workspace):
    path = _step(workspace.models_dir / "revision.step", "Revision A")
    record = _register(workspace, "REVISION", step=StepModel(file="3D\\revision.step"))
    first = client.get(_url(record.name)).json()["models"][0]
    _step(path, "Revision B")
    second = client.get(_url(record.name)).json()["models"][0]
    assert second["id"] != first["id"]
    assert second["url"] != first["url"]
    assert client.get(first["url"]).status_code == 404
    assert client.get(second["url"]).content == path.read_bytes()

    record.spec.step.offset = (0, 0, 2)
    registry.upsert_footprint(record)
    third = client.get(_url(record.name)).json()["models"][0]
    assert third["id"] != second["id"]
    assert third["offset"] == [0, 0, 2]
    assert client.get(second["url"]).status_code == 404


def test_resolved_model_is_bound_to_workspace_and_exact_file_revision(workspace, tmp_path):
    from partforge.altium.step_preview import resolve_models
    from partforge.workspace import Workspace

    path = _step(tmp_path / "shared.step", "Original")
    record = _register(workspace, "SHARED", step=StepModel(file=str(path)), source="generated")
    models, warnings = resolve_models(workspace, record)
    assert not warnings
    other = Workspace.create(tmp_path / "Other library")
    others, _ = resolve_models(other, record)
    assert models[0].id != others[0].id
    # A file replacement between resolution and response must not silently serve stale URLs.
    _step(path, "Replaced")
    with pytest.raises(ValueError):
        models[0].read()


def test_oversized_step_is_reported_without_reading_its_contents(client, workspace):
    from partforge.altium.step_preview import MAX_STEP_BYTES

    path = workspace.models_dir / "huge.step"
    with path.open("wb") as stream:
        stream.write(b"ISO-10303-21;\n")
        stream.truncate(MAX_STEP_BYTES + 1)
    _register(workspace, "HUGE", step=StepModel(file="3D\\huge.step"), source="generated")
    result = client.get(_url("HUGE")).json()
    assert result["models"] == []
    assert any("64 MB" in warning for warning in result["warnings"])


@pytest.mark.parametrize("filename,content", [
    ("not-a-step.step", b"private text, not a STEP document"),
    ("wrong-extension.txt", b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;"),
])
def test_preview_does_not_serve_invalid_or_unrelated_files(client, workspace, filename, content):
    path = workspace.models_dir / filename
    path.write_bytes(content)
    _register(workspace, "INVALID", step=StepModel(file=f"3D\\{filename}"))
    response = client.get(_url("INVALID"))
    assert response.status_code == 200, response.text
    assert response.json()["models"] == []
    assert response.json()["warnings"]


def test_preview_endpoints_require_known_footprint_and_session_token(client, workspace):
    assert client.get(_url("UNKNOWN")).status_code == 404
    _step(workspace.models_dir / "private.step")
    _register(workspace, "PRIVATE", step=StepModel(file="3D\\private.step"))
    model = client.get(_url("PRIVATE")).json()["models"][0]
    assert client.get(_url("PRIVATE"), headers={"X-PartForge-Token": "wrong-token"}).status_code in (401, 403)
    assert client.get(model["url"], headers={"X-PartForge-Token": "wrong-token"}).status_code in (401, 403)
    registry.delete_footprint("PRIVATE")
    assert client.get(model["url"]).status_code == 404


def test_preview_requests_cannot_use_a_workspace_that_has_been_closed(workspace, monkeypatch, tmp_path):
    from fastapi import HTTPException, Response

    from partforge.api import routes_libraries
    from partforge.db import close_database, open_database
    from partforge.workspace import Workspace, set_current

    replacement = Workspace.create(tmp_path / "Replacement")
    close_database()
    open_database(replacement)
    set_current(replacement)
    try:
        def forbidden_read(*args, **kwargs):
            pytest.fail("A stale preview request must not query the newly opened library")

        with monkeypatch.context() as patch:
            patch.setattr(registry, "get_footprint", forbidden_read)
            requests = [
                lambda: routes_libraries.footprint_step_models("STALE", Response(), ws=workspace),
                lambda: routes_libraries.footprint_step_model("STALE", "a" * 64, ws=workspace),
                lambda: routes_libraries.download_step("STALE", ws=workspace),
            ]
            for request in requests:
                with pytest.raises(HTTPException) as error:
                    request()
                assert error.value.status_code == 409
    finally:
        close_database()
        open_database(workspace)
        set_current(workspace)
