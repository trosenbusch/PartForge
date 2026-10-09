"""Windows structured storage (OLE compound files) for PartForge's PcbLib patches.

Altium libraries are compound files. After the Rust writer has produced a PcbLib, PartForge
changes a few of its streams and nothing else – the layer header (:mod:`.stackup`) and the
footprint heights (:mod:`.heights`). Both use :func:`replace_streams`:

1. copy the library beside itself (``<stem>.<tag><hex8><suffix>``, a name
   :func:`partforge.altium.libwriter.is_temp_library_file` never lists),
2. write the new streams into the copy through ole32 (``pythoncom.StgOpenStorageEx`` +
   ``IStorage``/``IStream``, read-modify-write, transacted commit),
3. re-read the **whole** copy: the planned streams must hold exactly the planned bytes and
   every other stream and storage must be byte-identical,
4. run the optional ``verify(copy)`` callback (e.g. the Rust reader lists the same
   components) and only then move the copy over the library (``os.replace``).

Any check failure raises :class:`CompoundError` (German message); COM and OS errors
propagate unchanged. In every failure case the library stays untouched and the copy is
removed. Only existing streams are replaced – the patches never create or delete elements.
"""
from __future__ import annotations

import gc
import logging
import os
import shutil
import traceback
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "CompoundError",
    "open_root",
    "read_all",
    "read_tree",
    "read_tree_file",
    "read_streams",
    "read_child_streams",
    "write_streams",
    "replace_streams",
]

# Windows SDK constants (objbase.h / coml2api.h)
STGM_READ: Final = 0x00000000
STGM_READWRITE: Final = 0x00000002
STGM_SHARE_EXCLUSIVE: Final = 0x00000010
STGM_SHARE_DENY_WRITE: Final = 0x00000020
STGM_TRANSACTED: Final = 0x00010000
STGFMT_STORAGE: Final = 0
STGC_DEFAULT: Final = 0
STGTY_STORAGE: Final = 1
STGTY_STREAM: Final = 2
STREAM_SEEK_SET: Final = 0

_CHUNK: Final = 1 << 20


class CompoundError(Exception):
    """The compound file does not have the expected structure, or a check failed (German)."""


def _pythoncom() -> Any:
    try:
        import pythoncom  # pywin32
    except ImportError as exc:  # pragma: no cover - PartForge runs on Windows with pywin32
        raise CompoundError("pywin32 (pythoncom) ist nicht verfügbar") from exc
    try:
        # pywintypes converts the FILETIMEs of IStorage.EnumElements() through a C-level import of
        # win32timezone that PyInstaller cannot see – importing it here puts it into the program package
        # and turns a missing module into a clear error instead of a failure deep inside COM (PKG-01).
        import win32timezone  # noqa: F401
    except ImportError as exc:  # pragma: no cover - only in an incomplete program package
        raise CompoundError(
            "pywin32-Modul win32timezone fehlt – das Programmpaket ist unvollständig (bitte neu installieren)"
        ) from exc
    return pythoncom


def open_root(path: str | os.PathLike[str], *, write: bool) -> Any:
    """Root ``IStorage`` of a compound file (write: exclusive and transacted)."""
    pythoncom = _pythoncom()
    mode = (STGM_READWRITE | STGM_SHARE_EXCLUSIVE | STGM_TRANSACTED) if write else (STGM_READ | STGM_SHARE_DENY_WRITE)
    return pythoncom.StgOpenStorageEx(os.fspath(path), mode, STGFMT_STORAGE, 0, pythoncom.IID_IStorage)


def read_all(stream: Any) -> bytes:
    """The rest of an ``IStream``."""
    chunks: list[bytes] = []
    while True:
        data = stream.Read(_CHUNK)
        if not data:
            return b"".join(chunks)
        chunks.append(bytes(data))


def read_tree(storage: Any, prefix: str = "") -> dict[str, bytes | None]:
    """Every element below ``storage``: ``path -> bytes`` for streams, ``path/ -> None`` for storages."""
    out: dict[str, bytes | None] = {}
    for stat in storage.EnumElements():
        name, kind = stat[0], stat[1]
        if kind == STGTY_STORAGE:
            child = storage.OpenStorage(name, None, STGM_READ | STGM_SHARE_EXCLUSIVE, None, 0)
            try:
                out[prefix + name + "/"] = None
                out.update(read_tree(child, prefix + name + "/"))
            finally:
                del child
        elif kind == STGTY_STREAM:
            stream = storage.OpenStream(name, None, STGM_READ | STGM_SHARE_EXCLUSIVE, 0)
            try:
                out[prefix + name] = read_all(stream)
            finally:
                del stream
    return out


def read_tree_file(path: str | os.PathLike[str]) -> dict[str, bytes | None]:
    """:func:`read_tree` of a whole file (read-only, others may read at the same time)."""
    root = open_root(path, write=False)
    try:
        return read_tree(root)
    finally:
        del root


def read_streams(path: str | os.PathLike[str], wanted: Iterable[str]) -> dict[str, bytes | None]:
    """Selected streams (``"Library/Data"``); missing ones map to ``None``."""
    root = open_root(path, write=False)
    out: dict[str, bytes | None] = {}
    try:
        for name in wanted:
            parts = name.split("/")
            opened: list[Any] = [root]
            try:
                current = root
                for part in parts[:-1]:
                    current = current.OpenStorage(part, None, STGM_READ | STGM_SHARE_EXCLUSIVE, None, 0)
                    opened.append(current)
                stream = current.OpenStream(parts[-1], None, STGM_READ | STGM_SHARE_EXCLUSIVE, 0)
                try:
                    out[name] = read_all(stream)
                finally:
                    del stream
            except Exception as exc:  # noqa: BLE001 - pywintypes.com_error: element missing
                log.debug("Stream %s in %s nicht lesbar: %s", name, path, exc)
                out[name] = None
            finally:
                del opened[1:]
    finally:
        del root
    return out


