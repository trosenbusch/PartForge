"""Own layer sets (Altium *View Configuration › Layer Sets*, :mod:`partforge.altium.layersets`): reading ``.layerset``
files, layer tokens, the set built from the LayerMap, the workspace setting ``layer_set``, writing the set into PcbLib
headers (:mod:`partforge.altium.stackup`) and the API (``/api/libraries/layer-set/*``, workspace settings)."""
from __future__ import annotations

import hashlib
import json
import re
import struct
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient
from test_sync_support import EMPTY_KIND_MAPPING, RUST_ENABLED, library_data, rust_like_header, synthetic_pcblib
from test_writer_samples import chip_0603

from partforge.altium import stackup, sync
from partforge.altium.layersets import (
    BUILTIN_NAME,
    LayerSetDef,
    LayerSetError,
    builtin_layer_set,
    layer_for_token,
    parse_layerset_file,
    parse_layerset_text,
    resolve_layer_set,
    token_for_layer,
    token_problem,
    workspace_layer_set,
)
from partforge.altium.libwriter import WriterUnavailable
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.altium.stackup import (
    LayerStack,
    default_stack,
    effective_stack,
    patch_pcblib_layers,
    pcblib_layer_problems,
    plan_library_data,
    read_library_data,
    workspace_stack,
)
from partforge.workspace import LayerMap, LayerSetSettings, Workspace, set_current

# --------------------------------------------------------------------------- inputs

#: The user's "Component" set as exported by Altium (single set; any LAYERSET<n> numbering is accepted).
COMPONENT_TOKENS = [
    "TopLayer", "BottomLayer", "TopOverlay", "BottomOverlay", "TopPaste", "BottomPaste", "TopSolder", "BottomSolder",
    "DrillGuide", "DrillDrawing", "MultiLayer", "Mechanical1", "Mechanical9", "Mechanical11", "Mechanical13",
    "Mechanical15", "Mechanical17", "Mechanical19", "Mechanical21",
]
#: "Component Layers" of the default LayerMap in Altium's order (Mech 1-16 before, Mech 17-32 after DrillDrawing).
BUILTIN_LAYERS = [
    "MultiLayer", "TopPaste", "TopOverlay", "TopSolder", "TopLayer", "BottomLayer", "DrillGuide", "KeepOutLayer",
    "Mechanical9", "Mechanical11", "Mechanical13", "Mechanical15", "DrillDrawing", "Mechanical17", "Mechanical19",
    "Mechanical21",
]
#: Header fields of "Component Layers" (default LayerMap, current).
BUILTIN_FIELDS = {
    "NAME": "Component Layers",
    "LAYERS": ",".join(BUILTIN_LAYERS),
    "ACTIVELAYER.7": "TOP",
    "ISCURRENT": "TRUE",
    "ISLOCKED": "FALSE",
    "FLIPBOARD": "FALSE",
}
_RUST_MECH = [f"Mechanical{n}" for n in sorted(RUST_ENABLED)]
#: Altium's own sets in the Rust writer's template – name, layers, active layer. VERIFIED in a Rust-written PcbLib:
#: LAYERSETSCOUNT=5, sets numbered 1..5, each with all six fields (``rust_like_header`` has only sets 1, 2 and 5).
NATIVE_SETS: list[tuple[str, list[str], str]] = [
    ("&All Layers", ["MultiLayer", "TopPaste", "TopOverlay", "TopSolder", "TopLayer", "BottomLayer", "BottomSolder",
                     "BottomOverlay", "BottomPaste", "DrillGuide", "KeepOutLayer", *_RUST_MECH, "DrillDrawing"], "TOP"),
    ("&Signal Layers", ["MultiLayer", "TopLayer", "BottomLayer"], "TOP"),
    ("&Plane Layers", [], "UNKNOWN"),
    ("&NonSignal Layers", ["MultiLayer", "TopPaste", "TopOverlay", "TopSolder", "BottomSolder", "BottomOverlay",
                           "BottomPaste", "DrillGuide", "KeepOutLayer", "DrillDrawing"], "MULTILAYER"),
    ("&Mechanical Layers", _RUST_MECH, "MECHANICAL1"),
]


def set_segments(index: int, name: str, layers: Sequence[str], active: str = "TOP", *, current: bool = True,
                 locked: bool = False, flip: bool = False) -> list[str]:
    """The six ``LAYERSET<index>…=…`` entries of one set as Altium writes them (header and ``.layerset`` file)."""
    flag = {True: "TRUE", False: "FALSE"}
    return [
        f"LAYERSET{index}NAME={name}",
        f"LAYERSET{index}LAYERS={','.join(layers)}",
        f"LAYERSET{index}ACTIVELAYER.7={active}",
        f"LAYERSET{index}ISCURRENT={flag[current]}",
        f"LAYERSET{index}ISLOCKED={flag[locked]}",
        f"LAYERSET{index}FLIPBOARD={flag[flip]}",
    ]


def layerset_text(*sets: list[str]) -> str:
    """``.layerset`` text: every entry of the sets in one '|'-separated line."""
    return "|".join(entry for entries in sets for entry in entries) + "\r\n"


COMPONENT_LAYERSET = layerset_text(set_segments(6, "Component", COMPONENT_TOKENS))


def header_with_sets(*extra: list[str], current: int | None = 1) -> bytes:
    """``rust_like_header()`` with the Rust template's layer-set block (Altium's five sets, the one numbered
    ``current`` is the current set) followed by the ``extra`` sets, ``LAYERSETSCOUNT`` counting all of them."""
    entries = [f"LAYERSETSCOUNT={len(NATIVE_SETS) + len(extra)}"]
    for index, (name, layers, active) in enumerate(NATIVE_SETS, start=1):
        entries += set_segments(index, name, layers, active, current=index == current, locked=True)
    for extra_set in extra:
        entries += extra_set
    base = rust_like_header()
    start, end = base.index(b"|LAYERSETSCOUNT="), base.index(b"|MECHPAIR0L1=")
    return base[:start] + ("|" + "|".join(entries)).encode("cp1252") + base[end:]


