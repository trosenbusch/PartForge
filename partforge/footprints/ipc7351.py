"""IPC-7351B land-pattern mathematics (pure functions, no geometry building).

Model (IPC-7351B §3.1.5, see docs/entwicklung/recherche/ipc-footprints.md §1)::

    Zmax = Lmin + 2*JT + sqrt(CL² + F² + P²)        outer land extent (toe to toe)
    Gmin = Smax - 2*JH - sqrt(CS² + F² + P²)        inner gap between opposite lands
    Xmax = Wmin + 2*JS + sqrt(CW² + F² + P²)        land width

* ``L`` outer terminal span, ``T`` terminal (foot) length, ``W`` terminal width,
  ``S = L - 2T`` inner span with the IPC-7351B RMS treatment (§1.2).
* ``F`` fabrication and ``P`` placement tolerance (totals, style defaults 0.10 / 0.05).
* J values (toe/heel/side/courtyard excess) per lead family and density M/N/L (§2).
  Convention: *toe* always acts on Z, *heel* on G (tables 3-4/3-8/3-13 are stored swapped).
* Rounding: ``"kicad"`` = nearest 0.05 mm (0.02 mm for chips smaller than 0603,
  0.01 mm for the IPC-7352 tantalum table), Python round-half-even like the KiCad
  generator; ``"ipc"`` = nearest 0.01 mm.

The functions reproduce the reference implementation
``docs/entwicklung/recherche/ipc-work/ipc7351b_ref.py`` bit for bit (same order of
floating point operations), which in turn reproduces 13 published KiCad footprints.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from .models import Tol

Density = Literal["M", "N", "L"]
RoundingMode = Literal["kicad", "ipc"]
DENSITIES: tuple[Density, ...] = ("M", "N", "L")

DENSITY_LABELS: dict[str, str] = {  # one wording in the whole UI: Klein (L) · Nominal (N) · Groß (M)
    "L": "Klein (L) – IPC Level C, hohe Bestückungsdichte",
    "N": "Nominal (N) – IPC Level B, mittlere Bestückungsdichte",
    "M": "Groß (M) – IPC Level A, geringe Bestückungsdichte",
}
DENSITY_WIZARD_TEXT: dict[str, str] = {  # Altium IPC wizard wording used in descriptions
    "M": "IPC Low Density",
    "N": "IPC Medium Density",
    "L": "IPC High Density",
}
THT_LEVEL: dict[str, str] = {"M": "A", "N": "B", "L": "C"}  # IPC-2222 producibility level

DEFAULT_MIN_COPPER_GAP = 0.15  # mm, minimum copper gap between adjacent lands (clamp)
DEFAULT_EP_CLEARANCE = 0.20  # mm, exposed pad to signal pad (TI SLUA271, KiCad)
DEFAULT_COURTYARD_GRID = 0.05  # mm, house style (TR_* libraries): courtyard rounded up to 0.05 mm
_EPS = 1e-9


# --------------------------------------------------------------------------- J tables


@dataclass(frozen=True)
class Fillet:
    """Fillet goals of one density: toe (acts on Z), heel (acts on G), side (acts on X)."""

    toe: float
    heel: float
    side: float
    courtyard: float


@dataclass(frozen=True)
class JTable:
    key: str
    table: str  # IPC table number, e.g. "3-5"
    title: str  # English table title
    label: str  # German label for the UI
    values: Mapping[str, Fillet]
    kicad_round: float = 0.05  # round-off base in "kicad" mode
    standard: str = "IPC-7351B"


def _fillets(m: tuple[float, float, float, float], n: tuple[float, float, float, float],
             l: tuple[float, float, float, float]) -> dict[str, Fillet]:  # noqa: E741
    return {"M": Fillet(*m), "N": Fillet(*n), "L": Fillet(*l)}


_GULLWING = _fillets((0.55, 0.45, 0.05, 0.50), (0.35, 0.35, 0.03, 0.25), (0.15, 0.25, 0.01, 0.10))
_QFN = _fillets((0.40, 0.00, -0.04, 0.50), (0.30, 0.00, -0.04, 0.25), (0.20, 0.00, -0.04, 0.10))

J_TABLES: dict[str, JTable] = {
    t.key: t
    for t in (
        JTable("gullwing", "3-2", "Flat ribbon L and gull-wing leads (pitch > 0.625 mm)",
               "Gull-Wing-/L-Anschlüsse, Raster > 0,625 mm", _GULLWING),
        JTable("gullwing_fine", "3-3", "Flat ribbon L and gull-wing leads (pitch <= 0.625 mm)",
               "Gull-Wing-/L-Anschlüsse, Raster ≤ 0,625 mm",
               _fillets((0.55, 0.45, 0.01, 0.50), (0.35, 0.35, -0.02, 0.25), (0.15, 0.25, -0.04, 0.10))),
        JTable("jlead", "3-4", "J leads", "J-Anschlüsse",
               _fillets((0.55, 0.10, 0.05, 0.50), (0.35, 0.00, 0.03, 0.25), (0.15, -0.10, 0.01, 0.10))),
        JTable("chip", "3-5", "Rectangular or square-end components >= 0603 (1608)",
               "Chip-Bauteile ab 0603 (1608)",
               _fillets((0.55, 0.00, 0.05, 0.50), (0.35, 0.00, 0.00, 0.25), (0.15, 0.00, -0.05, 0.10))),
        JTable("chip_small", "3-6", "Rectangular or square-end components < 0603 (1608)",
               "Chip-Bauteile kleiner 0603 (1608)",
               _fillets((0.30, 0.00, 0.05, 0.20), (0.20, 0.00, 0.00, 0.15), (0.10, 0.00, -0.05, 0.10)),
               kicad_round=0.02),
        JTable("melf", "3-7", "Cylindrical end cap terminations (MELF)", "Zylindrische Endkappen (MELF)",
               _fillets((0.60, 0.20, 0.10, 0.50), (0.40, 0.10, 0.05, 0.25), (0.20, 0.02, 0.01, 0.10))),
        JTable("castellated", "3-8", "Castellated terminations (LCC)", "Castellated-Anschlüsse (LCC)",
               _fillets((0.65, 0.25, 0.05, 0.50), (0.55, 0.15, -0.05, 0.25), (0.45, 0.05, -0.15, 0.10))),
        JTable("chip_array", "3-9…3-11", "Chip arrays (concave, convex, flat)", "Chip-Arrays",
               _fillets((0.55, -0.05, -0.05, 0.50), (0.45, -0.07, -0.07, 0.25), (0.35, -0.10, -0.10, 0.10))),
        JTable("butt", "3-12", "Butt joints", "Stumpfstoß-Anschlüsse",
               _fillets((1.00, 1.00, 0.30, 1.50), (0.80, 0.80, 0.20, 0.80), (0.60, 0.60, 0.10, 0.20))),
        JTable("inward_l", "3-13", "Inward formed L-shaped ribbon leads (molded bodies)",
               "Nach innen gebogene L-Anschlüsse (Molded, SMA/SMB/SMC, Tantal)",
               _fillets((0.80, 0.25, 0.01, 0.50), (0.50, 0.15, -0.05, 0.25), (0.20, 0.07, -0.10, 0.10))),
        JTable("flat_lug", "3-14", "Flat lug leads (power tabs)", "Flache Laschen (Kühlfahnen)", _GULLWING),
        JTable("qfn", "3-15", "Quad flat no-lead (QFN)", "QFN (ohne Anschlussbeinchen)", _QFN),
        JTable("son", "3-16", "Small outline no-lead (SON/DFN)", "SON/DFN (ohne Anschlussbeinchen)", _QFN),
        JTable("pullback", "3-18", "Pull-back no-lead packages", "Pull-back-QFN/SON",
               _fillets((0.05, 0.05, 0.05, 0.50), (0.00, 0.00, 0.00, 0.25), (-0.05, -0.05, -0.05, 0.10))),
        JTable("flat_lead", "3-22", "Small outline flat leads (SODFL/SOTFL)", "Flache Anschlüsse (SOD-F, SOT-89)",
               _fillets((0.30, 0.00, 0.05, 0.20), (0.20, 0.00, 0.00, 0.15), (0.10, 0.00, -0.05, 0.10))),
        JTable("inward_l_7352", "IPC-7352 inward L", "Inward L leads per IPC-7352 (KiCad tantalum)",
               "Nach innen gebogene L-Anschlüsse nach IPC-7352 (wie KiCad)",
               _fillets((0.55, 0.10, 0.05, 0.50), (0.35, 0.00, 0.03, 0.25), (0.15, 0.00, 0.01, 0.10)),
               kicad_round=0.01, standard="IPC-7352"),
    )
}

#: ``LandCalc.table_title`` of a manufacturer-recommended land pattern (no J table).
MANUFACTURER_TABLE_TITLE = "Herstellerempfehlung (Land Pattern)"

BGA_COURTYARD: dict[str, float] = {"M": 2.0, "N": 1.0, "L": 0.5}  # IPC-7351B table 3-17
THT_COURTYARD: dict[str, float] = {"M": 0.50, "N": 0.25, "L": 0.10}

# BGA lands (IPC-7351B tables 14-5 / 14-6): ball nominal -> (land nominal, land max (MMC), land min)
BGA_COLLAPSIBLE: dict[float, tuple[float, float, float]] = {
    0.75: (0.55, 0.60, 0.50), 0.65: (0.50, 0.55, 0.45), 0.60: (0.45, 0.50, 0.40), 0.55: (0.40, 0.45, 0.35),
    0.50: (0.40, 0.45, 0.35), 0.45: (0.35, 0.40, 0.30), 0.40: (0.30, 0.35, 0.25), 0.35: (0.30, 0.35, 0.25),
    0.30: (0.25, 0.25, 0.20), 0.25: (0.20, 0.20, 0.17), 0.20: (0.17, 0.20, 0.14), 0.17: (0.15, 0.18, 0.12),
    0.15: (0.13, 0.15, 0.10),
}
BGA_NON_COLLAPSIBLE: dict[float, tuple[float, float, float]] = {
    0.75: (0.85, 0.90, 0.80), 0.65: (0.75, 0.80, 0.70), 0.60: (0.70, 0.75, 0.65), 0.55: (0.65, 0.70, 0.60),
    0.50: (0.55, 0.60, 0.50), 0.45: (0.50, 0.55, 0.45), 0.40: (0.45, 0.50, 0.40), 0.35: (0.40, 0.45, 0.35),
    0.30: (0.35, 0.40, 0.30), 0.25: (0.30, 0.35, 0.25), 0.20: (0.21, 0.26, 0.16), 0.17: (0.18, 0.22, 0.13),
    0.15: (0.16, 0.21, 0.11),
}

# Through-hole rules (IPC-2222 table 9-3, IPC-2221 table 9-1), keyed by IPC level A/B/C.
THT_HOLE_ALLOWANCE: dict[str, float] = {"A": 0.25, "B": 0.20, "C": 0.15}
THT_FAB_ALLOWANCE: dict[str, float] = {"A": 0.60, "B": 0.50, "C": 0.40}
THT_ANNULAR_RING_MIN = 0.05
THT_DRILL_GRID = 0.05


def j_table(key: str) -> JTable:
    try:
        return J_TABLES[key]
    except KeyError as exc:
        raise ValueError(f"Unbekannte IPC-Tabelle „{key}“.") from exc


def gullwing_table(pitch: float) -> str:
    """Table 3-2 for pitch > 0.625 mm, table 3-3 otherwise (KiCad: ``pitch < 0.625``)."""
    return "gullwing_fine" if pitch < 0.625 else "gullwing"


# --------------------------------------------------------------------------- numbers


def round_to(value: float, base: float) -> float:
    """Round to the nearest multiple of ``base`` (round-half-even like the KiCad generator)."""
    return round(round(value / base) * base, 6)


_GRID_EPS = 1e-6  # tolerance in grid steps (absorbs float noise such as 1.2000000001)


def round_up(value: float, base: float) -> float:
    """Round up to the grid (values within float noise of a grid point stay on it)."""
    return round(math.ceil(value / base - _GRID_EPS) * base, 6)


def round_down(value: float, base: float) -> float:
    return round(math.floor(value / base + _GRID_EPS) * base, 6)


def fmt_mm(value: float, decimals: int = 2) -> str:
    """German number formatting for messages: 0.15 -> "0,15"."""
    text = f"{value:.{decimals}f}"
    if text.startswith("-") and float(text) == 0:
        text = text[1:]
    return text.replace(".", ",")


def round_base(table: JTable, rounding: RoundingMode) -> float:
    return table.kicad_round if rounding == "kicad" else 0.01


# --------------------------------------------------------------------------- records


class DimInfo(BaseModel):
    min: float
    nom: float
    max: float
    tol: float

    @classmethod
    def of(cls, t: Tol) -> DimInfo:
        nom = t.nom if t.nom is not None else (t.min + t.max) / 2
        return cls(min=_r(t.min), nom=_r(nom), max=_r(t.max), tol=_r(t.max - t.min))


class SpanInfo(DimInfo):
    """Inner span S with RMS-adjusted limits (equal to min/max when S is given directly)."""

    min_rms: float
    max_rms: float
    tol_rms: float
    mode: Literal["rms", "direct"] = "rms"


class LandCalc(BaseModel):
    """Calculation record of one land row group (shown in the UI)."""

    label: str = ""
    axis: Literal["x", "y"] = "x"
    source: Literal["ipc", "manufacturer"] = "ipc"
    standard: str = "IPC-7351B"
    table: str
    table_key: str
    table_title: str = Field(description="Deutsche Bezeichnung der J-Tabelle (bzw. „Herstellerempfehlung“)")
    table_title_en: str = Field(default="", description="Englischer Originaltitel der IPC-Tabelle")
    density: str
    toe: float
    heel: float
    side: float
    F: float
    P: float
    L: DimInfo
    T: DimInfo
    W: DimInfo
    S: SpanInfo
    z_raw: float
    g_raw: float
    x_raw: float
    rounding: str
    round_base: float
    z_rounded: float
    g_rounded: float
    x_rounded: float
    z: float  # final Zmax after clamps
    g: float  # final Gmin after clamps
    x: float  # final Xmax after clamps
    clamps: list[str] = Field(default_factory=list)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pad_length(self) -> float:
        return _r((self.z - self.g) / 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pad_width(self) -> float:
        return _r(self.x)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def pad_center(self) -> float:
        return _r((self.z + self.g) / 4)


def _r(v: float) -> float:
    return round(v, 6)


# --------------------------------------------------------------------------- equations


def inner_span(L: Tol, T: Tol) -> SpanInfo:  # noqa: N803 - IPC symbols
    """S = L - 2T with IPC-7351B RMS adjustment (§1.2)::

        Smin = Lmin - 2*Tmax ; Smax = Lmax - 2*Tmin ; Stol = Smax - Smin
        Stol(RMS) = sqrt(Ltol² + 2*Ttol²)
        Smin(RMS) = Smin + (Stol - Stol(RMS))/2 ; Smax(RMS) = Smax - (Stol - Stol(RMS))/2
    """
    smin = L.min - 2 * T.max
    smax = L.max - 2 * T.min
    stol = smax - smin
    ltol = L.max - L.min
    ttol = T.max - T.min
    stol_rms = math.sqrt(ltol ** 2 + 2 * ttol ** 2)
    stol_rms = min(stol_rms, stol)
    d = (stol - stol_rms) / 2
    return SpanInfo(min=smin, nom=(smin + smax) / 2, max=smax, tol=stol,
                    min_rms=smin + d, max_rms=smax - d, tol_rms=stol_rms, mode="rms")


def direct_span(S: Tol) -> SpanInfo:  # noqa: N803
    """S given directly by the datasheet: worst-case limits, CS = Smax - Smin (KiCad behaviour)."""
    tol = S.max - S.min
    nom = S.nom if S.nom is not None else (S.min + S.max) / 2
    return SpanInfo(min=S.min, nom=nom, max=S.max, tol=tol, min_rms=S.min, max_rms=S.max, tol_rms=tol,
                    mode="direct")


def land(
    L: Tol,  # noqa: N803
    T: Tol,  # noqa: N803
    W: Tol,  # noqa: N803
    *,
    table: str,
    density: Density,
    F: float,  # noqa: N803
    P: float,  # noqa: N803
    rounding: RoundingMode = "kicad",
    S: Tol | None = None,  # noqa: N803
    base: float | None = None,
    axis: Literal["x", "y"] = "x",
    label: str = "",
) -> LandCalc:
    """Zmax/Gmin/Xmax of one land row group, rounded but not yet clamped."""
    jt = j_table(table)
    if density not in jt.values:
        raise ValueError(f"Unbekannte Dichte „{density}“ (erlaubt: M, N, L).")
    j = jt.values[density]
    span = direct_span(S) if S is not None else inner_span(L, T)
    ltol = L.max - L.min
    wtol = W.max - W.min
    # Same order of operations as the reference implementation (bit-identical rounding).
    z_raw = L.min + 2 * j.toe + math.sqrt(ltol ** 2 + F ** 2 + P ** 2)
    g_raw = span.max_rms - 2 * j.heel - math.sqrt(span.tol_rms ** 2 + F ** 2 + P ** 2)
    x_raw = W.min + 2 * j.side + math.sqrt(wtol ** 2 + F ** 2 + P ** 2)
    rb = base if base is not None else round_base(jt, rounding)
    z, g, x = round_to(z_raw, rb), round_to(g_raw, rb), round_to(x_raw, rb)
    return LandCalc(
        label=label, axis=axis, standard=jt.standard, table=jt.table, table_key=jt.key, table_title=jt.label,
        table_title_en=jt.title, density=density, toe=j.toe, heel=j.heel, side=j.side, F=F, P=P,
        L=DimInfo.of(L), T=DimInfo.of(T), W=DimInfo.of(W),
        S=span.model_copy(update={k: _r(getattr(span, k)) for k in
                                  ("min", "nom", "max", "tol", "min_rms", "max_rms", "tol_rms")}),
        z_raw=_r(z_raw), g_raw=_r(g_raw), x_raw=_r(x_raw), rounding=rounding,
        round_base=rb, z_rounded=z, g_rounded=g, x_rounded=x, z=z, g=g, x=x,
    )


def manual_land(
    *,
    pad_length: float,
    pad_width: float,
    row_spacing: float,
    reference: Literal["center", "inner", "outer"],
    density: Density,
    axis: Literal["x", "y"] = "x",
    label: str = "",
) -> LandCalc:
    """Land record from a manufacturer-recommended pattern (no IPC calculation)."""
    if reference == "inner":
        g, z = row_spacing, row_spacing + 2 * pad_length
    elif reference == "outer":
        z, g = row_spacing, row_spacing - 2 * pad_length
    else:
        z, g = row_spacing + pad_length, row_spacing - pad_length
    zero = DimInfo(min=0, nom=0, max=0, tol=0)
    return LandCalc(
        label=label, axis=axis, source="manufacturer", standard="Herstellerempfehlung", table="–",
        table_key="manufacturer", table_title=MANUFACTURER_TABLE_TITLE,
        table_title_en="Manufacturer recommended land pattern", density=density,
        toe=0, heel=0, side=0, F=0, P=0, L=zero, T=zero, W=zero,
        S=SpanInfo(min=0, nom=0, max=0, tol=0, min_rms=0, max_rms=0, tol_rms=0, mode="direct"),
        z_raw=_r(z), g_raw=_r(g), x_raw=_r(pad_width), rounding="none", round_base=0.0,
        z_rounded=_r(z), g_rounded=_r(g), x_rounded=_r(pad_width), z=_r(z), g=_r(g), x=_r(pad_width),
    )


# --------------------------------------------------------------------------- clamps


def clamp_exposed_pad(calc: LandCalc, ep_size: float, clearance: float = DEFAULT_EP_CLEARANCE) -> list[str]:
    """KiCad rule: the heel side keeps ``clearance`` to the exposed pad (G >= EP + 2*clearance)."""
    if ep_size <= 0:
        return []
    needed = _r(ep_size + 2 * clearance)
    if calc.g < needed - _EPS:
        old = calc.g
        calc.g = needed
        msg = (f"Abstand zum Exposed Pad unter {fmt_mm(clearance)} mm: Innenkante der Pads von "
               f"G = {fmt_mm(old)} mm auf {fmt_mm(needed)} mm zurückgenommen.")
        calc.clamps.append(msg)
        return [msg]
    return []


def clamp_min_gap(calc: LandCalc, min_gap: float) -> list[str]:
    """Opposite lands keep at least ``min_gap`` (tiny packages give G <= 0 at density M)."""
    if calc.g < min_gap - _EPS:
        old = calc.g
        calc.g = _r(min_gap)
        msg = (f"Innenabstand G = {fmt_mm(old)} mm unterschreitet den Mindestabstand {fmt_mm(min_gap)} mm: "
               f"Pads innen gekürzt (G = {fmt_mm(min_gap)} mm).")
        calc.clamps.append(msg)
        return [msg]
    return []


def clamp_pad_width(calc: LandCalc, pitch: float, min_gap: float) -> list[str]:
    """Land width must leave ``min_gap`` copper between neighbours at ``pitch``."""
    if pitch <= 0:
        return []
    limit = round_down(pitch - min_gap, 0.01)
    if calc.x > limit + _EPS:
        old = calc.x
        if limit <= 0:
            raise ValueError(
                f"Raster {fmt_mm(pitch)} mm ist zu klein für einen Kupferabstand von {fmt_mm(min_gap)} mm."
            )
        calc.x = limit
        msg = (f"Padbreite {fmt_mm(old)} mm ließe bei {fmt_mm(pitch)} mm Raster nur "
               f"{fmt_mm(pitch - old)} mm Kupferabstand: auf {fmt_mm(limit)} mm reduziert "
               f"(Mindestabstand {fmt_mm(min_gap)} mm).")
        calc.clamps.append(msg)
        return [msg]
    return []


def check_land(calc: LandCalc, what: str = "Anschlusspads") -> None:
    """Raise if the land degenerates (pad length or width <= 0)."""
    if calc.z - calc.g <= 0.01:
        raise ValueError(
            f"{what}: Z = {fmt_mm(calc.z)} mm und G = {fmt_mm(calc.g)} mm ergeben keine sinnvolle Padlänge – "
            "bitte Maße prüfen (Anschlusslänge, Spannweite)."
        )
    if calc.x <= 0.01:
        raise ValueError(f"{what}: berechnete Padbreite X = {fmt_mm(calc.x)} mm ist zu klein – bitte Maße prüfen.")


# --------------------------------------------------------------------------- courtyard


def courtyard_excess(table: str | None, density: Density, *, kind: Literal["smd", "bga", "tht"] = "smd") -> float:
    if kind == "bga":
        return BGA_COURTYARD[density]
    if kind == "tht" or table is None:
        return THT_COURTYARD[density]
    return j_table(table).values[density].courtyard


def courtyard_rect(
    extent: tuple[float, float, float, float], excess: float, grid: float = DEFAULT_COURTYARD_GRID
) -> tuple[float, float, float, float]:
    """Bounding rectangle + excess, every side rounded outward to ``grid``."""
    x1, y1, x2, y2 = extent
    g = grid if grid > 0 else 0.01
    return (
        round_down(x1 - excess, g),
        round_down(y1 - excess, g),
        round_up(x2 + excess, g),
        round_up(y2 + excess, g),
    )


# --------------------------------------------------------------------------- BGA / THT


def bga_land(ball: float, density: Density, collapsible: bool) -> tuple[float, str]:
    """Land diameter for a BGA ball (IPC-7351B tables 14-5/14-6).

    M -> land max (MMC), N -> land nominal, L -> land min. Balls between table rows take the
    lower row's values (Tom Hausherr); outside the table a percentage rule is used.
    """
    table = BGA_COLLAPSIBLE if collapsible else BGA_NON_COLLAPSIBLE
    rows = sorted(table)
    index = {"N": 0, "M": 1, "L": 2}[density]
    if rows[0] - _EPS <= ball <= rows[-1] + _EPS:
        lower = max(r for r in rows if r <= ball + _EPS)
        value = table[lower][index]
        note = (f"IPC-7351B Tabelle {'14-5 (kollabierend)' if collapsible else '14-6 (nicht kollabierend)'}, "
                f"Kugel {fmt_mm(lower)} mm")
        return value, note
    factor = {"N": 0.80, "M": 0.85, "L": 0.75} if collapsible else {"N": 1.10, "M": 1.15, "L": 1.05}
    value = round_to(ball * factor[density], 0.01)
    return value, f"außerhalb der IPC-Tabelle: {round(factor[density] * 100)} % des Kugeldurchmessers"


def tht_hole(lead_size: float, density: Density) -> float:
    """Finished hole: max lead size (diagonal for rectangular leads) + IPC-2222 allowance, drill grid up."""
    level = THT_LEVEL[density]
    return round_up(lead_size + THT_HOLE_ALLOWANCE[level], THT_DRILL_GRID)


def tht_pad(hole: float, density: Density) -> float:
    """Land diameter: hole + 2 * min annular ring + IPC-2221 fabrication allowance (rounded up to 0.05)."""
    level = THT_LEVEL[density]
    return round_up(hole + 2 * THT_ANNULAR_RING_MIN + THT_FAB_ALLOWANCE[level], 0.05)
