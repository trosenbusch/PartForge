"""Built-in inductor series: Bourns SRR1260 shielded SMD power inductors (catalog)."""
from __future__ import annotations

from ..formats import ValueFormat, encode_value
from ..model import CatalogEntry, CodeOption, FootprintHint, MpnTemplate, SizeSpec, Source, Variable
from .common import mm

_SRR1260_URL = "https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf"
_UH = ValueFormat(style="eia3", scale=1e-6)
_TOLERANCE_CODES = {30: "Y", 20: "M", 10: "K"}

# mpn, L (µH), tolerance (%), SRF typ (MHz), RDC max (mΩ), Irms max (A), Isat typ (A) – datasheet p. 1
SRR1260_PARTS: list[tuple[str, float, int, float, float, float, float]] = [
    ("SRR1260-1R0Y", 1.0, 30, 100.0, 7.8, 9.4, 10.0),
    ("SRR1260-1R2Y", 1.2, 30, 91.1, 8.0, 9.2, 9.8),
    ("SRR1260-1R5Y", 1.5, 30, 86.0, 9.5, 8.8, 9.0),
    ("SRR1260-2R2Y", 2.2, 30, 70.0, 10.5, 8.2, 8.5),
    ("SRR1260-2R4Y", 2.4, 30, 63.8, 11.5, 7.8, 8.0),
    ("SRR1260-3R3Y", 3.3, 30, 40.0, 12.0, 7.6, 7.8),
    ("SRR1260-3R5Y", 3.5, 30, 37.6, 13.0, 7.5, 7.6),
    ("SRR1260-4R7Y", 4.7, 30, 36.7, 15.5, 6.8, 7.0),
    ("SRR1260-5R6Y", 5.6, 30, 33.0, 16.2, 6.7, 6.9),
    ("SRR1260-6R1Y", 6.1, 30, 29.8, 17.0, 6.6, 6.8),
    ("SRR1260-6R8Y", 6.8, 30, 28.2, 18.0, 6.3, 6.5),
    ("SRR1260-7R6Y", 7.6, 30, 27.9, 19.0, 6.0, 6.2),
    ("SRR1260-8R2Y", 8.2, 30, 24.0, 19.5, 5.7, 5.8),
    ("SRR1260-100M", 10.0, 20, 21.0, 20.0, 5.5, 5.5),
    ("SRR1260-120M", 12.0, 20, 19.4, 23.0, 5.2, 5.0),
    ("SRR1260-150M", 15.0, 20, 17.6, 27.0, 5.0, 4.6),
    ("SRR1260-180M", 18.0, 20, 15.5, 36.0, 4.2, 3.9),
    ("SRR1260-220M", 22.0, 20, 13.4, 43.0, 4.0, 3.7),
    ("SRR1260-270M", 27.0, 20, 12.7, 45.0, 3.6, 3.3),
    ("SRR1260-330M", 33.0, 20, 9.97, 60.0, 3.0, 2.8),
    ("SRR1260-390M", 39.0, 20, 10.4, 70.0, 2.8, 2.7),
    ("SRR1260-470M", 47.0, 20, 7.63, 86.0, 2.6, 2.5),
    ("SRR1260-560M", 56.0, 20, 7.92, 100.0, 2.3, 2.2),
    ("SRR1260-680M", 68.0, 20, 7.43, 110.0, 2.1, 2.1),
    ("SRR1260-820M", 82.0, 20, 6.85, 145.0, 1.95, 1.9),
    ("SRR1260-101M", 100.0, 20, 6.07, 180.0, 1.7, 1.7),
    ("SRR1260-121K", 120.0, 10, 5.5, 210.0, 1.65, 1.65),
    ("SRR1260-151K", 150.0, 10, 5.0, 260.0, 1.55, 1.55),
    ("SRR1260-181K", 180.0, 10, 4.5, 320.0, 1.4, 1.4),
    ("SRR1260-221K", 220.0, 10, 4.2, 380.0, 1.38, 1.3),
    ("SRR1260-271K", 270.0, 10, 3.6, 450.0, 1.3, 1.2),
    ("SRR1260-331K", 330.0, 10, 3.2, 580.0, 1.15, 1.1),
    ("SRR1260-391K", 390.0, 10, 2.8, 700.0, 1.08, 1.0),
    ("SRR1260-471K", 470.0, 10, 2.6, 820.0, 0.95, 0.9),
    ("SRR1260-561K", 560.0, 10, 2.4, 1000.0, 0.88, 0.8),
    ("SRR1260-681K", 680.0, 10, 2.2, 1150.0, 0.8, 0.75),
    ("SRR1260-821K", 820.0, 10, 2.0, 1500.0, 0.73, 0.63),
    ("SRR1260-102K", 1000.0, 10, 1.8, 1700.0, 0.68, 0.6),
]


