# PartForge – Datasheet Test Corpus with Ground Truth

Research agent report (UNDERSTAND phase), 2026-10-07.
Status tags: **VERIFIED** = read from the PDF by me (rendered page image and/or text layer) or tested by running code; **DERIVED** = computed from verified values / naming rules; **UNVERIFIED** = assumption, not checked.

Scratchpad root (abbreviated `SP` below): `<scratchpad>`

---

## 1. What was produced (VERIFIED)

| Path (under `SP/corpus/`) | Content |
|---|---|
| `pdfs/` | 11 PDFs (8 local copies + 3 downloads), the test corpus |
| `downloads/` | original downloads (fresh folder, untrusted data, nothing executed) |
| `manifest.json` | machine-readable ground truth, one entry per PDF, `file` relative to `corpus/` (146 KB) |
| `groundtruth/kemet_C1002_X7R_series.json` | full KEMET X7R availability matrix (3342 cells), thickness codes, IPC land patterns (700 KB) |
| `work/<stem>/p###.txt`, `p###.plumber.txt` | per-page text from pypdf and pdfplumber (for text-pipeline tests) |
| `work/analysis.json` | page count, encryption, chars/images per page, keyword hits |
| `render/` | PNG renders of the key pages used for visual verification |
| `tools/analyze.py` | page stats + keyword page classifier (pypdf + pdfplumber) |
| `tools/render.py` | page/crop renderer (pypdfium2) – `python -I render.py <pdf> <pages> <out_dir> [dpi] [x0,y0,x1,y1]` |
| `tools/kemet_matrix.py`, `tools/kemet_finalize.py` | coordinate-based extraction of KEMET sparse "waterfall" tables |
| `tools/build_manifest.py` | builds `manifest.json` (all ground truth is in this file as Python data) |
| `tools/crosscheck.py` | checks manifest values against the text layer (MPNs, dimensions, Bourns rows) |
| `tools/mpn_decoders.py` | reference decoders/encoders for Vishay CRCW and KEMET X7R, with asserts |
| `.venv/` | Python 3.13.5 venv: pypdf 6.19.0, pdfplumber 0.11.10, pypdfium2 5.14.0 (PDFium 156.0.8076.0), Pillow 12.3.0, fonttools 4.66.1 |

All Python was run as `SP/corpus/.venv/Scripts/python.exe -I <script> <args>` from `SP/corpus/tools` (never from inside `downloads/`).

Cross-check results (VERIFIED, `crosscheck.py`): all 111 listed MPNs (73 IC + 38 Bourns; the DERIVED HCPL option MPNs are excluded) occur verbatim in the PDF text layers; all 38 Bourns rows match the text layer exactly; every dimension value in the manifest was found in the text layer **except** values on pages without a usable text layer (they were read visually) and min/max values computed from `nom ± tol` (DERIVED).

Note for other agents (VERIFIED): the `Read` tool cannot render PDF pages here (`pdftoppm is not installed`). Render with `tools/render.py` and read the PNG instead.

---

## 2. Corpus inventory

| # | File (`pdfs/`) | Manufacturer | Doc | Pages | Text layer | Difficulty tags |
|---|---|---|---|---|---|---|
| 1 | `opa656.pdf` | Texas Instruments | SBOS196G | 25 | yes, **except p21–24** (0 chars, vector) | 2 packages, mechanical/land pattern only as vector graphics, doc-internal qty conflict |
| 2 | `LTC6244.pdf` | Linear Technology (ADI) | 6244fb | 26 | yes | dual op amp, DFN exposed pad = pin 9, 22 orderable MPNs, no pin-function table |
| 3 | `6N137.pdf` | Fairchild (onsemi) | Rev 1.0.8, Jan 2011 | 12 | yes (p9 rotated labels scrambled) | 5 devices in one PDF, single vs dual pinout, 3 package options, THT + SMD, land pattern in inches(mm) |
| 4 | `25AA02E48.pdf` | Microchip | DS22123B | 26 | yes, **p16–19 glyph-encoded** (`(cid:N)` / `/gNN`) | encrypted (owner pw), active-low overbars, VDD/VCC naming conflict, tabular package dims |
| 5 | `AD7983.pdf` | Analog Devices | Rev A | 24 | yes | pin Type column (AI/DI/DO/P), QFN paddle without pin number, no land pattern |
| 6 | `sn65lv1023a.pdf` | Texas Instruments | SLLS621E | 30 | yes, **except p26–28**; pdfplumber merges words | 2 devices (SER + DES), 28-SSOP + 32-QFN, exposed pad, family drawing, MPN typo in addendum |
| 7 | `ADG736.pdf` | Analog Devices | Rev D | 12 | yes | metadata wrong ("25 Ohm"), RM-10 with different tolerances than AD7983 |
| 8 | `AD5235.pdf` | Analog Devices | Rev F | 32 | yes | MPN encodes value (25k/250k), TOC on p2–3 causes false keyword hits |
| 9 | `vishay_dcrcwe3.pdf` | Vishay | 20035, 14-Apr-2026 | 13 | yes | resistor series, merged table cells, two power modes |
| 10 | `kemet_C1002_X7R_SMD.pdf` | KEMET (YAGEO Group) | C1002_X7R 2026-09-01 | 28 | yes | MLCC series, sparse availability matrix, superscript footnotes, "C" = half pitch |
| 11 | `bourns_SRR1260.pdf` | Bourns | SRR1260, REV 03/26 | 4 | yes | inductor series, Ω→"W" font glitch, off-page hidden text, no ordering legend |

SHA-256 of every file is in `manifest.json` (`sha256`). Local sources (read-only, copied with `cp -p`; source directories anonymized): `<datasheet-source>/{opa656,LTC6244}.pdf`, `<datasheet-source>/6N137.pdf`, `<datasheet-source>/{25AA02E48,AD7983,sn65lv1023a}.pdf`, `<datasheet-source>/{ADG736,AD5235}.pdf`.