# --------------------------------------------------------------------------- helpers


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _header_text(data: bytes) -> bytes:
    """Header text of a ``Library/Data`` stream (without length prefix and NUL)."""
    (length,) = struct.unpack_from("<I", data, 0)
    return data[4 : 4 + length - 1]


def _lib_text(path: Path) -> bytes:
    return _header_text(read_library_data(path))


def _keys(text: bytes) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for seg in text[1:].split(b"|"):
        key, _, value = seg.partition(b"=")
        out.setdefault(key, value.rstrip(b"\r"))
    return out


def _key_order(text: bytes) -> list[bytes]:
    return [seg.partition(b"=")[0] for seg in text[1:].split(b"|")]


_SET_KEY = re.compile(rb"^LAYERSET(\d+)(.+)$")


def _sets(text: bytes) -> dict[int, dict[str, str]]:
    """``{set number: {field: value}}`` of a header text."""
    out: dict[int, dict[str, str]] = {}
    for key, value in _keys(text).items():
        m = _SET_KEY.match(key)
        if m:
            out.setdefault(int(m.group(1)), {})[m.group(2).decode("ascii")] = value.decode("cp1252")
    return out


def _workspace(tmp_path: Path, **layer_set: Any) -> Workspace:
    """A library folder (not opened) whose setting ``layer_set`` is ``LayerSetSettings(**layer_set)``."""
    ws = Workspace.create(tmp_path / "Lagensatz-Bibliothek", name="Lagensatz-Test")
    ws.settings.layer_set = LayerSetSettings(**layer_set)
    return ws


def _stack(ws: Workspace) -> tuple[LayerStack, list[str]]:
    """The stack the library writers and the layer job use: workspace stack, LayerMap layers enabled."""
    base, notes = workspace_stack(ws)
    return effective_stack(base, ws.settings.layers), notes


def _stack_with(definition: LayerSetDef | None) -> LayerStack:
    return effective_stack(default_stack(), LayerMap()).model_copy(update={"layer_set": definition})


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    """Synthetic Rust-written PcbLib whose header has Altium's five sets ("&All Layers" is the current one)."""
    return synthetic_pcblib(tmp_path / "PF_CHIP.PcbLib", header=header_with_sets())


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module() -> Iterator[None]:
    yield
    shutdown_client()


# --------------------------------------------------------------------------- parsing


def test_parse_the_component_set_of_an_altium_export() -> None:
    assert parse_layerset_text(COMPONENT_LAYERSET) == [
        LayerSetDef(name="Component", layers=COMPONENT_TOKENS, active_layer="TOP", current=True, locked=False,
                    flip_board=False)
    ]


def test_parse_several_sets_in_their_numbering_order() -> None:
    text = layerset_text(
        set_segments(1, "&All Layers", ["TopLayer", "BottomLayer"], locked=True),  # Altium's own set: not offered
        set_segments(7, "Bestückung oben", ["TopOverlay", "Mechanical9"], "MECHANICAL9", current=False),
        set_segments(3, "Kupfer", ["TopLayer", "BottomLayer", "MultiLayer"], "BOTTOM", locked=True, flip=True),
    )
    assert parse_layerset_text(text) == [
        LayerSetDef(name="Kupfer", layers=["TopLayer", "BottomLayer", "MultiLayer"], active_layer="BOTTOM",
                    current=True, locked=True, flip_board=True),
        LayerSetDef(name="Bestückung oben", layers=["TopOverlay", "Mechanical9"], active_layer="MECHANICAL9",
                    current=False, locked=False, flip_board=False),
    ]


def test_parse_sets_on_separate_lines() -> None:
    lines = ["|".join(set_segments(1, "Oben", ["TopLayer"])), "|".join(set_segments(2, "Unten", ["BottomLayer"]))]
    sets = parse_layerset_text("\r\n".join(lines))
    assert [(s.name, s.layers) for s in sets] == [("Oben", ["TopLayer"]), ("Unten", ["BottomLayer"])]


def test_parse_defaults_for_missing_fields() -> None:
    assert parse_layerset_text("LAYERSET2NAME=Minimal|LAYERSET2LAYERS=TopLayer") == [
        LayerSetDef(name="Minimal", layers=["TopLayer"], active_layer="TOP", current=True, locked=False,
                    flip_board=False)
    ]


def test_parse_is_tolerant_of_case_blanks_duplicates_and_nul() -> None:
    text = (
        "layerset4name=  Mein   Satz \x00|layerset4layers= TopLayer , Mechanical13,,TopLayer |"
        "layerset4activelayer.7=bottom|layerset4iscurrent=false|layerset4islocked=true\rLAYERSET4FLIPBOARD=True"
    )
    assert parse_layerset_text(text) == [
        LayerSetDef(name="Mein Satz", layers=["TopLayer", "Mechanical13"], active_layer="BOTTOM", current=False,
                    locked=True, flip_board=True)
    ]


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("Bauteile = oben\tlinks", "Bauteile oben links"),  # '=' and control characters never reach a header
        ("L" * 80, "L" * 60),  # Altium's name length
    ],
)
def test_parse_cleans_the_name(raw: str, name: str) -> None:
    assert parse_layerset_text(f"LAYERSET1NAME={raw}|LAYERSET1LAYERS=TopLayer")[0].name == name


@pytest.mark.parametrize("active", ["Top Layer", "", "top_layer"])
def test_parse_falls_back_to_top_for_an_unusable_active_layer(active: str) -> None:
    text = f"LAYERSET1NAME=A|LAYERSET1LAYERS=TopLayer|LAYERSET1ACTIVELAYER.7={active}"
    assert parse_layerset_text(text)[0].active_layer == "TOP"


