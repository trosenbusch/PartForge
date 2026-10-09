"""Choose a standard symbol for a part from its category table and field values.

Used by the part editor, the series assistant and the datasheet import to suggest a generic
DbLib symbol. Discrete symbols hide their pin numbers (house style), so a wrong pin map would
be invisible in the schematic and in the preview. A suggestion therefore only carries a ready
:class:`SymbolRequest` when the pinout is certain:

* the kind has no package-dependent pinout (resistor, capacitor, 2-terminal diodes ...),
* the package is recognised and numbered uniformly (SOT-23 transistors 1=B/G 2=E/S 3=C/D,
  SOT-89/DPAK/D2PAK/TO-220 B-C-E / G-D-S, SOT-223 tab 4, SO-8 and power-DFN MOSFETs ...),
* the part's pin table (datasheet import) names every function, or
* the footprint pads confirm it (a tab or exposed pad joins the MOSFET drain / BJT collector).

Otherwise :func:`suggest_symbol` names the fitting kind with ``needs_pinmap`` and the
candidate presets (TO-92, TO-126, SOT-23-6, single op-amps in SOT-23-5, relays ...), and
:func:`standard_symbol_for` returns ``None``.

Package names are read from ``Package``, ``Case/Package`` and ``Footprint Ref`` (free text
like ``TO-252 (DPAK)`` or ``DFN-8 5x6`` and IPC-7351 names like ``SOT95P237X112-3N``); a
:class:`~partforge.geometry.model.FootprintSpec` or pad list passed in wins over the text.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from ..geometry.model import FootprintSpec, SymbolSpec
from ..workspace import FootprintStyle, SymbolStyle
from .errors import SymbolError
from .models import IcPin, SuggestionSource, SymbolRequest, SymbolSuggestion
from .pinmap import NC_CHARS, PinMapSpec, ResolvedPinMap, resolve_pinmap
from .standard import build_standard, get_kind, is_diode_kind, kind_pinmap, tab_function
from .style import StyleKit
from .text import display_text
from .util import natural_key

log = logging.getLogger(__name__)

__all__ = ["NC_PADS_KEY", "UNUSED_PADS_OK", "free_pads", "standard_symbol_for", "suggest_symbol", "symbol_kind",
           "unused_pads_ok"]

_TRUE = {"ja", "yes", "true", "1", "y", "x", "wahr", "on"}
_FALSE = {"nein", "no", "false", "0", "n", "falsch", "off"}


class _Values:
    """Case-insensitive, whitespace-tolerant access to part field values."""

    def __init__(self, values: Mapping[str, Any]) -> None:
        self._data: dict[str, str] = {}
        for key, value in (values or {}).items():
            if value is None:
                continue
            self._data[str(key).strip().lower()] = str(value).strip()

    def get(self, *keys: str) -> str:
        for key in keys:
            value = self._data.get(key.lower())
            if value:
                return value
        return ""

    def text(self) -> str:
        return " ".join(self._data.values())

    def flag(self, key: str) -> bool | None:
        value = self.get(key).lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        return None

    def number(self, key: str) -> int | None:
        value = self.get(key).replace(",", ".")
        m = re.match(r"^\s*(\d+(?:\.0+)?)\b", value)
        return int(float(m.group(1))) if m else None


def _norm(text: str) -> str:
    return re.sub(r"[\s_]+", "", text).upper()


# ======================================================================================
# packages
# ======================================================================================
@dataclass(frozen=True)
class _Pkg:
    """Recognised package: coarse family plus the number of pads/terminals (``None`` = unknown)."""

    family: str | None = None
    label: str = ""
    pads: int | None = None  # all pads incl. tab / exposed pad
    leads: int | None = None  # pads without the exposed pad (no-lead packages)
    ep: bool | None = None  # exposed pad present (None = unknown)
    text: str = ""  # normalised source text ("" = no package information at all)
    from_footprint: bool = False  # derived from the actual footprint pads

    @property
    def known(self) -> bool:
        return self.family is not None


def _ntext(text: str) -> str:
    """Upper case, separators unified to '-' (keeps token boundaries: 'DFN-8 5x6' -> 'DFN-8-5X6')."""
    t = text.upper().replace("²", "2").replace("µ", "U").replace("Μ", "U")
    t = re.sub(r"[^A-Z0-9.+/]+", "-", t)
    return re.sub(r"-{2,}", "-", t).strip("-")


_B = r"(?<![A-Z0-9])"
_E = r"(?![A-Z0-9])"
_END = r"(?![A-Z0-9])(?!-\d)"  # no further pin-count suffix ("SOT-23" must not match "SOT-23-5")
_DIMS = r"(?:-?\d+(?:\.\d+)?X\d+(?:\.\d+)?)"

# IPC-7351 footprint names (whole string)
_IPC_SOT = re.compile(r"^SOT(\d+)P\d+X\d+-(\d+)[NML]$")
_IPC_SOT89 = re.compile(r"^SOT89[NML]?$")
_IPC_TO_SMD = re.compile(r"^TO(\d+)P\d+X\d+-(\d+)[NML]$")  # DPAK / D2PAK family
_IPC_TO220 = re.compile(r"^TO-?220[A-Z]*P?\d*-(\d+)[A-Z]$")
_IPC_TO92 = re.compile(r"^TO-?92[A-Z]*P?\d*-(\d+)[A-Z]$")
_IPC_SOIC = re.compile(r"^SOIC(\d+)P\d+X\d+-(\d+)[NML]$")
_IPC_SOP = re.compile(r"^SOP(\d+)P\d+X\d+-(\d+)[NML]$")
_IPC_NOLEAD = re.compile(r"^(?:DFN|SON|QFN)(?:\d+P)?\d+X\d+X\d+-(\d+)[NML]$")
_IPC_QFP = re.compile(r"^(?:L|T)?QFP\d+P\d+X\d+X\d+-(\d+)[NML]$")
_IPC_DIP = re.compile(r"^DIP\d+W\d+P\d+L\d+H\d+Q(\d+)[A-Z]?$")
_IPC_TWO = re.compile(
    r"^(?:SODFL|SOD|DIOM|DIOC|DIOMELF|DIOAD|DIOAX|DIOSM[ABC]|LEDC|LEDM|RESC|CAPC|INDC|CAPMP|CAPM|INDM|RESMELF|CAPAE)\d"
)
_IPC_BGA = re.compile(r"^[A-Z]{0,4}BGA\d")

# free-text rules: (family, label, pads, pattern); first match wins; group "n" = pad count
_TEXT_RULES: list[tuple[str, str, int | None, re.Pattern[str]]] = [
    (
        "bga",
        "BGA/CSP",
        None,
        re.compile(rf"{_B}(?:[A-Z]{{0,4}}BGA|WLCSP|[A-Z]{{0,3}}CSP|LGA|UCSP)(?:-?\d+)?{_E}"),
    ),
    ("lfpak", "LFPAK", None, re.compile(rf"{_B}(?:LFPAK(?:33|56D?|56E|88)?|SOT-?669|SOT-?1210|SOT-?1023|SOT-?1235)")),
    (
        "dfn",
        "Power-DFN-8 (mit Drain-Pad)",
        8,
        re.compile(
            rf"{_B}(?:POWER-?PAK(?:-?SO-?8|-?1212-?8)?|SUPER-?SO-?8|SO-?8-?FL|TDSON-?8(?:-?FL)?|TSDSON-?8"
            rf"|PG-?TDSON-?8|PG-?TSDSON-?8|PQFN(?:-?8)?{_DIMS}?|POWER-?DI-?(?:5060|3333)(?:-?8)?|POWER-?SO-?8"
            rf"|(?:8-?)?POWER[TVWU]?DFN(?:-?8)?{_DIMS}?|WPAK|DFN-?5X6|DFN-?3X3|DFN-?3\.3X3\.3|SON-?5X6|SON-?3X3"
            rf"|QFN-?5X6|PDFN(?:-?8)?{_DIMS}?){_E}"
        ),
    ),
    (
        "sot5",
        "SOT-23-5",
        5,
        re.compile(rf"{_B}(?:T?SOT-?23-?5|SC-?70-?5|SOT-?353|SC-?88A|SOT-?25|SOT-?753|SC-?74A)L?{_END}"),
    ),
    (
        "sot6",
        "SOT-23-6",
        6,
        re.compile(
            rf"{_B}(?:T?SOT-?23-?6|TSOP-?6|SC-?74|SOT-?457|SC-?70-?6|SOT-?363|SC-?88|SOT-?26|US6|SOT-?563)L?{_END}"
        ),
    ),
    ("sot143", "SOT-143", 4, re.compile(rf"{_B}(?:SOT-?143[BR]?|TO-?253(?:AA)?|SC-?61)(?:-?4)?{_END}")),
    ("sot223", "SOT-223", 4, re.compile(rf"{_B}(?:SOT-?223|TO-?261(?:AA)?|SC-?73|DCY)(?:-?[34])?{_END}")),
    ("sot89", "SOT-89", 3, re.compile(rf"{_B}(?:SOT-?89|TO-?243(?:AA)?|SC-?62|UPAK)(?:-?3)?{_END}")),
    (
        "sot3",
        "SOT-23",
        3,
        re.compile(
            rf"{_B}(?:SOT-?23|TO-?236(?:AA|AB)?|SC-?59A?|SOT-?346|SOT-?323|SC-?70|SOT-?416|SC-?75A?|SOT-?523|SC-?89"
            rf"|SOT-?490|SOT-?723|SOT-?883B?|SOT-?923|(?:X\d-)?DFN-?1006B?-?3|EMT3|UMT3|SMT3|VMT3)(?:-?3L?)?{_END}"
        ),
    ),
    ("dpak", "DPAK/D2PAK (5/7 Beinchen)", None, re.compile(rf"{_B}(?:TO-?252|TO-?263|D2?-?PAK|DDPAK)-?[5-9]L?{_E}")),
    ("dpak", "DPAK (3 Beinchen + Fahne)", 4, re.compile(rf"{_B}(?:TO-?252|TO-?263)-?4L?{_END}")),
    (
        "dpak",
        "DPAK/D2PAK",
        3,
        re.compile(
            rf"{_B}(?:D-?PAK|D2-?PAK|D3-?PAK|DDPAK|TO-?252(?:AA|AB|AC)?|TO-?263(?:AA|AB|AC)?|TO-?268(?:AA)?"
            rf"|SC-?63|SC-?83)"
            rf"(?:-?[23]L?)?{_END}"
        ),
    ),
    (
        "to220",
        "TO-220 (2-polig)",
        2,
        re.compile(rf"{_B}(?:TO-?220(?:AC|F?-?2L?)|ITO-?220AC|TO-?247(?:AC)?-?2L?){_E}"),
    ),
    ("to220", "TO-247-4", 4, re.compile(rf"{_B}TO-?247-?4L?{_E}")),
    ("to220", "TO-220 (mehrpolig)", None, re.compile(rf"{_B}TO-?220-?[5-9]L?{_E}")),
    (
        "to220",
        "TO-220/TO-247",
        3,
        re.compile(
            rf"{_B}(?:TO-?220(?:AB|F|FP|FULLPAK|IS|ISO)?|ITO-?220(?:AB)?|TO-?247(?:AC|AD)?|TO-?3P(?:N|F|FM)?"
            rf"|TO-?218(?:AC)?"
            rf"|TO-?262(?:AA)?|I2-?PAK|I-?PAK|TO-?251(?:AA)?|TO-?264(?:AA)?|SOT-?78|SOT-?186A?|SOT-?429|SUPER-?247"
            rf"|MAX-?247|PLUS-?247)(?:-?3L?)?{_END}"
        ),
    ),
    (
        "to92",
        "TO-92",
        3,
        re.compile(rf"{_B}(?:TO-?92(?:L|S|MOD)?|TO-?226(?:AA)?|SC-?43A?|SOT-?54|E-?LINE)(?:-?3L?)?{_END}"),
    ),
    ("to126", "TO-126", 3, re.compile(rf"{_B}(?:TO-?126|TO-?225(?:AA)?|SOT-?32|SOT-?82)(?:-?3)?{_END}")),
    ("two", "2-polig", 2, re.compile(rf"{_B}(?:X\d-?)?(?:[TVWUX]{{0,2}}DFN|DSN)\d{{4}}[A-Z]?-?2{_END}")),
    (
        "dfn",
        "DFN/QFN",
        None,
        re.compile(
            rf"{_B}(?:X\d-?)?(?:[TVWUX]{{0,2}}DFN|[TVWUH]{{0,2}}SON|[TVWUH]{{0,2}}QFN|DQFN)(?:{_DIMS}|\d{{4}}[A-Z]?)?"
            rf"-?(?P<n>\d{{1,3}})(?:-?(?:EP|PAD|L))?{_DIMS}?{_END}"
        ),
    ),
    (
        "so",
        "SO",
        None,
        re.compile(rf"{_B}(?:SO|SOIC|SOP)-?(?P<n>\d{{1,2}})(?:-?(?:N|W|NB|WB|L))?{_END}"),
    ),
    ("so", "SO", None, re.compile(rf"{_B}(?P<n>\d{{1,2}})-?(?:SOIC|SO|SOP)(?:-?(?:N|W))?{_END}")),
    (
        "msop",
        "MSOP/TSSOP",
        None,
        re.compile(
            rf"{_B}(?:MSOP|VSSOP|TSSOP|HTSSOP|SSOP|QSOP|U?MAX|MICRO|US|TSOP|LSSOP|VSOP)-?(?P<n>\d{{1,2}})"
            rf"(?:-?(?:EP|PAD))?{_END}"
        ),
    ),
    ("msop", "MSOP/TSSOP", None, re.compile(rf"{_B}(?P<n>\d{{1,2}})-?(?:MSOP|VSSOP|TSSOP|SSOP|QSOP|TSOP){_END}")),
    ("msop", "VSSOP-8", 8, re.compile(rf"{_B}DGK{_E}")),
    (
        "dip",
        "DIP",
        None,
        re.compile(rf"{_B}(?:P?DIP|CDIP|SDIP|DIL|MDIP)-?(?P<n>\d{{1,2}})(?:-?(?:W|N|300|600|MIL))?{_END}"),
    ),
    ("dip", "DIP", None, re.compile(rf"{_B}(?P<n>\d{{1,2}})-?(?:P?DIP|DIL)(?:-?W)?{_END}")),
    ("plcc", "PLCC", None, re.compile(rf"{_B}PLCC-?(?P<n>[246]){_END}")),
    ("sip4", "SIP-4 (KBP/GBU)", 4, re.compile(rf"{_B}(?:KBPM?|KBL|KBU|KBJ|GBU|GBJ|GBL|SIP-?4|4-?SIP)")),
    (
        "two",
        "2-polig",
        2,
        re.compile(
            rf"{_B}(?:SOD-?\d{{2,3}}(?:F|FL|HE|C)?|SMA|SMB|SMC|SMA-?FL|SMAF|SMBF|SMF|SMP"
            rf"|DO-?\d{{2,3}}(?:A[A-F]|B[A-F])?"
            rf"|MINI-?MELF|MICRO-?MELF|MELF|POWER-?DI-?123|POWERMITE|DSN\d{{4}}-?2|(?:X\d-)?DFN\d{{4}}B?-?2|AXIAL"
            rf"|CFP\d|LL-?34|LL-?41|0201|0402|0603|0805|1206|1210|1806|1812|2010|2512|01005|1005|1608|2012|3216)"
            rf"(?:-?2)?{_END}"
        ),
    ),
    (
        "two",
        "LED bedrahtet",
        2,
        re.compile(rf"{_B}(?:(?:LED-?)?(?:1\.8|3|5|8|10)-?MM|T-?1(?:-?3/4)?){_E}"),
    ),
    (
        "npin",
        "n-polig",
        None,
        re.compile(rf"{_B}(?:SMD|LSOP|MFP|MINI-?FLAT|SSOP|SDIP|LSDIP)-?(?P<n>\d{{1,2}}){_END}"),
    ),
    (
        "npin",
        "n-polig",
        None,
        re.compile(rf"{_B}(?P<n>\d{{1,2}})-?(?:PIN|POL|PAD|LEAD|TERMINAL|SMD|MFP)S?(?:IG)?{_E}"),
    ),
]
_SOURCE_DOWN = re.compile(rf"{_B}SOURCE-?DOWN{_E}")
_FAMILY_LABEL = {"so": "SO", "msop": "MSOP/TSSOP", "dip": "DIP", "dfn": "DFN/QFN", "plcc": "PLCC", "npin": ""}


def _with_count(family: str, label: str, n: int) -> str:
    base = _FAMILY_LABEL.get(family, label)
    return f"{base}-{n}" if base else f"{n}-polig"


def _classify_text(raw: str) -> _Pkg:
    """Package from free text or an IPC footprint name."""
    t = _ntext(raw)
    if not t:
        return _Pkg()
    if m := _IPC_SOT.match(t):
        pitch, n = int(m.group(1)), int(m.group(2))
        family = {3: "sot3", 5: "sot5", 6: "sot6"}.get(n) or ("sot223" if n == 4 and pitch >= 200 else "sot143")
        if n not in (3, 4, 5, 6):
            return _Pkg("npin", f"{n}-polig", n, text=t)
        label = {"sot3": "SOT-23", "sot5": "SOT-23-5", "sot6": "SOT-23-6", "sot223": "SOT-223", "sot143": "SOT-143"}
        return _Pkg(family, label[family], n, text=t)
    if _IPC_SOT89.match(t):
        return _Pkg("sot89", "SOT-89", 3, text=t)
    if m := _IPC_TO_SMD.match(t):
        n = int(m.group(2))
        label = "DPAK/D2PAK" if n == 3 else ("DPAK (3 Beinchen + Fahne)" if n == 4 else f"DPAK/D2PAK ({n} Pads)")
        return _Pkg("dpak", label, n, text=t)
    if m := _IPC_TO220.match(t):
        return _Pkg("to220", "TO-220", int(m.group(1)), text=t)
    if m := _IPC_TO92.match(t):
        return _Pkg("to92", "TO-92", int(m.group(1)), text=t)
    if m := _IPC_SOIC.match(t):
        return _Pkg("so", f"SO-{m.group(2)}", int(m.group(2)), text=t)
    if m := _IPC_SOP.match(t):
        n = int(m.group(2))
        return _Pkg("so" if m.group(1) == "127" else "msop", f"SOP-{n}", n, text=t)
    if m := _IPC_NOLEAD.match(t):
        n = int(m.group(1))
        ep = n % 2 == 1  # IPC counts the thermal pad: "-9N" = 8 leads + EP
        leads = n - 1 if ep else n
        return _Pkg("dfn", f"DFN/QFN-{leads}" + (" mit EP" if ep else ""), n, leads, ep, text=t)
    if m := _IPC_QFP.match(t):
        return _Pkg("qfp", f"QFP-{m.group(1)}", int(m.group(1)), text=t)
    if m := _IPC_DIP.match(t):
        return _Pkg("dip", f"DIP-{m.group(1)}", int(m.group(1)), text=t)
    if _IPC_TWO.match(t):
        return _Pkg("two", "2-polig", 2, text=t)
    if _IPC_BGA.match(t):
        return _Pkg("bga", "BGA/CSP", text=t)
    for family, label, pads, pattern in _TEXT_RULES:
        m = pattern.search(t)
        if m is None:
            continue
        n = pads
        if "n" in pattern.groupindex and m.group("n"):
            n = int(m.group("n"))
            label = _with_count(family, label, n)
        if family == "dfn":
            ep = True if label.startswith("Power") else None
            return _Pkg(family, label, n, n, ep, text=t)
        return _Pkg(family, label, n, text=t)
    return _Pkg(text=t)


@dataclass(frozen=True)
class _Footprint:
    """What the suggestion needs to know about the footprint."""

    pads: tuple[str, ...]
    thermal: frozenset[str] = frozenset()
    family: str | None = None
    cathode_pad: str | None = None
    name: str = ""
    variant: str = ""


def _footprint_info(footprint: FootprintSpec | Sequence[str] | None) -> _Footprint | None:
    if footprint is None:
        return None
    if isinstance(footprint, FootprintSpec):
        params = (footprint.generator or {}).get("params") or {}
        cathode = params.get("cathode_pad")
        return _Footprint(
            pads=tuple(footprint.pad_designators()),
            thermal=frozenset(p.designator for p in footprint.pads if p.thermal and p.designator),
            family=footprint.family or None,
            cathode_pad=str(cathode) if cathode is not None else None,
            name=footprint.name,
            variant=str(params.get("variant") or ""),
        )
    pads = tuple(dict.fromkeys(str(p).strip() for p in footprint if str(p).strip()))
    return _Footprint(pads=pads)


_FP_FAMILIES = {
    "sot89": ("sot89", "SOT-89"),
    "sot223": ("sot223", "SOT-223"),
    "dpak": ("dpak", "DPAK/D2PAK"),
    "to92": ("to92", "TO-92"),
    "to220": ("to220", "TO-220"),
    "dip": ("dip", "DIP"),
    "qfp": ("qfp", "QFP"),
    "bga": ("bga", "BGA"),
    "pin_header": ("header", "Stiftleiste"),
}
_FP_TWO = {"chip", "sod", "do214", "melf", "molded", "axial", "radial"}


def _package_from_footprint(fp: _Footprint) -> _Pkg:
    pkg = _package_from_footprint_raw(fp)
    return _Pkg(pkg.family, pkg.label, pkg.pads, pkg.leads, pkg.ep, pkg.text, from_footprint=True)


def _package_from_footprint_raw(fp: _Footprint) -> _Pkg:
    n = len(fp.pads)
    fam = fp.family
    if fam in ("sot23", "sc70", "sot523"):
        family = {3: "sot3", 5: "sot5", 6: "sot6"}.get(n)
        if family:
            return _Pkg(family, {"sot3": "SOT-23", "sot5": "SOT-23-5", "sot6": "SOT-23-6"}[family], n, text=fp.name)
    elif fam in _FP_FAMILIES:
        family, label = _FP_FAMILIES[fam]
        return _Pkg(family, label if family not in ("dip", "qfp") else f"{label}-{n}", n, text=fp.name)
    elif fam == "nolead":
        leads = n - len(fp.thermal)
        return _Pkg("dfn", f"DFN/QFN-{leads}" + (" mit EP" if fp.thermal else ""), n, leads, bool(fp.thermal), fp.name)
    elif fam == "gullwing":
        family = "so" if fp.variant.upper().startswith("SOIC") or fp.name.startswith("SOIC") else "msop"
        return _Pkg(family, f"{fp.variant or 'SO'}-{n}", n, text=fp.name)
    elif fam in _FP_TWO and n == 2:
        return _Pkg("two", "2-polig", 2, text=fp.name)
    by_name = _classify_text(fp.name) if fp.name else _Pkg()
    if by_name.known and (by_name.pads is None or by_name.pads == n):
        return by_name
    return _Pkg("npin" if n else None, f"{n}-polig" if n else "", n or None, text=fp.name)


def _text_package(v: _Values) -> _Pkg:
    """Footprint Ref > Package > Case/Package (the first recognised one)."""
    first = _Pkg()
    for key in ("Footprint Ref", "Package", "Case/Package"):
        raw = v.get(key)
        if not raw:
            continue
        pkg = _classify_text(raw)
        if pkg.known:
            return pkg
        if not first.text:
            first = pkg
    return first


def _detect_package(v: _Values, fp: _Footprint | None) -> _Pkg:
    """The footprint (spec or pad list) wins; a bare pad list only contributes the pad count."""
    text = _text_package(v)
    if fp is None or not fp.pads:
        return text
    pkg = _package_from_footprint(fp)
    if pkg.family in (None, "npin") and text.known:
        n = len(fp.pads)
        leads = text.leads if text.leads is not None else text.pads
        if leads is not None and leads > n:
            leads = None
        ep = (n > leads) if leads is not None else text.ep
        return replace(text, pads=n, leads=leads, ep=ep, from_footprint=True)
    return pkg


def _exposed_pad_designator(leads: int) -> str:
    """Designator of the exposed pad in PartForge footprints (workspace footprint style)."""
    from ..workspace import current_or_none  # runtime lookup, no import-time state

    ws = current_or_none()
    style = ws.settings.footprint if ws is not None else FootprintStyle()
    return "EP" if style.exposed_pad_designator == "EP" else str(leads + 1)


# ======================================================================================
# drafts per category
# ======================================================================================
@dataclass
class _Draft:
    kind: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    needs_pinmap: bool = False
    options: tuple[str, ...] = ()
    alternatives: tuple[str, ...] = ()
    messages: list[str] = field(default_factory=list)
    source: SuggestionSource | None = None
    failed: bool = False  # the kind fits in principle, but pins/pads contradict it


def _ok(kind: str, *, source: SuggestionSource = "standard", message: str = "", **params: Any) -> _Draft:
    return _Draft(
        kind=kind,
        params={k: p for k, p in params.items() if p is not None},
        source=source,
        messages=[message] if message else [],
    )


def _ask(kind: str, options: Sequence[str], message: str, **params: Any) -> _Draft:
    return _Draft(
        kind=kind,
        params={k: p for k, p in params.items() if p is not None},
        needs_pinmap=True,
        options=tuple(options),
        messages=[message],
    )


def _none(message: str = "", alternatives: Sequence[str] = ()) -> _Draft:
    return _Draft(messages=[message] if message else [], alternatives=tuple(alternatives))


def _pkg_hint(pkg: _Pkg) -> str:
    if pkg.known:
        return f"Gehäuse {pkg.label}"
    return f"Gehäuse „{pkg.text}“ nicht erkannt" if pkg.text else "Gehäuse unbekannt"


def _multi_terminal(pkg: _Pkg, limit: int = 2) -> bool:
    return pkg.pads is not None and pkg.pads > limit


_BJT_OPTIONS = ("BEC", "EBC", "CBE", "BCE", "ECB", "CEB", "BCEC")
_FET_OPTIONS = ("GSD", "GDS", "SGD", "DGS", "GDSD", "SSSGDDDD", "SSSGDDDDD", "SSSGDDDD+EP", "DDGSDD")
_DIODE_OPTIONS = ("KA", "AK", "AxK", "KxA")


def _two_terminal(kind: str, what: str, pkg: _Pkg) -> _Draft:
    if _multi_terminal(pkg):
        return _none(f"{what}: {_pkg_hint(pkg)} hat {pkg.pads} Anschlüsse – kein 2-poliges Standardsymbol.")
    return _ok(kind)


def _resistors(v: _Values, pkg: _Pkg) -> _Draft:
    tech = _norm(v.get("Technology"))
    if any(key in tech for key in ("NETZWERK", "NETWORK", "ARRAY")):
        return _none("Widerstandsnetzwerk – bitte ein IC-Symbol aus der Pinliste verwenden.")
    return _two_terminal("resistor", "Widerstand", pkg)


def _capacitors(v: _Values, pkg: _Pkg) -> _Draft:
    if "ARRAY" in _norm(v.get("Type")):
        return _none("Kondensator-Array – bitte ein IC-Symbol aus der Pinliste verwenden.")
    polarized = v.flag("Polarized")
    if polarized is None:
        kind_text = _norm(v.get("Type") + " " + v.get("Dielectric"))
        polarized = any(
            key in kind_text for key in ("TANTAL", "ALUMINIUM", "ALUMINUM", "ELKO", "POLYMER", "SUPERKONDENSATOR")
        )
    if _multi_terminal(pkg):
        return _none(f"Kondensator: {_pkg_hint(pkg)} hat {pkg.pads} Anschlüsse (z. B. Durchführungsfilter).")
    return _ok("capacitor_polarized" if polarized else "capacitor")


def _diode_draft(kind: str, pkg: _Pkg) -> _Draft:
    """Diode-family pin map from the package (pin 1 = cathode on 2-terminal IPC footprints)."""
    if pkg.family == "sot3":
        return _ok(kind, source="package", pinmap="AxK", message="SOT-23: Pin 1 = Anode, Pin 3 = Kathode.")
    if pkg.family == "two" or (pkg.family in (None, "npin", "plcc") and pkg.pads == 2):
        return _ok(kind)
    if not pkg.known and pkg.pads is None:
        if not pkg.text:
            return _ok(kind)
        return _ok(kind, message=f"{_pkg_hint(pkg)} – 2-polig angenommen (Kathode/Anode laut Hausstil).")
    return _ask(
        kind,
        _DIODE_OPTIONS,
        f"{_pkg_hint(pkg)}: Die Anschlussbelegung der Diode hängt vom Gehäuse ab – bitte wählen.",
    )


def _diodes(v: _Values, pkg: _Pkg) -> _Draft:
    config = _norm(v.get("Configuration"))
    if config.startswith(("DOPPEL", "DUAL", "ARRAY", "TRIPLE", "QUAD", "VIERFACH")):
        return _none("Mehrfachdiode – bitte ein IC-Symbol aus der Pinliste verwenden.")
    dtype = _norm(v.get("Diode Type", "Type"))
    if "BRÜCKE" in dtype or "BRUECKE" in dtype or "BRIDGE" in dtype:
        if pkg.family == "sip4":
            return _ok("bridge_rectifier", source="package")
        return _ask(
            "bridge_rectifier",
            ("+AA-", "AA+-", "A+A-", "A+-A", "+-AA"),
            f"Brückengleichrichter: {_pkg_hint(pkg)} – Belegung von +, − und ~ bitte wählen.",
        )
    if "SCHOTTKY" in dtype:
        return _diode_draft("schottky", pkg)
    if dtype.startswith("Z") or "ZENER" in dtype:
        return _diode_draft("zener", pkg)
    if "TVS" in dtype or "SUPPRESSOR" in dtype:
        bidirectional = (
            config.startswith(("BIDIREK", "BIDIREC"))
            or bool(_BIDIR.search(v.get("Description")))
            or bool(_TVS_BI_MPN.match(_norm(v.get("Manufacturer Part Number", "Part Number"))))
        )
        if bidirectional:
            return _two_terminal("tvs_bi", "Bidirektionale TVS-Diode", pkg)
        return _diode_draft("tvs_uni", pkg)
    return _diode_draft("diode", pkg)


_TVS_BI_MPN = re.compile(
    r"^(?:SMAJ|SMBJ|SMCJ|SMDJ|P4SMA|P6SMB|P4KE|P6KE|1\.5KE|1\.5SMC|SMF|SMLJ|TPSMA|TPSMB)\S*?\d+(?:\.\d+)?CA"
)
_BIDIR = re.compile(r"bi-?direktional|bi-?directional|\bbidir", re.I)
_OPEN_DRAIN = re.compile(r"open[- ]?(?:drain|collector|kollektor)", re.I)


def _leds(v: _Values, pkg: _Pkg) -> _Draft:
    color = _norm(v.get("Color"))
    if any(key in color for key in ("RGB", "BICOLOR", "ZWEIFARBIG", "DUO", "MEHRFARBIG")):
        return _none("Mehrfarbige LED – bitte ein IC-Symbol aus der Pinliste verwenden.")
    if pkg.family == "plcc" and pkg.pads == 2:
        return _ok("led")
    return _diode_draft("led", pkg)


def _bjt(v: _Values, pkg: _Pkg) -> _Draft:
    polarity = _norm(v.get("Polarity"))
    if polarity.startswith(("DUAL", "DOPPEL")) or "+" in polarity or "ARRAY" in polarity:
        return _none("Doppeltransistor – bitte ein IC-Symbol aus der Pinliste verwenden.")
    if polarity.endswith("NPN"):
        kind = "npn"
    elif polarity.endswith("PNP"):
        kind = "pnp"
    else:
        return _none("Polarität (NPN/PNP) unbekannt.")
    fam, pads = pkg.family, pkg.pads
    if fam == "sot3":
        return _ok(kind, source="package", message="SOT-23: 1 = B, 2 = E, 3 = C.")
    preset: str | None = None
    if fam == "sot89" or (fam in ("dpak", "to220") and pads == 3):
        preset = "BCE"
    elif fam == "sot223" or (fam == "dpak" and pads == 4):
        preset = "BCEC"
    if preset is not None:
        return _ok(kind, source="package", pinmap=preset)
    if fam == "to92":
        options: tuple[str, ...] = ("EBC", "CBE", "ECB", "BCE")
    elif fam == "to126":
        options = ("ECB", "BCE", "EBC")
    else:
        options = _BJT_OPTIONS
    return _ask(
        kind, options, f"{_pkg_hint(pkg)}: Die Pinbelegung des Transistors ist nicht eindeutig – bitte wählen."
    )


def _fet(v: _Values, pkg: _Pkg) -> _Draft:
    channel = _norm(v.get("Channel"))
    ftype = _norm(v.get("FET Type"))
    if "JFET" in ftype:
        return _none("JFET – kein Standardsymbol.")
    if "GAN" in ftype:
        return _none("GaN-Transistor – bitte ein IC-Symbol aus der Pinliste verwenden.")
    if "DUAL" in channel or "+" in channel or "DOPPEL" in channel:
        return _none("Doppel-MOSFET – bitte ein IC-Symbol aus der Pinliste verwenden.")
    if channel in ("N", "N-KANAL", "N-CHANNEL", "NCH", "N-CH"):
        kind = "nmos"
    elif channel in ("P", "P-KANAL", "P-CHANNEL", "PCH", "P-CH"):
        kind = "pmos"
    else:
        return _none("Kanal (N/P) unbekannt.")
    if _SOURCE_DOWN.search(pkg.text):
        return _ask(kind, _FET_OPTIONS, "Source-Down-Gehäuse: Das Thermal-Pad ist Source – bitte Belegung wählen.")
    fam, pads = pkg.family, pkg.pads
    if fam == "sot3":
        return _ok(kind, source="package", message="SOT-23: 1 = G, 2 = S, 3 = D.")
    preset: str | None = None
    message = ""
    if fam == "sot89" or (fam in ("dpak", "to220") and pads == 3):
        preset = "GDS"
    elif fam == "sot223" or (fam == "dpak" and pads == 4):
        preset = "GDSD"
    elif fam == "so" and (pkg.leads or pads) == 8:
        preset = "SSSGDDDD"  # an extra footprint pad (exposed drain) joins D in the pad check
    elif fam == "dfn" and (pkg.leads or pads) == 8:
        if pkg.ep is False or pkg.from_footprint:
            preset = "SSSGDDDD"  # with a footprint, its thermal pad joins D in the pad check
        else:
            ep = _exposed_pad_designator(8)
            preset = "SSSGDDDDD" if ep == "9" else "SSSGDDDD+EP"
            message = f"Drain-Pad als Pad {ep} angenommen (Footprint-Einstellung für das Thermal-Pad)."
    if preset is not None:
        return _ok(kind, source="package", pinmap=preset, message=message)
    if fam == "sot6":
        options: tuple[str, ...] = ("DDGSDD",)
    elif fam == "to92":
        options = ("SGD", "DGS", "GSD", "GDS")
    elif fam == "lfpak":
        options = ("SSSGDDDD",)
    else:
        options = _FET_OPTIONS
    return _ask(kind, options, f"{_pkg_hint(pkg)}: Die Pinbelegung des MOSFETs ist nicht eindeutig – bitte wählen.")


_XTAL4_TEXT = re.compile(
    rf"{_B}(?:3225|2520|2016|1612|1210|1008|3\.2X2\.5|2\.5X2(?:\.0)?|2\.0X1\.6|2X1\.6|1\.6X1\.2|4-?SMD|SMD-?4|4-?PADS?)"
    rf"(?:-?4)?{_E}"
)
_XTAL2_TEXT = re.compile(
    rf"{_B}(?:HC-?49(?:/?U?S|/?S|-?SMD|/4H|U)?|HC-?52|HC-?18|UM-?1|UM-?5|FC-?1\d\d|FC-?12M|CM-?315|TC-?26|TC-?38"
    rf"|3215|2012|1610|2-?SMD|SMD-?2|2-?PADS?|2-?PINS?|ZYLINDER|CYLINDER)(?:-?2)?{_E}"
)
_XTAL_N = re.compile(rf"{_B}(?:5032|7050|6035|8045|5\.0X3\.2|7\.0X5\.0)-?(?P<n>[24]){_E}")
_RESONATOR3 = re.compile(rf"{_B}(?:CST(?:CE|NE|LS|CR|CC|CW)|ZTT|PBRC|AWSCR|3-?SMD|3-?PINS?|3-?POL|3-?TERMINAL)")
_RESONATOR2 = re.compile(rf"{_B}(?:CSA|CSB|ZTB|2-?SMD|2-?PINS?|2-?POL)")
_OSC_MULTI = re.compile(rf"{_B}(?:6-?SMD|SMD-?6|6-?PADS?|LVDS|LVPECL|HCSL|CML|DIFFERENTIAL|DIFFERENZIELL){_E}")


def _crystal_pads(v: _Values, pkg: _Pkg) -> int | None:
    # chip-size codes ("two") collide with crystal case codes (1210, 2012): check those by text
    if pkg.pads in (2, 4) and (pkg.from_footprint or pkg.family != "two"):
        return pkg.pads
    text = _ntext(" ".join((v.get("Package"), v.get("Case/Package"), v.get("Footprint Ref"))))
    if m := _XTAL_N.search(text):
        return int(m.group("n"))
    if _XTAL4_TEXT.search(text):
        return 4
    if _XTAL2_TEXT.search(text):
        return 2
    return pkg.pads if pkg.pads in (2, 4) else None


def _oscillators(v: _Values, pkg: _Pkg) -> _Draft:
    otype = _norm(v.get("Oscillator Type", "Type"))
    if otype in ("", "QUARZ", "CRYSTAL", "XTAL", "QUARTZ", "SCHWINGQUARZ"):
        pads = _crystal_pads(v, pkg)
        if pads == 4:
            return _ok("crystal_4", source="package")
        if pads == 2:
            return _ok("crystal_2", source="package")
        return _none(
            f"Quarz: {_pkg_hint(pkg)} – 2 oder 4 Pads? Bitte Gehäuse angeben oder Symbol wählen.",
            alternatives=("crystal_2", "crystal_4"),
        )
    if "RESONATOR" in otype:
        text = _ntext(" ".join((v.get("Package"), v.get("Case/Package"), v.get("Manufacturer Part Number"))))
        if _RESONATOR3.search(text) or pkg.pads == 3:
            return _none("Keramikresonator mit 3 Anschlüssen (Mitte = GND) – kein Standardsymbol.")
        if _RESONATOR2.search(text) or pkg.pads == 2:
            return _ok("crystal_2", source="package")
        return _none(
            "Keramikresonator: 2 oder 3 Anschlüsse? Bitte Gehäuse angeben.", alternatives=("crystal_2",)
        )
    if "OSZILLATOR" in otype or "OSCILLATOR" in otype or "MEMS" in otype or otype in ("XO", "TCXO", "VCXO", "OCXO"):
        if _OSC_MULTI.search(_ntext(v.text())) or (pkg.pads is not None and pkg.pads != 4):
            return _none("Oszillator mit mehr als 4 Pads (z. B. differenziell) – IC-Symbol aus der Pinliste.")
        return _ok("oscillator")
    return _none()


def _fuses(v: _Values, pkg: _Pkg) -> _Draft:
    ptype = _norm(v.get("Protection Type", "Type"))
    if not ptype or ptype.startswith(("SICHERUNG", "FUSE")):
        return _two_terminal("fuse", "Sicherung", pkg)
    if ptype.startswith("PTC") or "POLYFUSE" in ptype:
        return _two_terminal("ptc", "PTC-Sicherung", pkg)
    if "VARISTOR" in ptype or ptype.startswith("MOV"):
        return _two_terminal("varistor", "Varistor", pkg)
    return _none()


_AMP_SINGLE_OPTIONS = ("SOT23-5", "SOT23-5R", "SOT23-5U", "SOIC8")


def _eight_lead(pkg: _Pkg) -> bool:
    return pkg.family in ("so", "msop", "dip") and pkg.pads == 8


def _amplifiers(v: _Values, pkg: _Pkg) -> _Draft:
    atype = _norm(v.get("Amplifier Type", "Type"))
    channels = v.number("Channels")
    if channels not in (1, 2, 4):
        return _none("Kanalzahl 1, 2 oder 4 nötig." if channels else "")
    comparator = "KOMPARATOR" in atype or "COMPARATOR" in atype
    opamp = "OPERATIONSVERST" in atype or "OPAMP" in atype or "OP-AMP" in atype or atype == "OPV"
    if not comparator and atype and not opamp:
        return _none()
    if pkg.family in ("bga", "qfp"):
        return _none(f"{_pkg_hint(pkg)} – bitte ein IC-Symbol aus der Pinliste verwenden.")
    output = "open_drain" if comparator and _OPEN_DRAIN.search(v.text()) else None
    extra: dict[str, Any] = {"channels": str(channels), "output": output} if comparator else {}
    if channels == 1:
        kind = "comparator" if comparator else "opamp"
        if not comparator and _eight_lead(pkg):
            return _ok(kind, source="package", pinmap="SOIC8", message="8-polig: Standard-Belegung 2/3/4/6/7.")
        options = _AMP_SINGLE_OPTIONS[:3] if pkg.family == "sot5" else _AMP_SINGLE_OPTIONS
        return _ask(
            kind,
            options,
            f"{_pkg_hint(pkg)}: Einfach-{'Komparatoren' if comparator else 'OPVs'} gibt es mit verschiedenen "
            "Pinbelegungen – bitte laut Datenblatt wählen.",
            **extra,
        )
    want = 8 if channels == 2 else 14
    leads = pkg.leads if pkg.family == "dfn" else pkg.pads
    if leads is not None and leads != want:
        return _none(f"{_pkg_hint(pkg)}: {leads} Anschlüsse passen nicht zur Standardbelegung mit {want} Pins.")
    kind = "comparator" if comparator else ("opamp_dual" if channels == 2 else "opamp_quad")
    message = ""
    if pkg.family == "dfn" and pkg.ep:
        message = "Das Thermal-Pad hat keinen Pin im Symbol (laut Datenblatt anschließen, z. B. an V−)."
    return _ok(kind, message=message, **extra)


def _optocouplers(v: _Values, pkg: _Pkg) -> _Draft:
    otype = _norm(v.get("Opto Type", "Type"))
    output = _norm(v.get("Output Type"))
    if "FOTODIODE" in otype or "PHOTODIODE" in otype:
        return _diode_draft("photodiode", pkg)
    if otype and not ("OPTOKOPPLER" in otype or "OPTOCOUPLER" in otype):
        return _none()
    if output and not output.startswith("TRANSISTOR"):
        return _none()
    if pkg.pads == 4:
        return _ok("optocoupler_4", source="package")
    if pkg.pads == 6:
        return _ok("optocoupler_6", source="package")
    if pkg.pads is None:
        return _none(
            f"Optokoppler: {_pkg_hint(pkg)} – 4 oder 6 Pins? Bitte Gehäuse angeben.",
            alternatives=("optocoupler_4", "optocoupler_6"),
        )
    return _none(f"Optokoppler mit {pkg.pads} Pins (mehrkanalig) – bitte ein IC-Symbol aus der Pinliste verwenden.")


_MAX_ROW = 100


def _connectors(v: _Values, pkg: _Pkg) -> _Draft:
    pins = v.number("Pins")
    rows = v.number("Rows") or 1
    if not pins or pins < 1 or rows not in (1, 2) or pins > 200:
        return _none()
    if rows == 2 and pins % 2:
        return _none(f"{pins} Pole lassen sich nicht auf 2 Reihen verteilen.")
    if pins // rows > _MAX_ROW:
        return _none(f"Mehr als {_MAX_ROW} Pole je Reihe – bitte Reihen angeben oder ein IC-Symbol verwenden.")
    return _ok("connector", pins=pins, rows=str(rows))


def _electromechanical(v: _Values, pkg: _Pkg) -> _Draft:
    etype = _norm(v.get("Electromech Type", "Type"))
    contact = _norm(v.get("Contact Configuration"))
    if etype.startswith(("RELAIS", "RELAY")):
        if contact not in ("", "SPDT"):
            return _none()
        return _ask(
            "relay_spdt",
            ("STANDARD",),
            "Relais-Pinbelegungen sind herstellerspezifisch – bitte Spule, COM, NC und NO laut Datenblatt zuordnen.",
        )
    if "SUMMER" in etype or "BUZZER" in etype:
        return _two_terminal("buzzer", "Summer", pkg)
    if "BATTERIE" in etype or "BATTERY" in etype:
        return _two_terminal("battery", "Batterie", pkg)
    if "POTENTIOMETER" in etype:
        return _ok("potentiometer")
    if etype.startswith("SCHALTER") or etype == "SWITCH":
        if contact not in ("", "SPST", "SPST-NO"):
            return _none()
        return _two_terminal("switch_2", "Schalter", pkg)
    if etype.startswith("TASTER") or etype in ("PUSHBUTTON", "TACTILESWITCH"):
        if pkg.pads == 2:
            return _ok("switch_2", source="package")
        if pkg.pads == 4:
            return _ask(
                "pushbutton_4",
                ("LLRR", "LRLR", "LRRL"),
                "Taster mit 4 Pins: Welche Pins sind intern verbunden? Bitte laut Datenblatt wählen.",
            )
        return _none("Taster: 2 oder 4 Pins? Bitte Gehäuse angeben.", alternatives=("switch_2", "pushbutton_4"))
    return _none()


def _mechanical(v: _Values, pkg: _Pkg) -> _Draft:
    mtype = _norm(v.get("Mechanical Type", "Type"))
    if "BEFESTIGUNG" in mtype or "MOUNTING" in mtype:
        return _ok("mounting_hole")
    if "FIDUCIAL" in mtype or "PASSERMARKE" in mtype:
        return _ok("fiducial")
    if "TESTPUNKT" in mtype or "TESTPOINT" in mtype:
        return _ok("test_point")
    return _none()


_RULES: dict[str, Callable[[_Values, _Pkg], _Draft]] = {
    "resistors": _resistors,
    "capacitors": _capacitors,
    "inductors": lambda v, pkg: _two_terminal("inductor", "Induktivität", pkg),
    "ferrite beads": lambda v, pkg: _two_terminal("ferrite_bead", "Ferrit", pkg),
    "diodes": _diodes,
    "leds": _leds,
    "transistors bjt": _bjt,
    "transistors fet": _fet,
    "oscillators": _oscillators,
    "fuses": _fuses,
    "amplifiers": _amplifiers,
    "optocouplers": _optocouplers,
    "connectors": _connectors,
    "electromechanical": _electromechanical,
    "mechanical": _mechanical,
}


# ======================================================================================
# pin tables (datasheet import)
# ======================================================================================
def _fn(text: str | None) -> str:
    """Normalised pin name for matching: no overbars, '−' -> '-', no spaces/underscores."""
    t = display_text(text or "").upper()
    t = t.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"[\s_]+", "", t)


_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "diode": {
        "A": ("A", "ANODE", "AN", "+"),
        "K": ("K", "C", "CATHODE", "KATHODE", "KAT", "-"),
    },
    "cap": {
        "+": ("+", "PLUS", "POS", "POSITIVE", "ANODE", "A", "+VE"),
        "-": ("-", "MINUS", "NEG", "NEGATIVE", "CATHODE", "K", "-VE"),
    },
    "bjt": {
        "B": ("B", "BASE", "BASIS"),
        "C": ("C", "COLLECTOR", "KOLLEKTOR", "COL"),
        "E": ("E", "EMITTER", "EMIT"),
    },
    "fet": {"G": ("G", "GATE"), "D": ("D", "DRAIN"), "S": ("S", "SOURCE")},
    "amp": {
        "OUT": ("OUT", "OUTPUT", "VOUT", "VO", "AOUT", "AUSGANG"),
        "IN-": ("IN-", "-IN", "INN", "INM", "VIN-", "-VIN", "VINN", "VINM", "IN(-)", "INVERTINGINPUT", "INV",
                "INVERTIERENDEREINGANG"),
        "IN+": ("IN+", "+IN", "INP", "VIN+", "+VIN", "VINP", "IN(+)", "NONINVERTINGINPUT", "NON-INVERTINGINPUT",
                "NONINV", "NICHTINVERTIERENDEREINGANG"),
        "V+": ("V+", "VCC", "VDD", "VS+", "+VS", "VS", "+V", "VCC+", "VPOS", "+VCC", "+VDD", "V+/VCC", "VCC/V+",
               "VDD/V+", "V+/VDD"),
        "V-": ("V-", "VEE", "VSS", "GND", "VS-", "-VS", "-V", "VNEG", "VCC-", "-VCC", "-VEE", "V-/GND", "GND/V-",
               "VEE/GND", "V-/VEE", "VSS/GND"),
    },
    "opto": {
        "A": ("A", "ANODE", "AN", "LED+"),
        "K": ("K", "CATHODE", "KATHODE", "LED-"),
        "C": ("C", "COLLECTOR", "KOLLEKTOR", "COL"),
        "E": ("E", "EMITTER"),
        "B": ("B", "BASE", "BASIS"),
    },
    "xtal": {
        "X": ("XTAL", "XTAL1", "XTAL2", "X1", "X2", "XIN", "XOUT", "CRYSTAL", "QUARZ", "Q", "IN/OUT", "OUT/IN",
              "XTALIN", "XTALOUT", "XI", "XO"),
        "G": ("GND", "CASE", "GROUND", "GND/CASE", "CASE/GND", "SHIELD", "GEHAEUSE", "GEHÄUSE"),
    },
    "bridge": {
        "+": ("+", "DC+", "+DC", "V+", "POS", "PLUS", "OUT+", "+OUT"),
        "-": ("-", "DC-", "-DC", "V-", "NEG", "MINUS", "OUT-", "-OUT"),
        "AC": ("~", "AC", "AC1", "AC2", "~1", "~2", "AC~", "ACIN", "AC-IN", "IN~", "AC/IN", "AC-1", "AC-2"),
    },
    "relay": {
        "COIL": ("A1", "A2", "COIL", "COIL1", "COIL2", "COIL+", "COIL-", "SPULE", "SPULE+", "SPULE-", "+", "-"),
        "COM": ("COM", "COMMON", "C", "MITTE", "WURZEL"),
        "NC": ("NC", "N.C.", "NORMALLYCLOSED", "OEFFNER", "ÖFFNER", "BREAK"),
        "NO": ("NO", "N.O.", "NORMALLYOPEN", "SCHLIESSER", "SCHLIEẞER", "SCHLIEßER", "MAKE"),
    },
    "osc": {
        "PIN1": ("OE", "EN", "E/D", "OE/ST", "ST", "STANDBY", "STBY", "NC", "VC", "VCONT", "TRISTATE", "TRI-STATE",
                 "INH", "DNC", "CONTROL", "OE/NC", "ST/OE"),
        "GND": ("GND", "VSS", "CASE", "GROUND"),
        "OUT": ("OUT", "OUTPUT", "CLK", "CLKOUT", "FOUT", "VOUT"),
        "VDD": ("VDD", "VCC", "V+", "VS", "+V", "SUPPLY", "VDD/VCC"),
    },
}
# several symbol functions share one alias function: assigned in pad order
_SHARED: dict[str, dict[str, tuple[str, ...]]] = {
    "xtal": {"X": ("X1", "X2"), "G": ("G1", "G2")},
    "bridge": {"AC": ("AC1", "AC2")},
    "relay": {"COIL": ("A1", "A2")},
}
_ALIAS_GROUP = {
    **dict.fromkeys(("diode", "zener", "schottky", "tvs_uni", "led", "photodiode"), "diode"),
    "capacitor_polarized": "cap",
    "battery": "cap",
    "buzzer": "cap",
    "npn": "bjt",
    "pnp": "bjt",
    "nmos": "fet",
    "pmos": "fet",
    **dict.fromkeys(("opamp", "opamp_dual", "opamp_quad", "comparator"), "amp"),
    **dict.fromkeys(("optocoupler_4", "optocoupler_6"), "opto"),
    "crystal_4": "xtal",
    "bridge_rectifier": "bridge",
    "relay_spdt": "relay",
    "oscillator": "osc",
}
_NC_PIN = re.compile(r"^(?:NC|N\.C\.?|N/C|DNC|NU|N\.U\.?|NOCONNECT|NOTCONNECTED|NOCONNECTION)\d*$")
_EP_PIN = re.compile(r"^(?:EP|EPAD|E-PAD|PAD|THERMALPAD|EXPOSEDPAD|TAB|MB|MOUNTINGBASE|HS|HEATSINK|SLUG)\d*$")
_CHANNEL_VARIANTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^[1-4](?=\D)"), ""),  # 1OUT, 1IN-
    (re.compile(r"(?<=\D)[1-4A-D]$"), ""),  # OUT1, OUTA, -INA, VOUTA
    (re.compile(r"(IN|OUT)[1-4A-D](?=[-+]?$)"), r"\1"),  # IN1-, INA+
    (re.compile(r"^[A-D](?=[-+]?(?:IN|OUT))"), ""),  # AOUT, A-IN
)


def _lookup(group: str) -> dict[str, str]:
    table: dict[str, str] = {}
    for function, aliases in _ALIASES[group].items():
        for alias in aliases:
            table.setdefault(_fn(alias), function)
    return table


def _function_of(name: str, table: Mapping[str, str], *, channels: bool) -> str | None:
    n = _fn(name)
    if n in table:
        return table[n]
    if channels:
        for pattern, repl in _CHANNEL_VARIANTS:
            candidate = pattern.sub(repl, n, count=1)
            if candidate != n and candidate in table:
                return table[candidate]
    return None


def _pin_function(pin: IcPin, table: Mapping[str, str], *, channels: bool = False) -> str | None:
    found = _function_of(pin.name, table, channels=channels)
    if found is None and pin.description:
        found = _function_of(pin.description, table, channels=channels)
        if found is None:  # "Drain (exposed pad)" -> the one function named in the text
            words = set(re.findall(r"[A-ZÄÖÜ]{4,}", pin.description.upper()))
            hits = {table[w] for w in words if w in table}
            found = hits.pop() if len(hits) == 1 else None
    return found


def _pins_label(pads: Mapping[str, Sequence[str]]) -> str:
    pairs = sorted(((d, f) for f, ds in pads.items() for d in ds), key=lambda p: natural_key(p[0]))
    return ", ".join(f"{d} = {f}" for d, f in pairs)


def _derive_pinmap(kind: str, params: Mapping[str, Any], pins: Sequence[IcPin]) -> tuple[dict[str, Any], str]:
    """Pin map (and extra params) of a pin-map kind from a pin table; raises ``SymbolError`` if it does not fit."""
    group = _ALIAS_GROUP.get(kind)
    if group is None:
        raise SymbolError("Die Pinliste lässt sich diesem Symbol nicht automatisch zuordnen.")
    table = _lookup(group)
    tab = tab_function(kind)
    found: dict[str, list[str]] = {}
    unknown: list[str] = []
    for pin in sorted(pins, key=lambda p: natural_key(p.designator)):
        function = _pin_function(pin, table, channels=group == "amp")
        if function is None:
            name = _fn(pin.name)
            if _NC_PIN.match(name):
                continue
            if tab and _EP_PIN.match(name):
                function = tab
            else:
                unknown.append(f"{pin.designator} ({pin.name or '?'})")
                continue
        found.setdefault(function, []).append(pin.designator)
    if unknown:
        raise SymbolError(f"Pins ohne passende Funktion im Standardsymbol: {', '.join(unknown)}.")
    extra: dict[str, Any] = {}
    if kind == "optocoupler_6":
        extra["base"] = "B" in found
    spec = kind_pinmap(kind, {**params, **extra})
    if spec is None:
        raise SymbolError("Die Pinliste lässt sich diesem Symbol nicht automatisch zuordnen.")
    mapping: dict[str, list[str]] = {}
    for function, pads in found.items():
        targets = _SHARED.get(group, {}).get(function)
        if targets is None:
            mapping[function] = pads
            continue
        if len(pads) != len(targets):
            raise SymbolError(f"Funktion {function}: {len(pads)} Pins in der Pinliste, erwartet {len(targets)}.")
        for target, pad in zip(targets, pads, strict=True):
            mapping[target] = [pad]
    keys = {f.key for f in spec.functions}
    surplus = sorted(set(mapping) - keys)
    if surplus:
        raise SymbolError(f"Die Pinliste enthält Funktionen, die das Symbol nicht hat: {', '.join(surplus)}.")
    missing = [f.name for f in spec.functions if f.key not in mapping]
    if missing:
        raise SymbolError(f"In der Pinliste fehlt {', '.join(missing)}.")
    resolved = resolve_pinmap(spec, mapping, what=get_kind(kind).label)
    value: Any = resolved.key if not resolved.key.startswith("M") else mapping
    return {"pinmap": value, **extra}, _pins_label(mapping)


def _verify_fixed(spec: SymbolSpec, kind: str, pins: Sequence[IcPin]) -> list[str]:
    """Problems of a fixed-pinout symbol against a pin table (designators and, if known, functions)."""
    group = _ALIAS_GROUP.get(kind)
    table = _lookup(group) if group else {}
    by_designator = {p.designator: p for p in pins}
    problems: list[str] = []
    for sym in spec.pins:
        row = by_designator.get(sym.designator)
        if row is None:
            problems.append(f"Pin {sym.designator} ({sym.name}) fehlt in der Pinliste")
            continue
        if not table:
            continue
        want = _function_of(sym.name, table, channels=False)
        got = _pin_function(row, table, channels=group == "amp")
        if want is not None and got != want:
            problems.append(f"Pin {sym.designator}: Symbol {sym.name}, Pinliste {row.name or '?'}")
    symbol_pins = {p.designator for p in spec.pins}
    for row in pins:
        if row.designator in symbol_pins:
            continue
        name = _fn(row.name)
        if not (_NC_PIN.match(name) or _EP_PIN.match(name)):
            problems.append(f"Pin {row.designator} ({row.name or '?'}) fehlt im Symbol")
    return problems


# ======================================================================================
# suggestion
# ======================================================================================
def _resolved(kind: str, params: Mapping[str, Any], kit: StyleKit) -> tuple[PinMapSpec, ResolvedPinMap] | None:
    spec = kind_pinmap(kind, params)
    if spec is None:
        return None
    default = None
    if is_diode_kind(kind):
        default = "KA" if kit.diode_pin1 == "cathode" else "AK"
    return spec, resolve_pinmap(spec, params.get("pinmap"), what=get_kind(kind).label, default=default)


def _apply_pins(draft: _Draft, pins: Sequence[IcPin], kit: StyleKit) -> None:
    assert draft.kind is not None
    kind = draft.kind
    try:
        if kind_pinmap(kind, draft.params) is not None and kind in _ALIAS_GROUP:
            params, label = _derive_pinmap(kind, draft.params, pins)
            draft.params.update(params)
            draft.needs_pinmap = False
            draft.failed = False
            draft.source = "pins"
            draft.messages = [f"Pinbelegung aus der Pinliste: {label}."]
            return
        spec = build_standard(SymbolRequest(kind=kind, params=draft.params), kit)
    except SymbolError as exc:
        draft.failed = True
        draft.messages.append(f"Pinliste passt nicht zum Standardsymbol: {exc}")
        return
    problems = _verify_fixed(spec, kind, pins)
    if problems:
        draft.failed = True
        draft.messages.append("Pinliste passt nicht zum Standardsymbol: " + "; ".join(problems[:6]) + ".")
    elif draft.source is None or draft.source == "standard":
        draft.source = "pins"


# amplifiers/oscillators: unused pads (NC, offset trim) are normal
_UNUSED_PADS_OK = frozenset({"opamp", "comparator", "opamp_dual", "opamp_quad", "oscillator"})
#: Symbol kinds whose footprints may have pads without symbol pin (NC, offset trim) – public name of the rule.
UNUSED_PADS_OK = _UNUSED_PADS_OK
#: ``SymbolSpec.generator`` key with pads a symbol leaves free on purpose (e.g. NC pins of a datasheet pin table).
NC_PADS_KEY = "nc_pads"


def _generator(spec: SymbolSpec | Mapping[str, Any] | None) -> Mapping[str, Any]:
    """``spec.generator`` (a spec) or the mapping itself (a generator dict, e.g. read as JSON)."""
    if isinstance(spec, SymbolSpec):
        return spec.generator if isinstance(spec.generator, dict) else {}
    return spec if isinstance(spec, Mapping) else {}


def symbol_kind(spec: SymbolSpec | Mapping[str, Any] | None, kind: str | None = None) -> str | None:
    """Generator kind of a symbol (``kind`` from the registry wins), ``None`` if unknown."""
    if kind:
        return kind
    value = _generator(spec).get("kind")
    return value if isinstance(value, str) and value else None


def unused_pads_ok(spec: SymbolSpec | Mapping[str, Any] | None, kind: str | None = None) -> bool:
    """Pads without symbol pin are normal for this symbol (op-amps, comparators, oscillators).

    ``spec``: the symbol or its ``generator`` dict; ``kind``: the registry's symbol kind (wins)."""
    return symbol_kind(spec, kind) in _UNUSED_PADS_OK


