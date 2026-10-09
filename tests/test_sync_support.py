"""Shared helpers of the library-sync tests (fake writer/bridge, parts, synthetic PcbLibs).

Imported by the other ``test_sync_*``, ``test_stackup_*`` and ``test_api_libraries*``
modules; the tests here only check the helpers themselves.
"""
from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import pytest

from partforge.altium.bridge.core import DocumentState
from partforge.altium.models import ComponentInfo, WriteResult
from partforge.db import categories, parts
from partforge.geometry.model import FootprintSpec, SymbolSpec

# --------------------------------------------------------------------------- fake writer


class FakeWriter:
    """In-memory :class:`LibraryWriter` (files are touched so ``exists()`` and caches work)."""

    name = "rust"

    def __init__(self, *, compound: bool = False) -> None:
        self.libs: dict[str, dict[str, SymbolSpec | FootprintSpec]] = {}
        self.calls: list[tuple[str, str, list[str]]] = []
        self.fail: Exception | None = None
        self.errors: dict[str, str] = {}
        self.warnings: list[str] = []
        self.compound = compound  # write PcbLibs as synthetic compound files (Rust header template)
        self._version = 0

    # -- helpers ----------------------------------------------------------------------
    @staticmethod
    def key(library: Path) -> str:
        return os.path.normcase(os.path.abspath(library))

    def _touch(self, library: Path) -> None:
        self._version += 1
        library.parent.mkdir(parents=True, exist_ok=True)
        names = list(self.libs.get(self.key(library), {}))
        if self.compound and library.suffix.lower() == ".pcblib":
            library.unlink(missing_ok=True)
            synthetic_pcblib(library, components=names or ["EMPTY"])
            return
        library.write_text(f"{self._version}|" + "|".join(names), encoding="utf-8")

    def _result(self, library: Path, names: Sequence[str]) -> WriteResult:
        result = WriteResult(library=str(library), backend="rust", warnings=list(self.warnings))
        if self.errors:
            result.errors = {n: self.errors.get(n, "Vorgang fehlgeschlagen") for n in names}
            return result
        result.written = list(names)
        return result

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def put(self, library: Path, specs: Iterable[SymbolSpec | FootprintSpec]) -> None:
        """Place components directly (e.g. 'foreign' components not in the registry)."""
        lib = self.libs.setdefault(self.key(library), {})
        for spec in specs:
            lib[spec.name] = spec
        self._touch(library)

    def names(self, library: Path) -> list[str]:
        return list(self.libs.get(self.key(library), {}))

    # -- protocol ---------------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        return True, "bereit"

    def _upsert(self, op: str, library: Path, specs: Sequence[SymbolSpec | FootprintSpec]) -> WriteResult:
        self.calls.append((op, str(library), [s.name for s in specs]))
        self._check()
        result = self._result(library, [s.name for s in specs])
        if not result.errors:
            lib = self.libs.setdefault(self.key(library), {})
            for spec in specs:
                lib[spec.name] = spec
            self._touch(library)
        return result

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        return self._upsert("write_symbols", library, symbols)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        return self._upsert("write_footprints", library, footprints)

    def write_library_full(self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]) -> WriteResult:
        self.calls.append(("write_library_full", str(library), [s.name for s in specs]))
        self._check()
        result = self._result(library, [s.name for s in specs])
        if not result.errors:
            self.libs[self.key(library)] = {s.name: s for s in specs}
            self._touch(library)
        return result

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        self.calls.append(("delete_components", str(library), list(names)))
        self._check()
        lib = self.libs.setdefault(self.key(library), {})
        result = WriteResult(library=str(library), backend="rust")
        for name in names:
            if name in lib:
                del lib[name]
                result.deleted.append(name)
            else:
                result.warnings.append(f"{name}: nicht in der Bibliothek vorhanden.")
        self._touch(library)
        return result

    def list_components(self, library: Path) -> list[str]:
        self.calls.append(("list_components", str(library), []))
        return self.names(library)

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None:
        spec = self.libs.get(self.key(library), {}).get(name)
        return spec if isinstance(spec, SymbolSpec) else None

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None:
        spec = self.libs.get(self.key(library), {}).get(name)
        return spec if isinstance(spec, FootprintSpec) else None

    def scan_library(self, library: Path) -> list[ComponentInfo]:
        out: list[ComponentInfo] = []
        for name, spec in self.libs.get(self.key(library), {}).items():
            kind = "symbol" if isinstance(spec, SymbolSpec) else "footprint"
            count = len(spec.pins) if isinstance(spec, SymbolSpec) else len(spec.pads)
            out.append(ComponentInfo(name=name, library=str(library), kind=kind, pin_count=count))  # type: ignore[arg-type]
        return out

    def writes(self) -> list[tuple[str, str, list[str]]]:
        return [c for c in self.calls if c[0] != "list_components"]