def test_layer_set_written_into_a_header_reads_back_unchanged() -> None:
    definition = LayerSetDef(name="Bestückung", layers=["TopOverlay", "Mechanical9", "Mechanical33"],
                             active_layer="MECHANICAL9", current=False, locked=True, flip_board=True)
    values = definition.header_values()
    assert values == {"NAME": "Bestückung", "LAYERS": "TopOverlay,Mechanical9,Mechanical33",
                      "ACTIVELAYER.7": "MECHANICAL9", "ISCURRENT": "FALSE", "ISLOCKED": "TRUE", "FLIPBOARD": "TRUE"}
    assert parse_layerset_text("|".join(f"LAYERSET9{k}={v}" for k, v in values.items())) == [definition]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "In der Datei wurde kein eigener Lagensatz gefunden."),
        ("KIND=Protel|VERSION=1.0", "In der Datei wurde kein eigener Lagensatz gefunden."),
        (layerset_text(set_segments(1, "&All Layers", ["TopLayer"])), "kein eigener Lagensatz gefunden"),
        ("LAYERSET1LAYERS=TopLayer,BottomLayer", "kein eigener Lagensatz gefunden"),  # a set without a name
        ("LAYERSET1NAME=X|LAYERSET1LAYERS=TopLayer,FooLayer", "Unbekannte Lage „FooLayer“ im Lagensatz."),
        ("LAYERSET1NAME=X|LAYERSET1LAYERS=toplayer", "Unbekannte Lage „toplayer“ im Lagensatz."),
        ("LAYERSET1NAME=X|LAYERSET1LAYERS=Top Layer", "Unbekannte Lage „Top Layer“ im Lagensatz."),
        ("LAYERSET1NAME=Leer|LAYERSET1LAYERS= , ", "Der Lagensatz „Leer“ enthält keine Lagen."),
        ("LAYERSET1NAME=Leer", "Der Lagensatz „Leer“ enthält keine Lagen."),
        ("LAYERSET1NAME===|LAYERSET1LAYERS=TopLayer", "Der Lagensatz braucht einen Namen."),
        # one unusable set makes the whole file unusable
        ("LAYERSET1NAME=Gut|LAYERSET1LAYERS=TopLayer|LAYERSET2NAME=Schlecht|LAYERSET2LAYERS=Mechanical9,Bogus",
         "Unbekannte Lage „Bogus“ im Lagensatz."),
    ],
)
def test_parse_refuses_unusable_text(text: str, message: str) -> None:
    with pytest.raises(LayerSetError) as info:
        parse_layerset_text(text)
    assert message in str(info.value)


def test_parse_names_the_source_in_the_message() -> None:
    with pytest.raises(LayerSetError, match="In Leer.layerset wurde kein eigener Lagensatz gefunden"):
        parse_layerset_text("", source="Leer.layerset")


def test_parse_file_reads_ansi_text(tmp_path: Path) -> None:
    component = tmp_path / "Component.layerset"
    component.write_text(COMPONENT_LAYERSET, encoding="cp1252", newline="")
    assert parse_layerset_file(component) == parse_layerset_text(COMPONENT_LAYERSET)
    # Windows-1252 (Altium's ANSI) – not valid UTF-8
    umlaut = tmp_path / "Bestückung.layerset"
    umlaut.write_bytes(layerset_text(set_segments(2, "Bestückung", ["TopOverlay", "Mechanical9"])).encode("cp1252"))
    assert [s.name for s in parse_layerset_file(umlaut)] == ["Bestückung"]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (None, "wurde nicht gefunden"),
        (b"", "Leer.layerset ist keine Altium-Lagensatz-Datei (.layerset)."),
        (bytes(range(256)) * 8, "Leer.layerset ist keine Altium-Lagensatz-Datei (.layerset)."),  # binary garbage
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\xff\xfe\xfd", "keine Altium-Lagensatz-Datei"),
        (b"LAYERSETSCOUNT=0|KIND=Protel", "In Leer.layerset wurde kein eigener Lagensatz gefunden."),
        (b"LAYERSET1NAME=X|" + b" " * 1_000_000, "Leer.layerset ist zu groß für eine .layerset-Datei."),
    ],
    ids=["missing", "empty", "binary", "png", "no-own-set", "too-large"],
)
def test_parse_file_refuses_unusable_files(tmp_path: Path, content: bytes | None, message: str) -> None:
    path = tmp_path / "Leer.layerset"
    if content is not None:
        path.write_bytes(content)
    with pytest.raises(LayerSetError) as info:
        parse_layerset_file(path)
    assert message in str(info.value)


def test_parse_file_refuses_a_folder(tmp_path: Path) -> None:
    with pytest.raises(LayerSetError, match="konnte nicht gelesen werden"):
        parse_layerset_file(tmp_path)


# --------------------------------------------------------------------------- tokens


@pytest.mark.parametrize(
    ("layer", "token"),
    [
        ("Top Overlay", "TopOverlay"),
        ("Bottom Overlay", "BottomOverlay"),
        ("Top Layer", "TopLayer"),
        ("Bottom Layer", "BottomLayer"),
        ("Multi-Layer", "MultiLayer"),
        ("Top Paste", "TopPaste"),
        ("Bottom Solder", "BottomSolder"),
        ("Keep-Out Layer", "KeepOutLayer"),
        ("Drill Guide", "DrillGuide"),
        ("Drill Drawing", "DrillDrawing"),
        ("Mechanical 1", "Mechanical1"),
        ("Mechanical 9", "Mechanical9"),
        ("Mechanical 17", "Mechanical17"),
        ("Mechanical 32", "Mechanical32"),
        ("Mid-Layer 1", "MidLayer1"),
        ("Mid-Layer 30", "MidLayer30"),
        ("Internal Plane 16", "InternalPlane16"),
    ],
)
def test_token_round_trip(layer: str, token: str) -> None:
    assert token_for_layer(layer) == token
    assert layer_for_token(token) == layer
    assert token_problem(token) is None