def free_pads(spec: SymbolSpec | Mapping[str, Any] | None) -> frozenset[str]:
    """Pads the symbol leaves free on purpose: ``generator["nc_pads"]`` (NC pins recorded by the datasheet
    import) and the ``x``/``.`` positions of a letter-code pin map (``AxK``: pad 2 of a SOT-23 diode).

    ``spec``: the symbol or its ``generator`` dict."""
    generator = _generator(spec)
    out: set[str] = set()
    recorded = generator.get(NC_PADS_KEY)
    if isinstance(recorded, (list, tuple, set, frozenset)):
        out.update(str(p).strip() for p in recorded if str(p).strip())
    pinmap = generator.get("pinmap")
    key = pinmap.get("key") if isinstance(pinmap, dict) else None
    pins = pinmap.get("pins") if isinstance(pinmap, dict) else None
    if isinstance(key, str) and key and any(ch in NC_CHARS for ch in key) and isinstance(pins, dict):
        used = {str(pad) for pads in pins.values() if isinstance(pads, (list, tuple)) for pad in pads}
        positions = {str(i) for i, ch in enumerate(key, start=1) if ch not in NC_CHARS}
        if positions == used:  # a letter code: one character per pad, in pad order
            out.update(str(i) for i, ch in enumerate(key, start=1) if ch in NC_CHARS)
    return frozenset(out)