### 2.1 Downloads (VERIFIED, `curl -L`, 2026-10-07)

| URL | Result | Saved as |
|---|---|---|
| `https://www.vishay.com/docs/20035/dcrcwe3.pdf` | 200 application/pdf, 150 402 B, `%PDF-1.4` | `vishay_dcrcwe3.pdf` (sha256 04331e24…) |
| `https://content.kemet.com/datasheets/KEM_C1002_X7R_SMD.pdf` | 200 application/pdf, 3 316 643 B, `%PDF-1.7` | `kemet_C1002_X7R_SMD.pdf` (sha256 d8e6ca66…) |
| `https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf` | 200 application/pdf, 716 143 B, `%PDF-1.6` | `bourns_SRR1260.pdf` (sha256 63df6a6f…) |
| `https://www.yageo.com/upload/media/product/productsearch/datasheet/rchip/PYu-RC_Group_51_RoHS_L_12.pdf` | redirected to yageogroup.com, **404 HTML** (also `_L_11/13/14/15`) | deleted, not used |

Murata GRM / Samsung CL / Würth WE-PD were not attempted because KEMET (MLCC) and Bourns (power inductor) succeeded on first try.

---

## 3. Page map per PDF (ground truth, 1-based PDF page index) – VERIFIED

| File | Ordering / MPN decoding | Pinout / pin table | Package outline | Land pattern | Abs. max. |
|---|---|---|---|---|---|
| opa656 | 2 (Package/Ordering table), 17–18 (Package Option Addendum), 19–20 (tape&reel) | 2 | 21 (DBV SOT-23-5), 23 (D SOIC-8) | 22 (DBV), 24 (D) | 2 |
| LTC6244 | 2 (Order Information) | 2 (drawings only) | 23 (DD), 24 (MS8) | 23 (DD), 24 (MS8) | 2 |
| 6N137 | 10 (option suffixes, marking) | 1 ("Schematics") | 9 (THT 0.3", 0.4", SMD) | 9 ("8-Pin DIP – Land Pattern") | 2 |
| 25AA02E48 | 1 (Device Selection Table), 23 (Product Identification System) | 1, 14 (Table 4-1) | 16 (SN), 18 (OT) | 17 (SN), 19 (OT) | 2 |
| AD7983 | 24 (Ordering Guide) | 7 (Table 6) | 24 (RM-10, CP-10-9) | **none** (p23 = example PCB layout photo) | 6 |
| sn65lv1023a | 22–23 (addendum), 24–25 (tape&reel) | 1 (SER drawings), 6 (PIN FUNCTIONS, SER+DES) | 26 (RHB), 27 (RHB thermal pad), 29 (DB family) | 28 (RHB only) | 7 |
| ADG736 | 12 | 6 | 12 (RM-10) | none | 5 |
| AD5235 | 30 | 9 | 30 (RU-16) | none | 8 |
| vishay_dcrcwe3 | 3 (Part Number and Product Description, packaging codes) | – | 11 | 11 (Recommended Solder Pad Dimensions) | – (ratings p1–2) |
| kemet_C1002_X7R_SMD | 2 (Ordering Information + C-Spec table) | – | 3 (+ thickness codes p9–10) | 12 (Table 3, IPC-7351 A/B/C) | – (ratings p1, availability p4–8) |
| bourns_SRR1260 | 1 (Electrical Specifications = part list; no legend) | – | 1 | 2 (Recommended Layout) | – (ratings p1) |

### 3.1 How well does a keyword page classifier work? (VERIFIED, `analyze.py` vs. table above)

| Section | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| ordering | 12 | 8 | 3 | 0.60 | 0.80 |
| pinout | 9 | 5 | 1 | 0.64 | 0.90 |
| package_outline | 10 | 27 | 6 | 0.27 | 0.62 |
| land_pattern | 6 | 4 | 5 | 0.60 | 0.55 |
| abs_max | 8 | 6 | 0 | 0.57 | 1.00 |

Causes: ADI tables of contents (p2–3) mention every section; TI mechanical pages have no text; Microchip package pages are glyph-encoded; "Dimensions" occurs everywhere in KEMET; Vishay says "PART NUMBER AND PRODUCT DESCRIPTION"; Bourns has no heading at all. Conclusion: text keywords alone are not a reliable page selector; page images (vision) are needed for outline/land-pattern pages.

---

## 4. Extraction pitfalls found in this corpus (all VERIFIED)

1. **Vector-only mechanical pages** – `opa656.pdf` p21–24 and `sn65lv1023a.pdf` p26–28: 0 extractable chars, 0 images. All package and land-pattern numbers exist only as drawn outlines. Only vision can read them.
2. **Glyph-ID encoded text** – `25AA02E48.pdf` p16–19: pdfplumber returns `(cid:2)(cid:3)…`, pypdf returns `/g27/g16/g47…`. Decoding `chr(N + 29)` restores readable text for this file, e.g. p16 becomes `8-Lead Plastic Small Outline (SN) Î Narrow, 3.90 mm Body [SOIC]` … `Pitch e 1.27 BSC` … `Lead Width b 0.31 Î 0.51` (`Î` = en dash, `f`/`a`/`b` = φ/α/β). Tested only on this file; whether the +29 offset generalises is UNVERIFIED. Working snippet:
   ```python
   dec = re.sub(r'/g(\d+)', lambda m: chr(int(m.group(1)) + 29), pypdf_page_text)
   ```
