"""Built-in MLCC series.

KEMET, YAGEO and Samsung are *matrix* templates: only cells listed in the manufacturer's
availability tables (``data_*.py``) are generated, together with the thickness (height) of each
cell. Murata GRM is a catalog of common X7R parts (the individual specification code of a GRM part
number is set per type by Murata, so values cannot be generated freely), checked part by part against
Murata's product database and decoded with Murata's part-numbering key.
"""
from __future__ import annotations

from collections import defaultdict

from ...units import parse_value
from ..formats import ValueFormat, decode_value, encode_value
from ..model import AvailabilityCell, CatalogEntry, CodeOption, MpnTemplate, Source, Variable
from . import data_kemet, data_samsung_cl, data_yageo_cc
from .common import CAPACITOR_FIELDS, chip_size, custom_chip, mm, size_options

_X7R = {"temperature": "-55 … 125"}
_PF = ValueFormat(style="eia3", scale=1e-12)


def _tol(code: str, percent: str, *, default: bool = False, note: str | None = None) -> CodeOption:
    attrs = {"row_note": note} if note else {}
    return CodeOption(code=code, value=f"±{percent}%", label=f"±{percent} %", default=default, attrs=attrs)


def _voltage_options(codes: dict[str, str]) -> list[CodeOption]:
    return [CodeOption(code=code, value=volts, label=volts.replace(".", ",").replace("V", " V"))
            for code, volts in codes.items()]


def _thickness_attrs(nominal: float, tolerance: float, tape: str, code: str) -> dict[str, str]:
    return {"height": mm(nominal + tolerance), "thickness_nom": f"{nominal:g}", "thickness_tol": f"{tolerance:g}",
            "thickness_code": code, "tape": tape}


# --------------------------------------------------------------------------- KEMET C-series X7R

_KEMET_URL = "https://content.kemet.com/datasheets/KEM_C1002_X7R_SMD.pdf"
_KEMET_VOLTAGES = {"9": "6.3V", "8": "10V", "4": "16V", "3": "25V", "6": "35V", "5": "50V", "1": "100V", "2": "200V",
                   "A": "250V"}
_KEMET_SIZES = ["0402", "0603", "0805", "1206", "1210", "1805", "1808", "1812", "1825", "2220", "2225"]
_KEMET_FORMAT = ValueFormat(style="eia3", scale=1e-12, small_multipliers={"9": -1, "8": -2})
# "Capacitor Marking (Optional)", datasheet p. 20: laser marking is not available on EIA 0402 case size
# devices and on X7R capacitance values up to these limits (pF); 1805 is not listed (no limit)
_KEMET_UNMARKABLE_PF: dict[str, float] = {
    "0603": 170, "0805": 150, "1206": 910, "1210": 2000, "1808": 3900, "1812": 6700, "1825": 18000,
    "2220": 27000, "2225": 33000,
}
_KEMET_NO_MARKING = ["0402"]


def kemet_markable(case: str, cap_code: str) -> bool:
    """True if KEMET offers laser marking (C-Spec TM/7040/7215) for this X7R cell."""
    if case in _KEMET_NO_MARKING:
        return False
    limit = _KEMET_UNMARKABLE_PF.get(case)
    capacitance_pf = decode_value(cap_code, _KEMET_FORMAT) / 1e-12
    return limit is None or capacitance_pf > limit * (1 + 1e-9)


def kemet_thickness() -> dict[str, tuple[str, float, float, str]]:
    """KEMET thickness code -> (case, nominal mm, tolerance mm, tape)."""
    out: dict[str, tuple[str, float, float, str]] = {}
    for line in data_kemet.THICKNESS.strip().splitlines():
        code, case, nominal, tol, tape = line.split()
        out[code] = (case, float(nominal), float(tol), tape)
    return out