@pytest.mark.parametrize(
    ("spelling", "token"),
    [
        ("Mech 15", "Mechanical15"),
        ("Mechanical Layer 9", "Mechanical9"),
        ("M21", "Mechanical21"),
        ("Top Assembly", "Mechanical2"),  # Rust writer alias
        ("top silkscreen", "TopOverlay"),
        ("Multi Layer", "MultiLayer"),
        ("Top Solder Mask", "TopSolder"),
    ],
)
def test_token_for_layer_accepts_other_spellings(spelling: str, token: str) -> None:
    assert token_for_layer(spelling) == token


@pytest.mark.parametrize(
    "layer", ["", "   ", "Foo", "Mechanical 0", "Mechanical 33", "Mid-Layer 31", "Internal Plane 17"]
)
def test_token_for_layer_of_unknown_layers(layer: str) -> None:
    assert token_for_layer(layer) is None


def test_tokens_altium_knows_beyond_the_header_layers() -> None:
    assert layer_for_token("ConnectLayer") == "Connect Layer" and token_problem("ConnectLayer") is None
    assert layer_for_token("Mechanical100") == "Mechanical 100"  # Altium has up to 1024 mechanical layers
    assert token_problem("Mechanical1024") is None


@pytest.mark.parametrize("token", ["Foo", "toplayer", "TOPLAYER", "Top Layer", "Mechanical", "MidLayer0", "MidLayer31",
                                   "InternalPlane0", "InternalPlane17"])
def test_unknown_tokens(token: str) -> None:
    assert layer_for_token(token) is None
    assert token_problem(token) == f"Unbekannte Lage „{token}“ im Lagensatz."


@pytest.mark.parametrize("token", ["Mechanical0", "Mechanical01", "Mechanical1025"])
def test_impossible_mechanical_numbers_are_unknown(token: str) -> None:
    assert token_problem(token) == f"Unbekannte Lage „{token}“ im Lagensatz."


# --------------------------------------------------------------------------- built-in set


def test_builtin_set_of_the_default_layer_map() -> None:
    built = builtin_layer_set(LayerMap())
    assert built.name == BUILTIN_NAME == "Component Layers"
    assert (built.active_layer, built.current, built.locked, built.flip_board) == ("TOP", True, False, False)
    for token in ("TopLayer", "BottomLayer", "TopPaste", "TopSolder", "TopOverlay", "DrillGuide", "DrillDrawing",
                  "MultiLayer", "KeepOutLayer"):
        assert token in built.layers, token
    mechanical = [f"Mechanical{n}" for n in (9, 11, 13, 15, 17, 19, 21)]  # exactly the layers of the LayerMap
    assert [t for t in built.layers if t.startswith("Mechanical")] == mechanical
    assert built.layers == BUILTIN_LAYERS  # Altium's order of the user's "Component Layers"
    assert all(token_problem(t) is None for t in built.layers) and len(set(built.layers)) == len(built.layers)
    assert builtin_layer_set() == built


@pytest.mark.parametrize(
    ("changes", "low", "high"),
    [
        ({"assembly": "Mechanical 5"}, [5, 11, 13, 15], [17, 19, 21]),
        ({"assembly": "Mechanical 16"}, [11, 13, 15, 16], [17, 19, 21]),
        ({"courtyard": "Mechanical 28", "component_outline": "Mechanical 3"}, [3, 9, 11, 13], [17, 19, 28]),
        ({"designator": "Mechanical 9", "comment": "Mechanical 9"}, [9, 13, 15], [17, 21]),  # shared layers once
        ({"body3d": "Top Overlay"}, [9, 11, 15], [17, 19, 21]),  # a role on a non-mechanical layer adds none
    ],
)
def test_builtin_set_follows_the_layer_map(changes: dict[str, str], low: list[int], high: list[int]) -> None:
    layers = builtin_layer_set(LayerMap(**changes)).layers
    assert [t for t in layers if t.startswith("Mechanical")] == [f"Mechanical{n}" for n in (*low, *high)]
    at = layers.index("DrillDrawing")
    assert layers[at - len(low) : at] == [f"Mechanical{n}" for n in low]  # Mech 1-16 right before DrillDrawing
    assert layers[at + 1 :] == [f"Mechanical{n}" for n in high]  # Mech 17-32 after it


def test_builtin_set_contains_the_silkscreen_layer() -> None:
    layers = builtin_layer_set(LayerMap(silkscreen="Bottom Overlay")).layers
    assert "BottomOverlay" in layers and "TopOverlay" not in layers


def test_builtin_current_flag_passes_through() -> None:
    assert builtin_layer_set(LayerMap(), current=False).current is False
    assert builtin_layer_set(LayerMap(), current=True).current is True


def test_header_set_lists_a_mechanical_silkscreen_layer_once() -> None:
    resolved = resolve_layer_set(LayerSetSettings(mode="builtin"), LayerMap(silkscreen="Mechanical 3"))
    assert resolved is not None and resolved.layers.count("Mechanical3") == 1


def test_builtin_set_lists_a_mechanical_silkscreen_layer_once() -> None:
    assert builtin_layer_set(LayerMap(silkscreen="Mechanical 3")).layers.count("Mechanical3") == 1


# --------------------------------------------------------------------------- settings -> layer set


def test_resolve_mode_none() -> None:
    assert resolve_layer_set(LayerSetSettings()) is None
    assert resolve_layer_set(LayerSetSettings(mode="none", name="X", layers=["TopLayer"])) is None


def test_resolve_builtin_uses_the_layer_map_and_the_current_flag() -> None:
    layer_map = LayerMap(assembly="Mechanical 5")
    assert resolve_layer_set(LayerSetSettings(mode="builtin"), layer_map) == builtin_layer_set(layer_map)
    off = resolve_layer_set(LayerSetSettings(mode="builtin", current=False), layer_map)
    assert off == builtin_layer_set(layer_map, current=False)
    assert resolve_layer_set(LayerSetSettings(mode="builtin")) == builtin_layer_set(LayerMap())


