# PartForge: Claude API integration guide for datasheet extraction

Research agent, UNDERSTAND phase, 2026-10-07. Every claim is tagged:
- **VERIFIED**: I ran or read it in this session.
- **DOC**: taken from the claude-api skill or the live docs at platform.claude.com, not tested here.
- **INFERRED**: derived from measurements, not documented.
- **UNVERIFIED**: an assumption or a proposal that has not been tested.

Work folder: `<scratchpad>/claude-api/`
(`scripts/` holds all code, `out/` holds the JSON results and metrics, and `.venv/` is the environment.)

Environment (**VERIFIED**): Python 3.13.5, anthropic **1.12.0** (runs on `httpx2` 2.13.1), pydantic 2.13.5, pypdf 6.19.0, pypdfium2 5.14.0, Pillow 12.3.0 (needed for `bitmap.to_pil()`), jiter 0.17.0 (an SDK dependency, used here for partial JSON parsing).
Total API spend for every test in this report: about **$0.76** (usage × list prices). count_tokens, the Models API and 400 responses cost nothing.

---

## 0. TL;DR (decisions for the implementation agents)

| Topic | Recommendation | Evidence |
|---|---|---|
| Default model | `claude-opus-5-5` at `output_config.effort = "low"` with `fallbacks="default"` (beta `server-side-fallback-2026-07-01`) | VERIFIED: 100 % correct on OPA656, first JSON after 2 s, done in 21 to 28 s, $0.14 to 0.18 per datasheet |
| Cheap / bulk / cross-check | `claude-haiku-5-5` (released 2026-10-07) at effort `low` or `medium`, **thinking left ON** | VERIFIED: 100 % correct at $0.007, but 39 to 49 s. With thinking disabled it misread one dimension and dropped 6 MPNs |
| Middle option | `claude-sonnet-5-5` at `low` | VERIFIED: correct but left out coplanarity, $0.08 to 0.09, 30 s |
| PDF transport | base64 `document` block holding a **pypdf page subset**: page 1, pin/ordering pages, package/land-pattern pages and pages without a text layer | VERIFIED: 7 of 25 pages = 14,627 instead of 63,474 tokens (−77 %) |
| Files API | only for PDFs reused across sessions; upload with `expires_in_seconds`, then delete | VERIFIED: round trip works with no beta header; `count_tokens` rejects file sources |
| Structured output | `output_config={"effort":..., "format":{"type":"json_schema","schema": anthropic.transform_schema(Model)}}`, then `Model.model_validate_json(text)` once `stop_reason == "end_turn"` | VERIFIED on 3 models, streaming and non-streaming |
| Schema rule | **no `float \| None` inside nested arrays.** Use the sentinel `-1` (or strings) | VERIFIED: the nullable version gets a 400 "compiled grammar is too large", the sentinel version compiles |
| Caching | `cache_control` on the document block. **The output schema is part of the cached prefix**, so keep one frozen schema per pass type and do follow-up passes as appended turns | VERIFIED with usage numbers |
| Progress | `messages.stream()` events, plus `jiter.from_json(partial, partial_mode="trailing-strings")` for live counters; `thinking.display="summarized"` for a status ticker | VERIFIED |
| Vision fallback | pypdfium2 renders at 200 dpi, fitted to ≤ 2576 px and ≤ 4784 visual tokens, grayscale PNG, labeled `Image n (datasheet page p):` | VERIFIED: geometry from images alone was 100 % correct on Haiku 5.5 for $0.005 |

---

## 1. Key handling and first call

- The research calls used an explicitly configured local key file, read only inside Python and passed as `anthropic.Anthropic(api_key=Path(...).read_text(encoding="utf-8").strip())`. Its contents were never printed. PartForge itself requires explicit key configuration and does not search other projects for credentials.
- Tiny call (**VERIFIED**): `claude-haiku-5-5`, `max_tokens=32`, `thinking={"type":"disabled"}`, prompt "Reply with exactly: OK". It returned `'OK'`, `stop_reason=end_turn`, 16 input and 4 output tokens, **0.86 s**, $0.000004, and `usage.output_tokens_details.thinking_tokens=0`.
- Models API (free, **VERIFIED**). The key sees `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`, `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-opus-4-6`, `claude-opus-4-5-20251101`, `claude-haiku-4-5-20251001` and `claude-sonnet-4-5-20250929`. In SDK 1.12.0, `model.capabilities` is a **typed `ModelCapabilities` object**, not the dict the skill describes. Read it with `m.capabilities.model_dump()`. All three candidates report `pdf_input`, `image_input`, `structured_outputs`, `citations` and `batch` as supported, plus effort `low` through `max`. Thinking support differs:
  - `claude-opus-5-5` and `claude-sonnet-5-5`: `adaptive` true, `disabled` false, `enabled` false.
  - `claude-haiku-5-5`: `adaptive` true, **`disabled` true**, `enabled` false.
- Windows note (**VERIFIED**): printing datasheet text such as "Ω" crashed under the cp1252 console. Call `sys.stdout.reconfigure(encoding="utf-8")`. `python -I` ignores `PYTHONIOENCODING`.
- PartForge should keep its own key in Windows Credential Manager (via `keyring`) or in the `ANTHROPIC_API_KEY` environment variable, and must never pass it to the pywebview/React frontend (**UNVERIFIED**, a proposal).

---

## 2. Models, prices and measured quality

### 2.1 Current models and prices (DOC, live pricing page fetched 2026-10-07)

| Model | ID | Input $/MTok | 5-min cache write | Cache read | Output $/MTok | Default effort | Thinking |
|---|---|---|---|---|---|---|---|
| Claude Opus 5.5 | `claude-opus-5-5` | 4.00 | 5.00 | 0.20 | 20.00 | `medium` | adaptive, always on (`disabled` → 400, VERIFIED) |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2.00 | 2.50 | 0.20 (table) / 0.10 (prose) ⚠ | 10.00 | `high` | adaptive (`between_tools` to turn it off) |
| Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 (≤100k-token prompt) / 0.50 (>100k) | 0.125 / 0.625 | 0.01 / 0.05 | 0.50 / 2.50 | `medium` | adaptive; `disabled` accepted (VERIFIED) |

- The pricing page contradicts itself on Sonnet 5.5 cache reads ($0.20/MTok in the table, "$0.10 USD on Claude Sonnet 5.5" in the caching section). None of my Sonnet runs had a cache read, so this is not resolved.
- Haiku 5.5 has a **price cliff at 100k prompt tokens** (5× above it). The full 25-page OPA656 PDF (63k tokens) stays below it; a 60-page datasheet would not. This is one more reason to subset pages.
- Batch API: 50 % off (DOC). Opus 5.5 fast mode costs $8/$40 (DOC; not useful here).
- All three models share the new tokenizer and the high-resolution vision tier. They return identical token counts for the same input (**VERIFIED** with count_tokens, §3.2).
- The skill text (cached 2026-09-25) does not yet list Haiku 5.5. The live docs say "Released October 7, 2026" and list "classification, routing, extraction" as its main uses (DOC).