# --------------------------------------------------------------------------- fake Altium bridge


class FakeBridge:
    """Stands in for :class:`AltiumBridge` (never starts a script)."""

    def __init__(self, *, open_: bool = False, modified: bool = False, refresh: str = "reloaded"):
        self.open = open_
        self.modified = modified
        self.refresh_outcome = refresh
        self.calls: list[tuple[str, str]] = []

    def document_state(self, path: Path) -> DocumentState:
        self.calls.append(("document_state", str(path)))
        return DocumentState(path=str(path), open=self.open, modified=self.modified)

    def refresh_document(self, path: Path, kind: str | None = None) -> str:
        self.calls.append(("refresh_document", str(path)))
        return self.refresh_outcome


# --------------------------------------------------------------------------- parts


def make_part(table: str, pn: str, **links: str) -> dict[str, Any]:
    """Create a part with dummy values for the required fields (``Library_Ref=...``)."""
    cat = categories.get_category(table)
    values: dict[str, Any] = {}
    for f in cat.fields:
        if not f.required:
            continue
        if f.options:
            values[f.column] = f.options[0]
        elif f.kind in ("int", "quantity"):
            values[f.column] = "1"
        elif f.kind == "bool":
            values[f.column] = "Ja"
        else:
            values[f.column] = "X"
    values.update({"Part Number": pn, "Manufacturer Part Number": pn})
    values.update({k.replace("_", " "): v for k, v in links.items()})
    return parts.create_part(table, values)


# --------------------------------------------------------------------------- synthetic PcbLib

MECH_BASE = 0x01020000
_STGM_CREATE = 0x1000
_STGM_READWRITE = 0x2
_STGM_SHARE_EXCLUSIVE = 0x10
RUST_KINDS = {2: "AssemblyTop", 3: "AssemblyBottom", 4: "CourtyardTop", 5: "CourtyardBottom", 6: "3DBodyTop", 7: "3DBodyBottom"}
RUST_NAMES = {2: "Top Assembly", 3: "Bottom Assembly", 4: "Top Courtyard", 5: "Bottom Courtyard", 6: "Top 3D Body", 7: "Bottom 3D Body"}
RUST_ENABLED = {1, 2, 3, 4, 5, 6, 7, 13, 15}


