# IPC-7351B land patterns, footprints and simple 3D bodies: implementation reference for PartForge

Research date: 2026-10-07. Scope: SMD + THT families listed in the task. All dimensions in **mm**.
Work folder (scripts, downloaded sources): `.../scratchpad/research/ipc-work/`
(`scripts/ipc7351b_ref.py` = from-scratch reference implementation, `scripts/ipc_examples.py` = example generator, `examples.md` = its output).

## 0. Status legend and key findings

| Tag | Meaning |
|---|---|
| **V** | VERIFIED: read by me in a primary source (official IPC document/TOC, IPC-SM-782A text, JEDEC-conformant manufacturer drawing, manufacturer datasheet) or computed and cross-checked by me |
| **V\*** | VERIFIED against secondary sources only (IPC-7351B full text is paywalled): KiCad generator data (GPL), JITX `jitxlib-standard` (proprietary licence, values only), PCB Libraries forum posts by Tom Hausherr (IPC-7351 committee chair), SnapEDA blog |
| **U** | UNVERIFIED (memory, inference, single weak/search-summary source) |

Key findings (details below):

1. Equations **V**: `Zmax = Lmin + 2JT + sqrt(CL² + F² + P²)`, `Gmin = Smax − 2JH − sqrt(CS² + F² + P²)`, `Xmax = Wmin + 2JS + sqrt(CW² + F² + P²)` (IPC-SM-782A §3.3.3 text; IPC-7351B §3.1.5 per JITX/SnapEDA).
2. S tolerance is RMS-combined. **IPC-7351B**: `Stol_rms = sqrt(Ltol² + 2·Ttol²)`, `Smax_rms = Smax − (Stol − Stol_rms)/2`, and `CS = Stol_rms` (**V\***). The older IPC-SM-782A used `Smax_rms = Smin + Stol_rms` (**V**, worked example reproduced: Gmin = 2.25).
3. F and P are **not normative** in 7351B (**V\***). Use configurable defaults **F = 0.10, P = 0.05** (total values; = ±0.05/±0.025). This is what KiCad uses (**V**) and what Tom H quotes (**V\***). Other values exist:
   - IPC-SM-782A: F = P = 0.10 (**V**).
   - PCBL's Jeff.M says the IPC-7351 publication example uses F 0.10 / P 0.20 (**V\***).
4. My from-scratch implementation reproduces **13 published KiCad footprints exactly** (chips 0402–2512, tantalum A, SOIC-8, SOT-23, SOT-23-5, TSSOP-16, LQFP-48, QFN-16) (**V**, section 1.8).
5. J-tables (toe/heel/side/courtyard per M/N/L) for all needed lead families come from two independent transcriptions (KiCad + JITX) that agree (**V\***). Courtyard excess is 0.50/0.25/0.10 (M/N/L), BGA 2.0/1.0/0.5 (**V\***).
6. Round-off: KiCad rounds Z/G/X to the nearest 0.05 (0.02 for chips smaller than 0603) (**V**). PCB Libraries says IPC-7351B rounds to the nearest 0.01 (**V\***). Make it configurable. The courtyard round-off rule of 7351B is **U**. KLC puts the courtyard on a 0.01 grid (**V**).
7. Official IPC-7351B naming convention (2010 IPC/Mentor PDF) obtained and transcribed (**V**).
8. IPC-7352 (May 2023, "Generic Guideline for Land Pattern Design") is the current successor and also covers TH (**V**). IPC-7251 (TH) was never published (**V\***). Tom Hausherr says Altium's IPC wizard follows IPC-7351 (2005), not B (**V\***).

---

## 1. IPC-7351B mathematical model (code-ready)

### 1.1 Symbols and equations
- `L` = outer terminal span (toe-to-toe): `E`/`HE` lead span for gull wings, body length for chips and MELF, body size `D/E` for QFN.
- `T` = terminal or foot length in the span direction: chip band width `B`, gull-wing foot `L`/`Lp`, QFN terminal `L`.
- `W` = terminal width (`b`/`bp`, chip body width, or terminal width `F` for tantalum, or MELF diameter).
- `S` = inner span, heel-to-heel, `= L − 2T`.
- `C*` = tolerance (`max − min`) of L, S, W. `F` = PCB fabrication tolerance (total). `P` = placement tolerance (total).
- `JT/JH/JS` = toe/heel/side fillet goals from the J-tables (section 2). Their sign can be negative.

```
Zmax = Lmin + 2*JT + sqrt(CL**2 + F**2 + P**2)     # outer land extent
Gmin = Smax_rms - 2*JH - sqrt(CS**2 + F**2 + P**2) # inner gap between opposite lands
Xmax = Wmin + 2*JS + sqrt(CW**2 + F**2 + P**2)     # land width
```
Sources: IPC-SM-782A §3.3.3 (**V**, read in PDF); IPC-7351B §3.1.5 (**V\***: JITX `ipc.py` docstring quotes the equations; SnapEDA blog; KiCad `ipc_pad_size_calculators.py`).

### 1.2 RMS treatment of S (when S is derived from L and T)
```
Smin = Lmin - 2*Tmax ; Smax = Lmax - 2*Tmin ; Stol = Smax - Smin
Stol_rms = sqrt(Ltol**2 + 2*Ttol**2)
# IPC-7351B (default):
Smin_rms = Smin + (Stol - Stol_rms)/2
Smax_rms = Smax - (Stol - Stol_rms)/2
CS = Stol_rms
# IPC-SM-782A legacy variant (do NOT use for 7351B):  Smax_rms = Smin + Stol_rms
```
- 7351B variant: **V\***. Sources:
  - KiCad librarian John Beard, 2025-07-30: "IPC 7351B uses an RMS error propagation method… add/subtract half of that each to the worst-case min and max (caution: IPC 7351 not-B is different here)".
  - PCB Libraries forum TID 785 (read by me), with three statements:
    - User 2021: "Library Expert RMS Smax formula: New Smax = Smax - (Stol - Stol[RMS])/2".
    - Jeff.M (PCBL) 2021: "(Smin + Stol[RMS]) dates back to the IPC-SM-782 document from 1993. IPC revised this about 2005. Please refer to IPC-7351B section 3.1.1".
    - Jeff.M quoting IPC-7351B verbatim: "Smin = Lmin - 2Tmax = 5.8 mm - 2 (1.27 mm) = 3.26 mm / Smax = Lmax - 2Tmin = 6.2 mm - 2 (0.4 mm) = 5.40 mm / Stol = … = 2.14 mm", followed by "New_Smax is ultimately used to produce Gmin. Not Smax".
  - KiCad `TolerancedSize.update_rms()` implements exactly this.
- IPC-SM-782A text, quoted verbatim (**V**): "S tol (rms) = √(L tol² + 2(T tol)²) … = 1.29 mm … S max (rms) = S min + S tol (rms) = 3.26 + 1.29 = 4.55 mm … G min = 4.55 – 2(0.5) – √(1.29² + 0.1² + 0.1²) = 2.25 mm", with "F = 0.1 mm (assumed fabrication tolerance)" and "P = 0.1 mm (assumed assembly equipment placement tolerance)". My script reproduces 2.25 exactly. The 7351B variant gives Smax_rms = 4.977 for the same part.
- If the datasheet gives S directly (KiCad `terminator_spacing`), use S as given with `CS = Smax − Smin` (no RMS). That is KiCad behaviour (**V**).

### 1.3 F and P
| Item | Value | Status / source |
|---|---|---|
| IPC-7351B normative value | none; user and fabricator define it. 7351B "recommends F = 0 when the fabricator applies etch compensation". Tables 3-25 (finished conductor width tol.) and 3-26 (feature location accuracy) are suggested starting points | **V\*** (JITX `ipc.py` docstring). Table titles **V** (IPC-7351B TOC) |
| KiCad generator default | `manufacturing_tolerance: 0.1`, `placement_tolerance: 0.05` | **V** (`package_config_KLCv3.0.yaml`, generators) |
| PCB Libraries (Footprint Expert) | Tom H 2014: "Fabrication Tolerance – ± 2 Mil (0.05 mm); Placement Tolerance – ± 1 Mil (0.025 mm)", which is 0.10 / 0.05 as totals. Jeff.M 2014 (TID 785) contradicts this: "IPC-7351 … in their publication they use 0.10 mm for F and 0.20 mm for P … We use plus-or-minus values where an equivalent F would be +/- 0.05 mm and P would be +/- 0.10 mm so they're doubled before squaring" | **V\*** (TID 1314, TID 785, both read). P is inconsistent: 0.05 vs 0.20 total |
| IPC-SM-782A | F = 0.10, P = 0.10 | **V** |
| SnapEDA | "IPC uses a standard value of 0.1mm for each" | **V\*** (weak) |
| IPC-7352 (FPX model) | fabrication and assembly tolerances "turned off" (F = P = 0) | **V\*** (forum TID 2590) |
| IPC-2221A Table 10-3, conductor width tol. for 46 µm Cu (likely basis of 7351B Table 3-25) | unplated ±0.06 / ±0.04 / ±0.015 (Level A/B/C); plated ±0.10 / ±0.08 / ±0.05 | **V** values (FED excerpt). Mapping to 3-25 is **V\*** |

**Recommendation:** `F = 0.10, P = 0.05` as project defaults, stored per rule set and overridable per footprint.

### 1.4 Round-off
| Rule set | Z / G / X rounding | Status |
|---|---|---|
| KiCad (IPC-7351B tables) | `round(v/base)*base`, nearest, Python round-half-even; base 0.05 for chips ≥0603, gull wing, QFN; **0.02** for chips <0603 | **V** (yaml `round_base`, code) |
| PCB Libraries / IPC-7351B as they apply it | "everything is rounded to the nearest 0.01 mm"; 0.05 mm pad rounding "cannot be classified as an IPC compliant pattern". The same thread also says "IPC has no guidance on SMD pad size rounding" | **V\*** (forum TID 2866, Tom H; contradictory wording) |
| IPC-7351B table row text | "Round off to the nearest two place decimal (1.00, 1.01, 1.02 …)" | **U** (search snippets only) |
| Pad stack naming | 0.01 mm increments | **V\*** (TID 2866) |

**Recommendation:** setting `pad_roundoff ∈ {0.01 (IPC/PCBL), 0.05 (KiCad/legacy)}`, default 0.01 for strict 7351B. Use KiCad mode (0.05/0.02, half-even) when validating against KiCad test vectors. Round Z, G, X **independently**, then derive pads.

### 1.5 Pad geometry from Z/G/X
```
pad_len  = (Z - G)/2                 # along span
pad_wid  = X
center   = (Z + G)/4                 # distance of pad centre from footprint origin (each side)
# quad packages: same per axis (Zx,Gx) and (Zy,Gy); X shared
```
**V** (KiCad, reproduced). Pad shape: rectangle is acceptable. KiCad uses roundrect with radius ratio 0.25 and max 0.25 mm, with the comment "IPC-7351C will most likely suggest the use of rounded rectangle pads with 25% radius ratio but at a maximum of 0.25mm" (**V**, `config_KLCv3.0.yaml`). TI recommended patterns use 0.05 mm corner radius (**V\***, TID 2590). Paste: same size as the pad (1:1) by default. For chips smaller than 0402, KiCad shrinks paste to 90 % on all sides with a 0.05 heel reduction (**V**).

### 1.6 Sanity and clamping rules (needed in practice)
- **V**: KiCad forces `Gmin ≥ EP + 2·0.2` with `min_ep_to_pad_clearance = 0.2`, a heel reduction for packages with an exposed pad. TI: centre pad to signal pad ≥ 0.2 mm (SLUA271C). Broadcom: 0.15 mm.
- **V** (computed): tiny packages can produce G ≤ 0 at density M, e.g. SOT-523 at density M gives G = −0.10 (section 9). Clamp to a minimum pad-to-pad gap (suggest 0.2 mm, configurable). Also cap `pad_wid ≤ pitch − min_mask_web` (**U**: typical web 0.1 mm).
- **V**: KiCad overrides density per package where the nominal value gives oversized pads: SC-70 family uses `least`. MSOP-8 and SSOP-8 use `force_small_pitch_ipc_definition` (the ≤0.625 table) "if not using it, distance between pads is just 0.15mm".
- Pitch rule for gull-wing tables: `pitch < 0.625 → Table 3-3`, else Table 3-2 (**V**, KiCad code `gwc.pitch < 0.625`). Note that 0.65 mm pitch (TSSOP, MSOP, SC-70) falls into Table 3-2.

### 1.7 Courtyard
- Definition: smallest rectangle around the combined body and land pattern, plus the courtyard excess from the J-table row. **V\*** (KLC F5.3 wording, IPC-SM-782A "Courtyards are intended to encompass the land pattern and a component body").
- Excess per density: M 0.50 / N 0.25 / L 0.10 for almost all families. Exceptions: chips <0603 and flat lead 0.20 / 0.15 / 0.10; BGA 2.0 / 1.0 / 0.5; CAPAE/crystal 1.0 / 0.5 / 0.25; butt joints 1.5 / 0.8 / 0.2. **V\*** (KiCad + JITX agree; Tom H 2022: "IPC-7351B released in 2010 defines the 3-Tier courtyard sizes for Least 0.10, Nominal, 0.25 and Most 0.50").
- Conflicting older statement: in 2016 Tom H described the IPC courtyards as "around since 1987 when IPC-SM-782 was released" with "0.12 Excess for Least, 0.25 … Nominal, 0.50 … Most" (TID 1905). In 2022 he stated 0.10 for 7351B Least (TID 3060). KiCad and JITX use 0.10, so 0.10 is the default (**V\***).
- IPC-SM-782A itself used a 0.5 × 0.5 mm "grid placement courtyard" (**V**, IPC-SM-782A text). PCB Libraries' current non-IPC defaults are 0.40 / 0.20 / 0.10 (**V\***).
- Rounding: KLC puts all courtyard elements on a **0.01 mm grid**, line width 0.05, and computes clearance from **nominal** body dimensions (**V**). KiCad rounds the courtyard half-size up to the grid (**V**, `round_to_grid_up`). The IPC-7351B courtyard round-off rule is **U**. Implement `courtyard_grid` = 0.01 (default) or 0.05, rounding outward.
- KLC courtyard clearances (KiCad convention, not IPC) (**V**): default 0.25; 0.15 for parts smaller than 1.5 mm in any dimension; connectors 0.5; canned caps 0.5; crystals 0.5; BGA/WLCSP 1.0.