### 2.2 Measured runs on `<datasheet-source>/opa656.pdf` (VERIFIED)

Input was the same for every run: 7-page subset [1, 2, 17, 21, 22, 23, 24], the system prompt, and the full `DatasheetExtraction` schema (§4.3). That is 19,809 prompt tokens, of which 19,716 were cached at the document breakpoint. Streaming was on, `max_tokens=32000`, and `fallbacks="default"` was set on the Opus and Sonnet runs. Costs below include the 1.25× cache write on the first run per model.

| Run | Effort | Thinking tok | Output tok | First JSON char | Total | Cost | Pins (13) | Dims (22) | Land pattern (14) | MPNs (14) |
|---|---|---|---|---|---|---|---|---|---|---|
| opus55_low | low | 0 | 3,990 | **1.96 s** | **27.7 s** | $0.179 | 13 | 22 (+ gauge plane) | 14 | 14 |
| opus55_medium | medium | 855 | 5,200 | 9.83 s | 37.1 s | $0.203 | 13 | 22 (+ gauge plane) | 14 | 14 |
| sonnet55_low | low | 0 | 3,899 | 3.78 s | 30.8 s | $0.088 | 13 | 20 (no coplanarity) | 14 | 14 |
| sonnet55_medium | medium | 0 | 3,980 | 2.45 s | 30.1 s | $0.089 | 13 | 20 (no coplanarity) | 14 | 14 |
| haiku55_medium¹ | medium | 8,048 | 12,901 | 37.1 s | 49.3 s | $0.0067 | 13 | 22 | 14 | 14 |
| haiku55_low | low | 4,695 | 9,262 | 29.0 s | 38.9 s | $0.0071 | 13 | 22 | 14 | 14 |
| haiku55_nothink | `thinking: disabled` | 0 | 3,861 | 6.9 s | 18.9 s | $0.0044 | 13 | **19 (c min 0.10 instead of 0.13; no symbols)** | 14 | **8** |
| minimal sample, Opus 5.5 (§9) | low | n/a | 2,501 | n/a | 21 s | ≈$0.136 | 13 | 20 of 20 printed | all | 14 |
| minimal sample, Haiku 5.5 (§9) | low | n/a | 5,170 | n/a | 27 s | ≈$0.005 | 13 | ok | ok | 8 |

¹ This run read 19,723 tokens from the cache written by a previous identical request (§5).

- Ground truth was read by hand from 200 dpi renders. Scoring is done by `scripts/evaluate.py`. The pins and pin types are:
  - SO-8 (D): 1 NC, 2 −IN, 3 +IN, 4 −VS, 5 NC, 6 OUT, 7 +VS, 8 NC.
  - SOT-23-5 (DBV): 1 OUT, 2 −VS, 3 +IN, 4 −IN, 5 +VS.
  - The pypdf text layer garbles the SOT-23 pin order. Every model read it correctly from the page image.
- Land patterns:
  - D: pad 0.60 × 2.00 mm, pitch 1.27, rows 4.80 center-to-center, mask 0.07, stencil 0.55 × 1.95.
  - DBV: pad 0.6 × 1.05, pitch 0.95, rows 2.7 center-to-center, mask 0.07, stencil 0.55 × 1.00.
  - These drawings (pages 21 to 24) **have no text layer at all**. The models read them from the page images that the PDF pipeline renders.
- Output speed (INFERRED from the table): Opus and Sonnet about 150 output tok/s, Haiku about 300 tok/s. Haiku is still the slowest end to end because it thinks for 4.7k to 8k tokens even at `low`. Opus and Sonnet did **not** think at `low`, and Sonnet did not think at `medium` either.
- The JSON is 8.2k to 10.5k characters.
- Without the cache write (single shot, no `cache_control`) the costs drop to about $0.16 (Opus low), $0.079 (Sonnet low) and $0.007 (Haiku) (INFERRED from usage).

### 2.3 Recommendation

1. **Interactive drag-and-drop import:** `claude-opus-5-5`, effort `low`. It was complete and correct, had the fastest first byte, and was the fastest end to end; it costs about $0.15 to 0.18 per datasheet. The docs describe Opus 5.5 as the strongest current model at reading technical drawings ("reads visual material more accurately at every effort level", DOC). Raise effort to `medium` only when validation fails or for dense packages (QFN/BGA, pitch ≤ 0.5 mm). On OPA656 that cost +$0.02 and +9 s with the same result.
2. **Bulk imports or a "cheap mode":** `claude-haiku-5-5` at `low` or `medium` with thinking on: 25× cheaper and still 100 % on this datasheet. Never disable thinking for geometry (the no-thinking run produced a real misread). For overnight series imports, the Batch API takes another 50 % off (DOC, UNVERIFIED here).
3. **Consensus cross-check (UNVERIFIED as a pipeline):** run Haiku 5.5 next to Opus (+4 % cost), diff pins, dimensions and land pattern, and show any disagreement in the UI. On OPA656 both agreed.
4. Make the model and effort configurable, and treat the numbers above as **n = 1 datasheet**. Before fixing defaults, build a 10 to 20 datasheet eval set (QFN with an exposed pad, BGA, multi-part datasheets, scanned PDFs, non-TI layouts).

---

## 3. Sending PDFs

### 3.1 Transport options

**base64 document block** (VERIFIED, used in every run):

```python
{"type": "document",
 "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(pdf_bytes).decode("ascii")},
 "cache_control": {"type": "ephemeral"}}          # put it BEFORE the text block
```

**Files API** (VERIFIED, GA, no beta header, `client.files` rather than `client.beta.files`):

```python
up = client.files.upload(file=("opa656_subset.pdf", io.BytesIO(data), "application/pdf"), expires_in_seconds=3600)
# -> FileMetadata(id='file_016e...', mime_type='application/pdf', size_bytes=292220, expires_at=..., downloadable=False)
doc = {"type": "document", "source": {"type": "file", "file_id": up.id}}
client.files.retrieve_metadata(up.id); client.files.delete(up.id)   # retrieving after delete -> anthropic.NotFoundError (404)
```

- The file_id request billed 14,638 input tokens, the same as the base64 subset (14,627 + text) (VERIFIED).
- `client.messages.count_tokens(...)` with a file source returns **400 "File sources are not supported in the token counting endpoint."** (VERIFIED). Count tokens on the base64 bytes before uploading.
- `expires_in_seconds` accepts 3,600 to 7,776,000 (DOC). Files are workspace-scoped: any key in the workspace can read them, so never accept a file_id from a user. Files are **not ZDR-eligible**. The Files API allows about 500 RPM and 500 MB per file (DOC).
- Use the Files API only when the same PDF is referenced again later (re-extraction days later, a "chat with this datasheet" feature, payloads over several MB). For a one-shot import, base64 is simpler and needs no cleanup.