def rust_like_header(*, pairs: bool = True, legacy_kind_on: int | None = None) -> bytes:
    """``Library/Data`` text with the structure of the Rust writer's template (all mechanical
    representations, record breaks, layer sets and pairs)."""
    segs: list[str] = ["FILENAME=", "KIND=Protel_Advanced_PCB_Library", "VERSION=3.00"]

    def name(n: int) -> str:
        return RUST_NAMES.get(n, f"Mechanical {n}")

    def mech(prefix: str, n: int, sep: str = "") -> list[str]:
        out = [
            f"{prefix}ID={{00000000-0000-0000-0000-{n:012d}}}",
            f"{prefix}NAME={name(n)}",
            f"{prefix}LAYERID={MECH_BASE + n}",
            f"{prefix}USEDBYPRIMS=FALSE",
            f"{prefix}MECHENABLED={'TRUE' if n in RUST_ENABLED else 'FALSE'}",
        ]
        if n in RUST_KINDS:
            out.append(f"{prefix}MECHKIND={RUST_KINDS[n]}")
        return out

    for n in range(1, 17):
        segs += mech(f"V9_CACHE_LAYER{68 + n}_", n)
    segs += ["V9_CACHE_LAYER85_ID={X}", "V9_CACHE_LAYER85_NAME=Drill Drawing", "V9_CACHE_LAYER85_LAYERID=16973838"]
    for n in range(17, 33):
        segs += mech(f"V9_CACHE_LAYER{69 + n}_", n)
    segs += ["LAYERMASTERSTACK_V8STYLE=0", "LAYERMASTERSTACK_V8NAME=Master layer stack"]
    for n in range(1, 17):
        segs += mech(f"LAYER_V8_{10 + n}", n)
    segs += ["LAYER_V8_27NAME=Drill Drawing", "LAYER_V8_27LAYERID=16973838"]
    for n in range(17, 33):
        segs += mech(f"LAYER_V8_{23 + n}", n)
    for index in range(1, 83):
        n = index - 56
        layer_name = name(n) if 1 <= n <= 16 else f"Layer {index}"
        group = [
            f"LAYER{index}NAME={layer_name}",
            f"LAYER{index}PREV=0",
            f"LAYER{index}NEXT=0",
            f"LAYER{index}MECHENABLED={'TRUE' if n in RUST_ENABLED else 'FALSE'}",
            f"LAYER{index}COPTHICK=1.4mil",
        ]
        if n in RUST_KINDS or n == legacy_kind_on:
            group.append(f"LAYER{index}MECHKIND={RUST_KINDS.get(n, 'Dimensions')}")
        group += [f"LAYER{index}DIELTYPE=0", f"LAYER{index}DIELMATERIAL=FR-4"]
        if index % 5 == 0:
            group[-1] += "\r"
            group.append("RECORD=Board")
        segs += group
    for j, n in enumerate(range(17, 33)):
        segs += [
            f"LAYERV7_{j}LAYERID={MECH_BASE + n}",
            f"LAYERV7_{j}NAME={name(n)}",
            f"LAYERV7_{j}PREV=16973824",
            f"LAYERV7_{j}NEXT=16973824",
            f"LAYERV7_{j}MECHENABLED=FALSE",
            f"LAYERV7_{j}COPTHICK=1.4mil",
            f"LAYERV7_{j}DIELTYPE=0",
        ]
    rust_mech = ",".join(f"Mechanical{n}" for n in sorted(RUST_ENABLED))
    segs += [
        "LAYERSETSCOUNT=3",
        "LAYERSET1NAME=&All Layers",
        f"LAYERSET1LAYERS=MultiLayer,TopLayer,BottomLayer,KeepOutLayer,{rust_mech},DrillDrawing",
        "LAYERSET2NAME=&Signal Layers",
        "LAYERSET2LAYERS=MultiLayer,TopLayer,BottomLayer",
        "LAYERSET5NAME=&Mechanical Layers",
        f"LAYERSET5LAYERS={rust_mech}",
    ]
    if pairs:
        segs += [
            "MECHPAIR0L1=MECHANICAL2",
            "MECHPAIR0L2=MECHANICAL3",
            "MECHPAIR1L1=MECHANICAL4",
            "MECHPAIR1L2=MECHANICAL5",
            "MECHPAIR2L1=MECHANICAL6",
            "MECHPAIR2L2=MECHANICAL7\r",
        ]
    segs += ["RECORD=Board", "CFGALL.CONFIGURATIONKIND=1", "BOARDVERSION=5.01", "VAULTGUID="]
    return ("|" + "|".join(segs)).encode("ascii")


def library_data(text: bytes, components: Sequence[str] = ("RESC1608X55N", "SOIC-8")) -> bytes:
    """``Library/Data`` stream: length + text + NUL, then the component list."""
    block = text + b"\x00"
    out = struct.pack("<I", len(block)) + block + struct.pack("<I", len(components))
    for name in components:
        raw = name.encode("ascii")
        out += struct.pack("<I", len(raw) + 1) + bytes([len(raw)]) + raw
    return out


EMPTY_KIND_MAPPING = struct.pack("<I", 8) + "1.0\x00".encode("utf-16-le") + struct.pack("<II", 0, 0)
NATIVE_KIND_MAPPING = (
    struct.pack("<I", 8) + "1.0\x00".encode("utf-16-le") + bytes.fromhex("79f5ecb7") + struct.pack("<I", 1)
    + struct.pack("<II", 0x3B, 11)
)


def build_compound(path: Path, streams: dict[str, bytes]) -> Path:
    """Create a compound file (ole32) with the given ``"Storage/Stream": data`` entries."""
    import pythoncom

    mode = _STGM_READWRITE | _STGM_SHARE_EXCLUSIVE
    root = pythoncom.StgCreateStorageEx(str(path), _STGM_CREATE | mode, 0, 0, pythoncom.IID_IStorage)
    storages: dict[str, Any] = {"": root}
    try:
        for name, data in streams.items():
            parts_ = name.split("/")
            parent = ""
            for part in parts_[:-1]:
                key = f"{parent}/{part}" if parent else part
                if key not in storages:
                    storages[key] = storages[parent].CreateStorage(part, mode, 0, 0)
                parent = key
            stream = storages[parent].CreateStream(parts_[-1], mode, 0, 0)
            stream.Write(data)
            del stream
        for key in sorted((k for k in storages if k), key=lambda k: -k.count("/")):
            storages[key].Commit(0)
        root.Commit(0)
    finally:
        storages.clear()
        del root
    return path