### 1.8 Verification of the model (test vectors) — **V** (run `python -I scripts/ipc7351b_ref.py`)
Inputs are KiCad data (git master, 2026-10-05). Expected values come from published `kicad-footprints` (format 20260206). F = 0.1, P = 0.05, density N.

| Footprint | L (min..max) | T | W | Table / round | Expected pad (len x wid @ ±centre) | Result |
|---|---|---|---|---|---|---|
| R_0402_1005Metric | 1.0..1.1 | 0.1..0.3 | 0.48..0.6 | 3-6 / 0.02 | 0.54 x 0.64 @ 0.51 | OK |
| R_0603_1608Metric | 1.5..1.7 | 0.15..0.4 | 0.7..0.95 | 3-5 / 0.05 | 0.8 x 0.95 @ 0.825 | OK |
| R_0805_2012Metric | 1.85..2.15 | 0.15..0.65 | 1.1..1.4 | 3-5 | 1.025 x 1.4 @ 0.9125 | OK |
| R_1206_3216Metric | 3.05..3.35 | 0.25..0.75 | 1.45..1.75 | 3-5 | 1.125 x 1.75 @ 1.4625 | OK |
| R_2512_6332Metric | 6.15..6.45 | 0.35..0.85 | 3.05..3.35 | 3-5 | 1.225 x 3.35 @ 2.9625 | OK |
| C_0805_2012Metric | 1.8..2.2 | 0.25..0.55 | 1.05..1.45 | 3-5 | 1.0 x 1.45 @ 0.95 | OK |
| CP_EIA-3216-18_Kemet-A | 3.0..3.4 | 0.5..1.0 | F 1.1..1.3 | IPC-7352 inward-L, N = (0.35, 0, 0.03), round 0.01 | 1.415 x 1.39 @ 1.3525 | OK |
| SOIC-8_3.9x4.9mm_P1.27mm | 5.8..6.2 | 0.4..1.27 | 0.31..0.51 | 3-2 | 1.95 x 0.6 @ 2.475 | OK |
| SOT-23 | 2.10..2.64 | **0.30..0.60** | 0.3..0.5 | 3-2 | 1.475 x 0.6 @ 0.9375 | OK (*) |
| SOT-23-5 | 2.8 (BSC) | 0.3..0.6 | 0.3..0.5 | 3-2 | 1.325 x 0.6 @ 1.1375 | OK |
| TSSOP-16_4.4x5mm_P0.65mm | 6.4 (BSC) | 0.45..0.75 | 0.17..0.30 | 3-2 (0.65 > 0.625) | 1.475 x 0.4 @ 2.8625 | OK |
| LQFP-48_7x7mm_P0.5mm | 9.0 (BSC) | 0.45..0.75 | 0.17..0.27 | 3-3 | 1.475 x 0.3 @ 4.1625 | OK |
| QFN-16-1EP_3x3mm_P0.5mm_EP1.75 | 3.0 | 0.3..0.5 | 0.18..0.30 | 3-15 + EP rule (G ≥ 1.75+0.4) | 0.775 x 0.25 @ 1.4625 | OK |

(*) KiCad master yaml now says foot = 0.40..0.60 for TO-236AB, which gives 1.50 x 0.60 @ 0.925. The published footprint matches 0.30..0.60, so the published library lags the data.

### 1.9 Which datasheet dimension maps to L / T / W, and which table (family mapping)
```python
FAMILY_RULES = {  # table ids refer to section 2; status per entry
  "chip_ge_0603":   dict(table="T3-5", L="body length", T="terminal band (bottom T2 if given)", W="body width"),        # V*
  "chip_lt_0603":   dict(table="T3-6", L="body length", T="terminal band", W="body width"),                              # V*
  "molded_polar":   dict(table="T3-13", L="overall length", T="bottom terminal length", W="terminal width (KEMET F)"),   # tantalum CAPMP, INDM, DIOM (SMA/SMB/SMC) V*
  "melf":           dict(table="T3-7", L="body length", T="end-cap length K/T", W="diameter"),                            # V*
  "sod_gullwing":   dict(table="T3-2", L="lead span HE/He", T="foot L/Lp", W="lead width b"),                           # SOD-123, SOD-323 V*
  "sod_flat":       dict(table="T3-22", L="lead span", T="foot length", W="lead width"),                               # SOD-123F/323F/523/923 (SODFL) V*/U mapping
  "sot_gullwing":   dict(table="T3-2 if pitch>=0.625 else T3-3", L="HE/E", T="Lp/L", W="bp/b"),                         # SOT-23(-5/6), SC-70, SOT-523(0.5 -> T3-3), SOT-223 V*
  "sot89":          dict(table="T3-22 (SOTFL)", L="HE", T="Lp", W="bp1/bp2; tab bp3"),                                  # U mapping (pcb-3d names SOT89 'SOTFL')
  "dpak_leads":     dict(table="T3-2", L="H (overall)", T="L (foot)", W="b"),                                           # U for tab: T3-14 flat lug
  "soic_ssop_tssop_msop_qfp": dict(table="T3-2 if pitch>=0.625 else T3-3", L="E/HE (per axis for QFP)", T="L/Lp", W="b/bp"),  # V
  "qfn":            dict(table="T3-15", L="body D/E", T="terminal L", W="b", extra="G >= EP + 2*0.2"),                    # V
  "son_dfn":        dict(table="T3-16", L="body", T="terminal L", W="b"),                                               # V*
  "pullback_qfn_son": dict(table="T3-18 (values U)", L="body - 2*pullback", T="terminal L", W="b"),                    # U
  "bga":            dict(table="T3-17 + T14-5/T14-6", land="from ball diameter"),                                         # V*
}
```

### 1.10 Recommended generation pipeline (synthesis; individual rules cite sections above)
1. Load package dims as `(min, max)` and select the rule set (`IPC7351B` default; `IPC7352` and `KiCad-compat` optional). Then select density M/N/L. JITX/KiCad default is N: "Level B … general-purpose choice" (**V\***).
2. Pick the table via `FAMILY_RULES` and the pitch rule. Compute S with RMS (1.2), Z/G/X (1.1), and round them (1.4).
3. Apply clamps (1.6): EP clearance 0.2, min gap, max pad width vs pitch.
4. Place pads by pitch. Pin numbering and zero orientation follow section 4.1 (Pin 1 left for 2-terminal parts, upper left for ICs). Footprint origin at the land-pattern centre for SMD (KiCad does this; IPC wording **U**). For THT KiCad uses pin 1 as origin (**V**).
5. Paste: 1:1 for pads; EP windows per section 7. Mask: 1:1 in the library, expansion via board rules (**V\***).
6. Assembly outline = nominal body rectangle with pin-1 bevel. Courtyard = bounding box of pads ∪ body (max or nominal, configurable) + excess, rounded outward (1.7).
7. Silkscreen: body outline offset outward, clipped so that clearance to every pad ≥ silk_pad_clearance + line_width/2 (0.12/0.2), plus a pin-1 marker. No silk under SMD bodies (KLC) (**V**).
8. 3D: extrude the body rectangle from standoff to the nominal or max height (section 8). Optionally add lead blocks.
9. Name: IPC name (section 4) as a parameter, plus a unique internal ID (TID 2336 flaw).

---

## 2. J-value tables (toe, heel, side, courtyard excess) per lead family — IPC-7351B

Sources: KiCad `ipc_7351b.yaml`, `ipc7351B_2terminal.yaml`, `ipc7351B_capae_crystal.yaml` (**V** read). JITX `jitxlib-standard 4.4.0 / leads/protrusions.py`, header "from IPC-7351B Section 3, Tables 3-2 to 3-22" (**V** read). Table titles: IPC-7351B TOC (**V**). The two transcriptions agree on every table that both contain, so the values are **V\***. M = Most (Level A), N = Nominal (Level B), L = Least (Level C) (**V**, naming PDF).

**Convention below: `toe` always acts on Z (outer edge), `heel` on G (inner edge).** Where IPC names the rows the other way round (Tables 3-4, 3-8, 3-13), the values are already swapped, as JITX and KiCad do (**V\***). JITX comment: "Tables 3-4, 3-8 and 3-13 name the row producing Zmax the 'heel' and the row producing Gmin the 'toe'".

```python
# (toe, heel, side, courtyard_excess) per density; round_base = KiCad default (0.05 unless noted)
IPC7351B_FILLETS = {
 "T3-2_flat_ribbon_L_gullwing_pitch_gt_0p625": {   # SOIC, SOT-23, SC-70, SOD-123, SOT-223, DPAK leads, TSSOP/MSOP 0.65, QFP 0.65/0.8
   "M": (0.55, 0.45, 0.05, 0.50), "N": (0.35, 0.35, 0.03, 0.25), "L": (0.15, 0.25, 0.01, 0.10)},  # V* (KiCad+JITX+SnapEDA)
 "T3-3_flat_ribbon_L_gullwing_pitch_le_0p625": {   # 0.5/0.4 mm pitch SOP/QFP, SOT-523
   "M": (0.55, 0.45, 0.01, 0.50), "N": (0.35, 0.35, -0.02, 0.25), "L": (0.15, 0.25, -0.04, 0.10)}, # V*
 "T3-4_J_lead_SWAPPED": {   # IPC row 'heel' (0.55/0.35/0.15) acts on Z; IPC row 'toe' (0.10/0.00/-0.10) on G
   "M": (0.55, 0.10, 0.05, 0.50), "N": (0.35, 0.00, 0.03, 0.25), "L": (0.15, -0.10, 0.01, 0.10)},  # V*
 "T3-5_chip_ge_1608": {
   "M": (0.55, 0.00, 0.05, 0.50), "N": (0.35, 0.00, 0.00, 0.25), "L": (0.15, 0.00, -0.05, 0.10)},  # V*
 "T3-6_chip_lt_1608": {     # KiCad round_base 0.02
   "M": (0.30, 0.00, 0.05, 0.20), "N": (0.20, 0.00, 0.00, 0.15), "L": (0.10, 0.00, -0.05, 0.10)},  # V*
 "T3-7_MELF_cylindrical_end_cap": {
   "M": (0.60, 0.20, 0.10, 0.50), "N": (0.40, 0.10, 0.05, 0.25), "L": (0.20, 0.02, 0.01, 0.10)},  # V* (JITX only + matches my memory; KiCad has no 7351B MELF table)
 "T3-8_LCC_castellated_SWAPPED": {
   "M": (0.65, 0.25, 0.05, 0.50), "N": (0.55, 0.15, -0.05, 0.25), "L": (0.45, 0.05, -0.15, 0.10)}, # V* (JITX; KiCad has the same under IPC-7351 'castellated')
 "T3-9_10_11_chip_array_concave_convex_flat": {
   "M": (0.55, -0.05, -0.05, 0.50), "N": (0.45, -0.07, -0.07, 0.25), "L": (0.35, -0.10, -0.10, 0.10)}, # V* (JITX only)
 "T3-12_butt_joint": {
   "M": (1.00, 1.00, 0.30, 1.50), "N": (0.80, 0.80, 0.20, 0.80), "L": (0.60, 0.60, 0.10, 0.20)},  # V* (JITX only)
 "T3-13_inward_flat_ribbon_L_SWAPPED": {  # molded inductors, diodes (SMA/SMB/SMC), polarized caps (tantalum)
   # IPC rows as printed: Toe 0.25/0.15/0.07, Heel 0.80/0.50/0.20, Side 0.01/-0.05/-0.10
   "M": (0.80, 0.25, 0.01, 0.50), "N": (0.50, 0.15, -0.05, 0.25), "L": (0.20, 0.07, -0.10, 0.10)}, # V* (KiCad comment + JITX)
 "T3-14_flat_lug": {
   "M": (0.55, 0.45, 0.05, 0.50), "N": (0.35, 0.35, 0.03, 0.25), "L": (0.15, 0.25, 0.01, 0.10)},  # V* (JITX only)
 "T3-15_QFN": {
   "M": (0.40, 0.00, -0.04, 0.50), "N": (0.30, 0.00, -0.04, 0.25), "L": (0.20, 0.00, -0.04, 0.10)}, # V*
 "T3-16_SON": {
   "M": (0.40, 0.00, -0.04, 0.50), "N": (0.30, 0.00, -0.04, 0.25), "L": (0.20, 0.00, -0.04, 0.10)}, # V* (JITX)
 "T3-18_pullback_QFN_SON": {  # KiCad values only, look synthetic
   "M": (0.05, 0.05, 0.05, 0.50), "N": (0.00, 0.00, 0.00, 0.25), "L": (-0.05, -0.05, -0.05, 0.10)}, # U
 "T3-20_CAPAE_crystal_lt_10mm": {
   "M": (0.70, 0.00, 0.50, 1.00), "N": (0.50, -0.10, 0.40, 0.50), "L": (0.30, -0.20, 0.30, 0.25)}, # V* (KiCad has side L = 0.03, JITX 0.3: KiCad typo likely)
 "T3-20_CAPAE_crystal_ge_10mm": {
   "M": (1.00, 0.00, 0.60, 1.00), "N": (0.70, -0.05, 0.50, 0.50), "L": (0.40, -0.10, 0.40, 0.25)}, # V*
 "T3-22_small_outline_flat_lead": {  # SODFL/SOTFL (SOD-123F, SOD-323F, SOD-523, SOT-89?)
   "M": (0.30, 0.00, 0.05, 0.20), "N": (0.20, 0.00, 0.00, 0.15), "L": (0.10, 0.00, -0.05, 0.10)}, # V* (JITX); KiCad IPC-7352 'flat lead' has L-side 0.00
 "T3-17_BGA": {"courtyard": {"M": 2.0, "N": 1.0, "L": 0.5}},                                      # V* (JITX 'IPC-7351B Table 3-17', KiCad IPC-7352 T3-11)
}
```
Comparison tables (do not use as 7351B defaults):
```python
IPC7351_2005_CHIP = {   # KiCad ipc7351_2terminal.yaml (from IPC-7351 2005 p.23) -- V*
 "lt_0603": {"M": (0.20, -0.05, 0.05, 0.20), "N": (0.10, -0.05, 0.00, 0.15), "L": (0.00, -0.05, 0.00, 0.10)},
 "ge_0603": {"M": (0.55, -0.05, 0.05, 0.50), "N": (0.35, -0.05, 0.00, 0.25), "L": (0.15, -0.05, -0.05, 0.10)}}
IPC7352_INWARD_L = {"M": (0.55, 0.10, 0.05, 0.50), "N": (0.35, 0.00, 0.03, 0.25), "L": (0.15, 0.00, 0.01, 0.10)}  # KiCad, round 0.01 -- V*
IPC7352_FLAT_LEAD = {"M": (0.30, 0.0, 0.05, 0.20), "N": (0.20, 0.0, 0.00, 0.15), "L": (0.10, 0.0, 0.00, 0.10)}      # KiCad 'IPC-7352 table 3-15' -- V*
IPC7352_BGA = {"L": {"collapsible": -0.25, "non_collapsible": +0.05, "courtyard": 0.5},   # pad = (1+ratio)*ball, round 0.01
               "N": {"collapsible": -0.20, "non_collapsible": +0.10, "courtyard": 1.0},
               "M": {"collapsible": -0.15, "non_collapsible": +0.15, "courtyard": 2.0}}   # KiCad ipc7352_ball.yaml -- V*
```
Notes: PCB Libraries proposed 7351C values with 40 pitch-dependent gull-wing rows and courtyard 0.40/0.20/0.10. These are not IPC-7351B (**V\***, TID 1905/2509). The IPC-7352 Table 3-6 castellated toe and heel appear swapped (Tom H, 2026-05: "IPC got the Toe and Heel values backward") (**V\***).