### 3.2 Limits and token costs

Limits (DOC): 32 MB per request, 600 pages per request (100 if the context window is below 1M; all three models have 1M), no password or encryption. A PDF is processed as page text plus a page image, so the vision limits apply (8000 × 8000 px per image; with more than 20 images or documents, each image must be ≤ 2000 px).

Measured token counts (VERIFIED, `count_tokens`, identical for Opus 5.5, Sonnet 5.5 and Haiku 5.5):

| Input | Tokens |
|---|---|
| full PDF, 25 pages, 853,689 bytes | 63,474 (≈ 2,540 per page) |
| 7-page subset, 292,220 bytes | 14,627 |
| single page without a text layer (p21) | 1,588 → the PDF page image ≈ 1.6k visual tokens ≈ 1.2 MP ≈ 110 to 120 dpi on Letter (**INFERRED**) |
| single text page (p2) | 2,699 |
| p21 rendered at 200 dpi, fitted to 1666 × 2156 px PNG | 4,632 (formula ⌈w/28⌉·⌈h/28⌉ = 4,620) |
| whole extraction request (system + schema + subset + instruction), early prompt version | 20,068 |
| cached prefix size: system + PDF with no schema / with the small pins-only schema / with the full schema | 15,183 / 17,442 / 19,716 → the schema adds hidden system text of ≈ 2.3k (small) to ≈ 4.5k (full) tokens |

### 3.3 Pre-splitting with pypdf and choosing pages

Always pre-split for extraction. It cut tokens by 77 %, removed noise (typical-characteristics plots, legal notice) and makes latency predictable.

The heuristic below (VERIFIED, `scripts/pdf_tools.py`) selected exactly [1, 2, 17, 21, 22, 23, 24] for OPA656:

```python
CATEGORIES = {
    "pins": re.compile(r"pin\s*(configuration|functions?|description|assignments?|out)|pinout|terminal functions|pin\s+no\b", re.I),
    "ordering": re.compile(r"ordering information|orderable device|order(ing)?\s+(code|number)", re.I),
    "mechanical": re.compile(r"mechanical data|package (outline|dimensions|drawing)|outline dimensions|case outline|physical dimensions|package information", re.I),
    "land_pattern": re.compile(r"land pattern|recommended (footprint|land|pad layout|solder pad)|example board layout|solder pad layout|mounting pad|pcb footprint", re.I),
}
NOISE = re.compile(r"important notice|revision history|typical characteristics|tape and reel|all dimensions are nominal", re.I)

def select_pages(pdf_path: str, max_pages: int = 12) -> tuple[list[int], dict[int, list[str]]]:
    texts = page_texts(pdf_path)          # [(p.extract_text() or "") for p in PdfReader(pdf_path).pages]
    n = len(texts)
    reasons: dict[int, list[str]] = {1: ["first page"]}
    for i, t in enumerate(texts, start=1):
        hits = [name for name, rx in CATEGORIES.items() if rx.search(t)]
        if hits and NOISE.search(t) and set(hits) <= {"ordering", "mechanical"} and not re.search(r"orderable device", t, re.I):
            hits = []  # tape&reel tables, legal addenda, characteristic plots
        if hits:
            reasons.setdefault(i, []).extend(hits)
        if len(t.strip()) < 50 and i > min(3, n):          # no text layer -> drawing/scan
            reasons.setdefault(i, []).append("no text layer (drawing?)")
    ranked = sorted(reasons, key=lambda p: (-len(reasons[p]), p))[:max_pages]
    return sorted(ranked), reasons
```

- The first version also picked page 18 (addendum legal notes) and page 20 (tape-and-reel box sizes). The `NOISE` rule fixed that (VERIFIED).
- **Page numbering:** ask for page numbers *of the attached PDF* and map them back in code (`orig = pages[i-1]`). In the first Haiku run, Haiku ignored a "PDF page i = datasheet page p" map and reported subset page numbers (VERIFIED). After switching to subset numbering, every model returned correct pages (D outline 23, land pattern 24; DBV 21 and 22).
- **LLM page triage (VERIFIED as an option):** send `[page i] chars=N (NO TEXT LAYER...)` plus the first 400 characters of each page to `claude-haiku-5-5` (effort `low`) via `client.messages.parse(..., output_format=Triage)`. It took 4.6 s, 5,338 input tokens and cost **$0.00096**. It kept 1, 2 and 17 to 24 (it over-included tape-and-reel pages 18 to 20, and with only 400 characters per page it missed the "pinout" on page 2). Use it as a supplement when the heuristic finds fewer than about 3 pages, the PDF has no text layer anywhere (a scan), or the datasheet is long (MCU manuals). Union both results and cap the count.
- Scanned PDFs (UNVERIFIED): every page lacks a text layer, so the heuristic would keep everything. Send the whole PDF if it is ≤ about 40 pages, or render 50 to 70 dpi thumbnails and let Haiku pick pages from them.

---

## 4. Structured output and schema design

### 4.1 Method (VERIFIED)

- **Request:** `output_config={"effort": "low", "format": {"type": "json_schema", "schema": anthropic.transform_schema(DatasheetExtraction)}}`. `anthropic.transform_schema` is a public export (`anthropic/__init__.py`). It turns a Pydantic class into the strict API form: `additionalProperties: false` everywhere, unsupported keywords moved into `description`.
- **Response:** take the `text` blocks, check `final.stop_reason == "end_turn"`, then call `DatasheetExtraction.model_validate_json(text)`. On `refusal` or `max_tokens` the JSON may not match the schema (DOC).
- **SDK helpers, also verified:**
  - `client.messages.parse(..., output_format=Model)` returns `.parsed_output` (non-streaming; used for page triage).
  - `AsyncAnthropic().messages.stream(..., output_format=Model)` gives `await stream.get_final_message()`, whose `.parsed_output` is a validated model.
  - The SDK's own stream accumulator calls the parser on `content_block_stop`. That raises **in the middle of iteration** if the text is truncated or a refusal. That is why the raw `output_config.format` plus explicit validation shown above is the robust choice for long extractions.
- `output_format=` is the SDK convenience parameter. On the wire it becomes `output_config.format`, merged with your `output_config` (`effort` stays) (VERIFIED in SDK source, `resources/messages/messages.py`).
- `messages.parse()` has no top-level `cache_control` parameter, but block-level `cache_control` works (VERIFIED by signature).

### 4.2 Limits, including one undocumented in practice