def _num(value: float) -> str:
    return f"{value:g}"


def bourns_srr1260() -> MpnTemplate:
    entries = []
    for mpn, inductance, tol, srf, rdc, irms, isat in SRR1260_PARTS:
        expected = f"SRR1260-{encode_value(inductance * 1e-6, _UH)}{_TOLERANCE_CODES[tol]}"
        if expected != mpn:  # pragma: no cover - guards the data table
            raise ValueError(f"SRR1260-Tabelle inkonsistent: {mpn} != {expected}")
        entries.append(CatalogEntry(
            mpn=mpn, size="SRR1260", value=f"{_num(inductance)}µH", codes={"tolerance": _TOLERANCE_CODES[tol]},
            attrs={"current": f"{_num(irms)}A", "saturation_current": f"{_num(isat)}A", "dcr": f"{_num(rdc)}mΩ",
                   "srf": f"{_num(srf)}MHz"}))
    footprint = FootprintHint(
        family="molded", kind="INDM",
        params={"L": {"min": 12.2, "max": 12.8}, "W": {"min": 12.2, "max": 12.8}, "H": {"min": 5.5, "max": 6.5},
                "F": {"min": 4.7, "max": 5.3}, "S": {"min": 2.6, "max": 2.9}},
        land_pattern={"pad_length": 2.9, "pad_width": 5.4, "row_spacing": 9.7, "row_spacing_reference": "center"},
    )
    return MpnTemplate(
        id="bourns-srr1260",
        manufacturer="Bourns",
        series="SRR1260",
        category="Inductors",
        title="Bourns SRR1260 – geschirmte SMD-Speicherdrosseln 12,5 × 12,5 mm",
        description=("38 Typen 1 µH … 1000 µH (±30 % bis 8,2 µH, ±20 % bis 100 µH, darüber ±10 %) laut "
                     "Datenblatt S. 1; Footprint nach der Herstellerempfehlung (Pads 2,9 × 5,4 mm, Abstand 6,8 mm)."),
        datasheet_url=_SRR1260_URL,
        kind="catalog",
        pattern="SRR{size}-{value}{tolerance}",
        value_unit="H",
        variables=[
            Variable(name="size", label="Baugröße",
                     options=[CodeOption(code="1260", value="SRR1260", label="SRR1260")]),
            Variable(name="value", label="Induktivität", format=_UH),
            Variable(name="tolerance", label="Toleranz", options=[
                CodeOption(code="Y", value="±30%", label="±30 %"), CodeOption(code="M", value="±20%", label="±20 %"),
                CodeOption(code="K", value="±10%", label="±10 %")]),
        ],
        sizes=[SizeSpec(size="SRR1260", label="SRR1260 (12,5 × 12,5 × 6,0 mm)", footprint=footprint,
                        attrs={"height": mm(6.5), "dimensions": "12.5 x 12.5 x 6.0 mm"})],
        catalog=entries,
        attrs={"temperature": "-40 … 125", "shielding": "geschirmt"},
        fields={
            "Inductance": "{value}",
            "Tolerance": "{tolerance}",
            "Current Rating": "{current}",
            "Saturation Current": "{saturation_current}",
            "DCR": "{dcr}",
            "SRF": "{srf}",
            "Shielding": "{shielding}",
            "Size": "{dimensions}",
            "Package": "{size}",
            "Mounting": "SMD",
            "Height": "{height}",
            "Operating Temperature": "{temperature}",
        },
        sources=[Source(title="SRR1260 Series – Shielded SMD Power Inductors", url=_SRR1260_URL,
                        revision="REV. 03/26", pages="1-2",
                        note="Testkorpus tests/data/corpus/pdfs/bourns_SRR1260.pdf (Grundwahrheit, 38 Typen); "
                             "Code-Regel (R = Komma, 2 Ziffern + Nullen in µH; Y/M/K) aus der Tabelle abgeleitet.")],
        verified=True,
        builtin=True,
    )


INDUCTOR_TEMPLATES = [bourns_srr1260]