3. **pdfplumber merges words** on TI/SPDF files with the default `x_tolerance=3`: `Analogcircuitground(PLLandanalogcircuits)`. `page.extract_text(x_tolerance=1.5)` gives `Analog circuit ground (PLL and analog circuits)`. pypdf keeps the spaces.
4. **Hidden / off-page text** – `bourns_SRR1260.pdf` p1 contains the recommended-layout labels `2.9`, `5.4`, `6.8` at y = 803–868 pt on a 792 pt page (invisible). p2 contains product-dimension labels at y = −41…150 pt (clipped). Filter chars by the page bbox, and preferably by the clip path, before giving text to an LLM.
5. **Symbol-font Ω** – Bourns RDC header extracts as `RDC Max. (mW)` but the page shows `(mΩ)`.
6. **Superscript footnotes glued to values** – KEMET p3 size codes extract as `10402`, `20603`, `30805`, `41206`, `51210` (rendered as `¹0402`, `²0603`, …). In the KEMET matrix the superscript is U+00B9 at body font size, e.g. `DH¹`.
7. **Sparse matrix tables** – KEMET p4–8: row text such as `0.27 µF 274 J K M CF CF CF DP DP DP DP DP DP DG EB …` has lost the column positions. Assigning each character to the nearest "Voltage Code" header column by x-coordinate solves this (`kemet_matrix.py`); results agree with every cell I checked against the page renders.
8. **Merged cells** – Vishay p1 "Resistance range" spans 0402–1210 / 1218 / 2010–2512. The text layer flattens these into three strings.
9. **Overbars lost** – active-low names (25AA02E48 CS/WP/HOLD, AD5235 CS/PR/WP, SN65LV1023A PWRDN, TCLK_R/F̄, SN65LV1224B LOCK/PWRDN) have no marker in the text layer. They are only visible in the drawings.
10. **Document-internal conflicts** – OPA656 p2 "OPA656U … Rails, 100" vs. addendum p17 package qty 75. 25AA02E48 SOT-23 pin 6 is labelled `VDD` in the p1 drawing but `VCC` in Table 4-1. TI addendum contains the typo `SNLV1023ARHBTG4` (confirmed on the rendered page).
11. **Metadata is unreliable** – ADG736 PDF subject says "CMOS Low Voltage 25 Ohm Dual SPDT Switch"; the page title says "2.5 Ω".
12. **Same package code, different dimensions** – ADI RM-10 in AD7983 (2010) vs. ADG736 (2012): b 0.17–0.33 vs 0.15–0.30; c 0.08–0.23 vs 0.13–0.23; L nom 0.60 vs 0.55; θ 0–8° vs 0–6°. Dimensions must come from the actual datasheet, not from a package-code lookup alone.
13. **Land-pattern dimension semantics differ by vendor** – TI uses pad-centre-to-pad-centre row spacing (4.80 / 2.7). LTC uses outer/inner span (3.5 / 2.10). Microchip uses `C` = centre spacing plus `G`, `Z`. KEMET's `C` is component centre to pad centre (half pitch; checked against the p12 drawing: 0603 level B C = 0.80 with pad length Y = 0.95, so C cannot be the full pitch). Vishay uses `G` (gap), `Y` (pad length), `X` (pad width), `Z` (outer); `Z = G + 2Y` holds for every row.
14. **Encrypted PDF** – `25AA02E48.pdf` reports `is_encrypted=True` but opens with `decrypt('')`. Text extraction works.

---

## 5. Ground truth – ICs (full data in `manifest.json` → `entries[i]`)

Electrical types use Altium's set (Input, IO, Output, OpenCollector, Passive, HiZ, OpenEmitter, Power). The mapping from datasheet wording to these types is DERIVED. AD7983's own Type column (AI/DI/DO/P) is VERIFIED and stored as `ds_type`. Dimensions are mm as min/nom/max. BSC = basic.

### 5.1 OPA656 (TI, SBOS196G) – single wideband FET-input op amp, −40…+85 °C
- MPNs (p2): `OPA656U`, `OPA656U/2K5`, `OPA656UB`, `OPA656UB/2K5` (SO-8, pkg D). `OPA656N/250`, `OPA656N/3K`, `OPA656NB/250`, `OPA656NB/3K` (SOT23-5, pkg DBV, marking `B56`). "UB and NB are high grade". Addendum adds G4 variants.
- Pins SO-8: 1 NC, 2 Inverting Input, 3 Noninverting Input, 4 −VS, 5 NC, 6 Output, 7 +VS, 8 NC.
- Pins SOT23-5: 1 Output, 2 −VS, 3 Noninverting Input, 4 Inverting Input, 5 +VS.
- SOIC-8 D (4040047-3/M, MS-012 AA, p23): D 4.80–5.00, E1 3.80–4.00, E 5.80–6.20, e 1.27, b 0.31–0.51, c 0.13–0.25, A ≤ 1.75, A1 0.10–0.25, L 0.40–1.27, 0–8°, coplanarity 0.10.
- SOIC-8 land pattern (4211283-2/D, p24): pads 0.60 × 2.00, pitch 1.27, row centre distance **4.80**, mask 0.07 all around, stencil 0.55 × 1.95.
- SOT-23-5 DBV (4073253-4/K, MO-178 AA, p21): D 2.75–3.05, E1 1.45–1.75, E 2.60–3.00, e 0.95, b 0.30–0.50, c 0.08–0.22, A ≤ 1.45, A1 0–0.15, L 0.30–0.55, 0–8°.
- SOT-23-5 land pattern (4209593-3/C, p22): pads 0.6 × 1.05, pitch 0.95, pins 4–5 at 1.90, row centre distance **2.7**, mask 0.07, stencil 0.55 × 1.00 (0.127 mm stencil).
- Abs. max (p2): supply ±6.5 V; differential and input voltage ±VS; storage −65…+125 °C; lead 260 °C; TJ 150 °C; ESD 2000 V HBM / 200 V MM.

