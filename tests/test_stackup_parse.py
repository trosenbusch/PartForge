"""Altium .stackup parsing, the built-in standard stack and the LayerMap suggestions."""
from __future__ import annotations

from pathlib import Path

import pytest

from partforge.altium import stackup
from partforge.altium.stackup import (
    LayerStack,
    MechLayer,
    StackupError,
    default_stack,
    effective_stack,
    layer_map_issues,
    parse_stackup,
    parse_stackup_text,
    suggest_layer_map,
    workspace_stack,
)
from partforge.workspace import LayerMap, Workspace

USER_STACK = Path(r"C:\PartForge-Examples\Altium_Templates\Mechanical_Stackup_Standard\mechanical_layer.stackup")
BASE = 0x01020000


def v8_layer(index: int, number: int, name: str, kind: str | None = None, enabled: bool = True) -> str:
    """One mechanical layer in the user's .stackup format (incl. the substack context keys)."""
    parts = [
        f"LAYER_V8_{index}_{{F6855C8C-AA1C-4BB7-A452-3C83D4E3C71F}}CONTEXT=0",
        f"LAYER_V8_{index}ID={{00000000-0000-0000-0000-{index:012d}}}",
        f"LAYER_V8_{index}NAME={name}",
        f"LAYER_V8_{index}LAYERID={BASE + number}",
        f"LAYER_V8_{index}USEDBYPRIMS=FALSE",
        f"LAYER_V8_{index}MECHENABLED={'TRUE' if enabled else 'FALSE'}",
    ]
    if kind:
        parts.append(f"LAYER_V8_{index}MECHKIND={kind}")
    return "|".join(parts)


def stack_text(*layers: str, pairs: str = "") -> str:
    head = "STACKUPVERSION=1|DISPLAYUNIT=1|LAYERMASTERSTACK_V8NAME=Master layer stack"
    copper = "LAYER_V8_3NAME=Top Layer|LAYER_V8_3LAYERID=16777217|LAYER_V8_3COPTHICK=1.378mil"
    body = "|".join([head, copper, *layers])
    return body + (f"|{pairs}" if pairs else "") + "\x00"


# --------------------------------------------------------------------------- parsing


def test_parse_user_format_layers_kinds_enabled_and_pairs():
    text = stack_text(
        v8_layer(11, 1, "Board Shape", "BoardShape"),
        v8_layer(19, 9, "Top Assembly", "AssemblyTop"),
        v8_layer(20, 10, "Bottom Assembly", "AssemblyBottom"),
        v8_layer(14, 4, "Hole Detail"),
        v8_layer(55, 32, "Mechanical 32", enabled=False),
        v8_layer(70, 49, "Top PSA (Pressure Sensitive Adhesive)"),
        pairs="MECHPAIR0L1=MECHANICAL9|MECHPAIR0L2=MECHANICAL10|MECHPAIR1L1=MECHANICAL49|MECHPAIR1L2=MECHANICAL50",
    )
    stack = parse_stackup_text(text, source="x.stackup", name="x")
    assert sorted(stack.layers) == [1, 4, 9, 10, 32, 49]
    assert stack.layers[9] == MechLayer(number=9, name="Top Assembly", kind="AssemblyTop", enabled=True)
    assert stack.layers[4].kind is None and stack.layers[4].enabled
    assert not stack.layers[32].enabled
    assert stack.pairs == [(9, 10), (49, 50)]  # trailing NUL of the file is ignored
    assert stack.header_pairs() == [(9, 10)]  # Mechanical 49/50 are not in a PcbLib header
    assert stack.source == "x.stackup"


def test_parse_ignores_copper_layers_invalid_kinds_and_bad_pairs():
    text = stack_text(
        v8_layer(19, 9, "Top Assembly", "Assembly Top!"),
        pairs="MECHPAIR0L1=MECHANICAL9|MECHPAIR0L2=MECHANICAL9|MECHPAIR1L1=TOPLAYER|MECHPAIR1L2=MECHANICAL3",
    )
    stack = parse_stackup_text(text)
    assert list(stack.layers) == [9]
    assert stack.layers[9].kind is None  # not a valid MECHKIND token
    assert stack.pairs == []


