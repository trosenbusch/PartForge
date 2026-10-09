"""Extract KEMET 'Capacitance Range/Selection Waterfall' tables (sparse matrices) by coordinates.

Usage: python -I kemet_matrix.py <kemet_pdf> <out_json> <pages e.g. 4,5,6,7,8>
Each cell (cap code row x case/voltage column) -> thickness code (+ footnote superscript flag).
Columns are derived from the 'Voltage Code' header row; chars are assigned to the nearest column.
"""
import json
import re
import sys
from collections import Counter, defaultdict

import pdfplumber

VOLT = {"9": 6.3, "8": 10, "4": 16, "3": 25, "6": 35, "5": 50, "1": 100, "2": 200, "A": 250}


def main() -> None:
    pdf_path, out_path, pages = sys.argv[1], sys.argv[2], [int(p) for p in sys.argv[3].split(",")]
    result: dict = {"cells": [], "pages": {}}
    with pdfplumber.open(pdf_path) as pdf:
        for pno in pages:
            page = pdf.pages[pno - 1]
            words = page.extract_words(extra_attrs=["size"])
            # header row with voltage codes: the line whose text starts with 'Voltage Code' (topmost)
            vc_words = [w for w in words if w["text"] == "Voltage"]
            vc_words.sort(key=lambda w: w["top"])
            vc = vc_words[0]
            line = [w for w in words if abs(w["top"] - vc["top"]) < 2.5 and w["x0"] > vc["x1"] + 15]
            line.sort(key=lambda w: w["x0"])
            # case-size header (e.g. C0402C) above the voltage line
            cases = [w for w in words if re.fullmatch(r"C\d{4}C", w["text"]) and w["top"] < vc["top"]]
            cases.sort(key=lambda w: w["x0"])
            cols = []
            group = -1
            prev_v = 1e9
            for w in line:
                v = VOLT.get(w["text"], 0)
                if v <= prev_v:  # voltage order restarts -> next case-size group
                    group += 1
                prev_v = v
                xc = (w["x0"] + w["x1"]) / 2
                cols.append({"case": cases[group]["text"][1:5], "vcode": w["text"], "volt": VOLT.get(w["text"]), "xc": xc})
            if group + 1 != len(cases):
                print(f"WARNING page {pno}: {group + 1} column groups vs {len(cases)} case headers")
            pitch = min(b["xc"] - a["xc"] for a, b in zip(cols, cols[1:]))
            x_min = cols[0]["xc"] - pitch * 0.6
            # row labels: cap code column = words directly below 'Cap Code' header, matching 3 digits or ranges
            bottom_hdr = max(w["top"] for w in words if w["text"] == "Voltage")
            code_words = [
                w for w in words
                if re.fullmatch(r"\d{3}\*{0,2}", w["text"]) and w["x1"] < cols[0]["xc"] - pitch
                and vc["top"] + 15 < w["top"] < bottom_hdr - 15
            ]
            x0s = Counter(round(w["x0"]) for w in code_words)
            mode_x0 = x0s.most_common(1)[0][0]
            cx0 = mode_x0 - 16
            cx1 = mode_x0 + 22
            rows = []
            for w in words:
                if cx0 <= w["x0"] <= cx1 and vc["top"] + 20 < w["top"] < bottom_hdr - 20:
                    rows.append(w)
            # merge words on the same row (e.g. '100 - 200*')
            by_y = defaultdict(list)
            for w in rows:
                by_y[round(w["top"])].append(w)
            chars = page.chars
            main_size = 0.0
            for key in sorted(by_y):
                ws = sorted(by_y[key], key=lambda w: w["x0"])
                label = " ".join(w["text"] for w in ws)
                top = min(w["top"] for w in ws) - 1.5
                bot = max(w["bottom"] for w in ws) + 1.5
                rowchars = [c for c in chars if c["x0"] >= x_min and top <= (c["top"] + c["bottom"]) / 2 <= bot]
                if not main_size and rowchars:
                    main_size = max(c["size"] for c in rowchars)
                cells = defaultdict(list)
                for c in rowchars:
                    if not c["text"].strip():
                        continue
                    xc = (c["x0"] + c["x1"]) / 2
                    j = min(range(len(cols)), key=lambda k: abs(cols[k]["xc"] - xc))
                    if abs(cols[j]["xc"] - xc) <= pitch * 0.75:
                        cells[j].append(c)
                for j, cs in sorted(cells.items()):
                    cs.sort(key=lambda c: c["x0"])
                    big = "".join(c["text"] for c in cs if c["size"] >= main_size - 0.6)
                    small = "".join(c["text"] for c in cs if c["size"] < main_size - 0.6)
                    result["cells"].append({
                        "page": pno, "cap_label": label, "case": cols[j]["case"], "vcode": cols[j]["vcode"],
                        "volt": cols[j]["volt"], "thickness_code": big, "footnote": small or None,
                    })
            result["pages"][pno] = {"columns": cols, "pitch": round(pitch, 2), "main_size": main_size}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)
    print("cells:", len(result["cells"]))
    for pno, info in result["pages"].items():
        print(pno, "cols", len(info["columns"]), "cases", sorted({c["case"] for c in info["columns"]}), "pitch", info["pitch"], "size", info["main_size"])


if __name__ == "__main__":
    main()