- Documented limits (DOC): ≤ 20 strict tools, ≤ **24 optional parameters**, ≤ **16 parameters with union types** (`anyOf` or type arrays), summed over all strict schemas in a request. No `minimum`/`maximum`/`minLength`/`maxLength`. Array `minItems` only 0 or 1. Recursive schemas are not supported. Compiling a grammar can take up to 180 s and the compiled grammar is cached for 24 h. Enum casing is **not guaranteed**, so compare case-insensitively. Required properties come out first, in schema order. Do not add "reasoning"/"step-by-step" fields, because they can trigger `reasoning_extraction` refusals.
- **Grammar size (VERIFIED, important).** The full schema had 10 nullable numbers (`float | None`, i.e. `anyOf[number, null]`) nested in `packages[].dimensions[]` and `packages[].land_pattern`, which is under the documented 16-union limit. It was still rejected:
  `400 invalid_request_error: "The compiled grammar is too large, which would cause performance issues. Simplify your tool schemas or reduce the number of strict tools."`
  Probes run on Haiku 5.5, about $0.0004 each; failures cost nothing:

| Variant | Result |
|---|---|
| A: full schema with nullable numbers (10 anyOf, 5 enums) | **FAIL** (too large) |
| I: A with enums removed | **FAIL** |
| J: A with `{"type":["number","null"]}` instead of anyOf | **FAIL** |
| G: nullable numbers turned into `string` | OK |
| H/L: nullable numbers turned into plain `number` with a `-1` sentinel (**chosen**) | OK |
| C: part + variants + packages with pins only (no geometry) | OK |
| D: geometry only (dimensions + land pattern, 10 anyOf) | OK |

  So either drop nullable numbers or split the schema into passes. Re-run a compile probe whenever the schema changes: one tiny request with `max_tokens=16` costs about $0.0005 on Haiku.
- Pydantic: `x: float | None = None` is optional **and** a union, so it counts toward both limits. Declare every field required (no defaults). The SDK keeps `required` only for fields Pydantic marks required (VERIFIED in `transform_schema` source).
- `transform_schema` keeps only the string formats `date-time`, `time`, `date`, `duration`, `email`, `hostname`, `uri`, `ipv4`, `ipv6` and `uuid`. Any other leftover keyword, **including `pattern`**, is appended to `description` as text and is not enforced, even though the API itself supports `pattern` (VERIFIED, SDK source). Pass a hand-written dict schema if you need a pattern enforced.

### 4.3 Recommended schema (VERIFIED: compiles; 100 % on OPA656 with Opus and Haiku), `scripts/datasheet_schema.py`

```python
PinType = Literal["Input", "IO", "Output", "OpenCollector", "Passive", "HiZ", "OpenEmitter", "Power"]   # Altium electrical types

class Pin(BaseModel):
    number: str = Field(description="Pin/pad designator exactly as printed for THIS package, e.g. '1', 'A3', 'EP'.")
    name: str = Field(description="Short schematic pin name, e.g. '-IN', '+IN', 'V+', 'V-', 'OUT', 'NC'. Use the datasheet's short name if one exists.")
    function: str = Field(description="Pin function as written in the datasheet, e.g. 'Inverting Input'.")
    electrical_type: PinType = Field(description="Altium pin electrical type. Supplies/ground/exposed pad -> Power; NC -> Passive.")
    is_no_connect: bool

NA = -1.0  # sentinel for "not given in the datasheet"
_NUM = "Millimetres (degrees for unit 'deg'); -1 if the datasheet does not give this value."

class Dimension(BaseModel):
    symbol: str = Field(description="JEDEC-style symbol if identifiable (A, A1, A2, b, c, D, E, E1, e, L, theta, ccc ...), else ''.")
    description: str = Field(description="What is measured, e.g. 'body length', 'overall width incl. leads', 'lead pitch (basic)'.")
    unit: Literal["mm", "deg"]
    min: float = Field(description=_NUM)
    nom: float = Field(description=_NUM)
    max: float = Field(description=_NUM)

class LandPattern(BaseModel):
    present_in_datasheet: bool = Field(description="True only if the PDF contains a recommended land pattern / example board layout for this package.")
    source_pages: list[int] = Field(description="1-based page numbers within the attached PDF showing the land pattern; [] if none.")
    pad_shape: Literal["rectangle", "rounded_rectangle", "oval", "circle", "other", "unknown"]
    pad_width_mm: float = Field(description="Pad size measured parallel to the pad row (across the lead). -1 if not given.")
    pad_length_mm: float = Field(description="Pad size measured along the lead direction (perpendicular to the pad row). -1 if not given.")
    pad_pitch_mm: float = Field(description="Center-to-center distance of adjacent pads in one row. -1 if not given.")
    row_spacing_mm: float = Field(description="Distance between the two opposing pad rows, as dimensioned in the drawing. -1 if not given.")
    row_spacing_reference: Literal["center_to_center", "inner_edges", "outer_edges", "not_applicable", "unclear"]
    solder_mask_expansion_mm: float = Field(description="Solder mask opening clearance per side around the pad. -1 if not given.")
    stencil_aperture_width_mm: float = Field(description="-1 if not given.")
    stencil_aperture_length_mm: float = Field(description="-1 if not given.")
    notes: str

class Package(BaseModel):
    package_code: str = Field(description="Manufacturer package designator, e.g. 'D', 'DBV'.")
    package_name: str = Field(description="Common name, e.g. 'SOIC-8', 'SOT-23-5'.")
    outline_reference: str = Field(description="JEDEC/EIAJ outline reference if stated, e.g. 'MS-012 AA'; '' if none.")
    ipc7351_name: str = Field(description="IPC-7351B footprint name derived from the nominal dimensions, e.g. 'SOIC127P600X175-8N'.")
    pin_count: int
    mounting: Literal["SMD", "THT"]
    pins: list[Pin] = Field(description="Complete pin table for THIS package, ordered by pin number.")
    dimensions_source_pages: list[int] = Field(description="1-based page numbers within the attached PDF showing the package outline; [] if none.")
    dimensions: list[Dimension] = Field(description="All package outline dimensions in mm (convert inches; for 'inch (mm)' drawings use the mm values).")
    land_pattern: LandPattern

class OrderableVariant(BaseModel):
    mpn: str = Field(description="Complete orderable manufacturer part number, e.g. 'OPA656U/2K5'.")
    package_code: str
    grade: str = Field(description="Grade/option, e.g. 'standard', 'high grade'; '' if none.")
    packing: str = Field(description="Transport media and quantity, e.g. 'Tape and Reel, 2500'.")
    temperature_range: str
    status: str = Field(description="Lifecycle status if stated (ACTIVE, PREVIEW, NRND ...), else ''.")
    marking: str

class KeyParameter(BaseModel):
    name: str
    value: str = Field(description="Value as printed, keep typ/min/max qualifiers, e.g. 'typ 230'.")
    unit: str
    condition: str

class DatasheetExtraction(BaseModel):
    manufacturer: str
    base_part_number: str
    datasheet_document_id: str = Field(description="Literature number / document id, e.g. 'SBOS196G'.")
    datasheet_date: str
    component_category: str = Field(description="e.g. 'Operational Amplifier', 'LDO Regulator', 'Resistor'.")
    description_short: str = Field(description="Altium Description field, max ~60 characters.")
    description_long: str
    orderable_variants: list[OrderableVariant]
    packages: list[Package]
    key_parameters: list[KeyParameter] = Field(description="Up to 12 headline parameters useful as database columns.")
    warnings: list[str] = Field(description="Ambiguities, conflicts between pages, values that could not be read.")
```