@pytest.mark.parametrize(
    ("name", "expected"),
    [(None, BUILTIN_NAME), ("", BUILTIN_NAME), ("   ", BUILTIN_NAME), ("  Meine   Bauteile ", "Meine Bauteile"),
     ("Oben|Unten=Alle", "Oben Unten Alle")],
)
def test_resolve_builtin_with_an_own_name(name: str | None, expected: str) -> None:
    resolved = resolve_layer_set(LayerSetSettings(mode="builtin", name=name))
    assert resolved is not None and resolved.name == expected and resolved.layers == BUILTIN_LAYERS


def test_resolve_file_uses_the_stored_definition() -> None:
    settings = LayerSetSettings(mode="file", file=r"C:\Vorlagen\Component.layerset", name="Component",
                                layers=[" TopLayer", "Mechanical9", "TopLayer", ""], active_layer="bottom",
                                current=False, locked=True, flip_board=True)
    assert resolve_layer_set(settings) == LayerSetDef(name="Component", layers=["TopLayer", "Mechanical9"],
                                                      active_layer="BOTTOM", current=False, locked=True,
                                                      flip_board=True)
    plain = LayerSetSettings(mode="file", name="Component", layers=COMPONENT_TOKENS)
    assert resolve_layer_set(plain) == LayerSetDef(name="Component", layers=COMPONENT_TOKENS, active_layer="TOP")


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (LayerSetSettings(mode="file", layers=["TopLayer"]), "Der Lagensatz braucht einen Namen."),
        (LayerSetSettings(mode="file", name="Leer"), "Der Lagensatz „Leer“ enthält keine Lagen."),
        (LayerSetSettings(mode="file", name="X", layers=["TopLayer", "Top Overlay"]),
         "Unbekannte Lage „Top Overlay“ im Lagensatz."),
        (LayerSetSettings(mode="builtin", name="&All Layers"),
         "„&All Layers“ ist ein Altium-Standardsatz – bitte einen eigenen Lagensatz wählen."),
    ],
)
def test_resolve_refuses_unusable_definitions(settings: LayerSetSettings, message: str) -> None:
    with pytest.raises(LayerSetError) as info:
        resolve_layer_set(settings)
    assert str(info.value) == message


def test_workspace_layer_set_notes_instead_of_raising(tmp_path: Path) -> None:
    assert workspace_layer_set(None) == (None, [])
    ws = _workspace(tmp_path)
    assert workspace_layer_set(ws) == (None, [])
    ws.settings.layer_set = LayerSetSettings(mode="builtin")
    ws.settings.layers = LayerMap(assembly="Mechanical 5")
    assert workspace_layer_set(ws) == (builtin_layer_set(LayerMap(assembly="Mechanical 5")), [])
    ws.settings.layer_set = LayerSetSettings(mode="file", name="Kaputt", layers=["TopLayer", "Foo"])
    note = "Lagensatz nicht verwendet: Unbekannte Lage „Foo“ im Lagensatz."
    assert workspace_layer_set(ws) == (None, [note])
    stack, notes = workspace_stack(ws)
    assert stack.layer_set is None and notes == [note]


def test_workspace_stack_carries_the_layer_set(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, mode="builtin", current=False)
    stack, notes = _stack(ws)
    assert notes == [] and stack.layer_set == builtin_layer_set(LayerMap(), current=False)
    ws.settings.layer_set = LayerSetSettings()
    assert _stack(ws)[0].layer_set is None


def test_layer_set_setting_is_stored_in_the_library_folder(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, mode="file", file=str(tmp_path / "Component.layerset"), name="Component",
                    layers=COMPONENT_TOKENS, active_layer="TOP", current=False, locked=True)
    ws.save()
    assert Workspace.open(ws.root).settings.layer_set == ws.settings.layer_set
    # partforge.json of an older PartForge (no layer_set): no own set
    config = ws.root / "partforge.json"
    data = json.loads(config.read_text(encoding="utf-8"))
    del data["layer_set"]
    config.write_text(json.dumps(data), encoding="utf-8")
    assert Workspace.open(ws.root).settings.layer_set == LayerSetSettings()


# --------------------------------------------------------------------------- PcbLib header


@pytest.mark.windows
def test_patch_appends_the_builtin_set_as_the_current_one(tmp_path: Path, lib: Path) -> None:
    stack, notes = _stack(_workspace(tmp_path, mode="builtin"))
    assert notes == []
    assert "Der Lagensatz „Component Layers“ fehlt im Bibliothekskopf." in pcblib_layer_problems(lib, stack)
    assert patch_pcblib_layers(lib, stack) == []
    text = _lib_text(lib)
    assert _keys(text)[b"LAYERSETSCOUNT"] == b"6"
    sets = _sets(text)
    assert sets[6] == BUILTIN_FIELDS
    assert [sets[n]["ISCURRENT"] for n in range(1, 6)] == ["FALSE"] * 5  # "&All Layers" was the current set
    assert [sets[n]["NAME"] for n in range(1, 6)] == [name for name, _layers, _active in NATIVE_SETS]
    order = _key_order(text)
    assert order[order.index(b"LAYERSET5FLIPBOARD") + 1 :][:6] == [
        b"LAYERSET6NAME", b"LAYERSET6LAYERS", b"LAYERSET6ACTIVELAYER.7", b"LAYERSET6ISCURRENT", b"LAYERSET6ISLOCKED",
        b"LAYERSET6FLIPBOARD",
    ]
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.windows
def test_second_patch_changes_nothing(tmp_path: Path, lib: Path) -> None:
    stack, _notes = _stack(_workspace(tmp_path, mode="builtin"))
    assert patch_pcblib_layers(lib, stack) == []
    digest = _sha(lib)
    assert patch_pcblib_layers(lib, stack) == []
    assert _sha(lib) == digest
    assert _keys(_lib_text(lib))[b"LAYERSETSCOUNT"] == b"6"