def kemet_x7r() -> MpnTemplate:
    thickness = kemet_thickness()
    cells: list[AvailabilityCell] = []
    for line in data_kemet.CELLS.strip().splitlines():
        case, vcode, cap, thick, tols = line.split()
        _case, nominal, tol, tape = thickness[thick]
        attrs = {**_thickness_attrs(nominal, tol, tape, thick), "markable": "1" if kemet_markable(case, cap) else "0"}
        cells.append(AvailabilityCell(size=case, value=cap, codes={"voltage": vcode}, tolerances=list(tols),
                                      attrs=attrs))
    marked = {"markable": ["1"]}
    big = [s for s in _KEMET_SIZES if s not in ("0402", "0603")]
    custom = {
        "1805": custom_chip("C", L=(4.0, 5.0), W=(0.89, 1.65), T=(0.25, 0.95), H=(0.8, 1.15)),
        "1825": custom_chip("C", L=(4.2, 4.8), W=(6.0, 6.8), T=(0.25, 0.95), H=(0.95, 1.65)),
        "2225": custom_chip("C", L=(5.2, 6.0), W=(6.0, 6.8), T=(0.25, 0.95), H=(0.85, 1.55)),
    }
    return MpnTemplate(
        id="kemet-c-x7r",
        manufacturer="KEMET",
        series="C-Serie X7R (C1002)",
        category="Capacitors",
        title="KEMET C-Serie X7R – Vielschicht-Keramikkondensatoren 6,3 … 250 V",
        description=("Kommerzielle X7R-MLCC 0402 … 2225, ±5/10/20 %. Es werden nur Kombinationen aus Baugröße, "
                     "Spannung und Kapazität erzeugt, die in den Lieferbarkeitstabellen 1A–1C stehen; die Bauhöhe "
                     "folgt aus dem Dickencode der Zelle (Tabelle 2A). Zellen mit Fußnote ¹ nur in ±10/20 %. "
                     "Laserbeschriftung (TM, 7040, 7215) nicht für 0402 und kleine Kapazitäten (Datenblatt S. 20) – "
                     "dort wird die gleichwertige unbeschriftete Rolle verwendet."),
        datasheet_url=_KEMET_URL,
        pattern="C{size}C{value}{tolerance}{voltage}{dielectric}AC{cspec}",
        value_unit="F",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(_KEMET_SIZES)),
            Variable(name="value", label="Kapazität", format=_KEMET_FORMAT),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("J", "5"), _tol("K", "10", default=True), _tol("M", "20")]),
            Variable(name="voltage", label="Nennspannung", options=_voltage_options(_KEMET_VOLTAGES)),
            Variable(name="dielectric", label="Dielektrikum", options=[CodeOption(code="R", value="X7R", label="X7R")]),
            Variable(name="cspec", label="Verpackung (C-Spec)", options=[
                CodeOption(code="TU", label="TU: Rolle 7\", unbeschriftet", default=True, attrs={"reel": "7"}),
                CodeOption(code="", label="ohne: Beutel (lose)", attrs={"reel": "bulk"}),
                CodeOption(code="7411", label="7411: Rolle 13\", unbeschriftet", sizes=["0402", "0603"],
                           attrs={"reel": "13"}),
                CodeOption(code="7210", label="7210: Rolle 13\", unbeschriftet", sizes=big, attrs={"reel": "13"}),
                CodeOption(code="TM", label="TM: Rolle 7\", beschriftet", sizes=["0603", *big], requires=marked,
                           attrs={"reel": "7"}),
                CodeOption(code="7040", label="7040: Rolle 13\", beschriftet", sizes=["0603"], requires=marked,
                           attrs={"reel": "13"}),
                CodeOption(code="7215", label="7215: Rolle 13\", beschriftet", sizes=big, requires=marked,
                           attrs={"reel": "13"}),
            ]),
        ],
        sizes=[chip_size(s, footprint=custom.get(s)) for s in _KEMET_SIZES],
        availability=cells,
        availability_keys=["voltage"],
        attrs=dict(_X7R),
        fields=dict(CAPACITOR_FIELDS),
        sources=[Source(title="Surface Mount Multilayer Ceramic Chip Capacitors X7R Dielectric, 6.3-250 VDC",
                        url=_KEMET_URL, document="C1002_X7R", revision="2026-09-01", pages="2-12, 20",
                        note="Grundwahrheit tests/data/corpus/groundtruth/kemet_C1002_X7R_series.json (3342 Zellen); "
                             "S. 20: Laserbeschriftung nicht für 0402 und X7R-Werte bis 170 pF (0603) … 0,033 µF "
                             "(2225)")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- YAGEO CC X7R

_YAGEO_CC_URL = "https://www.yageo.com/upload/media/product/productsearch/datasheet/mlcc/UPY-GPHC_X7R_6.3V-to-250V_24.pdf"
_YAGEO_CC_VOLTAGES = {"5": "6.3V", "6": "10V", "7": "16V", "8": "25V", "9": "50V", "0": "100V", "A": "200V",
                      "Y": "250V"}
# dimension code -> (thickness nominal mm, tolerance mm, tape) – Tables 2-8
_YAGEO_CC_THICKNESS: dict[str, tuple[float, float, str]] = {
    "BA": (0.3, 0.03, "paper"), "CA": (0.5, 0.05, "paper"), "CD": (0.5, 0.2, "paper"),
    "DA": (0.8, 0.1, "paper"), "DB": (0.8, 0.15, "paper"), "DC": (0.8, 0.2, "paper"),
    "E0": (0.6, 0.1, "paper"), "EA": (0.85, 0.1, "paper"), "EB": (1.25, 0.2, "blister"),
    "F0": (0.85, 0.1, "paper"), "F1": (1.0, 0.1, "blister"), "FA": (1.15, 0.1, "blister"),
    "FB": (1.25, 0.2, "blister"), "FC": (1.6, 0.2, "blister"), "FD": (1.6, 0.3, "blister"),
    "G0": (0.85, 0.1, "blister"), "GA": (1.25, 0.2, "blister"), "G2": (1.6, 0.2, "blister"),
    "GB": (1.9, 0.2, "blister"), "G3": (2.0, 0.2, "blister"), "GC": (2.5, 0.2, "blister"),
    "GD": (2.5, 0.3, "blister"), "JA": (0.85, 0.1, "blister"), "JB": (1.25, 0.2, "blister"),
    "JC": (1.6, 0.2, "blister"), "KA": (1.15, 0.1, "blister"),
}
_YAGEO_CC_SIZES = ["0201", "0402", "0603", "0805", "1206", "1210", "1812", "2220"]


def yageo_cc_x7r() -> MpnTemplate:
    by_volts = {v: k for k, v in _YAGEO_CC_VOLTAGES.items()}
    cells: list[AvailabilityCell] = []
    for line in data_yageo_cc.CELLS.strip().splitlines():
        size, volts, cap_pf, code = line.split()
        nominal, tol, tape = _YAGEO_CC_THICKNESS[code]
        value_code = encode_value(float(cap_pf) * 1e-12, _PF)
        cells.append(AvailabilityCell(size=size, value=value_code, codes={"voltage": by_volts[f"{float(volts):g}V"]},
                                      attrs=_thickness_attrs(nominal, tol, tape, code)))
    return MpnTemplate(
        id="yageo-cc-x7r",
        manufacturer="YAGEO",
        series="CC X7R",
        category="Capacitors",
        title="YAGEO CC X7R – Vielschicht-Keramikkondensatoren 6,3 … 250 V",
        description=("Allzweck-MLCC X7R 0201 … 2220 (E6-Werte laut Lieferbarkeitstabellen 2–7). Die Gurtart "
                     "(R Papier/K Blister, 7\") folgt aus der Dickenklasse der Zelle (Tabelle 8). ±5 % ist laut "
                     "YAGEO nicht für alle Werte lieferbar."),
        datasheet_url=_YAGEO_CC_URL,
        pattern="CC{size}{tolerance}{packing}{dielectric}{voltage}BB{value}",
        value_unit="F",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(_YAGEO_CC_SIZES)),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("J", "5", note="±5 % ist laut YAGEO nicht für alle Werte lieferbar – "
                                    "vor der Bestellung anfragen."),
                _tol("K", "10", default=True), _tol("M", "20")]),
            Variable(name="packing", label="Gurtart", options=[
                CodeOption(code="R", label="R: Papiergurt, Rolle 7\"", requires={"tape": ["paper"]}, default=True,
                           attrs={"reel": "7"}),
                CodeOption(code="K", label="K: Blistergurt, Rolle 7\"", requires={"tape": ["blister"]}, default=True,
                           attrs={"reel": "7"}),
                CodeOption(code="P", label="P: Papiergurt, Rolle 13\"", requires={"tape": ["paper"]},
                           attrs={"reel": "13"}),
                CodeOption(code="F", label="F: Blistergurt, Rolle 13\"", requires={"tape": ["blister"]},
                           attrs={"reel": "13"})]),
            Variable(name="dielectric", label="Dielektrikum", options=[CodeOption(code="X7R", value="X7R")]),
            Variable(name="voltage", label="Nennspannung", options=_voltage_options(_YAGEO_CC_VOLTAGES)),
            Variable(name="value", label="Kapazität", format=_PF),
        ],
        sizes=[chip_size(s) for s in _YAGEO_CC_SIZES],
        availability=cells,
        availability_keys=["voltage"],
        attrs=dict(_X7R),
        fields=dict(CAPACITOR_FIELDS),
        sources=[Source(title="Surface-Mount Ceramic Multilayer Capacitors, General Purpose & High Capacitance, "
                              "Class 2, X7R 6.3 V to 250 V", url=_YAGEO_CC_URL, document="UPY-GPHC_X7R",
                        revision="V.23, 13-Feb-2023", pages="2-10",
                        note="Geprüft an V.23 (Kopie über static.chipdip.ru/lib/017/DOC043017719.pdf); die "
                             "YAGEO-Adresse liefert inzwischen eine neuere Fassung.")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- Samsung CL X7R

_SAMSUNG_URL = "https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/7133/MLCC.pdf"
_SAMSUNG_SIZE_CODES = {"01005": "02", "0201": "03", "0402": "05", "0603": "10", "0805": "21", "1206": "31",
                       "1210": "32"}
_SAMSUNG_VOLTAGES = {"Q": "6.3V", "P": "10V", "O": "16V", "A": "25V", "L": "35V", "B": "50V", "C": "100V",
                     "D": "200V", "E": "250V", "G": "500V", "H": "630V", "I": "1000V", "J": "2000V"}
# (size, thickness code) -> (nominal mm, tolerance mm) – catalog "THICKNESS CODE" table
_SAMSUNG_THICKNESS: dict[tuple[str, str], tuple[float, float]] = {
    ("01005", "2"): (0.20, 0.02), ("0201", "3"): (0.30, 0.03), ("0402", "5"): (0.50, 0.05),
    ("0603", "8"): (0.80, 0.10), ("0805", "A"): (0.65, 0.10), ("0805", "C"): (0.85, 0.10),
    ("0805", "F"): (1.25, 0.10), ("0805", "Q"): (1.25, 0.15), ("1206", "C"): (0.85, 0.15),
    ("1206", "F"): (1.25, 0.15), ("1206", "H"): (1.60, 0.20), ("1210", "F"): (1.25, 0.20),
    ("1210", "H"): (1.60, 0.20), ("1210", "I"): (2.00, 0.20), ("1210", "J"): (2.50, 0.20),
}


def _samsung_tape(size: str, nominal: float) -> str:
    """Catalog packaging table: paper up to 0.85 mm (1210 always embossed)."""
    return "paper" if size != "1210" and nominal <= 0.85 + 1e-9 else "embossed"


def samsung_thickness_rows() -> list[tuple[str, str, str, str, str, float]]:
    """Catalog lineup rows (size, voltage code, cap code, tolerance, thickness code, T max)."""
    by_code = {v: k for k, v in _SAMSUNG_SIZE_CODES.items()}
    rows = []
    for line in data_samsung_cl.CELLS.strip().splitlines():
        size_code, vcode, cap, tol, thick, tmax = line.split()
        rows.append((by_code[size_code], vcode, cap, tol, thick, float(tmax)))
    return rows


def samsung_cl_x7r() -> MpnTemplate:
    grouped: dict[tuple[str, str, str, str], list[str]] = defaultdict(list)
    for size, vcode, cap, tol, thick, _tmax in samsung_thickness_rows():
        grouped[(size, vcode, cap, thick)].append(tol)
    cells = []
    for (size, vcode, cap, thick), tols in grouped.items():
        nominal, tol_mm = _SAMSUNG_THICKNESS[(size, thick)]
        cells.append(AvailabilityCell(size=size, value=cap, codes={"voltage": vcode, "thickness": thick},
                                      tolerances=sorted(set(tols)),
                                      attrs=_thickness_attrs(nominal, tol_mm, _samsung_tape(size, nominal), thick)))
    thickness_options = [
        CodeOption(code=code, label=f"{code}: {nominal:.2f} ± {tol:.2f} mm".replace(".", ","), sizes=[size])
        for (size, code), (nominal, tol) in _SAMSUNG_THICKNESS.items()
    ]
    sizes = list(_SAMSUNG_SIZE_CODES)
    return MpnTemplate(
        id="samsung-cl-x7r",
        manufacturer="Samsung Electro-Mechanics",
        series="CL X7R (Standard)",
        category="Capacitors",
        title="Samsung CL X7R – Vielschicht-Keramikkondensatoren",
        description=("X7R-MLCC 01005 … 1210 aus dem Samsung-Katalog (Januar 2024, Standardausführung NNN). Dicken- "
                     "und Verpackungscode (C Papier bis 0,85 mm, E Blister darüber) folgen aus der Katalogzeile. "
                     "Lieferbarkeit vor der Bestellung prüfen – der Katalog ist nicht tagesaktuell."),
        datasheet_url=_SAMSUNG_URL,
        pattern="CL{size}{dielectric}{value}{tolerance}{voltage}{thickness}NNN{packaging}",
        value_unit="F",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes, _SAMSUNG_SIZE_CODES)),
            Variable(name="dielectric", label="Dielektrikum",
                     options=[CodeOption(code="B", value="X7R", label="B: X7R")]),
            Variable(name="value", label="Kapazität", format=_PF),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("J", "5"), _tol("K", "10", default=True), _tol("M", "20")]),
            Variable(name="voltage", label="Nennspannung", options=_voltage_options(_SAMSUNG_VOLTAGES)),
            Variable(name="thickness", label="Dickencode", options=thickness_options),
            Variable(name="packaging", label="Verpackung", options=[
                CodeOption(code="C", label="C: Papiergurt, Rolle 7\"", requires={"tape": ["paper"]}, default=True,
                           attrs={"reel": "7"}),
                CodeOption(code="E", label="E: Blistergurt, Rolle 7\"", requires={"tape": ["embossed"]},
                           default=True, attrs={"reel": "7"})]),
        ],
        sizes=[chip_size(s) for s in sizes],
        availability=cells,
        availability_keys=["voltage", "thickness"],
        availability_certain=False,
        attrs=dict(_X7R),
        fields=dict(CAPACITOR_FIELDS),
        sources=[Source(title="Samsung Electro-Mechanics MLCC Catalog", url=_SAMSUNG_URL, revision="January 2024",
                        pages="6-8 (Teilenummern), 15 (X7R-Tabelle), 18-80 (Produktliste), 135 (Verpackung)")],
        verified=True,
        notes=["Mehrere Dickenvarianten eines Werts (z. B. 0805 100 nF in 0,85 und 1,25 mm) sind eigene Bauteile."],
        builtin=True,
    )