Design notes:
- Pins are stored per package because the numbering differs (OPA656: SO-8 pin 6 is OUT, SOT-23 pin 1 is OUT).
- The `-1` sentinel was followed by every model. Map `v < 0 → None` before writing to the DB, and treat any other negative value as a validation error.
- `row_spacing_reference` matters: TI dimensions row spacing between pad **centerlines** (4.80 / 2.7). Sonnet once returned `"unclear"` with the correct value plus a warning.
- **Do not trust `ipc7351_name` from the model.** Haiku at `low` left it blank on purpose ("nominal not printed"). PartForge should compute IPC-7351B names and land patterns in code from min/max (UNVERIFIED proposal).
- The `warnings` field turned out very useful. The runs flagged real data conflicts: "rails 100 vs 75" (Opus, Sonnet, Haiku medium), "/3K variants missing from the addendum", "G4 variants only in the addendum", "UB/2K5G4 PREVIEW".

System prompt used, kept byte-stable (`scripts/prompts.py`, VERIFIED):

```text
You extract component data from electronic-component datasheets for an Altium Designer database library (PartForge).
The output is used to generate the database record, the schematic symbol and an IPC-7351B footprint automatically, so precision matters more than completeness.

Rules:
- Use only information visible in the supplied pages (text, tables, drawings). Never fill gaps from general knowledge of similar parts; use -1 for numbers, "" for strings and [] for lists instead, and add a warning.
- Pin tables are per package: pin numbers usually differ between packages. List every pin of every package, including NC pins.
- Pin electrical types follow Altium: supply, ground and exposed/thermal pads -> Power; signal inputs -> Input; outputs -> Output; bidirectional -> IO; open-drain/open-collector outputs -> OpenCollector; NC and pins of passive parts -> Passive (set is_no_connect for NC).
- Dimensions: report millimetres. If a drawing shows "inch (mm)" pairs, use the millimetre values. Map two stacked values to max (upper) and min (lower) as drawn; use nom only when a nominal/basic value is printed (basic dimensions such as pitch go into nom). Angles use unit "deg".
- Land patterns: take pad size, pitch and row spacing only from a recommended land pattern / example board layout drawing. State in row_spacing_reference which features the row-spacing dimension connects (pad centre lines vs pad edges). Do not compute a land pattern yourself.
- Page numbers you report are 1-based page numbers of the attached PDF.
- Record every ambiguity or conflict (for example between the ordering table and the package addendum) in warnings.
```

User text after the document block: "Extract the complete part record from the attached datasheet pages. Return manufacturer, base part number, all orderable MPN variants, descriptions, every package with its full pin table, all outline dimensions (min/nom/max in mm) and the recommended land pattern if one is shown."

Suggested client-side validation before anything reaches Altium (UNVERIFIED proposal):
- `min ≤ nom ≤ max`
- `len(pins) == pin_count`, pin numbers unique
- outline `e` equals `land_pattern.pad_pitch_mm`
- for gull-wing parts, row spacing (center-to-center) lies between `E − 2L` and `E`
- `b < e`, `E1 < E`, `A1 < A`

Any failure should trigger the vision verification pass (§8).

---

## 5. Prompt caching for multi-pass extraction

Verified behavior (Haiku 5.5, `max_tokens=16` probes plus the real runs; `scripts/cache_probe.py`, `scripts/followup_pass.py`):

| Request (same system prompt + same PDF with `cache_control` on the document block) | Usage |
|---|---|
| 1. schema A (part + pins) | cache_write 17,442 |
| 2. schema A, different instruction after the breakpoint | **cache_read 17,442**, uncached 217 |
| 3. schema B (geometry) | cache_read 0, **cache_write 17,645** (miss) |
| 4. no schema | cache_read 0, cache_write 15,183 (miss) |
| 5. schema A again | cache_read 17,442 (entry A still alive) |
| identical extraction re-run within 5 min (haiku55_medium) | cache_read 19,723, uncached 211 |
| effort `low` → `medium` and display `summarized` → `omitted` (Haiku 5.5) | still a hit (19,716 read); observed once |
| `thinking: disabled` vs adaptive (Haiku 5.5) | separate entry (19,715 vs 19,716 written) |
| follow-up turn in the same conversation (append `final.content`, then user turn with 4 renders), same schema | **cache_read 19,716**, cache_write 30,686 (previous answer + images), 23.6 s, $0.0074 |

What follows from this:
1. **The output schema is part of the cached prefix** (it sits in the system area, ahead of the messages). Changing schemas between passes re-bills the whole PDF at the write rate. Freeze one schema per pass type and serialize it deterministically (`transform_schema` of a fixed class gives a stable dict).
2. **Breakpoint placement:** put `cache_control: {"type": "ephemeral"}` on the **document block** so the instruction text after it can vary. Render order is tools → system (+ schema) → messages. Up to 4 breakpoints are allowed (DOC). In follow-ups, add a second breakpoint on the last new block (as done in `followup_pass.py`).
3. **Multi-pass pattern (recommended):**
   - Pass 1 is the combined extraction with the frozen schema.
   - Verification and correction passes are **appended turns in the same conversation** with the same schema: append `final.content` unchanged (including the thinking blocks), then a user turn carrying high-res crops or a correction request.
   - Keep the history **append-only**. Opus/Sonnet/Haiku 5.5 thinking blocks are bound to the conversation and the account. Editing earlier turns can give a 400 "Invalid `signature` in `thinking` block" on accounts created after 2026-08-31 (DOC).
4. If you split into several schemas because a single schema hits the grammar limit, send each pass **only the pages it needs** (pins: pages 1, 2, 17; geometry: pages 21 to 24) instead of sharing one cached full prefix. That is cheaper than four separate cache writes of the whole subset, and the two passes can run in parallel.
5. **Economics (DOC prices):** a 5-minute write costs 1.25× input and a read 0.05× on Opus 5.5 ($0.20 against $4.00 per MTok). For one OPA656 extraction the write premium is +$0.02 on Opus, and one hit saves about $0.075. Set the breakpoint when a follow-up within 5 minutes is likely: a verification pass, a user pressing "re-extract", or a chat about the datasheet. For a one-shot bulk import, leave it off. The 1-hour TTL (2× write) pays off only for gaps of 5 to 60 minutes.
6. Caches are **model-scoped**: an Opus + Haiku consensus run pays two writes. Parallel requests only read a cache entry once the first response **has started streaming**. To fan out, wait for the first event of request 1 before sending the others (DOC).
7. The minimum cacheable prefix is 512 tokens on Opus 5.5 and Sonnet 5.5 (DOC). Haiku 5.5 is not documented, but our 15k+ prefixes cached fine. Verify with `usage.cache_read_input_tokens > 0` in an integration test.

