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

from .config import load_settings

log = logging.getLogger("partforge.desktop")

# File types PartForge may hand to the associated application.
OPENABLE_SUFFIXES = {
    ".pdf", ".schlib", ".pcblib", ".dblib", ".intlib", ".libpkg", ".step", ".stp",
    ".xlsx", ".xls", ".csv", ".ods", ".png", ".jpg", ".jpeg", ".svg", ".txt", ".md", ".log", ".json",
}

ALL_FILES = "All files (*.*)"
_FILTER_RE = re.compile(r"^\s*(?P<label>[^()]*?)\s*\((?P<patterns>[^()]*)\)\s*$")
_PATTERN_RE = re.compile(r"\*(?:\.(?:\w+|\*))*")


def native_text(english: str, german: str, *, language: str | None = None) -> str:
    """Translate native UI at use time, including changes saved while the window is open."""
    return german if (language or load_settings().language) == "de" else english


def webview_localization(language: str | None = None) -> dict[str, str]:
    """Labels controlled by pywebview; operating-system dialog chrome stays native."""
    language = language or load_settings().language
    labels = {
        "global.quitConfirmation": ("Do you really want to quit?", "Möchten Sie wirklich beenden?"),
        "global.ok": ("OK", "OK"),
        "global.quit": ("Quit", "Beenden"),
        "global.cancel": ("Cancel", "Abbrechen"),
        "global.saveFile": ("Save file", "Datei speichern"),
        "cocoa.menu.about": ("About", "Über"),
        "cocoa.menu.services": ("Services", "Dienste"),
        "cocoa.menu.view": ("View", "Ansicht"),
        "cocoa.menu.edit": ("Edit", "Bearbeiten"),
        "cocoa.menu.hide": ("Hide", "Ausblenden"),
        "cocoa.menu.hideOthers": ("Hide Others", "Andere ausblenden"),
        "cocoa.menu.showAll": ("Show All", "Alle einblenden"),
        "cocoa.menu.quit": ("Quit", "Beenden"),
        "cocoa.menu.fullscreen": ("Enter Fullscreen", "Vollbild"),
        "cocoa.menu.cut": ("Cut", "Ausschneiden"),
        "cocoa.menu.copy": ("Copy", "Kopieren"),
        "cocoa.menu.paste": ("Paste", "Einfügen"),
        "cocoa.menu.selectAll": ("Select All", "Alles auswählen"),
        "windows.fileFilter.allFiles": ("All files", "Alle Dateien"),
        "windows.fileFilter.otherFiles": ("Other file types", "Andere Dateitypen"),
        "linux.openFile": ("Open file", "Datei öffnen"),
        "linux.openFiles": ("Open files", "Dateien öffnen"),
        "linux.openFolder": ("Open folder", "Ordner öffnen"),
    }
    return {key: native_text(*texts, language=language) for key, texts in labels.items()}


def file_types(filters: Sequence[str] | None, *, language: str | None = None) -> tuple[str, ...]:
    """File filters of the web UI as pywebview accepts them, plus :data:`ALL_FILES` (last, once).

    pywebview rejects a whole dialog for one filter it does not like (``ValueError``: the description may only hold
    letters, digits, ``_`` and blanks, the patterns must look like ``*.ext``) – the button then seems dead. So other
    characters in the description become blanks ("Altium-Bibliotheken" -> "Altium Bibliotheken"), a file name
    pattern becomes its extension ("X2.EXE" -> "*.EXE") and a filter that stays unusable is left out (logged)."""
    language = language or load_settings().language
    all_files = native_text(ALL_FILES, "Alle Dateien (*.*)", language=language)
    out: list[str] = []
    for raw in filters or ():
        found = _FILTER_RE.match(str(raw))
        if found is None:
            log.warning(native_text('Ignoring file filter (expected "Description (*.ext)"): %r',
                                    "Dateifilter ignoriert (Form „Beschreibung (*.ext)“ erwartet): %r",
                                    language=language), raw)
            continue
        label = re.sub(r"\s+", " ", re.sub(r"[^\w ]+", " ", found["label"])).strip() or native_text(
            "Files", "Dateien", language=language)
        patterns: list[str] = []
        for part in found["patterns"].split(";"):
            part = part.strip()
            if part and not part.startswith("*"):
                part = f"*{PurePath(part).suffix}" if PurePath(part).suffix else ""
            if part and _PATTERN_RE.fullmatch(part) and part not in patterns:
                patterns.append(part)
        if not patterns:
            log.warning(native_text("Ignoring file filter without a valid pattern: %r",
                                    "Dateifilter ohne gültiges Muster ignoriert: %r", language=language), raw)
            continue
        if label in {"All files", "Alle Dateien"} and patterns == ["*.*"]:
            continue
        entry = f"{label} ({';'.join(patterns)})"
        if entry not in out:
            out.append(entry)
    out.append(all_files)
    return tuple(out)


class DesktopApi:
    """Methods are called by pywebview from a worker thread; keep them small and defensive."""

    def _window(self):
        import webview

        window = webview.windows[0] if webview.windows else None
        if window is not None:
            # The GUI backend shares this dictionary with the window. Update it in place
            # before each native interaction so saved language changes take effect.
            window.localization.update(webview_localization())
        return window

    def pick_folder(self, initial: str | None = None) -> str | None:
        import webview

        window = self._window()
        if window is None:
            return None
        directory = initial if initial and Path(initial).is_dir() else ""
        try:
            result = window.create_file_dialog(webview.FileDialog.FOLDER, directory=directory)
        except Exception:
            log.exception(native_text("Folder dialog failed", "Ordnerdialog fehlgeschlagen"))
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
            log.exception(native_text("File dialog failed", "Dateidialog fehlgeschlagen"))
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
            log.exception(native_text("Save dialog failed", "Speichern-Dialog fehlgeschlagen"))
            raise
        if not result:
            return None
        target = Path(result if isinstance(result, str) else result[0])
        data = base64.b64decode(content[7:]) if content.startswith("base64:") else content.encode("utf-8")
        tmp = target.with_name(target.name + ".partforge-tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        log.info(native_text("Saved: %s (%d bytes)", "Gespeichert: %s (%d Bytes)"), target, len(data))
        return str(target)

    def open_path(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(native_text("Path not found: {path}", "Pfad nicht gefunden: {path}").format(path=path))
        if p.is_dir():
            os.startfile(str(p))  # noqa: S606 - opens Explorer
        elif p.suffix.lower() in OPENABLE_SUFFIXES:
            os.startfile(str(p))  # noqa: S606 - associated document viewer, never an executable
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607 - reveal only
        log.info(native_text("Opened: %s", "Geöffnet: %s"), p)

    def reveal_path(self, path: str) -> None:
        """Show ``path`` in Explorer (file selected, folder opened) without opening the file itself."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(native_text("Path not found: {path}", "Pfad nicht gefunden: {path}").format(path=path))
        if p.is_dir():
            os.startfile(str(p))  # noqa: S606 - opens Explorer
        else:
            subprocess.Popen(["explorer", "/select,", str(p)])  # noqa: S603,S607 - reveal only
        log.info(native_text("Revealed in Explorer: %s", "Im Explorer gezeigt: %s"), p)
