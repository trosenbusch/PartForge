"""Footprint names: IPC-7351B (SMD), IPC-7251 draft (THT), PartForge house names, ASCII sanitising.

IPC-7351B number rules (official 2010 IPC/Mentor naming PDF, see ipc-footprints.md §4.1):

* lead span / height / pitch: two decimals, no decimal point, no leading zeros
  (6.00 -> ``600``, 0.95 -> ``95``, 1.27 -> ``127``)
* chip body sizes: one place each side of the decimal point (1.6 -> ``16``, 0.8 -> ``08``)
* height = **maximum** package height, lead span = **nominal**
* last character = density M/N/L (official: not for BGA; PartForge appends M/L to BGA names of the
  non-nominal densities because their lands and courtyards differ, see ``families/bga.py``)
* ``R`` before the density letter = reverse pin order (IPC modifier, e.g. ``-20RN``); used for
  diodes/LEDs whose cathode is on pad 2 (house convention "anode = pin 1")

House names follow the user's TR_* libraries (user-lib-style.md §4.10):
``RES 0603_1608[ RF]``, ``CAP 1210_3225 - 2.5MM``, ``CAP POL 2917_7343``, ICs ``<MFR> <PKG>[ <code>]``;
reversed diode polarity adds `` AK`` (pad 1 = Anode, pad 2 = Kathode) before the density suffix.

Uniqueness (ipc-footprints.md §4.1 "known flaws"): IPC names omit foot length, lead width, EP and
ball size, so different land patterns can share a name. PartForge keeps the plain name for packages
that match a preset (standard dimensions) and appends ``_<TAG>`` (4 hex digits of a hash over the
land-relevant parameters, see ``identity.py``) otherwise; ``FootprintSpec.ipc_name`` always holds the
plain IPC name.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

MAX_NAME_LENGTH = 64
NAME_ALLOWED = re.compile(r"^[A-Za-z0-9_.\-+() ]+$")
_REPLACEMENTS = {
    "×": "x", "µ": "u", "μ": "u", "Ω": "R", "°": "deg", "±": "+-", "ß": "ss",
    "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
    "/": "-", "\\": "-", ":": "-", "*": "x", "?": "", '"': "", "<": "", ">": "", "|": "-",
    ",": ".", ";": "-", "#": "", "&": "+", "'": "", "[": "(", "]": ")", "{": "(", "}": ")",
    "–": "-", "—": "-",
}

# House-name density suffixes: N (IPC Medium) none, L (IPC High) " RF" as in the TR_* libraries.
HOUSE_DENSITY_SUFFIX = {"N": "", "L": " RF", "M": " LD"}
HOUSE_REVERSE_MARK = " AK"  # pad 1 = anode, pad 2 = cathode
TAG_SEPARATOR = "_"


def ascii_name(text: str, max_len: int = MAX_NAME_LENGTH) -> str:
    """Make a library-safe ASCII name: ``[A-Za-z0-9_.\\-+() ]``, at most ``max_len`` characters."""
    out = []
    for ch in str(text):
        if ch in _REPLACEMENTS:
            out.append(_REPLACEMENTS[ch])
            continue
        if NAME_ALLOWED.match(ch):
            out.append(ch)
            continue
        decomposed = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii")
        out.append("".join(c for c in decomposed if NAME_ALLOWED.match(c)) or "_")
    name = re.sub(r"\s+", " ", "".join(out)).strip()
    name = re.sub(r"_+", "_", name)
    if len(name) > max_len:
        name = name[:max_len].rstrip(" -_.")
    return name


def ascii_text(text: str) -> str:
    """Free text (descriptions, parameter values) transliterated to printable ASCII
    (PcbLib descriptions are Latin-1, see ARCHITEKTUR.md §8.2)."""
    special = {"Ω": "Ohm", "µ": "u", "μ": "u", "×": "x", "Ø": "D", "ø": "d", "°": "deg", "±": "+-", "ß": "ss",
               "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "–": "-", "—": "-", "…": "...",
               "„": '"', "“": '"', "”": '"', "‘": "'", "’": "'", "≤": "<=", "≥": ">="}
    out = []
    for ch in str(text):
        if ch in special:
            out.append(special[ch])
        elif 32 <= ord(ch) < 127:
            out.append(ch)
        else:
            out.append(unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode("ascii") or "?")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def name_problems(name: str) -> list[str]:
    """German descriptions of everything that makes ``name`` unusable as footprint name."""
    problems = []
    if not name or not name.strip():
        problems.append("Name ist leer.")
        return problems
    if len(name) > MAX_NAME_LENGTH:
        problems.append(f"Name ist länger als {MAX_NAME_LENGTH} Zeichen.")
    if not NAME_ALLOWED.match(name):
        bad = sorted({c for c in name if not NAME_ALLOWED.match(c)})
        problems.append(f"Name enthält unzulässige Zeichen: {' '.join(bad)}")
    if name != name.strip():
        problems.append("Name beginnt oder endet mit Leerzeichen.")
    return problems


# --------------------------------------------------------------------------- number codes


def _dec(value: float) -> Decimal:
    return Decimal(repr(round(float(value), 6)))


def f2(value: float) -> str:
    """Two decimals, no point, no leading zeros: 6.0 -> "600", 0.95 -> "95", 0.05 -> "5"."""
    n = int((_dec(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return str(n)


def f1(value: float) -> str:
    """Chip body code: one place each side of the decimal point: 1.6 -> "16", 0.8 -> "08"."""
    n = int((_dec(value) * 10).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return str(n).zfill(2)


def short_num(value: float, decimals: int = 2) -> str:
    """Human-readable short number for house names: 3.90 -> "3.9", 3.0 -> "3", 0.65 -> "0.65"."""
    text = f"{round(float(value), decimals):.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def density_suffix(density: str) -> str:
    return density if density in ("M", "N", "L") else "N"


def with_tag(name: str, tag: str | None, max_len: int = MAX_NAME_LENGTH) -> str:
    """``name`` + ``_<tag>``; the base is shortened first so that the tag always survives."""
    if not tag:
        return ascii_name(name, max_len)
    suffix = TAG_SEPARATOR + tag
    base = ascii_name(name, max_len - len(suffix)).rstrip(" -_.")
    return base + suffix


def ipc_reverse(name: str) -> str:
    """IPC "reverse pin order" modifier: ``R`` before the closing density/level letter
    (``SOD3716X135N`` -> ``SOD3716X135RN``, ``DIOAD1016W65L630D230B`` -> ``...D230RB``)."""
    if len(name) >= 2 and name[-1] in "MNLABC":
        return f"{name[:-1]}R{name[-1]}"
    return f"{name}R"


def house_reverse(name: str, density: str) -> str:
    """House marker for diodes with pad 1 = anode, inserted before the density suffix."""
    suffix = HOUSE_DENSITY_SUFFIX.get(density, "")
    if suffix and name.endswith(suffix):
        return ascii_name(name[: len(name) - len(suffix)] + HOUSE_REVERSE_MARK + suffix)
    return ascii_name(name + HOUSE_REVERSE_MARK)


# --------------------------------------------------------------------------- IPC-7351B (SMD)


def ipc_chip(prefix: str, body_length: float, body_width: float, height: float, density: str,
             *, metric_code: str | None = None) -> str:
    """``RESC1608X55N`` (prefix RESC/CAPC/INDC/DIOC/LEDC/CAPMP/DIOM/...)."""
    code = metric_code if metric_code else f1(body_length) + f1(body_width)
    return f"{prefix}{code}X{f2(height)}{density_suffix(density)}"


def ipc_melf(prefix: str, body_length: float, diameter: float, density: str) -> str:
    """``RESMELF3514N`` / ``DIOMELF3515N``."""
    return f"{prefix}{f1(body_length)}{f1(diameter)}{density_suffix(density)}"


def ipc_sod(prefix: str, lead_span: float, body_width: float, height: float, density: str) -> str:
    """``SOD3717X135N`` (official example: JEDEC SOD-123), ``SODFL...`` for flat leads."""
    return f"{prefix}{f1(lead_span)}{f1(body_width)}X{f2(height)}{density_suffix(density)}"


def ipc_pitch_span(prefix: str, pitch: float, lead_span: float, height: float, pins: int, density: str) -> str:
    """``SOIC127P600X175-8N``, ``SOP65P640X120-16N``, ``SOT95P280X145-5N``, ``TO228P970X238-3N``."""
    return f"{prefix}{f2(pitch)}P{f2(lead_span)}X{f2(height)}-{pins}{density_suffix(density)}"


def ipc_qfp(pitch: float, span_1: float, span_2: float, height: float, pins: int, density: str) -> str:
    """``QFP50P900X900X160-48N``."""
    return f"QFP{f2(pitch)}P{f2(span_1)}X{f2(span_2)}X{f2(height)}-{pins}{density_suffix(density)}"


def ipc_qfn(prefix: str, pitch: float, body_width: float, body_length: float, height: float, pins: int,
            density: str) -> str:
    """``QFN50P300X300X100-17N`` (pin quantity includes the thermal pad), also SON/PQFN/PSON."""
    return f"{prefix}{f2(pitch)}P{f2(body_width)}X{f2(body_length)}X{f2(height)}-{pins}{density_suffix(density)}"


def ipc_dfn(body_length: float, body_width: float, height: float, pins: int, density: str) -> str:
    """``DFN200X200X80-9N`` (DFN has no pitch in its name)."""
    return f"DFN{f2(body_length)}X{f2(body_width)}X{f2(height)}-{pins}{density_suffix(density)}"


def ipc_bga(pins: int, collapsible: bool, pitch: float, cols: int, rows: int, body_length: float,
            body_width: float, height: float) -> str:
    """``BGA256C100P16X16_1700X1700X200`` (no density suffix for BGA)."""
    return (f"BGA{pins}{'C' if collapsible else 'N'}{f2(pitch)}P{cols}X{rows}_"
            f"{f2(body_length)}X{f2(body_width)}X{f2(height)}")


# --------------------------------------------------------------------------- IPC-7251 draft (THT)


def ipc_dip(row_spacing: float, lead_width: float, pitch: float, body_length: float, height: float, pins: int,
            level: str) -> str:
    """``DIP762W56P254L958H533Q8B``."""
    return f"DIP{f2(row_spacing)}W{f2(lead_width)}P{f2(pitch)}L{f2(body_length)}H{f2(height)}Q{pins}{level}"


def ipc_axial(prefix: str, spacing: float, lead_diameter: float, body_length: float, body_diameter: float,
              level: str) -> str:
    """``RESAD1016W65L630D250B``."""
    return f"{prefix}{f2(spacing)}W{f2(lead_diameter)}L{f2(body_length)}D{f2(body_diameter)}{level}"


def ipc_radial(prefix: str, spacing: float, lead_diameter: float, body_diameter: float, height: float,
               level: str) -> str:
    """``CAPPRD200W55D500H1100B``."""
    return f"{prefix}{f2(spacing)}W{f2(lead_diameter)}D{f2(body_diameter)}H{f2(height)}{level}"


def ipc_header(pins: int, lead_width: float, pitch: float, rows: int, per_row: int, body_length: float,
               body_thickness: float, height: float, level: str) -> str:
    """``HDRV10W64P254_1X10_2540X254X854B``."""
    return (f"HDRV{pins}W{f2(lead_width)}P{f2(pitch)}_{rows}X{per_row}_"
            f"{f2(body_length)}X{f2(body_thickness)}X{f2(height)}{level}")


def ipc_to_tht(base: str, pitch: float, pins: int, level: str) -> str:
    """Transistor outlines (exact IPC-7251 format unknown): ``TO92P127-3B``, ``TO220VP254-3B``."""
    return f"{base}P{f2(pitch)}-{pins}{level}"


# --------------------------------------------------------------------------- house names


def house(base: str, density: str, *, manufacturer: str = "", code: str = "", extra: str = "") -> str:
    """``[<MFR> ]<base>[ <code>][ <extra>]<density suffix>`` sanitised to ASCII."""
    parts = [p for p in (manufacturer.strip(), base.strip(), code.strip(), extra.strip()) if p]
    return ascii_name(" ".join(parts) + HOUSE_DENSITY_SUFFIX.get(density, ""))


def house_body(width: float, length: float) -> str:
    """``3.9x4.9MM``."""
    return f"{short_num(width)}x{short_num(length)}MM"


def house_passive(type_code: str, size: str, density: str, *, height: float | None = None) -> str:
    """``RES 0603_1608``, ``CAP 1206_3216 RF``, ``CAP 1210_3225 - 2.5MM`` (TR_Passives pattern
    ``<TYPE> <imperial>_<metric>[ RF][ - <height>MM]``)."""
    name = f"{type_code} {size}{HOUSE_DENSITY_SUFFIX.get(density, '')}"
    if height is not None:
        name += f" - {short_num(height, 2)}MM"
    return ascii_name(name)