def read_child_streams(path: str | os.PathLike[str], name: str) -> dict[str, bytes]:
    """``{"<storage>/<name>": data}`` for every top-level storage that has a stream ``name``
    (e.g. each component's ``Parameters``) – without reading any other stream."""
    root = open_root(path, write=False)
    out: dict[str, bytes] = {}
    try:
        for stat in root.EnumElements():
            if stat[1] != STGTY_STORAGE:
                continue
            storage = root.OpenStorage(stat[0], None, STGM_READ | STGM_SHARE_EXCLUSIVE, None, 0)
            try:
                try:
                    stream = storage.OpenStream(name, None, STGM_READ | STGM_SHARE_EXCLUSIVE, 0)
                except Exception:  # noqa: BLE001 - pywintypes.com_error: this storage has no such stream
                    continue
                try:
                    out[f"{stat[0]}/{name}"] = read_all(stream)
                finally:
                    del stream
            finally:
                del storage
    finally:
        del root
    return out


def _write_stream(storage: Any, name: str, data: bytes) -> None:
    stream = storage.OpenStream(name, None, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, 0)
    try:
        stream.SetSize(len(data))
        stream.Seek(0, STREAM_SEEK_SET)
        written = stream.Write(data)
        if isinstance(written, int) and written != len(data):
            raise CompoundError(f"nur {written} von {len(data)} Bytes geschrieben")
        stream.Commit(STGC_DEFAULT)
    finally:
        del stream


def _write_group(root: Any, folder: tuple[str, ...], items: Mapping[str, bytes]) -> None:
    """Write the streams of one storage path and commit the child storages into their parents."""
    opened: list[Any] = []
    try:
        for part in folder:
            parent = opened[-1] if opened else root
            opened.append(parent.OpenStorage(part, None, STGM_READWRITE | STGM_SHARE_EXCLUSIVE, None, 0))
        target = opened[-1] if opened else root
        for name, data in items.items():
            _write_stream(target, name, data)
        del target
        for storage in reversed(opened):
            storage.Commit(STGC_DEFAULT)
    finally:
        while opened:  # release the innermost storage first
            opened.pop()


def write_streams(path: str | os.PathLike[str], streams: Mapping[str, bytes]) -> None:
    """Replace existing streams of ``path`` (``"Storage/Stream": data``) in one transacted commit.

    Elements are only opened, never created: a missing stream or storage raises the COM
    error, and nothing reaches the file before the final commit of the root storage.
    """
    groups: dict[tuple[str, ...], dict[str, bytes]] = {}
    for name, data in streams.items():
        parts = tuple(name.split("/"))
        if any(not p for p in parts):
            raise CompoundError(f"ungültiger Stream-Name {name!r}")
        groups.setdefault(parts[:-1], {})[parts[-1]] = data
    root = open_root(path, write=True)
    try:
        for folder, items in groups.items():
            _write_group(root, folder, items)
        root.Commit(STGC_DEFAULT)
    finally:
        del root


def replace_streams(
    library: str | os.PathLike[str],
    streams: Mapping[str, bytes],
    *,
    verify: Callable[[Path], None] | None = None,
    tag: str = "pf",
    write: Callable[[Path, Mapping[str, bytes]], None] | None = None,
) -> None:
    """Replace ``streams`` of ``library`` through a checked copy (see the module docstring).

    ``write`` (default :func:`write_streams`) writes the streams into the copy. Raises
    :class:`CompoundError` when the re-read copy differs from the plan, or whatever
    ``verify``/COM/OS raise; the library is then unchanged and the copy is gone.
    """
    target = Path(os.path.abspath(os.fspath(library)))
    if not streams:
        return
    temp = target.with_name(f"{target.stem}.{tag}{uuid.uuid4().hex[:8]}{target.suffix}")
    try:
        shutil.copyfile(target, temp)
        before = read_tree_file(temp)
        missing = sorted(name for name in streams if before.get(name) is None)
        if missing:
            raise CompoundError(f"Stream fehlt: {', '.join(missing[:5])}")
        (write or write_streams)(temp, streams)
        after = read_tree_file(temp)
        expected = dict(before)
        expected.update(streams)
        if after != expected:
            changed = sorted(k for k in set(expected) | set(after) if expected.get(k) != after.get(k))
            raise CompoundError(f"Kopie nach dem Schreiben nicht identisch ({', '.join(changed[:5]) or '?'})")
        if verify is not None:
            verify(temp)
        os.replace(temp, target)
    except BaseException as exc:
        # The traceback keeps the frames of the failed COM calls alive – and with them the storage objects
        # (e.g. an enumerator inside read_tree), which hold the copy open: release them before removing it.
        _release_frames(exc)
        raise
    finally:
        _remove(temp)


def _release_frames(exc: BaseException) -> None:
    """Drop the locals of the finished frames in ``exc``'s traceback (COM objects) and collect them."""
    traceback.clear_frames(exc.__traceback__)
    gc.collect()


def _remove(path: Path) -> None:
    """Delete a temporary copy (retried once after a garbage collection – a COM object may still hold it)."""
    for attempt in range(2):
        try:
            if path.exists():
                path.unlink()
            return
        except OSError as exc:
            if attempt:
                log.warning("Temporäre Kopie %s konnte nicht entfernt werden: %s", path, exc)
                return
            gc.collect()
