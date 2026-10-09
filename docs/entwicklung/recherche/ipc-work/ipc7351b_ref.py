"""Minimal, self-contained IPC-7351B land-pattern reference implementation.

Written from scratch for verification purposes (no third-party code copied).
It reproduces the RMS tolerance model used by IPC-7351B (and implemented by the
KiCad footprint generator) so that its results can be compared with published
KiCad footprints.

Conventions
-----------
* All dimensions in mm.
* A dimension is a ``Dim(min, max)``; ``tol = max - min`` (total tolerance).
* L = outer terminal span (toe to toe), T = terminal (foot) length,
  W = terminal width, S = inner span (heel to heel) = L - 2T.
* F = PCB fabrication tolerance (total), P = placement tolerance (total).
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Dim:
    min: float
    max: float
    # RMS-adjusted limits (equal to min/max for directly measured dimensions)
    min_rms: float | None = None
    max_rms: float | None = None
    tol_rms: float | None = None

    @property
    def tol(self) -> float:
        return self.max - self.min

    @property
    def nom(self) -> float:
        return (self.min + self.max) / 2

    @property
    def lo(self) -> float:  # RMS-adjusted minimum
        return self.min if self.min_rms is None else self.min_rms

    @property
    def hi(self) -> float:  # RMS-adjusted maximum
        return self.max if self.max_rms is None else self.max_rms

    @property
    def ctol(self) -> float:  # tolerance used inside the root-sum-square
        return self.tol if self.tol_rms is None else self.tol_rms

    @staticmethod
    def pm(nom: float, tol: float) -> "Dim":
        return Dim(nom - tol, nom + tol)


def inner_span(L: Dim, T: Dim) -> Dim:
    """S = L - 2T with IPC-7351B RMS adjustment.

    Smin = Lmin - 2*Tmax, Smax = Lmax - 2*Tmin (worst case)
    Stol(RMS) = sqrt(Ltol^2 + 2*Ttol^2)
    Smin(RMS) = Smin + (Stol - Stol(RMS))/2 ; Smax(RMS) = Smax - (Stol - Stol(RMS))/2
    """
    smin = L.min - 2 * T.max
    smax = L.max - 2 * T.min
    stol = smax - smin
    stol_rms = math.sqrt(L.tol ** 2 + 2 * T.tol ** 2)
    stol_rms = min(stol_rms, stol)
    d = (stol - stol_rms) / 2
    return Dim(smin, smax, smin + d, smax - d, stol_rms)


def round_to(v: float, base: float) -> float:
    # NOTE: Python round() is round-half-to-even (same as the KiCad generator)
    return round(v / base) * base


@dataclass
class Fillets:
    toe: float
    heel: float
    side: float


def zgx(L: Dim, S: Dim, W: Dim, j: Fillets, F: float = 0.1, P: float = 0.05,
        round_base=(0.05, 0.05, 0.05)) -> tuple[float, float, float]:
    """Return (Zmax, Gmin, Xmax) per IPC-7351B section 3.1.5 equations."""
    z = L.lo + 2 * j.toe + math.sqrt(L.ctol ** 2 + F ** 2 + P ** 2)
    g = S.hi - 2 * j.heel - math.sqrt(S.ctol ** 2 + F ** 2 + P ** 2)
    x = W.lo + 2 * j.side + math.sqrt(W.ctol ** 2 + F ** 2 + P ** 2)
    return round_to(z, round_base[0]), round_to(g, round_base[1]), round_to(x, round_base[2])


def pad_from_zgx(z: float, g: float, x: float) -> tuple[float, float, float]:
    """Return (pad_length_along_span, pad_width, pad_center_offset_from_origin)."""
    return (z - g) / 2, x, (z + g) / 4


# ---------------------------------------------------------------------------
# IPC-7351B fillet goals (toe, heel, side) per density, transcribed from
# KiCad ipc_7351b.yaml / ipc7351B_2terminal.yaml and JITX protrusions.py
# ---------------------------------------------------------------------------
J = {
    "gullwing_gt0625": {"M": Fillets(0.55, 0.45, 0.05), "N": Fillets(0.35, 0.35, 0.03), "L": Fillets(0.15, 0.25, 0.01)},
    "gullwing_le0625": {"M": Fillets(0.55, 0.45, 0.01), "N": Fillets(0.35, 0.35, -0.02), "L": Fillets(0.15, 0.25, -0.04)},
    "chip_ge0603": {"M": Fillets(0.55, 0.0, 0.05), "N": Fillets(0.35, 0.0, 0.0), "L": Fillets(0.15, 0.0, -0.05)},
    "chip_lt0603": {"M": Fillets(0.30, 0.0, 0.05), "N": Fillets(0.20, 0.0, 0.0), "L": Fillets(0.10, 0.0, -0.05)},
    "qfn": {"M": Fillets(0.40, 0.0, -0.04), "N": Fillets(0.30, 0.0, -0.04), "L": Fillets(0.20, 0.0, -0.04)},
    # IPC-7352 inward L (KiCad ipc_spec_tantalum_7352) -- toe applies to Z
    "inward_L_7352": {"M": Fillets(0.55, 0.10, 0.05), "N": Fillets(0.35, 0.0, 0.03), "L": Fillets(0.15, 0.0, 0.01)},
}


def check(name: str, got: tuple[float, float, float], exp: tuple[float, float, float], tol=1e-6) -> bool:
    ok = all(abs(a - b) <= tol for a, b in zip(got, exp))
    print(f"{'OK ' if ok else 'BAD'} {name:42s} got pad {got[0]:.4f} x {got[1]:.4f} @ +/-{got[2]:.4f}   "
          f"kicad {exp[0]} x {exp[1]} @ +/-{exp[2]}")
    return ok


def chip(L: Dim, W: Dim, T: Dim, fam: str, rb: float, F=0.1, P=0.05, dens="N"):
    S = inner_span(L, T)
    return pad_from_zgx(*zgx(L, S, W, J[fam][dens], F, P, (rb, rb, rb)))


def gullwing(E: Dim, Lf: Dim, b: Dim, pitch: float, F=0.1, P=0.05, dens="N", force_small=False):
    fam = "gullwing_le0625" if (pitch < 0.625 or force_small) else "gullwing_gt0625"
    S = inner_span(E, Lf)
    return pad_from_zgx(*zgx(E, S, b, J[fam][dens], F, P))


def qfn(D: Dim, Lt: Dim, b: Dim, ep: float, F=0.1, P=0.05, dens="N", min_ep_clear=0.2):
    S = inner_span(D, Lt)
    z, g, x = zgx(D, S, b, J["qfn"][dens], F, P)
    if ep > 0 and g - 2 * min_ep_clear < ep:  # KiCad: pull heel back to keep 0.2 mm to EP
        g = ep + 2 * min_ep_clear
    return pad_from_zgx(z, g, x)


if __name__ == "__main__":
    allok = True
    # 2-terminal chips (KiCad data: IPC-SM-782 / Vishay sizes), expected values from published KiCad footprints
    allok &= check("R_0402_1005Metric", chip(Dim(1.0, 1.1), Dim(0.48, 0.6), Dim(0.1, 0.3), "chip_lt0603", 0.02), (0.54, 0.64, 0.51))
    allok &= check("R_0603_1608Metric", chip(Dim(1.5, 1.7), Dim(0.7, 0.95), Dim(0.15, 0.4), "chip_ge0603", 0.05), (0.8, 0.95, 0.825))
    allok &= check("R_0805_2012Metric", chip(Dim(1.85, 2.15), Dim(1.1, 1.4), Dim(0.15, 0.65), "chip_ge0603", 0.05), (1.025, 1.4, 0.9125))
    allok &= check("R_1206_3216Metric", chip(Dim(3.05, 3.35), Dim(1.45, 1.75), Dim(0.25, 0.75), "chip_ge0603", 0.05), (1.125, 1.75, 1.4625))
    allok &= check("R_2512_6332Metric", chip(Dim(6.15, 6.45), Dim(3.05, 3.35), Dim(0.35, 0.85), "chip_ge0603", 0.05), (1.225, 3.35, 2.9625))
    allok &= check("C_0805_2012Metric", chip(Dim(1.8, 2.2), Dim(1.05, 1.45), Dim(0.25, 0.55), "chip_ge0603", 0.05), (1.0, 1.45, 0.95))
    # Tantalum A case (KEMET dims, KiCad uses IPC-7352 inward-L, round 0.01, W = terminal width F)
    L = Dim.pm(3.2, 0.2); W = Dim.pm(1.2, 0.1); T = Dim(0.8 - 0.3, 0.8 + 0.2)
    S = inner_span(L, T)
    allok &= check("CP_EIA-3216-18_Kemet-A", pad_from_zgx(*zgx(L, S, W, J["inward_L_7352"]["N"], 0.1, 0.05, (0.01, 0.01, 0.01))), (1.415, 1.39, 1.3525))
    # Gull-wing
    allok &= check("SOIC-8_3.9x4.9mm_P1.27mm", gullwing(Dim.pm(6.0, 0.2), Dim(0.4, 1.27), Dim(0.31, 0.51), 1.27), (1.95, 0.6, 2.475))
    # KiCad data (git master 2026-10) says L = 0.40..0.60 for TO-236AB, but the *published*
    # SOT-23.kicad_mod (format 20260206) is reproduced only with L = 0.30..0.60 -> data lag.
    print("    info: SOT-23 with foot 0.40..0.60 ->", tuple(round(v, 4) for v in gullwing(Dim(2.10, 2.64), Dim(0.40, 0.60), Dim(0.3, 0.5), 0.95)))
    allok &= check("SOT-23 (TO-236AB, foot 0.30..0.60)", gullwing(Dim(2.10, 2.64), Dim(0.30, 0.60), Dim(0.3, 0.5), 0.95), (1.475, 0.6, 0.9375))
    allok &= check("SOT-23-5 (MO-178)", gullwing(Dim(2.8, 2.8), Dim(0.3, 0.6), Dim(0.3, 0.5), 0.95), (1.325, 0.6, 1.1375))
    allok &= check("TSSOP-16 (MO-153)", gullwing(Dim(6.4, 6.4), Dim.pm(0.6, 0.15), Dim(0.17, 0.30), 0.65), (1.475, 0.4, 2.8625))
    allok &= check("LQFP-48 7x7 (MS-026)", gullwing(Dim(9.0, 9.0), Dim(0.45, 0.75), Dim(0.17, 0.27), 0.5), (1.475, 0.3, 4.1625))
    # QFN
    allok &= check("QFN-16 3x3 P0.5 EP1.75", qfn(Dim(3.0, 3.0), Dim(0.3, 0.5), Dim(0.18, 0.30), 1.75), (0.775, 0.25, 1.4625))
    print("ALL OK" if allok else "MISMATCHES PRESENT")

    # IPC-SM-782A (1999) worked example, section 3.3.1/Figure 3-5 (SOIC, L 5.8-6.2, T 0.4-1.27):
    # document states Smin=3.26, Smax=5.4, Stol=2.14, Stol(rms)=1.29, Smax(rms)=Smin+Stol(rms)=4.55,
    # Gmin = 4.55 - 2(0.5) - sqrt(1.29^2+0.1^2+0.1^2) = 2.25 (J_h=0.5, F=P=0.1)
    L, T = Dim(5.8, 6.2), Dim(0.4, 1.27)
    smin, smax = L.min - 2 * T.max, L.max - 2 * T.min
    st_rms = math.sqrt(L.tol ** 2 + 2 * T.tol ** 2)
    g782 = (smin + st_rms) - 2 * 0.5 - math.sqrt(st_rms ** 2 + 0.1 ** 2 + 0.1 ** 2)
    print(f"IPC-SM-782A example: Smin={smin:.2f} Smax={smax:.2f} Stol={smax - smin:.2f} "
          f"Stol_rms={st_rms:.2f} Smax_rms(782A)={smin + st_rms:.2f} Gmin={g782:.2f} (doc: 2.25)")
    S = inner_span(L, T)
    print(f"IPC-7351B variant for same part: Smax_rms = Smax-(Stol-Stol_rms)/2 = {S.hi:.3f}")