### 2.1 BGA lands (IPC-7351B Tables 14-5 / 14-6 / 14-4)
Source: IPC-7351B tables as reproduced on the PCB Libraries forum (TID 1708 image, confirmed by Tom H, TID 2607: "The IPC mathematical model uses this table") (**V\***; I read the images). IPC recommends the **maximum material condition (MMC)** of the land variation (Tom H; Altium AD22 docs: "Use Maximum Material Condition (MMC) to use the largest pad size (IPC recommended)") (**V**).
```python
# ball_nominal: (reduction, density_letter_in_table, land_nominal, land_max(MMC), land_min)
BGA_COLLAPSIBLE = {
 0.75: (0.25, "A", 0.55, 0.60, 0.50), 0.65: (0.25, "A", 0.50, 0.55, 0.45), 0.60: (0.25, "A", 0.45, 0.50, 0.40),
 0.55: (0.25, "A", 0.40, 0.45, 0.35), 0.50: (0.20, "B", 0.40, 0.45, 0.35), 0.45: (0.20, "B", 0.35, 0.40, 0.30),
 0.40: (0.20, "B", 0.30, 0.35, 0.25), 0.35: (0.20, "B", 0.30, 0.35, 0.25), 0.30: (0.20, "B", 0.25, 0.25, 0.20),
 0.25: (0.20, "B", 0.20, 0.20, 0.17), 0.20: (0.15, "C", 0.17, 0.20, 0.14), 0.17: (0.15, "C", 0.15, 0.18, 0.12),
 0.15: (0.15, "C", 0.13, 0.15, 0.10)}
BGA_NON_COLLAPSIBLE = {  # increase
 0.75: (0.15, 0.85, 0.90, 0.80), 0.65: (0.15, 0.75, 0.80, 0.70), 0.60: (0.15, 0.70, 0.75, 0.65), 0.55: (0.15, 0.65, 0.70, 0.60),
 0.50: (0.10, 0.55, 0.60, 0.50), 0.45: (0.10, 0.50, 0.55, 0.45), 0.40: (0.10, 0.45, 0.50, 0.40), 0.35: (0.10, 0.40, 0.45, 0.35),
 0.30: (0.10, 0.35, 0.40, 0.30), 0.25: (0.10, 0.30, 0.35, 0.25), 0.20: (0.05, 0.21, 0.26, 0.16), 0.17: (0.05, 0.18, 0.22, 0.13),
 0.15: (0.05, 0.16, 0.21, 0.11)}
BGA_BALL_VS_PITCH = {  # nominal ball: (variation max, min, typical pitches)   IPC-7351B Table 14-4 (V*)
 0.75: (0.90, 0.65, (1.50, 1.27)), 0.60: (0.70, 0.50, (1.00,)), 0.50: (0.55, 0.40, (1.00, 0.80)),
 0.45: (0.50, 0.40, (1.00, 0.80, 0.75)), 0.40: (0.45, 0.35, (0.80, 0.75, 0.65)), 0.30: (0.35, 0.25, (0.80, 0.75, 0.65, 0.50)),
 0.25: (0.28, 0.22, (0.40,)), 0.20: (0.22, 0.18, (0.30,)), 0.15: (0.17, 0.13, (0.25,))}
```
- For balls between table rows, take the lower row's values (Tom H, TID 3370) (**V\***). The FPX 2024 table recomputes exact percentages, e.g. 0.55 → 0.41 (**V\***, image).
- IPC-7351B §14.2.4 text (quoted on the forum) contradicts the table: "typically 20% smaller … for pitches greater than 1.0 mm and 10% smaller for pitches less than 1.0 mm" (**V\***).
- BGA names carry no M/N/L suffix: "This excludes the BGA component family as they only come in the Nominal Environment Condition" (**V**, naming PDF).

---

## 3. Package dimension data (min/max), Python-dict ready

Conventions: tuples are `(min, max)`; `nom` where given; `None` = not specified. `src` keys refer to section 11. Use the **datasheet of the actual part** when available; these are defaults for generators and series wizards.

### 3.1 Chip resistors (EIA ↔ metric) — Vishay D/CRCW e3 rev 14-Apr-2026 (S15, **V**), CRCW0201/01005 e3 (**V**), IPC-SM-782A §8.1 (S4, **V**)
`T1` = top-side terminal, `T2` = bottom-side terminal. For IPC calculations use T2 (bottom) when given. KiCad uses IPC-SM-782 values.
```python
CHIP_RESISTOR = {   # Vishay CRCW e3: L, W, H, T1, T2  (+ IPC-SM-782A alt: L, W, T, S, Hmax)
 "01005": dict(metric="0402", L=(0.38,0.42), W=(0.18,0.22), H=(0.11,0.15), T1=(0.07,0.13), T2=(0.07,0.13), src="S15c"),
 "0201":  dict(metric="0603", L=(0.57,0.63), W=(0.27,0.33), H=(0.20,0.26), T1=(0.10,0.20), T2=(0.05,0.15), src="S15b"),
 "0402":  dict(metric="1005", L=(0.95,1.05), W=(0.45,0.55), H=(0.30,0.40), T1=(0.15,0.35), T2=(0.10,0.30), src="S15a",
               ipc782=dict(L=(1.00,1.10), S=(0.40,0.70), W=(0.48,0.60), T=(0.10,0.30), Hmax=0.40)),
 "0603":  dict(metric="1608", L=(1.50,1.65), W=(0.75,0.95), H=(0.40,0.50), T1=(0.10,0.50), T2=(0.10,0.50), src="S15a",
               ipc782=dict(L=(1.50,1.70), S=(0.70,1.11), W=(0.70,0.95), T=(0.15,0.40), Hmax=0.60)),
 "0805":  dict(metric="2012", L=(1.90,2.20), W=(1.10,1.40), H=(0.40,0.60), T1=(0.20,0.50), T2=(0.10,0.50), src="S15a",
               ipc782=dict(L=(1.85,2.15), S=(0.55,1.32), W=(1.10,1.40), T=(0.15,0.65), Hmax=0.65)),
 "1206":  dict(metric="3216", L=(3.00,3.30), W=(1.45,1.75), H=(0.50,0.60), T1=(0.25,0.65), T2=(0.20,0.60), src="S15a",
               ipc782=dict(L=(3.05,3.35), S=(1.55,2.32), W=(1.45,1.75), T=(0.25,0.75), Hmax=0.71)),
 "1210":  dict(metric="3225", L=(3.00,3.40), W=(2.30,2.70), H=(0.50,0.60), T1=(0.25,0.65), T2=(0.20,0.60), src="S15a",
               ipc782=dict(L=(3.05,3.35), S=(1.55,2.32), W=(2.34,2.64), T=(0.25,0.75), Hmax=0.71)),
 "1812":  dict(metric="4532", L=(4.30,4.70), W=(3.00,3.40), H=None, T=(0.30,0.70), src="S5 (KiCad R_1812, Panasonic link)", status="V*"),
 "2010":  dict(metric="5025", L=(4.85,5.15), W=(2.35,2.65), H=(0.50,0.70), T1=(0.40,0.80), T2=(0.40,0.80), src="S15a",
               ipc782=dict(L=(4.85,5.15), S=(3.15,3.92), W=(2.35,2.65), T=(0.35,0.85), Hmax=0.71)),
 "2512":  dict(metric="6332", L=(6.10,6.50), W=(3.00,3.30), H=(0.50,0.70), T1=(0.40,0.80), T2=(0.40,0.80), src="S15a",
               ipc782=dict(L=(6.15,6.45), S=(4.45,5.22), W=(3.05,3.35), T=(0.35,0.85), Hmax=0.71)),
}
# Vishay recommended reflow lands (G, Y=pad length, X, Z), cross-check only (V):
VISHAY_CRCW_REFLOW_LANDS = {"0402": (0.45,0.6,0.6,1.65), "0603": (0.75,0.75,1.00,2.25), "0805": (1.00,0.95,1.45,2.90),
  "1206": (1.50,1.05,1.80,3.60), "1210": (1.70,1.10,2.80,3.90), "2010": (3.50,1.45,2.80,6.40), "2512": (4.75,1.45,3.50,7.65),
  "0201": dict(a=0.28,b=0.43,l=0.23), "01005": dict(a=0.15,b=0.2,l=0.2)}
```

### 3.2 Chip capacitors (MLCC) — KEMET/YAGEO C1002 X7R, 2026-09-01 (S16, **V**); IPC-SM-782A §8.2 (S4, **V**)
`B` = band width (terminal T). Thickness depends on the value: use the per-part thickness code. KEMET note: "For capacitance values ≥ 2.2 µF add 0.10 to the length tolerance" etc. (the tolerance adders depend on the value) (**V**).
```python
MLCC = {
 "0402": dict(metric="1005", L=(0.95,1.05), W=(0.45,0.55), B=(0.20,0.40), S_min=0.30, T_codes={"BB":(0.45,0.55)},
              ipc782=dict(L=(0.90,1.10), W=(0.40,0.60), T=(0.10,0.30), Hmax=0.60)),
 "0603": dict(metric="1608", L=(1.45,1.75), W=(0.65,0.95), B=(0.20,0.50), S_min=0.50,
              T_codes={"CF":(0.73,0.87),"CG":(0.70,0.90),"CJ":(0.65,0.95),"CK":(0.60,1.00)}, ipc782=dict(L=(1.45,1.75), W=(0.65,0.95), T=(0.20,0.50), Hmax=0.85)),
 "0805": dict(metric="2012", L=(1.80,2.20), W=(1.05,1.45), B=(0.25,0.75), S_min=0.70, T_range=(0.50,1.45),   # DM 0.70±0.20 ... DH 1.25±0.20
              ipc782=dict(L=(1.80,2.20), W=(1.05,1.45), T=(0.25,0.75), Hmax=1.10)),
 "1206": dict(metric="3216", L=(3.00,3.40), W=(1.40,1.80), B=(0.25,0.75), S_min=1.50, T_range=(0.58,1.80),   # EB 0.78±0.10 ... EH 1.60±0.20
              ipc782=dict(L=(3.00,3.40), W=(1.40,1.80), T=(0.25,0.75), Hmax=1.35)),
 "1210": dict(metric="3225", L=(3.00,3.40), W=(2.30,2.70), B=(0.25,0.75), S_min=1.50, T_range=(0.68,2.80),   # FB 0.78±0.10 ... FS 2.50±0.30
              ipc782=dict(L=(3.00,3.40), W=(2.30,2.70), T=(0.25,0.75), Hmax=1.35)),
 "1812": dict(metric="4532", L=(4.20,4.80), W=(2.90,3.50), B=(0.25,0.95), S_min=2.30, T_range=(0.90,2.70),   # GB 1.00±0.10 ... GO 2.50±0.20
              ipc782=dict(L=(4.20,4.80), W=(3.00,3.40), T=(0.25,0.95), Hmax=1.35)),
 # not in KEMET C1002 -- typical Murata/Samsung values, UNVERIFIED:
 "0201":  dict(metric="0603", L=(0.57,0.63), W=(0.27,0.33), T=(0.27,0.33), B=(0.10,0.20), status="U"),
 "01005": dict(metric="0402", L=(0.38,0.42), W=(0.18,0.22), T=(0.18,0.22), B=(0.07,0.14), status="U"),
}
```
Other sizes, for completeness (**V**): 1808 = 4.70±0.50 × 2.00±0.20, B 0.60±0.35; 1825 = 4.50±0.30 × 6.40±0.40; 2220 = 5.70±0.40 × 5.00±0.40; 2225 = 5.60±0.40 × 6.40±0.40.

### 3.3 Chip inductors
- IPC-SM-782A §8.3 (**V**): 2012 chip: L 1.70–2.30, W 0.60–1.20, T 0.10–0.30, Hmax 1.20. 3216 chip: L 2.90–3.50, W 1.30–1.90, T 0.20–0.50, Hmax 1.90. 4516 chip: L 4.20–4.80, W 0.60–1.20 (KiCad uses 1.3–1.9, IPC value suspected typo), T 0.30–0.80, Hmax 1.90.
- Multilayer ferrite chip inductors (0201…1210) follow MLCC body sizes. **U**: use the MLCC table plus the part's thickness. Use prefix `INDC`.
- KiCad 1008 (2520): 2.5±0.2 × 2.0±0.2, T 0.6±0.25 (ECS source) (**V\***).