# --------------------------------------------------------------------------- Murata GRM (catalog)

_MURATA_URL = "https://www.murata.com/en-us/products/capacitor/ceramiccapacitor/overview/lineup/smd/grm"
_MURATA_NUMBERING_URL = "https://pim.murata.com/asset/pim4/ceramicCapacitorSMD/SMD-EN_PDF_CERAMICCAPACITORSMD"
_MURATA_DETAILS_URL = "https://pim.murata.com/en-us/pim/details/?partNum={part}%23"
_MURATA_SPEC_EXAMPLE_URL = ("https://pim.murata.com/asset/pim4/ceramicCapacitorSMD/"
                            "GRM155R71H102KA01-01A-EN_PDF_CERAMICCAPACITORSMD")
_MURATA_CHECKED = "08.10.2026"
# Part Numbering (pim.murata.com, p. 2): ❷ chip dimensions L×W
_MURATA_SIZE_CODES = {"0402": "15", "0603": "18", "0805": "21", "1206": "31", "1210": "32"}
# ❸ dimension T (p. 2): code -> thickness
_MURATA_THICKNESS = {"3": "0.3mm", "5": "0.5mm", "6": "0.6mm", "7": "0.7mm", "8": "0.8mm", "9": "0.85mm",
                     "A": "1.0mm", "M": "1.15mm", "B": "1.25mm", "Q": "1.5mm", "C": "1.6mm", "D": "2.0mm",
                     "E": "2.5mm"}
