"""Built-in resistor series (thick-film chip resistors).

Every value below was read from the manufacturer datasheet cited in ``sources`` (rendered pages,
2026-10-07/08). Datasheet table rows map 1:1 to :class:`~partforge.domain.mpn.model.ValueRule`
objects; "10 Ω < R" bounds are written as the next E192 value (10.1 Ω), which keeps every E-series
value on the correct side.
"""
from __future__ import annotations

from collections.abc import Sequence

from ..formats import ValueFormat
from ..model import CodeOption, FormatOverride, JumperSpec, MpnTemplate, Source, ValueRule, Variable
from .common import E24, E24_E96, RESISTOR_FIELDS, chip_size, custom_chip, jumper_attrs, rule, size_options

_THICK_FILM = {"technology": "Dickschicht", "temperature": "-55 … 155"}


def _tol(code: str, percent: str, *, default: bool = False, **attrs: str) -> CodeOption:
    return CodeOption(code=code, value=f"±{percent}%", label=f"±{percent.replace('.', ',')} %", default=default,
                      attrs=dict(attrs))


def _jumper_tol(code: str) -> CodeOption:
    return CodeOption(code=code, label="Brücke (0 Ω)", attrs={"jumper_only": "1"})


def _banded(sizes: Sequence[str], tolerances: Sequence[str], series: Sequence[str],
            bands: Sequence[tuple[str, str, str]], extra_when: dict[str, Sequence[str]] | None = None,
            **attrs: str) -> list[ValueRule]:
    """One rule per TCR band: ``bands`` = (low, high, tcr text) inclusive ranges."""
    when: dict[str, Sequence[str]] = {"tolerance": tolerances, **(extra_when or {})}
    return [rule(when, [(lo, hi)], series, sizes=sizes, tcr=tcr, **attrs) for lo, hi, tcr in bands]


def _clip(bands: Sequence[tuple[str, str, str]], low: float, high: float) -> list[tuple[str, str, str]]:
    """Bands limited to [low, high] (Ω) – bands outside are dropped."""
    from ...units import parse_value

    out: list[tuple[str, str, str]] = []
    for lo, hi, tcr in bands:
        lo_v, hi_v = parse_value(lo, "Ω"), parse_value(hi, "Ω")
        assert lo_v is not None and hi_v is not None
        new_lo, new_hi = max(lo_v, low), min(hi_v, high)
        if new_lo <= new_hi:
            out.append((f"{new_lo:g}", f"{new_hi:g}", tcr))
    return out


# --------------------------------------------------------------------------- Vishay CRCW e3

_VISHAY_URL = "https://www.vishay.com/docs/20035/dcrcwe3.pdf"
# size: (P70 standard mode, Umax standard mode, height max mm, jumper Imax)
_VISHAY: dict[str, tuple[str, str, float, str]] = {
    "0402": ("0.063W", "50V", 0.40, "1.5A"),
    "0603": ("0.1W", "75V", 0.50, "2A"),
    "0805": ("0.125W", "150V", 0.60, "2.5A"),
    "1206": ("0.25W", "200V", 0.60, "3.5A"),
    "1210": ("0.5W", "200V", 0.60, "5A"),
    "1218": ("1W", "200V", 0.60, "7A"),
    "2010": ("0.75W", "400V", 0.70, "6A"),
    "2512": ("1W", "500V", 0.70, "7A"),
}


def vishay_crcw() -> MpnTemplate:
    sizes = list(_VISHAY)
    not_1218 = [s for s in sizes if s != "1218"]
    size_specs = []
    for size, (power, voltage, height, jumper) in _VISHAY.items():
        footprint = (custom_chip("R", L=(3.0, 3.3), W=(4.45, 4.75), T=(0.2, 0.6), H=(0.5, 0.6))
                     if size == "1218" else None)
        size_specs.append(chip_size(size, power=power, voltage=voltage, height=height, jumper_current=jumper,
                                    footprint=footprint))
    packaging = [
        CodeOption(code="ED", label="ED (ET7/ET3): Papier, 2 mm Teilung, 10 000 St., Ø 180 mm", sizes=["0402", "0603"]),
        CodeOption(code="EE", label="EE (EF4/ET8): Papier, 2 mm Teilung, 50 000 St., Ø 330 mm", sizes=["0402", "0603"]),
        CodeOption(code="EI", label="EI (ET2): Papier, 2 mm Teilung, 5000 St., Ø 180 mm", sizes=["0603"]),
        CodeOption(code="EA", label="EA (ET1): Papier, 4 mm Teilung, 5000 St., Ø 180 mm",
                   sizes=["0603", "0805", "1206", "1210"]),
        CodeOption(code="EC", label="EC (ET6): Papier, 4 mm Teilung, 20 000 St., Ø 330 mm",
                   sizes=["0603", "0805", "1206", "1210"]),
        CodeOption(code="EK", label="EK (ET9): Blister 12 mm, 4000 St., Ø 180 mm", sizes=["1218"]),
        CodeOption(code="EF", label="EF (E02): Blister 12 mm, 4000 St., Ø 180 mm", sizes=["2010"]),
        CodeOption(code="EG", label="EG (E67): Blister 12 mm, 8 mm Teilung, 2000 St., Ø 180 mm", sizes=["2512"]),
        CodeOption(code="EH", label="EH (E82): Blister 12 mm, 4 mm Teilung, 4000 St., Ø 180 mm", sizes=["2512"]),
    ]
    rules = [
        rule({"tolerance": ["F"], "tcr": ["K"]}, [("1", "10M")], E24_E96, sizes=not_1218),
        rule({"tolerance": ["F"], "tcr": ["K"]}, [("1", "2.2M")], E24_E96, sizes=["1218"]),
        rule({"tolerance": ["F"], "tcr": ["N"]}, [("1", "9.76")], E24_E96),
        rule({"tolerance": ["J"], "tcr": ["N"]}, [("1", "10M")], E24, sizes=not_1218),
        rule({"tolerance": ["J"], "tcr": ["N"]}, [("1", "2.2M")], E24, sizes=["1218"]),
    ]
    return MpnTemplate(
        id="vishay-crcw-e3",
        manufacturer="Vishay",
        series="D/CRCW e3",
        category="Resistors",
        title="Vishay CRCW e3 – Dickschicht-Chipwiderstände",
        description=("Standard-Dickschicht-Chipwiderstände 0402 … 2512, ±1 % (E24/E96, ±100 oder ±200 ppm/K) und "
                     "±5 % (E24, ±200 ppm/K), 0-Ω-Brücken. Leistung und Spannung von 0402/0603/0805 im "
                     "Standardbetrieb laut Datenblatt Seite 2."),
        datasheet_url=_VISHAY_URL,
        pattern="CRCW{size}{value}{tolerance}{tcr}{packaging}",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes)),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="rkm4")),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("F", "1", default=True, eseries="E24+E96"), _tol("J", "5", eseries="E24"), _jumper_tol("Z")]),
            Variable(name="tcr", label="Temperaturkoeffizient", options=[
                CodeOption(code="K", value="±100ppm/K", label="±100 ppm/K", default=True),
                CodeOption(code="N", value="±200ppm/K", label="±200 ppm/K"),
                CodeOption(code="0", label="Brücke (ohne TK)", attrs={"jumper_only": "1"}),
            ]),
            Variable(name="packaging", label="Verpackung", options=packaging,
                     defaults={"0402": "ED", "0603": "EA", "0805": "EA", "1206": "EA", "1210": "EA", "1218": "EK",
                               "2010": "EF", "2512": "EG"}),
        ],
        sizes=size_specs,
        rules=rules,
        jumper=JumperSpec(value_code="0000", codes={"tolerance": "Z", "tcr": "0"},
                          attrs=jumper_attrs("≤ 20 mΩ")),
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="D/CRCW e3 Standard Thick Film Chip Resistors", url=_VISHAY_URL,
                        document="Vishay Document Number 20035", revision="14-Apr-2026", pages="1-3, 11",
                        note="Testkorpus tests/data/corpus/pdfs/vishay_dcrcwe3.pdf (Grundwahrheit)")],
        verified=True,
        notes=["0402/0603/0805 im erweiterten Betrieb: 0,10/0,125/0,25 W (Driftgrenze 2 % statt 1 %).",
               "Brücken: TK-Code 0, Toleranzcode Z, Wertcode 0000."],
        builtin=True,
    )