### 3.4 Molded tantalum (CAPMP) — KEMET T491 (S17, **V**), IPC-SM-782A §8.4 (**V**)
KEMET columns: L, W, H, F = terminal width ±0.1, S = terminal length, A(min) = min gap between terminations (bottom), G(ref), E(ref).
```python
TANTALUM = {  # IPC calc: L=L (overall), T=S, W=F
 "A": dict(eia="3216-18", L=(3.0,3.4), W=(1.4,1.8), H=(1.4,1.8), F=(1.1,1.3), S=(0.5,1.0), A_min=1.2, G_ref=1.1, E_ref=1.3,
           ipc782=dict(L=(3.00,3.40), S=(0.80,1.74), W1=(1.17,1.21), W2=(1.40,1.80), T=(0.50,1.10), H2max=1.80)),
 "B": dict(eia="3528-21", L=(3.3,3.7), W=(2.6,3.0), H=(1.7,2.1), F=(2.1,2.3), S=(0.5,0.9), A_min=1.9, G_ref=1.8, E_ref=2.2,
           ipc782=dict(L=(3.30,3.70), S=(1.10,2.04), W1=(2.19,2.21), W2=(2.60,3.00), T=(0.50,1.10), H2max=2.10)),
 "C": dict(eia="6032-28", L=(5.7,6.3), W=(2.9,3.5), H=(2.2,2.8), F=(2.1,2.3), S=(1.0,1.6), A_min=2.9, G_ref=2.8, E_ref=2.4,
           ipc782=dict(L=(5.70,6.30), S=(2.50,3.54), W1=(2.19,2.21), W2=(2.90,3.50), T=(1.00,1.60), H2max=2.80)),
 "D": dict(eia="7343-31", L=(7.0,7.6), W=(4.0,4.6), H=(2.5,3.1), F=(2.3,2.5), S=(1.0,1.6), A_min=3.6, G_ref=3.5, E_ref=3.5,
           ipc782=dict(L=(7.00,7.60), S=(3.80,4.84), W1=(2.39,2.41), W2=(4.00,4.60), T=(1.00,1.60), H2max=3.10)),
}
# The EIA suffix (-18, -21, -28, -31) is the max height x10 (A: 1.6±0.2 -> 1.8 max).  V
```

### 3.5 MELF / MiniMELF / MicroMELF (RESMELF / DIOMELF)
```python
MELF = {  # L = length, D = diameter, K = end-cap length (IPC T)
 "MicroMELF_0102": dict(L=(2.1,2.2), D=(1.0,1.1), K=(0.35,0.45), L1_min=1.2, src="Vishay MMU 0102 (S18) V"),
 "MiniMELF_0204":  dict(L=(3.4,3.6), D=(1.3,1.4), K=(0.7,0.9),   L1_min=1.8, src="Vishay MMA 0204 (S18) V"),
 "MELF_0207":      dict(L=(5.65,5.8), D=(2.0,2.2), K=(1.05,1.25), L1_min=3.2, src="Vishay MMB 0207 (S18) V"),
 "MiniMELF_SOD-80_LL-34": dict(L=(3.30,3.70), D=(1.30,1.60), K=(0.28,0.50), src="Diodes MiniMELF (S19) V",
                          ipc782=dict(L=(3.30,3.70), S=(2.20,2.65), D=(1.60,1.70), T=(0.41,0.55))),
 "MELF_DO-213AB_LL-41":   dict(L=(4.80,5.20), D=(2.40,2.60), K_typ=0.55, src="Diodes MELF (S19) V",
                          ipc782=dict(L=(4.80,5.20), S=(3.80,4.25), D=(2.44,2.54), T=(0.36,0.50))),
 # IPC-SM-782A MELF resistors (V): 2012: L 1.90-2.10, D 1.35-1.45, T 0.23-0.37 | 3216: L 3.00-3.40, D 1.75-1.85, T 0.43-0.57
 #                                 3516: L 3.30-3.70, D 1.55-1.65, T 0.43-0.57 | 5923: L 5.70-6.10, D 2.40-2.50, T 0.53-0.67
}
VISHAY_MELF_REFLOW_LANDS = {"0102": dict(G=1.1, Y=0.8, X=1.3, Z=2.7), "0204": dict(G=1.7, Y=1.2, X=1.6, Z=4.1), "0207": dict(G=3.2, Y=1.7, X=2.4, Z=6.6)}  # V
```

### 3.6 SOD family
```python
SOD = {  # HE = lead span, body D(len) x E(wid) as per vendor letters normalised to body_len/body_wid, b = lead width, Lf = foot
 "SOD-123":  dict(HE=(3.55,3.85), body_len=(2.55,2.85), body_wid=(1.40,1.70), b=(0.52,0.62), Lf=(0.25,0.40), A=(1.00,1.35), A1=(0.00,0.10), c=(0.10,0.15),
                  src="Diodes SOD123 (S19) V", ipc782=dict(L=(3.55,3.85), S=(2.35,2.93), W1=(0.45,0.65), W2=(1.40,1.70), T=(0.25,0.60), Hmax=1.35)),
 "SOD-123F": dict(HE=(3.4,3.6), body_len=(2.5,2.7), body_wid=(1.5,1.7), b=(0.55,0.70), Lf=(0.35,0.55), A=(1.0,1.2), c=(0.10,0.25),
                  src="Nexperia SOD123F (S20) V", alt_diodes=dict(HE=(3.30,3.70), body_len=(2.60,2.80), body_wid=(1.70,1.90), b=(0.80,1.05), Lf=(0.35,0.85), A=(0.81,1.15))),
 "SOD-323":  dict(HE=(2.3,2.7), body_len=(1.6,1.8), body_wid=(1.15,1.35), b=(0.25,0.40), Lf=(0.15,0.45), A=(0.8,1.1), A1_max=0.05, c=(0.10,0.25),
                  src="Nexperia SOD323 / SC-76 (S20) V", alt_diodes=dict(HE=(2.30,2.70), body_len=(1.60,1.80), body_wid=(1.20,1.40), b=(0.25,0.35), Lf=(0.20,0.40), A=(1.00,1.10))),
 "SOD-523":  dict(HE=(1.55,1.70), body_len=(1.15,1.25), body_wid=(0.75,0.85), b=(0.26,0.34), Lf=(0.10,0.30), A=(0.58,0.65), c=(0.11,0.17),
                  src="Nexperia SOD523 / SC-79 (S20) V; Diodes: HE 1.55-1.65, A 0.55-0.65"),
 "SOD-923":  dict(HE=(0.95,1.05), body_len=(0.75,0.85), body_wid=(0.55,0.65), b=(0.15,0.25), Lf=(0.07,0.19), A=(0.36,0.43),
                  src="search summary of MCC/onsemi drawings", status="U"),   # JEITA SC-116A per mbedded.ninja (U)
}
```
Gull wing vs flat (**V**, drawings): SOD-123 and SOD-323 have bent gull-wing leads, so use Table 3-2. SOD-123F and SOD-523 have flat leads, so use Table 3-22 (SODFL). SOD-923: Table 3-22 (**U**).

### 3.7 SMA / SMB / SMC (DO-214AC/AA/AB, molded inward-L "DIOM") — Diodes Inc. (S19, **V**)
```python
DO214 = {  # body_len, body_wid, overall E (IPC L), lead width b (IPC W), terminal length (IPC T), height
 "SMA_DO-214AC": dict(body_len=(4.00,4.60), body_wid=(2.29,2.92), E=(4.80,5.59), b=(1.27,1.63), T=(0.76,1.52), A=(1.96,2.40), A1=(0.05,0.20), c=(0.15,0.31)),
 "SMB_DO-214AA": dict(body_len=(4.06,4.57), body_wid=(3.30,3.94), E=(5.00,5.59), b=(1.96,2.21), T=(0.76,1.52), A=(2.00,2.50), A1=(0.05,0.20), c=(0.15,0.31),
                      ipc782=dict(L=(5.21,5.59), S=(2.17,3.31), W1=(1.96,2.21), W2=(3.30,3.94), T=(0.76,1.52), Hmax=2.41)),
 "SMC_DO-214AB": dict(body_len=(6.60,7.11), body_wid=(5.59,6.22), E=(7.75,8.13), b=(2.75,3.18), T=(0.76,1.52), A=(2.00,2.50), A1=(0.10,0.20), c=(0.15,0.31)),
}
```
Diodes' own suggested SMA pads (cross-check) (**V**): C 4.00, G 1.50, X 2.50, X1 6.50, Y 1.70.

### 3.8 SOT-23 / SOT-23-5/6 / SC-70 (SOT-323/363) / SOT-523
```python
SOT_SMALL = {  # HE = lead span (IPC L), E = body width, D = body length, b, Lf = foot (IPC T), A = height, e = pitch
 "SOT-23-3_TO-236AB_JEDEC": dict(HE=(2.10,2.64), E=(1.20,1.40), D=(2.80,3.04), b=(0.30,0.50), Lf=(0.40,0.60), c=(0.08,0.20), A1=(0.05,0.15), e=0.95, e1=1.90,
                                 src="KiCad sot.yaml 'JEDEC TO-236 Var AB' (S5) V*; published KiCad footprint implies Lf 0.30-0.60"),
 "SOT-23-3_Nexperia":       dict(HE=(2.1,2.5), E=(1.2,1.4), D=(2.8,3.0), b=(0.38,0.48), Lf=(0.15,0.45), A=(0.9,1.1), A1_max=0.1, c=(0.09,0.15), src="Nexperia SOT23 (S20) V"),
 "SOT-23_IPC-SM-782A":      dict(L=(2.30,2.60), S=(1.10,1.47), W=(0.36,0.46), T=(0.45,0.60), Hmax=1.10, src="S4 V"),
 "SOT-23-5/6_MO-178_TI_DBV":dict(HE=(2.60,3.00), E=(1.45,1.75), b=(0.30,0.50), Lf=(0.30,0.60), A_max=1.45, e=0.95, src="TI DBV0005A (search summary) V*"),
 "SOT-23-5_Diodes_SOT25":   dict(HE=(2.70,3.00), E=(1.50,1.70), D=(2.90,3.10), b=(0.35,0.50), Lf=(0.35,0.55), A=(1.00,1.30), c=(0.10,0.20), e=0.95, src="S19 V"),
 "SOT-23-6_Diodes_SOT26":   dict(HE=(2.70,3.00), E=(1.50,1.70), D=(2.90,3.10), b=(0.35,0.50), Lf=(0.35,0.55), A2=(1.00,1.30), A1=(0.013,0.10), c=(0.10,0.20), e=0.95, e1=1.90, src="S19 V"),
 "SC-74A_SOT753_Nexperia":  dict(HE=(2.5,3.0), E=(1.3,1.7), D=(2.7,3.1), b=(0.25,0.40), Lf=(0.2,0.6), A=(0.9,1.1), e=0.95, src="S20 V (not MO-178!)"),
 "SOT-323_SC-70_Nexperia":  dict(HE=(2.0,2.2), E=(1.15,1.35), D=(1.8,2.2), b=(0.3,0.4), Lf=(0.15,0.45), A=(0.8,1.1), c=(0.10,0.25), e=1.3, e1=0.65, src="S20 V"),
 "SOT-363_SC-88_Nexperia":  dict(HE=(2.0,2.2), E=(1.15,1.35), D=(1.8,2.2), b=(0.20,0.30), Lf=(0.15,0.45), A=(0.8,1.1), c=(0.10,0.25), e=0.65, src="S20 V"),
 "SC-70_JEDEC_MO-203_JEITA":dict(HE=(1.8,2.4), E=(1.10,1.40), D=(1.8,2.2), b=(0.15,0.30), Lf=(0.10,0.46), A_max=1.1, src="KiCad sot.yaml comments (JEDEC 2.1±0.3) V*"),
 "SOT-523_Diodes":          dict(HE=(1.45,1.75), E=(0.75,0.85), D=(1.50,1.70), b=(0.15,0.30), Lf=(0.20,0.40), A2=(0.60,0.80), A1=(0.00,0.10), e=0.50, e1=1.00, src="S19 V"),
 "SC-75_SOT416_Nexperia":   dict(HE=(1.45,1.75), E=(0.7,0.9), D=(1.4,1.8), b=(0.15,0.30), Lf=(0.15,0.45), A=(0.6,0.9), e=0.5, e1=1.0, src="S20 V"),
}
```
Note (**V**): SC-74/SC-74A (Nexperia SOT457/SOT753) are similar to SOT-23-6/5 but not identical to MO-178. Treat them as separate packages. SOT-523 is equivalent to SC-75/SOT-416 in dimensions (**V**, compared). The family name equivalence is **U**.

### 3.9 SOT-89 (TO-243 / SC-62) and SOT-223 (TO-261 / SC-73)
```python
SOT89 = dict(HE=(3.75,4.25), D=(4.4,4.6), E=(2.4,2.6), b1_pins13=(0.35,0.48), b2_pin2=(0.40,0.53), b3_tab=(1.4,1.8),
             Lp=(0.8,1.2), c=(0.23,0.44), A=(1.4,1.6), e=3.0, e1=1.5, src="Nexperia SOT89 (S20) V",
             ipc782=dict(L=(3.94,4.25), T=(0.89,1.20), W1=(0.36,0.48), W2=(0.44,0.56), W3=(1.62,1.83), K=(2.60,2.85), Hmax=1.60, P=1.50),
             diodes=dict(A=(1.40,1.60), D=(4.40,4.60), E=(2.40,2.60), H=(3.95,4.25), L=(0.90,1.20), D1_tab=(1.62,1.83), c=(0.35,0.43)))
SOT223 = dict(HE=(6.7,7.3), D=(6.3,6.7), E=(3.3,3.7), bp=(0.60,0.80), b1_tab=(2.9,3.1), Lp=(0.7,1.1), c=(0.22,0.32), A=(1.5,1.8), A1=(0.01,0.10),
              e_pin1_to_3=4.6, e1_pitch=2.3, src="Nexperia SOT223 (S20) V",
              ipc782=dict(L=(6.70,7.30), S=(4.10,4.92), W1=(0.60,0.88), W2_tab=(2.90,3.18), T=(0.90,1.30), Hmax=1.80, P1=2.30, P2=4.60),
              diodes=dict(A=(1.55,1.65), b=(0.60,0.80), b1=(2.90,3.10), D=(6.45,6.55), E=(3.45,3.55), E1=(6.90,7.10), L=(0.85,1.05), e=2.30))
```

