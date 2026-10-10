"""Hausstil aus Beispielbibliothek (``partforge.altium.learnstyle``): proposals from reference libraries."""
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from test_writer_samples import chip_0603, ic8_symbol

from partforge.altium import learnstyle, libimport, libwriter, sync
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.workspace import SymbolStyle, Workspace, WorkspaceSettings


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    cache = tmp_path / "cache"
    monkeypatch.setattr(libimport, "_cache_dir", lambda: cache.mkdir(parents=True, exist_ok=True) or cache)
    libwriter.forget_component_names()


def test_paths_without_libraries(tmp_path: Path):
    files, notes = learnstyle.library_paths([str(tmp_path / "missing")])
    assert files == [] and "wurde nicht gefunden" in notes[0]
    (tmp_path / "empty").mkdir()
    with pytest.raises(libimport.ImportError_, match="Keine Symbol- oder Footprint-Bibliothek"):
        learnstyle.learn([str(tmp_path / "empty")], WorkspaceSettings())


def test_unreadable_reference_is_a_note(tmp_path: Path):
    bad = tmp_path / "Broken.SchLib"
    bad.write_bytes(b"not a compound file")
    proposal = learnstyle.learn([str(bad)], WorkspaceSettings())
    assert proposal.symbols == 0 and any("Broken.SchLib" in n for n in proposal.notes)


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    """A reference library made the way the user wants every component: Verdana 9, 100-mil IC pins, TrueType
    texts (Verdana 0.8 mm) – written with PartForge's own writer."""
    ref = Workspace.create(tmp_path / "Referenz", name="Referenz")
    ref.settings.symbol = SymbolStyle(font="Verdana", font_size=9, ic_pin_length=100)
    ref.save()
    ops = RustLibraryOps(workspace=ref)
    ic = ic8_symbol("REF_TIMER")
    ic = ic.model_copy(update={"pins": [p.model_copy(update={"length": 100}) for p in ic.pins]})
    fp = chip_0603("REF_0603")
    fp = fp.model_copy(update={"texts": [t.model_copy(update={"font": "truetype", "font_name": "Verdana", "height": 0.8})
                                         for t in fp.texts]})
    assert not ops.upsert_symbols(ref.symbols_dir / "Referenz.SchLib", [ic]).errors
    assert not ops.upsert_footprints(ref.footprints_dir / "Referenz.PcbLib", [fp]).errors
    return ref.root


def _findings(proposal: learnstyle.StyleProposal) -> dict[tuple[str, str], learnstyle.StyleFinding]:
    return {(f.area, f.key): f for f in proposal.findings}


@pytest.mark.rustwriter
def test_learn_from_a_reference_folder(reference: Path):
    settings = WorkspaceSettings()
    proposal = learnstyle.learn([str(reference)], settings)
    assert proposal.symbols == 1 and proposal.footprints == 1
    found = _findings(proposal)
    assert found[("symbol", "font")].value == "Verdana" and found[("symbol", "font")].differs
    assert found[("symbol", "font_size")].value == 9
    assert found[("symbol", "ic_pin_length")].value == 100 and found[("symbol", "ic_pin_length")].differs
    assert found[("symbol", "pin_font")].value == "house"
    assert found[("footprint", "text_font")].value == "truetype"
    assert found[("footprint", "text_font_name")].value == "Verdana"
    assert found[("footprint", "text_height")].value == pytest.approx(0.8)
    assert found[("footprint", "center_cross")].value is True and not found[("footprint", "center_cross")].differs
    assert found[("layers", "assembly")].value == "Mechanical 9" and not found[("layers", "assembly")].differs
    # the proposal is a complete, valid set of settings
    assert proposal.symbol.font == "Verdana" and proposal.symbol.ic_pin_length == 100
    assert proposal.footprint.text_font == "truetype" and proposal.layers == settings.layers
    assert "weichen vom Hausstil ab" in proposal.message


@pytest.mark.rustwriter
def test_learn_from_a_zip_archive(reference: Path, tmp_path: Path):
    archive = tmp_path / "Components.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for file in reference.rglob("*"):
            if file.suffix.lower() in (".schlib", ".pcblib"):
                zf.write(file, f"Components/{file.name}")
        zf.writestr("Components/readme.txt", "no library")
    from_zip = learnstyle.learn([str(archive)], WorkspaceSettings())
    from_folder = learnstyle.learn([str(reference)], WorkspaceSettings())
    assert from_zip.symbols == 1 and from_zip.footprints == 1
    strip = [(f.area, f.key, f.value) for f in from_folder.findings]
    assert [(f.area, f.key, f.value) for f in from_zip.findings] == strip


@pytest.mark.rustwriter
def test_learn_api(client, reference: Path):
    response = client.post("/api/housestyle/learn", json={"paths": [str(reference)]})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"]["font"] == "Verdana" and body["footprint"]["text_font"] == "truetype"
    assert any(f["key"] == "ic_pin_length" and f["differs"] for f in body["findings"])
