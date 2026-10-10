"""Native helpers exposed to the web UI inside the pywebview window (``window.pywebview.api``).

The frontend (``frontend/src/lib/native.ts``) expects::

    pick_folder(initial: str | None) -> str | None
    pick_file(initial: str | None, filters: list[str] | None) -> str | None
    open_path(path: str) -> None
    reveal_path(path: str) -> None
    save_file(suggested_name: str, content: str, filters: list[str] | None) -> str | None

``open_path`` never executes programs: folders open in Explorer, known document types
open with their associated application (SchLib/PcbLib/DbLib in Altium), anything else is
revealed in Explorer. ``reveal_path`` always shows the file selected in Explorer.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path, PurePath

log = logging.getLogger("partforge.desktop")

# File types PartForge may hand to the associated application.
OPENABLE_SUFFIXES = {
    ".pdf", ".schlib", ".pcblib", ".dblib", ".intlib", ".libpkg", ".step", ".stp",
    ".xlsx", ".xls", ".csv", ".ods", ".png", ".jpg", ".jpeg", ".svg", ".txt", ".md", ".log", ".json",
}

ALL_FILES = "Alle Dateien (*.*)"
_FILTER_RE = re.compile(r"^\s*(?P<label>[^()]*?)\s*\((?P<patterns>[^()]*)\)\s*$")
_PATTERN_RE = re.compile(r"\*(?:\.(?:\w+|\*))*")


def file_types(filters: Sequence[str] | None) -> tuple[str, ...]:
    """File filters of the web UI as pywebview accepts them, plus :data:`ALL_FILES` (last, once).

    pywebview rejects a whole dialog for one filter it does not like (``ValueError``: the description may only hold
    letters, digits, ``_`` and blanks, the patterns must look like ``*.ext``) – the button then seems dead. So other
    characters in the description become blanks ("Altium-Bibliotheken" -> "Altium Bibliotheken"), a file name
    pattern becomes its extension ("X2.EXE" -> "*.EXE") and a filter that stays unusable is left out (logged)."""
    out: list[str] = []
    for raw in filters or ():
        found = _FILTER_RE.match(str(raw))
        if found is None:
            log.warning("Dateifilter ignoriert (Form „Beschreibung (*.ext)“ erwartet): %r", raw)
            continue
        label = re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", found["label"])).strip() or "Dateien"
        patterns: list[str] = []
        for part in found["patterns"].split(";"):
            part = part.strip()
            if part and not part.startswith("*"):
                part = f"*{PurePath(part).suffix}" if PurePath(part).suffix else ""
            if part and _PATTERN_RE.fullmatch(part) and part not in patterns:
                patterns.append(part)
        if not patterns:
            log.warning("Dateifilter ohne gültiges Muster ignoriert: %r", raw)
            continue
        entry = f"{label} ({';'.join(patterns)})"
        if entry not in out:
            out.append(entry)
    if ALL_FILES in out:
        out.remove(ALL_FILES)
    out.append(ALL_FILES)
    return tuple(out)


class DesktopApi:
    """Methods are called by pywebview from a worker thread; keep them small and defensive."""

    def _window(self):
        import webview

        return webview.windows[0] if webview.windows else None

    def pick_folder(self, initial: str | None = None) -> str | None:
        import webview

        window = self._window()
        if window is None:
            return None
        directory = initial if initial and Path(initial).is_dir() else ""
        try:
            result = window.create_file_dialog(webview.FileDialog.FOLDER, directory=directory)
        except Exception:
            log.exception("Ordnerdialog fehlgeschlagen")
            raise
        return str(result[0]) if result else None

    def pick_file(self, initial: str | None = None, filters: list[str] | None = None) -> str | None:
        import webview

        window = self._window()
        if window is None:
            return None
        directory = ""
        if initial:
            p = Path(initial)
            directory = str(p if p.is_dir() else p.parent) if (p.is_dir() or p.parent.is_dir()) else ""
        try:
            result = window.create_file_dialog(webview.FileDialog.OPEN, directory=directory,
                                               file_types=file_types(filters))
        except Exception:
            log.exception("Dateidialog fehlgeschlagen")
            raise
        return str(result[0]) if result else None

    def save_file(self, suggested_name: str, content: str, filters: list[str] | None = None) -> str | None:
        """Ask for a target file and write ``content`` there; returns the path or None (cancelled).

        ``content`` is text (UTF-8) or binary data as ``"base64:<data>"`` (e.g. XLSX exports)."""
        import base64

        import webview

        window = self._window()
        if window is None:
            return None
        name = Path(str(suggested_name or "PartForge-Export")).name
        try:
            result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name,
                                               file_types=file_types(filters))
        except Exception:
            log.exception("Speichern-Dialog fehlgeschlagen")
            raise
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        data = base64.b64decode(content[7:]) if content.startswith("base64:") else content.encode("utf-8")
        tmp = target.with_name(target.name + ".partforge-tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        log.info("Gespeichert: %s (%d Bytes)", target, len(data))
        return str(target)

    def open_path(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {path}")
        if p.is_dir():
            os.startfile(str(p))  # noqa: S606 - opens Explorer
        elif p.suffix.lower() in OPENABLE_SUFFIXES:
            os.startfile(str(p))  # noqa: S606 - associated document viewer, never an executable
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607 - reveal only
        log.info("Geöffnet: %s", p)

    def reveal_path(self, path: str) -> None:
        """Show ``path`` in Explorer (file selected, folder opened) without opening the file itself."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {path}")
        if p.is_dir():
            os.startfile(str(p))  # noqa: S606 - opens Explorer
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607 - reveal only
        log.info("Im Explorer gezeigt: %s", p)