### 3.10 TO-252 (DPAK) and TO-263 (D2PAK)
```python
DPAK_TO252AA = dict(A=(2.18,2.39), A1=(0.0,0.13), b=(0.64,0.89), b2=(0.76,1.14), b3_tab=(4.95,5.46), c=(0.46,0.61), c2_tab=(0.46,0.89),
                    D=(5.97,6.22), D1_min=5.21, E=(6.35,6.73), E1_min=4.32, e=2.29, H=(9.40,10.41), L_foot=(1.40,1.78), L1_ref=2.74,
                    L3_tab=(0.89,1.27), L4_max=1.02, src="Vishay D-PAK (TO-252AA) doc 95627 'conforms to JEDEC TO-252AA' (S21) V",
                    nexperia=dict(A=(2.22,2.38), b=(0.71,0.89), b2_tab=(5.00,5.46), D1=(5.98,6.22), E=(6.47,6.73), HD=(9.6,10.4), L=(2.55,2.95), e=2.285),
                    ipc782_TS003=dict(L=(9.32,10.41), W1=(0.64,0.91), W2_tab=(4.35,5.35), T1=(0.51,0.80), T2_tab=(4.00,5.50), P1=2.28, P2=4.57, Hmax=2.38))
D2PAK_TO263AB = dict(A=(4.06,4.83), A1=(0.0,0.25), b=(0.51,0.99), b1=(0.51,0.89), b2=(1.14,1.78), c=(0.38,0.74), c2_tab=(1.14,1.65),
                     D=(8.38,9.65), D1_min=6.86, E=(9.65,10.67), E1_min=6.22, e=2.54, H=(14.61,15.88), L_foot=(1.78,2.79), L1_max=1.65,
                     L4=(4.78,5.28), src="Vishay TO-263AB doc 91364 'conforms to JEDEC TO-263AB' (S21) V",
                     nexperia=dict(A=(4.1,4.5), A1_tab=(1.27,1.40), b=(0.60,0.85), E=(9.7,10.3), HD=(14.8,15.8), Lp=(2.1,2.9), e=2.54),
                     ipc782_TS005=dict(L=(14.60,15.88), W1=(0.51,0.91), W2_tab=(6.22,6.86), T1=(2.29,2.79), T2_tab=(8.00,9.00), P1=2.54, P2=5.08, Hmax=4.83))
```
Land approach for DPAK/D2PAK (**V\*** from the Altium template columns `JTmin JH1min JH2min JS1min JS2min`; table assignment **U**): use gull wing (Table 3-2) for the leads, with L = H and T = foot. Size the tab land from the exposed tab (b3 × tab length) with the flat-lug goals (Table 3-14). The IPC-SM-782A tab land uses T2 = 4.00–5.50 (DPAK).

### 3.11 SOIC (JEDEC MS-012, narrow 3.9 mm)
```python
SOIC_MS012 = dict(HE=(5.8,6.2), E=(3.8,4.0), b=(0.31,0.51), Lp=(0.40,1.27), A_max=1.75, A1=(0.10,0.25), A2_min=1.25, c=(0.10,0.25), e=1.27,
                  D={8:(4.8,5.0), 14:(8.55,8.75), 16:(9.80,10.00)},
                  src="Nexperia SOT96-1 (MS-012) (S20) V; IPC-SM-782A S08/S014/S016 identical L/W/T/B (W 0.33-0.51, H 1.35-1.75) V; KiCad JEDEC V*")
SOIC_WIDE_MS013 = dict(HE=(10.00,10.65), E=(7.40,7.60), b=(0.33,0.51), Lp=(0.40,1.27), A=(2.35,2.65), e=1.27,
                       D={16:(10.10,10.50), 20:(12.60,13.00)}, src="IPC-SM-782A (S4) V")
```

### 3.12 SSOP / TSSOP / MSOP (0.65 / 0.5 mm)
```python
TSSOP_MO153 = dict(HE=(6.2,6.6), E=(4.3,4.5), b_065=(0.19,0.30), b_050=(0.17,0.27), Lp=(0.45,0.75), A_max=1.20, A1=(0.05,0.15), A2=(0.80,1.05), c=(0.09,0.20),
                   D={("0.65",8):(2.9,3.1), ("0.65",14):(4.9,5.1), ("0.65",16):(4.9,5.1), ("0.65",20):(6.4,6.6), ("0.65",24):(7.7,7.9), ("0.65",28):(9.6,9.8),
                      ("0.5",20):(4.9,5.1), ("0.5",24):(6.4,6.6), ("0.5",28):(7.7,7.9), ("0.5",38):(9.6,9.8)},
                   src="Nexperia SOT403-1 (TSSOP16) V; other D/b from KiCad MO-153 data V* (KiCad uses HE 6.40 BSC)")
MSOP_MO187 = {"8_0.65":  dict(HE=(4.7,5.1), E=(2.9,3.1), D=(2.9,3.1), b=(0.25,0.45), Lp=(0.4,0.7), A_max=1.1, A1=(0.05,0.15), c=(0.15,0.28), e=0.65,
                            src="Nexperia SOT505-1 V; JEDEC MO-187 AA via KiCad: HE 4.9±0.25, b 0.22-0.38, L 0.4-0.8 V*"),
              "10_0.5":  dict(HE_nom=4.90, E_nom=3.00, D_nom=3.00, b=(0.17,0.33), Lp=(0.40,0.80), A_max=1.10, e=0.5, src="KiCad MO-187 BA (BSC values, tol U) V*")}
SSOP_MO150_5p3 = dict(HE=(7.40,8.20), E=(5.00,5.60), b=(0.22,0.38), Lp=(0.55,0.95), A=(1.70,2.00), c=(0.09,0.25), e=0.65,
                      D={8:(2.70,3.30), 14:(5.90,6.50), 20:(6.90,7.50), 24:(7.90,8.50), 28:(9.90,10.50)}, src="KiCad ssop.yaml (JEDEC MO-150) V*")
SSOP_0p5_5p3 = dict(HE=(7.40,8.20), E=(5.00,5.60), b=(0.20,0.315), Lp=(0.55,0.95), A_max=2.00, D={48:(12.50,13.10)}, src="KiCad (ADI G48) V*")
QSOP_MO137 = dict(HE=(5.84,6.20), E=(3.81,3.99), b=(0.20,0.30), Lp=(0.41,0.89), A=(1.245,1.651), e=0.635, D={16:(4.80,4.98)}, src="KiCad (Maxim 21-0055) V*")
```

### 3.13 QFN / DFN / SON with exposed pad (JEDEC MO-220 / MO-229 family)
The exposed pad size is device-specific and must come from the datasheet. Typical envelopes:
```python
QFN_GENERIC = {  # status V* (from KiCad data entries + their datasheet links)
 "b_by_pitch": {0.4: (0.15,0.25), 0.5: (0.18,0.30), 0.65: (0.25,0.35), 0.8: (0.25,0.35)},  # 0.4/0.8 rows U
 "L_terminal": (0.30, 0.50),
 "A_by_profile": {"VQFN": (0.80,1.00), "WQFN": (0.70,0.80), "UQFN": (0.50,0.60)},   # max values follow JEDEC 'V/W/U' profile letters (U)
 "A1": (0.00, 0.05), "A3_ref": 0.20,
 "body_tol": "±0.05..±0.10 (vendor-dependent; JEDEC BSC + profile tol)",
}
QFN_EXAMPLES = {
 "QFN-16 3x3 P0.5": dict(D=3.0, L=(0.30,0.50), b=(0.18,0.30), EP=(1.65,1.85), A=(0.70,0.80), src="onsemi NCN4555 via KiCad"),
 "QFN-20 4x4 P0.5": dict(D=4.0, L=(0.35,0.55), b=(0.18,0.30), EP=(2.45,2.75), A=(0.70,0.80), src="Microchip doc2535 via KiCad"),
 "QFN-24 4x4 P0.5": dict(D=4.0, L=(0.30,0.50), b=(0.20,0.30), EP=(2.40,2.60), A=(0.80,0.90), src="Microchip 00000049BQ p278 via KiCad"),
 "QFN-28 5x5 P0.5": dict(D=5.0, L=(0.35,0.45), b=(0.18,0.30), EP=(3.15,3.35), A=(0.80,1.00), src="Microchip via KiCad"),
 "QFN-32 5x5 P0.5": dict(D=(4.9,5.1), L=(0.30,0.50), b=(0.20,0.30), EP=(3.35,3.55), A=(0.70,0.80), src="ADI 05-08-1693 via KiCad"),
 "QFN-48 7x7 P0.5": dict(D=(6.9,7.1), L=(0.30,0.50), b=(0.20,0.30), EP=(5.5,5.7), A=(0.50,0.60), src="ST STM32F042 UFQFPN via KiCad"),
 "QFN-64 9x9 P0.5": dict(D=(8.9,9.1), L=(0.30,0.50), b=(0.20,0.30), EP=(7.05,7.25), A=(0.70,0.80), src="ADI 229321fa via KiCad"),
 "QFN-16 4x4 P0.65": dict(D=(3.9,4.1), L=(0.35,0.45), b=(0.25,0.35), EP=2.1, A=(0.85,0.95), src="THAT1580 via KiCad"),
 "DFN-8 2x2 P0.5": dict(D=(1.85,2.15), L=(0.20,0.50), b=(0.18,0.30), EP=((0.75,1.00),(1.45,1.70)), src="ST LM2903 via KiCad"),
 "DFN-6 2x2 SOT1220-2": dict(note="Nexperia outline downloaded (S20); body 2x2x0.65"),
}
```
TI land guidance (SLUA271C, **V**): Z starts at body + 0.8 mm ("0.4 mm toe length beyond the package body"). The pad is ≥ 0.1 mm longer than the terminal at the toe and extends 0.05 mm toward the centre (heel). Pad width is ≥ terminal width + 0.05, but ≤ 0.28 mm at 0.5 mm pitch. Centre pad to lead pad is ≥ 0.2 mm. Broadcom (**V**): extend pads ≥ 0.1 mm outside and 0.05 mm inside, EP land ≥ die-flag size, EP-to-pad clearance 0.15 mm.

### 3.14 LQFP / TQFP (JEDEC MS-026)
```python
QFP_MS026 = {  # HD/HE = lead span (both axes), D/E = body, b, Lp (foot), A max
 "LQFP-32 7x7 P0.8":   dict(HD=(8.85,9.15), D=(6.9,7.1), b=(0.30,0.40), Lp=(0.45,0.75), A_max=1.60, A2=(1.35,1.45), A1=(0.05,0.15), src="NXP SOT358-1 via KiCad V*"),
 "LQFP-44 10x10 P0.8": dict(HD_nom=12.00, D_nom=10.00, b=(0.30,0.45), Lp=(0.45,0.75), A_max=1.60, src="MS-026 BCB via KiCad V* (BSC; tol U)"),
 "LQFP-48 7x7 P0.5":   dict(HD_nom=9.00, D_nom=7.00, b=(0.17,0.27), Lp=(0.45,0.75), A_max=1.60, src="MS-026 BBC via KiCad V*; HD tol ±0.20 assumed U"),
 "LQFP-64 10x10 P0.5": dict(HD=(11.8,12.2), D=(9.8,10.2), b=(0.17,0.27), Lp=(0.45,0.75), A_max=1.60, src="ADI AD7606 via KiCad V*"),
 "LQFP-100 14x14 P0.5":dict(HD=(15.75,16.25), D=(13.9,14.1), b=(0.17,0.27), Lp=(0.45,0.75), A_max=1.60, src="NXP SOT407-1 via KiCad V*"),
 "LQFP-144 20x20 P0.5":dict(HD_nom=22.00, D_nom=20.00, b=(0.17,0.27), Lp=(0.45,0.75), A=(1.40,1.60), src="MS-026 BFB via KiCad V*"),
 "TQFP-32 7x7 P0.8":   dict(HD_nom=9.00, D_nom=7.00, b=(0.30,0.45), Lp=(0.45,0.75), A_max=1.20, A2=(0.95,1.05), src="MS-026 ABA via KiCad V*"),
 "TQFP-44 10x10 P0.8": dict(HD_nom=12.00, D_nom=10.00, b=(0.30,0.45), Lp=(0.45,0.75), A=(1.00,1.20), src="MS-026 ACB via KiCad V*"),
 "TQFP-48 7x7 P0.5":   dict(HD_nom=9.00, D_nom=7.00, b=(0.17,0.27), Lp=(0.45,0.75), A=(1.00,1.20), src="MS-026 ABC via KiCad V*"),
 "TQFP-100 14x14 P0.5":dict(HD_nom=16.00, D_nom=14.00, b=(0.17,0.27), Lp=(0.45,0.75), A=(1.00,1.20), src="MS-026 AED via KiCad V*"),
}
# Height classes (JEITA EDR-7314A as quoted in KiCad lssop... yaml, V*): LSSOP 1.70, TSSOP 1.20, VSSOP 1.00, WSSOP 0.80 (A max)
```
The naming PDF's family split (pcb-3d version): QFP = height > 1.6, TQFP = height ≤ 1.6 (**V\***). The official 2010 PDF only lists `QFP` (**V**).

### 3.15 BGA (basic)
Ball/pitch/land data are in section 2.1. Body sizes and ball maps are per device. Courtyard excess 2.0/1.0/0.5 (**V\***). JEDEC pitches used: 1.27, 1.0, 0.8, 0.75, 0.65, 0.5, 0.4 (**V\***, Table 14-4 image). Altium BGA wizard inputs (**V**, AD22 template): `Dmin Dmax D1ave Emin Emax E1ave A1min A1max A2min A2max Amin Amax Bnom PitchD PitchE GridType MatrixType Rows Columns …`.