def _nc_pads(spec: PinMapSpec, resolved: ResolvedPinMap) -> set[str]:
    """Pads a letter-code map leaves free on purpose ('AxK': pad 2 of a SOT-23 diode)."""
    codes = {f.code.upper() for f in spec.functions if f.code}
    key = resolved.key
    if not codes or not key or not all(ch.upper() in codes or ch in NC_CHARS for ch in key):
        return set()
    return {str(i) for i, ch in enumerate(key, start=1) if ch in NC_CHARS}


def _apply_footprint(draft: _Draft, fp: _Footprint, kit: StyleKit) -> None:
    """Check the symbol pins against the footprint pads; tabs/EPs join the MOSFET drain / BJT collector."""
    assert draft.kind is not None
    kind = draft.kind
    if is_diode_kind(kind) and len(fp.pads) == 2 and fp.cathode_pad in fp.pads:
        anode = next(p for p in fp.pads if p != fp.cathode_pad)
        wanted = {"K": [fp.cathode_pad], "A": [anode]}
        current = _resolved(kind, draft.params, kit)
        if current is not None and dict(current[1].pins) != {k: tuple(v) for k, v in wanted.items()}:
            if draft.source == "pins":
                draft.messages.append(
                    "Die Pinliste widerspricht dem Footprint – die Pad-Nummern des Footprints gelten."
                )
            draft.params["pinmap"] = "KA" if fp.cathode_pad == "1" else ("AK" if fp.cathode_pad == "2" else wanted)
            draft.source = "footprint"
    try:
        spec = build_standard(SymbolRequest(kind=kind, params=draft.params), kit)
    except SymbolError as exc:
        draft.failed = True
        draft.messages.append(str(exc))
        return
    pads = set(fp.pads)
    symbol_pins = {p.designator for p in spec.pins}
    missing = sorted(symbol_pins - pads, key=natural_key)
    extra = sorted(pads - symbol_pins, key=natural_key)
    if missing:
        draft.failed = True
        draft.messages.append(f"Pins ohne Pad im Footprint: {', '.join(missing)}.")
        return
    current = _resolved(kind, draft.params, kit)
    if current is not None:
        free = _nc_pads(*current)
        extra = [p for p in extra if p not in free]
    if not extra:
        return
    tab = tab_function(kind)
    tab_pads = [p for p in extra if p in fp.thermal] if fp.thermal else (extra if len(extra) == 1 else [])
    if tab and current is not None and tab_pads:
        pin_spec, resolved = current
        mapping = {k: list(v) for k, v in resolved.pins.items()}
        mapping[tab] = [*mapping[tab], *tab_pads]
        merged = resolve_pinmap(pin_spec, mapping, what=get_kind(kind).label)
        draft.params["pinmap"] = merged.key if not merged.key.startswith("M") else mapping
        draft.source = "footprint"
        draft.messages.append(f"Pad {', '.join(tab_pads)} (Fahne/Thermal-Pad) als {tab} angeschlossen.")
        extra = [p for p in extra if p not in tab_pads]
    thermal_left = [p for p in extra if p in fp.thermal]
    other = [p for p in extra if p not in fp.thermal]
    if other and kind in _UNUSED_PADS_OK:
        draft.messages.append(f"Pads ohne Pin im Symbol (nicht verbunden): {', '.join(other)}.")
        other = []
    if other:
        draft.failed = True
        draft.messages.append(f"Pads ohne Pin im Symbol: {', '.join(other)}.")
    elif thermal_left:
        draft.messages.append(
            f"Thermal-Pad {', '.join(thermal_left)} hat keinen Pin im Symbol (laut Datenblatt anschließen)."
        )