# ❺ rated voltage (p. 4)
_MURATA_VOLTAGES = {"0J": "6.3V", "1A": "10V", "1C": "16V", "1E": "25V", "YA": "35V", "1H": "50V", "1J": "63V",
                    "1K": "80V", "2A": "100V", "2D": "200V", "2E": "250V"}
# ❾ packaging (p. 4; V = ø330 mm paper W8P1 in the product data of 0402 types)
_MURATA_PACKAGING: list[tuple[str, str, str]] = [
    ("D", "D: Papiergurt, Rolle Ø 180 mm", "paper"), ("E", "E: Papiergurt, Rolle Ø 180 mm", "paper"),
    ("W", "W: Papiergurt, Rolle Ø 180 mm", "paper"), ("J", "J: Papiergurt, Rolle Ø 330 mm", "paper"),
    ("F", "F: Papiergurt, Rolle Ø 330 mm", "paper"), ("V", "V: Papiergurt, Rolle Ø 330 mm", "paper"),
    ("L", "L: Blistergurt, Rolle Ø 180 mm", "embossed"), ("K", "K: Blistergurt, Rolle Ø 330 mm", "embossed"),
    ("T", "T: Schüttgut im Tray", "bulk"),
]
_TBD = "To be discontinued"
# Murata product database (pim.murata.com, products/search), checked 08.10.2026:
# part number (ø180 mm reel), size, capacitance, rated voltage, T nominal, T tolerance (mm), status, successor
_MURATA_GRM: list[tuple[str, str, str, str, float, float, str, str | None]] = [
    ("GRM155R71H102KA01D", "0402", "1nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71H472KA01D", "0402", "4.7nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71H103KA88D", "0402", "10nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71H223KA12D", "0402", "22nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71H473KE14D", "0402", "47nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71C104KA88D", "0402", "100nF", "16V", 0.5, 0.05, "In Production", None),
    ("GRM155R71H104KE14D", "0402", "100nF", "50V", 0.5, 0.05, "In Production", None),
    ("GRM155R71C224KA12D", "0402", "220nF", "16V", 0.5, 0.05, "In Production", None),
    ("GRM155R71A474KE01D", "0402", "470nF", "10V", 0.5, 0.05, "In Production", None),
    ("GRM188R71H103KA01D", "0603", "10nF", "50V", 0.8, 0.1, _TBD, "GRM155R71H103KA88"),
    ("GRM188R71H104KA93D", "0603", "100nF", "50V", 0.8, 0.1, _TBD, "GRM155R71H104KE14"),
    ("GRM188R71H224KAC4D", "0603", "220nF", "50V", 0.8, 0.1, "In Production", None),
    ("GRM188R71E474KA12D", "0603", "470nF", "25V", 0.8, 0.1, "In Production", None),
    ("GRM188R71C105KA12D", "0603", "1µF", "16V", 0.8, 0.1, _TBD, "GRM155C71C105KE11"),
    ("GRM188R71A225KE15D", "0603", "2.2µF", "10V", 0.8, 0.1, "In Production", None),
    ("GRM21BR71H104KA01L", "0805", "100nF", "50V", 1.25, 0.1, _TBD, "GRM155R71H104KE14"),
    ("GRM21BR71H474KA88L", "0805", "470nF", "50V", 1.25, 0.1, "In Production", None),
    ("GRM21BR71C105KA01L", "0805", "1µF", "16V", 1.25, 0.1, "In Production", None),
    ("GRM21BR71E225KE11L", "0805", "2.2µF", "25V", 1.25, 0.15, "In Production", None),
    ("GRM21BR71C475KE51L", "0805", "4.7µF", "16V", 1.25, 0.15, "In Production", None),
    ("GRM21BR71A106KA73L", "0805", "10µF", "10V", 1.25, 0.15, "In Production", None),
    ("GRM31CR71H105KA61L", "1206", "1µF", "50V", 1.6, 0.2, "In Production", None),
    ("GRM31CR71H475KA12L", "1206", "4.7µF", "50V", 1.6, 0.2, "In Production", None),
    ("GRM31CR71E106KA12L", "1206", "10µF", "25V", 1.6, 0.2, "In Production", None),
    ("GRM31CR71A226KE15L", "1206", "22µF", "10V", 1.6, 0.2, "In Production", None),
    ("GRM32ER71C226KEA8L", "1210", "22µF", "16V", 2.5, 0.2, "In Production", None),
    ("GRM32ER71E226KE15L", "1210", "22µF", "25V", 2.5, 0.2, "In Production", None),
    ("GRM32ER71A476KE15L", "1210", "47µF", "10V", 2.5, 0.2, "In Production", None),
]
_MURATA_LIFECYCLE = {"In Production": None, "NRND": "NRND", _TBD: "Abgekündigt"}