def test_parse_prefers_v9_cache_over_v8_and_legacy():
    text = "|".join(
        [
            f"V9_CACHE_LAYER77_NAME=From V9|V9_CACHE_LAYER77_LAYERID={BASE + 9}|V9_CACHE_LAYER77_MECHENABLED=TRUE",
            v8_layer(19, 9, "From V8", "AssemblyTop"),
            "LAYER65NAME=From legacy|LAYER65MECHENABLED=TRUE",
            "LAYER66NAME=Legacy only|LAYER66MECHENABLED=TRUE|LAYER66MECHKIND=AssemblyBottom",
        ]
    )
    stack = parse_stackup_text(text)
    assert stack.layers[9].name == "From V9" and stack.layers[9].kind is None
    assert stack.layers[10] == MechLayer(number=10, name="Legacy only", kind="AssemblyBottom", enabled=True)


def test_parse_without_mechanical_layers_raises():
    with pytest.raises(StackupError, match="keine Mechanik-Lagen"):
        parse_stackup_text("STACKUPVERSION=1|LAYER_V8_3NAME=Top Layer|LAYER_V8_3LAYERID=16777217")


def test_parse_stackup_file_errors(tmp_path: Path):
    with pytest.raises(StackupError, match="nicht gefunden"):
        parse_stackup(tmp_path / "missing.stackup")
    garbage = tmp_path / "garbage.stackup"
    garbage.write_bytes(b"\x00\x01binary")
    with pytest.raises(StackupError, match="keine Altium-Lagen-Datei"):
        parse_stackup(garbage)


def test_parse_stackup_file_cp1252(tmp_path: Path):
    path = tmp_path / "eigen.stackup"
    path.write_bytes(stack_text(v8_layer(19, 9, "Bestückung oben", "AssemblyTop")).encode("cp1252"))
    stack = parse_stackup(path)
    assert stack.layers[9].name == "Bestückung oben" and stack.name == "eigen"


@pytest.mark.skipif(not USER_STACK.is_file(), reason="Standard-Lagenaufbau des Benutzers nicht vorhanden")
def test_builtin_default_equals_the_users_standard_file():
    parsed = parse_stackup(USER_STACK)  # read-only
    builtin = default_stack()
    assert parsed.layers == builtin.layers
    assert parsed.pairs == builtin.pairs


def test_default_stack_is_a_fresh_copy():
    a = default_stack()
    a.layers[9].name = "changed"
    assert default_stack().layers[9].name == "Top Assembly"


# --------------------------------------------------------------------------- layer map


def test_suggest_layer_map_from_default_matches_the_workspace_defaults():
    assert suggest_layer_map(default_stack()) == LayerMap()


def test_suggest_layer_map_by_kinds():
    stack = LayerStack(
        layers={
            5: MechLayer(number=5, name="Top Assembly", kind="AssemblyTop"),
            7: MechLayer(number=7, name="Top Value", kind="ValueTop"),
            2: MechLayer(number=2, name="Top Designator", kind="DesignatorTop", enabled=False),
            12: MechLayer(number=12, name="Top Designator 2", kind="DesignatorTop"),
            40: MechLayer(number=40, name="Far", kind="CourtyardTop"),
        }
    )
    base = LayerMap(courtyard="Mechanical 15")
    suggested = suggest_layer_map(stack, base)
    assert suggested.assembly == "Mechanical 5"
    assert suggested.comment == "Mechanical 7"
    assert suggested.designator == "Mechanical 12"  # the enabled layer wins
    assert suggested.courtyard == "Mechanical 15"  # Mechanical 40 cannot be written -> base value
    assert suggested.silkscreen == "Top Overlay"