@pytest.mark.windows
def test_set_that_is_not_current_leaves_the_current_set_alone(tmp_path: Path, lib: Path) -> None:
    stack, _notes = _stack(_workspace(tmp_path, mode="builtin", current=False))
    assert patch_pcblib_layers(lib, stack) == []
    sets = _sets(_lib_text(lib))
    assert sets[6] == {**BUILTIN_FIELDS, "ISCURRENT": "FALSE"}
    assert sets[1]["ISCURRENT"] == "TRUE"
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.windows
def test_file_set_is_written_with_its_flags(tmp_path: Path, lib: Path) -> None:
    ws = _workspace(tmp_path, mode="file", file=str(tmp_path / "Component.layerset"), name="Component",
                    layers=COMPONENT_TOKENS, active_layer="BOTTOM", locked=True, flip_board=True)
    stack, _notes = _stack(ws)
    assert patch_pcblib_layers(lib, stack) == []
    assert _sets(_lib_text(lib))[6] == {
        "NAME": "Component", "LAYERS": ",".join(COMPONENT_TOKENS), "ACTIVELAYER.7": "BOTTOM", "ISCURRENT": "TRUE",
        "ISLOCKED": "TRUE", "FLIPBOARD": "TRUE",
    }


@pytest.mark.windows
def test_set_with_the_same_name_is_updated_instead_of_appended(tmp_path: Path) -> None:
    stale = set_segments(6, "component layers", ["TopLayer", "Mechanical9"], "BOTTOM", current=False, locked=True)
    lib = synthetic_pcblib(tmp_path / "PF_OLD.PcbLib", header=header_with_sets(stale))
    stack = _stack_with(builtin_layer_set(LayerMap()))
    assert patch_pcblib_layers(lib, stack) == []
    text = _lib_text(lib)
    sets = _sets(text)
    assert _keys(text)[b"LAYERSETSCOUNT"] == b"6" and sorted(sets) == [1, 2, 3, 4, 5, 6]
    assert sets[6] == BUILTIN_FIELDS
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.windows
def test_missing_fields_of_an_existing_set_are_added(tmp_path: Path) -> None:
    partial = ["LAYERSET6NAME=Component Layers", "LAYERSET6LAYERS=TopLayer"]
    lib = synthetic_pcblib(tmp_path / "PF_PART.PcbLib", header=header_with_sets(partial))
    stack = _stack_with(builtin_layer_set(LayerMap()))
    assert patch_pcblib_layers(lib, stack) == []
    text = _lib_text(lib)
    assert _sets(text)[6] == BUILTIN_FIELDS and _keys(text)[b"LAYERSETSCOUNT"] == b"6"
    order = _key_order(text)
    at = order.index(b"LAYERSET6LAYERS")
    assert order[at + 1 : at + 5] == [b"LAYERSET6ACTIVELAYER.7", b"LAYERSET6ISCURRENT", b"LAYERSET6ISLOCKED",
                                      b"LAYERSET6FLIPBOARD"]


@pytest.mark.windows
def test_renamed_set_is_appended_and_the_old_one_stays(lib: Path) -> None:
    assert patch_pcblib_layers(lib, _stack_with(builtin_layer_set(LayerMap()))) == []
    renamed = builtin_layer_set(LayerMap()).model_copy(update={"name": "Bauteile"})
    assert patch_pcblib_layers(lib, _stack_with(renamed)) == []
    text = _lib_text(lib)
    sets = _sets(text)
    assert _keys(text)[b"LAYERSETSCOUNT"] == b"7"
    assert sets[6] == {**BUILTIN_FIELDS, "ISCURRENT": "FALSE"}
    assert sets[7] == {**BUILTIN_FIELDS, "NAME": "Bauteile"}


@pytest.mark.windows
def test_problems_report_a_set_that_differs(lib: Path) -> None:
    assert patch_pcblib_layers(lib, _stack_with(builtin_layer_set(LayerMap()))) == []
    moved = _stack_with(builtin_layer_set(LayerMap(assembly="Mechanical 5")))
    assert pcblib_layer_problems(lib, moved) == ["Der Lagensatz „Component Layers“ weicht vom eingestellten ab."]
    assert patch_pcblib_layers(lib, moved) == []
    sets = _sets(_lib_text(lib))
    assert len(sets) == 6 and "Mechanical5" in sets[6]["LAYERS"].split(",")
    assert pcblib_layer_problems(lib, moved) == []


@pytest.mark.windows
def test_problems_report_a_set_that_is_not_the_current_one(tmp_path: Path) -> None:
    exact = set_segments(6, "Component Layers", BUILTIN_LAYERS, current=True)  # as wanted, but "&All Layers" current
    lib = synthetic_pcblib(tmp_path / "PF_TWO.PcbLib", header=header_with_sets(exact, current=1))
    stack = _stack_with(builtin_layer_set(LayerMap()))
    assert "Der Lagensatz „Component Layers“ ist beim Öffnen nicht der aktive." in pcblib_layer_problems(lib, stack)
    assert patch_pcblib_layers(lib, stack) == []
    assert _sets(_lib_text(lib))[1]["ISCURRENT"] == "FALSE"
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.windows
def test_mode_none_leaves_existing_sets_untouched(tmp_path: Path) -> None:
    own = set_segments(6, "Component Layers", ["TopLayer", "Mechanical9"], current=True)
    lib = synthetic_pcblib(tmp_path / "PF_OWN.PcbLib", header=header_with_sets(own, current=None))
    before = _sets(_lib_text(lib))
    stack, notes = _stack(_workspace(tmp_path))
    assert stack.layer_set is None and notes == []
    assert patch_pcblib_layers(lib, stack) == []
    text = _lib_text(lib)
    after = _sets(text)
    for index in (1, 5):  # the mechanical-layer patch rebuilds the lists of "&All Layers"/"&Mechanical Layers" only
        del before[index]["LAYERS"], after[index]["LAYERS"]
    assert after == before and _keys(text)[b"LAYERSETSCOUNT"] == b"6"
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.parametrize(
    ("header", "fragment"),
    [
        (rust_like_header(), "LAYERSETSCOUNT passt nicht zu den Lagensätzen im Kopf"),  # sets 1, 2, 5 of 3
        (header_with_sets().replace(b"LAYERSETSCOUNT=5", b"LAYERSETSCOUNT=4"), "LAYERSETSCOUNT passt nicht"),
        (header_with_sets().replace(b"LAYERSETSCOUNT=5", b"LAYERSETSCOUNT=X"), "LAYERSETSCOUNT ist keine Zahl"),
        (header_with_sets().replace(b"|LAYERSETSCOUNT=5", b""), "keine Lagensätze (LAYERSETSCOUNT) im Kopf"),
    ],
)
@pytest.mark.windows
def test_unexpected_set_block_leaves_the_library_untouched(tmp_path: Path, header: bytes, fragment: str) -> None:
    lib = synthetic_pcblib(tmp_path / "PF_ODD.PcbLib", header=header)
    digest = _sha(lib)
    warnings = patch_pcblib_layers(lib, _stack_with(builtin_layer_set(LayerMap())))
    assert len(warnings) == 1 and "unerwarteter Aufbau" in warnings[0] and fragment in warnings[0], warnings
    assert _sha(lib) == digest
    # without an own set the same header is patched (only appending needs a consistent set block)
    assert patch_pcblib_layers(lib, _stack_with(None)) == []


