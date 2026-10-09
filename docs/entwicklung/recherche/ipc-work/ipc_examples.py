"""Compute example IPC-7351B land patterns (N/M/L) + IPC names for the reference
package table, using the verified reference implementation in ipc7351b_ref.py.

Run: python -I ipc_examples.py > ../examples.md
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ipc7351b_ref import Dim, Fillets, inner_span, pad_from_zgx, round_to  # noqa: E402

F_TOL, P_TOL = 0.10, 0.05  # KiCad / PCB-Libraries (+-0.05 / +-0.025) convention

# IPC-7351B fillet goals (toe -> Z, heel -> G, side -> X) per density M/N/L
JT = {
    "T3-2_gullwing_gt0p625": {"M": (0.55, 0.45, 0.05), "N": (0.35, 0.35, 0.03), "L": (0.15, 0.25, 0.01), "cy": (0.50, 0.25, 0.10)},
    "T3-3_gullwing_le0p625": {"M": (0.55, 0.45, 0.01), "N": (0.35, 0.35, -0.02), "L": (0.15, 0.25, -0.04), "cy": (0.50, 0.25, 0.10)},
    "T3-5_chip_ge0603": {"M": (0.55, 0.00, 0.05), "N": (0.35, 0.00, 0.00), "L": (0.15, 0.00, -0.05), "cy": (0.50, 0.25, 0.10)},
    "T3-6_chip_lt0603": {"M": (0.30, 0.00, 0.05), "N": (0.20, 0.00, 0.00), "L": (0.10, 0.00, -0.05), "cy": (0.20, 0.15, 0.10)},
    "T3-7_melf": {"M": (0.60, 0.20, 0.10), "N": (0.40, 0.10, 0.05), "L": (0.20, 0.02, 0.01), "cy": (0.50, 0.25, 0.10)},
    # Table 3-13 inward L: IPC 'heel' row (0.80/0.50/0.20) acts on Z, IPC 'toe' row (0.25/0.15/0.07) on G
    "T3-13_inward_L": {"M": (0.80, 0.25, 0.01), "N": (0.50, 0.15, -0.05), "L": (0.20, 0.07, -0.10), "cy": (0.50, 0.25, 0.10)},
    "T3-15_qfn": {"M": (0.40, 0.00, -0.04), "N": (0.30, 0.00, -0.04), "L": (0.20, 0.00, -0.04), "cy": (0.50, 0.25, 0.10)},
    "T3-22_flat_lead": {"M": (0.30, 0.00, 0.05), "N": (0.20, 0.00, 0.00), "L": (0.10, 0.00, -0.05), "cy": (0.20, 0.15, 0.10)},
}


def calc(L: Dim, T: Dim, W: Dim, table: str, dens: str, rb: float):
    j = Fillets(*JT[table][dens])
    S = inner_span(L, T)
    z = L.lo + 2 * j.toe + math.sqrt(L.ctol ** 2 + F_TOL ** 2 + P_TOL ** 2)
    g = S.hi - 2 * j.heel - math.sqrt(S.ctol ** 2 + F_TOL ** 2 + P_TOL ** 2)
    x = W.lo + 2 * j.side + math.sqrt(W.ctol ** 2 + F_TOL ** 2 + P_TOL ** 2)
    z, g, x = round_to(z, rb), round_to(g, rb), round_to(x, rb)
    return z, g, x


def courtyard(extent_x: float, extent_y: float, excess: float, grid: float = 0.01):
    # round each half-dimension UP to the grid (KLC style)
    hx = math.ceil((extent_x / 2 + excess) / grid - 1e-9) * grid
    hy = math.ceil((extent_y / 2 + excess) / grid - 1e-9) * grid
    return 2 * hx, 2 * hy


def n2(v: float) -> str:  # IPC name: 2 decimals, no decimal point, no leading zeros
    return str(int(round(v * 100)))


def n1(v: float) -> str:  # chip body: 1 place each side of decimal point
    return str(int(round(v * 10)))


ROWS = []


def add(name, ipc_name, L, T, W, table, rb, body_w=None, pitch=None):
    ROWS.append((name, ipc_name, L, T, W, table, rb, body_w, pitch))


# ----------------------------- inputs ---------------------------------------
# chip resistors: Vishay D/CRCW e3 (rev 14-Apr-2026), CRCW0201 e3, CRCW01005 e3; T = bottom terminal T2
add("R 01005 (0402M)", "RESC" + "04" + "02" + "X" + n2(0.15) + "N", Dim(0.38, 0.42), Dim(0.07, 0.13), Dim(0.18, 0.22), "T3-6_chip_lt0603", 0.02)
add("R 0201 (0603M)", "RESC0603X26N", Dim(0.57, 0.63), Dim(0.05, 0.15), Dim(0.27, 0.33), "T3-6_chip_lt0603", 0.02)
add("R 0402 (1005M)", "RESC1005X40N", Dim(0.95, 1.05), Dim(0.10, 0.30), Dim(0.45, 0.55), "T3-6_chip_lt0603", 0.02)
add("R 0603 (1608M)", "RESC1608X50N", Dim(1.50, 1.65), Dim(0.10, 0.50), Dim(0.75, 0.95), "T3-5_chip_ge0603", 0.05)
add("R 0805 (2012M)", "RESC2012X60N", Dim(1.90, 2.20), Dim(0.10, 0.50), Dim(1.10, 1.40), "T3-5_chip_ge0603", 0.05)
add("R 1206 (3216M)", "RESC3216X60N", Dim(3.00, 3.30), Dim(0.20, 0.60), Dim(1.45, 1.75), "T3-5_chip_ge0603", 0.05)
add("R 1210 (3225M)", "RESC3225X60N", Dim(3.00, 3.40), Dim(0.20, 0.60), Dim(2.30, 2.70), "T3-5_chip_ge0603", 0.05)
add("R 2010 (5025M)", "RESC5025X70N", Dim(4.85, 5.15), Dim(0.40, 0.80), Dim(2.35, 2.65), "T3-5_chip_ge0603", 0.05)
add("R 2512 (6332M)", "RESC6332X70N", Dim(6.10, 6.50), Dim(0.40, 0.80), Dim(3.00, 3.30), "T3-5_chip_ge0603", 0.05)
# MLCC: KEMET/YAGEO C1002 X7R (2026-09-01); T = bandwidth B
add("C 0402 (1005M)", "CAPC1005X55N", Dim(0.95, 1.05), Dim(0.20, 0.40), Dim(0.45, 0.55), "T3-6_chip_lt0603", 0.02)
add("C 0603 (1608M)", "CAPC1608X87N", Dim(1.45, 1.75), Dim(0.20, 0.50), Dim(0.65, 0.95), "T3-5_chip_ge0603", 0.05)
add("C 0805 (2012M)", "CAPC2012X145N", Dim(1.80, 2.20), Dim(0.25, 0.75), Dim(1.05, 1.45), "T3-5_chip_ge0603", 0.05)
add("C 1206 (3216M)", "CAPC3216X180N", Dim(3.00, 3.40), Dim(0.25, 0.75), Dim(1.40, 1.80), "T3-5_chip_ge0603", 0.05)
add("C 1210 (3225M)", "CAPC3225X280N", Dim(3.00, 3.40), Dim(0.25, 0.75), Dim(2.30, 2.70), "T3-5_chip_ge0603", 0.05)
add("C 1812 (4532M)", "CAPC4532X270N", Dim(4.20, 4.80), Dim(0.25, 0.95), Dim(2.90, 3.50), "T3-5_chip_ge0603", 0.05)
# Tantalum: KEMET T491 (L, S terminal length, F terminal width)
add("Ta A 3216-18", "CAPMP3216X180N", Dim(3.0, 3.4), Dim(0.5, 1.0), Dim(1.1, 1.3), "T3-13_inward_L", 0.05)
add("Ta B 3528-21", "CAPMP3528X210N", Dim(3.3, 3.7), Dim(0.5, 0.9), Dim(2.1, 2.3), "T3-13_inward_L", 0.05)
add("Ta C 6032-28", "CAPMP6032X280N", Dim(5.7, 6.3), Dim(1.0, 1.6), Dim(2.1, 2.3), "T3-13_inward_L", 0.05)
add("Ta D 7343-31", "CAPMP7343X310N", Dim(7.0, 7.6), Dim(1.0, 1.6), Dim(2.3, 2.5), "T3-13_inward_L", 0.05)
# MELF: Vishay MMU/MMA/MMB (L, end cap K, diameter D) and Diodes MiniMELF/MELF
add("MicroMELF 0102 (Vishay MMU)", "RESMELF2211N", Dim(2.1, 2.2), Dim(0.35, 0.45), Dim(1.0, 1.1), "T3-7_melf", 0.05)
add("MiniMELF 0204 (Vishay MMA)", "RESMELF3614N", Dim(3.4, 3.6), Dim(0.7, 0.9), Dim(1.3, 1.4), "T3-7_melf", 0.05)
add("MELF 0207 (Vishay MMB)", "RESMELF5822N", Dim(5.65, 5.8), Dim(1.05, 1.25), Dim(2.0, 2.2), "T3-7_melf", 0.05)
add("MiniMELF SOD-80 (Diodes)", "DIOMELF3515N", Dim(3.3, 3.7), Dim(0.28, 0.50), Dim(1.3, 1.6), "T3-7_melf", 0.05)
# SMA/SMB/SMC (Diodes Inc.): E overall, H/L terminal length, C/b lead width
add("SMA DO-214AC", "DIOM5226X240N", Dim(4.80, 5.59), Dim(0.76, 1.52), Dim(1.27, 1.63), "T3-13_inward_L", 0.05)
add("SMB DO-214AA", "DIOM5336X250N", Dim(5.00, 5.59), Dim(0.76, 1.52), Dim(1.96, 2.21), "T3-13_inward_L", 0.05)
add("SMC DO-214AB", "DIOM7959X250N", Dim(7.75, 8.13), Dim(0.76, 1.52), Dim(2.75, 3.18), "T3-13_inward_L", 0.05)
# SOD (gull-wing): Diodes SOD123; Nexperia SOD323 ; flat lead: Nexperia SOD123F, SOD523
add("SOD-123 (Diodes)", "SOD3716X135N", Dim(3.55, 3.85), Dim(0.25, 0.40), Dim(0.52, 0.62), "T3-2_gullwing_gt0p625", 0.05)
add("SOD-323 (Nexperia)", "SOD2513X110N", Dim(2.3, 2.7), Dim(0.15, 0.45), Dim(0.25, 0.40), "T3-2_gullwing_gt0p625", 0.05)
add("SOD-123F (Nexperia, flat)", "SODFL3516X120N", Dim(3.4, 3.6), Dim(0.35, 0.55), Dim(0.55, 0.70), "T3-22_flat_lead", 0.05)
add("SOD-523 (Nexperia, flat)", "SODFL1680X65N", Dim(1.55, 1.70), Dim(0.10, 0.30), Dim(0.26, 0.34), "T3-22_flat_lead", 0.02)
# SOT family (gull-wing)
add("SOT-23-3 TO-236AB (JEDEC via KiCad)", "SOT95P237X112-3N", Dim(2.10, 2.64), Dim(0.40, 0.60), Dim(0.30, 0.50), "T3-2_gullwing_gt0p625", 0.05)
add("SOT-23-5/6 MO-178 (TI DBV)", "SOT95P280X145-5N", Dim(2.60, 3.00), Dim(0.30, 0.60), Dim(0.30, 0.50), "T3-2_gullwing_gt0p625", 0.05)
add("SOT-323/363 SC-70 (Nexperia)", "SOT65P210X110-6N", Dim(2.0, 2.2), Dim(0.15, 0.45), Dim(0.20, 0.30), "T3-2_gullwing_gt0p625", 0.05)
add("SOT-523/SC-75 (Diodes SOT523)", "SOT50P160X90-3N", Dim(1.45, 1.75), Dim(0.20, 0.40), Dim(0.15, 0.30), "T3-3_gullwing_le0p625", 0.05)
add("SOT-223 leads (Nexperia)", "SOT230P700X180-4N", Dim(6.7, 7.3), Dim(0.7, 1.1), Dim(0.60, 0.80), "T3-2_gullwing_gt0p625", 0.05)
# ICs
add("SOIC-8 MS-012 (Nexperia SOT96-1)", "SOIC127P600X175-8N", Dim(5.8, 6.2), Dim(0.40, 1.27), Dim(0.31, 0.51), "T3-2_gullwing_gt0p625", 0.05)
add("TSSOP-16 MO-153 (Nexperia SOT403-1)", "SOP65P640X120-16N", Dim(6.2, 6.6), Dim(0.45, 0.75), Dim(0.19, 0.30), "T3-2_gullwing_gt0p625", 0.05)
add("MSOP-8 MO-187 (Nexperia SOT505-1)", "SOP65P490X110-8N", Dim(4.7, 5.1), Dim(0.40, 0.70), Dim(0.25, 0.45), "T3-2_gullwing_gt0p625", 0.05)
add("MSOP-10 0.5 MO-187BA (E 4.9+-0.15 assumed)", "SOP50P490X110-10N", Dim(4.75, 5.05), Dim(0.40, 0.80), Dim(0.17, 0.33), "T3-3_gullwing_le0p625", 0.05)
add("SSOP-20 5.3mm MO-150", "SOP65P780X200-20N", Dim(7.40, 8.20), Dim(0.55, 0.95), Dim(0.22, 0.38), "T3-2_gullwing_gt0p625", 0.05)
add("LQFP-48 7x7 0.5 (span 9.0+-0.2 assumed)", "QFP50P900X900X160-48N", Dim(8.8, 9.2), Dim(0.45, 0.75), Dim(0.17, 0.27), "T3-3_gullwing_le0p625", 0.05)
add("LQFP-32 7x7 0.8 (NXP SOT358-1)", "QFP80P900X900X160-32N", Dim(8.85, 9.15), Dim(0.45, 0.75), Dim(0.30, 0.40), "T3-2_gullwing_gt0p625", 0.05)
add("LQFP-100 14x14 0.5 (NXP SOT407-1)", "QFP50P1600X1600X160-100N", Dim(15.75, 16.25), Dim(0.45, 0.75), Dim(0.17, 0.27), "T3-3_gullwing_le0p625", 0.05)
add("QFN-16 3x3 0.5 (body +-0.05 assumed)", "QFN50P300X300X80-17N", Dim(2.95, 3.05), Dim(0.30, 0.50), Dim(0.18, 0.30), "T3-15_qfn", 0.05)
add("QFN-32 5x5 0.5 (ADI 05-08-1693)", "QFN50P500X500X80-33N", Dim(4.9, 5.1), Dim(0.30, 0.50), Dim(0.20, 0.30), "T3-15_qfn", 0.05)


def main() -> None:
    print("| Package | IPC name (N) | table | Z/G/X (M) | Z/G/X (N) | Z/G/X (L) | pad LxW @ +-c (N) |")
    print("|---|---|---|---|---|---|---|")
    for name, ipc, L, T, W, table, rb, _bw, _p in ROWS:
        res = {d: calc(L, T, W, table, d, rb) for d in "MNL"}
        z, g, x = res["N"]
        pl, pw, c = pad_from_zgx(z, g, x)
        fmt = lambda t: f"{t[0]:.2f}/{t[1]:.2f}/{t[2]:.2f}"  # noqa: E731
        print(f"| {name} | {ipc} | {table} | {fmt(res['M'])} | {fmt(res['N'])} | {fmt(res['L'])} | {pl:.3f} x {pw:.2f} @ {c:.3f} |")


if __name__ == "__main__":
    main()