def test_layer_map_issues():
    stack = default_stack()
    assert layer_map_issues(stack, LayerMap()) == []
    stack.layers[15] = stack.layers[15].model_copy(update={"enabled": False})
    lm = LayerMap(assembly="Mechanical 13", designator="Mechanical 33", comment="Mechanical 21")
    issues = layer_map_issues(stack, lm)
    text = "\n".join(issues)
    assert "Mechanical 13 ist im Lagenaufbau „Top 3D Body“ (Typ 3DBodyTop), erwartet wird Typ AssemblyTop" in text
    assert "Mechanical 15 (Top Courtyard) ist im Lagenaufbau deaktiviert" in text
    assert "Mechanical 13 trägt mehrere Rollen" in text
    assert "Mechanical 21 trägt mehrere Rollen" in text


def test_layer_map_issue_for_undefined_layer():
    stack = LayerStack(layers={1: MechLayer(number=1, name="Board")})
    issues = layer_map_issues(stack, LayerMap())
    assert any("Mechanical 9 ist im Lagenaufbau nicht definiert" in i for i in issues)


def test_effective_stack_enables_and_names_layer_map_layers():
    stack = LayerStack(
        layers={
            9: MechLayer(number=9, name="Top Assembly", kind="AssemblyTop", enabled=False),
            13: MechLayer(number=13, name="Top 3D Body", kind="3DBodyTop"),
        }
    )
    eff = effective_stack(stack, LayerMap())
    assert eff.layers[9].enabled  # was disabled
    assert eff.layers[11] == MechLayer(number=11, name="Top Designator", kind="DesignatorTop")
    assert eff.layers[17].name == "Top Component Center" and eff.layers[17].kind == "ComponentCenterTop"
    assert not stack.layers[9].enabled  # the input is not modified
    # a role on a layer whose kind another layer already has: name only, no duplicate kind
    eff2 = effective_stack(stack, LayerMap(assembly="Mechanical 20"))
    assert eff2.layers[20].kind is None and eff2.layers[20].name == "Top Assembly"


def test_header_layers_fill_undefined_layers():
    stack = LayerStack(layers={9: MechLayer(number=9, name="A")})
    header = stack.header_layers()
    assert len(header) == 32 and header[9].name == "A"
    assert header[2] == MechLayer(number=2, name="Mechanical 2", enabled=False)


# --------------------------------------------------------------------------- workspace


def test_workspace_stack_default_file_and_fallback(tmp_path: Path):
    ws = Workspace.create(tmp_path / "W", name="w")
    stack, notes = workspace_stack(ws)
    assert notes == [] and stack.source == "builtin"
    (ws.root / "own.stackup").write_text(stack_text(v8_layer(19, 9, "Own Assembly", "AssemblyTop")), encoding="ascii")
    ws.settings.layer_stackup = "own.stackup"  # workspace-relative
    stack, notes = workspace_stack(ws)
    assert notes == [] and stack.layers[9].name == "Own Assembly"
    ws.settings.layer_stackup = str(tmp_path / "gone.stackup")
    stack, notes = workspace_stack(ws)
    assert stack.source == "builtin" and len(notes) == 1 and "nicht lesbar" in notes[0]
    assert workspace_stack(None)[0].source == "builtin"


def test_workspace_stack_cache_sees_changes(tmp_path: Path):
    ws = Workspace.create(tmp_path / "W", name="w")
    file = ws.root / "s.stackup"
    file.write_text(stack_text(v8_layer(19, 9, "First", "AssemblyTop")), encoding="ascii")
    ws.settings.layer_stackup = str(file)
    assert workspace_stack(ws)[0].layers[9].name == "First"
    file.write_text(stack_text(v8_layer(19, 9, "Second name", "AssemblyTop")), encoding="ascii")
    assert workspace_stack(ws)[0].layers[9].name == "Second name"


def test_header_patch_switch(monkeypatch):
    monkeypatch.delenv(stackup.PATCH_ENV, raising=False)
    assert stackup.header_patch_enabled()
    monkeypatch.setenv(stackup.PATCH_ENV, "0")
    assert not stackup.header_patch_enabled()
    monkeypatch.delenv(stackup.PATCH_ENV)
    monkeypatch.setattr(stackup, "HEADER_PATCH_ENABLED", False)
    assert not stackup.header_patch_enabled()