# --------------------------------------------------------------------------- YAGEO RC_L

_YAGEO_RC_URL = "https://yageogroup.com/content/datasheet/asset/file/PYU-RC_GROUP_51_ROHS_L"
# taping reel codes with standard power (p. 2): 7"/10"/13" reel, 7D = 7" reel with twice the quantity (0201/0402)
_STD_REELS = ["07", "10", "13", "7D"]
_DOUBLE_POWER_REELS = ["7W", "3W"]  # 7"/13" reel with 2 x standard power (1 Ω … 1 MΩ, ±200 ppm/K)
# size: (power, double power or None, Umax, height max mm, jumper rated current)
_YAGEO_RC: dict[str, tuple[str, str | None, str, float, str]] = {
    "0201": ("0.05W", None, "25V", 0.26, "0.5A"),
    "0402": ("0.0625W", "0.125W", "50V", 0.40, "1A"),
    "0603": ("0.1W", "0.2W", "75V", 0.55, "1A"),
    "0805": ("0.125W", "0.25W", "150V", 0.60, "2A"),
    "1206": ("0.25W", "0.5W", "200V", 0.65, "2A"),
    "1210": ("0.5W", None, "200V", 0.65, "2A"),
    "1218": ("1W", None, "200V", 0.65, "6A"),
    "2010": ("0.75W", None, "200V", 0.65, "2A"),
    "2512": ("1W", "2W", "200V", 0.65, "2A"),
}
_P200, _P100, _P300 = "±200ppm/K", "±100ppm/K", "±300ppm/K"
# TCR bands per size (Table 2/3, standard power)
_YAGEO_RC_BANDS: dict[str, list[tuple[str, str, str]]] = {
    "0201": [("1", "10", "-100 … +350ppm/K"), ("10.1", "100M", _P200)],
    "0402": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "100M", _P200)],
    "0603": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200)],
    "0805": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200), ("24M", "100M", _P300)],
    "1206": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200), ("24M", "100M", _P300)],
    "1210": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200)],
    "1218": [("1", "10", _P200), ("10.1", "1M", _P100)],
    "2010": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200)],
    "2512": [("1", "10", _P200), ("10.1", "10M", _P100), ("10.1M", "22M", _P200)],
}
# tolerance -> (low, high) per size
_YAGEO_RC_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "0201": {"J": (1, 100e6), "F": (1, 10e6), "D": (1, 1e6), "B": (10, 1e6)},
    "0402": {"J": (1, 100e6), "F": (1, 10e6), "D": (1, 1e6), "B": (10, 1e6)},
    "0603": {"J": (1, 22e6), "F": (1, 10e6), "D": (1, 1e6), "B": (10, 1e6)},
    "0805": {"J": (1, 100e6), "F": (1, 10e6), "D": (1, 1e6), "B": (10, 1e6)},
    "1206": {"J": (1, 100e6), "F": (1, 10e6), "D": (1, 1e6), "B": (10, 1e6)},
    "1210": {"J": (1, 22e6), "F": (1, 10e6), "D": (10, 1e6), "B": (10, 1e6)},
    "1218": {"J": (1, 1e6), "F": (1, 1e6), "D": (10, 1e6), "B": (10, 1e6)},
    "2010": {"J": (1, 22e6), "F": (1, 10e6), "D": (10, 1e6), "B": (10, 1e6)},
    "2512": {"J": (1, 22e6), "F": (1, 10e6), "D": (10, 1e6), "B": (10, 1e6)},
}