def params_stream(name: str, height: str = "0mil", description: str = "Test footprint") -> bytes:
    """``<component>/Parameters`` exactly as the Rust writer stores it (length, text, NUL)."""
    text = f"|PATTERN={name}|HEIGHT={height}|DESCRIPTION={description}|ITEMGUID=|REVISIONGUID=".encode("latin-1")
    text += b"\x00"
    return struct.pack("<I", len(text)) + text


def toc_stream(entries: Iterable[tuple[str, int, str, str]]) -> bytes:
    """``Library/ComponentParamsTOC/Data``: ``Name=…|Pad Count=…|Height=…|Description=…`` CRLF per component."""
    text = b"".join(
        f"Name={name}|Pad Count={pads}|Height={height}|Description={description}\r\n".encode("latin-1")
        for name, pads, height, description in entries
    )
    text += b"\x00"
    return struct.pack("<I", len(text)) + text


def synthetic_pcblib(path: Path, *, header: bytes | None = None, mapping: bytes | None = EMPTY_KIND_MAPPING,
                     components: Sequence[str] = ("RESC1608X55N", "SOIC-8"),
                     heights: dict[str, str] | None = None, toc: bool = True) -> Path:
    """A compound file with the structure of a Rust-written PcbLib.

    ``heights`` (component -> stored ``HEIGHT`` value, e.g. ``"0mil"``) adds every
    component's ``Parameters`` stream and, with ``toc``, the parameter table of contents.
    """
    streams = {
        "FileHeader": b"\x1b\x00\x00\x00PCB 6.0 Binary Library File",
        "Library/Header": struct.pack("<I", 1),
        "Library/Data": library_data(header if header is not None else rust_like_header(), components),
    }
    if mapping is not None:
        streams["Library/LayerKindMapping/Header"] = struct.pack("<I", 1)
        streams["Library/LayerKindMapping/Data"] = mapping
    if heights is not None and toc:
        streams["Library/ComponentParamsTOC/Header"] = struct.pack("<I", 1)
        streams["Library/ComponentParamsTOC/Data"] = toc_stream(
            (name, 2, heights.get(name, "0mil").removesuffix("mil"), "Test footprint") for name in components
        )
    for name in components:
        streams[f"{name}/Data"] = name.encode("ascii") * 20
        streams[f"{name}/Header"] = struct.pack("<I", 3)
        if heights is not None:
            streams[f"{name}/Parameters"] = params_stream(name, heights.get(name, "0mil"))
    return build_compound(path, streams)


# --------------------------------------------------------------------------- self-tests


def test_fake_writer_round_trip(tmp_path: Path):
    writer = FakeWriter()
    lib = tmp_path / "Symbols" / "X.SchLib"
    spec = SymbolSpec(name="A")
    writer.write_symbols(lib, [spec])
    assert lib.is_file() and writer.names(lib) == ["A"]
    writer.write_library_full(lib, [SymbolSpec(name="B")])
    assert writer.names(lib) == ["B"]
    result = writer.delete_components(lib, ["B", "C"])
    assert result.deleted == ["B"] and "C: nicht in der Bibliothek vorhanden." in result.warnings


def test_synthetic_pcblib_is_a_compound_file(tmp_path: Path):
    from partforge.altium.stackup import read_library_data, read_pcblib_layers

    path = synthetic_pcblib(tmp_path / "S.PcbLib")
    data = read_library_data(path)
    (length,) = struct.unpack_from("<I", data, 0)
    assert data[4 + length - 1] == 0 and data.endswith(b"SOIC-8")
    layers = read_pcblib_layers(path)
    assert layers[2].name == "Top Assembly" and layers[2].kind == "AssemblyTop" and layers[2].enabled
    assert layers[9].name == "Mechanical 9" and not layers[9].enabled and layers[9].kind is None


@pytest.mark.parametrize("table", ["Resistors", "Connectors", "Integrated Circuits"])
def test_make_part(workspace, table):
    part = make_part(table, f"PN-{table[:3]}", Library_Ref="Resistor")
    assert part["Library Ref"] == "Resistor"
