"""Read-only STEP models for previews, including models not extracted during import.

The editable footprint spec represents one STEP reference. A PcbLib may contain several;
previewing reads their original placements without replacing or rewriting the saved spec.
Embedded bytes use the writer's existing extraction cache, never the workspace's 3D folder.
Callers hold the workspace for the complete resolve/read operation.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..db.models import FootprintRecord
from ..footprints.step import file_digest, step_digest
from ..workspace import Workspace
from .rustwriter import RustLibraryOps, RustWriterError

MAX_STEP_BYTES = 64 * 1024 * 1024
MAX_TOTAL_STEP_BYTES = 128 * 1024 * 1024
MAX_STEP_MODELS = 128
Vector = tuple[float, float, float]
ZERO: Vector = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class PreviewModel:
    id: str
    name: str
    path: Path
    digest: str
    byte_size: int
    rotation: Vector
    offset: Vector

    def read(self) -> bytes:
        """Return exactly the revision named by this model, including on external edits."""
        with self.path.open("rb") as stream:
            data = stream.read(MAX_STEP_BYTES + 1)
        if len(data) > MAX_STEP_BYTES or hashlib.sha256(data).hexdigest() != self.digest:
            raise ValueError("Das STEP-Modell wurde geändert. Bitte die Vorschau neu laden.")
        return data


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else 0.0


def _vector(body: dict[str, Any], keys: tuple[str, str, str]) -> Vector:
    return _number(body.get(keys[0])), _number(body.get(keys[1])), _number(body.get(keys[2]))


def _body_rotation(body: dict[str, Any]) -> Vector:
    """Altium's board-plane placement rotates the oriented model around footprint Z.

    MODEL.2D.ROTATION follows MODEL.3D.ROTX/Y/Z. Fixed-axis X/Y/Z composition is
    Rz * Ry * Rx, so the final board-plane rotation combines with its Z component.
    MODEL.2D.X/Y are already footprint-plane translations and are not rotated again.
    """
    rx, ry, rz = _vector(body, ("rotation_x", "rotation_y", "rotation_z"))
    return rx, ry, rz + _number(body.get("model_2d_rotation"))


def _linked_path(ws: Workspace, library: Path | None, file: str) -> Path | None:
    """Resolve a registered reference; never accept paths from the preview request itself."""
    path = Path(file.replace("\\", "/"))
    candidates = ([path] if path.is_absolute() else [
        *([library.parent / path] if library is not None else []),
        ws.root / path,
        ws.models_dir / path,
    ]) + [ws.models_dir / path.name]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _model(ws: Workspace, rec: FootprintRecord, path: Path, name: str,
           rotation: Vector, offset: Vector, key: str) -> PreviewModel:
    """Hash bounded STEP bytes: an ID is valid for one workspace, model, and placement."""
    if path.suffix.lower() not in (".step", ".stp"):
        raise ValueError("Die Modelldatei ist keine STEP-Datei (.step oder .stp).")
    if path.stat().st_size > MAX_STEP_BYTES:
        raise ValueError("Die STEP-Datei ist größer als 64 MB und kann nicht angezeigt werden.")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        head = stream.read(4096)
        if not head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"ISO-10303-21;"):
            raise ValueError("Die Modelldatei enthält keine gültigen STEP-Daten.")
        digest.update(head)
        size += len(head)
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_STEP_BYTES:
                raise ValueError("Die STEP-Datei ist größer als 64 MB und kann nicht angezeigt werden.")
            digest.update(chunk)
    content = digest.hexdigest()
    identity = json.dumps([str(ws.root.resolve()), rec.name, key, content, rotation, offset], ensure_ascii=True)
    return PreviewModel(hashlib.sha256(identity.encode()).hexdigest(), name, path, content, size, rotation, offset)


def _automatic_step(path: Path | None, rec: FootprintRecord, rotation: Vector, offset: Vector) -> bool:
    """PartForge's STEP of its existing prisms must not cover those prisms a second time."""
    if path is None or rec.spec is None or not rec.spec.bodies or rotation != ZERO or offset != ZERO:
        return False
    try:
        with path.open("rb") as stream:
            return file_digest(stream.read(8192).decode("ascii", errors="ignore")) == step_digest(rec.spec)
    except OSError:
        return False