def yageo_rc() -> MpnTemplate:
    sizes = list(_YAGEO_RC)
    double = [s for s, d in _YAGEO_RC.items() if d[1]]
    rules: list[ValueRule] = []
    for size in sizes:
        for tol, (low, high) in _YAGEO_RC_RANGES[size].items():
            series = E24 if tol == "J" else E24_E96
            rules += _banded([size], [tol], series, _clip(_YAGEO_RC_BANDS[size], low, high),
                             extra_when={"packaging": _STD_REELS})
    for size in double:
        power2 = _YAGEO_RC[size][1]
        assert power2 is not None
        rules.append(rule({"tolerance": ["J"], "packaging": _DOUBLE_POWER_REELS}, [("1", "1M")], E24, sizes=[size],
                          tcr=_P200, power=power2))
        rules.append(rule({"tolerance": ["F"], "packaging": _DOUBLE_POWER_REELS}, [("1", "1M")], E24_E96,
                          sizes=[size], tcr=_P200, power=power2))
    size_specs = []
    for size, (power, _p2, voltage, height, jumper) in _YAGEO_RC.items():
        extra = {"temperature": "-55 … 125"} if size == "0201" else None
        footprint = (custom_chip("R", L=(3.0, 3.2), W=(4.5, 4.7), T=(0.2, 0.6), H=(0.45, 0.65))
                     if size == "1218" else None)
        size_specs.append(chip_size(size, power=power, voltage=voltage, height=height, jumper_current=jumper,
                                    extra=extra, footprint=footprint))
    paper = [s for s in sizes if s not in ("1218", "2010", "2512")]
    reel13 = [*paper, "2010"]  # Table 4: 13" reels (paper; 2010 embossed)
    return MpnTemplate(
        id="yageo-rc-l",
        manufacturer="YAGEO",
        series="RC_L",
        category="Resistors",
        title="YAGEO RC_L – Dickschicht-Chipwiderstände",
        description=("Allzweck-Chipwiderstände 0201 … 2512, ±0,1/0,5/1 % (E24/E96) und ±5 % (E24), "
                     "0-Ω-Brücken (Toleranzcode J). Rollencode 07/10/13 = Rolle 7\"/10\"/13\" mit Standardleistung, "
                     "7D = Rolle 7\" mit doppelter Stückzahl (0201/0402), 7W/3W = Rolle 7\"/13\" mit doppelter "
                     "Leistung (nur 1 Ω … 1 MΩ, ±200 ppm/K). Der TK ist nicht Teil der Bestellnummer, er folgt aus "
                     "dem Wertebereich."),
        datasheet_url=_YAGEO_RC_URL,
        pattern="RC{size}{tolerance}{packing}-{packaging}{value}L",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes)),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("B", "0.1", eseries="E24+E96"), _tol("D", "0.5", eseries="E24+E96"),
                _tol("F", "1", default=True, eseries="E24+E96"), _tol("J", "5", eseries="E24")]),
            Variable(name="packing", label="Gurtart", options=[
                CodeOption(code="R", label="Papiergurt (R)", sizes=paper),
                CodeOption(code="K", label="Blistergurt (K)", sizes=["1218", "2010", "2512"])]),
            Variable(name="packaging", label="Rolle / Leistung", options=[
                CodeOption(code="07", label="07: Rolle 7\", Standardleistung", default=True, attrs={"reel": "7"}),
                CodeOption(code="10", label="10: Rolle 10\"", sizes=paper, attrs={"reel": "10"}),
                CodeOption(code="13", label="13: Rolle 13\"", sizes=reel13, attrs={"reel": "13"}),
                CodeOption(code="7D", label="7D: Rolle 7\", doppelte Stückzahl", sizes=["0201", "0402"],
                           attrs={"reel": "7"}),
                CodeOption(code="7W", label="7W: Rolle 7\", doppelte Leistung", sizes=double,
                           attrs={"power_mode": "doppelt", "reel": "7"}),
                CodeOption(code="3W", label="3W: Rolle 13\", doppelte Leistung",
                           sizes=[s for s in double if s in reel13], attrs={"power_mode": "doppelt", "reel": "13"}),
            ]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="rkm")),
        ],
        sizes=size_specs,
        rules=rules,
        jumper=JumperSpec(value_code="0R", codes={"tolerance": "J", "packaging": "07"},
                          allowed={"packaging": ["10", "13", "7D"]}, attrs=jumper_attrs("< 50 mΩ")),
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="General Purpose Chip Resistors RC_L series", url=_YAGEO_RC_URL,
                        document="PYu-RC_Group_51_RoHS_L", revision="V.14, 14-Nov-2025", pages="2, 4-7",
                        note="Rollencodes S. 2 (07, 10, 13, 7W, 7D, 3W; 7N/S nur 0075/0100), Rollengrößen je Baugröße "
                             "Tabelle 4 (S. 7): 13\" nur Papier 0201 … 1210 und Blister 2010.")],
        verified=True,
        notes=["Brücken werden mit Toleranzcode J bestellt (Datenblatt S. 2), auf Rolle 07, 10, 13 oder 7D – nicht "
               "mit doppelter Leistung (7W/3W).",
               "10 %/20 %-Typen (24 MΩ … 100 MΩ) und die Baugrößen 0075/0100 sind nicht enthalten."],
        builtin=True,
    )


# --------------------------------------------------------------------------- Panasonic ERJ

_PANA_1PCT_URL = "https://industrial.panasonic.com/cdbs/www-data/pdf/RDA0000/AOA0000C304.pdf"
_PANA_5PCT_URL = "https://industrial.panasonic.com/cdbs/www-data/pdf/RDA0000/AOA0000C301.pdf"
_NRND = {"lifecycle": "NRND"}
# size: (1 % code, 5 % code, power, limiting element voltage, height max, packaging, NRFND)
_PANA: dict[str, tuple[str, str, str, str, float, str, bool]] = {
    "0201": ("1GN", "1GN", "0.05W", "25V", 0.26, "C", False),
    "0402": ("2RK", "2GE", "0.1W", "50V", 0.40, "X", False),
    "0603": ("3EK", "3GE", "0.1W", "75V", 0.55, "V", False),
    "0805": ("6EN", "6GE", "0.125W", "150V", 0.70, "V", False),
    "1206": ("8EN", "8GE", "0.25W", "200V", 0.70, "V", True),
    "1210": ("14N", "14", "0.5W", "200V", 0.70, "U", True),
    "1812": ("12N", "12", "0.75W", "200V", 0.70, "U", True),
    "2010": ("12S", "12Z", "0.75W", "200V", 0.70, "U", True),
    "2512": ("1TN", "1T", "1W", "200V", 0.70, "U", True),
}
_PANA_PACKAGING = [
    CodeOption(code="C", label="C: Papiergurt gepresst, 2 mm Teilung, 15 000 St.", sizes=["0201"]),
    CodeOption(code="X", label="X: Papiergurt gestanzt, 2 mm Teilung, 10 000 St.", sizes=["0402"]),
    CodeOption(code="V", label="V: Papiergurt gestanzt, 4 mm Teilung, 5000 St.", sizes=["0603", "0805", "1206"]),
    CodeOption(code="U", label="U: Blistergurt, 4 mm Teilung, 5000 St. (2512: 4000 St.)",
               sizes=["1210", "1812", "2010", "2512"]),
]