def test_plan_library_data_appends_the_set_without_file_access() -> None:
    data = library_data(header_with_sets())
    stack = _stack_with(builtin_layer_set(LayerMap()))
    planned = plan_library_data(data, EMPTY_KIND_MAPPING, stack)
    assert planned is not None
    text = _header_text(planned)
    assert _keys(text)[b"LAYERSETSCOUNT"] == b"6" and _sets(text)[6] == BUILTIN_FIELDS
    assert planned[4 + struct.unpack_from("<I", planned)[0] :] == data[4 + struct.unpack_from("<I", data)[0] :]
    assert plan_library_data(planned, EMPTY_KIND_MAPPING, stack) is None  # already as wanted
    with pytest.raises(stackup.HeaderStructureError, match="LAYERSETSCOUNT passt nicht"):
        plan_library_data(library_data(rust_like_header()), EMPTY_KIND_MAPPING, stack)


@pytest.mark.windows
@pytest.mark.parametrize("source", ["typed name", "layerset file"])
def test_set_name_outside_windows_1252_does_not_block_the_header_patch(tmp_path: Path, lib: Path, source: str) -> None:
    if source == "typed name":
        settings = LayerSetSettings(mode="builtin", name="Lagen Ω")
    else:
        file = tmp_path / "Lagen.layerset"
        file.write_bytes(b"LAYERSET1NAME=Lagen\x81satz|LAYERSET1LAYERS=TopLayer,Mechanical9")  # 0x81: no cp1252 char
        (parsed,) = parse_layerset_file(file)
        settings = LayerSetSettings(mode="file", file=str(file), **parsed.model_dump())
    ws = _workspace(tmp_path)
    ws.settings.layer_set = settings
    stack, _notes = _stack(ws)
    assert patch_pcblib_layers(lib, stack) == []
    assert pcblib_layer_problems(lib, stack) == []


@pytest.mark.rustwriter
def test_library_written_by_the_rust_writer_gets_the_set(tmp_path: Path) -> None:
    ws = _workspace(tmp_path, mode="builtin")
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    set_current(ws)
    try:
        result = RustLibraryOps(workspace=ws).write_library_full(lib, [chip_0603()])
    finally:
        set_current(None)
    assert result.ok and result.warnings == [], result
    text = _lib_text(lib)
    count = int(_keys(text)[b"LAYERSETSCOUNT"])
    sets = _sets(text)
    assert sorted(sets) == list(range(1, count + 1)) and sets[count] == BUILTIN_FIELDS
    assert [s["ISCURRENT"] for n, s in sorted(sets.items()) if n != count] == ["FALSE"] * (count - 1)
    assert pcblib_layer_problems(lib, _stack(ws)[0]) == []


# --------------------------------------------------------------------------- API


def _put_settings(client: TestClient, **changes: Any) -> Any:
    settings = client.get("/api/workspace").json()["settings"]
    settings.update(changes)
    return client.put("/api/workspace/settings", json=settings)


def _wait_job(client: TestClient, job: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"job {job['id']} did not finish")


def _no_writer(*_args: object, **_kwargs: object) -> NoReturn:
    raise WriterUnavailable("no library writer in this test")


