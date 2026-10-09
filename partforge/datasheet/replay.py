"""Official replay mode for tests and demos: recorded Claude answers instead of the API – never a network call.

Switched on with ``PARTFORGE_AI_REPLAY_DIR=<folder>`` – **only** together with ``PARTFORGE_HOME`` (isolated test or
demo runs; the user's real program never replays). The folder has the layout of ``tests/data/ai_fixtures``:

* ``<folder>/*.json`` – analysis fixtures (``{"sha256": …, "calls": [...]}``): the analysis of a datasheet replays
  the calls of the fixture whose ``sha256[:16]`` is the datasheet id (= the PDF's content hash);
* ``<folder>/find/*.json`` – datasheet searches (``{"query": …, "manufacturer": …, "calls": [...], "probes": {url:
  …}, "downloads": {url: file}}``), keyed by the normalised query (:func:`search_key`); the PDF check of the found
  links (``probes``) and the import of a found link (``downloads``, a file relative to the fixture) are replayed
  too.

``PARTFORGE_AI_REPLAY_SPEED`` = seconds per streamed chunk (default 0: as fast as possible) – lets UI tests watch an
analysis. A datasheet or query without recording fails with a German message (:class:`~.errors.AiUnavailable`)
before any work; a download of an unknown address is refused. ``/api/ai/status`` reports ``key_source = "replay"``
and ``/api/ai/test`` answers "OK" (cost 0).
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

from .errors import AiUnavailable, DatasheetError

if TYPE_CHECKING:
    from ..config import AppSettings
    from .llm import ReplayLlmClient

log = logging.getLogger(__name__)

__all__ = [
    "DIR_ENV",
    "SPEED_ENV",
    "ReplayFixtures",
    "active",
    "client",
    "download",
    "fixtures",
    "probe",
    "replay_dir",
    "search_key",
    "speed",
    "url_key",
]

DIR_ENV = "PARTFORGE_AI_REPLAY_DIR"
SPEED_ENV = "PARTFORGE_AI_REPLAY_SPEED"
_warned = False


def replay_dir() -> Path | None:
    """The replay folder, or ``None`` when the replay mode is off (also when ``PARTFORGE_HOME`` is not set)."""
    global _warned
    value = (os.environ.get(DIR_ENV) or "").strip()
    if not value:
        return None
    if not (os.environ.get("PARTFORGE_HOME") or "").strip():
        if not _warned:
            _warned = True
            log.warning("%s wird ignoriert: der Wiedergabemodus gilt nur zusammen mit PARTFORGE_HOME.", DIR_ENV)
        return None
    return Path(value)


def active() -> bool:
    return replay_dir() is not None


def speed() -> float:
    """Seconds per streamed chunk (``PARTFORGE_AI_REPLAY_SPEED``, 0 = no delay; at most 10)."""
    try:
        value = float((os.environ.get(SPEED_ENV) or "0").replace(",", "."))
    except ValueError:
        return 0.0
    return min(10.0, max(0.0, value))


def search_key(query: str) -> str:
    """Normalised search query (NFKC, case-folded, single spaces) – the key of search fixtures."""
    text = unicodedata.normalize("NFKC", str(query or ""))
    return " ".join(text.split()).casefold()


def url_key(url: str) -> str:
    """URL for comparisons: scheme/host case-insensitive, without fragment and trailing slash."""
    parsed = urlparse(str(url or "").strip())
    path = unquote(parsed.path or "").rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{(parsed.scheme or '').lower()}://{(parsed.hostname or '').lower()}{path}{query}"


# --------------------------------------------------------------------------- fixtures


@dataclass
class SearchFixture:
    path: Path
    query: str
    manufacturer: str
    calls: list[dict[str, Any]]
    probes: dict[str, dict[str, Any]] = field(default_factory=dict)
    downloads: dict[str, str] = field(default_factory=dict)


@dataclass
class ReplayFixtures:
    root: Path
    datasheets: dict[str, Path] = field(default_factory=dict)  # sha256[:16] -> fixture file
    searches: dict[str, list[SearchFixture]] = field(default_factory=dict)  # search_key -> fixtures

    def analysis_calls(self, datasheet_id: str) -> list[dict[str, Any]] | None:
        path = self.datasheets.get(str(datasheet_id or "").lower())
        if path is None:
            return None
        return list(_read(path).get("calls") or [])

    def search(self, query: str) -> SearchFixture | None:
        """The recording of a query (several for one query: the first file name)."""
        hits = self.searches.get(search_key(query))
        return hits[0] if hits else None

    def probe(self, url: str) -> dict[str, Any] | None:
        key = url_key(url)
        for fixtures in self.searches.values():
            for fixture in fixtures:
                for recorded, result in fixture.probes.items():
                    if url_key(recorded) == key:
                        return dict(result)
        return None

    def download(self, url: str) -> Path | None:
        key = url_key(url)
        for fixtures in self.searches.values():
            for fixture in fixtures:
                for recorded, target in fixture.downloads.items():
                    if url_key(recorded) == key:
                        path = Path(target)
                        return path if path.is_absolute() else (fixture.path.parent / path).resolve()
        return None


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Wiedergabedatei %s nicht lesbar: %s", path, exc)
        return {}
    return data if isinstance(data, dict) else {}


_SHA = re.compile(r"^[0-9a-f]{16,64}$")


def fixtures(root: Path | None = None) -> ReplayFixtures:
    """Index of the recordings in ``root`` (default: the replay folder). Read on every call – the files are small and
    a demo may add recordings while the server runs."""
    folder = root if root is not None else replay_dir()
    if folder is None:
        return ReplayFixtures(root=Path())
    out = ReplayFixtures(root=folder)
    if not folder.is_dir():
        log.warning("Wiedergabeordner %s fehlt", folder)
        return out
    for path in sorted(folder.glob("*.json")):
        sha = str(_read(path).get("sha256") or "").lower()
        if _SHA.match(sha):
            out.datasheets.setdefault(sha[:16], path)
    for path in sorted((folder / "find").glob("*.json")):
        data = _read(path)
        query = str(data.get("query") or "")
        if not query:
            continue
        out.searches.setdefault(search_key(query), []).append(SearchFixture(
            path=path, query=query, manufacturer=str(data.get("manufacturer") or ""),
            calls=list(data.get("calls") or []), probes=dict(data.get("probes") or {}),
            downloads={str(k): str(v) for k, v in dict(data.get("downloads") or {}).items()}))
    return out


# --------------------------------------------------------------------------- clients


def _test_call(settings: AppSettings) -> dict[str, Any]:
    """The answer of ``/api/ai/test`` in the replay mode (no cost)."""
    return {"kind": "test", "request_id": "req_replay", "message": {
        "id": "msg_replay", "type": "message", "role": "assistant", "model": settings.ai.fast_model,
        "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
        "usage": {"input_tokens": 0, "output_tokens": 0}}}


def client(settings: AppSettings, *, datasheet_id: str | None = None, search: str | None = None) -> ReplayLlmClient:
    """Replay client for an analysis (``datasheet_id``), a search (``search`` = query) or anything else (connection
    test, availability checks). Raises :class:`AiUnavailable` (German) when no recording exists."""
    from .llm import ReplayLlmClient

    index = fixtures()
    delay = speed()
    if datasheet_id:
        calls = index.analysis_calls(datasheet_id)
        if calls is None:
            raise AiUnavailable(
                f"Testmodus ({DIR_ENV}): Für dieses Datenblatt (Inhalts-Hash {datasheet_id}) gibt es keine aufgezeichnete "
                f"Analyse in „{index.root}“ – es wird keine echte Claude-Anfrage gestellt.")
        return ReplayLlmClient(calls, delay_s=delay)
    if search is not None:
        fixture = index.search(search)
        if fixture is None:
            raise AiUnavailable(
                f"Testmodus ({DIR_ENV}): Für die Suche „{search}“ gibt es keine Aufzeichnung in „{index.root / 'find'}“ "
                "– es wird keine echte Claude-Anfrage gestellt.")
        return ReplayLlmClient(fixture.calls, delay_s=delay)
    return ReplayLlmClient([_test_call(settings)], delay_s=0.0)


def probe(url: str) -> dict[str, Any] | None:
    """Recorded result of the PDF check of ``url`` (``None`` = not recorded)."""
    return fixtures().probe(url)


def download(url: str) -> tuple[bytes, str, str]:
    """``(bytes, file name, URL)`` of a found link in the replay mode – from the file the search fixture names; any
    other address is refused (no network in the replay mode)."""
    path = fixtures().download(url)
    if path is None:
        raise DatasheetError(f"Testmodus ({DIR_ENV}): Für „{url}“ ist keine Datei hinterlegt – im Testmodus wird "
                             "nichts heruntergeladen.")
    if not path.is_file():
        raise DatasheetError(f"Testmodus ({DIR_ENV}): Die hinterlegte Datei „{path}“ fehlt.")
    name = Path(unquote(urlparse(url).path or "")).name or path.name
    if not name.lower().endswith(".pdf"):
        name = f"{name or 'Datenblatt'}.pdf"
    return path.read_bytes(), name, url