def _pana_sizes(jumpers: dict[str, str] | None = None) -> list:
    specs = []
    for size, (_c1, _c5, power, voltage, height, _pack, nrfnd) in _PANA.items():
        extra = dict(_NRND) if nrfnd else {}
        if size == "0201":
            extra["temperature"] = "-55 … 125"
        specs.append(chip_size(size, power=power, voltage=voltage, height=height,
                               jumper_current=(jumpers or {}).get(size), extra=extra))
    return specs


def panasonic_erj_1pct() -> MpnTemplate:
    sizes = list(_PANA)
    ranges = {"0201": "1M", "0402": "1M", "0603": "1M", "0805": "2.2M", "1206": "2.2M", "1210": "1M", "1812": "1M",
              "2010": "1M", "2512": "1M"}
    rules = [rule({"tolerance": ["F"]}, [("10", high)], E24_E96, sizes=[size],
                  tcr=_P200 if size == "0201" else _P100) for size, high in ranges.items()]
    return MpnTemplate(
        id="panasonic-erj-1pct",
        manufacturer="Panasonic",
        series="ERJ (±1 %)",
        category="Resistors",
        title="Panasonic ERJ – Präzisions-Dickschicht-Chipwiderstände ±1 %",
        description=("ERJ-1GN/2RK/3EK/6EN/8EN/14N/12N/12S/1TN, ±1 %, E24/E96, 10 Ω … 1 MΩ (0805/1206 bis 2,2 MΩ). "
                     "1206 und größer sind laut Hersteller nicht für Neuentwicklungen empfohlen (NRFND). "
                     "Werte unter 10 Ω (ERJ-2RC) sind nicht enthalten."),
        datasheet_url=_PANA_1PCT_URL,
        pattern="ERJ-{size}{tolerance}{value}{packaging}",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes, {s: d[0] for s, d in _PANA.items()})),
            Variable(name="tolerance", label="Toleranz", options=[_tol("F", "1", default=True, eseries="E24+E96")]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="eia4")),
            Variable(name="packaging", label="Verpackung", options=list(_PANA_PACKAGING)),
        ],
        sizes=_pana_sizes(),
        rules=rules,
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="Precision Thick Film Chip Resistors ERJ type", url=_PANA_1PCT_URL,
                        document="AOA0000C304", revision="29-May-25", pages="2-4")],
        verified=True,
        notes=[("Bestellnummern werden mit Bindestrich geschrieben (ERJ-3EKF1002V); ohne Bindestrich werden sie "
                "ebenfalls erkannt.")],
        builtin=True,
    )


def panasonic_erj_5pct() -> MpnTemplate:
    sizes = list(_PANA)
    bands = [("1", "9.1", "-100 … +600ppm/K"), ("10", "1M", _P200), ("1.1M", "10M", "-400 … +150ppm/K")]
    rules: list[ValueRule] = []
    for size in sizes:
        high = 1e6 if size == "2512" else 10e6
        rules += _banded([size], ["J"], E24, _clip(bands, 1, high))
    jumpers = {"0201": "0.5A", "0402": "1A", "0603": "1A", "0805": "2A", "1206": "2A", "1210": "2A", "1812": "2A",
               "2010": "2A", "2512": "2A"}
    return MpnTemplate(
        id="panasonic-erj-5pct",
        manufacturer="Panasonic",
        series="ERJ (±5 %)",
        category="Resistors",
        title="Panasonic ERJ – Dickschicht-Chipwiderstände ±5 %",
        description=("ERJ-1GN/2GE/3GE/6GE/8GE/14/12/12Z/1T, ±5 % (E24), 1 Ω … 10 MΩ (2512: 1 MΩ) und "
                     "0-Ω-Brücken. 1206 und größer: nicht für Neuentwicklungen empfohlen (NRFND)."),
        datasheet_url=_PANA_5PCT_URL,
        pattern="ERJ-{size}{marking}{tolerance}{value}{packaging}",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes, {s: d[1] for s, d in _PANA.items()})),
            Variable(name="marking", label="Beschriftung", options=[
                CodeOption(code="Y", label="Y: Wert auf der Oberseite",
                           sizes=["0603", "0805", "1206", "1210", "1812", "2010", "2512"]),
                CodeOption(code="", label="ohne Beschriftung", sizes=["0201", "0402"])]),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("J", "5", default=True, eseries="E24"), _jumper_tol("0")]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="eia3")),
            Variable(name="packaging", label="Verpackung", options=list(_PANA_PACKAGING)),
        ],
        sizes=_pana_sizes(jumpers),
        rules=rules,
        jumper=JumperSpec(value_code="R00", codes={"tolerance": "0"},
                          attrs=jumper_attrs("≤ 50 mΩ")),
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="Thick Film Chip Resistors ERJ type", url=_PANA_5PCT_URL, document="AOA0000C301",
                        revision="22-Dec-22", pages="1-3")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- KOA RK73H / RK73B

_KOA_H_URL = "https://www.koaspeer.com/pdfs/RK73H.pdf"
_KOA_B_URL = "https://www.koaspeer.com/pdfs/RK73B.pdf"
_KOA_PACKAGING_URL = "https://www.koaspeer.com/pdfs/Appendix_A.pdf"
_KOA_CODES = {"0201": "1H", "0402": "1E", "0603": "1J", "0805": "2A", "1206": "2B", "1210": "2E", "2010": "W2H",
              "2512": "W3A"}
# size: (power, max working voltage, height max)
_KOA: dict[str, tuple[str, str, float]] = {
    "0201": ("0.05W", "25V", 0.26), "0402": ("0.1W", "75V", 0.40), "0603": ("0.1W", "75V", 0.55),
    "0805": ("0.25W", "150V", 0.60), "1206": ("0.25W", "200V", 0.70), "1210": ("0.5W", "200V", 0.70),
    "2010": ("0.75W", "200V", 0.70), "2512": ("1W", "200V", 0.70),
}


