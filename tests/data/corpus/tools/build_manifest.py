"""Build corpus/manifest.json (ground truth for PartForge datasheet import tests).

Usage: python -I build_manifest.py <corpus_dir>
All values were read by a human-equivalent reviewer from rendered pages (pypdfium2 PNGs) and/or the text layer.
Status keys: VERIFIED = read from the PDF; DERIVED = computed from verified values; UNVERIFIED = assumption.
"""
import hashlib
import json
import sys
from pathlib import Path

CORPUS = Path(sys.argv[1])
ANALYSIS = json.loads((CORPUS / "work" / "analysis.json").read_text(encoding="utf-8"))


def d(mn=None, nom=None, mx=None, basic=False, ref=False, note=None):
    out = {"min": mn, "nom": nom, "max": mx}
    if basic:
        out["basic"] = True
    if ref:
        out["ref"] = True
    if note:
        out["note"] = note
    return out


def tol(nom, t, note=None):
    return d(round(nom - t, 4), nom, round(nom + t, 4), note=note)


def pin(number, name, function, etype, active_low=False, **kw):
    p = {"number": str(number), "name": name, "function": function, "electrical_type": etype}
    if active_low:
        p["active_low"] = True
    p.update(kw)
    return p


def fileinfo(rel, origin, kind):
    path = CORPUS / rel
    a = ANALYSIS[path.name]
    return {
        "file": rel,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
        "origin": origin,
        "kind": kind,
        "pages": a["pages"],
        "encrypted": a["encrypted"],
        "text_extractable": a["text_extractable"],
        "pages_without_text_layer": [p["page"] for p in a["page_detail"] if max(p["chars_pypdf"], p["chars_plumber"]) < 20],
    }


ALTIUM_TYPES = "Altium pin electrical types used: Input, IO, Output, OpenCollector, Passive, HiZ, OpenEmitter, Power. Mapping from datasheet text is DERIVED."

entries = []