---

## 6. Streaming and progress reporting (VERIFIED, `scripts/extract.py`)

```python
with client.messages.stream(**request) as stream:          # or client.beta.messages.stream(..., betas=[...], fallbacks="default")
    for event in stream:
        if event.type == "content_block_start":             # "thinking" first (if any), then "text"
            ...
        elif event.type == "content_block_delta":
            if event.delta.type == "thinking_delta":         # only non-empty with thinking.display="summarized"
                ui.status(event.delta.thinking)
            elif event.delta.type == "text_delta":           # JSON characters
                json_chars += len(event.delta.text)
                if json_chars - last >= 3000:
                    snap = stream.current_message_snapshot
                    txt = "".join(b.text for b in snap.content if b.type == "text")
                    partial = jiter.from_json(txt.encode(), partial_mode="trailing-strings")
                    ui.progress(variants=len(partial.get("orderable_variants", [])),
                                packages=len(partial.get("packages", [])),
                                pins=sum(len(p.get("pins", [])) for p in partial.get("packages", [])))
    final = stream.get_final_message()
    request_id = stream.request_id       # NOTE: final._request_id does NOT exist on streamed ParsedMessage (AttributeError)
```

- Observed sequence for Haiku: `block start: thinking` at 1.4 s, `block start: text` at 37 s, then counters such as "3008 JSON chars | mpn variants=14 packages=1 pins=0", then "packages=2 pins=12" and so on. Because required properties come out in schema order, the identity data (manufacturer, MPNs) arrives first and pins and geometry later. The UI can show the part name about 2 s after JSON starts.
- `thinking={"type": "adaptive", "display": "summarized"}` streams readable thinking summaries (Haiku: 6,418 characters for 8,048 thinking tokens; Opus medium: 632 characters for 855). The default `display` is `"omitted"`, which gives empty thinking text (DOC). Display does not change billing.
- With Opus and Sonnet at `low` there is no thinking block; JSON starts at 2.0 to 3.8 s. Opus at `medium` starts at 9.8 s.
- Timeouts: the SDK default is 10 min, and I used `timeout=600.0`. Streaming avoids the SDK's "non-streaming request may exceed 10 min" `ValueError` for large `max_tokens` (DOC).
- FastAPI and pywebview: `anthropic.AsyncAnthropic` streaming with structured output was VERIFIED (`async with aclient.messages.stream(..., output_format=Pins) as stream: async for ev in stream: ...; final = await stream.get_final_message()` gives `final.parsed_output`). Forwarding the events to React via SSE or WebSocket is a proposal (UNVERIFIED).
- Progress estimate: expect 8 to 11k characters of JSON for a 2-package part. Roughly `chars ≈ 1,500 + 500·pins + 250·dims` (INFERRED). Counters from the partial parse are more honest than a percentage bar.

---

## 7. Errors, retries, refusals, rate limits

- **SDK retries** (DOC + README): connection errors, 408, 409, 429 and ≥ 500 are retried with exponential backoff, honoring `retry-after`. The default is `max_retries=2`; I used 3 (`anthropic.Anthropic(..., max_retries=3)`). A stream that breaks mid-way is **not** resumed. Retry the whole request; with caching that is cheap.
- **Typed exceptions** (VERIFIED instances):
  - `anthropic.NotFoundError` (404) for an unknown model, and for `files.retrieve_metadata` after delete.
  - `anthropic.BadRequestError` (400) for each of these:
    - grammar too large (§4.2)
    - `"thinking.type.disabled" is not supported for this model. Use "thinking.type.adaptive" and "output_config.effort" ...` on Opus 5.5
    - `tool_choice: type "tool" and "any" are not supported for this model.` on Opus 5.5
    - `File sources are not supported in the token counting endpoint.`

  Catch from most specific to least: `NotFoundError` → `RateLimitError` → `APIStatusError` (check `e.status_code`, `e.type`) → `APIConnectionError`. Log `stream.request_id`.
- **stop_reason handling:**
  - `end_turn`: validate the JSON.
  - `max_tokens`: the JSON is truncated; retry with a larger `max_tokens` (thinking counts toward it, so keep 32k).
  - `refusal`: HTTP 200 with `stop_details.category` (`cyber`, `bio`, `reasoning_extraction`, ...); the output may not match the schema (DOC).
- **Server-side fallbacks** (VERIFIED accepted; never triggered here): `client.beta.messages.stream(..., betas=["server-side-fallback-2026-07-01"], fallbacks="default")` works together with structured output, PDF input and effort on Opus 5.5 and Sonnet 5.5. Haiku 5.5 also accepted the parameter without error, although its docs say it "has no server-side fallback".
  - After a mid-stream fallback, `content` holds the declined model's partial text, a `{"type":"fallback"}` block, then the new output (DOC). **Parse only the text blocks after the last `fallback` block**; the minimal sample does this.
  - Detect a fallback with `any(i.type == "fallback_message" for i in final.usage.iterations or [])`.
  - `reasoning_extraction` declines are not retried (DOC).
- **Rate limits for this organization** (VERIFIED from `anthropic-ratelimit-*` response headers via `client.messages.with_raw_response.create(...)`). They are identical for Haiku 5.5, Sonnet 5.5 and Opus 5.5:
  - `requests-limit = 10000` per minute
  - `input-tokens-limit = 10000000`
  - `output-tokens-limit = 2000000`
  - `tokens-limit = 12000000`

  That is far above what PartForge needs, so a simple `asyncio.Semaphore(4)` is enough. The Files API allows about 500 RPM (DOC). Cache reads do not count toward input TPM on most models (DOC).
- **529 overloaded:** retried by the SDK. As a last resort, retry once on another model on the client side.

---

## 8. Vision fallback (pypdfium2 renders)

Why and when:
- The PDF pipeline already shows each page to the model as an image of about 1.6k visual tokens (≈ 1.2 MP, roughly 110 to 120 dpi; INFERRED from the 1,588-token count for an image-only page). That was enough for the OPA656 drawings: every model read all values from the text-less pages 21 to 24.
- Use high-res renders when:
  - client-side validation fails
  - two models disagree
  - the drawing is dense (QFN/BGA, fine pitch, small fonts)
  - the drawing covers only a small part of the page
  - the PDF is scanned or rejected (encrypted, too large)
  - the user drops an image (PNG/JPG) instead of a PDF

Resolution math (DOC + VERIFIED):
- On the high-resolution tier (Claude 4.7 and later, which includes Opus, Sonnet and Haiku 5.5), images are downscaled to fit a **2576 px long edge and 4,784 visual tokens**, where an image costs ⌈w/28⌉·⌈h/28⌉ tokens.
- A Letter page at 200 dpi is 1700 × 2200 px = 4,819 tokens, so the API would shrink it slightly. `render_png` (below) fits it to 1666 × 2156 = 4,620 tokens (measured 4,632).
- A 300 dpi crop of the drawing area (0.12 to 0.92 by 0.12 to 0.60 of the page) gives 2040 × 1584 px = 4,161 tokens, which is more pixels per millimetre for the same cost.
- One full-page render costs about 2.9× the same page inside the PDF (4.6k against 1.6k tokens).
- Other limits: ≤ 10 MB per base64 image; with more than 20 images in one request, every image must be ≤ 2000 px; use JPEG, PNG, GIF or WebP; put images before the text (DOC). Grayscale PNGs of drawings came out at about 120 to 210 KB per page.