def _koa_variables(tolerances: list[CodeOption], fmt: ValueFormat) -> list[Variable]:
    sizes = list(_KOA)
    return [
        Variable(name="size", label="Baugröße", options=size_options(sizes, _KOA_CODES)),
        Variable(name="char", label="Ausführung", options=[
            CodeOption(code="", label="Standard", default=True),
            CodeOption(code="A", label="A: erhöhte Temperaturwechselfestigkeit", sizes=["0603", "0805", "1206"])]),
        Variable(name="termination", label="Anschluss", options=[CodeOption(code="T", value="Sn", label="T: Zinn")]),
        Variable(name="packaging", label="Verpackung", options=[
            CodeOption(code="TCM", label="TCM: Papiergurt gepresst, 2 mm Teilung", sizes=["0201"]),
            CodeOption(code="TP", label="TP: Papiergurt gestanzt, 2 mm Teilung, 10 000 St.", sizes=["0402"]),
            CodeOption(code="TD", label="TD: Papiergurt gestanzt, 4 mm Teilung, 5000 St.",
                       sizes=["0603", "0805", "1206", "1210"]),
            CodeOption(code="TE", label="TE: Blistergurt, 4 mm Teilung, 4000 St.",
                       sizes=["0805", "1206", "1210", "2010", "2512"]),
        ], defaults={"0603": "TD", "0805": "TD", "1206": "TD", "1210": "TD", "2010": "TE", "2512": "TE"}),
        Variable(name="value", label="Widerstand", format=fmt),
        Variable(name="tolerance", label="Toleranz", options=tolerances),
    ]


def _koa_sizes() -> list:
    return [chip_size(size, power=power, voltage=voltage, height=height)
            for size, (power, voltage, height) in _KOA.items()]


def koa_rk73h() -> MpnTemplate:
    big = ["1206", "1210", "2010", "2512"]
    df = ["D", "F"]
    rules = [
        # 0201 (1H): * E24 only for 1-9.1 Ω and 1-10 MΩ
        rule({"tolerance": df}, [("10", "1M")], E24_E96, sizes=["0201"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("1M", "10M")], E24, sizes=["0201"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("1", "9.1")], E24, sizes=["0201"], tcr="±400ppm/K"),
        # 0402 (1E)
        rule({"tolerance": df}, [("10", "1M")], E24_E96, sizes=["0402"], tcr=_P100),
        rule({"tolerance": ["F"]}, [("1", "9.76"), ("1.02M", "10M")], E24_E96, sizes=["0402"], tcr=_P200),
        # 0603 (1J): power depends on the value
        rule({"tolerance": df}, [("1.02k", "1M")], E24_E96, sizes=["0603"], tcr=_P100, power="0.1W"),
        rule({"tolerance": ["F"]}, [("1.02M", "10M")], E24_E96, sizes=["0603"], tcr=_P200, power="0.1W"),
        rule({"tolerance": df}, [("10", "1k")], E24_E96, sizes=["0603"], tcr=_P100, power="0.125W"),
        rule({"tolerance": ["F"]}, [("1", "9.76")], E24_E96, sizes=["0603"], tcr=_P200, power="0.125W"),
        # 0805 (2A)
        rule({"tolerance": df}, [("10", "1M")], E24_E96, sizes=["0805"], tcr=_P100),
        rule({"tolerance": ["F"]}, [("1", "9.76")], E24_E96, sizes=["0805"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("1.02M", "10M")], E24_E96, sizes=["0805"], tcr="±400ppm/K"),
        # 1206 … 2512 (2B, 2E, W2H, W3A)
        rule({"tolerance": df}, [("10", "1M")], E24_E96, sizes=big, tcr=_P100),
        rule({"tolerance": ["F"]}, [("1", "9.76"), ("1.02M", "5.6M")], E24_E96, sizes=big, tcr=_P200),
        rule({"tolerance": ["F"]}, [("5.62M", "10M")], E24_E96, sizes=big, tcr="±400ppm/K"),
    ]
    tolerances = [_tol("D", "0.5", eseries="E24+E96"), _tol("F", "1", default=True, eseries="E24+E96")]
    return MpnTemplate(
        id="koa-rk73h",
        manufacturer="KOA",
        series="RK73H",
        category="Resistors",
        title="KOA RK73H – Präzisions-Dickschicht-Chipwiderstände ±0,5 %/±1 %",
        description=("RK73H 0201 … 2512 (2010/2512 als W2H/W3A), ±0,5 % und ±1 % in E24/E96. Der TK ist nicht Teil "
                     "der Bestellnummer, er folgt aus dem Wertebereich; 0603 hat bis 1 kΩ 0,125 W, darüber 0,1 W."),
        datasheet_url=_KOA_H_URL,
        pattern="RK73H{size}{char}{termination}{packaging}{value}{tolerance}",
        value_unit="Ω",
        variables=_koa_variables(tolerances, ValueFormat(style="eia4")),
        sizes=_koa_sizes(),
        rules=rules,
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="RK73H precision 0.5 %, 1 % tolerance thick film chip resistor", url=_KOA_H_URL,
                        revision="10/26/25 (S. 1), 01/27/26 (S. 2)", pages="1-2"),
                 Source(title="KOA Appendix A – Taping", url=_KOA_PACKAGING_URL, pages="1",
                        note="Verpackungscodes je Baugröße (TP, TD, TE)")],
        verified=True,
        builtin=True,
    )


