"""Turn raw KEMET waterfall cells + text tables into a clean ground-truth JSON.

Usage: python -I kemet_finalize.py <kemet_waterfall.json> <work_dir_of_kemet_pages> <out_json>
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

E24 = [10, 11, 12, 13, 15, 16, 18, 20, 22, 24, 27, 30, 33, 36, 39, 43, 47, 51, 56, 62, 68, 75, 82, 91]
E12 = [10, 12, 15, 18, 22, 27, 33, 39, 47, 56, 68, 82]
LABEL_FIX = {"- 151**": "101 - 151**", "- 821**": "181 - 821**"}  # verified visually on page 4


def code_to_pf(code: str) -> float:
    return int(code[:2]) * 10 ** int(code[2])


def pf_to_code(pf: float) -> str:
    exp = 0
    while pf >= 100:
        pf /= 10
        exp += 1
    return f"{int(round(pf)):02d}{exp}"


def expand(label: str) -> list[str]:
    label = LABEL_FIX.get(label, label)
    m = re.fullmatch(r"(\d{3}) - (\d{3})(\*{1,2})", label)
    if not m:
        assert re.fullmatch(r"\d{3}", label), label
        return [label]
    lo, hi, stars = code_to_pf(m.group(1)), code_to_pf(m.group(2)), m.group(3)
    series = E24 if stars == "*" else E12
    out = []
    for decade in (1, 10, 100, 1000):
        for v in series:
            pf = v * decade / 10  # series values 10..91 -> 1.0..9.1 pF base
            if lo <= pf <= hi:
                out.append(pf_to_code(pf))
    return out


def main() -> None:
    raw = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    work = Path(sys.argv[2])
    entries = []
    for c in raw["cells"]:
        code = c["thickness_code"]
        foot = c["footnote"]
        if "¹" in code:  # superscript one rendered at body size (verified visually = footnote 1)
            code = code.replace("¹", "")
            foot = "1"
        if "²" in code:
            code = code.replace("²", "")
            foot = "2"
        if foot:
            foot = foot.replace("^", "")
        for cap_code in expand(c["cap_label"]):
            entries.append({
                "case": c["case"], "voltage_code": c["vcode"], "rated_voltage_V": c["volt"],
                "cap_code": cap_code, "cap_pF": code_to_pf(cap_code), "thickness_code": code,
                "tolerances": "K,M" if foot == "1" else ("M" if foot == "2" else "J,K,M"),
                "source_page": c["page"],
            })
    # thickness table (Table 2A, pages 9-10)
    thick = {}
    for p in ("p009.txt", "p010.txt"):
        for line in (work / p).read_text(encoding="utf-8").splitlines():
            line = line.replace("\t", " ")
            m = re.match(r"^([A-Z]{2}) (\d{4}) ([\d.]+)\s*±\s*([\d.]+)\*?\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)", line)
            if m:
                q = [int(x.replace(",", "")) for x in m.groups()[4:]]
                thick[m.group(1)] = {"case": m.group(2), "thickness_mm": float(m.group(3)), "tol_mm": float(m.group(4)),
                                     "paper_7in": q[0], "paper_13in": q[1], "plastic_7in": q[2], "plastic_13in": q[3]}
    # land pattern (Table 3, page 12)
    land = {}
    for line in (work / "p012.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(\d{4})(1?) (\d{4}) ((?:[\d.]+ ){14}[\d.]+)$", line.strip())
        if m:
            nums = [float(x) for x in m.group(4).split()]
            key = m.group(1) + (" (>=22uF)" if m.group(2) else "")
            land[key] = {lvl: dict(zip(["C_center_to_pad_center", "Y_pad_length", "X_pad_width", "V1_courtyard_x", "V2_courtyard_y"], nums[i * 5:(i + 1) * 5]))
                         for i, lvl in enumerate(["A_most", "B_nominal", "C_least"])}
    missing = sorted({e["thickness_code"] for e in entries} - set(thick))
    summary = defaultdict(dict)
    for e in entries:
        k = (e["case"], e["rated_voltage_V"])
        s = summary[e["case"]].setdefault(str(e["rated_voltage_V"]), {"min_pF": e["cap_pF"], "max_pF": e["cap_pF"], "count": 0})
        s["min_pF"] = min(s["min_pF"], e["cap_pF"])
        s["max_pF"] = max(s["max_pF"], e["cap_pF"])
        s["count"] += 1
    out = {
        "source": "kemet_C1002_X7R_SMD.pdf", "tables": "Table 1A/1B/1C pages 4-8, Table 2A pages 9-10, Table 3 page 12",
        "method": "pdfplumber char coordinates -> nearest voltage column; spot-checked against 150-200 dpi renders",
        "availability": entries, "thickness_codes": thick, "land_pattern_ipc7351": land,
        "summary_by_case_and_voltage": summary, "thickness_codes_missing_in_table2A": missing,
    }
    Path(sys.argv[3]).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print("entries", len(entries), "thickness codes", len(thick), "land rows", len(land), "missing", missing)
    for case, volts in summary.items():
        print(case, {v: (f"{s['min_pF']:g}..{s['max_pF']:g} pF", s["count"]) for v, s in volts.items()})


if __name__ == "__main__":
    main()
