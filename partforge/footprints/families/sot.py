"""Small-outline transistors with gull-wing leads: SOT-23 (3/5/6), SC-70 (SOT-323/353/363), SOT-523.

Pin layout (pin 1 upper left, counter-clockwise):
* 3 pins: 1 (left, +e), 2 (left, -e), 3 (right, 0)
* 5 pins: 1/2/3 left (top→bottom), 4 right bottom, 5 right top
* 6 pins: 1/2/3 left, 4/5/6 right (bottom→top)
Tables 3-2 (pitch > 0.625) / 3-3 (pitch ≤ 0.625, SOT-523).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..geom import rect_centered
from ..ipc7351 import gullwing_table
from ..models import FamilyInfo, Preset, Tol
from ..params import ParamError, nom
from .base import (
    COMMON_SMD,
    NAMING_PARAMS,
    FamilyDef,
    GenContext,
    check_row_fits_body,
    describe,
    differs_from,
    dot_above,
    dot_corner,
    ic_silk,
    p_enum,
    p_float,
    p_tol,
)

_DIMS = ("E", "E1", "D", "L", "b", "A", "A1", "c")
PITCH_HINT = ("Ist e im Datenblatt der Abstand der äußeren Anschlüsse (Nexperia/NXP: e, Raster = e1)? "
              "Dann das Raster (halber Wert) als e angeben.")


@dataclass(frozen=True)
class SotVariant:
    key: str
    pins_options: tuple[str, ...]
    pitch: float
    names: Mapping[int, str]  # pins -> package name
    presets: tuple[Preset, ...]
    label: str
    description: str


def _preset(key: str, label: str, source: str, pins: int, pitch: float, dims: Mapping[str, tuple[float, float]]
            ) -> Preset:
    return Preset(key=key, label=label, source=source,
                  params={"pins": str(pins), "e": pitch,
                          **{k: {"min": v[0], "max": v[1]} for k, v in dims.items()}})


SOT23 = SotVariant(
    key="sot23",
    pins_options=("3", "5", "6"),
    pitch=0.95,
    names={3: "SOT-23-3", 5: "SOT-23-5", 6: "SOT-23-6"},
    label="SOT-23 (3/5/6 Pins)",
    description="SOT-23-Familie mit 0,95 mm Raster (TO-236, MO-178).",
    presets=(
        _preset("SOT-23-3", "SOT-23-3 (JEDEC TO-236AB)", "KiCad sot.yaml (JEDEC TO-236 Var. AB)", 3, 0.95,
                {"E": (2.10, 2.64), "E1": (1.20, 1.40), "D": (2.80, 3.04), "L": (0.40, 0.60), "b": (0.30, 0.50),
                 "A": (0.89, 1.12), "A1": (0.01, 0.10), "c": (0.08, 0.20)}),
        _preset("SOT-23-3-Nexperia", "SOT-23-3 (Nexperia SOT23)", "Nexperia SOT23", 3, 0.95,
                {"E": (2.1, 2.5), "E1": (1.2, 1.4), "D": (2.8, 3.0), "L": (0.15, 0.45), "b": (0.38, 0.48),
                 "A": (0.9, 1.1), "A1": (0.0, 0.1), "c": (0.09, 0.15)}),
        _preset("SOT-23-5", "SOT-23-5 (JEDEC MO-178, TI DBV)", "TI DBV0005A / JEDEC MO-178", 5, 0.95,
                {"E": (2.60, 3.00), "E1": (1.45, 1.75), "D": (2.75, 3.05), "L": (0.30, 0.60), "b": (0.30, 0.50),
                 "A": (0.90, 1.45), "A1": (0.0, 0.15), "c": (0.08, 0.22)}),
        _preset("SOT-23-6", "SOT-23-6 (JEDEC MO-178, Diodes SOT26)", "Diodes Inc. SOT26", 6, 0.95,
                {"E": (2.70, 3.00), "E1": (1.50, 1.70), "D": (2.90, 3.10), "L": (0.35, 0.55), "b": (0.35, 0.50),
                 "A": (1.00, 1.30), "A1": (0.013, 0.10), "c": (0.10, 0.20)}),
    ),
)

SC70 = SotVariant(
    key="sc70",
    pins_options=("3", "5", "6"),
    pitch=0.65,
    names={3: "SOT-323", 5: "SOT-353", 6: "SOT-363"},
    label="SC-70 (SOT-323/353/363)",
    description="SC-70-Familie mit 0,65 mm Raster.",
    presets=(
        _preset("SOT-323", "SOT-323 / SC-70-3 (Nexperia)", "Nexperia SOT323", 3, 0.65,
                {"E": (2.0, 2.2), "E1": (1.15, 1.35), "D": (1.8, 2.2), "L": (0.15, 0.45), "b": (0.3, 0.4),
                 "A": (0.8, 1.1), "A1": (0.0, 0.1), "c": (0.10, 0.25)}),
        _preset("SOT-353", "SOT-353 / SC-70-5", "wie Nexperia SOT363 (typisch)", 5, 0.65,
                {"E": (2.0, 2.2), "E1": (1.15, 1.35), "D": (1.8, 2.2), "L": (0.15, 0.45), "b": (0.15, 0.30),
                 "A": (0.8, 1.1), "A1": (0.0, 0.1), "c": (0.10, 0.25)}),
        _preset("SOT-363", "SOT-363 / SC-70-6 (Nexperia)", "Nexperia SOT363", 6, 0.65,
                {"E": (2.0, 2.2), "E1": (1.15, 1.35), "D": (1.8, 2.2), "L": (0.15, 0.45), "b": (0.20, 0.30),
                 "A": (0.8, 1.1), "A1": (0.0, 0.1), "c": (0.10, 0.25)}),
    ),
)

SOT523 = SotVariant(
    key="sot523",
    pins_options=("3",),
    pitch=0.50,
    names={3: "SOT-523"},
    label="SOT-523 / SC-75",
    description="SOT-523 (SC-75, SOT-416) mit 0,5 mm Raster.",
    presets=(
        _preset("SOT-523", "SOT-523 (Diodes)", "Diodes Inc. SOT523", 3, 0.50,
                {"E": (1.45, 1.75), "E1": (0.75, 0.85), "D": (1.50, 1.70), "L": (0.20, 0.40), "b": (0.15, 0.30),
                 "A": (0.70, 0.90), "A1": (0.0, 0.10), "c": (0.10, 0.20)}),
        _preset("SC-75", "SC-75 / SOT-416 (Nexperia)", "Nexperia SOT416", 3, 0.50,
                {"E": (1.45, 1.75), "E1": (0.7, 0.9), "D": (1.4, 1.8), "L": (0.15, 0.45), "b": (0.15, 0.30),
                 "A": (0.6, 0.9), "A1": (0.0, 0.1), "c": (0.10, 0.20)}),
    ),
)


def _params(v: SotVariant) -> list:
    return [
        p_enum("pins", "Anzahl Anschlüsse", list(v.pins_options), default=v.pins_options[0], group="Anschlüsse"),
        p_float("e", "Raster e", default=v.pitch, minimum=0.3, maximum=2.0, group="Anschlüsse"),
        p_tol("E", "Gesamtbreite E", help="Spannweite über die Anschlussspitzen (Nexperia: HE)."),
        p_tol("E1", "Körperbreite E1", help="Breite des Kunststoffkörpers (Nexperia: E)."),
        p_tol("D", "Körperlänge D"),
        p_tol("L", "Fußlänge L", group="Anschlüsse", help="Auflagelänge (Nexperia: Lp)."),
        p_tol("b", "Anschlussbreite b", group="Anschlüsse"),
        p_tol("A", "Bauhöhe A"),
        p_tol("A1", "Abstand A1", default={"min": 0.0, "max": 0.1}, help="Abstand Körperunterseite – Platine."),
        p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.08, "max": 0.2}),
        *NAMING_PARAMS,
        *COMMON_SMD,
    ]


def _layout(pins: int, e: float) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """(left pads, right pads) as (designator, y)."""
    if pins == 3:
        return [("1", e), ("2", -e)], [("3", 0.0)]
    if pins == 5:
        return [("1", e), ("2", 0.0), ("3", -e)], [("4", -e), ("5", e)]
    if pins == 6:
        return [("1", e), ("2", 0.0), ("3", -e)], [("4", -e), ("5", 0.0), ("6", e)]
    raise ParamError(f"{pins} Anschlüsse werden für SOT-Gehäuse nicht unterstützt (3, 5 oder 6).", params=("pins",))


def _builder(v: SotVariant) -> Callable[[GenContext], FootprintSpec]:
    def build(ctx: GenContext) -> FootprintSpec:
        p = ctx.p
        pins = int(p.enum("pins", v.pins_options[0]))
        e = p.float("e", v.pitch)
        defaults = next((pr.params for pr in v.presets if int(pr.params["pins"]) == pins), v.presets[0].params)

        def dim(name: str) -> Tol:
            d = defaults[name]
            return p.tol_or(name, Tol(min=d["min"], max=d["max"]))

        E, E1, D, L, b_, A, A1, c = (dim(n) for n in _DIMS)  # noqa: N806
        if E1.max >= E.min:
            raise ValueError("Körperbreite E1 muss kleiner als die Gesamtbreite E sein "
                             "(Hinweis: bei Nexperia heißt die Gesamtbreite HE und die Körperbreite E).")
        package = v.names.get(pins, f"{v.key.upper()}-{pins}")
        # all variants: three lead positions (+e, 0, -e) on the pin-1 side
        check_row_fits_body(ctx, pitch=e, positions=3, lead_width=b_, body=D, package=package, hint=PITCH_HINT)
        base = {k: (defaults[k]["min"], defaults[k]["max"]) for k in _DIMS}
        custom = differs_from(base, {"E": E, "E1": E1, "D": D, "L": L, "b": b_, "A": A})
        table = gullwing_table(e)
        land = ctx.ipc_land(E, L, b_, table, label="Anschlüsse")
        pitch_rows = e if pins > 3 else 2 * e
        ctx.finalize_land(land, pitch=pitch_rows)

        b = ctx.builder()
        left, right = _layout(pins, e)
        c_ = land.pad_center
        pad1 = None
        for des, y in left:
            pad = b.smd_pad(des, -c_, y, land.pad_length, land.x)
            pad1 = pad1 or pad
        for des, y in right:
            b.smd_pad(des, c_, y, land.pad_length, land.x)
        en, e1n, dn = nom(E), nom(E1), nom(D)
        body = b.body(rect_centered(0, 0, e1n, dn))
        assert pad1 is not None
        ic_silk(b, body, [dot_above(b, pad1), dot_corner(b, body)], push=(0.0, 1.0))
        b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

        h, a1, cn, bn, ln = A.max, nom(A1), nom(c), nom(b_), nom(L)
        b.box("Body", body, max(a1, cn), h, IC_BODY)
        for pad in b.pads:
            sign = -1.0 if pad.x < 0 else 1.0
            x_in, x_out = sign * (e1n / 2 - 0.05), sign * en / 2
            b.box(f"Lead {pad.designator}", (min(x_in, x_out), pad.y - bn / 2, max(x_in, x_out), pad.y + bn / 2),
                  0.0, cn, TIN)
            x_foot = sign * (en / 2 - ln)
            b.box(f"Lead {pad.designator} leg", (min(x_in, x_foot), pad.y - bn / 2, max(x_in, x_foot),
                                                 pad.y + bn / 2), cn, max(a1, cn) + 0.35 * (h - max(a1, cn)), TIN)

        ipc_name = naming.ipc_pitch_span("SOT", e, en, h, pins, ctx.density)
        house_name = naming.house(package + (f" {naming.house_body(e1n, dn)}" if custom else ""), ctx.density,
                                  manufacturer=p.text("manufacturer"), code=p.text("package_code"))
        description = describe(package.replace("-", ""), pins, dn, e1n, ctx.density, pitch=e)
        return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                          package=package + (" (angepasst)" if custom else ""), height=h, courtyard_table=table)

    return build


def _family(v: SotVariant, group: str, aliases: tuple[str, ...],
            alias_params: Mapping[str, Mapping[str, str]]) -> FamilyDef:
    info = FamilyInfo(key=v.key, label=v.label, group=group, description=v.description, params=_params(v),
                      presets=list(v.presets), ipc_table="3-2" if v.pitch >= 0.625 else "3-3")
    return FamilyDef(info, _builder(v), aliases=aliases, alias_params=alias_params,
                     free_params=frozenset({"A1", "c"}), max_only=frozenset({"A"}))


GROUP = "Transistoren (SOT/TO)"
_P3, _P5, _P6 = {"pins": "3"}, {"pins": "5"}, {"pins": "6"}
FAMILIES = [
    _family(SOT23, GROUP, ("sot-23",), {
        "sot23-3": _P3, "to236": _P3, "to236ab": _P3, "sot23-5": _P5, "sot25": _P5, "mo178": _P5, "sc74a": _P5,
        "sot753": _P5, "sot23-6": _P6, "sot26": _P6, "sc74": _P6, "sot457": _P6}),
    _family(SC70, GROUP, ("sc-70",), {
        "sot323": _P3, "sc70-3": _P3, "sot353": _P5, "sc70-5": _P5, "sc88a": _P5, "sot363": _P6, "sc70-6": _P6,
        "sc88": _P6}),
    _family(SOT523, GROUP, ("sot-523", "sc89"), {"sc75": {"preset": "SC-75"}, "sot416": {"preset": "SC-75"}}),
]