### 5.2 LTC6244 (Linear, 6244fb) – dual 50 MHz CMOS rail-to-rail op amp
- 22 MPNs (p2). Pattern `LTC6244[HV]{C|I|H}{DD|MS8}#{PBF|TRPBF}`, except that **no HV + H-grade MS8** is listed. Markings: DD `LCCF` (std) and `LCGD` (HV); MS8 `LTCCM` (std) and `LTCGF` (HV). Temperature: C 0…70 °C, I −40…85 °C, H −40…125 °C.
- Pins (MS8 and DD): 1 OUT A, 2 −IN A, 3 +IN A, 4 V−, 5 +IN B, 6 −IN B, 7 OUT B, 8 V+. DD also has **9 = exposed pad, connected to V− (PCB connection optional)**.
- DD DFN-8 3×3 (05-08-1698 Rev C, p23): body 3.00 ± 0.10, A 0.75 ± 0.05, A1 0–0.05, e 0.50, b 0.25 ± 0.05, L 0.40 ± 0.10, EP 2.38 ± 0.10 × 1.65 ± 0.10.
- DD recommended pads: 0.25 ± 0.05 × 0.70 ± 0.05, pitch 0.50, outer span 3.5 ± 0.05, inner span 2.10 ± 0.05, so the row centre distance is 2.80 (DERIVED). Thermal pad 2.38 ± 0.05 × 1.65 ± 0.05.
- MS8 (05-08-1660 Rev F, p24): D = E1 3.00 ± 0.102, E 4.90 ± 0.152, e 0.65, b 0.22–0.38, A ≤ 1.10, A1 0.1016 ± 0.0508, L 0.53 ± 0.152, 0–6°.
- MS8 recommended pads: 0.42 ± 0.038 × 0.889 ± 0.127, pitch 0.65, outer span ≥ 5.23, inner span 3.20–3.45, so the row centre distance is about 4.34 (DERIVED).
- Abs. max: V+ to V− 7 V (HV: 12 V); input current ±10 mA; TJ 150 °C; storage −65…150 °C; lead 300 °C. θJA: DD 43 °C/W, MS8 250 °C/W.