def koa_rk73b() -> MpnTemplate:
    rules = [
        rule({"tolerance": ["G", "J"]}, [("10", "10M")], E24, sizes=["0201"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("1", "9.1")], E24, sizes=["0201"], tcr="±400ppm/K"),
        rule({"tolerance": ["G", "J"]}, [("1", "10M")], E24, sizes=["0402"], tcr=_P200),
        rule({"tolerance": ["G", "J"]}, [("1", "1k")], E24, sizes=["0603"], tcr=_P200, power="0.125W"),
        rule({"tolerance": ["G"]}, [("1.1k", "1M")], E24, sizes=["0603"], tcr=_P200, power="0.1W"),
        rule({"tolerance": ["J"]}, [("1.1k", "10M")], E24, sizes=["0603"], tcr=_P200, power="0.1W"),
        rule({"tolerance": ["J"]}, [("11M", "22M")], E24, sizes=["0603"], tcr="±400ppm/K", power="0.1W"),
        rule({"tolerance": ["G", "J"]}, [("1", "1M")], E24, sizes=["0805"], tcr=_P200),
        rule({"tolerance": ["G", "J"]}, [("1.1M", "10M")], E24, sizes=["0805"], tcr="±400ppm/K"),
        rule({"tolerance": ["G", "J"]}, [("1", "5.6M")], E24, sizes=["1206"], tcr=_P200),
        rule({"tolerance": ["G"]}, [("6.2M", "10M")], E24, sizes=["1206"], tcr="±400ppm/K"),
        rule({"tolerance": ["J"]}, [("6.2M", "22M")], E24, sizes=["1206"], tcr="±400ppm/K"),
        rule({"tolerance": ["G"]}, [("10", "5.6M")], E24, sizes=["1210", "2010", "2512"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("1", "5.6M")], E24, sizes=["1210", "2010", "2512"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("6.2M", "10M")], E24, sizes=["1210"], tcr="±400ppm/K"),
        rule({"tolerance": ["J"]}, [("6.2M", "22M")], E24, sizes=["2010", "2512"], tcr="±400ppm/K"),
    ]
    tolerances = [_tol("G", "2", eseries="E24"), _tol("J", "5", default=True, eseries="E24")]
    return MpnTemplate(
        id="koa-rk73b",
        manufacturer="KOA",
        series="RK73B",
        category="Resistors",
        title="KOA RK73B – Dickschicht-Chipwiderstände ±2 %/±5 %",
        description=("RK73B 0201 … 2512 (2010/2512 als W2H/W3A), ±2 % und ±5 % in E24. Der TK folgt aus dem "
                     "Wertebereich; 0603 hat bis 1 kΩ 0,125 W, darüber 0,1 W. Brücken (RK73Z) sind eine eigene Serie."),
        datasheet_url=_KOA_B_URL,
        pattern="RK73B{size}{char}{termination}{packaging}{value}{tolerance}",
        value_unit="Ω",
        variables=_koa_variables(tolerances, ValueFormat(style="eia3")),
        sizes=_koa_sizes(),
        rules=rules,
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="RK73B general purpose 2 %, 5 % tolerance thick film chip resistor", url=_KOA_B_URL,
                        revision="10/26/25", pages="1-2"),
                 Source(title="KOA Appendix A – Taping", url=_KOA_PACKAGING_URL, pages="1")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- Stackpole RMCF

_RMCF_URL = "https://www.seielect.com/catalog/sei-rmcf_rmcp.pdf"
# size: (power, max working voltage, height max, jumper rated current)
_RMCF: dict[str, tuple[str, str, float, str]] = {
    "0201": ("0.05W", "25V", 0.28, "0.5A"), "0402": ("0.063W", "50V", 0.40, "1A"),
    "0603": ("0.1W", "75V", 0.60, "1A"), "0805": ("0.125W", "150V", 0.65, "2A"),
    "1206": ("0.25W", "200V", 0.70, "2A"), "1210": ("0.5W", "200V", 0.70, "3A"),
    "2010": ("0.75W", "200V", 0.70, "3A"), "2512": ("1W", "200V", 0.75, "3A"),
}


def _fj(ranges: Sequence[tuple[str, str]], sizes: Sequence[str], tcr: str) -> list[ValueRule]:
    """±1 % (E24/E96) and ±5 % (E24) rules with the same ranges (merged datasheet cells)."""
    return [rule({"tolerance": ["F"]}, ranges, E24_E96, sizes=sizes, tcr=tcr),
            rule({"tolerance": ["J"]}, ranges, E24, sizes=sizes, tcr=tcr)]


def stackpole_rmcf() -> MpnTemplate:
    p400, p500 = "±400ppm/K", "±500ppm/K"
    big = ["1210", "2010", "2512"]
    rules = [
        *_fj([("1", "9.76")], ["0201"], p400),
        *_fj([("10", "10M")], ["0201"], _P200),
        *_fj([("1", "9.76")], ["0402"], _P200),
        *_fj([("10", "1M")], ["0402"], _P100),
        rule({"tolerance": ["F"]}, [("1.02M", "22.1M")], E24_E96, sizes=["0402"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("1.1M", "22M")], E24, sizes=["0402"], tcr=_P200),
        *_fj([("0.1", "0.499")], ["0603"], p500),
        *_fj([("0.5", "0.976")], ["0603"], p400),
        rule({"tolerance": ["F"]}, [("1", "9.76")], E24_E96, sizes=["0603"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("1", "9.1")], E24, sizes=["0603"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("10", "1M")], E24_E96, sizes=["0603", "0805"], tcr=_P100),
        rule({"tolerance": ["J"]}, [("10", "10M")], E24, sizes=["0603", "0805"], tcr=_P100),
        rule({"tolerance": ["F"]}, [("1.02M", "22.1M")], E24_E96, sizes=["0603", "0805"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("11M", "22M")], E24, sizes=["0603", "0805"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("0.1", "9.76")], E24_E96, sizes=["0805", "1206"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("0.1", "9.1")], E24, sizes=["0805", "1206"], tcr=_P200),
        *_fj([("10", "10M")], ["1206"], _P100),
        rule({"tolerance": ["F"]}, [("10.2M", "22.1M")], E24_E96, sizes=["1206"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("11M", "22M")], E24, sizes=["1206"], tcr=_P200),
        *_fj([("0.1", "0.976")], big, _P200),
        *_fj([("1", "9.76")], big, p400),
        *_fj([("10", "10M")], ["1210"], _P100),
        rule({"tolerance": ["F"]}, [("10", "10M")], E24_E96, sizes=["2010", "2512"], tcr=_P100),
        rule({"tolerance": ["J"]}, [("10", "10M")], E24, sizes=["2010", "2512"], tcr=_P200),
    ]
    sizes = list(_RMCF)
    return MpnTemplate(
        id="stackpole-rmcf",
        manufacturer="Stackpole",
        series="RMCF",
        category="Resistors",
        title="Stackpole RMCF – Dickschicht-Chipwiderstände (Standardleistung)",
        description="RMCF 0201 … 2512, ±1 % (E24/E96) und ±5 % (E24), 0,1 Ω … 22 MΩ je nach Baugröße, 0-Ω-Brücken.",
        datasheet_url=_RMCF_URL,
        pattern="RMCF{size}{tolerance}{packaging}{value}",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes)),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("F", "1", default=True, eseries="E24+E96"), _tol("J", "5", eseries="E24"), _jumper_tol("Z")]),
            Variable(name="packaging", label="Verpackung", options=[
                CodeOption(code="T", label="T: Rolle 7\" (Papier, 2010/2512 Blister)", default=True),
                CodeOption(code="G", label="G: Rolle 10\" Papier, 10 000 St.", sizes=["0603", "0805", "1206"])]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="rkm4")),
        ],
        sizes=[chip_size(size, power=power, voltage=voltage, height=height, jumper_current=jumper)
               for size, (power, voltage, height, jumper) in _RMCF.items()],
        rules=rules,
        jumper=JumperSpec(value_code="0R00", codes={"tolerance": "Z"},
                          attrs=jumper_attrs("≤ 50 mΩ")),
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="RMCF / RMCP Series General Purpose Thick Film Chip Resistor", url=_RMCF_URL,
                        revision="Rev Date 1/7/2026", pages="1-3, 15")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- UNI-ROYAL (UniOhm)