def resolve_models(ws: Workspace, rec: FootprintRecord) -> tuple[list[PreviewModel], list[str]]:
    """All readable registered models and actionable warnings; no registry/library writes.

    Saved model files work without a library writer. For imports the original PcbLib is
    additionally consulted to recover every body, even when import-time extraction was off.
    A saved primary model is retained when the original library or reader is unavailable.
    """
    warnings: list[str] = []
    models: list[PreviewModel] = []
    total_bytes = 0
    spec = rec.spec
    library = ws.abs(rec.library)
    saved_file = spec.step.file if spec is not None and spec.step is not None else rec.step_file
    saved_path = ws.abs(saved_file)
    if saved_path is not None and not saved_path.is_file():
        saved_path = _linked_path(ws, library, saved_file) if saved_file else None
    rotation = spec.step.rotation if spec is not None and spec.step is not None else ZERO
    offset = spec.step.offset if spec is not None and spec.step is not None else ZERO

    def add(path: Path | None, name: str, rot: Vector, off: Vector, key: str) -> bool:
        nonlocal total_bytes
        if path is None:
            warnings.append(f"STEP-Modell „{name}“:\nDie Datei wurde nicht gefunden. Stellen Sie die verknüpfte Datei "
                            "wieder her oder legen Sie sie im 3D-Ordner der Bibliothek ab.")
            return False
        if _automatic_step(path, rec, rot, off):
            return True
        try:
            size = path.stat().st_size
            if total_bytes + size > MAX_TOTAL_STEP_BYTES:
                warnings.append("Die STEP-Modelle überschreiten zusammen 128 MB. Weitere Modelle werden nicht angezeigt.")
                return False
            model = _model(ws, rec, path, Path(name.replace("\\", "/")).name, rot, off, key)
            if total_bytes + model.byte_size > MAX_TOTAL_STEP_BYTES:
                warnings.append("Die STEP-Modelle überschreiten zusammen 128 MB. Weitere Modelle werden nicht angezeigt.")
                return False
            models.append(model)
            total_bytes += model.byte_size
            return True
        except (OSError, ValueError) as exc:
            warnings.append(f"STEP-Modell „{name}“:\n{exc}")
            return False

    def saved() -> None:
        if saved_file:
            add(saved_path, Path(saved_file.replace("\\", "/")).name, rotation, offset, "saved")

    # Generated models have authoritative geometry in the editable spec. In particular,
    # no writer is needed to display a generated/custom STEP file or the existing prisms.
    if rec.source not in ("imported", "external"):
        saved()
        return models, warnings
    if library is None or not library.is_file():
        saved()
        if not saved_file:
            warnings.append("Die ursprüngliche Footprint-Bibliothek wurde nicht gefunden. Eingebettete STEP-Modelle sind nicht verfügbar.")
        return models, warnings

    ops = RustLibraryOps(workspace=ws)
    try:
        raw = ops._get_component(library, rec.name, "pcblib")
    except (RustWriterError, OSError, ValueError) as exc:
        saved()
        warnings.append(f"Die STEP-Modelle der Footprint-Bibliothek konnten nicht gelesen werden.\n{exc}")
        return models, warnings
    if raw is None:
        saved()
        if not saved_file:
            warnings.append("Der Footprint wurde in seiner ursprünglichen Bibliothek nicht gefunden.")
        return models, warnings

    bodies = [body for body in raw.get("component_bodies") or [] if isinstance(body, dict)
              and (body.get("embedded") or body.get("model_id") or str(body.get("model_name") or "").strip())]
    if not bodies:
        legacy = raw.get("model_3d")
        file = legacy.get("filepath") if isinstance(legacy, dict) else None
        if isinstance(file, str) and file.strip():
            add(_linked_path(ws, library, file.strip()) or saved_path, file.strip(), rotation, offset, "legacy")
        else:
            saved()
        return models, warnings
    if len(bodies) > MAX_STEP_MODELS:
        warnings.append("Der Footprint enthält mehr als 128 STEP-Modelle. Die Vorschau zeigt die ersten 128 Modelle.")
        bodies = bodies[:MAX_STEP_MODELS]

    references: list[tuple[str | None, str, Vector, Vector]] = []
    wanted: dict[str, str] = {}
    for body in bodies:
        model_id = str(body.get("model_id") or "").strip()
        name = str(body.get("model_name") or "").strip() or "model.step"
        embedded = bool(model_id) and body.get("embedded") is not False
        if embedded:
            wanted[model_id] = name
        references.append((model_id if embedded else None, name,
                           _body_rotation(body),
                           _vector(body, ("model_2d_x", "model_2d_y", "z_offset"))))
    files: dict[str, Path] = {}
    if wanted:
        try:
            files = ops._extract_models(library, wanted)
        except (RustWriterError, OSError, ValueError) as exc:
            warnings.append(f"Die eingebetteten STEP-Modelle konnten nicht gelesen werden.\n{exc}")
    for index, (model_id, name, rot, off) in enumerate(references):
        path = files.get(model_id) if model_id is not None else _linked_path(ws, library, name)
        # The saved spec represents the first raw STEP reference. A valid extracted or
        # user-provided copy remains useful when the library reader cannot extract it.
        if path is None and index == 0:
            path = saved_path
        add(path, name, rot, off, str(index))
    return models, list(dict.fromkeys(warnings))