def _as_pins(pins: Sequence[IcPin | Mapping[str, Any]] | None) -> list[IcPin]:
    out: list[IcPin] = []
    for pin in pins or ():
        out.append(pin if isinstance(pin, IcPin) else IcPin.model_validate(dict(pin)))
    return out


def suggest_symbol(
    category_table: str,
    values: Mapping[str, Any] | None,
    *,
    pins: Sequence[IcPin | Mapping[str, Any]] | None = None,
    footprint: FootprintSpec | Sequence[str] | None = None,
    style: SymbolStyle | None = None,
) -> SymbolSuggestion:
    """Standard symbol for a part of ``category_table`` with the given field values.

    ``pins`` (the part's pin table, e.g. from the datasheet import) and ``footprint`` (a
    :class:`FootprintSpec` or its pad designators) are optional ground truth: a pin map is
    derived from the pin names, and the symbol pins are checked against the pads. The
    result only carries a ``request`` when the pinout is certain (see module docstring).
    """
    kit = StyleKit.from_style(style)
    v = _Values(values or {})
    fp = _footprint_info(footprint)
    pkg = _detect_package(v, fp)
    rule = _RULES.get(str(category_table or "").strip().lower())
    if rule is None:
        return SymbolSuggestion(package=pkg.label or None)
    draft = rule(v, pkg)
    if draft.kind is None:
        return SymbolSuggestion(
            alternatives=list(draft.alternatives), package=pkg.label or None, messages=list(draft.messages)
        )
    pin_rows = _as_pins(pins)
    if pin_rows:
        _apply_pins(draft, pin_rows, kit)
    if fp is not None and fp.pads and not draft.failed and not draft.needs_pinmap:
        _apply_footprint(draft, fp, kit)
    request: SymbolRequest | None = None
    name: str | None = None
    if not draft.failed and not draft.needs_pinmap:
        candidate = SymbolRequest(kind=draft.kind, params=dict(draft.params))
        try:
            name = build_standard(candidate, kit).name
            request = candidate
        except SymbolError as exc:  # defensive: every rule only produces valid requests
            log.warning("Standardsymbol-Vorschlag %s nicht erzeugbar: %s", candidate, exc)
            draft.messages.append(str(exc))
    return SymbolSuggestion(
        request=request,
        name=name,
        kind=draft.kind,
        needs_pinmap=draft.needs_pinmap or (draft.failed and kind_pinmap(draft.kind, draft.params) is not None),
        pinmap_options=list(draft.options),
        alternatives=list(draft.alternatives),
        package=pkg.label or None,
        source=draft.source if request is not None else None,
        messages=[m for m in draft.messages if m],
    )


def standard_symbol_for(
    category_table: str,
    values: Mapping[str, Any] | None,
    *,
    pins: Sequence[IcPin | Mapping[str, Any]] | None = None,
    footprint: FootprintSpec | Sequence[str] | None = None,
    style: SymbolStyle | None = None,
) -> SymbolRequest | None:
    """Standard symbol request for a part of ``category_table`` with the given field values.

    ``None`` means: no generic symbol can be suggested safely - either none fits (ICs,
    regulators, dual transistors, RGB LEDs ...) or its pin map depends on a package that is
    unknown or ambiguous (use :func:`suggest_symbol` to tell the two apart).
    """
    return suggest_symbol(category_table, values, pins=pins, footprint=footprint, style=style).request