_UNIOHM_URL = "https://www.uni-royal.cn/images/userfile/file/1787191733c56505e6d9ab55c7.pdf"
# size: (power code, power, max working voltage, height max, quantity code)
_UNIOHM: dict[str, tuple[str, str, str, float, str]] = {
    "0201": ("WM", "0.05W", "25V", 0.26, "E"), "0402": ("WG", "0.0625W", "50V", 0.40, "C"),
    "0603": ("WA", "0.1W", "75V", 0.55, "5"), "0805": ("W8", "0.125W", "150V", 0.65, "5"),
    "1206": ("W4", "0.25W", "200V", 0.65, "5"), "1210": ("W2", "0.5W", "200V", 0.65, "5"),
    "1812": ("07", "0.75W", "200V", 0.75, "4"), "2010": ("07", "0.75W", "200V", 0.65, "4"),
    "2512": ("1W", "1W", "200V", 0.65, "4"),
}


def uniohm() -> MpnTemplate:
    sizes = list(_UNIOHM)
    others = [s for s in sizes if s != "0201"]
    rules = [
        rule({"tolerance": ["D", "F"]}, [("1", "10")], E24_E96, sizes=["0201"], tcr="-100 … +350ppm/K"),
        rule({"tolerance": ["D", "F"]}, [("10.1", "10M")], E24_E96, sizes=["0201"], tcr=_P200),
        rule({"tolerance": ["J"]}, [("1", "10")], E24, sizes=["0201"], tcr="-100 … +350ppm/K"),
        rule({"tolerance": ["J"]}, [("10.1", "10M")], E24, sizes=["0201"], tcr=_P200),
        rule({"tolerance": ["F"]}, [("0.1", "0.976")], E24_E96, sizes=others, tcr="±800ppm/K"),
        rule({"tolerance": ["J"]}, [("0.1", "0.91")], E24, sizes=others, tcr="±800ppm/K"),
        rule({"tolerance": ["D", "F"]}, [("1", "10")], E24_E96, sizes=others, tcr=_P200),
        rule({"tolerance": ["D", "F"]}, [("10.1", "10M")], E24_E96, sizes=others, tcr=_P100),
        rule({"tolerance": ["J"]}, [("1", "10")], E24, sizes=others, tcr=_P200),
        rule({"tolerance": ["J"]}, [("10.1", "10M")], E24, sizes=others, tcr=_P100),
    ]
    return MpnTemplate(
        id="uniohm-chip",
        manufacturer="UNI-ROYAL",
        series="Chip Series (UniOhm)",
        category="Resistors",
        title="UNI-ROYAL (UniOhm) – Dickschicht-Chipwiderstände",
        description=("Dickschicht-Chipwiderstände 0201 … 2512, ±0,5 %/±1 % (E24/E96, 3 Ziffern) und ±5 % (E24, "
                     "4 Ziffern mit führender 0), 0,1 Ω … 10 MΩ. ±2 % und Brücken sind nicht enthalten "
                     "(Codierung im Datenblatt nicht beschrieben)."),
        datasheet_url=_UNIOHM_URL,
        pattern="{size}{power}{tolerance}{value}T{quantity}E",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes)),
            Variable(name="power", label="Leistungscode",
                     options=[CodeOption(code=d[0], value=d[1], label=f"{d[0]}: {d[1]}", sizes=[s])
                              for s, d in _UNIOHM.items() if s not in ("1812", "2010")]
                     + [CodeOption(code="07", value="0.75W", label="07: 0.75W", sizes=["1812", "2010"])]),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("D", "0.5", eseries="E24+E96"), _tol("F", "1", default=True, eseries="E24+E96"),
                _tol("J", "5", eseries="E24")]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="uniohm4", digits=3),
                     format_overrides=[FormatOverride(when={"tolerance": ["J"]},
                                                      format=ValueFormat(style="uniohm4", digits=2))]),
            Variable(name="quantity", label="Packungsmenge", options=[
                CodeOption(code="E", label="E: 15 000 St.", sizes=["0201"]),
                CodeOption(code="C", label="C: 10 000 St.", sizes=["0402"]),
                CodeOption(code="5", label="5: 5000 St.", sizes=["0603", "0805", "1206", "1210"]),
                CodeOption(code="4", label="4: 4000 St.", sizes=["1812", "2010", "2512"])]),
        ],
        sizes=[chip_size(size, power=power, voltage=voltage, height=height)
               for size, (_code, power, voltage, height, _q) in _UNIOHM.items()],
        rules=rules,
        attrs=dict(_THICK_FILM),
        fields={**RESISTOR_FIELDS, "Power": "{power}"},
        sources=[Source(title="Thick Film Chip Resistors – Chip Series", url=_UNIOHM_URL, document="SMD-SP-001",
                        revision="V.11, 17-Mar-2026", pages="2, 4, 5, 7")],
        verified=True,
        builtin=True,
    )


# --------------------------------------------------------------------------- Bourns CR