### 5.3 6N137 / HCPL2601 / HCPL2611 / HCPL2630 / HCPL2631 (Fairchild, Rev 1.0.8)
- Option suffixes (p10, shown as examples for 6N137 only): none, `S` (SMD lead bend), `SD` (SMD, T&R), `W` (0.4" spacing), `V` (VDE0884), `WV`, `SV`, `SDV`. Applying them to the HCPL parts is DERIVED.
- Single-channel pins (6N137, HCPL2601, HCPL2611): 1 N/C, 2 VF+ (anode), 3 VF− (cathode), 4 N/C, 5 GND, 6 VO (open collector), 7 VE (enable), 8 VCC. A 0.1 µF bypass between pins 8 and 5 is required.
- Dual-channel pins (HCPL2630, HCPL2631): 1 VF1+, 2 VF1−, 3 VF2−, 4 VF2+, 5 GND, 6 VO2, 7 VO1, 8 VCC.
- DIP-8 THT (p9, inch(mm)): body 9.40–9.91 × 6.35–6.86, seating plane to top 3.55–5.08, standoff ≥ 0.51, lead below seating plane 3.05–3.90, b 0.41–0.56, b2 1.14–1.78, e 2.54, row spacing 7.62 TYP, 15° max.
- W option: row spacing 10.16 TYP, standoff ≥ 0.10.
- SMD (S option): lead span ≤ 10.30, inner span ≥ 8.00, foot 1.14, coplanarity 0.10.
- SMD land pattern: pads 1.78 (along the row) × 1.52, pitch 2.54, gap 0.76, outer 10.54, inner 7.49, so the row centre distance is 9.015 (DERIVED).
- Abs. max (p2): IF 50 mA (dual 30 mA/ch); VR 5.0 V; VCC 7.0 V (1 min); VO 7.0 V; IO 50 mA; VE 5.5 V; TSTG −55…+125 °C; TOPR −40…+85 °C; wave solder 260 °C 10 s.

### 5.4 25AA02E48 (Microchip, DS22123B) – 2 Kbit SPI EEPROM with EUI-48
- MPN system (p23): `25AA02E48[T]-I/{SN|OT}`. T = tape & reel; I = −40…+85 °C; SN = 8-lead SOIC 3.90 mm; OT = 6-lead SOT-23, which is tape & reel only.
- Listed MPNs: `25AA02E48-I/SN`, `25AA02E48T-I/SN`, `25AA02E48T-I/OT`.
- Pins SOIC: 1 CS̄, 2 SO, 3 WP̄, 4 VSS, 5 SI, 6 SCK, 7 HOLD̄, 8 VCC.
- Pins SOT-23-6: 1 SCK, 2 VSS, 3 SI, 4 SO, 5 CS̄, 6 VCC (drawn as `VDD` on p1).
- SOIC SN (C04-057B, p16): e 1.27 BSC, A ≤ 1.75, A2 ≥ 1.25, A1 0.10–0.25, E 6.00 BSC, E1 3.90 BSC, D 4.90 BSC, h 0.25–0.50, L 0.40–1.27, L1 1.04 REF, φ 0–8°, c 0.17–0.25, b 0.31–0.51, α/β 5–15°.
- SOIC land pattern (C04-2057A, p17): E 1.27, C 5.40 (centre to centre), X1 ≤ 0.60, Y1 ≤ 1.55.
- SOT-23-6 OT (C04-028B, p18): e 0.95, e1 1.90, A 0.90–1.45, A2 0.89–1.30, A1 0–0.15, E 2.20–3.20, E1 1.30–1.80, D 2.70–3.10, L 0.10–0.60, L1 0.35–0.80, φ 0–30°, c 0.08–0.26, b 0.20–0.51.
- SOT-23-6 land pattern (C04-2028A, p19): E 0.95, C 2.80, X ≤ 0.60, Y ≤ 1.10, G ≥ 1.70, GX ≥ 0.35, Z ≤ 3.90.
- Abs. max (p2): VCC 6.5 V; I/O −0.6 V…VCC + 1.0 V; storage −65…150 °C; ambient under bias −40…85 °C; ESD 4 kV.

### 5.5 AD7983 (ADI, Rev A) – 16-bit 1.33 MSPS SAR ADC, branding C5Y
- MPNs: `AD7983BRMZ` (tube 50), `AD7983BRMZRL7` (reel 1000), `AD7983BCPZ-R2` (reel 250), `AD7983BCPZ-RL` (reel **1000** as printed), `AD7983BCPZ-RL7` (reel **5000** as printed).
- Pins (both packages, Type column): 1 REF AI, 2 VDD P, 3 IN+ AI, 4 IN− AI, 5 GND P, 6 CNV DI, 7 SDO DO, 8 SCK DI, 9 SDI DI, 10 VIO P. On the QFN the paddle is connected to GND (connection optional) and has no pin number.
- RM-10 MSOP (MO-187-BA): D = E1 2.90/3.00/3.10, E 4.65/4.90/5.15, e 0.50, A ≤ 1.10, A2 0.75/0.85/0.95, A1 0.05–0.15, b 0.17–0.33, c 0.08–0.23, L 0.40/0.60/0.80, 0–8°.
- CP-10-9 LFCSP_WD 3×3: 3.00 BSC sq, A 0.70/0.75/0.80, A1 0.02 nom / 0.05 max, A3 0.20 REF, b 0.18/0.23/0.30, e 0.50, L 0.30/0.40/0.50, EP 2.23/2.38/2.48 × 1.49/1.64/1.74.
- No land pattern in this datasheet.
- Abs. max (p6): REF and VIO to GND −0.3…+6 V; VDD to GND −0.3…+3 V; analog inputs −0.3 V…VREF + 0.3 V or ±130 mA; digital I/O −0.3 V…VIO + 0.3 V; TJ 150 °C; storage −65…150 °C.

### 5.6 SN65LV1023A serializer (+ SN65LV1224B deserializer) (TI, SLLS621E)
- SER MPNs: `SN65LV1023ADB`/`DBG4` (50), `SN65LV1023ADBR`/`DBRG4` (2000), `SN65LV1023ARHBR`/`RHBRG4` (3000), `SN65LV1023ARHBT` (250), and `SNLV1023ARHBTG4` (sic, 250).
- DES MPNs: `SN65LV1224BDB`, `DBG4`, `DBR`, `DBRG4`, `RHBR`, `RHBRG4`, `RHBT`, `RHBTG4`.
- SER DB (SSOP-28): 1 SYNC1, 2 SYNC2, 3–12 DIN0–DIN9, 13 TCLK_R/F̄, 14 TCLK, 15–16 DGND, 17 AVCC, 18 AGND, 19 DEN, 20 AGND, 21 DO−, 22 DO+, 23 AGND, 24 PWRDN̄, 25 AGND, 26 AVCC, 27–28 DVCC.
- SER RHB (VQFN-32): 1–9 DIN1–DIN9, 10 TCLK_R/F̄, 11 TCLK, 12–15 DGND, 16 AVCC, 17 AGND, 18 DEN, 19 AGND, 20 DO−, 21 DO+, 22 AGND, 23 PWRDN̄, 24 AGND, 25 AVCC, 26–29 DVCC, 30 SYNC1, 31 SYNC2, 32 DIN0, plus an exposed thermal pad with no number or net given ("must be soldered").
- DES pin tables are built from the PIN FUNCTIONS table (p6). The ROUT0–9 order is inferred from "28−24, 19−15" and "27−23, 18−14" (UNVERIFIED, no drawing).
- DB SSOP (4040065/E, MO-150, p29, 28-pin row): D 9.90–10.50, E1 5.00–5.60, E 7.40–8.20, e 0.65, b 0.22–0.38, A ≤ 2.00, A1 ≥ 0.05, c 0.09–0.25, L 0.55–0.95, 0–8°. No land pattern for DB.
- RHB VQFN (4204326/C, MO-220, p26): body 4.85–5.15, A 0.80–1.00, A1 0–0.05, A3 0.20 REF, e 0.50, b 0.18–0.30, L 0.30–0.50, coplanarity 0.08. EP 3.45 ± 0.10 (p27).
- RHB land pattern (4207808-2/I, p28): pads 0.28 × 0.85 (R0.14), pitch 0.5, outer span 5.8, inner span 4.1, so the row centre distance is 4.95 (DERIVED). The first pad centre is 0.25 from the centre line. Thermal pad 3.45 × 3.45, mask 0.07, mask web 0.08.
- RHB stencil (0.125 mm): 0.23 × 0.8, spans 4.15/5.75, thermal pad printed as 4 × 1.45 × 1.45 with 0.3 web (71 %). Example vias: 9 × Ø0.3 on a 1.0 mm grid.
- Abs. max (p7): VCC −0.3…4 V; LVDS I/O −0.3…3.9 V; HBM 6 kV; MM 200 V; TJ 150 °C; storage −65…150 °C. Dissipation DB 1.27 W, RHB 2.85 W at 25 °C.

### 5.7 ADG736 (ADI, Rev D) – dual SPDT switch, −40…+125 °C
- MPNs: `ADG736BRM`, `-REEL`, `-REEL7`, `ADG736BRMZ`, `-REEL`, `-REEL7`, `ADW54010Z-0REEL` (automotive). Branding SAB / SAB#.
- Pins: 1 IN1, 2 S1A, 3 GND, 4 S2A, 5 IN2, 6 D2, 7 S2B, 8 VDD, 9 S1B, 10 D1. Logic 0 = switch A off / B on.
- RM-10 (091709-A, MO-187-BA): D = E1 2.90/3.00/3.10, E 4.65/4.90/5.15, e 0.50, A ≤ 1.10, A2 0.75/0.85/0.95, A1 0.05–0.15, b 0.15–0.30, c 0.13–0.23, L 0.40/0.55/0.70, 0–6°, 15° max draft.
- Abs. max (p5): VDD −0.3…+6 V; inputs −0.3 V…VDD + 0.3 V or 30 mA; continuous S/D current 30 mA; peak 100 mA; θJA 205 °C/W; ESD 2 kV.

### 5.8 AD5235 (ADI, Rev F) – dual 1024-position NV digital potentiometer, −40…+85 °C
- MPNs: `AD5235BRUZ25` (25 kΩ, 96), `AD5235BRUZ25-RL7` (1,000), `AD5235BRUZ250` (250 kΩ, 96), `AD5235BRUZ250-R7` (1,000). Branding 5235B25 / 5235B250.
- Pins: 1 CLK, 2 SDI, 3 SDO (needs pull-up, mapped to OpenCollector), 4 GND, 5 VSS, 6 A1, 7 W1, 8 B1, 9 B2, 10 W2, 11 A2, 12 VDD, 13 WP̄, 14 PR̄, 15 CS̄, 16 RDY (open-drain output).
- RU-16 TSSOP (MO-153-AB): D 4.90/5.00/5.10, E1 4.30/4.40/4.50, E 6.40 BSC, e 0.65, b 0.19–0.30, A ≤ 1.20, A1 0.05–0.15, c 0.09–0.20, L 0.45/0.60/0.75, 0–8°.
- Abs. max (p8): VDD −0.3…+7 V; VSS +0.3…−7 V; VDD − VSS 7 V; terminal current ±20 mA pulsed / ±2 mA continuous; θJA 150 °C/W.

---

## 6. Ground truth – passive series

### 6.1 Vishay D/CRCW e3 thick-film chip resistors (`vishay_dcrcwe3.pdf`)
- **Global part number** (p3, VERIFIED): `CRCW` + size(4) + resistance(4) + tolerance(1) + TCR(1) + packaging(2).
  - Datasheet examples: `CRCW0603562RFKEA` and jumper `CRCW06030000Z0EA`.
  - Resistance: `R` = decimal, `K` = thousand, `M` = million; `0000` = jumper.
  - Tolerance: `F` ±1 %, `J` ±5 %, `Z` jumper. TCR: `K` ±100 ppm/K, `N` ±200 ppm/K, `0` jumper.
  - Packaging: `EA, EC, ED, EE, EF, EG, EH, EI, EK`.
  - Product description format: `D11/CRCW0603 100 562R 1 % ET1 e3`.
- **Values (p2):**
  - ±200 ppm/K, ±5 %: 1 Ω–10 MΩ, E24.
  - ±200 ppm/K, ±1 %: 1 Ω–9.76 Ω, E24 + E96.
  - ±100 ppm/K, ±1 %: 1 Ω–10 MΩ, E24 + E96.
  - 1218 tops out at 2.2 MΩ.
  - Jumper ≤ 20 mΩ, Imax 1.5 / 2.0 / 2.5 / 3.5 / 5.0 / 7.0 / 6.0 / 7.0 A (0402…2512).
- **Value counts (DERIVED from IEC E24/E96 tables):**
  - E24 1 Ω…10 MΩ = **169** values. E24 ∪ E96 1 Ω…10 MΩ = **799**.
  - For 1218 (to 2.2 MΩ): 153 and 721.

| Size | Metric | P70 (W) | Umax (V) | Uins (V) | L × W × H (mm) | Reflow pads G / Y / X / Z (mm) | Packaging |
|---|---|---|---|---|---|---|---|
| 0402 | RR1005M | 0.10 (std 0.063) | 75 (std 50) | 100 | 1.0±0.05 × 0.5±0.05 × 0.35±0.05 | 0.45 / 0.6 / 0.6 / 1.65 (no wave) | ED=ET7 10k, EE=EF4 50k |
| 0603 | RR1608M | 0.125 (std 0.10) | 75 | 100 | 1.55+0.10/−0.05 × 0.85±0.10 × 0.45±0.05 | 0.75 / 0.75 / 1.00 / 2.25 | EI 5k, ED 10k, EE 50k (2 mm); EA 5k, EC 20k (4 mm) |
| 0805 | RR2012M | 0.25 (std 0.125) | 150 | 200 | 2.0+0.20/−0.10 × 1.25±0.15 × 0.5±0.10 | 1.00 / 0.95 / 1.45 / 2.90 | EA 5k, EC 20k |
| 1206 | RR3216M | 0.25 | 200 | 300 | 3.2+0.10/−0.20 × 1.6±0.15 × 0.55±0.05 | 1.50 / 1.05 / 1.80 / 3.60 | EA 5k, EC 20k |
| 1210 | RR3225M | 0.5 | 200 | 300 | 3.2±0.20 × 2.5±0.20 × 0.55±0.05 | 1.70 / 1.10 / 2.80 / 3.90 | EA 5k, EC 20k |
| 1218 | RR3246M | 1.0 | 200 | 300 | 3.2+0.10/−0.20 × 4.6±0.15 × 0.55±0.05 | 1.90 / 1.10 / 4.90 / 4.10 | EK=ET9 4k |
| 2010 | RR5025M | 0.75 | 400 | 300 | 5.0±0.15 × 2.5±0.15 × 0.6±0.10 | 3.50 / 1.45 / 2.80 / 6.40 | EF=E02 4k |
| 2512 | RR6332M | 1.0 | 500 | 300 | 6.3±0.20 × 3.15±0.15 × 0.6±0.10 | 4.75 / 1.45 / 3.50 / 7.65 | EG=E67 2k, EH=E82 4k |

Operating temperature −55…+155 °C. Wave-solder pads are in the manifest too. Pad centre distance = G + Y (DERIVED), e.g. 0603 reflow 1.50 mm.

### 6.2 KEMET X7R commercial MLCC (`kemet_C1002_X7R_SMD.pdf`)
- **MPN** (p2, VERIFIED): `C` + case(4) + `C`(Standard) + cap code(3, pF, 2 digits + zeros) + tolerance(`J` ±5 %, `K` ±10 %, `M` ±20 %) + voltage + `R`(X7R) + `A` + `C`(100 % matte Sn) + C-Spec.
  - Voltage codes: `9` 6.3, `8` 10, `4` 16, `3` 25, `6` 35, `5` 50, `1` 100, `2` 200, `A` 250.
  - C-Spec: blank = bulk bag; `TU` = 7" reel unmarked; `7411` = 13" unmarked (≤ 0603); `7210` = 13" unmarked (≥ 0805); `TM` = 7" marked; `7040` = 13" marked (0603); `7215` = 13" marked (≥ 0805).
  - Datasheet example: `C1206C106M4RACTU`.
  - Cases: 0402, 0603, 0805, 1206, 1210, 1805, 1808, 1812, 1825, 2220, 2225.
- **Availability** (Tables 1A–1C, p4–8): extracted cell by cell into `groundtruth/kemet_C1002_X7R_series.json` → `availability[]` (3342 entries; each has case, rated voltage, cap code, pF, thickness code, allowed tolerances).
  - `¹` cells (35) = "available only in K and M tolerance".
  - Range rows expanded: `*` = E24 decade values, `**` = E12 decade values.
  - Spot-checked against renders: rows 104, 105, 106, 224, 225, 226, 475, 476, top rows of p4, all of p7 and p8.
  - Summary (min–max, count of values):

| Case | 6.3 V | 10 V | 16 V | 25 V | 35 V | 50 V | 100 V | 200 V | 250 V |
|---|---|---|---|---|---|---|---|---|---|
| 0402 | 10 pF–470 nF (63) | 10 pF–470 nF (63) | 10 pF–220 nF (62) | 10 pF–220 nF (59) | – | 10 pF–22 nF (53) | 1 nF–10 nF (10) | 1 nF–1.5 nF (3) | 1 nF–1.5 nF (3) |
| 0603 | 10 pF–4.7 µF (72) | 10 pF–2.2 µF (71) | 10 pF–1 µF (70) | 10 pF–1 µF (67) | – | 10 pF–220 nF (64) | 10 pF–100 nF (61) | 10 pF–10 nF (49) | 1 nF–10 nF (13) |
| 0805 | 10 pF–10 µF (79) | 10 pF–10 µF (79) | 10 pF–4.7 µF (78) | 10 pF–4.7 µF (75) | 10 pF–2.2 µF (73) | 10 pF–2.2 µF (73) | 10 pF–270 nF (66) | 10 pF–68 nF (59) | 180 pF–68 nF (32) |
| 1206 | 10 pF–22 µF (86) | 10 pF–22 µF (86) | 10 pF–10 µF (85) | 10 pF–10 µF (82) | 10 pF–4.7 µF (78) | 10 pF–4.7 µF (78) | 10 pF–1 µF (73) | 10 pF–220 nF (65) | 1 nF–220 nF (29) |
| 1210 | 10 pF–47 µF (87) | 10 pF–47 µF (87) | 10 pF–22 µF (85) | 10 pF–22 µF (85) | – | 10 pF–10 µF (81) | 10 pF–2.2 µF (76) | 10 pF–470 nF (68) | 2.2 nF–470 nF (29) |
| 1805 | – | – | – | – | – | 220 pF–100 nF (33) | 220 pF–27 nF (26) | 220 pF–5.6 nF (14) | – |
| 1808 | – | – | – | – | – | 330 pF–180 nF (34) | 330 pF–56 nF (28) | 330 pF–18 nF (20) | – |
| 1812 | – | – | – | 470 pF–10 µF (50) | – | 470 pF–4.7 µF (49) | 470 pF–3.3 µF (47) | 470 pF–470 nF (37) | 6.8 nF–470 nF (23) |
| 1825 | – | – | – | – | – | 3.9 nF–2.2 µF (34) | 3.9 nF–1 µF (30) | 3.9 nF–1 µF (28) | 22 nF–1 µF (21) |
| 2220 | – | – | – | 6.8 nF–22 µF (35) | – | 6.8 nF–15 µF (34) | 6.8 nF–1 µF (27) | 82 nF–1 µF (14) | 82 nF–1 µF (14) |
| 2225 | – | – | – | – | – | 4.7 nF–2.2 µF (28) | 4.7 nF–1.2 µF (24) | 4.7 nF–1.2 µF (21) | 100 nF–1.2 µF (14) |

- **Values are not a contiguous E-series.** Some ranges have gaps, e.g. 0402 at 100 V: 1.0–1.5 nF, then 3.3–10 nF.
- **Thickness codes** (Table 2A, p9–10): 70 codes, e.g. `BB` 0402 0.50±0.05; `CF` 0603 0.80±0.07; `DN` 0805 0.78±0.10; `EH` 1206 1.60±0.20; `FS` 1210 2.50±0.30. Each code has its own reel quantities (paper/plastic, 7"/13").
- **Dimensions** (p3): L/W/B/S per case. For example 0603: L 1.60±0.15, W 0.80±0.15, B 0.35±0.15, S ≥ 0.50. Footnotes add tolerance for specific values.
- **Land patterns** (Table 3, p12, IPC-7351 density A/B/C): C = centre to pad centre, Y = pad length, X = pad width, V1 × V2 = courtyard. For example 0603 level B: C 0.80, Y 0.95, X 1.00, V1 3.10, V2 1.50. A separate `1210 (≥ 22 µF)` row exists.
- **Decode test vectors** (DERIVED from rules + matrix, asserted in `mpn_decoders.py`):

| MPN | Result |
|---|---|
| `C1206C106M4RACTU` | EH, orderable |
| `C0603C104K5RACTU` | CJ, orderable |
| `C0402C104K3RACTU` | BB¹, K/M only, orderable |
| `C0805C106J8RACTU` | **not orderable** (J not allowed) |
| `C1210C476M8RACTU` | FS¹, orderable |
| `C0402C105K8RACTU` | **not in table** |

### 6.3 Bourns SRR1260 shielded SMD power inductors (`bourns_SRR1260.pdf`)
- **38 parts** (p1), from `SRR1260-1R0Y` to `SRR1260-102K`. Each has L (µH), tol, Q, test freq, SRF, RDC max (mΩ), Irms, Isat, K-factor. All rows match the text layer.
  - First: `SRR1260-1R0Y` 1.0 µH ±30 %, RDC 7.8 mΩ, Irms 9.40 A, Isat 10.00 A.
  - Last: `SRR1260-102K` 1000 µH ±10 %, 1700 mΩ, 0.68 A, 0.60 A.
- **MPN rule** (DERIVED, holds for all 38): `SRR1260-` + L code (`R` = decimal point, else 2 digits + zeros, in µH) + tolerance letter (`Y` ±30 %, `M` ±20 %, `K` ±10 %). The datasheet has no legend.
  - The series is called "E12" but contains the non-E12 values 2.4, 3.5, 6.1 and 7.6 µH.
- **Body:** 12.5 ± 0.3 × 12.5 ± 0.3 × 6.0 ± 0.5. Bottom terminals 5.0 ± 0.3 wide, 7.0 TYP inner gap.
- **Recommended layout** (p2): 2 pads 2.9 REF × 5.4 REF, gap 6.8 REF, so the pad centre distance is 9.7 and the outer extent 12.6 (DERIVED).
- **Other:** −40…+125 °C; 600 pcs/reel; 2 pins, non-polar.

---

## 7. `manifest.json` schema (VERIFIED by loading it)

```text
{ "schema": "partforge-datasheet-corpus/1", "status_legend": {...}, "conventions": {...},
  "entries": [ {
     "file": "pdfs/opa656.pdf", "sha256": "...", "bytes": 853689, "origin": "...", "kind": "ic" | "passive_series",
     "pages": 25, "encrypted": false, "text_extractable": true, "pages_without_text_layer": [21,22,23,24],
     "manufacturer": "...", "document": {"id","title","revision"},
     "sections": {"ordering":[...], "pinout":[...], "package_outline":[...], "land_pattern":[...], "abs_max":[...], ...},
     "extraction_notes": [...],
     "devices": [ {"base_part", "description", "category", "mpns": [ {"mpn","package",...} | "MPN" ],
                   "pin_tables": { "<package key>": [ {"number":"1","name":"CS","function":"...","electrical_type":"Input",
                                                       "active_low":true, "exposed_pad":true, "ds_type":"AI"} ] } } ],
     "packages": { "<package key>": {"drawing","jedec","pins","page",
                   "dims_mm": {"D_body_length": {"min":4.8,"nom":null,"max":5.0,"basic"?,"ref"?,"note"?}, ...},
                   "land_pattern": {...vendor-specific keys, *_DERIVED for computed values...} } },
     "abs_max": [ {"parameter": "...", "value": "..."} ],
     "series": { ... passive-series data (mpn_scheme, ranges, dims, pads, parts) ... }
  } ] }
```

Package keys that the pin tables refer to: `SOIC-8`, `SOT-23-5`, `SOT-23-6`, `DFN-8 3x3 (DD)`, `MSOP-8 (MS8)`, `MSOP-10 (RM-10)`, `LFCSP_WD-10 3x3 (CP-10-9)`, `SSOP-28 (DB)`, `VQFN-32 5x5 (RHB)`, `TSSOP-16 (RU-16)`, and `DIP-8 / SMD-8 (all options)` for 6N137. For 6N137, `package_by_option` maps each order suffix to its package.

Suggested assertions for import tests:
- MPN set equality per device.
- Pin count, plus pin number→name equality after normalising (case, `−`/`-`, overbar).
- Pin electrical type equality (loose, because the mapping is DERIVED).
- Dimensions within ±0.005 mm of the ground truth.
- Land-pattern pad size and pitch equality.
- Passives: MPN round-trips through decode→encode, and per-case/voltage availability equality against the KEMET groundtruth file.

---

## 8. Recommendations for PartForge (derived from the findings, not tested in PartForge itself)
1. Use **both** text and page images for datasheet extraction. Render candidate pages with pypdfium2 (BSD/Apache, no external binary; VERIFIED working here). 130–150 dpi full pages were readable; I used 200–400 dpi crops to confirm small dimension labels.
2. Pre-filter text before LLM use:
   - drop chars outside the page bbox;
   - use `x_tolerance=1.5` with pdfplumber, or prefer pypdf text;
   - detect `(cid:N)` and `/gNN` garbage and switch that page to vision only (or try the +29 decode).
3. Do not rely on a keyword page classifier (precision 0.27 for outline pages). Let the LLM classify pages from thumbnails, or send all pages after the first 2–3 when the PDF is small.
4. Normalise land-pattern semantics per vendor (centre spacing vs. inner/outer span vs. half pitch) and store the derivation. Every land pattern in this corpus can be reduced to {pad W, pad L, pitch, row-centre distance, thermal pad}.
5. Ask the user to confirm conflicts. Multi-device and multi-package datasheets (6N137, SN65LV1023A/1224B, OPA656, LTC6244) need a device/package selection step before symbol and footprint generation.

---

## 9. Open questions / UNVERIFIED items
- Altium overbar notation for active-low pin names (`C\S\` style) is stored as `altium_name_UNVERIFIED`. It was not checked in Altium in this task.
- SN65LV1224B ROUT0–9 pin order is inferred from the range notation. The RHB thermal pad net for both devices is not stated.
- Whether the 6N137 option suffixes apply to HCPL2601/2611/2630/2631 (the datasheet shows only 6N137 examples).
- AD7983 `-RL` = 1000 and `-RL7` = 5000 reel quantities are as printed but contradict usual ADI practice.
- KEMET footnote ² ("M tolerance only") occurs in the legend, but no ² cell was found. Cells were verified by sampling (about 170 cells in 15 rows on p4, p5, p7 and p8, compared with page renders), not all 3342.
- Electrical-type mapping and IPC naming are DERIVED. No IPC-7351 footprint names are asserted.