### 3.16 Through-hole packages
```python
DIP_MS001_300mil = dict(pitch=2.54, row=7.62,
                        # JEDEC MS-001 (web-search summary of a MS-001 drawing, V*): b, b1, E1, A, L
                        b=(0.36,0.56), b1_shoulder=(1.14,1.78), E1_body=(6.10,7.11), A_max=5.33, L_tip_to_seat=(2.92,3.81),
                        # Power Integrations DIP-8, 'conform to JEDEC MS-001-AB' (S24, V): letters A,B,C,G,H,J1,J2,K,N,P
                        pi=dict(body_len=(9.32,9.83), body_wid=(6.10,6.60), body_h=(3.18,3.68), standoff=(0.38,1.02), tip_to_seat=(3.05,3.56),
                                b1_shoulder=(1.45,1.73), b=(0.36,0.56), c=(0.20,0.38), row_at_shoulder=(7.62,8.13), row_at_tips=(7.62,9.91), row_bsc=7.62),
                        # from memory of Microchip/TI MS-001 drawings, UNVERIFIED:
                        E_shoulders_U=(7.62,8.26), eB_max_U=10.92, D8_U=(9.02,10.16))
AXIAL_RESISTOR = {  # L/D/d = Yageo CFR carbon-film datasheet values (S26, V): CFR-12 / CFR-25 / CFR-50 / CFR100;
                    # assigning them to DIN sizes is my approximation (U). KiCad DIN body & drill (S5, V).
 "DIN0204": dict(L=(2.9,3.7), D=(1.5,2.1), d=(0.45,0.55), yageo="CFR-12 1/8W", kicad=dict(L=3.6, D=1.6, drill=0.7, pitches=(5.08,7.62))),
 "DIN0207": dict(L=(5.8,6.8), D=(2.0,2.6), d=(0.55,0.65), yageo="CFR-25 1/4W", kicad=dict(L=6.3, D=2.5, drill=0.8, pitches=(7.62,10.16,15.24))),
 "DIN0309": dict(L=(8.5,9.5), D=(2.7,3.7), d=(0.55,0.65), yageo="CFR-50 1/2W", kicad=dict(L=9.0, D=3.2, drill=0.8, pitches=(12.7,15.24,20.32,25.4))),
 "DIN0411": dict(kicad=dict(L=9.9, D=3.6, drill=1.2, pitches=(12.7,15.24,20.32,25.4)), status="U body tol"),
 "DIN0414": dict(L=(10.5,12.5), D=(4.0,5.0), d=(0.75,0.85), yageo="CFR100 1W", kicad=dict(L=11.9, D=4.5, drill=1.2, pitches=(15.24,20.32,25.4))),
}
RADIAL_ECAP = {  # Panasonic FR-A (S25, V): D ±0.5, lead d ±0.05, F (lead spacing) ±0.5, L ±1.5 (L<=16) / ±2.0 (L>=20)
 5.0: dict(F=2.0, d=0.5), 6.3: dict(F=2.5, d=0.5), 8.0: dict(F=3.5, d=0.6), 10.0: dict(F=5.0, d=0.6),
 12.5: dict(F=5.0, d=0.6, d_if_L_30_35=0.8), 16.0: dict(F=7.5, d=0.8),
 4.0: dict(F=1.5, d=0.45, status="U"), 18.0: dict(F=7.5, d=0.8, status="U (KiCad has 0.8/0.9)"), 20.0: dict(F=7.5, d=0.8, status="KiCad V*")}
TO92_SOT54 = dict(A_body=(5.0,5.2), b=(0.40,0.48), b1=(0.55,0.66), c=(0.38,0.45), D=(4.4,4.8), d_flat_to_lead=(1.4,1.7), E=(3.6,4.2),
                  e=2.54, e1=1.27, L=(12.7,14.5), L1_max=2.5, src="Nexperia SOT54 (TO-92/SC-43A) (S20) V")
TO220AB_SOT78 = dict(A=(4.1,4.7), A1_tab=(1.25,1.40), b=(0.6,0.9), b1=(1.0,1.6), b2=(1.0,1.3), c=(0.4,0.7), D=(15.2,16.0), D1_tab=(5.9,6.6),
                     E=(9.7,10.3), e=2.54, L=(12.8,15.0), L1=(2.79,3.30), L2_max=3.0, p_hole=(3.5,3.8), q=(2.7,3.0), Q=(2.2,2.6),
                     src="Nexperia SOT78 '3-lead TO-220AB' (S20) V")
PIN_HEADER = {  # KiCad data (S5, V*) -- square post size, body (plastic) height, post length above body; KiCad drill/pad (V, published)
 2.54: dict(post=0.64, body_h=2.54, post_above=6.0, kicad_drill=1.0, kicad_pad=1.7, src="Wurth 6130xx11121"),
 2.00: dict(post=0.50, body_h=1.8,  post_above=4.2, kicad_drill=0.8, kicad_pad=1.35),
 1.27: dict(post=0.40, body_h=1.0,  post_above=4.0, kicad_drill=0.65, kicad_pad=1.0, src="Harwin M50-353"),
}
```

---

## 4. Naming convention

### 4.1 IPC-7351B (official 2010 IPC/Mentor PDF, S1, **V** — transcribed verbatim)
Number formatting rules (verbatim):
- "All dimensions are in Metric Units"
- "All Lead Span and Height numbers go two places past the decimal point and 'include' trailing Zeros"
- "All Lead Span and Body Sizes go two place before the decimal point and 'remove' leading Zeros"
- "All Chip Component Body Sizes are one place to each side of the decimal point"
- "Pitch Values are two places to the right & left of decimal point with no leading Zeros but include trailing zeros"
- "_ (underscore) is the separator between pin Qty in Hidden & Deleted pin components"; "– (dash) is used to separate the pin qty"; "X … instead of the word 'by'".
- Suffix (last character): "M … Most Material Condition (Level A); N … Nominal (Level B); L … Least (Level C)". BGA has no suffix. "A/B … Alternate Component", "-20RN reverse pin order", "-20_24N hidden pins", "-24_20N deleted pins", "_HS heat sink (TO254P1055X160_HS-6N)", "_BEC / _SGD / _213 pin assignment (SOT95P280X160_BEC-3N)".

```python
IPC7351B_NAME_FORMATS = {   # V (S1)
 "BGA":     "BGA + Pin Qty + C or N + Pitch P + Ball Columns X Ball Rows _ Body Length X Body Width X Height",
 "CAPC":    "CAPC + Body Length + Body Width X Height",          "CAPCP": "CAPCP + Body Length + Body Width X Height",
 "CAPM":    "CAPM + Body Length + Body Width X Height",          "CAPMP": "CAPMP + Body Length + Body Width X Height",
 "CAPAE":   "CAPAE + Base Body Size X Height",
 "RESC":    "RESC + Body Length + Body Width X Height",          "RESM": "RESM + Body Length + Body Width X Height",
 "RESMELF": "RESMELF + Body Length + Body Diameter",             "DIOMELF": "DIOMELF + Body Length + Body Diameter",
 "INDC":    "INDC + Body Length + Body Width X Height",          "INDM": "INDM + Body Length + Body Width X Height",
 "INDP":    "INDP + Body Length + Body Width X Height",          "DIOC": "DIOC + Body Length + Body Width X Height",
 "DIOM":    "DIOM + Body Length + Body Width X Height",          "LEDM": "LEDM + Body Length + Body Width X Height",
 "FUSM":    "FUSM + Body Length + Body Width X Height",          "XTAL": "XTAL + Body Length X Body Width X Height",
 "DFN":     "DFN + Body Length X Body Width X Height – Pin Qty",
 "QFN":     "QFN + Pitch P + Body Width X Body Length X Height - Pin Qty + Thermal Pad",
 "PQFN":    "PQFN + Pitch P + Body Width X Body Length X Height - Pin Qty + Thermal Pad",
 "SON":     "SON + Pitch P + Body Width X Body Length X Height - Pin Qty + Thermal Pad",
 "PSON":    "PSON + Pitch P + Body Width X Body Length X Height - Pin Qty + Thermal Pad",
 "QFP":     "QFP + Pitch P + Lead Span L1 X Lead Span L2 Nominal X Height - Pin Qty",
 "SOIC":    "SOIC127P + Lead Span Nominal X Height - Pin Qty",
 "SOP":     "SOP + Pitch P + Lead Span Nominal X Height - Pin Qty",
 "SOJ":     "SOJ + Pitch P + Lead Span Nominal X Height - Pin Qty",
 "SOD":     "SOD + Lead Span Nominal + Body Width X Height",     # example: SOD3717X135 = JEDEC SOD123
 "SODFL":   "SODFL + Lead Span Nominal + Body Width X Height",
 "SOTFL":   "SOTFL + Pitch P + Lead Span Nominal X Height - Pin Qty",
 "SOT":     "SOT + Pitch P + Lead Span Nominal X Height - Pin Qty",  # SOT23 & SOT223 (example: SOT230P700X180-4)
 "SOT89":   "SOT89",  "SOT143": "SOT143 & SOT343", "SOT143R": "SOT143R & SOT343R",   # JEDEC standard package names
 "TO":      "TO + Pitch P + Lead Span X Height - Pin Qty",       # Generic DPAK, example: TO228P970X238-3
 "DIP_SMT": "DIP + Pitch P + Lead Span Nominal X Height - Pin Qty",   # butt-mount DIP
 "LGA":     "LGA + Pin Qty + C/S/R + Pitch P + Pin Columns X Pin Rows _ Body Length X Body Width X Height",
}
IPC7351_ZERO_ORIENTATION = {  # V (S1 p.5)
 "chip RES/CAP/IND, molded INDM/RESM/CAPMP, precision wire-wound, CAPAE": "Pin 1 (positive) on left",
 "MELF diode, SOD diodes": "Pin 1 (cathode) on left",
 "SOT (SOT23, SOT23-5, SOT223, SOT89, SOT143), TO252/TO263, SOIC/SOP/TSOP/SSOP/TSSOP, CFP, SOJ, QFP, QFN, LCCS": "Pin 1 upper left",
 "PLCC, LCC, BQFPC/PQFPC (pin 1 centre)": "Pin 1 top centre", "BGA": "Pin A1 upper left"}
```
Formatter (my implementation of the rules; examples from S1 are **V**, the others **U** as illustrations):
```python
def f2(v):  return str(int(round(v * 100)))      # 2 decimals, no point, no leading zeros: 6.00 -> "600", 0.95 -> "95"
def f1(v):  return str(int(round(v * 10))).zfill(2)  # chip body "one place each side": 1.6 -> "16", 0.8 -> "08"
# RESC1608X55N (0603, H max 0.55) ; CAPC2012X145N ; CAPMP3216X180N (Ta A) ; SOIC127P600X175-8N ; SOP65P640X120-16N (TSSOP16)
# SOP65P490X110-8N (MSOP8) ; QFP50P900X900X160-48N (LQFP48) ; SOT95P280X145-5N (SOT-23-5) ; SOT230P700X180-4N (SOT-223, S1 example)
# TO228P970X238-3N (DPAK, S1 example) ; SOD3717X135N (SOD-123, S1 example) ; QFN50P300X300X100-17N (QFN16+EP: '-Pin Qty + Thermal Pad', U)
# BGA256C100P16X16_1700X1700X200 (no density suffix)
```
Height uses the **maximum** package height and lead span uses the **nominal** (e.g. SOIC127P600X175: span 6.00 nominal, A max 1.75; SOT230P700X180: SOT-223 A max 1.80) (**V** against package data).
Known flaws (Tom H, TID 2336, **V\***): names can collide because they omit the terminal length/width, the thermal-tab size, the BGA ball size and the SOIC body length. PCB Libraries' extended scheme appends `L<len>X<wid>`, `T<tab>`, `B<ball>`, e.g. `QFN25P40_400X300X80L40X20T265X165`, `BGA49CP80_7X7_700X700X155B50`, `CAPC320X250X120L50`. **Recommendation:** store the IPC name as an attribute and keep a unique internal footprint ID.

### 4.2 Through-hole (IPC-7251 draft naming, via pcb-3d.com, S12, **V\***)
Body identifiers: P = pitch, W = max lead width/diameter, L = body length, D = body diameter, T = body thickness, H = height, Q = pin qty, R = rows; final A/B/C = producibility level. Values are given with 2 decimals, without point or leading zero.
```python
IPC7251_NAME_FORMATS = {
 "DIP":    "DIP + Lead Span + W Lead Width + P Pin Pitch + L Body Length + H Component Height + Q Pin Qty",
 "RESAD":  "RESAD + Lead Spacing + W Lead Width + L Body Length + D Body Diameter",       # axial horizontal (RESADV vertical)
 "DIOAD":  "DIOAD + Lead Spacing + W Lead Width + L Body Length + D Body Diameter",
 "CAPPRD": "CAPPRD + Lead Spacing + W Lead Width + D Body Diameter + H Body Height",      # polarized radial
 "CAPRD":  "CAPRD + Lead Spacing + W Lead Width + D Body Diameter + H Body Height",
 "HDRV":   "HDRV + total Pins + W Lead Width + P Row Pitch (+ X Column Pitch) + _ Rows X Pins per Row + _ Body Length X Body Thickness X Component Height",
 "HDRRA":  "HDRRA + … (right angle, same fields)",
 "TO":     "TO-JEDEC Standard Code (transistor outlines, e.g. TO92 / TO220AB)",   # exact format U
 "PAD":    "C + Pad Diameter + H + Hole Diameter (round), S… (square), e.g. C150H90",
}
# examples (U, illustrations): DIP762W56P254L958H533Q8B ; RESAD1016W65L630D250B ; CAPPRD200W55D500H1100B ; HDRV10W64P254_1X10_2540X254X854B
```

---

## 5. Silkscreen, assembly, courtyard drawing rules; Altium layer usage

