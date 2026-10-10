"""Keep untouched components byte-identical when the Rust writer rewrites a library.

Every mutation of ``altium-designer-mcp.exe`` re-serialises **all** components of the file from its own
model (VERIFIED 2026-10-09 with the user's reference library): in a PcbLib saved by Altium the untouched
footprints lose Mechanical 17–32 (moved to Mechanical 16), their ``WideStrings`` (TrueType texts) and the
embedded TrueType fonts (``Library/EmbeddedFonts``); in a SchLib the untouched symbols lose
``PinTextData`` (custom pin fonts) and their designator font. PartForge therefore snapshots the working copy
before a write (:func:`snapshot`) and afterwards sets every stream of the components the call did **not**
write back to its old bytes (:func:`restore_plan`) – plus the library streams that belong to them
(``Library/EmbeddedFonts``, ``Library/PadViaLibrary/Data`` of a PcbLib, ``Storage`` (images) of a SchLib).

A footprint is only restored when every 3D model its bodies reference that was embedded before is still
embedded in the rewritten file (linked models are no concern); otherwise the writer's version stays and the
caller reports it.
"""
from __future__ import annotations

import logging
import os
import re
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Final, Literal

from . import compound
from . import pcbrecords as R
from . import schrecords as S

log = logging.getLogger(__name__)

__all__ = ["snapshot", "component_storages", "restore_plan", "LIBRARY_STREAMS"]

Tree = Mapping[str, bytes | None]
#: Library-level streams that hold data of the components (restored when they were not empty before).
LIBRARY_STREAMS: Final[dict[str, tuple[str, ...]]] = {
    "pcblib": ("Library/EmbeddedFonts", "Library/PadViaLibrary/Data"),
    "schlib": ("Storage",),
}
_SKIP_STORAGES: Final = frozenset({"library", "fileversioninfo"})
_MODEL_ID_RE: Final = re.compile(r"MODELID=(\{[0-9A-Fa-f-]{36}\})")


def snapshot(path: str | os.PathLike[str]) -> dict[str, bytes | None] | None:
    """Every element of a library file (``None`` if it does not exist or cannot be read)."""
    if not Path(path).is_file():
        return None
    try:
        return compound.read_tree_file(path)
    except Exception as exc:  # noqa: BLE001 - COM errors: nothing to preserve
        log.debug("Bibliothek %s nicht als Ganzes lesbar: %s", path, exc)
        return None


def component_storages(tree: Tree, kind: Literal["schlib", "pcblib"]) -> dict[str, str]:
    """``{storage: casefolded component name}`` of the components in a tree."""
    out: dict[str, str] = {}
    for key, data in tree.items():
        if data is None or not key.endswith("/Data") or key.count("/") != 1:
            continue
        storage = key.split("/", 1)[0]
        if storage.casefold() in _SKIP_STORAGES or storage.casefold() in R.NON_FOOTPRINT_STORAGES:
            continue
        name: str | None = None
        if kind == "pcblib":
            try:
                name = R.parse_footprint(data).name
            except R.PcbRecordError:
                name = None
        else:
            try:
                head = next((r for r in S.parse_records(data) if not r.binary and r.get("RECORD") == "1"), None)
            except S.SchRecordError:
                head = None
            name = head.get("LibReference") if head is not None else None
        if name:
            out[storage] = name.casefold()
    return out


def _model_ids(tree: Tree, storage: str) -> set[str]:
    data = tree.get(f"{storage}/Data")
    if not data:
        return set()
    try:
        records = R.parse_footprint(data)
    except R.PcbRecordError:
        return set()
    ids: set[str] = set()
    for body in records.of_kind("body"):
        ids.update(m.upper() for m in _MODEL_ID_RE.findall(body.property_text()))
    return ids


def _models_in(tree: Tree) -> set[str]:
    """Ids of the embedded 3D models of a PcbLib tree (``Library/Models/Data``)."""
    data = tree.get("Library/Models/Data")
    if not data:
        return set()
    return {m.decode("ascii").upper() for m in re.findall(rb"ID=(\{[0-9A-Fa-f-]{36}\})", bytes(data))}


def restore_plan(
    before: Tree,
    after: Tree,
    written: Collection[str],
    kind: Literal["schlib", "pcblib"],
) -> tuple[dict[str, bytes], list[str]]:
    """Streams that set the components not in ``written`` back to ``before`` (+ library streams), and the
    storages of components that could not be restored (an embedded 3D model is missing). Pure function."""
    wanted = {n.casefold() for n in written}
    old = component_storages(before, kind)
    new = component_storages(after, kind)
    models_before = _models_in(before) if kind == "pcblib" else set()
    models = _models_in(after) if kind == "pcblib" else set()
    streams: dict[str, bytes] = {}
    skipped: list[str] = []
    for storage, name in old.items():
        if name in wanted or new.get(storage) != name:
            continue  # written in this call, deleted or renamed: the writer's version counts
        if kind == "pcblib" and not (_model_ids(before, storage) & models_before) <= models:
            skipped.append(storage)
            continue
        prefix = f"{storage}/"
        for key, data in before.items():
            if data is None or not key.startswith(prefix):
                continue
            if after.get(key) != data:
                streams[key] = data
    for key in LIBRARY_STREAMS[kind]:
        data = before.get(key)
        if data is not None and len(data) > 4 and after.get(key) != data and key in after:
            streams[key] = data
    return streams, skipped