_BOURNS_CR_URL = "https://www.bourns.com/docs/product-datasheets/cr.pdf"
# size: (power, max working voltage, height max, jumper rated current, packaging)
_BOURNS_CR: dict[str, tuple[str, str, float, str, str]] = {
    "0201": ("0.05W", "30V", 0.26, "0.5A", "G"), "0402": ("0.0625W", "50V", 0.37, "1A", "G"),
    "0603": ("0.1W", "75V", 0.55, "1A", "E"), "0805": ("0.125W", "150V", 0.60, "2A", "E"),
    "1206": ("0.25W", "200V", 0.65, "2A", "E"), "2010": ("0.5W", "200V", 0.70, "2A", "E"),
    "2512": ("1W", "200V", 0.70, "2A", "E"),
}


def bourns_cr() -> MpnTemplate:
    sizes = list(_BOURNS_CR)
    std = [s for s in sizes if s not in ("0201", "0402")]
    rules = [
        # 0201
        rule({"tolerance": ["F"], "tcr": ["/"]}, [("1", "9.76")], E24_E96, sizes=["0201"], tcr="-200 … +600ppm/K"),
        rule({"tolerance": ["F"], "tcr": ["W"]}, [("10", "3M")], E24_E96, sizes=["0201"]),
        rule({"tolerance": ["J"], "tcr": ["/"]}, [("1", "9.1")], E24, sizes=["0201"], tcr="-200 … +600ppm/K"),
        rule({"tolerance": ["J"], "tcr": ["W"]}, [("10", "10M")], E24, sizes=["0201"]),
        # 0402
        rule({"tolerance": ["F"], "tcr": ["/"]}, [("1", "9.76")], E24_E96, sizes=["0402"], tcr="-200 … +500ppm/K"),
        rule({"tolerance": ["F"], "tcr": ["X"]}, [("10", "1M")], E24_E96, sizes=["0402"]),
        rule({"tolerance": ["F"], "tcr": ["W"]}, [("1.02M", "10M")], E24_E96, sizes=["0402"]),
        rule({"tolerance": ["J"], "tcr": ["/"]}, [("1", "9.1")], E24, sizes=["0402"], tcr="-200 … +500ppm/K"),
        rule({"tolerance": ["J"], "tcr": ["W"]}, [("10", "10M")], E24, sizes=["0402"]),
        rule({"tolerance": ["J"], "tcr": ["Z"]}, [("11M", "20M")], E24, sizes=["0402"]),
        # 0603 … 2512
        rule({"tolerance": ["F"], "tcr": ["/"]}, [("1", "9.76")], E24_E96, sizes=std, tcr=_P200),
        rule({"tolerance": ["F"], "tcr": ["X"]}, [("10", "1M")], E24_E96, sizes=std),
        rule({"tolerance": ["F"], "tcr": ["W"]}, [("1.02M", "10M")], E24_E96, sizes=std),
        rule({"tolerance": ["J"], "tcr": ["/"]}, [("1", "9.1")], E24, sizes=std, tcr="±400ppm/K"),
        rule({"tolerance": ["J"], "tcr": ["W"]}, [("10", "10M")], E24, sizes=std),
        rule({"tolerance": ["J"], "tcr": ["Z"]}, [("11M", "20M")], E24, sizes=std),
    ]
    size_specs = []
    for size, (power, voltage, height, jumper, _pack) in _BOURNS_CR.items():
        extra = {"temperature": "-55 … 125"} if size == "0201" else None
        size_specs.append(chip_size(size, power=power, voltage=voltage, height=height, jumper_current=jumper,
                                    extra=extra))
    return MpnTemplate(
        id="bourns-cr",
        manufacturer="Bourns",
        series="CR",
        category="Resistors",
        title="Bourns CR – Dickschicht-Chipwiderstände",
        description=("CR 0201 … 2512, ±1 % (E24/E96, 4-stelliger Wertcode) und ±5 % (E24, 3-stellig), 1 Ω … 20 MΩ, "
                     "0-Ω-Brücken. Der TK-Code (X, W, Z, /) folgt aus dem Wertebereich."),
        datasheet_url=_BOURNS_CR_URL,
        pattern="CR{size}-{tolerance}{tcr}-{value}{packaging}LF",
        value_unit="Ω",
        variables=[
            Variable(name="size", label="Baugröße", options=size_options(sizes)),
            Variable(name="tolerance", label="Toleranz", options=[
                _tol("F", "1", default=True, eseries="E24+E96"), _tol("J", "5", eseries="E24")]),
            Variable(name="tcr", label="Temperaturkoeffizient", options=[
                CodeOption(code="X", value="±100ppm/K", label="X: ±100 ppm/K"),
                CodeOption(code="W", value="±200ppm/K", label="W: ±200 ppm/K"),
                CodeOption(code="V", value="±300ppm/K", label="V: ±300 ppm/K"),
                CodeOption(code="Z", value="±400ppm/K", label="Z: ±400 ppm/K"),
                CodeOption(code="/", label="/: Brücke und 1 Ω … 9,76 Ω")]),
            Variable(name="value", label="Widerstand", format=ValueFormat(style="eia4"),
                     format_overrides=[FormatOverride(when={"tolerance": ["J"]}, format=ValueFormat(style="eia3"))]),
            Variable(name="packaging", label="Verpackung", options=[
                CodeOption(code="G", label="G: Papiergurt, 10 000 St., Rolle 7\"", sizes=["0201", "0402"]),
                CodeOption(code="E", label="E: Rolle 7\" (Papier 5000 St., 2010/2512 Blister 4000 St.)",
                           sizes=std)]),
        ],
        sizes=size_specs,
        rules=rules,
        jumper=JumperSpec(value_code="000", codes={"tolerance": "J", "tcr": "/"},
                          attrs=jumper_attrs("≤ 50 mΩ")),
        attrs=dict(_THICK_FILM),
        fields=dict(RESISTOR_FIELDS),
        sources=[Source(title="CR Series – Thick Film Chip Resistors", url=_BOURNS_CR_URL, pages="1, 2, 5")],
        verified=True,
        builtin=True,
    )


RESISTOR_TEMPLATES = [vishay_crcw, yageo_rc, panasonic_erj_1pct, panasonic_erj_5pct, koa_rk73h, koa_rk73b,
                      stackpole_rmcf, uniohm, bourns_cr]