def murata_codes(mpn: str) -> dict[str, str]:
    """Codes of a GRM part number by position (Part Numbering ❶–❾): GRM 18 8 R7 1H 104 K A93 D."""
    if len(mpn) != 18 or not mpn.startswith("GRM"):
        raise ValueError(f"Murata-Teilenummer {mpn} hat nicht den GRM-Aufbau (18 Zeichen).")
    return {"size": mpn[3:5], "thickness": mpn[5], "dielectric": mpn[6:8], "voltage": mpn[8:10],
            "value": mpn[10:13], "tolerance": mpn[13], "spec": mpn[14:17], "packaging": mpn[17]}


def murata_grm() -> MpnTemplate:
    by_size_code = {code: size for size, code in _MURATA_SIZE_CODES.items()}
    tape_of = {code: tape for code, _label, tape in _MURATA_PACKAGING}
    entries = []
    specs: list[str] = []
    for mpn, size, cap, volts, nominal, tol, status, successor in _MURATA_GRM:
        codes = murata_codes(mpn)
        expected_value = encode_value(parse_value(cap, "F") or 0.0, _PF)
        if (by_size_code.get(codes["size"]) != size or _MURATA_VOLTAGES.get(codes["voltage"]) != volts
                or codes["value"] != expected_value or codes["dielectric"] != "R7"
                or _MURATA_THICKNESS.get(codes["thickness"]) != mm(nominal)):  # pragma: no cover - data guard
            raise ValueError(f"Murata-Tabelle inkonsistent: {mpn} ({size}, {cap}, {volts}, {nominal} mm)")
        if codes["spec"] not in specs:
            specs.append(codes["spec"])
        attrs = {**_thickness_attrs(nominal, tol, tape_of[codes["packaging"]], codes["thickness"]),
                 "datasheet_url": _MURATA_DETAILS_URL.format(part=mpn[:-1])}
        lifecycle = _MURATA_LIFECYCLE[status]
        if lifecycle:
            attrs["lifecycle"] = lifecycle
            attrs["row_note"] = (f"Murata-Lieferstatus „{status}“ (Stand {_MURATA_CHECKED})"
                                 + (f" – Nachfolger laut Murata: {successor}." if successor else "."))
        entries.append(CatalogEntry(mpn=mpn, size=size, value=cap,
                                    codes={k: v for k, v in codes.items() if k not in ("size", "value")},
                                    attrs=attrs))
    return MpnTemplate(
        id="murata-grm-x7r",
        manufacturer="Murata",
        series="GRM X7R (Auswahl)",
        category="Capacitors",
        title="Murata GRM X7R – Auswahl gängiger Typen",
        description=(f"{len(entries)} gängige X7R-Vielschicht-Keramikkondensatoren ±10 % in 0402 … 1210 (GRM, für "
                     "Konsumer- und Industriegeräte), je Typ gegen die Murata-Produktdatenbank geprüft (Stand "
                     f"{_MURATA_CHECKED}): Maße, Kapazität, Nennspannung, Verpackung, Lieferstatus. Von Murata "
                     "abgekündigte Typen („To be discontinued“) sind als „Abgekündigt“ markiert und nennen den "
                     "Nachfolger. Die Teilenummer folgt dem Murata-Schlüssel; der Steuercode (z. B. A93) ist je Typ "
                     "festgelegt – deshalb ein Katalog statt frei wählbarer Werte."),
        datasheet_url=_MURATA_URL,
        kind="catalog",
        pattern="GRM{size}{thickness}{dielectric}{voltage}{value}{tolerance}{spec}{packaging}",
        value_unit="F",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(list(_MURATA_SIZE_CODES), _MURATA_SIZE_CODES)),
            Variable(name="thickness", label="Dicke T", options=[
                CodeOption(code=code, value=text, label=f"{code}: {text.replace('mm', ' mm').replace('.', ',')}")
                for code, text in _MURATA_THICKNESS.items()]),
            Variable(name="dielectric", label="Temperaturcharakteristik",
                     options=[CodeOption(code="R7", value="X7R", label="R7: X7R (EIA)")]),
            Variable(name="voltage", label="Nennspannung", options=_voltage_options(_MURATA_VOLTAGES)),
            Variable(name="value", label="Kapazität", format=_PF),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("J", "5"), _tol("K", "10", default=True), _tol("M", "20")]),
            Variable(name="spec", label="Murata-Steuercode", options=[
                CodeOption(code=code, label=f"{code}: individuelle Spezifikation") for code in specs],
                help="❽ Individual Specification Code – je Typ von Murata festgelegt"),
            Variable(name="packaging", label="Verpackung", options=[
                CodeOption(code=code, label=label, attrs={"tape": tape}) for code, label, tape in _MURATA_PACKAGING]),
        ],
        sizes=[chip_size(s) for s in _MURATA_SIZE_CODES],
        catalog=entries,
        attrs=dict(_X7R),
        fields=dict(CAPACITOR_FIELDS),
        sources=[
            Source(title="Murata Part Numbering – Chip Multilayer Ceramic Capacitors (SMD)", url=_MURATA_NUMBERING_URL,
                   pages="1-4", revision=f"abgerufen {_MURATA_CHECKED}",
                   note="❶ Serie GRM, ❷ L×B (15 = 0402, 18 = 0603, 21 = 0805, 31 = 1206, 32 = 1210), ❸ Dicke T, "
                        "❹ Temperaturcharakteristik (R7 = X7R), ❺ Nennspannung, ❻ Kapazität in pF (3 Stellen), "
                        "❼ Toleranz (K = ±10 %), ❽ individuelle Spezifikation, ❾ Verpackung (D/E/W Papier Ø 180 mm, "
                        "J/F Papier Ø 330 mm, L Blister Ø 180 mm, K Blister Ø 330 mm)"),
            Source(title="Murata-Produktdatenbank (pim.murata.com) – Produktdetails je Teilenummer",
                   url=_MURATA_DETAILS_URL.format(part="GRM155R71H102KA01"), revision=f"Stand {_MURATA_CHECKED}",
                   note="Je Typ geprüft: L/B/T mit Toleranz, Kapazität und Toleranz, Nennspannung, X7R, "
                        "Verpackungscodes, Lieferstatus (In Production / To be discontinued) und Nachfolger – "
                        "abgefragt über die öffentliche Schnittstelle pimapi.murata.com (products/search), die die "
                        "Produktseiten speist. GRM32ER71H106KA12L (früher im Katalog) führt Murata nicht mehr."),
            Source(title="Murata Spezifikationsblatt GRM155R71H102KA01-01A (Beispiel)", url=_MURATA_SPEC_EXAMPLE_URL,
                   revision="Stand 18.06.2026", pages="2",
                   note="Teilenummernschlüssel und Maße 1,0 × 0,5 × 0,5 mm (±0,05 mm), Verpackung D: Papier Ø 180 mm"),
        ],
        verified=True,
        notes=[f"Lieferstatus laut Murata, Stand {_MURATA_CHECKED} – vor der Bestellung beim Hersteller prüfen.",
               "Die Teilenummer endet mit dem Verpackungscode: im Katalog die Rolle Ø 180 mm (D Papier, L Blister); "
               "J/K = Rolle Ø 330 mm."],
        builtin=True,
    )


CAPACITOR_TEMPLATES = [kemet_x7r, yageo_cc_x7r, samsung_cl_x7r, murata_grm]
