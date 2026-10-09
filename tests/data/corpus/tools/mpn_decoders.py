"""Reference MPN decoders/encoders derived from the corpus datasheets (tested in __main__).

Run: python -I mpn_decoders.py <corpus_dir>
"""
import json
import re
import sys
from pathlib import Path

# --- Vishay CRCW e3 (vishay_dcrcwe3.pdf p3) -----------------------------------------
CRCW_RE = re.compile(r"^CRCW(0402|0603|0805|1206|1210|1218|2010|2512)([0-9RKM]{4})([FJZ])([KN0])(E[ACDEFGHIK])$")
CRCW_TOL = {"F": "±1 %", "J": "±5 %", "Z": "jumper"}
CRCW_TCR = {"K": "±100 ppm/K", "N": "±200 ppm/K", "0": "jumper"}


def crcw_decode(mpn: str) -> dict:
    m = CRCW_RE.match(mpn)
    if not m:
        raise ValueError(f"not a CRCW e3 GPN: {mpn}")
    size, rcode, tol, tcr, pack = m.groups()
    if rcode == "0000":
        ohm = 0.0
    else:
        mult = {"R": 1, "K": 1e3, "M": 1e6}
        letter = next(c for c in rcode if c in mult)
        ohm = float(rcode.replace(letter, ".")) * mult[letter]
    return {"size": size, "ohm": ohm, "tolerance": CRCW_TOL[tol], "tcr": CRCW_TCR[tcr], "packaging": pack}


def crcw_encode(size: str, ohm: float, tol: str, tcr: str, pack: str) -> str:
    """tol 'F'/'J', tcr 'K'/'N'; resistance -> 4-char code with R/K/M as decimal point."""
    if ohm == 0:
        return f"CRCW{size}0000Z0{pack}"
    for letter, mult in (("M", 1e6), ("K", 1e3), ("R", 1)):
        if ohm >= mult:
            v = ohm / mult
            break
    else:
        raise ValueError("below 1 ohm not in series")
    digits = f"{v:.3f}".rstrip("0").rstrip(".") if v < 1000 else str(int(v))
    ip, _, fp = digits.partition(".")
    code = (ip + letter + fp).ljust(4, "0")[:4]
    return f"CRCW{size}{code}{tol}{tcr}{pack}"


# --- KEMET C-series X7R (kemet_C1002_X7R_SMD.pdf p2) ------------------------------------
KEMET_RE = re.compile(r"^C(0402|0603|0805|1206|1210|1805|1808|1812|1825|2220|2225)C(\d{3})([JKM])([984365 12A])R A C(TU|TM|7411|7210|7040|7215)?$".replace(" ", ""))
KEMET_V = {"9": 6.3, "8": 10, "4": 16, "3": 25, "6": 35, "5": 50, "1": 100, "2": 200, "A": 250}


def kemet_decode(mpn: str) -> dict:
    m = KEMET_RE.match(mpn)
    if not m:
        raise ValueError(f"not a KEMET X7R C-series MPN: {mpn}")
    case, cap, tol, v, cspec = m.groups()
    return {"case": case, "cap_code": cap, "cap_pF": int(cap[:2]) * 10 ** int(cap[2]), "tolerance": tol, "rated_V": KEMET_V[v], "cspec": cspec or ""}


def main() -> None:
    corpus = Path(sys.argv[1])
    # CRCW round trips
    for mpn in ["CRCW0603562RFKEA", "CRCW06030000Z0EA", "CRCW060310K0FKEA", "CRCW08054K70JNEA", "CRCW04021M00FKED", "CRCW12064R70FNEA"]:
        print(mpn, crcw_decode(mpn))
    assert crcw_encode("0603", 562, "F", "K", "EA") == "CRCW0603562RFKEA"
    assert crcw_encode("0603", 0, "Z", "0", "EA") == "CRCW06030000Z0EA"
    assert crcw_encode("0603", 10e3, "F", "K", "EA") == "CRCW060310K0FKEA"
    assert crcw_encode("0805", 4.7e3, "J", "N", "EA") == "CRCW08054K70JNEA"
    assert crcw_encode("0402", 1e6, "F", "K", "ED") == "CRCW04021M00FKED"
    assert crcw_encode("1206", 4.7, "F", "N", "EA") == "CRCW12064R70FNEA"
    assert crcw_encode("2512", 97.6, "F", "K", "EG") == "CRCW251297R6FKEG"
    assert crcw_encode("0603", 9.76e6, "F", "K", "EA") == "CRCW06039M76FKEA"
    # KEMET decode + availability lookup
    gt = json.loads((corpus / "groundtruth" / "kemet_C1002_X7R_series.json").read_text(encoding="utf-8"))
    avail = {(a["case"], a["voltage_code"], a["cap_code"]): a for a in gt["availability"]}
    vrev = {v: k for k, v in KEMET_V.items()}
    for mpn in ["C1206C106M4RACTU", "C0603C104K5RACTU", "C0402C104K3RACTU", "C0805C106J8RACTU", "C1210C476M8RACTU", "C0402C105K8RACTU"]:
        dcd = kemet_decode(mpn)
        a = avail.get((dcd["case"], vrev[dcd["rated_V"]], dcd["cap_code"]))
        ok = bool(a) and dcd["tolerance"] in a["tolerances"].split(",")
        print(mpn, dcd, "->", (a["thickness_code"], a["tolerances"]) if a else None, "ORDERABLE" if ok else "NOT ORDERABLE")
    print("all asserts passed")


if __name__ == "__main__":
    main()