```python
def render_png(pdf_path: str, page: int, dpi: int = 200, crop: tuple[float, float, float, float] | None = None,
               max_long_edge: int = 2576, max_visual_tokens: int = 4784) -> tuple[bytes, tuple[int, int]]:
    from PIL import Image
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        img = pdf[page - 1].render(scale=dpi / 72.0).to_pil()
    finally:
        pdf.close()
    if crop:
        w, h = img.size
        img = img.crop((int(w * crop[0]), int(h * crop[1]), int(w * crop[2]), int(h * crop[3])))
    w, h = img.size
    scale = min(1.0, max_long_edge / max(w, h))
    while True:
        nw, nh = int(w * scale), int(h * scale)
        if -(-nw // 28) * -(-nh // 28) <= max_visual_tokens:
            break
        scale *= 0.98
    if scale < 1.0:
        img = img.resize((nw, nh), Image.LANCZOS)
    img = img.convert("L")  # grayscale: drawings lose nothing, PNG gets smaller
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue(), img.size

# content blocks (images first, labeled):
content += [{"type": "text", "text": f"Image {i} (datasheet page {p}):"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64(png)}}]
```

Verified results:
- **Images only** (`scripts/vision_geometry.py`): the 4 renders of pages 21 to 24 at 200 dpi, no PDF, with a geometry-only schema (`packages[{package_code, package_name, outline_reference, ipc7351_name, dimensions_source_pages, dimensions[Dimension], land_pattern}]`, warnings), on `claude-haiku-5-5` at effort medium.
  - Usage: cache_write 21,465 (18,480 visual tokens by formula), out 4,704 (2,403 thinking), first JSON 15.0 s, total 22.5 s, **$0.005**.
  - Accuracy: all 22 dimensions (plus gauge plane 0.25) and all 14 land-pattern values correct.
- **Verification pass** (`scripts/followup_pass.py`): pass 1 was the PDF extraction; pass 2 appended the 4 renders asking "Verify every package dimension and land-pattern value ... return the complete corrected record and list each correction in warnings". The model confirmed every value, gave identical `packages`, and listed the checks in `warnings`. Usage: cache_read 19,716, $0.0074.
- The docs note that "higher-resolution images (most of all for technical drawings)" and crop/zoom tools add accuracy on the densest inputs, and that on Sonnet 5.5 tools help technical drawings only from effort `high` upward (DOC). An agentic crop tool was not tested.

---

## 9. Minimal working code sample (exactly as run)

`scripts/minimal_extract.py`. VERIFIED twice on `opa656.pdf`, run as `python -I minimal_extract.py <pdf> [model]`:
- default `claude-opus-5-5`: exit 0, 21 s, cache_write 17,108, out 2,501, all pins, dimensions and land patterns correct, 14 MPNs
- `claude-haiku-5-5`: exit 0, 27 s, correct, 8 MPNs

```python
"""PartForge minimal sample: datasheet PDF -> validated part record (pins, package outline, land pattern).

Verified 2026-10-07 with anthropic 1.12.0, pypdf 6.19.0, pydantic 2.13.5, Python 3.13.5.
usage: python minimal_extract.py <datasheet.pdf> [model]
"""
import base64
import io
import os
import re
import sys
from pathlib import Path
from typing import Literal

import anthropic
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

KEY_FILE = Path(os.environ["PARTFORGE_RESEARCH_KEY_FILE"])  # explicitly supplied local research key file
MODEL = sys.argv[2] if len(sys.argv) > 2 else "claude-opus-5-5"
NA = "-1 if the datasheet does not give this value"


class Pin(BaseModel):
    number: str
    name: str = Field(description="Short schematic pin name, e.g. '-IN', 'V+', 'OUT', 'NC'")
    function: str
    electrical_type: Literal["Input", "IO", "Output", "OpenCollector", "Passive", "HiZ", "OpenEmitter", "Power"]
    is_no_connect: bool


class Dimension(BaseModel):
    symbol: str
    description: str
    unit: Literal["mm", "deg"]
    min: float = Field(description=NA)
    nom: float = Field(description=NA)
    max: float = Field(description=NA)


class LandPattern(BaseModel):
    present_in_datasheet: bool
    pad_width_mm: float = Field(description="Across the lead. " + NA)
    pad_length_mm: float = Field(description="Along the lead. " + NA)
    pad_pitch_mm: float = Field(description=NA)
    row_spacing_mm: float = Field(description="Between opposing pad rows. " + NA)
    row_spacing_reference: Literal["center_to_center", "inner_edges", "outer_edges", "not_applicable", "unclear"]
    solder_mask_expansion_mm: float = Field(description=NA)


class Package(BaseModel):
    package_code: str
    package_name: str
    pin_count: int
    pins: list[Pin]
    dimensions: list[Dimension]
    land_pattern: LandPattern


class Variant(BaseModel):
    mpn: str
    package_code: str
    packing: str


class Part(BaseModel):
    manufacturer: str
    base_part_number: str
    description_short: str
    orderable_variants: list[Variant]
    packages: list[Package]
    warnings: list[str]


SYSTEM = (
    "You extract component data from datasheets for an Altium Designer database library. "
    "Use only what the pages show; never fill gaps from general knowledge (use -1, '' or [] and add a warning). "
    "Pin tables are per package. Altium pin types: supplies -> Power, NC -> Passive. "
    "Dimensions in mm (use the mm values of 'inch (mm)' drawings); stacked values are max over min; basic values go to nom. "
    "Land-pattern values only from a recommended land pattern drawing."
)
KEYWORDS = re.compile(r"pin\s*(configuration|functions?|description)|pinout|ordering information|orderable device|"
                      r"mechanical data|package (outline|dimensions)|land pattern|recommended (footprint|land)", re.I)


def pdf_subset_b64(path: str) -> tuple[str, list[int]]:
    """Keep page 1, keyword pages and text-less drawing pages; return base64 PDF + original page numbers."""
    reader = PdfReader(path)
    keep = [i for i, page in enumerate(reader.pages)
            if i == 0 or KEYWORDS.search(text := page.extract_text() or "") or (i > 2 and len(text.strip()) < 50)]
    writer = PdfWriter()
    for i in keep:
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return base64.standard_b64encode(buf.getvalue()).decode("ascii"), [i + 1 for i in keep]


def extract(pdf_path: str) -> Part:
    client = anthropic.Anthropic(api_key=KEY_FILE.read_text(encoding="utf-8").strip(), max_retries=3)
    data, pages = pdf_subset_b64(pdf_path)
    print(f"sending datasheet pages {pages} to {MODEL}", file=sys.stderr)
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=32000,
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": anthropic.transform_schema(Part)}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",                       # re-run on another model if a safety classifier declines
        messages=[{"role": "user", "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": data},
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Extract the part record: manufacturer, part number, orderable variants, "
                                     "every package with full pin table, outline dimensions and land pattern."},
        ]}],
    ) as stream:
        chars = 0
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                chars += len(event.delta.text)
                print(f"\rreceiving JSON: {chars} chars", end="", file=sys.stderr)
        final = stream.get_final_message()
    if final.stop_reason != "end_turn":           # refusal / max_tokens: output may not match the schema
        raise RuntimeError(f"extraction stopped: {final.stop_reason} {final.stop_details}")
    blocks = final.content                        # after a mid-stream fallback only text after the last
    start = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1) + 1   # fallback block counts
    part = Part.model_validate_json("".join(b.text for b in blocks[start:] if b.type == "text"))
    u = final.usage
    print(f"\nserved by {final.model}; tokens in={u.input_tokens} cache_write={u.cache_creation_input_tokens} "
          f"cache_read={u.cache_read_input_tokens} out={u.output_tokens}", file=sys.stderr)
    return part


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(extract(sys.argv[1]).model_dump_json(indent=1))
```