| Rule | Value | Status / source |
|---|---|---|
| IPC silkscreen line width | 0.12 mm nominal. 3-tier: L 0.10 / N 0.12 / M 0.15 (4/5/6 mil) | **V\*** (Tom H TID 1465: "IPC uses 0.12 mm (5 mil) … line width and clearance are 0.12 mm"; Sierra Circuits article) |
| IPC silk-to-pad clearance | = line width (0.12 nominal); silk must stay inside the courtyard | **V\*** (same) |
| KLC silk | width 0.12 (0.10 to 0.15 allowed); clearance to exposed copper 0.2 recommended and ≥ max(line width, mask expansion); no silk under SMD bodies; pin-1 mark on silk (filled chevron ▶ preferred; 0.25 mm dot for tiny parts; `+` for SMD caps; ⊔ shape for SMD diodes); ≥ 0.5 mm from board edge | **V** (KLC F5.1) |
| KLC RefDes on silk | text 1.00 mm, thickness 0.15 mm | **V** |
| Fab/assembly outline | nominal body outline, line 0.10 (0.10 to 0.15); pin-1 bevel = min(1 mm, 25 % of package size); second RefDes (`${REFERENCE}`) centred, 0.5 to 1.0 mm text, thickness about 15 % | **V** (KLC F5.2) |
| Courtyard | line 0.05, 0.01 mm grid, nominal body dimensions; polygonal courtyard allowed (IPC-7351C note) | **V** (KLC F5.3) |
| Solder mask | IPC calculator keeps pad and mask 1:1 and leaves mask swell to user rules; NSMD preferred for QFN (TI); copper-to-mask clearance 2.5 to 3 mil (Broadcom) | **V\*** / **V** |
| Altium IPC Footprint Wizard defaults | Courtyard → **Mechanical 15**, line 0.05; Assembly → **Mechanical 13**, line 0.1; Component Body (3D) → **Mechanical 13** | **V\*** (pcb-3d tutorial) |
| Altium layer types (AD22) | component layer pairs with types **Assembly, Courtyard, 3D Body, Designator (.Designator), Value (.Comment), Component Center, Component Outline**, Coating, Glue Points, Gold Plating; single-layer types include Board Shape, Dimensions, Fab Notes, Assembly Notes, Route Tool Path, Sheet. When a footprint is placed or copied, layers are matched **by Layer Type first, then by layer number** | **V** (Altium AD22 "Working with Mechanical Layers") |

**Recommendation:** configurable mapping, e.g. `{"courtyard": ("Courtyard", 15), "assembly": ("Assembly", 13), "body3d": ("3D Body", 13), "designator": ("Designator", None)}`. Assign the Layer Types in generated PcbLibs. The concrete numbers must match the user's existing library style (see the other research tracks; numbers are **U** for this user).

---

## 6. Through-hole rules

```python
TH_RULES = {
 # IPC-2222 Table 9-3 (hole vs lead): min hole = max lead (diagonal for rect leads) + {A:0.25,B:0.20,C:0.15};
 #                                    max hole = min lead + {A:0.70,B:0.70,C:0.60}          V* (JITX 'IPC 2222 Table 9-3'; pcb-3d)
 "hole_allow_min": {"A": 0.25, "B": 0.20, "C": 0.15},
 "hole_allow_max": {"A": 0.70, "B": 0.70, "C": 0.60},
 # IPC-2221 9.1.1: land_min = hole + 2*annular_ring_min + fabrication_allowance (Table 9-1)   V* (pcb-3d; forum quote of IPC-2221B 9.1.1)
 "fab_allowance": {"A": 0.60, "B": 0.50, "C": 0.40},          # IPC-2221 Table 9-1 'Minimum Standard Fabrication Allowance for Interconnection Lands' (title V via IPC-2221B TOC)
 "annular_ring_min": {"external": 0.05, "internal": 0.025},  # V* (Tom H TID 2586; pcb-3d)
 # Practice/alternatives
 "pcbl_defaults": {"round_lead_plus": 0.20, "rect_lead_diag_plus": 0.15, "pad_to_hole_ratio": 1.5, "slot_pad_ratio": 1.8,
                   "hole_tol_typ": 0.075, "antipad_ring": 0.35},   # V* (TID 2586)
 "ipc7351C_proposal": "pad = max(hole + 2*AR_min(0.2), hole*pad_to_hole_ratio)",   # V* (TID 1798) -- IPC-7251 never published (TID 1463)
 "drill_roundoff": 0.05,   # fabs use 0.05 mm drill steps (forum users, V*); configurable
}
```
Computed IPC values against KiCad conventions (**V** arithmetic; KiCad values **V** from published footprints):

| Case | Lead (max, diag.) | Hole A/B/C | Pad (A/B/C) = hole + 0.1 + {0.6,0.5,0.4} | KiCad drill / pad |
|---|---|---|---|---|
| Pin header 2.54 (0.64 sq) | 0.905 | 1.155 / 1.105 / 1.055 | 1.855 / 1.705 / 1.555 | 1.0 / 1.7 |
| Pin header 2.00 (0.50 sq) | 0.707 | 0.957 / 0.907 / 0.857 | 1.657 / 1.507 / 1.357 | 0.8 / 1.35 |
| Pin header 1.27 (0.40 sq) | 0.566 | 0.816 / 0.766 / 0.716 | 1.516 / 1.366 / 1.216 (**> pitch → clamp**) | 0.65 / 1.0 |
| DIP (0.56 × 0.38) | 0.677 | 0.927 / 0.877 / 0.827 | 1.627 / 1.477 / 1.327 | 0.8 / 1.6 (long pads 2.4 × 1.6) |
| Axial 0207 (Ø0.65) | 0.65 | 0.90 / 0.85 / 0.80 | 1.60 / 1.45 / 1.30 | 0.8 / 1.6 (KiCad pad = 2 × drill) |
| TO-220 (0.9 × 0.7) | 1.140 | 1.39 / 1.34 / 1.29 | 2.09 / 1.94 / 1.79 | 1.1 / 1.905 × 2.0 oval |
| TO-92 (0.48 × 0.45) | 0.658 | 0.908 / 0.858 / 0.808 | 1.608 / 1.458 / 1.308 (inline 1.27 → clamp/oval) | 0.75 / 1.05 × 1.5 oval (inline); 0.75 / 1.3 (triangle, pin 2 at (1.27, −1.27)) |
| E-cap D5 (Ø0.55) | 0.55 | 0.80 / 0.75 / 0.70 | 1.50 / 1.35 / 1.20 | 0.8 / 1.6 ; D10 P5: 1.0 / 2.0 |

Implementation notes: clamp the pad to `pitch − min_copper_gap`, or switch to an oblong pad. Pin 1 is square or rectangular, the rest round or oval (KiCad convention, **V**).

---

## 7. Exposed / thermal pad paste windowing

| Topic | Value | Status / source |
|---|---|---|
| EP paste coverage | 50 % to 70 % of pad area | **V** TI SLUA271C §4.4 ("Typically, the solder-paste coverage is approximately 50% to 70%") |
| | 60 % to 85 %, multiple small openings instead of one, rounded corners, positive taper; 91 % not recommended, 77 % and 65 % recommended | **V** Broadcom QFN SMT requirements |
| | KiCad default `EP_paste_coverage = 0.65` | **V** (no_lead/footprint.py `DEFAULT_PASTE_COVERAGE = 0.65`) |
| Why | 1:1 aperture "results in excessive metal volume that can 'float' the part"; voiding ≤ 50 % (TI), 25 % point of diminishing returns | **V** TI |
| Lead fingers | stencil 1:1, or reduce by 20 % at ≤ 0.5 mm pitch; 0.4 mm pitch → 0.2 mm pad width | **V** TI |
| Stencil | thickness 0.100 to 0.150, typically 0.125 for 0.5 mm pitch; area ratio > 0.66 (laser), down to 0.57 (Ni-formed); aspect ratio > 1.5 (IPC-7525) | **V** TI |
| Thermal vias | Ø 0.30 to 0.33 at 1.0 to 1.2 mm pitch | **V** Broadcom; KiCad typical drill 0.2 (**V**, data) |
| EP to signal pad clearance | ≥ 0.2 (TI, KiCad); 0.15 (Broadcom) | **V** |
| EP land size | ≥ exposed die-flag size (Broadcom); usually the datasheet EP nominal | **V** |

KiCad window algorithm (**V**, `KicadModTree/nodes/specialized/ExposedPad.py`, re-expressed):
```python
def ep_paste_windows(ep_w, ep_h, nx, ny, coverage=0.65, round_base=0.01):
    r = coverage ** 0.5
    w = round((ep_w * r / nx) / round_base) * round_base   # window size
    h = round((ep_h * r / ny) / round_base) * round_base
    pitch_x, pitch_y = ep_w / nx, ep_h / ny                 # each window centred in an equal cell
    centers = [(-ep_w/2 + pitch_x*(i+0.5), -ep_h/2 + pitch_y*(j+0.5)) for i in range(nx) for j in range(ny)]
    return w, h, centers
# KiCad grid choice in data: EP~1.7 -> 2x2, 3.3-3.5 -> 3x3, 5.6 -> 4x4, 7.15 -> 5x5 (V*); vias: paste avoids via drill + 0.1 clearance
# Example: EP 1.75 2x2 65% -> windows 0.71 (web 0.165); EP 2.6 2x2 -> 1.05 (web 0.25); EP 3.45 3x3 -> 0.93 (web 0.22); EP 5.6 4x4 -> 1.13 (web 0.27)
```
**Recommendation:** choose `n = ceil(EP / 1.5 mm)` per axis (**U** heuristic), target 65 %, and require web ≥ 0.2 mm.

---

## 8. Typical body heights for extruded 3D bodies

IPC names use the **max** height. For 3D: `overall_height` = nominal (appearance) or max (collision checks) — make it selectable. `standoff` = A1 (0 for chips, MELF, QFN).
```python
HEIGHT_3D = {  # (nominal, max) mm ; status
 "R_01005": (0.13,0.15), "R_0201": (0.23,0.26), "R_0402": (0.35,0.40), "R_0603": (0.45,0.50), "R_0805": (0.50,0.60),
 "R_1206": (0.55,0.60), "R_1210": (0.55,0.60), "R_2010": (0.60,0.70), "R_2512": (0.60,0.70),          # Vishay CRCW, V
 "R_1812": (0.60,0.70),                                                                                  # U
 "C_0402": (0.50,0.55), "C_0603": (0.80,0.87), "C_0805": (1.25,1.45), "C_1206": (1.60,1.80),
 "C_1210": (2.50,2.80), "C_1812": (2.50,2.70),   # KEMET thickest codes, V (value dependent: 0805 0.70..1.25, 1206 0.78..1.60 nominal)
 "C_0201": (0.30,0.33), "C_01005": (0.20,0.22),  # U
 "L_chip": "use MLCC height of same size (U)",
 "Ta_A": (1.6,1.8), "Ta_B": (1.9,2.1), "Ta_C": (2.5,2.8), "Ta_D": (2.8,3.1),                            # KEMET T491, V
 "MicroMELF": (1.1,1.1), "MiniMELF_0204": (1.4,1.4), "MiniMELF_SOD80": (1.45,1.60), "MELF_0207": (2.2,2.2), "MELF_DO213AB": (2.5,2.6),  # = diameter, V
 "SOD-123": (1.05,1.35), "SOD-123F": (1.1,1.2), "SOD-323": (0.95,1.10), "SOD-523": (0.60,0.65), "SOD-923": (0.40,0.43),  # V (SOD-923 U)
 "SMA": (2.18,2.40), "SMB": (2.25,2.50), "SMC": (2.25,2.50),                                             # Diodes, V
 "SOT-23": (1.0,1.1), "SOT-23-5/6": (1.15,1.45), "SC-70": (0.95,1.10), "SOT-523": (0.75,0.90), "SOT-89": (1.5,1.6), "SOT-223": (1.65,1.80),  # V
 "DPAK": (2.29,2.39), "D2PAK": (4.45,4.83),                                                              # Vishay JEDEC, V
 "SOIC": (1.55,1.75), "TSSOP": (1.00,1.20), "MSOP": (0.95,1.10), "SSOP_5.3": (1.85,2.00), "QSOP": (1.45,1.75),   # V/V*
 "VQFN": (0.90,1.00), "WQFN": (0.75,0.80), "UQFN": (0.55,0.60),                                          # V* / profile letters U
 "LQFP": (1.50,1.60), "TQFP": (1.10,1.20),                                                               # V*
 "DIP_300": dict(standoff=(0.38,1.02), body=(3.18,3.68), A_max=5.33),                                    # V (PI + JEDEC summary)
 "TO-92": dict(body_len_along_leads=(5.0,5.2), body_w=(4.4,4.8), body_depth=(3.6,4.2)),                 # V
 "TO-220": dict(body_thickness=(4.1,4.7), tab_thickness=(1.25,1.40), body_plus_tab=(15.2,16.0)),        # V
 "Header_2.54": dict(plastic=2.54, post_above=6.0), "Header_2.00": dict(plastic=1.8, post_above=4.2), "Header_1.27": dict(plastic=1.0, post_above=4.0),  # V*
 "Axial": "diameter D of the body (horizontal mounting)", "Radial_ecap": "L from datasheet (e.g. 5x11 -> 11.0) +0.5 sleeve (U)",
}
```

---

## 9. Worked examples (my reference implementation, F = 0.10, P = 0.05, round 0.05 or 0.02)
Computed by `scripts/ipc_examples.py` with the inputs of section 3 (**V** as computations, not official IPC output). Z/G/X in mm. Pad = `(Z−G)/2 × X @ ±(Z+G)/4` at density N.

