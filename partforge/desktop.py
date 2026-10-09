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
import subprocess
from pathlib import Path

log = logging.getLogger("partforge.desktop")

# File types PartForge may hand to the associated application.
OPENABLE_SUFFIXES = {
    ".pdf", ".schlib", ".pcblib", ".dblib", ".intlib", ".libpkg", ".step", ".stp",
    ".xlsx", ".xls", ".csv", ".ods", ".png", ".jpg", ".jpeg", ".svg", ".txt", ".md", ".log", ".json",
}


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
        result = window.create_file_dialog(webview.FileDialog.FOLDER, directory=directory)
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
        file_types = tuple(filters or ()) + ("Alle Dateien (*.*)",)
        result = window.create_file_dialog(webview.FileDialog.OPEN, directory=directory, file_types=file_types)
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
        file_types = tuple(filters or ()) + ("Alle Dateien (*.*)",)
        result = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=name, file_types=file_types)
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