# ---------------------------------------------------------------- OPA656
e = fileinfo("pdfs/opa656.pdf", "C:/PartForge-Examples/ExampleProject/opa656.pdf", "ic")
e.update({
    "manufacturer": "Texas Instruments",
    "document": {"id": "SBOS196G", "title": "Wideband, Unity-Gain Stable, FET-Input Operational Amplifier", "revision": "G (Nov 2008); addendum 26-May-2010; pack materials 17-Dec-2011"},
    "sections": {"ordering": [2, 17, 18], "pinout": [2], "package_outline": [21, 23], "land_pattern": [22, 24], "abs_max": [2], "tape_reel": [19, 20]},
    "extraction_notes": [
        "Pages 21-24 (mechanical + land pattern) have NO text layer (vector outlines, 0 chars, 0 images) -> vision required.",
        "Page 2 says OPA656U 'Rails, 100' but the Package Option Addendum (p17) lists OPA656U package qty 75 (document-internal conflict).",
        "Pin names are spelled out ('Inverting Input', 'Noninverting Input', '-VS', '+VS', 'Output', 'NC').",
    ],
    "devices": [{
        "base_part": "OPA656",
        "description": "Wideband, unity-gain stable, FET-input operational amplifier (single)",
        "category": "Operational Amplifier",
        "mpns": [
            {"mpn": "OPA656U", "package": "SOIC-8", "grade": "standard", "packing": "Rails, 100 (p2) / tube 75 (addendum p17)", "marking": "OPA656U"},
            {"mpn": "OPA656U/2K5", "package": "SOIC-8", "grade": "standard", "packing": "Tape and Reel, 2500", "marking": "OPA656U"},
            {"mpn": "OPA656UB", "package": "SOIC-8", "grade": "high", "packing": "Rails, 100", "marking": "OPA656UB"},
            {"mpn": "OPA656UB/2K5", "package": "SOIC-8", "grade": "high", "packing": "Tape and Reel, 2500", "marking": "OPA656UB"},
            {"mpn": "OPA656N/250", "package": "SOT-23-5", "grade": "standard", "packing": "Tape and Reel, 250", "marking": "B56"},
            {"mpn": "OPA656N/3K", "package": "SOT-23-5", "grade": "standard", "packing": "Tape and Reel, 3000", "marking": "B56"},
            {"mpn": "OPA656NB/250", "package": "SOT-23-5", "grade": "high", "packing": "Tape and Reel, 250", "marking": "B56"},
            {"mpn": "OPA656NB/3K", "package": "SOT-23-5", "grade": "high", "packing": "Tape and Reel, 3000", "marking": "B56"},
        ],
        "additional_orderables_addendum": ["OPA656N/250G4", "OPA656NB/250G4", "OPA656U/2K5G4", "OPA656UB/2K5G4 (PREVIEW)", "OPA656UBG4", "OPA656UG4"],
        "temperature_range": "-40 C to +85 C",
        "pin_tables": {
            "SOIC-8": [
                pin(1, "NC", "No connection", "Passive"),
                pin(2, "Inverting Input", "Inverting input (-IN)", "Input"),
                pin(3, "Noninverting Input", "Noninverting input (+IN)", "Input"),
                pin(4, "-VS", "Negative supply", "Power"),
                pin(5, "NC", "No connection", "Passive"),
                pin(6, "Output", "Output", "Output"),
                pin(7, "+VS", "Positive supply", "Power"),
                pin(8, "NC", "No connection", "Passive"),
            ],
            "SOT-23-5": [
                pin(1, "Output", "Output", "Output"),
                pin(2, "-VS", "Negative supply", "Power"),
                pin(3, "Noninverting Input", "Noninverting input (+IN)", "Input"),
                pin(4, "Inverting Input", "Inverting input (-IN)", "Input"),
                pin(5, "+VS", "Positive supply", "Power"),
            ],
        },
    }],
    "packages": {
        "SOIC-8": {
            "vendor_code": "D (R-PDSO-G8)", "drawing": "4040047-3/M 06/11", "jedec": "MS-012 variation AA", "pins": 8, "page": 23,
            "units_in_drawing": "inches (millimeters)",
            "dims_mm": {"e_pitch": d(nom=1.27, basic=True), "D_body_length": d(4.80, None, 5.00, note="excl. mold flash <=0.15/side"),
                        "E1_body_width": d(3.80, None, 4.00, note="excl. interlead flash <=0.43/side"), "E_lead_span": d(5.80, None, 6.20),
                        "A_height": d(None, None, 1.75), "A1_standoff": d(0.10, None, 0.25), "b_lead_width": d(0.31, None, 0.51),
                        "c_lead_thickness": d(0.13, None, 0.25), "L_foot_length": d(0.40, None, 1.27), "gauge_plane": d(nom=0.25),
                        "theta_deg": d(0, None, 8), "coplanarity": d(None, None, 0.10)},
            "land_pattern": {"page": 24, "drawing": "4211283-2/D 06/11", "type": "example board layout (IPC-7351 recommended for alternates)",
                             "pad_width_mm": 0.60, "pad_length_mm": 2.00, "pitch_mm": 1.27, "row_center_distance_mm": 4.80,
                             "solder_mask_expansion_mm": 0.07, "stencil_opening_mm": [0.55, 1.95]},
        },
        "SOT-23-5": {
            "vendor_code": "DBV (R-PDSO-G5)", "drawing": "4073253-4/K 03/2006", "jedec": "MO-178 variation AA", "pins": 5, "page": 21,
            "dims_mm": {"e_pitch": d(nom=0.95, basic=True), "D_body_length": d(2.75, None, 3.05), "E1_body_width": d(1.45, None, 1.75),
                        "E_lead_span": d(2.60, None, 3.00), "A_height": d(None, None, 1.45), "A1_standoff": d(0.00, None, 0.15),
                        "b_lead_width": d(0.30, None, 0.50), "c_lead_thickness": d(0.08, None, 0.22), "L_foot_length": d(0.30, None, 0.55),
                        "gauge_plane": d(nom=0.25), "theta_deg": d(0, None, 8), "coplanarity": d(None, None, 0.10)},
            "land_pattern": {"page": 22, "drawing": "4209593-3/C 08/11", "pad_width_mm": 0.60, "pad_length_mm": 1.05, "pitch_mm": 0.95,
                             "pin4_to_pin5_mm": 1.90, "row_center_distance_mm": 2.70, "solder_mask_expansion_mm": 0.07,
                             "stencil_opening_mm": [0.55, 1.00], "stencil_thickness_mm": 0.127},
        },
    },
    "abs_max": [
        {"parameter": "Supply Voltage", "value": "±6.5V"}, {"parameter": "Internal Power Dissipation", "value": "See Thermal Characteristics"},
        {"parameter": "Differential Input Voltage", "value": "±VS"}, {"parameter": "Input Voltage Range", "value": "±VS"},
        {"parameter": "Storage Temperature Range", "value": "-65°C to +125°C"}, {"parameter": "Lead Temperature", "value": "+260°C"},
        {"parameter": "Junction Temperature (TJ)", "value": "+150°C"}, {"parameter": "ESD Rating (Human Body Model)", "value": "2000V"},
        {"parameter": "ESD Rating (Machine Model)", "value": "200V"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- LTC6244
e = fileinfo("pdfs/LTC6244.pdf", "C:/PartForge-Examples/ExampleProject/LTC6244.pdf", "ic")
e.update({
    "manufacturer": "Linear Technology (now Analog Devices)",
    "document": {"id": "6244fb", "title": "LTC6244 - Dual 50MHz, Low Noise, Rail-to-Rail, CMOS Op Amp", "revision": "B"},
    "sections": {"ordering": [2], "pinout": [2], "package_outline": [23, 24], "land_pattern": [23, 24], "abs_max": [2]},
    "extraction_notes": [
        "Text layer complete; ligature 'fi' extracted as 'fi ' ('Specifi ed', 'amplifi ers').",
        "No pin-function table: names only in pin-configuration drawings. Datasheet typo 'CONNEECTED'.",
        "Pin 9 = exposed pad of DD package, connected to V- (PCB connection optional).",
        "MPN suffixes: C/I/H temperature grade, HV = high-voltage version, DD/MS8 package, #PBF lead free, #TRPBF tape&reel.",
    ],
    "devices": [{
        "base_part": "LTC6244", "description": "Dual 50MHz, low noise, rail-to-rail CMOS op amp", "category": "Operational Amplifier",
        "mpns": [
            {"mpn": m, "package": pkg, "marking": mk, "temperature_range": t}
            for m, pkg, mk, t in [
                ("LTC6244CDD#PBF", "DFN-8 3x3 (DD)", "LCCF", "0°C to 70°C"), ("LTC6244CDD#TRPBF", "DFN-8 3x3 (DD)", "LCCF", "0°C to 70°C"),
                ("LTC6244HVCDD#PBF", "DFN-8 3x3 (DD)", "LCGD", "0°C to 70°C"), ("LTC6244HVCDD#TRPBF", "DFN-8 3x3 (DD)", "LCGD", "0°C to 70°C"),
                ("LTC6244IDD#PBF", "DFN-8 3x3 (DD)", "LCCF", "-40°C to 85°C"), ("LTC6244IDD#TRPBF", "DFN-8 3x3 (DD)", "LCCF", "-40°C to 85°C"),
                ("LTC6244HVIDD#PBF", "DFN-8 3x3 (DD)", "LCGD", "-40°C to 85°C"), ("LTC6244HVIDD#TRPBF", "DFN-8 3x3 (DD)", "LCGD", "-40°C to 85°C"),
                ("LTC6244HDD#PBF", "DFN-8 3x3 (DD)", "LCCF", "-40°C to 125°C"), ("LTC6244HDD#TRPBF", "DFN-8 3x3 (DD)", "LCCF", "-40°C to 125°C"),
                ("LTC6244HVHDD#PBF", "DFN-8 3x3 (DD)", "LCGD", "-40°C to 125°C"), ("LTC6244HVHDD#TRPBF", "DFN-8 3x3 (DD)", "LCGD", "-40°C to 125°C"),
                ("LTC6244CMS8#PBF", "MSOP-8 (MS8)", "LTCCM", "0°C to 70°C"), ("LTC6244CMS8#TRPBF", "MSOP-8 (MS8)", "LTCCM", "0°C to 70°C"),
                ("LTC6244HVCMS8#PBF", "MSOP-8 (MS8)", "LTCGF", "0°C to 70°C"), ("LTC6244HVCMS8#TRPBF", "MSOP-8 (MS8)", "LTCGF", "0°C to 70°C"),
                ("LTC6244IMS8#PBF", "MSOP-8 (MS8)", "LTCCM", "-40°C to 85°C"), ("LTC6244IMS8#TRPBF", "MSOP-8 (MS8)", "LTCCM", "-40°C to 85°C"),
                ("LTC6244HVIMS8#PBF", "MSOP-8 (MS8)", "LTCGF", "-40°C to 85°C"), ("LTC6244HVIMS8#TRPBF", "MSOP-8 (MS8)", "LTCGF", "-40°C to 85°C"),
                ("LTC6244HMS8#PBF", "MSOP-8 (MS8)", "LTCCM", "-40°C to 125°C"), ("LTC6244HMS8#TRPBF", "MSOP-8 (MS8)", "LTCCM", "-40°C to 125°C"),
            ]
        ],
        "not_offered": ["LTC6244HVHMS8 (no HV + H-grade MSOP row in table)"],
        "pin_tables": {
            "MSOP-8 (MS8)": [
                pin(1, "OUT A", "Output amplifier A", "Output"), pin(2, "-IN A", "Inverting input A", "Input"),
                pin(3, "+IN A", "Noninverting input A", "Input"), pin(4, "V-", "Negative supply", "Power"),
                pin(5, "+IN B", "Noninverting input B", "Input"), pin(6, "-IN B", "Inverting input B", "Input"),
                pin(7, "OUT B", "Output amplifier B", "Output"), pin(8, "V+", "Positive supply", "Power"),
            ],
        },
        "symbol_hint": "dual op amp: 2 functional parts (A: 1,2,3; B: 5,6,7) + shared power 4,8 (+9 EP on DFN) - DERIVED",
    }],
    "packages": {
        "DFN-8 3x3 (DD)": {
            "drawing": "LTC DWG # 05-08-1698 Rev C", "jedec": "MO-229 variation (WEED-1)", "pins": 8, "exposed_pad_pin": "9", "page": 23,
            "dims_mm": {"D_body": tol(3.00, 0.10), "E_body": tol(3.00, 0.10), "A_height": tol(0.75, 0.05), "A1_standoff": d(0.00, None, 0.05),
                        "A3_terminal_thickness": d(nom=0.200, ref=True), "e_pitch": d(nom=0.50, basic=True), "b_terminal_width": tol(0.25, 0.05),
                        "L_terminal_length": tol(0.40, 0.10), "EP_D2": tol(2.38, 0.10), "EP_E2": tol(1.65, 0.10), "pin1_notch_R": d(nom=0.125)},
            "land_pattern": {"page": 23, "type": "recommended solder pad pitch and dimensions", "pad_width_mm": tol(0.25, 0.05),
                             "pad_length_mm": tol(0.70, 0.05), "pitch_mm": 0.50, "outer_span_mm": tol(3.5, 0.05), "inner_span_mm": tol(2.10, 0.05),
                             "row_center_distance_mm_DERIVED": 2.80, "thermal_pad_mm": [tol(2.38, 0.05), tol(1.65, 0.05)],
                             "note": "Apply solder mask to areas that are not soldered"},
        },
        "MSOP-8 (MS8)": {
            "drawing": "LTC DWG # 05-08-1660 Rev F", "pins": 8, "page": 24, "units_in_drawing": "millimeter (inch)",
            "dims_mm": {"e_pitch": d(nom=0.65, basic=True), "D_body_length": tol(3.00, 0.102, "note 3: excl. mold flash <=0.152/side"),
                        "E1_body_width": tol(3.00, 0.102, "note 4: excl. interlead flash <=0.152/side"), "E_lead_span": tol(4.90, 0.152),
                        "A_height": d(None, None, 1.10), "A2_body_thickness": d(nom=0.86, ref=True), "A1_standoff": tol(0.1016, 0.0508),
                        "b_lead_width": d(0.22, None, 0.38), "c_lead_thickness": d(nom=0.18), "L_foot_length": tol(0.53, 0.152),
                        "gauge_plane": d(nom=0.254), "theta_deg": d(0, None, 6, note="0-6 TYP"), "coplanarity": d(None, None, 0.102),
                        "unlabeled_0p52_ref": d(nom=0.52, ref=True, note="dimension at leads in top view, meaning not labeled")},
            "land_pattern": {"page": 24, "type": "recommended solder pad layout", "pad_width_mm": tol(0.42, 0.038), "pad_length_mm": tol(0.889, 0.127),
                             "pitch_mm": 0.65, "outer_span_min_mm": 5.23, "inner_span_mm": [3.20, 3.45], "row_center_distance_mm_DERIVED": 4.34},
        },
    },
    "abs_max": [
        {"parameter": "Total Supply Voltage (V+ to V-) LTC6244", "value": "7V"}, {"parameter": "Total Supply Voltage (V+ to V-) LTC6244HV", "value": "12V"},
        {"parameter": "Input Voltage", "value": "(V+ + 0.3V) to (V- - 0.3V)"}, {"parameter": "Input Current", "value": "±10mA"},
        {"parameter": "Output Short Circuit Duration", "value": "Indefinite"},
        {"parameter": "Operating Temperature Range", "value": "C: -40°C to 85°C; I: -40°C to 85°C; H: -40°C to 125°C"},
        {"parameter": "Specified Temperature Range", "value": "C: 0°C to 70°C; I: -40°C to 85°C; H: -40°C to 125°C"},
        {"parameter": "Junction Temperature", "value": "150°C"}, {"parameter": "Storage Temperature Range", "value": "-65°C to 150°C"},
        {"parameter": "Lead Temperature (Soldering, 10 sec)", "value": "300°C"},
        {"parameter": "Thermal", "value": "DD: TJMAX=150°C, θJA=43°C/W; MS8: TJMAX=150°C, θJA=250°C/W"},
    ],
})
e["devices"][0]["pin_tables"]["DFN-8 3x3 (DD)"] = e["devices"][0]["pin_tables"]["MSOP-8 (MS8)"] + [
    pin(9, "V-", "Exposed pad, connected to V- (PCB connection optional)", "Power", exposed_pad=True)]
entries.append(e)

# ---------------------------------------------------------------- 6N137 family
e = fileinfo("pdfs/6N137.pdf", "C:/PartForge-Examples/ExampleProject/6N137.pdf", "ic")
single = [
    pin(1, "N/C", "No connection", "Passive"), pin(2, "VF+", "LED anode (+)", "Passive"), pin(3, "VF-", "LED cathode (-)", "Passive"),
    pin(4, "N/C", "No connection", "Passive"), pin(5, "GND", "Ground", "Power"), pin(6, "VO", "Open-collector output", "OpenCollector"),
    pin(7, "VE", "Enable (strobe) input", "Input"), pin(8, "VCC", "Supply; 0.1uF bypass between pins 8 and 5 required", "Power"),
]
dual = [
    pin(1, "VF1+", "LED 1 anode (+)", "Passive"), pin(2, "VF1-", "LED 1 cathode (-)", "Passive"), pin(3, "VF2-", "LED 2 cathode (-)", "Passive"),
    pin(4, "VF2+", "LED 2 anode (+)", "Passive"), pin(5, "GND", "Ground", "Power"), pin(6, "VO2", "Open-collector output 2", "OpenCollector"),
    pin(7, "VO1", "Open-collector output 1", "OpenCollector"), pin(8, "VCC", "Supply", "Power"),
]
options = [("", "Standard through hole 0.3in"), ("S", "Surface Mount Lead Bend"), ("SD", "Surface Mount; Tape and Reel"), ("W", "0.4in Lead Spacing"),
           ("V", "VDE0884"), ("WV", "VDE0884; 0.4in Lead Spacing"), ("SV", "VDE0884; Surface Mount"), ("SDV", "VDE0884; Surface Mount; Tape and Reel")]
e.update({
    "manufacturer": "Fairchild Semiconductor (now onsemi)",
    "document": {"id": "6N137, HCPL2601, HCPL2611, HCPL2630, HCPL2631 Rev. 1.0.8", "title": "High Speed 10MBit/s Logic Gate Optocouplers", "date": "January 2011"},
    "sections": {"ordering": [10], "pinout": [1], "package_outline": [9], "land_pattern": [9], "abs_max": [2], "tape_reel": [11]},
    "extraction_notes": [
        "Multi-device datasheet: single-channel 6N137/HCPL2601/HCPL2611 and dual-channel HCPL2630/HCPL2631 share one PDF with different pinouts.",
        "No pin table: pin names only in the 'Schematics' drawings on page 1 (VF, VE, VO, VCC, GND, N/C).",
        "Page 9 dimension labels: rotated text is scrambled in the text layer -> vision required.",
        "Ordering options are given only as examples for 6N137 (6N137S, 6N137SD, ...).",
    ],
    "devices": [
        {"base_part": "6N137", "channels": 1, "description": "Single-channel 10 MBit/s logic gate optocoupler", "category": "Optocoupler",
         "mpns": [f"6N137{o}" for o, _ in options], "pin_tables": {"DIP-8 / SMD-8 (all options)": single}},
        {"base_part": "HCPL2601", "channels": 1, "description": "Single-channel, min CMR 5 kV/us", "category": "Optocoupler",
         "mpns_DERIVED": [f"HCPL2601{o}" for o, _ in options], "pin_tables": {"DIP-8 / SMD-8 (all options)": single}},
        {"base_part": "HCPL2611", "channels": 1, "description": "Single-channel, min CMR 10 kV/us", "category": "Optocoupler",
         "mpns_DERIVED": [f"HCPL2611{o}" for o, _ in options], "pin_tables": {"DIP-8 / SMD-8 (all options)": single}},
        {"base_part": "HCPL2630", "channels": 2, "description": "Dual-channel", "category": "Optocoupler",
         "mpns_DERIVED": [f"HCPL2630{o}" for o, _ in options], "pin_tables": {"DIP-8 / SMD-8 (all options)": dual}},
        {"base_part": "HCPL2631", "channels": 2, "description": "Dual-channel, min CMR 5 kV/us", "category": "Optocoupler",
         "mpns_DERIVED": [f"HCPL2631{o}" for o, _ in options], "pin_tables": {"DIP-8 / SMD-8 (all options)": dual}},
    ],
    "ordering_options": [{"suffix": o or "(none)", "description": t} for o, t in options],
    "package_by_option": {"(none)": "DIP-8 (through hole, 0.3in rows)", "V": "DIP-8 (through hole, 0.3in rows)",
                          "W": "DIP-8 (0.4in lead spacing, option W)", "WV": "DIP-8 (0.4in lead spacing, option W)",
                          "S": "SMD-8 gull wing (option S)", "SD": "SMD-8 gull wing (option S)", "SV": "SMD-8 gull wing (option S)",
                          "SDV": "SMD-8 gull wing (option S)"},
    "packages": {
        "DIP-8 (through hole, 0.3in rows)": {"page": 9, "units_in_drawing": "inches (millimeters)", "pins": 8,
            "dims_mm": {"D_body_length": d(9.40, None, 9.91), "E1_body_width": d(6.35, None, 6.86), "A_seating_to_top": d(3.55, None, 5.08),
                        "A1_standoff": d(0.51, None, None), "L_lead_below_seating": d(3.05, None, 3.90), "b_lead_width": d(0.41, None, 0.56),
                        "b2_shoulder_width": d(1.14, None, 1.78), "e_pitch": d(nom=2.54, note="TYP"), "c_lead_thickness": d(0.20, None, 0.40),
                        "eA_row_spacing": d(nom=7.62, note="TYP"), "lead_angle": "15° MAX"}},
        "DIP-8 (0.4in lead spacing, option W)": {"page": 9, "pins": 8,
            "dims_mm": {"D_body_length": d(9.40, None, 9.91), "E1_body_width": d(6.35, None, 6.86), "A_seating_to_top": d(3.55, None, 5.08),
                        "A1_standoff": d(0.10, None, None), "L_lead_below_seating": d(3.05, None, 3.90), "b_lead_width": d(0.41, None, 0.56),
                        "b2_shoulder_width": d(1.14, None, 1.78), "e_pitch": d(nom=2.54, note="TYP"), "c_lead_thickness": d(0.20, None, 0.40),
                        "eA_row_spacing": d(nom=10.16, note="TYP"), "lead_angle": "0° to 15°"}},
        "SMD-8 gull wing (option S)": {"page": 9, "pins": 8,
            "dims_mm": {"D_body_length": d(9.40, None, 9.91), "E1_body_width": d(6.35, None, 6.86), "e_pitch": d(nom=2.54, note="TYP"),
                        "b_lead_width": d(0.41, None, 0.56), "b2_shoulder_width": d(1.14, None, 1.78), "A1_standoff": d(0.51, None, None),
                        "c_lead_thickness": d(0.20, None, 0.41), "L_foot": d(nom=1.14), "inner_span_min": d(8.00, None, None),
                        "E_lead_span": d(None, None, 10.30), "eA_row_spacing": d(nom=7.62, note="TYP"), "coplanarity": d(None, None, 0.10)},
            "land_pattern": {"page": 9, "title": "8-Pin DIP - Land Pattern", "pad_width_mm": 1.78, "pad_length_mm": 1.52, "pitch_mm": 2.54,
                             "pad_gap_mm": 0.76, "outer_span_mm": 10.54, "inner_span_mm": 7.49, "row_center_distance_mm_DERIVED": 9.015}},
    },
    "abs_max": [
        {"parameter": "TSTG Storage Temperature", "value": "-55 to +125 °C"}, {"parameter": "TOPR Operating Temperature", "value": "-40 to +85 °C"},
        {"parameter": "TSOL Lead Solder Temperature (wave only)", "value": "260 for 10 sec °C"},
        {"parameter": "IF DC/Average Forward Input Current", "value": "single 50 mA; dual 30 mA each channel"},
        {"parameter": "VE Enable Input Voltage (not to exceed VCC by more than 500mV)", "value": "5.5 V (single channel)"},
        {"parameter": "VR Reverse Input Voltage", "value": "5.0 V each channel"},
        {"parameter": "PI Power Dissipation (emitter)", "value": "single 100 mW; dual 45 mW each channel"},
        {"parameter": "VCC Supply Voltage (1 minute max)", "value": "7.0 V"},
        {"parameter": "IO Output Current", "value": "single 50 mA; dual 50 mA each channel"},
        {"parameter": "VO Output Voltage", "value": "7.0 V each channel"},
        {"parameter": "PO Collector Output Power Dissipation", "value": "single 85 mW; dual 60 mW each channel"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- 25AA02E48
e = fileinfo("pdfs/25AA02E48.pdf", "C:/PartForge-Examples/ExampleProject/doc/datasheets/25AA02E48.pdf", "ic")
e.update({
    "manufacturer": "Microchip Technology",
    "document": {"id": "DS22123B", "title": "2K SPI Bus Serial EEPROM with EUI-48 Node Identity", "date": "2010"},
    "sections": {"ordering": [1, 23], "pinout": [1, 14], "package_outline": [16, 18], "land_pattern": [17, 19], "abs_max": [2], "marking": [15]},
    "extraction_notes": [
        "PDF is encrypted (owner password only); opens with empty user password (pypdf decrypt('') ok).",
        "Package pages 16-19: text layer is glyph-ID encoded (pdfplumber '(cid:N)', pypdf '/gNN'). Decoding chr(N+29) recovers the tables on p16 (VERIFIED); otherwise vision required.",
        "Active-low pins CS, WP, HOLD carry overbars that are lost in the text layer.",
        "SOT-23 pin 6 is labelled 'VDD' in the p1 package drawing but 'VCC' in the pin function table (name normalisation needed).",
        "MPN template: 25AA02E48[T]-I/<pkg>; T = tape&reel; I = -40..+85 C; SN = SOIC 3.90mm 8-lead; OT = SOT-23 6-lead (tape&reel only).",
    ],
    "devices": [{
        "base_part": "25AA02E48", "description": "2 Kbit SPI serial EEPROM with pre-programmed EUI-48 node address", "category": "Memory / EEPROM",
        "mpns": [{"mpn": "25AA02E48-I/SN", "package": "SOIC-8"}, {"mpn": "25AA02E48T-I/SN", "package": "SOIC-8", "packing": "Tape & Reel"},
                 {"mpn": "25AA02E48T-I/OT", "package": "SOT-23-6", "packing": "Tape & Reel (only option)"}],
        "marking": {"SOIC-8": "25A2E48I + YYWW + NNN (example '25A2E48I / SN e3 0827 / 1L7')", "SOT-23-6": "20NN"},
        "pin_tables": {
            "SOIC-8": [
                pin(1, "CS", "Chip Select Input", "Input", active_low=True, altium_name_UNVERIFIED="C\\S\\"),
                pin(2, "SO", "Serial Data Output", "Output"), pin(3, "WP", "Write-Protect", "Input", active_low=True, altium_name_UNVERIFIED="W\\P\\"),
                pin(4, "VSS", "Ground", "Power"), pin(5, "SI", "Serial Data Input", "Input"), pin(6, "SCK", "Serial Clock Input", "Input"),
                pin(7, "HOLD", "Hold Input", "Input", active_low=True, altium_name_UNVERIFIED="H\\O\\L\\D\\"), pin(8, "VCC", "Supply Voltage", "Power"),
            ],
            "SOT-23-6": [
                pin(1, "SCK", "Serial Clock Input", "Input"), pin(2, "VSS", "Ground", "Power"), pin(3, "SI", "Serial Data Input", "Input"),
                pin(4, "SO", "Serial Data Output", "Output"), pin(5, "CS", "Chip Select Input", "Input", active_low=True),
                pin(6, "VCC", "Supply Voltage (drawn as 'VDD' on p1)", "Power"),
            ],
        },
    }],
    "packages": {
        "SOIC-8": {"vendor_code": "SN", "drawing": "C04-057B", "page": 16, "pins": 8,
                   "dims_mm": {"e_pitch": d(nom=1.27, basic=True), "A_height": d(None, None, 1.75), "A2_body_thickness": d(1.25, None, None),
                               "A1_standoff": d(0.10, None, 0.25), "E_lead_span": d(nom=6.00, basic=True), "E1_body_width": d(nom=3.90, basic=True),
                               "D_body_length": d(nom=4.90, basic=True), "h_chamfer": d(0.25, None, 0.50), "L_foot_length": d(0.40, None, 1.27),
                               "L1_footprint": d(nom=1.04, ref=True), "phi_foot_angle_deg": d(0, None, 8), "c_lead_thickness": d(0.17, None, 0.25),
                               "b_lead_width": d(0.31, None, 0.51), "alpha_mold_draft_top_deg": d(5, None, 15), "beta_mold_draft_bottom_deg": d(5, None, 15)},
                   "land_pattern": {"page": 17, "drawing": "C04-2057A", "E_pitch_mm": 1.27, "C_pad_center_spacing_mm": 5.40,
                                    "X1_pad_width_max_mm": 0.60, "Y1_pad_length_max_mm": 1.55}},
        "SOT-23-6": {"vendor_code": "OT", "drawing": "C04-028B", "page": 18, "pins": 6,
                     "dims_mm": {"e_pitch": d(nom=0.95, basic=True), "e1_outside_lead_pitch": d(nom=1.90, basic=True), "A_height": d(0.90, None, 1.45),
                                 "A2_body_thickness": d(0.89, None, 1.30), "A1_standoff": d(0.00, None, 0.15), "E_lead_span": d(2.20, None, 3.20),
                                 "E1_body_width": d(1.30, None, 1.80), "D_body_length": d(2.70, None, 3.10), "L_foot_length": d(0.10, None, 0.60),
                                 "L1_footprint": d(0.35, None, 0.80), "phi_foot_angle_deg": d(0, None, 30), "c_lead_thickness": d(0.08, None, 0.26),
                                 "b_lead_width": d(0.20, None, 0.51)},
                     "land_pattern": {"page": 19, "drawing": "C04-2028A", "E_pitch_mm": 0.95, "C_pad_center_spacing_mm": 2.80,
                                      "X_pad_width_max_mm": 0.60, "Y_pad_length_max_mm": 1.10, "G_min_mm": 1.70, "GX_min_mm": 0.35, "Z_max_mm": 3.90}},
    },
    "abs_max": [
        {"parameter": "VCC", "value": "6.5V"}, {"parameter": "All inputs and outputs w.r.t. VSS", "value": "-0.6V to VCC +1.0V"},
        {"parameter": "Storage temperature", "value": "-65°C to 150°C"}, {"parameter": "Ambient temperature under bias", "value": "-40°C to 85°C"},
        {"parameter": "ESD protection on all pins", "value": "4kV"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- AD7983
e = fileinfo("pdfs/AD7983.pdf", "C:/PartForge-Examples/ExampleProject/doc/datasheets/AD7983.pdf", "ic")
ad7983_pins = [
    pin(1, "REF", "Reference input voltage (2.9 V to 5.1 V), decouple with 10 uF", "Input", ds_type="AI"),
    pin(2, "VDD", "Power supply", "Power", ds_type="P"), pin(3, "IN+", "Analog input", "Input", ds_type="AI"),
    pin(4, "IN-", "Analog input ground sense", "Input", ds_type="AI"), pin(5, "GND", "Power supply ground", "Power", ds_type="P"),
    pin(6, "CNV", "Convert input", "Input", ds_type="DI"), pin(7, "SDO", "Serial data output", "Output", ds_type="DO"),
    pin(8, "SCK", "Serial data clock input", "Input", ds_type="DI"), pin(9, "SDI", "Serial data input", "Input", ds_type="DI"),
    pin(10, "VIO", "Input/output interface digital power", "Power", ds_type="P"),
]
e.update({
    "manufacturer": "Analog Devices",
    "document": {"id": "D06974-0-3/10(A)", "title": "16-Bit, 1.33 MSPS PulSAR ADC in MSOP/QFN", "revision": "A"},
    "sections": {"ordering": [24], "pinout": [7], "package_outline": [24], "land_pattern": [], "abs_max": [6]},
    "extraction_notes": [
        "Pin table has a Type column (AI/DI/DO/P) -> direct electrical-type mapping.",
        "No recommended land pattern in this datasheet (p23 shows an example PCB layout image only).",
        "QFN exposed paddle has no pin number; note: 'paddle connected to GND, not required to meet electrical performance'.",
        "Ordering guide as printed: BCPZ-RL = Reel 1000, BCPZ-RL7 = Reel 5000 (unusual vs ADI convention; keep as printed).",
    ],
    "devices": [{
        "base_part": "AD7983", "description": "16-bit 1.33 MSPS PulSAR ADC", "category": "ADC", "temperature_range": "-40°C to +85°C", "branding": "C5Y",
        "mpns": [{"mpn": "AD7983BRMZ", "package": "MSOP-10 (RM-10)", "packing": "Tube, 50"},
                 {"mpn": "AD7983BRMZRL7", "package": "MSOP-10 (RM-10)", "packing": "Reel, 1000"},
                 {"mpn": "AD7983BCPZ-R2", "package": "LFCSP_WD-10 3x3 (CP-10-9)", "packing": "Reel, 250"},
                 {"mpn": "AD7983BCPZ-RL", "package": "LFCSP_WD-10 3x3 (CP-10-9)", "packing": "Reel, 1000"},
                 {"mpn": "AD7983BCPZ-RL7", "package": "LFCSP_WD-10 3x3 (CP-10-9)", "packing": "Reel, 5000"}],
        "pin_tables": {"MSOP-10 (RM-10)": ad7983_pins,
                       "LFCSP_WD-10 3x3 (CP-10-9)": ad7983_pins + [pin("EP", "GND", "Exposed paddle connected to GND (connection optional); no pin number in datasheet", "Power", exposed_pad=True)]},
    }],
    "packages": {
        "MSOP-10 (RM-10)": {"jedec": "MO-187-BA", "page": 24, "pins": 10,
                            "dims_mm": {"D_body_length": d(2.90, 3.00, 3.10), "E1_body_width": d(2.90, 3.00, 3.10), "E_lead_span": d(4.65, 4.90, 5.15),
                                        "e_pitch": d(nom=0.50, basic=True), "A_height": d(None, None, 1.10), "A2_body_thickness": d(0.75, 0.85, 0.95),
                                        "A1_standoff": d(0.05, None, 0.15), "b_lead_width": d(0.17, None, 0.33), "c_lead_thickness": d(0.08, None, 0.23),
                                        "L_foot_length": d(0.40, 0.60, 0.80), "theta_deg": d(0, None, 8), "coplanarity": d(None, None, 0.10)}},
        "LFCSP_WD-10 3x3 (CP-10-9)": {"page": 24, "pins": 10, "exposed_pad": True,
                                      "dims_mm": {"D_E_body": d(nom=3.00, basic=True, note="BSC SQ"), "A_height": d(0.70, 0.75, 0.80),
                                                  "A1_standoff": d(None, 0.02, 0.05), "A3_terminal_thickness": d(nom=0.20, ref=True),
                                                  "unlabeled_side_view": "0.80 MAX / 0.55 NOM", "b_terminal_width": d(0.18, 0.23, 0.30),
                                                  "e_pitch": d(nom=0.50, basic=True), "L_terminal_length": d(0.30, 0.40, 0.50),
                                                  "EP_D2": d(2.23, 2.38, 2.48), "EP_E2": d(1.49, 1.64, 1.74), "pin1_indicator": "R 0.19"}},
    },
    "abs_max": [
        {"parameter": "Analog Inputs IN+, IN- to GND", "value": "-0.3 V to VREF + 0.3 V or ±130 mA"},
        {"parameter": "REF, VIO to GND", "value": "-0.3 V to +6 V"}, {"parameter": "VDD to GND", "value": "-0.3 V to +3 V"},
        {"parameter": "VDD to VIO", "value": "+3 V to -6 V"}, {"parameter": "Digital Inputs to GND", "value": "-0.3 V to VIO + 0.3 V"},
        {"parameter": "Digital Outputs to GND", "value": "-0.3 V to VIO + 0.3 V"}, {"parameter": "Storage Temperature Range", "value": "-65°C to +150°C"},
        {"parameter": "Junction Temperature", "value": "150°C"}, {"parameter": "θJA", "value": "MSOP 200°C/W; QFN (LFCSP) 48.7°C/W"},
        {"parameter": "θJC", "value": "MSOP 44°C/W; QFN (LFCSP) 2.96°C/W"},
        {"parameter": "Lead Temperature", "value": "Vapor Phase (60 sec) 215°C; Infrared (15 sec) 220°C"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- SN65LV1023A / SN65LV1224B
e = fileinfo("pdfs/sn65lv1023a.pdf", "C:/PartForge-Examples/ExampleProject/doc/datasheets/sn65lv1023a.pdf", "ic")
db = ["SYNC1", "SYNC2"] + [f"DIN{i}" for i in range(10)] + ["TCLK_R/F", "TCLK", "DGND", "DGND", "AVCC", "AGND", "DEN", "AGND", "DO-", "DO+", "AGND", "PWRDN", "AGND", "AVCC", "DVCC", "DVCC"]
rhb = [f"DIN{i}" for i in range(1, 10)] + ["TCLK_R/F", "TCLK", "DGND", "DGND", "DGND", "DGND", "AVCC", "AGND", "DEN", "AGND", "DO-", "DO+", "AGND", "PWRDN", "AGND", "AVCC", "DVCC", "DVCC", "DVCC", "DVCC", "SYNC1", "SYNC2", "DIN0"]
FUNC = {"SYNC1": ("SYNC pattern request input (ORed with SYNC2)", "Input"), "SYNC2": ("SYNC pattern request input (ORed with SYNC1)", "Input"),
        "TCLK_R/F": ("TCLK edge select (low = falling, high = rising)", "Input"), "TCLK": ("LVTTL reference clock input 10-66 MHz", "Input"),
        "DGND": ("Digital circuit ground", "Power"), "AGND": ("Analog circuit ground", "Power"), "AVCC": ("Analog circuit power supply", "Power"),
        "DVCC": ("Digital circuit power supply", "Power"), "DEN": ("LVDS output enable (low = high-Z)", "Input"),
        "DO-": ("Inverting LVDS differential output", "Output"), "DO+": ("Noninverting LVDS differential output", "Output"),
        "PWRDN": ("Power down, active low", "Input")}


def mk(names):
    out = []
    for i, n in enumerate(names, start=1):
        if n.startswith("DIN"):
            out.append(pin(i, n, "Parallel LVTTL data input", "Input"))
        else:
            f, t = FUNC[n]
            out.append(pin(i, n, f, t, active_low=(n == "PWRDN")))
    return out


des_db = {"AGND": [1, 12, 13], "AVCC": [4, 11], "DGND": [14, 20, 22], "DVCC": [21, 23], "LOCK": [10], "PWRDN": [7], "RCLK_R/F": [2], "RCLK": [9],
          "REFCLK": [3], "REN": [8], "RI+": [5], "RI-": [6]}
des_rhb = {"AGND": [10, 11, 28, 29, 30], "AVCC": [1, 8, 9], "DGND": [12, 13, 19, 21], "DVCC": [20, 22], "LOCK": [7], "PWRDN": [4], "RCLK_R/F": [31],
           "RCLK": [6], "REFCLK": [32], "REN": [5], "RI+": [2], "RI-": [3]}
DES_FUNC = {"AGND": ("Analog circuit ground", "Power"), "AVCC": ("Analog circuit power supply", "Power"), "DGND": ("Digital circuit ground", "Power"),
            "DVCC": ("Digital circuit power supply", "Power"), "LOCK": ("LVTTL output, low when PLL locked", "Output"),
            "PWRDN": ("Power down, active low", "Input"), "RCLK_R/F": ("RCLK edge select", "Input"), "RCLK": ("Recovered clock output", "Output"),
            "REFCLK": ("PLL reference clock input", "Input"), "REN": ("Output enable (low = ROUT/RCLK high-Z)", "Input"),
            "RI+": ("Noninverting LVDS serial data input", "Input"), "RI-": ("Inverting LVDS serial data input", "Input")}


def des_table(funcs, rout_pins):
    rows = []
    for name, nums in funcs.items():
        f, t = DES_FUNC[name]
        rows += [pin(n, name, f, t, active_low=name in ("LOCK", "PWRDN")) for n in nums]
    rows += [pin(n, f"ROUT{i}", "Parallel LVTTL data output", "Output", order_inferred_UNVERIFIED=True) for i, n in enumerate(rout_pins)]
    return sorted(rows, key=lambda p: int(p["number"]))


des_db_table = des_table(des_db, [28, 27, 26, 25, 24, 19, 18, 17, 16, 15])
des_rhb_table = des_table(des_rhb, [27, 26, 25, 24, 23, 18, 17, 16, 15, 14])
assert [int(p["number"]) for p in des_db_table] == list(range(1, 29)), "DB deserializer table incomplete"
assert [int(p["number"]) for p in des_rhb_table] == list(range(1, 33)), "RHB deserializer table incomplete"
e.update({
    "manufacturer": "Texas Instruments",
    "document": {"id": "SLLS621E", "title": "10-MHz To 66-MHz, 10:1 LVDS Serializer/Deserializer (SN65LV1023A, SN65LV1224B)", "revision": "E (Dec 2009)"},
    "sections": {"ordering": [22, 23], "pinout": [1, 6], "package_outline": [26, 27, 29], "land_pattern": [28], "abs_max": [7], "tape_reel": [24, 25]},
    "extraction_notes": [
        "Two devices in one datasheet (serializer SN65LV1023A, deserializer SN65LV1224B); file name only names the serializer.",
        "Pinout drawings on p1 exist only for SN65LV1023A (DB 28-SSOP, RHB 32-QFN); the deserializer pinout is only in the PIN FUNCTIONS table (p6).",
        "pdfplumber default x_tolerance=3 merges words on this TI/SPDF file ('Analogcircuitground'); x_tolerance=1.5 restores spaces (VERIFIED).",
        "Pages 26-28 (RHB mechanical, thermal pad, land pattern) have no text layer -> vision required.",
        "p29 DB drawing is a family drawing (14-38 pins); D depends on pin count table (28 pins: 9.90-10.50).",
        "Package option addendum contains the manufacturer typo 'SNLV1023ARHBTG4' (VERIFIED visually).",
        "RHB exposed thermal pad: no pin number/net in pin table; mechanical note: must be soldered to the board.",
    ],
    "devices": [
        {"base_part": "SN65LV1023A", "description": "10:1 LVDS serializer, 10-66 MHz", "category": "Interface / SerDes",
         "mpns": [{"mpn": "SN65LV1023ADB", "package": "SSOP-28 (DB)", "qty": 50}, {"mpn": "SN65LV1023ADBG4", "package": "SSOP-28 (DB)", "qty": 50},
                  {"mpn": "SN65LV1023ADBR", "package": "SSOP-28 (DB)", "qty": 2000}, {"mpn": "SN65LV1023ADBRG4", "package": "SSOP-28 (DB)", "qty": 2000},
                  {"mpn": "SN65LV1023ARHBR", "package": "VQFN-32 5x5 (RHB)", "qty": 3000}, {"mpn": "SN65LV1023ARHBRG4", "package": "VQFN-32 5x5 (RHB)", "qty": 3000},
                  {"mpn": "SN65LV1023ARHBT", "package": "VQFN-32 5x5 (RHB)", "qty": 250},
                  {"mpn": "SNLV1023ARHBTG4", "package": "VQFN-32 5x5 (RHB)", "qty": 250, "note": "as printed (typo for SN65LV1023ARHBTG4)"}],
         "pin_tables": {"SSOP-28 (DB)": mk(db), "VQFN-32 5x5 (RHB)": mk(rhb) + [pin("EP", "EP", "Exposed thermal pad, must be soldered (net not specified)", "Passive", exposed_pad=True)]}},
        {"base_part": "SN65LV1224B", "description": "1:10 LVDS deserializer, 10-66 MHz", "category": "Interface / SerDes",
         "mpns": ["SN65LV1224BDB", "SN65LV1224BDBG4", "SN65LV1224BDBR", "SN65LV1224BDBRG4", "SN65LV1224BRHBR", "SN65LV1224BRHBRG4", "SN65LV1224BRHBT", "SN65LV1224BRHBTG4"],
         "pin_functions_as_printed": {"SSOP-28 (DB)": dict(des_db, **{"ROUT0-ROUT9": "28-24, 19-15"}), "VQFN-32 5x5 (RHB)": dict(des_rhb, **{"ROUT0-ROUT9": "27-23, 18-14"})},
         "pin_tables": {"SSOP-28 (DB)": des_db_table, "VQFN-32 5x5 (RHB)": des_rhb_table},
         "note": "Active-low: LOCK, PWRDN (overbars). Pin tables built from the PIN FUNCTIONS table; ROUTx order inferred from range notation (UNVERIFIED: no pinout drawing). RHB thermal pad not listed."},
    ],
    "packages": {
        "SSOP-28 (DB)": {"vendor_code": "DB (R-PDSO-G**)", "drawing": "4040065/E 12/01", "jedec": "MO-150", "page": 29, "pins": 28,
                         "dims_mm": {"e_pitch": d(nom=0.65), "b_lead_width": d(0.22, None, 0.38), "E1_body_width": d(5.00, None, 5.60),
                                     "E_lead_span": d(7.40, None, 8.20), "D_body_length": d(9.90, None, 10.50, note="28-pin row of the A dimension table"),
                                     "A_height": d(None, None, 2.00), "A1_standoff": d(0.05, None, None), "c_lead_thickness": d(0.09, None, 0.25),
                                     "L_foot_length": d(0.55, None, 0.95), "gauge_plane": d(nom=0.25), "theta_deg": d(0, None, 8), "coplanarity": d(None, None, 0.10)},
                         "land_pattern": None},
        "VQFN-32 5x5 (RHB)": {"vendor_code": "RHB (S-PQFP-N32 / S-PVQFN-N32)", "drawing": "4204326/C", "jedec": "MO-220", "page": 26, "pins": 32, "exposed_pad": True,
                              "dims_mm": {"D_E_body": d(4.85, None, 5.15), "A_height": d(0.80, None, 1.00), "A1_standoff": d(0.00, None, 0.05),
                                          "A3_terminal_thickness": d(nom=0.20, ref=True), "e_pitch": d(nom=0.50, basic=True), "b_terminal_width": d(0.18, None, 0.30),
                                          "L_terminal_length": d(0.30, None, 0.50), "terminal_center_span_per_side": d(nom=3.50, basic=True),
                                          "coplanarity": d(None, None, 0.08), "EP_D2_E2": tol(3.45, 0.10, "p27 drawing 4206356-2/N")},
                              "land_pattern": {"page": 28, "drawing": "4207808-2/I 03/10", "pad_width_mm": 0.28, "pad_length_mm": 0.85, "pad_end_radius_mm": 0.14,
                                               "pitch_mm": 0.5, "outer_span_mm": 5.8, "inner_span_mm": 4.1, "row_center_distance_mm_DERIVED": 4.95,
                                               "thermal_pad_mm": [3.45, 3.45], "solder_mask_expansion_mm": 0.07, "solder_mask_web_mm": 0.08,
                                               "stencil": {"thickness_mm": 0.125, "pad_mm": [0.23, 0.8], "corner_radius_mm": 0.115, "inner_span_mm": 4.15,
                                                           "outer_span_mm": 5.75, "thermal_windows": "4 x 1.45 x 1.45 mm, 0.3 mm web (71% coverage)"},
                                               "thermal_vias": "9 x Ø0.3 mm on 1.0 mm grid (example)"}},
    },
    "abs_max": [
        {"parameter": "VCC to GND", "value": "-0.3V to 4V"}, {"parameter": "LVTTL input voltage", "value": "-0.3V to (VCC + 0.3V)"},
        {"parameter": "LVTTL output voltage", "value": "-0.3V to (VCC + 0.3V)"}, {"parameter": "LVDS receiver input voltage", "value": "-0.3V to 3.9V"},
        {"parameter": "LVDS driver output voltage", "value": "-0.3V to 3.9V"}, {"parameter": "LVDS output short circuit duration", "value": "10ms"},
        {"parameter": "Electrostatic discharge", "value": "HBM up to 6kV; MM up to 200V"}, {"parameter": "Junction temperature", "value": "150°C"},
        {"parameter": "Storage temperature", "value": "-65°C to 150°C"},
        {"parameter": "Package power dissipation TA=25°C", "value": "DB 1.27W (derate 10.3mW/°C); RHB 2.85W (derate 23.6mW/°C)"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- ADG736
e = fileinfo("pdfs/ADG736.pdf", "C:/PartForge-Examples/ExampleProject/ExampleProject/Dokumentation/ADG736.pdf", "ic")
e.update({
    "manufacturer": "Analog Devices",
    "document": {"id": "D00046-0-2/12(D)", "title": "CMOS Low Voltage 2.5 Ω Dual SPDT Switch", "revision": "D"},
    "sections": {"ordering": [12], "pinout": [6], "package_outline": [12], "land_pattern": [], "abs_max": [5]},
    "extraction_notes": [
        "PDF metadata subject reads '25 Ohm' while the page says '2.5 Ω' -> never trust metadata.",
        "Same RM-10 package code as AD7983 but different printed tolerances (b 0.15-0.30 vs 0.17-0.33, c 0.13-0.23 vs 0.08-0.23, L nom 0.55 vs 0.60, 0-6° vs 0-8°).",
        "Ordering guide has no quantities; 'W' prefix = automotive (ADW54010Z-0REEL).",
    ],
    "devices": [{
        "base_part": "ADG736", "description": "Dual SPDT analog switch, 2.5 Ω, 1.8-5.5 V", "category": "Analog Switch", "temperature_range": "-40°C to +125°C",
        "mpns": [{"mpn": m, "package": "MSOP-10 (RM-10)", "branding": b} for m, b in [
            ("ADG736BRM", "SAB"), ("ADG736BRM-REEL", "SAB"), ("ADG736BRM-REEL7", "SAB"), ("ADG736BRMZ", "SAB#"),
            ("ADG736BRMZ-REEL", "SAB#"), ("ADG736BRMZ-REEL7", "SAB#"), ("ADW54010Z-0REEL", "SAB#")]],
        "pin_tables": {"MSOP-10 (RM-10)": [
            pin(1, "IN1", "Logic control input", "Input"), pin(2, "S1A", "Source terminal (input or output)", "Passive"),
            pin(3, "GND", "Ground (0 V) reference", "Power"), pin(4, "S2A", "Source terminal (input or output)", "Passive"),
            pin(5, "IN2", "Logic control input", "Input"), pin(6, "D2", "Drain terminal (input or output)", "Passive"),
            pin(7, "S2B", "Source terminal (input or output)", "Passive"), pin(8, "VDD", "Most positive power supply", "Power"),
            pin(9, "S1B", "Source terminal (input or output)", "Passive"), pin(10, "D1", "Drain terminal (input or output)", "Passive")]},
        "truth_table": {"logic 0": "Switch A off, Switch B on", "logic 1": "Switch A on, Switch B off"},
    }],
    "packages": {"MSOP-10 (RM-10)": {"jedec": "MO-187-BA", "drawing": "091709-A", "page": 12, "pins": 10,
        "dims_mm": {"D_body_length": d(2.90, 3.00, 3.10), "E1_body_width": d(2.90, 3.00, 3.10), "E_lead_span": d(4.65, 4.90, 5.15),
                    "e_pitch": d(nom=0.50, basic=True), "A_height": d(None, None, 1.10), "A2_body_thickness": d(0.75, 0.85, 0.95),
                    "A1_standoff": d(0.05, None, 0.15), "b_lead_width": d(0.15, None, 0.30), "c_lead_thickness": d(0.13, None, 0.23),
                    "L_foot_length": d(0.40, 0.55, 0.70), "theta_deg": d(0, None, 6), "mold_draft": "15° MAX", "coplanarity": d(None, None, 0.10)}}},
    "abs_max": [
        {"parameter": "VDD to GND", "value": "-0.3 V to +6 V"}, {"parameter": "Analog, Digital Inputs", "value": "-0.3 V to VDD + 0.3 V or 30 mA, whichever occurs first"},
        {"parameter": "Continuous Current, S or D", "value": "30 mA"}, {"parameter": "Peak Current, S or D", "value": "100 mA (pulsed at 1 ms, 10% duty cycle max)"},
        {"parameter": "Operating Temperature Range (Automotive)", "value": "-40°C to +125°C"}, {"parameter": "Storage Temperature Range", "value": "-65°C to +150°C"},
        {"parameter": "Junction Temperature", "value": "150°C"}, {"parameter": "MSOP Package Power Dissipation", "value": "315 mW"},
        {"parameter": "θJA", "value": "205°C/W"}, {"parameter": "Lead Temperature (Soldering, 10 sec)", "value": "300°C"},
        {"parameter": "IR Reflow (Peak, <20 sec)", "value": "235°C"}, {"parameter": "Lead-Free Reflow Peak", "value": "260(+0/-5)°C, 10 sec to 40 sec"},
        {"parameter": "ESD", "value": "2 kV"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- AD5235
e = fileinfo("pdfs/AD5235.pdf", "C:/PartForge-Examples/ExampleProject/ExampleProject/Dokumentation/AD5235.pdf", "ic")
e.update({
    "manufacturer": "Analog Devices",
    "document": {"id": "D02816-0-6/12(F)", "title": "Nonvolatile Memory, Dual 1024-Position Digital Potentiometer", "revision": "F"},
    "sections": {"ordering": [30], "pinout": [9], "package_outline": [30], "land_pattern": [], "abs_max": [8]},
    "extraction_notes": [
        "MPN encodes a parametric value: BRUZ25 = 25 kΩ, BRUZ250 = 250 kΩ end-to-end resistance (RAB) -> same footprint/symbol, different value parameter.",
        "Reel suffix differs between variants as printed: '-RL7' (25k) vs '-R7' (250k).",
        "Active-low CS, WP and PR shown with overbars in drawing; RDY is an open-drain output; SDO needs pull-up (open-drain behaviour).",
    ],
    "devices": [{
        "base_part": "AD5235", "description": "Dual 1024-position nonvolatile digital potentiometer, SPI", "category": "Digital Potentiometer",
        "temperature_range": "-40°C to +85°C",
        "mpns": [{"mpn": "AD5235BRUZ25", "RAB_kohm": 25, "packing": "96", "branding": "5235B25"},
                 {"mpn": "AD5235BRUZ25-RL7", "RAB_kohm": 25, "packing": "1,000", "branding": "5235B25"},
                 {"mpn": "AD5235BRUZ250", "RAB_kohm": 250, "packing": "96", "branding": "5235B250"},
                 {"mpn": "AD5235BRUZ250-R7", "RAB_kohm": 250, "packing": "1,000", "branding": "5235B250"}],
        "pin_tables": {"TSSOP-16 (RU-16)": [
            pin(1, "CLK", "Serial input register clock", "Input"), pin(2, "SDI", "Serial data input", "Input"),
            pin(3, "SDO", "Serial data output (needs 1k-10k pull-up)", "OpenCollector"), pin(4, "GND", "Logic ground", "Power"),
            pin(5, "VSS", "Negative supply (0 V for single supply)", "Power"), pin(6, "A1", "Terminal A of RDAC1", "Passive"),
            pin(7, "W1", "Wiper of RDAC1", "Passive"), pin(8, "B1", "Terminal B of RDAC1", "Passive"), pin(9, "B2", "Terminal B of RDAC2", "Passive"),
            pin(10, "W2", "Wiper of RDAC2", "Passive"), pin(11, "A2", "Terminal A of RDAC2", "Passive"), pin(12, "VDD", "Positive power supply", "Power"),
            pin(13, "WP", "Optional write protect (active low)", "Input", active_low=True), pin(14, "PR", "Optional hardware override preset", "Input", active_low=True),
            pin(15, "CS", "Serial register chip select, active low", "Input", active_low=True), pin(16, "RDY", "Ready, active-high open-drain output", "OpenCollector")]},
    }],
    "packages": {"TSSOP-16 (RU-16)": {"jedec": "MO-153-AB", "page": 30, "pins": 16,
        "dims_mm": {"D_body_length": d(4.90, 5.00, 5.10), "E1_body_width": d(4.30, 4.40, 4.50), "E_lead_span": d(nom=6.40, basic=True),
                    "e_pitch": d(nom=0.65, basic=True), "b_lead_width": d(0.19, None, 0.30), "A_height": d(None, None, 1.20),
                    "A1_standoff": d(0.05, None, 0.15), "c_lead_thickness": d(0.09, None, 0.20), "L_foot_length": d(0.45, 0.60, 0.75),
                    "theta_deg": d(0, None, 8), "coplanarity": d(None, None, 0.10)}}},
    "abs_max": [
        {"parameter": "VDD to GND", "value": "-0.3 V to +7 V"}, {"parameter": "VSS to GND", "value": "+0.3 V to -7 V"}, {"parameter": "VDD to VSS", "value": "7 V"},
        {"parameter": "VA, VB, VW to GND", "value": "VSS - 0.3 V to VDD + 0.3 V"}, {"parameter": "IA, IB, IW", "value": "Pulsed ±20 mA; Continuous ±2 mA"},
        {"parameter": "Digital Input and Output Voltage to GND", "value": "-0.3 V to VDD + 0.3 V"},
        {"parameter": "Operating Temperature Range", "value": "-40°C to +85°C"}, {"parameter": "Maximum Junction Temperature", "value": "150°C"},
        {"parameter": "Storage Temperature Range", "value": "-65°C to +150°C"},
        {"parameter": "Lead Temperature, Soldering", "value": "Vapor Phase (60 sec) 215°C; Infrared (15 sec) 220°C"},
        {"parameter": "Thermal Resistance", "value": "θJA TSSOP-16 150°C/W; θJC 28°C/W"},
    ],
})
entries.append(e)

# ---------------------------------------------------------------- Vishay CRCW
e = fileinfo("pdfs/vishay_dcrcwe3.pdf", "https://www.vishay.com/docs/20035/dcrcwe3.pdf (downloaded 2026-10-07)", "passive_series")
sizes = ["0402", "0603", "0805", "1206", "1210", "1218", "2010", "2512"]
p70 = [0.10, 0.125, 0.25, 0.25, 0.5, 1.0, 0.75, 1.0]
umax = [75, 75, 150, 200, 200, 200, 400, 500]
uins = [100, 100, 200, 300, 300, 300, 300, 300]
jmp = [1.5, 2.0, 2.5, 3.5, 5.0, 7.0, 6.0, 7.0]
dims = {"0402": ("1.0 ± 0.05", "0.5 ± 0.05", "0.35 ± 0.05", "0.25 ± 0.10", "0.2 ± 0.10", 0.65),
        "0603": ("1.55 + 0.10 / - 0.05", "0.85 ± 0.10", "0.45 ± 0.05", "0.3 ± 0.20", "0.3 ± 0.20", 2),
        "0805": ("2.0 + 0.20 / - 0.10", "1.25 ± 0.15", "0.5 ± 0.10", "0.3 + 0.20 / - 0.10", "0.3 ± 0.20", 5.5),
        "1206": ("3.2 + 0.10 / - 0.20", "1.6 ± 0.15", "0.55 ± 0.05", "0.45 ± 0.20", "0.4 ± 0.20", 10),
        "1210": ("3.2 ± 0.20", "2.5 ± 0.20", "0.55 ± 0.05", "0.45 ± 0.20", "0.4 ± 0.20", 16),
        "1218": ("3.2 + 0.10 / - 0.20", "4.6 ± 0.15", "0.55 ± 0.05", "0.45 ± 0.20", "0.4 ± 0.20", 29.5),
        "2010": ("5.0 ± 0.15", "2.5 ± 0.15", "0.6 ± 0.10", "0.6 ± 0.20", "0.6 ± 0.20", 25.5),
        "2512": ("6.3 ± 0.20", "3.15 ± 0.15", "0.6 ± 0.10", "0.6 ± 0.20", "0.6 ± 0.20", 40.5)}
pads = {"0402": (None, (0.45, 0.6, 0.6, 1.65)), "0603": ((0.65, 1.10, 1.25, 2.85), (0.75, 0.75, 1.00, 2.25)),
        "0805": ((0.90, 1.30, 1.60, 3.50), (1.00, 0.95, 1.45, 2.90)), "1206": ((1.40, 1.40, 1.95, 4.20), (1.50, 1.05, 1.80, 3.60)),
        "1210": ((1.80, 1.45, 2.95, 4.70), (1.70, 1.10, 2.80, 3.90)), "1218": ((1.80, 1.30, 5.10, 4.40), (1.90, 1.10, 4.90, 4.10)),
        "2010": ((3.40, 1.65, 2.85, 6.70), (3.50, 1.45, 2.80, 6.40)), "2512": ((4.60, 1.60, 3.65, 7.80), (4.75, 1.45, 3.50, 7.65))}
packaging = {"0402": [("ED", "ET7", 10000, "paper 8 mm, 2 mm pitch, 180 mm/7in"), ("EE", "EF4", 50000, "paper 8 mm, 2 mm pitch, 330 mm/13in")],
             "0603": [("EI", "ET2", 5000, "paper 8 mm, 2 mm pitch, 7in"), ("ED", "ET3", 10000, "paper 8 mm, 2 mm pitch, 7in"),
                      ("EE", "ET8", 50000, "paper 8 mm, 2 mm pitch, 13in"), ("EA", "ET1", 5000, "paper 8 mm, 4 mm pitch, 7in"),
                      ("EC", "ET6", 20000, "paper 8 mm, 4 mm pitch, 13in")],
             "0805": [("EA", "ET1", 5000, "paper 8 mm, 4 mm, 7in"), ("EC", "ET6", 20000, "paper 8 mm, 4 mm, 13in")],
             "1206": [("EA", "ET1", 5000, "paper 8 mm, 4 mm, 7in"), ("EC", "ET6", 20000, "paper 8 mm, 4 mm, 13in")],
             "1210": [("EA", "ET1", 5000, "paper 8 mm, 4 mm, 7in"), ("EC", "ET6", 20000, "paper 8 mm, 4 mm, 13in")],
             "1218": [("EK", "ET9", 4000, "blister 12 mm, 4 mm, 7in")], "2010": [("EF", "E02", 4000, "blister 12 mm, 4 mm, 7in")],
             "2512": [("EG", "E67", 2000, "blister 12 mm, 8 mm, 7in"), ("EH", "E82", 4000, "blister 12 mm, 4 mm, 7in")]}
E96 = [100, 102, 105, 107, 110, 113, 115, 118, 121, 124, 127, 130, 133, 137, 140, 143, 147, 150, 154, 158, 162, 165, 169, 174, 178, 182, 187, 191,
       196, 200, 205, 210, 215, 221, 226, 232, 237, 243, 249, 255, 261, 267, 274, 280, 287, 294, 301, 309, 316, 324, 332, 340, 348, 357, 365, 374,
       383, 392, 402, 412, 422, 432, 442, 453, 464, 475, 487, 499, 511, 523, 536, 549, 562, 576, 590, 604, 619, 634, 649, 665, 681, 698, 715, 732,
       750, 768, 787, 806, 825, 845, 866, 887, 909, 931, 953, 976]
E24 = [100, 110, 120, 130, 150, 160, 180, 200, 220, 240, 270, 300, 330, 360, 390, 430, 470, 510, 560, 620, 680, 750, 820, 910]


def series_values(base, lo_ohm, hi_ohm):
    vals = set()
    for dec in range(-2, 6):
        for b in base:
            v = round(b * 10 ** dec, 6)
            if lo_ohm - 1e-9 <= v <= hi_ohm + 1e-9:
                vals.add(v)
    return sorted(vals)


n_e24_10M = len(series_values(E24, 1, 10e6))
n_e24e96_10M = len(set(series_values(E24, 1, 10e6)) | set(series_values(E96, 1, 10e6)))
n_e24_22M = len(series_values(E24, 1, 2.2e6))
n_e24e96_22M = len(set(series_values(E24, 1, 2.2e6)) | set(series_values(E96, 1, 2.2e6)))
e.update({
    "manufacturer": "Vishay",
    "document": {"id": "Document Number 20035", "title": "D/CRCW e3 Standard Thick Film Chip Resistors", "revision": "14-Apr-2026"},
    "sections": {"ordering": [3], "value_ranges": [1, 2], "package_outline": [11], "land_pattern": [11], "ratings": [1, 2], "abs_max": []},
    "extraction_notes": [
        "Merged table cells on p1 (resistance range spans 0402-1210, 1218 alone, 2010-2512) are flattened in the text layer.",
        "Two operation modes: p1 lists extended-mode P70 for 0402/0603/0805 (0.10/0.125/0.25 W); standard mode is 0.063/0.10/0.125 W (p2).",
        "Solder pad naming: G = inner gap, Y = pad length, X = pad width, Z = outer extent (Z = G + 2Y holds for all rows).",
    ],
    "series": {
        "name": "CRCW e3 (D/CRCW e3)", "type": "thick film chip resistor", "sizes": sizes,
        "metric_codes": dict(zip(sizes, ["RR1005M", "RR1608M", "RR2012M", "RR3216M", "RR3225M", "RR3246M", "RR5025M", "RR6332M"])),
        "mpn_scheme": {
            "pattern": "CRCW{size:4}{resistance:4}{tolerance:1}{tcr:1}{packaging:2}",
            "examples_from_datasheet": {"CRCW0603562RFKEA": "0603, 562 Ω, ±1 %, ±100 ppm/K, packaging EA",
                                        "CRCW06030000Z0EA": "0603 jumper (0 Ω), tolerance Z, TCR 0, packaging EA"},
            "resistance_code": "4 characters; R = decimal point (Ω), K = thousand, M = million; '0000' = jumper",
            "tolerance": {"F": "±1 %", "J": "±5 %", "Z": "jumper"}, "tcr": {"K": "±100 ppm/K", "N": "±200 ppm/K", "0": "jumper"},
            "packaging_codes": ["EA", "EC", "ED", "EE", "EF", "EG", "EH", "EI", "EK"], "lead_free": "E.. = lead (Pb)-free",
            "product_description_format": "D11/CRCW0603 100 562R 1 % ET1 e3 (type/size, TCR, resistance, tolerance, packaging, e3)",
        },
        "decode_test_vectors_DERIVED": {
            "CRCW060310K0FKEA": {"size": "0603", "R_ohm": 10000, "tol": "±1 %", "tcr": "±100 ppm/K", "pack": "EA = ET1 5000 pcs 7in"},
            "CRCW08054K70JNEA": {"size": "0805", "R_ohm": 4700, "tol": "±5 %", "tcr": "±200 ppm/K", "pack": "EA"},
            "CRCW04021M00FKED": {"size": "0402", "R_ohm": 1000000, "tol": "±1 %", "tcr": "±100 ppm/K", "pack": "ED = ET7 10000 pcs"},
            "CRCW12064R70FNEA": {"size": "1206", "R_ohm": 4.7, "tol": "±1 %", "tcr": "±200 ppm/K", "pack": "EA", "valid": "yes (F+N only 1 Ω-9.76 Ω)"},
        },
        "value_rules_p2": [
            {"tcr": "±200 ppm/K", "tol": "±5 %", "range_ohm": "1 to 10M (1218: 2.2M)", "series": "E24"},
            {"tcr": "±200 ppm/K", "tol": "±1 %", "range_ohm": "1 to 9.76", "series": "E24; E96"},
            {"tcr": "±100 ppm/K", "tol": "±1 %", "range_ohm": "1 to 10M (1218: 2.2M)", "series": "E24; E96"},
            {"jumper": "0 Ω, ≤ 20 mΩ", "Imax_A": dict(zip(sizes, jmp))},
        ],
        "value_counts_DERIVED": {"E24 1Ω..10MΩ": n_e24_10M, "E24∪E96 1Ω..10MΩ": n_e24e96_10M, "E24 1Ω..2.2MΩ (1218)": n_e24_22M,
                                 "E24∪E96 1Ω..2.2MΩ (1218)": n_e24e96_22M},
        "ratings": [{"size": s, "P70_W": p, "Umax_V": u, "Uins_V": ui} for s, p, u, ui in zip(sizes, p70, umax, uins)],
        "ratings_standard_mode_p2": {"0402": {"P70_W": 0.063, "Umax_V": 50}, "0603": {"P70_W": 0.10, "Umax_V": 75}, "0805": {"P70_W": 0.125, "Umax_V": 150}},
        "operating_temperature": "-55 °C to +155 °C", "film_temperature_max": "155 °C",
        "dimensions_mm": {s: dict(zip(["L", "W", "H", "T1", "T2", "mass_mg"], v)) for s, v in dims.items()},
        "solder_pads_mm": {s: {"wave": (dict(zip(["G", "Y", "X", "Z"], w)) if w else None), "reflow": dict(zip(["G", "Y", "X", "Z"], r))} for s, (w, r) in pads.items()},
        "packaging": {s: [{"code": a, "alt_code": b, "qty": q, "desc": t} for a, b, q, t in v] for s, v in packaging.items()},
    },
})
entries.append(e)

# ---------------------------------------------------------------- KEMET C1002 X7R
e = fileinfo("pdfs/kemet_C1002_X7R_SMD.pdf", "https://content.kemet.com/datasheets/KEM_C1002_X7R_SMD.pdf (downloaded 2026-10-07)", "passive_series")
kem = json.loads((CORPUS / "groundtruth" / "kemet_C1002_X7R_series.json").read_text(encoding="utf-8"))
e.update({
    "manufacturer": "KEMET (YAGEO Group)",
    "document": {"id": "C1002_X7R", "title": "Surface Mount Multilayer Ceramic Chip Capacitors (SMD MLCCs) X7R Dielectric, 6.3-250 VDC (Commercial Grade)", "revision": "2026-09-01"},
    "sections": {"ordering": [2], "value_ranges": [4, 5, 6, 7, 8], "package_outline": [3], "thickness_and_packaging_qty": [9, 10, 11], "land_pattern": [12], "abs_max": []},
    "extraction_notes": [
        "Availability tables are sparse matrices (cap rows x case/voltage columns): plain text loses column alignment -> use char x-coordinates (kemet_matrix.py) or vision.",
        "Superscript footnote markers precede size codes on p3 ('¹0402' extracted as '10402').",
        "Footnote '¹' in matrix cells (U+00B9 at body size) = 'available only in K and M tolerance'.",
        "Land pattern 'C' is the distance from component centre to pad centre (half the pad pitch), per drawing on p12.",
        "Row labels '100 - 200*' etc. are value ranges: * = E24 decade values, ** = E12 decade values.",
    ],
    "series": {
        "name": "KEMET X7R commercial SMD MLCC (C-series, Standard)",
        "mpn_scheme": {
            "pattern": "C{case:4}{spec:1}{cap_code:3}{tol:1}{voltage:1}{dielectric:1}{failure_rate:1}{termination:1}{cspec:0-4}",
            "example_from_datasheet": "C1206C106M4RACTU",
            "case": ["0402", "0603", "0805", "1206", "1210", "1805", "1808", "1812", "1825", "2220", "2225"],
            "spec": {"C": "Standard"}, "cap_code": "two significant digits + number of zeros, in pF",
            "tolerance": {"J": "±5%", "K": "±10%", "M": "±20%"},
            "voltage": {"9": 6.3, "8": 10, "4": 16, "3": 25, "6": 35, "5": 50, "1": 100, "2": 200, "A": 250},
            "dielectric": {"R": "X7R"}, "failure_rate": {"A": "N/A"}, "termination": {"C": "100% Matte Sn"},
            "cspec": {"(blank)": "Bulk Bag/Unmarked (default)", "TU": "7in Reel/Unmarked", "7411": "13in Reel/Unmarked (EIA 0603 and smaller)",
                      "7210": "13in Reel/Unmarked (EIA 0805 and larger)", "TM": "7in Reel/Marked", "7040": "13in Reel/Marked (EIA 0603)",
                      "7215": "13in Reel/Marked (EIA 0805 and larger)"},
        },
        "decode_test_vectors_DERIVED": {
            "C1206C106M4RACTU": {"case": "1206", "C": "10 µF", "tol": "±20%", "V": 16, "available": "EH (1.60±0.20 mm), J/K/M"},
            "C0603C104K5RACTU": {"case": "0603", "C": "100 nF", "tol": "±10%", "V": 50, "available": "CJ (0.80±0.15 mm)"},
            "C0402C104K3RACTU": {"case": "0402", "C": "100 nF", "tol": "±10%", "V": 25, "available": "BB¹ -> K/M only"},
            "C0805C106J8RACTU": {"case": "0805", "C": "10 µF", "tol": "±5%", "V": 10, "available": "NOT orderable (DH¹: K/M only)"},
            "C1210C476M8RACTU": {"case": "1210", "C": "47 µF", "tol": "±20%", "V": 10, "available": "FS¹ (2.50±0.30 mm)"},
            "C0402C105K8RACTU": {"case": "0402", "C": "1 µF", "tol": "±10%", "V": 10, "available": "NOT in table (0402 max 0.47 µF)"},
        },
        "dimensions_mm": {
            "0402": {"metric": "1005", "L": "1.00 ±0.05", "W": "0.50 ±0.05", "B": "0.30 ±0.10", "S_min": 0.30, "mounting": "reflow only"},
            "0603": {"metric": "1608", "L": "1.60 ±0.15", "W": "0.80 ±0.15", "B": "0.35 ±0.15", "S_min": 0.50, "mounting": "wave or reflow"},
            "0805": {"metric": "2012", "L": "2.00 ±0.20", "W": "1.25 ±0.20", "B": "0.50 ±0.25", "S_min": 0.70, "mounting": "wave or reflow"},
            "1206": {"metric": "3216", "L": "3.20 ±0.20", "W": "1.60 ±0.20", "B": "0.50 ±0.25", "S_min": 1.50, "mounting": "wave or reflow"},
            "1210": {"metric": "3225", "L": "3.20 ±0.20", "W": "2.50 ±0.20", "B": "0.50 ±0.25", "S_min": 1.50, "mounting": "reflow only"},
            "1805": {"metric": "4513", "L": "4.50 ±0.50", "W": "1.27 ±0.38", "B": "0.60 ±0.35", "S_min": 2.90, "mounting": "reflow only"},
            "1808": {"metric": "4520", "L": "4.70 ±0.50", "W": "2.00 ±0.20", "B": "0.60 ±0.35", "S_min": 2.90, "mounting": "reflow only"},
            "1812": {"metric": "4532", "L": "4.50 ±0.30", "W": "3.20 ±0.30", "B": "0.60 ±0.35", "S_min": 2.30, "mounting": "reflow only"},
            "1825": {"metric": "4564", "L": "4.50 ±0.30", "W": "6.40 ±0.40", "B": "0.60 ±0.35", "S_min": 2.30, "mounting": "reflow only"},
            "2220": {"metric": "5650", "L": "5.70 ±0.40", "W": "5.00 ±0.40", "B": "0.60 ±0.35", "S_min": 3.50, "mounting": "reflow only"},
            "2225": {"metric": "5664", "L": "5.60 ±0.40", "W": "6.40 ±0.40", "B": "0.60 ±0.35", "S_min": 3.20, "mounting": "reflow only"},
            "T": "per thickness code (Table 2A) -> see groundtruth file",
        },
        "land_pattern_ipc7351": kem["land_pattern_ipc7351"],
        "availability_summary_by_case_and_voltage": kem["summary_by_case_and_voltage"],
        "availability_detail_file": "groundtruth/kemet_C1002_X7R_series.json",
        "availability_cell_count": len(kem["availability"]),
        "thickness_code_count": len(kem["thickness_codes"]),
        "operating_temperature": "-55°C to +125°C", "capacitance_range": "10 pF to 47 µF", "tolerances": "±5%, ±10%, ±20%",
    },
})
entries.append(e)

# ---------------------------------------------------------------- Bourns SRR1260
e = fileinfo("pdfs/bourns_SRR1260.pdf", "https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf (downloaded 2026-10-07)", "passive_series")
rows = """1R0Y 1.0 30 26 7.96 100.00 7.8 9.40 10.00 158
1R2Y 1.2 30 18 7.96 91.10 8.0 9.20 9.80 123
1R5Y 1.5 30 24 7.96 86.00 9.5 8.80 9.00 123
2R2Y 2.2 30 22 7.96 70.00 10.5 8.20 8.50 100
2R4Y 2.4 30 18 7.96 63.80 11.5 7.80 8.00 100
3R3Y 3.3 30 20 7.96 40.00 12.0 7.60 7.80 74
3R5Y 3.5 30 22 7.96 37.60 13.0 7.50 7.60 74
4R7Y 4.7 30 19 7.96 36.70 15.5 6.80 7.00 65
5R6Y 5.6 30 19 7.96 33.00 16.2 6.70 6.90 58
6R1Y 6.1 30 21 7.96 29.80 17.0 6.60 6.80 58
6R8Y 6.8 30 20 7.96 28.20 18.0 6.30 6.50 53
7R6Y 7.6 30 16 7.96 27.90 19.0 6.00 6.20 53
8R2Y 8.2 30 18 7.96 24.00 19.5 5.70 5.80 48
100M 10.0 20 32 2.52 21.00 20.0 5.50 5.50 44
120M 12.0 20 27 2.52 19.40 23.0 5.20 5.00 41
150M 15.0 20 25 2.52 17.60 27.0 5.00 4.60 36
180M 18.0 20 28 2.52 15.50 36.0 4.20 3.90 32
220M 22.0 20 29 2.52 13.40 43.0 4.00 3.70 30
270M 27.0 20 26 2.52 12.70 45.0 3.60 3.30 28
330M 33.0 20 27 2.52 9.97 60.0 3.00 2.80 24
390M 39.0 20 22 2.52 10.40 70.0 2.80 2.70 22
470M 47.0 20 22 2.52 7.63 86.0 2.60 2.50 20
560M 56.0 20 24 2.52 7.92 100.0 2.30 2.20 18
680M 68.0 20 22 2.52 7.43 110.0 2.10 2.10 17
820M 82.0 20 25 2.52 6.85 145.0 1.95 1.90 15
101M 100.0 20 26 0.796 6.07 180.0 1.70 1.70 14
121K 120.0 10 26 0.796 5.50 210.0 1.65 1.65 13
151K 150.0 10 20 0.796 5.00 260.0 1.55 1.55 11
181K 180.0 10 26 0.796 4.50 320.0 1.40 1.40 10
221K 220.0 10 22 0.796 4.20 380.0 1.38 1.30 9
271K 270.0 10 20 0.796 3.60 450.0 1.30 1.20 8
331K 330.0 10 22 0.796 3.20 580.0 1.15 1.10 8
391K 390.0 10 20 0.796 2.80 700.0 1.08 1.00 7
471K 470.0 10 18 0.796 2.60 820.0 0.95 0.90 6
561K 560.0 10 22 0.796 2.40 1000.0 0.88 0.80 6
681K 680.0 10 18 0.796 2.20 1150.0 0.80 0.75 5
821K 820.0 10 20 0.796 2.00 1500.0 0.73 0.63 5
102K 1000.0 10 30 0.252 1.80 1700.0 0.68 0.60 4"""
parts = []
for line in rows.splitlines():
    c, L, t, q, f, srf, rdc, irms, isat, k = line.split()
    parts.append({"mpn": f"SRR1260-{c}", "L_uH": float(L), "tol_pct": int(t), "Q_typ": int(q), "test_freq_MHz": float(f), "SRF_typ_MHz": float(srf),
                  "RDC_max_mohm": float(rdc), "Irms_max_A": float(irms), "Isat_typ_A": float(isat), "K_factor": int(k)})
e.update({
    "manufacturer": "Bourns",
    "document": {"id": "SRR1260 Series", "title": "SRR1260 Series - Shielded SMD Power Inductors", "revision": "REV. 03/26 (packaging page)"},
    "sections": {"ordering": [1], "value_ranges": [1], "package_outline": [1], "land_pattern": [2], "ratings": [1], "tape_reel": [3], "abs_max": []},
    "extraction_notes": [
        "RDC column unit is mΩ but the Symbol-font Ω is extracted as 'W' -> text says '(mW)'.",
        "Off-page/clipped text: p1 text layer contains the recommended-layout labels (2.9/5.4/6.8) positioned below the page (y > 792 pt); p2 contains product-dimension labels outside/clipped. Filter chars by page bbox.",
        "No explicit ordering-code legend: inductance code = 2 significant digits + zeros in µH, 'R' = decimal point; tolerance letter Y=±30 %, M=±20 %, K=±10 % (DERIVED from the table, consistent for all 38 rows).",
        "'Available in E12 values' claim, yet 2.4/3.5/6.1/7.6 µH are not E12 values.",
    ],
    "series": {
        "name": "SRR1260", "type": "shielded SMD power inductor", "pins": 2, "polarized": False,
        "mpn_scheme_DERIVED": {"pattern": "SRR1260-{L_code:3}{tol:1}", "L_code": "R = decimal point (µH), else 2 digits + number of zeros (µH)",
                               "tol": {"Y": "±30 %", "M": "±20 %", "K": "±10 %"}},
        "parts": parts,
        "general": {"inductance_test": "1R0Y-8R2Y: 100 kHz/0.1 V; 100M-102K: 1 kHz/0.1 V", "operating_temperature": "-40 °C to +125 °C (temperature rise included)",
                    "storage_temperature": "-40 °C to +125 °C", "temperature_rise": "40 °C typ. at rated Irms", "inductance_drop": "25 % typ. at Isat",
                    "MSL": 1, "packaging": "600 pcs per reel (330 mm reel, 24 mm tape)", "terminal_finish": "Sn"},
        "dimensions_mm": {"L": "12.5 ± 0.3", "W": "12.5 ± 0.3", "H": "6.0 ± 0.5", "terminal_width": "5.0 ± 0.3", "terminal_inner_gap": "7.0 TYP",
                          "marking": "inductance code printed on top (e.g. '100')"},
        "land_pattern_mm": {"pad_width_X": "2.9 REF", "pad_length_Y": "5.4 REF", "pad_gap_G": "6.8 REF",
                            "pad_center_distance_DERIVED": 9.7, "outer_extent_DERIVED": 12.6, "orientation": "pads side by side along X"},
    },
})
entries.append(e)

manifest = {
    "schema": "partforge-datasheet-corpus/1",
    "created": "2026-10-07",
    "root": "corpus/ (paths in 'file' are relative to this folder)",
    "status_legend": {"VERIFIED": "value read from the PDF (rendered page and/or text layer)", "DERIVED": "computed from verified values or naming rules",
                      "UNVERIFIED": "assumption, not checked"},
    "conventions": {
        "dims_mm": "min/nom/max in millimetres; basic=True means BSC; ref=True means REF; JEDEC-style symbols (D body length, E lead span, E1 body width, e pitch, b lead width, c lead thickness, L foot length, A height, A1 standoff)",
        "electrical_type": ALTIUM_TYPES,
        "sections": "1-based PDF page numbers (not printed page labels) where each information type is found",
        "fields_ending_DERIVED_or_UNVERIFIED": "carry that status; everything else is VERIFIED",
    },
    "entries": entries,
}
out = CORPUS / "manifest.json"
out.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
print("written", out, "entries", len(entries), "bytes", out.stat().st_size)
print("value counts", n_e24_10M, n_e24e96_10M, n_e24_22M, n_e24e96_22M)