| Package | IPC name (illustr.) | Table | Z/G/X M | Z/G/X N | Z/G/X L | Pad N |
|---|---|---|---|---|---|---|
| R 0402 (1005M) | RESC1005X40N | 3-6 | 1.70/0.42/0.70 | 1.50/0.42/0.60 | 1.30/0.42/0.50 | 0.540 × 0.60 @ 0.480 |
| R 0603 (1608M) | RESC1608X50N | 3-5 | 2.80/0.65/1.10 | 2.40/0.65/1.00 | 2.00/0.65/0.90 | 0.875 × 1.00 @ 0.763 |
| R 0805 (2012M) | RESC2012X60N | 3-5 | 3.30/1.10/1.50 | 2.90/1.10/1.40 | 2.50/1.10/1.30 | 0.900 × 1.40 @ 1.000 |
| R 1206 (3216M) | RESC3216X60N | 3-5 | 4.40/2.00/1.85 | 4.00/2.00/1.75 | 3.60/2.00/1.65 | 1.000 × 1.75 @ 1.500 |
| R 2512 (6332M) | RESC6332X70N | 3-5 | 7.60/4.75/3.40 | 7.20/4.75/3.30 | 6.80/4.75/3.20 | 1.225 × 3.30 @ 2.987 |
| C 0603 (1608M) | CAPC1608X87N | 3-5 | 2.85/0.65/1.05 | 2.45/0.65/0.95 | 2.05/0.65/0.85 | 0.900 × 0.95 @ 0.775 |
| C 0805 (2012M) | CAPC2012X145N | 3-5 | 3.30/0.60/1.55 | 2.90/0.60/1.45 | 2.50/0.60/1.35 | 1.150 × 1.45 @ 0.875 |
| Ta A 3216-18 | CAPMP3216X180N | 3-13 | 5.00/0.80/1.35 | 4.40/1.00/1.25 | 3.80/1.15/1.15 | 1.700 × 1.25 @ 1.350 |
| Ta D 7343-31 | CAPMP7343X310N | 3-13 | 9.20/3.65/2.55 | 8.60/3.85/2.45 | 8.00/4.05/2.35 | 2.375 × 2.45 @ 3.112 |
| MiniMELF 0204 | RESMELF3614N | 3-7 | 4.85/1.30/1.65 | 4.45/1.50/1.55 | 4.05/1.65/1.45 | 1.475 × 1.55 @ 1.488 |
| MELF 0207 | RESMELF5822N | 3-7 | 7.05/2.85/2.45 | 6.65/3.05/2.35 | 6.25/3.20/2.25 | 1.800 × 2.35 @ 2.425 |
| SMA DO-214AC | DIOM5226X240N | 3-13 | 7.20/1.75/1.65 | 6.60/1.95/1.55 | 6.00/2.10/1.45 | 2.325 × 1.55 @ 2.138 |
| SMB DO-214AA | DIOM5336X250N | 3-13 | 7.20/1.90/2.25 | 6.60/2.10/2.15 | 6.00/2.25/2.05 | 2.250 × 2.15 @ 2.175 |
| SMC DO-214AB | DIOM7959X250N | 3-13 | 9.75/4.60/3.20 | 9.15/4.80/3.10 | 8.55/4.95/3.00 | 2.175 × 3.10 @ 3.488 |
| SOD-123 | SOD3716X135N | 3-2 | 4.95/1.95/0.75 | 4.55/2.15/0.75 | 4.15/2.35/0.70 | 1.200 × 0.75 @ 1.675 |
| SOD-323 | SOD2513X110N | 3-2 | 3.80/0.70/0.55 | 3.40/0.90/0.50 | 3.00/1.10/0.45 | 1.250 × 0.50 @ 1.075 |
| SOD-123F | SODFL3516X120N | 3-22 | 4.25/2.40/0.85 | 4.05/2.40/0.75 | 3.85/2.40/0.65 | 0.825 × 0.75 @ 1.613 |
| SOT-23-3 (JEDEC) | SOT95P237X112-3N | 3-2 | 3.75/0.15/0.65 | 3.35/0.35/0.60 | 2.95/0.55/0.55 | 1.500 × 0.60 @ 0.925 |
| SOT-23-5/6 (TI DBV) | SOT95P280X145-5N | 3-2 | 4.10/0.70/0.65 | 3.70/0.90/0.60 | 3.30/1.10/0.55 | 1.400 × 0.60 @ 1.150 |
| SC-70 (SOT-323/363) | SOT65P210X110-6N | 3-2 | 3.35/0.35/0.45 | 2.95/0.55/0.40 | 2.55/0.75/0.35 | 1.200 × 0.40 @ 0.875 |
| SOT-523 | SOT50P160X90-3N | 3-3 | 2.85/**−0.10**/0.35 | 2.45/0.10/0.30 | 2.05/0.30/0.25 | 1.175 × 0.30 @ 0.638 (clamp!) |
| SOT-223 leads | SOT230P700X180-4N | 3-2 | 8.40/3.90/0.95 | 8.00/4.10/0.90 | 7.60/4.30/0.85 | 1.950 × 0.90 @ 3.025 |
| SOIC-8 | SOIC127P600X175-8N | 3-2 | 7.30/2.80/0.65 | 6.90/3.00/0.60 | 6.50/3.20/0.55 | 1.950 × 0.60 @ 2.475 |
| TSSOP-16 | SOP65P640X120-16N | 3-2 | 7.70/4.00/0.45 | 7.30/4.20/0.40 | 6.90/4.40/0.35 | 1.550 × 0.40 @ 2.875 |
| MSOP-8 | SOP65P490X110-8N | 3-2 | 6.20/2.60/0.60 | 5.80/2.80/0.55 | 5.40/3.00/0.50 | 1.500 × 0.55 @ 2.150 |
| SSOP-20 5.3 | SOP65P780X200-20N | 3-2 | 9.30/4.90/0.50 | 8.90/5.10/0.50 | 8.50/5.30/0.45 | 1.900 × 0.50 @ 3.500 |
| LQFP-48 (±0.2 assumed) | QFP50P900X900X160-48N | 3-3 | 10.30/6.60/0.35 | 9.90/6.80/0.30 | 9.50/7.00/0.25 | 1.550 × 0.30 @ 4.175 |
| LQFP-100 | QFP50P1600X1600X160-100N | 3-3 | 17.35/13.55/0.35 | 16.95/13.75/0.30 | 16.55/13.95/0.25 | 1.600 × 0.30 @ 7.675 |
| QFN-32 5x5 | QFN50P500X500X80-33N | 3-15 | 5.95/4.00/0.25 | 5.75/4.00/0.25 | 5.55/4.00/0.25 | 0.875 × 0.25 @ 2.438 (+EP rule) |

(The full list, including 01005, 0201, 1210, 2010, MLCC 0402/1206/1210/1812, Ta B/C, MicroMELF, SOD-80, SOD-523, MSOP-10 and LQFP-32, is in `ipc-work/examples.md`.)

---

## 10. Open questions, risks, flags

1. **IPC-7351B primary text not accessed** (paywalled). The J-tables, the S-RMS variant, F/P guidance and courtyard values rest on KiCad and JITX transcriptions plus statements by the IPC committee chair (**V\***). Tables 3-7, 3-9 to 3-12, 3-14 and 3-22 come from JITX only. Table 3-18 (pull-back) values are **U**.
2. **Round-off:** KiCad uses 0.05 and 0.02 (nearest, half-even); PCB Libraries says 0.01. The exact 7351B table row text and the courtyard round-off rule are **U**. Default to 0.01 and keep a KiCad-compatible mode.
3. **F/P:** 0.10 and 0.05 are a convention, not normative.
4. **SOT-23 foot length** differs between data sets: JEDEC per KiCad master 0.40–0.60, the published KiCad footprint implies 0.30–0.60, Nexperia Lp 0.15–0.45, IPC-SM-782A T 0.45–0.60.
5. **LQFP/TQFP and TSSOP spans** are BSC in JEDEC/KiCad, so the tolerance must be supplied: ±0.15 (NXP), ±0.2 (TI/ADI); TSSOP HE 6.2–6.6 (Nexperia).
6. **SOD-923, MLCC 0201/01005, 1812 resistor, D4/D18 radial caps, DIN0411 body tolerance, JEDEC MO-178 full table** are **U** or weakly sourced.
7. **Family-to-table mapping** for DPAK/D2PAK tab (flat lug?), SOT-89 (flat lead?) and SOD-923 is **U**.
8. **Altium:** per Tom H, Altium's IPC wizard follows IPC-7351 (2005), so its chip heel is −0.05. Expect differences against Altium wizard output (**V\***).
9. **Licences:** KiCad generator is GPL/LGPL/MIT-mixed and JITX is proprietary. Re-implement from the formulas (as in `ipc7351b_ref.py`); transcribe numeric facts only.
10. Small-package clamping (G ≤ 0, pad > pitch) is not covered by IPC. Implement explicit DRC-style limits.

---

## 11. Sources (all accessed 2026-10-07)
- S1 IPC-7351B Naming Convention (© 2010 IPC & Mentor Graphics), Wayback: https://web.archive.org/web/2016id_/http://landpatterns.ipc.org/IPC-7351BNamingConvention.pdf (linked from https://wiki.epfl.ch/pcb/ipc-7351b-naming-convention)
- S2 IPC-7351B TOC/preview: https://www.electronics.org/TOC/IPC-7351B.pdf ; IPC-7351 (2005) TOC https://www.ipc.org/TOC/IPC-7351.pdf ; IPC-7351A TOC https://www.electronics.org/TOC/IPC-7351A.pdf
- S3 IPC-7352 TOC (May 2023): https://www.ipc.org/TOC/IPC-7352-TOC.pdf
- S4 IPC-SM-782A (Dec 1999, amendments 1 & 2), Wayback of pcb-3d.com: https://web.archive.org/web/2019id_/https://www.pcb-3d.com/wordpress/wp-content/uploads/ipc-sm-782a_amendment_1_and_2.pdf
- S5 KiCad footprint generator, commit 6ef6869 (2026-10-05): https://gitlab.com/kicad/libraries/kicad-footprint-generator (`src/kilibs/config/ipc_configs/*.yaml`, `src/generators/tools/footprint/ipc_pad_size_calculators.py`, `src/kilibs/util/toleranced_size.py`, `src/kilibs/config/global_configs/config_KLCv3.0.yaml`, `data/**`, `KicadModTree/nodes/specialized/ExposedPad.py`)
- S6 KiCad published footprints (raw): https://gitlab.com/kicad/libraries/kicad-footprints/-/raw/master/<lib>.pretty/<fp>.kicad_mod
- S7 KiCad Library Conventions F5.1–F5.3: https://gitlab.com/kicad/libraries/klc (content/footprint/F5/*.adoc)
- S8 JITX jitxlib-standard 4.4.0 wheel (PyPI): https://pypi.org/project/jitxlib-standard/ (`landpatterns/leads/protrusions.py`, `ipc.py`, `courtyard.py`, `pads.py`) ; docs https://docs.jitx.com/en/latest/jitxlib-standard/jitxlib.landpatterns.ipc.html
- S9 KiCad forum (J. Beard, 2025-07-30): https://forum.kicad.info/t/capacitor-1206-footprint-correct-for-the-parts-i-will-be-using/62938/10
- S10 PCB Libraries forum (printer-friendly): https://www.pcblibraries.com/forum/printer_friendly_posts.asp?TID= {785, 1314, 1905, 3060, 2509, 2866, 3415, 1465, 2586, 1798, 1463, 2607, 1708, 3370, 2336, 3636, 2590, 3645} ; BGA images under https://www.pcblibraries.com/forum/uploads/5302/ and /uploads/3/
- S11 SnapEDA blog: https://blog.snapeda.com/?p=488
- S12 pcb-3d.com tutorials: IPC-7351B naming https://www.pcb-3d.com/wordpress/tutorials/ipc-7351b-naming-convention-for-surface-mount-device-3d-models-and-footprints/ ; IPC-7251 naming …/ipc-7251-naming-convention-for-through-hole-3d-models-and-footprints/ ; PTH calc …/how-to-calculate-pth-hole-and-pad-diameter-sizes-according-to-ipc-7251-ipc-2222-and-ipc-2221-standards/ ; IPC wizard part 2 …/create-a-footprint-using-ipc-compliant-footprint-wizard-part-2/
- S13 Altium docs: IPC Compliant Footprint Wizard (AD22) https://altium.com/documentation/node/264411/printable/print?version=22 ; Mechanical layers (AD22) https://www.altium.com/documentation/altium-designer/pcb/mechanical-layers?version=22
- S14 Local AD22 install (read-only): `C:/ProgramData/Altium/Altium Designer {A102241D-…}/Extensions/IPC Footprint Generator/Templates/*.xls` (batch-generator column schemas)
- S15 Vishay D/CRCW e3 doc 20035 (rev 14-Apr-2026) https://www.vishay.com/docs/20035/dcrcwe3.pdf ; CRCW0201 e3 https://www.vishay.com/docs/20052/crcw0201e3.pdf ; CRCW01005 e3 https://www.vishay.com/docs/20056/crcw01005e3.pdf
- S16 KEMET/YAGEO C1002 X7R (2026-09-01): https://content.kemet.com/datasheets/KEM_C1002_X7R_SMD.pdf
- S17 KEMET T491: https://content.kemet.com/datasheets/KEM_T2005_T491.pdf
- S18 Vishay MMU 0102/MMA 0204/MMB 0207 doc 28713 (copy): https://static.chipdip.ru/lib/162/DOC011162240.pdf
- S19 Diodes Inc. package outlines: https://www.diodes.com/assets/Package-Files/{SMA,SMB,SMC,SOD123,SOD123F,SOD323,SOD523,SOT523,MiniMELF,MELF,SOT25,SOT26,SOT89,SOT223,SOT323,SOT363}.pdf
- S20 Nexperia outlines: https://assets.nexperia.com/documents/outline-drawing/{SOT23,SOT323,SOT363,SOT416,SOT89,SOT223,SOD123F,SOD323,SOD523,SOT753,SOT457,SOT96-1,SOT403-1,SOT505-1,SOT428,SOT404,SOT78,SOT54,SOT1220-2}.pdf
- S21 Vishay D-PAK (TO-252AA) doc 95627 https://www.vishay.com/docs/95627/d-pakto-252aa-m.pdf ; TO-263AB doc 91364 https://www.vishay.com/docs/91364/to263ab.pdf
- S22 TI SLUA271C "QFN and SON PCB Attachment" (Dec 2023): https://www.ti.com/lit/an/slua271b/slua271b.pdf
- S23 Broadcom "Surface Mount Requirements for QFN Package": https://docs.broadcom.com/doc/QFN_Surface_Mount_Requirements.pdf
- S24 Power Integrations Package Information (DIP-8 MS-001-AB): https://xdevs.com/doc/_Datasheets/Power_Integrations/Package%20Information.pdf
- S25 Panasonic FR-A series (28-Feb-20): https://sy-dep-epc-lpc.web.cern.ch/components/datasheets/epc-lpc%20(converters)/FR-Aluminium-Capacitor_Panasonic.pdf
- S26 Yageo CFR carbon film (via Reichelt): http://cdn-reichelt.de/documents/datenblatt/B400/1_4W%23YAG.pdf
- S27 FED excerpt IPC-2221A Table 10-3: https://www.mikrocontroller.net/attachment/30997/Seiten_aus_IPC-2221IPC-2222__FED-Designrichtlinie_.pdf ; S28 IPC-2221B TOC https://www.electronics.org/TOC/IPC-2221B.pdf
- S29 Sierra Circuits/ProtoExpress IPC-7351 article: https://www.protoexpress.com/blog/features-of-ipc-7351-standards-to-design-pcb-component-footprint/
- S30 TI DBV0005A dims (web-search summary of TI drawing; e2e/alldatasheet) — secondary; S31 SOD-923 (web-search summary of MCC/onsemi drawings) — UNVERIFIED