def test_api_parses_a_layerset_file(client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "Lagensätze" / "Zwei.layerset"
    path.parent.mkdir()
    path.write_bytes(layerset_text(set_segments(6, "Component", COMPONENT_TOKENS),
                                   set_segments(7, "Bestückung", ["TopOverlay", "Mechanical9"], "MECHANICAL9",
                                                current=False, locked=True)).encode("cp1252"))
    response = client.post("/api/libraries/layer-set/parse", json={"path": f'  "{path}" '})
    assert response.status_code == 200
    assert response.json() == {
        "file": str(path),
        "sets": [
            {"name": "Component", "layers": COMPONENT_TOKENS, "active_layer": "TOP", "current": True,
             "locked": False, "flip_board": False},
            {"name": "Bestückung", "layers": ["TopOverlay", "Mechanical9"], "active_layer": "MECHANICAL9",
             "current": False, "locked": True, "flip_board": False},
        ],
    }


@pytest.mark.parametrize(
    ("name", "content", "fragment"),
    [
        ("Fehlt.layerset", None, "wurde nicht gefunden"),
        ("Bild.layerset", b"\x89PNG\r\n\x1a\n\x00\xff\xfe", "ist keine Altium-Lagensatz-Datei"),
        ("Leer.layerset", b"", "ist keine Altium-Lagensatz-Datei"),
        ("Falsch.layerset", b"LAYERSET1NAME=X|LAYERSET1LAYERS=TopLayer,Quatsch", "Unbekannte Lage „Quatsch“"),
    ],
)
def test_api_refuses_unusable_layerset_files(client: TestClient, tmp_path: Path, name: str, content: bytes | None,
                                             fragment: str) -> None:
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    response = client.post("/api/libraries/layer-set/parse", json={"path": str(path)})
    assert response.status_code == 400 and fragment in response.json()["detail"]


@pytest.mark.parametrize("path", ["Component.layerset", "", "   "])
def test_api_parse_needs_an_absolute_path(client: TestClient, path: str) -> None:
    response = client.post("/api/libraries/layer-set/parse", json={"path": path})
    assert response.status_code == 400
    assert response.json()["detail"] == "Bitte den absoluten Pfad einer .layerset-Datei angeben."


def test_api_builtin_set_for_a_posted_or_the_stored_layer_map(client: TestClient) -> None:
    posted = client.post("/api/libraries/layer-set/builtin",
                         json={"layers": LayerMap(assembly="Mechanical 5").model_dump(), "current": False})
    assert posted.status_code == 200
    assert posted.json() == builtin_layer_set(LayerMap(assembly="Mechanical 5"), current=False).model_dump()
    assert "Mechanical5" in posted.json()["layers"] and "Mechanical9" not in posted.json()["layers"]
    stored = client.post("/api/libraries/layer-set/builtin", json={})
    assert stored.status_code == 200 and stored.json()["layers"] == BUILTIN_LAYERS and stored.json()["current"] is True
    assert _put_settings(client, layers=LayerMap(courtyard="Mechanical 25").model_dump()).status_code == 200
    layers = client.post("/api/libraries/layer-set/builtin", json={}).json()["layers"]
    assert "Mechanical25" in layers and "Mechanical15" not in layers


def test_api_layer_set_endpoints_need_an_open_library(bare_client: TestClient, tmp_path: Path) -> None:
    assert bare_client.post("/api/libraries/layer-set/builtin", json={}).status_code == 409
    response = bare_client.post("/api/libraries/layer-set/parse", json={"path": str(tmp_path / "x.layerset")})
    assert response.status_code == 409


def test_api_settings_round_trip_the_layer_set(client: TestClient, workspace: Workspace, tmp_path: Path) -> None:
    assert client.get("/api/workspace").json()["settings"]["layer_set"] == LayerSetSettings().model_dump()
    from_file = {"mode": "file", "file": str(tmp_path / "Component.layerset"), "name": "Component",
                 "layers": COMPONENT_TOKENS, "active_layer": "TOP", "current": False, "locked": True,
                 "flip_board": False}
    response = _put_settings(client, layer_set=from_file)
    assert response.status_code == 200 and response.json()["settings"]["layer_set"] == from_file
    assert client.get("/api/workspace").json()["settings"]["layer_set"] == from_file
    saved = json.loads((workspace.root / "partforge.json").read_text(encoding="utf-8"))
    assert saved["layer_set"] == from_file
    stack = client.get("/api/libraries/layer-stack").json()
    assert stack["notes"] == []
    assert stack["stack"]["layer_set"] == {"name": "Component", "layers": COMPONENT_TOKENS, "active_layer": "TOP",
                                           "current": False, "locked": True, "flip_board": False}
    # builtin: a partial setting gets the defaults
    response = _put_settings(client, layer_set={"mode": "builtin", "name": "Bauteillagen"})
    assert response.status_code == 200
    assert response.json()["settings"]["layer_set"] == {**LayerSetSettings().model_dump(), "mode": "builtin",
                                                        "name": "Bauteillagen"}
    layer_set = client.get("/api/libraries/layer-stack").json()["stack"]["layer_set"]
    assert layer_set["name"] == "Bauteillagen" and layer_set["layers"] == BUILTIN_LAYERS


def test_api_settings_with_an_unusable_layer_set(client: TestClient) -> None:
    assert _put_settings(client, layer_set={"mode": "eigene"}).status_code == 422
    # an unusable definition is stored; the libraries then get no own set and a note
    assert _put_settings(client, layer_set={"mode": "file", "name": "Leer"}).status_code == 200
    stack = client.get("/api/libraries/layer-stack").json()
    assert stack["stack"]["layer_set"] is None
    assert stack["notes"] == ["Lagensatz nicht verwendet: Der Lagensatz „Leer“ enthält keine Lagen."]


@pytest.mark.windows
def test_api_layer_job_writes_the_set_from_the_settings(client: TestClient, workspace: Workspace,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    monkeypatch.setattr(sync, "get_writer", _no_writer)
    assert _put_settings(client, layer_set={"mode": "builtin"}).status_code == 200
    lib = synthetic_pcblib(workspace.footprints_dir / "PF_CHIP.PcbLib", header=header_with_sets())
    snap = _wait_job(client, client.post("/api/libraries/layer-stack/apply").json()["job"])
    assert snap["status"] == "done" and snap["result"]["patched"] == [str(lib)], snap
    sets = _sets(_lib_text(lib))
    assert sets[6] == BUILTIN_FIELDS and sets[1]["ISCURRENT"] == "FALSE"
    again = _wait_job(client, client.post("/api/libraries/layer-stack/apply").json()["job"])
    assert again["result"]["patched"] == [] and again["result"]["unchanged"] == [str(lib)]


def test_layerset_file_with_utf8_bom(tmp_path: Path) -> None:
    """Altium writes ANSI; a file an editor saved as UTF-8 with BOM keeps its first set and its umlauts."""
    file = tmp_path / "Bom.layerset"
    file.write_bytes(b"\xef\xbb\xbf" + "LAYERSET1NAME=Bestückung|LAYERSET1LAYERS=TopLayer,Mechanical9".encode("utf-8"))
    (parsed,) = parse_layerset_file(file)
    assert parsed.name == "Bestückung" and parsed.layers == ["TopLayer", "Mechanical9"]
