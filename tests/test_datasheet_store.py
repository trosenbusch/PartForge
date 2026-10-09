"""Datasheet import: content-addressed storage, metadata, text-layer analysis, page renders, URL download, deletion."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import httpx
import pytest

from partforge.config import app_data_dir
from partforge.datasheet import store
from partforge.datasheet.errors import DatasheetError, DatasheetNotFound, InvalidPdf
from partforge.datasheet.models import META_FORMAT, DatasheetMeta
from partforge.db import parts, registry
from partforge.db.models import DatasheetRecord
from partforge.workspace import Workspace

PDFS = Path(__file__).parent / "data" / "corpus" / "pdfs"
pytestmark = pytest.mark.skipif(not PDFS.is_dir(), reason="Datenblatt-Korpus fehlt")


def _pdf(name: str = "ADG736.pdf") -> bytes:
    return (PDFS / name).read_bytes()


def _blank_pdf(pages: int = 1) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- ingest


def test_ingest_is_content_addressed_and_deduplicated(workspace: Workspace):
    data = _pdf()
    sha = hashlib.sha256(data).hexdigest()
    rec, duplicate = store.ingest_bytes(data, r"C:\Downloads\ADG736 Datenblatt (Rev D).pdf", ws=workspace)
    assert not duplicate
    assert rec.id == sha[:16]
    assert rec.file == rf"Datasheets\ADG736_Datenblatt_(Rev_D)_{sha[:8]}.pdf"
    assert rec.original_name == "ADG736 Datenblatt (Rev D).pdf"
    assert rec.page_count == 12
    path = workspace.abs(rec.file)
    assert path is not None and path.read_bytes() == data
    meta = store.load_meta(rec)
    assert meta.format == META_FORMAT and meta.size_bytes == len(data) and not meta.pages
    again, duplicate = store.ingest_bytes(data, "andere.pdf", ws=workspace)
    assert duplicate and again.id == rec.id and again.original_name == rec.original_name
    assert len(list(workspace.datasheets_dir.glob("*.pdf"))) == 1


def test_ingest_restores_a_missing_file_and_keeps_the_source_url(workspace: Workspace):
    data = _pdf()
    rec, _ = store.ingest_bytes(data, "ADG736.pdf", ws=workspace)
    path = workspace.abs(rec.file)
    assert path is not None
    path.unlink()
    again, duplicate = store.ingest_bytes(data, "ADG736.pdf", source_url="https://www.analog.com/x.pdf", ws=workspace)
    assert duplicate
    restored = workspace.abs(again.file)
    assert restored is not None and restored.is_file()
    assert store.load_meta(again).source_url == "https://www.analog.com/x.pdf"


def test_ingest_ascii_names_and_name_collisions(workspace: Workspace):
    rec, _ = store.ingest_bytes(_blank_pdf(1), "Datenblatt µΩ Schaltregler|neu.pdf", ws=workspace)
    assert Path(rec.file.replace("\\", "/")).name.startswith("Datenblatt_uOhm_Schaltregler-neu_")
    other = _blank_pdf(2)
    sha = hashlib.sha256(other).hexdigest()
    clash = workspace.datasheets_dir / f"Kollision_{sha[:8]}.pdf"
    clash.write_bytes(b"%PDF-1.4 something else")
    rec2, _ = store.ingest_bytes(other, "Kollision.pdf", ws=workspace)
    assert rec2.file.endswith(f"Kollision_{sha[:8]}_{sha[8:16]}.pdf")
    assert clash.read_bytes() == b"%PDF-1.4 something else"


@pytest.mark.parametrize(("data", "message"), [
    (b"", "leer"),
    (b"GIF89a....", "kein PDF"),
    (b"%PDF-1.4 kaputt", "kein lesbares PDF"),
])
def test_ingest_rejects_invalid_files(workspace: Workspace, data, message):
    with pytest.raises(InvalidPdf, match=message):
        store.ingest_bytes(data, "x.pdf", ws=workspace)
    assert not registry.list_datasheets()


def test_ingest_size_limit(workspace: Workspace, monkeypatch):
    monkeypatch.setattr(store, "MAX_PDF_BYTES", 100)
    with pytest.raises(InvalidPdf, match="zu groß"):
        store.ingest_bytes(_blank_pdf(1), "gross.pdf", ws=workspace)


def test_unknown_and_malformed_ids(workspace: Workspace):
    with pytest.raises(DatasheetNotFound):
        store.get_record("0123456789abcdef")
    with pytest.raises(DatasheetNotFound):
        store.get_record("../../etc/passwd")
    with pytest.raises(DatasheetNotFound):
        store.cache_dir("..\\x")


def test_missing_pdf_file_is_reported(workspace: Workspace):
    rec, _ = store.ingest_bytes(_blank_pdf(), "weg.pdf", ws=workspace)
    path = workspace.abs(rec.file)
    assert path is not None
    path.unlink()
    with pytest.raises(DatasheetError, match="fehlt"):
        store.pdf_path(rec, workspace)


def test_damaged_metadata_starts_fresh(workspace: Workspace):
    rec = registry.upsert_datasheet(DatasheetRecord(id="00000000000000aa", file="x.pdf", original_name="x.pdf",
                                                    extraction={"format": META_FORMAT, "pages": "kaputt"}))
    assert store.load_meta(rec) == DatasheetMeta()
    foreign = rec.model_copy(update={"extraction": {"something": "else"}})
    assert store.load_meta(foreign) == DatasheetMeta()


# --------------------------------------------------------------------------- analysis


def test_analyze_stores_page_quality(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf("opa656.pdf"), "opa656.pdf", ws=workspace)
    calls: list[int] = []
    rec, texts = store.analyze(rec, ws=workspace, force=True, progress=lambda i, n: calls.append(i))
    assert len(texts) == 25 and calls[:3] == [0, 1, 2]
    meta = store.load_meta(rec)
    assert meta.analyzed and len(meta.pages) == 25
    assert [p.page for p in meta.pages if p.quality == "empty"] == [21, 22, 23, 24]
    assert rec.text_pages == [p for p in range(1, 26) if p not in (21, 22, 23, 24)]
    assert meta.pages[0].width_pt == 612.0 and meta.pages[0].height_pt == 792.0
    stored = registry.get_datasheet(rec.id)
    assert stored is not None and stored.text_pages == rec.text_pages
    # a second analysis keeps the stored result (no forced update)
    rec2, _ = store.analyze(rec, ws=workspace)
    assert store.load_meta(rec2).analyzed == meta.analyzed


def test_text_layer_is_cached_by_content_hash(workspace: Workspace, monkeypatch):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    rec, first = store.analyze(rec, ws=workspace, force=True)
    cache = store.cache_dir(rec.id) / "text-v1.json"
    assert cache.is_file()

    def no_reading(*args, **kwargs):
        raise AssertionError("PDF must not be read again")

    monkeypatch.setattr(store.pdfio, "read_page_texts", no_reading)
    _rec, second = store.analyze(rec, ws=workspace)
    assert second == first
    cache.write_text("{kaputt", encoding="utf-8")  # a damaged cache is ignored
    monkeypatch.undo()
    _rec, third = store.analyze(rec, ws=workspace)
    assert third == first and cache.read_text(encoding="utf-8").startswith("{")


def test_analyze_encrypted_and_glyph_pdf(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf("25AA02E48.pdf"), "25AA02E48.pdf", ws=workspace)
    rec, _ = store.analyze(rec, ws=workspace)
    meta = store.load_meta(rec)
    assert meta.encrypted
    assert [p.page for p in meta.pages if p.quality == "glyph"] == [16, 17, 18]
    assert 16 not in rec.text_pages


# --------------------------------------------------------------------------- renders


def test_page_png_is_cached_in_app_data(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    path = store.page_png(rec, 1, 50, ws=workspace)
    assert path.is_file() and path.read_bytes().startswith(b"\x89PNG")
    assert app_data_dir() in path.parents and rec.id in str(path)
    assert path.name == "p001_50.png"
    mtime = path.stat().st_mtime_ns
    assert store.page_png(rec, 1, 50, ws=workspace).stat().st_mtime_ns == mtime  # cache hit
    assert store.page_png(rec, 1, 5, ws=workspace).name == "p001_36.png"  # clamped
    assert store.page_png(rec, 1, 1000, ws=workspace).name == "p001_300.png"
    assert store.page_png(rec, 2, None, ws=workspace).name == "p002_110.png"
    with pytest.raises(DatasheetError, match="Seite 13"):
        store.page_png(rec, 13, ws=workspace)
    with pytest.raises(DatasheetError, match="Seite 0"):
        store.page_png(rec, 0, ws=workspace)


def test_parallel_requests_for_the_same_page_render_it_once(workspace: Workspace, monkeypatch):
    """Reviewer case h8: parallel page images of one uncached page (thread pool of the API)."""
    import shutil
    import threading

    from partforge.datasheet import pdf as pdfio

    rec, _ = store.ingest_bytes(_pdf("LTC6244.pdf"), "LTC6244.pdf", ws=workspace)
    renders: list[int] = []
    original = pdfio.render_page

    def counting(*args, **kwargs):
        renders.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pdfio, "render_page", counting)
    for _round in range(5):
        shutil.rmtree(store.cache_dir(rec.id), ignore_errors=True)
        renders.clear()
        errors: list[str] = []
        paths: list[Path] = []
        start = threading.Barrier(6)

        def work() -> None:
            start.wait()
            try:
                paths.append(store.page_png(rec, 3, 60, ws=workspace))
            except Exception as exc:  # noqa: BLE001 - collected for the assertion
                errors.append(f"{type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=work) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == [] and len(set(paths)) == 1 and len(renders) == 1
        assert paths[0].read_bytes().startswith(b"\x89PNG")
        assert not list(store.cache_dir(rec.id).glob("*.tmp"))


def test_atomic_write_while_the_target_is_being_read(workspace: Workspace, monkeypatch):
    monkeypatch.setattr(store, "_REPLACE_DELAY_S", 0.001)
    target = store.cache_dir("0123456789abcdef") / "p001_110.png"
    store._write_atomic(target, b"first")  # noqa: SLF001 - unit under test
    with target.open("rb"):  # Windows: a reader blocks the rename -> the existing (same) content stays
        store._write_atomic(target, b"second")  # noqa: SLF001
    assert target.read_bytes() in (b"first", b"second")
    assert not list(target.parent.glob("*.tmp"))
    store._write_atomic(target, b"third")  # noqa: SLF001
    assert target.read_bytes() == b"third"


@pytest.mark.parametrize("error", [AssertionError, AttributeError, NotImplementedError, IndexError, ZeroDivisionError])
def test_parser_crashes_of_damaged_files_become_invalid_pdf(workspace: Workspace, monkeypatch, error):
    """Reviewer case h13: pypdf raises arbitrary exceptions for damaged files – never HTTP 500."""
    import pypdf

    def broken(*args, **kwargs):
        raise error("kaputt")

    monkeypatch.setattr(pypdf, "PdfReader", broken)
    with pytest.raises(InvalidPdf, match=f"kein lesbares PDF \\({error.__name__}\\)"):
        store.ingest_bytes(_pdf(), "kaputt.pdf", ws=workspace)


def test_prune_cache_removes_oldest_files(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    first = store.page_png(rec, 1, 40, ws=workspace)
    second = store.page_png(rec, 2, 40, ws=workspace)
    import os

    os.utime(first, (1, 1))
    removed = store.prune_cache(limit_bytes=second.stat().st_size)
    assert removed >= 1 and not first.exists() and second.exists()
    assert store.prune_cache() == 0


def test_the_render_cache_is_never_in_the_roaming_profile(monkeypatch, tmp_path: Path):
    """PKG-09: page renders and text layers live in %LOCALAPPDATA%\\PartForge\\Cache\\datasheets; the render cache of
    older versions in the roaming folder is removed once (nothing else there); isolated runs stay in PARTFORGE_HOME."""
    import time

    roaming, local = tmp_path / "Roaming" / "PartForge", tmp_path / "Local" / "PartForge" / "Cache"
    old = roaming / "cache" / "datasheets" / "0123456789abcdef"
    old.mkdir(parents=True)
    (old / "p001_110.png").write_bytes(b"x" * 100)
    (roaming / "settings.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("PARTFORGE_HOME")
    monkeypatch.setattr(store, "app_data_dir", lambda: roaming)  # never the real profile in a test
    monkeypatch.setattr(store, "user_cache_dir", lambda *args, **kwargs: str(local))
    assert store.cache_root() == local / "datasheets"
    assert store.cache_dir("0123456789abcdef") == local / "datasheets" / "0123456789abcdef"
    deadline = time.time() + 10
    while (roaming / "cache").exists() and time.time() < deadline:
        time.sleep(0.02)
    assert not (roaming / "cache").exists() and (roaming / "settings.json").is_file()
    monkeypatch.setenv("PARTFORGE_HOME", str(tmp_path / "home"))
    assert store.cache_root() == tmp_path / "home" / "cache" / "datasheets"


# --------------------------------------------------------------------------- URL import


def _transport(handler):
    return httpx.MockTransport(handler)


def test_download_pdf_follows_redirects_and_uses_the_file_name():
    data = _blank_pdf()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ds":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/files/lm358%20rev.pdf"})
        assert request.headers["user-agent"].startswith("Mozilla/5.0")
        return httpx.Response(200, content=data, headers={"content-type": "application/pdf"})

    body, name, final = store.download_pdf("https://www.example.com/ds", transport=_transport(handler))
    assert body == data and name == "lm358 rev.pdf" and final == "https://cdn.example.com/files/lm358%20rev.pdf"


def test_download_pdf_content_disposition_name():
    data = _blank_pdf()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data, headers={
            "content-type": "application/octet-stream",
            "content-disposition": "attachment; filename*=UTF-8''Datenbl%C3%A4tt.pdf"})

    _body, name, _final = store.download_pdf("http://example.com/get?id=7", transport=_transport(handler))
    assert name == "Datenblätt.pdf"

    def plain(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=data, headers={"content-disposition": 'inline; filename="ti-opa656"'})

    assert store.download_pdf("http://example.com/x", transport=_transport(plain))[1] == "ti-opa656.pdf"


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(404, text="weg"), "HTTP 404"),
    (httpx.Response(200, text="<html></html>", headers={"content-type": "text/html; charset=utf-8"}), "Webseite"),
    (httpx.Response(200, content=b"{}", headers={"content-type": "application/json"}), "keinen PDF-Inhalt"),
    (httpx.Response(200, content=b"GIF89a", headers={"content-type": "application/pdf"}), "kein PDF"),
    (httpx.Response(200, content=b"%PDF-" + b"0" * 20, headers={"content-length": "999999999"}), "zu groß"),
])
def test_download_pdf_errors(response, message):
    with pytest.raises(DatasheetError, match=message):
        store.download_pdf("https://example.com/a.pdf", transport=_transport(lambda request: response))


def test_download_pdf_streaming_size_limit_and_network_errors():
    big = b"%PDF-1.4" + b"0" * 5000

    def streaming(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=big, headers={"content-type": "application/pdf"})

    with pytest.raises(DatasheetError, match="zu groß"):
        store.download_pdf("https://example.com/a.pdf", max_bytes=1000, transport=_transport(streaming))

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("langsam", request=request)

    with pytest.raises(DatasheetError, match="Zeitüberschreitung"):
        store.download_pdf("https://example.com/a.pdf", transport=_transport(timeout))

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Netz", request=request)

    with pytest.raises(DatasheetError, match="Download fehlgeschlagen"):
        store.download_pdf("https://example.com/a.pdf", transport=_transport(broken))


@pytest.mark.parametrize("url", ["", "ftp://example.com/a.pdf", "file:///C:/x.pdf", "example.com/a.pdf", "https://"])
def test_download_pdf_requires_http_urls(url):
    with pytest.raises(DatasheetError, match="Web-Adresse"):
        store.download_pdf(url)


# --------------------------------------------------------------------------- delete


def test_delete_removes_record_file_and_cache(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    png = store.page_png(rec, 1, 40, ws=workspace)
    path = workspace.abs(rec.file)
    result = store.delete_datasheet(rec.id, ws=workspace)
    assert result == {"id": rec.id, "file_deleted": True, "message": None}
    assert registry.get_datasheet(rec.id) is None
    assert path is not None and not path.exists()
    assert not png.exists()


def test_delete_keeps_a_linked_pdf(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    path = workspace.abs(rec.file)
    assert path is not None
    parts.create_part("Integrated Circuits", {
        "Part Number": "ADG736BRMZ", "Manufacturer": "Analog Devices", "Description": "Switch",
        "Function": "Schalter/Multiplexer", "Library Ref": "X", "Footprint Ref": "Y",
        "ComponentLink1URL": str(path)}, allow_incomplete=True)
    result = store.delete_datasheet(rec.id, ws=workspace)
    assert not result["file_deleted"] and "1 Bauteil" in result["message"]
    assert path.is_file() and registry.get_datasheet(rec.id) is None


def test_delete_keep_file_option_and_unknown_id(workspace: Workspace):
    rec, _ = store.ingest_bytes(_pdf(), "ADG736.pdf", ws=workspace)
    result = store.delete_datasheet(rec.id, delete_file=False, ws=workspace)
    assert not result["file_deleted"]
    path = workspace.abs(rec.file)
    assert path is not None and path.is_file()
    with pytest.raises(DatasheetNotFound):
        store.delete_datasheet(rec.id, ws=workspace)