Notes:
- The `fallback`-block slicing follows the documented behavior, but **no refusal or fallback happened** in any test (UNVERIFIED path).
- The PDF-only path above is verified. For the full pipeline, use `scripts/extract.py` (progress, metrics, page mapping, full schema) and `scripts/followup_pass.py` (cached verification pass with renders).

Async variant (VERIFIED with a small schema on Haiku 5.5, `scripts/tiny_checks.py`):

```python
aclient = anthropic.AsyncAnthropic(api_key=load_api_key(), max_retries=3)
async with aclient.messages.stream(
    model="claude-haiku-5-5", max_tokens=2000, output_config={"effort": "low"}, output_format=Pins,
    messages=[{"role": "user", "content": "An LM358 in SOIC-8: list pins 1-3 (number, name)."}],
) as stream:
    async for ev in stream:
        pass
    final = await stream.get_final_message()
# final.parsed_output -> Pins(pins=[Pin(number='1', name='OUT1'), Pin(number='2', name='IN1-'), Pin(number='3', name='IN1+')])
```

---

## 10. Proposed PartForge pipeline (UNVERIFIED design built from the verified pieces)

1. **Drop the PDF.** Compute its SHA-256 and look it up in the local result cache, so the same file is never extracted twice.
2. **Choose pages** with the pypdf heuristic (§3.3). Add Haiku triage (≈ $0.001) when the heuristic finds too few pages or there is no text layer. Count tokens (free) and show the cost estimate in the UI.
3. **Extract** with Opus 5.5 at `low`, the combined frozen schema, the cache breakpoint on the document, and streaming progress to the UI over SSE.
4. **Validate** in code (§4.3). Map the `-1` sentinel to NULL. Compute IPC-7351B names and land patterns in code; the datasheet land pattern takes precedence when `present_in_datasheet`.
5. **If validation fails or the package is dense,** append a verification turn to the same conversation with 200 to 300 dpi renders or crops of the flagged pages (cache hit), at effort `medium`.
6. **Optional consensus** with Haiku 5.5. Show diffs to the user.
7. **Persist** the JSON, `request_id`, usage and cost in an audit table. Then generate the DB rows, SchLib symbol and PcbLib footprint through the Altium bridge (other agents).
8. **Series or bulk imports** (no user waiting) go through the Message Batches API at −50 % (DOC; not tested here).

---

## 11. Risks and open questions

- **n = 1 datasheet** (a clean TI layout). Quality on QFN/BGA, multi-part datasheets, Chinese or Japanese datasheets and scanned PDFs is unknown. Build an eval set before fixing defaults.
- The **grammar-size limit** is internal and was not predictable from the documented limits: 10 unions failed, even though the documented limit is 16. Every schema change needs a compile probe, and the `-1` sentinel relies on the model following instructions (all runs did).
- **Pricing doc conflict** for Sonnet 5.5 cache reads ($0.20 vs $0.10 per MTok).
- **Haiku 5.5 is brand new** (released 2026-10-07):
  - It thinks a lot even at `low` (4.7k tokens), so it is slow end to end.
  - It accepted `fallbacks="default"`, but its docs say it has no server-side fallback.
  - The cache-hit observation after an effort change was made only once.
- **Preserved thinking:** Opus, Sonnet and Haiku 5.5 thinking blocks are bound to the conversation and the account. Multi-turn verification must stay append-only (DOC). Whether this account was created after 2026-08-31 (strict enforcement) is unknown.
- **Files API** is not ZDR-eligible and is workspace-scoped. The key currently lives in another project's `.secret` folder; PartForge needs its own secret handling.
- The PDF pipeline's page-image resolution (about 1.2 MP) is inferred from token counts and not documented.
- The fallback and refusal code paths were not exercised. No refusal occurred.
- The Altium pin-type mapping (Input/IO/Output/OpenCollector/Passive/HiZ/OpenEmitter/Power) matches Altium's electrical types as I know them, but was not checked against the Altium API in this task.

## Appendix: files produced

All paths are relative to the work folder named at the top.

- `scripts/pf_common.py`: key loading (never printed), price table, cost and usage helpers
- `scripts/check_models.py`, `scripts/tiny_call.py`: Models API check and the 1-token test call
- `scripts/count_tokens.py`: token counts for full PDF, subset, single pages and the 200 dpi PNG
- `scripts/pdf_tools.py`: page selection, pypdf subsetting, pypdfium2 rendering fitted to the vision limits
- `scripts/datasheet_schema.py`: recommended schema; `scripts/datasheet_schema_nullable.py`: the variant rejected for grammar size
- `scripts/schema_probe.py`, `scripts/schema_probe2.py`: grammar compile probes
- `scripts/prompts.py`: frozen system prompt and instruction
- `scripts/extract.py`: streaming extraction with progress and metrics (`<model> <effort> <label> [--fallbacks] [--summarized] [--nothink]`)
- `scripts/evaluate.py`: ground truth and scoring
- `scripts/cache_probe.py`, `scripts/followup_pass.py`: caching behavior
- `scripts/vision_geometry.py`: images-only geometry extraction
- `scripts/files_and_limits.py`: Files API round trip, rate-limit headers, typed errors
- `scripts/page_triage.py`: LLM page triage
- `scripts/tiny_checks.py`: fallbacks acceptance and async streaming
- `scripts/minimal_extract.py`: the §9 sample
- `out/*.json`, `out/*.metrics.json`: raw model outputs and metrics for every run; `out/r200/`: 200 dpi renders of the drawing pages
