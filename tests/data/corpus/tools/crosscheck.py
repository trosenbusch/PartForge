"""Cross-check manifest values against the PDF text layer (catches manual transcription errors).

Usage: python -I crosscheck.py <corpus_dir>
"""
import json
import re
import sys
from pathlib import Path

corpus = Path(sys.argv[1])
m = json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))


def text_of(pdf_name: str) -> str:
    stem = Path(pdf_name).stem
    parts = []
    for f in sorted((corpus / "work" / stem).glob("p*.txt")):
        parts.append(f.read_text(encoding="utf-8"))
    return re.sub(r"\s+", "", "\n".join(parts))


problems = 0
for e in m["entries"]:
    t = text_of(e["file"])
    mpns = []
    for dv in e.get("devices", []):
        for x in dv.get("mpns", []):
            mpns.append(x["mpn"] if isinstance(x, dict) else x)
    if "series" in e and "parts" in e["series"]:
        mpns += [p["mpn"] for p in e["series"]["parts"]]
    missing = [x for x in mpns if x.replace(" ", "") not in t]
    print(f"{e['file']}: {len(mpns)} MPNs checked, missing in text: {missing}")
    problems += len(missing)
    # numeric dims check (only pages with a text layer)
    nums = []
    for pk, pv in (e.get("packages") or {}).items():
        for dk, dvv in (pv.get("dims_mm") or {}).items():
            if isinstance(dvv, dict):
                for k in ("min", "nom", "max"):
                    if isinstance(dvv.get(k), (int, float)):
                        nums.append((pk, dk, dvv[k]))
    if nums:
        absent = []
        for pk, dk, v in nums:
            s1 = f"{v:.2f}"
            s2 = f"{v:g}"
            s3 = s1.replace(".", ",")
            s4 = f"{v:.3f}"
            s5 = f"{v:.4f}"
            if not any(s in t for s in {s1, s2, s3, s4, s5}):
                absent.append(f"{pk}/{dk}={v}")
        print(f"   dims numbers not found in text layer ({len(absent)}/{len(nums)}): {absent[:30]}")
print("MPN problems:", problems)

# Bourns table exact row check
e = [x for x in m["entries"] if x["file"].endswith("bourns_SRR1260.pdf")][0]
raw = (corpus / "work" / "bourns_SRR1260" / "p001.txt").read_text(encoding="utf-8")
bad = 0
for p in e["series"]["parts"]:
    line = next((ln for ln in raw.splitlines() if ln.startswith(p["mpn"] + " ")), None)
    toks = line.replace("±", " ").split()[1:] if line else []
    vals = [float(x) for x in toks]
    exp = [p["L_uH"], p["tol_pct"], p["Q_typ"], p["test_freq_MHz"], p["SRF_typ_MHz"], p["RDC_max_mohm"], p["Irms_max_A"], p["Isat_typ_A"], p["K_factor"]]
    if vals != exp:
        bad += 1
        print("Bourns mismatch", p["mpn"], vals, exp)
print("Bourns rows checked:", len(e["series"]["parts"]), "mismatches:", bad)
