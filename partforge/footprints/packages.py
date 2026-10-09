"""Map datasheet package data (JEDEC symbols) to generator requests (used by the datasheet AI).

``request_from_package("SOIC-8", {"A": {"max": 1.75}, "b": [0.31, 0.51], "e": 1.27, ...})``

* ``family``: family key/alias (``"gullwing"``, ``"qfn"``, ``"dfn"``) or a package name (``"SOIC-8"``,
  ``"SOT-23-5"``, ``"VQFN-32 5x5"``, ``"0603"``, ``"SMB"``). The best matching preset supplies every
  dimension the datasheet does not give; those parameters are listed in ``FootprintRequest.assumed``
  and reported as warnings by ``generate()``/``preview()``.
* ``dims``: dict symbol -> value (number, ``{min, nom, max}`` with ``-1`` sentinels, ``[min, max]``,
  ``"0.31..0.51"``; keys may carry a description: ``"T_thickness"``) or the datasheet-AI list
  ``[{symbol, description, min, nom, max, unit}, ...]``.

Vendor letter conventions that are resolved here:

* Nexperia/NXP gull wing: ``HE`` = lead span, ``E`` = body; ``e`` = distance of the outer leads and
  ``e1`` = pitch (SOT-23/323/89/223, DPAK): if ``e`` and ``e1`` are both given and one is about twice
  the other, the smaller one is the pitch. A lone ``e`` that cannot be the pitch (the lead row would be
  longer than the body) is taken as the outer distance (pitch = e/2, with a note).
* JEDEC MS-026 QFP: ``D/E`` = span and ``D1/E1`` = body; ``Lp``/``bp`` = foot length/lead width.
* Chip parts: KEMET/Murata/TDK ``T`` = thickness with ``B``/``BW``/``e``/``a``/``b`` = band (terminal);
  Vishay ``T1``/``T2`` terminals with ``H`` = height; a lone ``T`` is decided by plausibility.
* Tantalum: KEMET ``F`` terminal width, ``S`` terminal length, ``A`` gap; AVX ``W1`` terminal width,
  ``A`` terminal length, ``S`` separation.
* SOD/DO-214: the lead span is ``HE``/``HD`` or ``H``/``E`` – whichever is longer than the body length ``D``.
* Descriptions of the datasheet-AI list (``thickness``, ``band``, ``pitch``, ``overall`` …) take precedence.
"""
from __future__ import annotations

import copy
import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .families import SELECTORS, best_preset, get_family, registry, resolve
from .ipc7351 import fmt_mm
from .models import FootprintRequest, Preset, Tol
from .params import nom, parse_tol, tol_to_json

log = logging.getLogger(__name__)

Dims = dict[str, Tol]

# --------------------------------------------------------------------------- dims normalisation

_SUFFIX = re.compile(r"^(?P<sym>[A-Za-z][A-Za-z0-9]*?)_(?P<lim>min|max|nom|typ)$", re.I)
_SYMBOL_TOKEN = re.compile(r"^[A-Za-z]{1,2}\d?$")
_PAD_PREFIXES = {"EP", "TP"}  # exposed / thermal pad
_EXTRA_KEYS = ("n", "pins", "pin_count", "rows", "cols", "columns", "pins_x", "pins_y")


def _split_key(key: str) -> tuple[list[str], str]:
    """(JEDEC symbols, remaining description text) of a dimension key."""
    tokens = [t for t in re.split(r"[_\s/]+", key.strip()) if t]
    symbols: list[str] = []
    pad_prefix = False
    rest: list[str] = []
    for i, token in enumerate(tokens):
        if token.upper() in _PAD_PREFIXES and not symbols:
            pad_prefix = True
            continue
        if _SYMBOL_TOKEN.match(token):
            symbols.append(token)
            continue
        rest = tokens[i:]
        break
    if pad_prefix and not symbols:
        return ["EP"], " ".join(rest)
    return symbols, " ".join(rest)


def _symbols_of(key: str) -> list[str]:
    """JEDEC symbols encoded in a dimension key.

    ``"D_body_length"`` -> D, ``"E1_body_width"`` -> E1, ``"D_E_body"`` -> D, E, ``"EP_D2_E2"`` -> D2, E2,
    ``"EP"`` -> EP, ``"eA_row_spacing"`` -> eA, ``"terminal_center_span"`` -> (none).
    """
    return _split_key(key)[0]


def normalize_dims(dims: Mapping[str, Any] | list[Any] | None) -> tuple[Dims, dict[str, Any]]:
    """Return (toleranced dims by symbol, plain extras like n/pins/rows)."""
    out: Dims = {}
    extras: dict[str, Any] = {}
    if not dims:
        return out, extras
    items: list[tuple[str, Any]] = []
    if isinstance(dims, list):
        for entry in dims:
            if not isinstance(entry, Mapping):
                continue
            if str(entry.get("unit", "mm")).lower() not in ("mm", ""):
                continue  # angles etc.
            symbol = str(entry.get("symbol") or "").strip()
            if symbol:
                items.append((symbol, {k: entry.get(k) for k in ("min", "nom", "max")}))
    else:
        items = list(dims.items())
    partial: dict[str, dict[str, Any]] = {}
    for raw_key, value in items:
        key = str(raw_key).strip()
        if key.lower() in _EXTRA_KEYS:
            extras[key.lower()] = value
            continue
        m = _SUFFIX.match(key)
        if m and not isinstance(value, (Mapping, list, tuple)):
            lim = m.group("lim").lower()
            partial.setdefault(m.group("sym"), {})["nom" if lim == "typ" else lim] = value
            continue
        symbols = _symbols_of(key)
        if not symbols:
            continue
        if isinstance(value, Mapping):
            value = {k: value.get(k) for k in ("min", "nom", "typ", "max") if k in value}
        try:
            t = parse_tol(value, key)
        except ValueError:
            log.debug("Maß %s=%r ignoriert", key, value)
            continue
        if t is None:
            continue
        for symbol in symbols:
            out.setdefault(symbol, t)
    for symbol, parts in partial.items():
        try:
            t = parse_tol(parts, symbol)
        except ValueError:
            log.debug("Maß %s=%r ignoriert", symbol, parts)
            continue
        if t is not None and symbol not in out:
            out[symbol] = t
    return out, extras


def dimension_descriptions(dims: Mapping[str, Any] | list[Any] | None) -> dict[str, str]:
    """Symbol -> lower-case description (datasheet-AI ``description``, ``{"description": ...}`` values or
    the text part of keys such as ``"T_thickness"``)."""
    out: dict[str, str] = {}
    if not dims:
        return out
    if isinstance(dims, list):
        for entry in dims:
            if isinstance(entry, Mapping):
                symbol = str(entry.get("symbol") or "").strip()
                text = str(entry.get("description") or "").strip()
                if symbol and text:
                    out.setdefault(symbol, text.lower())
        return out
    for raw_key, value in dims.items():
        symbols, rest = _split_key(str(raw_key))
        text = rest
        if isinstance(value, Mapping) and value.get("description"):
            text = f"{text} {value['description']}".strip()
        if text:
            for symbol in symbols:
                out.setdefault(symbol, text.lower())
    return out


# Description roles (first match wins; order matters: "terminal width" is a lead width, not a band).
_ROLES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("separation", re.compile(r"separat|\bgap\b|between (?:the )?terminals|abstand zwischen", re.I)),
    ("outer", re.compile(r"outer|outside|pins? ?1 (?:and|to|-) ?(?:pin ?)?3|between (?:the )?(?:outer|end) "
                         r"|lead to lead|äußere", re.I)),
    ("pitch", re.compile(r"pitch|raster|lead spacing|pin spacing|\bbasic\b", re.I)),
    ("lead_width", re.compile(r"(?:lead|terminal|termination|pin|electrode) width|anschlussbreite", re.I)),
    ("thickness", re.compile(r"thick|height|\bhigh\b|höhe|dicke", re.I)),
    ("band", re.compile(r"band|electrode|termination|terminal length|terminal|end ?cap|kappe|metalli|foot",
                        re.I)),
    ("span", re.compile(r"overall|tip.to.tip|lead span|incl(?:\.|uding)? (?:the )?leads|across (?:the )?leads|"
                        r"total length|gesamt", re.I)),
)


def _role(text: str | None) -> str | None:
    if not text:
        return None
    for role, pattern in _ROLES:
        if pattern.search(text):
            return role
    return None


@dataclass
class _Input:
    """Everything a family mapper needs."""

    d: Dims
    extras: Mapping[str, Any]
    desc: Mapping[str, str]
    base: Mapping[str, Any] | None = None  # parameters of the preset that fills the gaps
    siblings: list[Mapping[str, Any]] = field(default_factory=list)  # presets of the same size/kind/variant
    notes: list[str] = field(default_factory=list)

    def role(self, symbol: str) -> str | None:
        return _role(self.desc.get(symbol))


def _get(d: Dims, *names: str) -> Tol | None:
    for n in names:
        if n in d:
            return d[n]
    return None


def _count(extras: Mapping[str, Any], dims: Dims) -> int | None:
    for key in ("n", "pins", "pin_count"):
        if key in extras:
            try:
                return int(float(str(extras[key]).replace(",", ".")))
            except ValueError:
                return None
    t = dims.get("n") or dims.get("N")
    return round(nom(t)) if t is not None else None


def _set(params: dict[str, Any], key: str, t: Tol | None) -> None:
    if t is not None:
        params[key] = tol_to_json(t)


def _tol_of(value: Any) -> Tol | None:
    if value is None:
        return None
    try:
        return parse_tol(value)
    except ValueError:
        return None


def _base_tol(inp: _Input, key: str) -> Tol | None:
    return _tol_of(inp.base.get(key)) if inp.base else None


def _pitch_value(inp: _Input, *, allow_e1: bool = False) -> tuple[float | None, str | None]:
    """(pitch, symbol) with the e/e1 rules of the module docstring."""
    d = inp.d
    e, e1 = d.get("e"), d.get("e1")
    if e is not None and e1 is not None:
        a, b = nom(e), nom(e1)
        lo, hi = min(a, b), max(a, b)
        if lo > 0 and 1.8 <= hi / lo <= 2.2:
            return lo, ("e" if a <= b else "e1")
    for symbol in ("e", "e1", "P", "pitch"):
        if symbol in d and inp.role(symbol) == "pitch":
            return nom(d[symbol]), symbol
    for symbol in ("e", "P", "pitch"):
        if symbol in d:
            return nom(d[symbol]), symbol
    if allow_e1 and e1 is not None:
        return nom(e1), "e1"
    return None, None


def _pitch(params: dict[str, Any], inp: _Input, *, key: str = "e", allow_e1: bool = False,
           row: tuple[str, int] | None = None) -> None:
    """Set the pitch. ``row`` = (body symbol, lead positions across it): a lone ``e`` described as the
    outer distance, or one that cannot be the pitch because the row would not fit the body, is halved."""
    value, symbol = _pitch_value(inp, allow_e1=allow_e1)
    if value is None:
        return
    if row is not None and symbol in ("e", "P", "pitch") and "e1" not in inp.d:
        body = inp.d.get(row[0])
        lead = _get(inp.d, "b", "bp") or _base_tol(inp, "b")
        positions = row[1]
        width = nom(lead) if lead is not None else 0.0
        too_long = body is not None and (positions - 1) * value + width > body.max + 0.1
        fits_half = body is not None and (positions - 1) * value / 2 + width <= body.max + 0.1
        if inp.role(symbol) == "outer" or (too_long and fits_half):
            inp.notes.append(f"Datenblatt-Maß {symbol} = {fmt_mm(value)} mm als Abstand der äußeren Anschlüsse "
                             f"gedeutet (Nexperia/NXP-Bezeichnung) – Raster {fmt_mm(value / (positions - 1))} mm "
                             "verwendet.")
            value = value / (positions - 1)
    params[key] = round(value, 4)


def _span_body(d: Dims) -> tuple[Tol | None, Tol | None]:
    """(lead span, body width) with Nexperia (HE/E) or JEDEC (E/E1) letters."""
    if "HE" in d:
        return d["HE"], _get(d, "E", "E1")
    span, body = _get(d, "E"), _get(d, "E1")
    if span is not None and body is not None and nom(span) < nom(body):
        span, body = body, span
    return span, body


def _two_lead_span(inp: _Input) -> tuple[Tol | None, str | None]:
    """Lead span of a SOD/DO-214 part: a description, ``HE``/``HD``, or ``H``/``E`` longer than ``D``."""
    d = inp.d
    for symbol, t in d.items():
        if inp.role(symbol) == "span":
            return t, symbol
    for symbol in ("HE", "HD"):
        if symbol in d:
            return d[symbol], symbol
    body = d.get("D")
    for symbol in ("H", "E"):
        if symbol in d and inp.role(symbol) != "thickness" and (body is None or nom(d[symbol]) > nom(body)):
            return d[symbol], symbol
    return None, None


# --------------------------------------------------------------------------- per family mapping


def _map_gullwing(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    span, body = _span_body(d)
    _set(params, "E", span)
    _set(params, "E1", body)
    for key, names in (("D", ("D",)), ("L", ("L", "Lp")), ("b", ("b", "bp")), ("A", ("A",)), ("A1", ("A1",)),
                       ("c", ("c",)), ("E2", ("E2",)), ("D2", ("D2",))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp)
    n = _count(inp.extras, d)
    if n:
        params["pins"] = n
    return params


def _map_sot(inp: _Input) -> dict[str, Any]:
    params = _map_gullwing(inp)
    params.pop("E2", None)
    params.pop("D2", None)
    params.pop("e", None)
    _pitch(params, inp, allow_e1=True, row=("D", 3))
    if "pins" in params:
        params["pins"] = str(params["pins"])
    return params


def _map_qfp(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    if "HE" in d or "HD" in d:
        _set(params, "HE", _get(d, "HE", "HD"))
        _set(params, "HD", _get(d, "HD", "HE"))
        _set(params, "E", _get(d, "E", "D"))
        _set(params, "D", _get(d, "D", "E"))
    else:  # JEDEC MS-026: D/E span, D1/E1 body
        _set(params, "HE", _get(d, "E", "D"))
        _set(params, "HD", _get(d, "D", "E"))
        _set(params, "E", _get(d, "E1", "D1"))
        _set(params, "D", _get(d, "D1", "E1"))
    for key, names in (("L", ("L", "Lp")), ("b", ("b", "bp")), ("A", ("A",)), ("A1", ("A1",)), ("c", ("c",)),
                       ("E2", ("E2",)), ("D2", ("D2",))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp)
    n = _count(inp.extras, d)
    if n:
        params["pins"] = n
    for key in ("pins_x", "pins_y"):
        if key in inp.extras:
            params[key] = inp.extras[key]
    return params


def _map_nolead(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    for key, names in (("E", ("E",)), ("D", ("D",)), ("L", ("L", "Lp")), ("b", ("b", "bp")), ("A", ("A",)),
                       ("A1", ("A1",)), ("E2", ("E2", "EP")), ("D2", ("D2", "EP"))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp)
    n = _count(inp.extras, d)
    if n:
        params["pins"] = n
    for key in ("pins_x", "pins_y"):
        if key in inp.extras:
            params[key] = inp.extras[key]
    return params


def _map_bga(inp: _Input) -> dict[str, Any]:
    d, extras = inp.d, inp.extras
    params: dict[str, Any] = {}
    _set(params, "E", _get(d, "E"))
    _set(params, "D", _get(d, "D"))
    _set(params, "A", _get(d, "A"))
    _set(params, "A1", _get(d, "A1"))
    _pitch(params, inp)
    ball = _get(d, "b", "ball")
    if ball is not None:
        params["ball"] = round(nom(ball), 4)
    e = params.get("e")
    for key, matrix in (("cols", "E1"), ("rows", "D1")):
        source = "columns" if key == "cols" and "columns" in extras else key
        if source in extras:
            params[key] = int(float(extras[source]))
        elif e and matrix in d:
            params[key] = round(nom(d[matrix]) / e) + 1
    return params


_CHIP_TERMINALS = ("T2", "B", "BW", "e", "b", "a", "T1", "I2", "I1")


def _chip_t_is_thickness(inp: _Input, t: Tol) -> bool:
    """A lone ``T`` (no band and no height symbol): thickness or terminal?"""
    length = inp.d.get("L")
    if length is not None and 2 * t.max >= length.min:
        return True  # cannot be a terminal length
    base_t = _base_tol(inp, "T")
    heights = [h for h in (_tol_of(params.get("H")) for params in (inp.base or {}, *inp.siblings)) if h is not None]
    if base_t is not None and heights:  # closer to one of the standard thicknesses than to the band?
        return min(abs(nom(t) - nom(h)) for h in heights) < abs(nom(t) - nom(base_t))
    return True  # MLCC drawings (KEMET, Murata, TDK, Samsung) use T for the thickness


def _map_chip(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    _set(params, "L", _get(d, "L"))
    _set(params, "W", _get(d, "W"))
    used = {"L", "W"}
    terminal: Tol | None = None
    height: Tol | None = None
    for symbol, t in d.items():  # descriptions first
        if symbol in used:
            continue
        role = inp.role(symbol)
        if role == "thickness" and height is None:
            height = t
            used.add(symbol)
        elif role == "band" and terminal is None:
            terminal = t
            used.add(symbol)
    if terminal is None:
        symbol = next((s for s in _CHIP_TERMINALS if s in d and s not in used), None)
        if symbol is not None:
            terminal = d[symbol]
            used.add(symbol)
    if height is None:
        symbol = next((s for s in ("H", "A") if s in d and s not in used), None)
        if symbol is not None:
            height = d[symbol]
            used.add(symbol)
    t = d.get("T") if "T" not in used else None
    if t is not None:
        if terminal is not None and height is None:
            height = t  # KEMET/Murata/TDK: L, W, T (thickness), B/e (band)
        elif height is not None and terminal is None:
            terminal = t  # generic L, W, H, T
        elif terminal is None and height is None:
            if _chip_t_is_thickness(inp, t):
                height = t
            else:
                terminal = t
    _set(params, "T", terminal)
    _set(params, "H", height)
    return params


def _map_molded(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    _set(params, "L", _get(d, "L"))
    _set(params, "W", _get(d, "W"))
    used = {"L", "W"}
    width: Tol | None = None
    length: Tol | None = None
    height: Tol | None = None
    for symbol, t in d.items():  # descriptions first
        if symbol in used:
            continue
        role = inp.role(symbol)
        if role == "thickness" and height is None:
            height = t
        elif role == "lead_width" and width is None:
            width = t
        elif role == "band" and length is None:
            length = t
        elif role != "separation":
            continue
        used.add(symbol)
    if "W1" in d:  # AVX TAJ: W1 terminal width, A terminal length, S min. separation
        width = width or d["W1"]
        length = length or (d["A"] if "A" in d and "A" not in used else None)
    else:  # KEMET T491: F terminal width, S terminal length, A min. gap between the terminations
        width = width or _get(d, "F", "b")
        length = length or next((d[s] for s in ("S", "T") if s in d and s not in used), None)
    height = height or (d["H"] if "H" in d and "H" not in used else None)
    _set(params, "F", width)
    _set(params, "S", length)
    _set(params, "H", height)
    return params


def _map_sod(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    span, span_symbol = _two_lead_span(inp)
    _set(params, "HE", span)
    _set(params, "D", _get(d, "D"))
    body_width = _get(d, "E1") or (d["E"] if "E" in d and span_symbol != "E" else None) or _get(d, "W")
    _set(params, "E", body_width)
    _set(params, "b", _get(d, "b", "bp"))
    _set(params, "L", _get(d, "L", "Lp"))
    height = _get(d, "A") or (d["H"] if "H" in d and span_symbol != "H" else None)
    _set(params, "A", height)
    _set(params, "c", _get(d, "c"))
    return params


def _map_do214(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    span, span_symbol = _two_lead_span(inp)
    _set(params, "E", span)
    _set(params, "D", _get(d, "D"))
    body_width = _get(d, "W", "E1") or (d["E"] if "E" in d and span_symbol != "E" else None)
    _set(params, "W", body_width)
    _set(params, "b", _get(d, "b", "bp"))
    _set(params, "T", _get(d, "T", "L", "Lp"))
    height = _get(d, "A") or (d["H"] if "H" in d and span_symbol != "H" else None)
    _set(params, "A", height)
    _set(params, "c", _get(d, "c"))
    return params


def _map_generic(inp: _Input) -> dict[str, Any]:
    params: dict[str, Any] = {k: tol_to_json(v) for k, v in inp.d.items()}
    n = _count(inp.extras, inp.d)
    if n:
        params["pins"] = n
    return params


def _map_sot89(inp: _Input) -> dict[str, Any]:
    """SOT-89 parameters: HE = overall length, E = body (Nexperia E, JEDEC E1), b/b2/b3 = pins 1+3 / pin 2 /
    tab (Nexperia bp1/bp2/bp3, research letters b1/b2/b3, Diodes D1 = tab width)."""
    d = inp.d
    params: dict[str, Any] = {}
    if "HE" not in d and "H" in d:  # Diodes Inc.: H = overall length, E = body
        span, body = d["H"], _get(d, "E", "E1")
    else:
        span, body = _span_body(d)
    _set(params, "HE", span)
    _set(params, "E", body)
    for key, names in (("D", ("D",)), ("L", ("L", "Lp")), ("b", ("b", "bp", "bp1", "b1")), ("b2", ("b2", "bp2")),
                       ("b3", ("b3", "bp3", "D1")), ("A", ("A",)), ("c", ("c",))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp, allow_e1=True, row=("D", 3))
    return params


def _map_sot223(inp: _Input) -> dict[str, Any]:
    """SOT-223 parameters: E = lead span (Nexperia HE), E1 = body (Nexperia E), b = pins 1–3, b1 = tab."""
    d = inp.d
    params: dict[str, Any] = {}
    span, body = _span_body(d)
    _set(params, "E", span)
    _set(params, "E1", body)
    for key, names in (("D", ("D",)), ("L", ("L", "Lp")), ("b", ("b", "bp")), ("b1", ("b1", "bp1", "b2", "bp2")),
                       ("A", ("A",)), ("A1", ("A1",)), ("c", ("c",))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp, allow_e1=True, row=("D", 3))
    return params


def _map_dpak(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    for key, names in (("H", ("H", "HD", "HE")), ("L", ("L", "Lp")), ("b", ("b", "bp")), ("D", ("D", "D1")),
                       ("E", ("E",)), ("L3", ("L3",)), ("b_tab", ("b3", "b2", "E1")), ("A", ("A",)),
                       ("c", ("c",))):
        _set(params, key, _get(d, *names))
    _pitch(params, inp, allow_e1=True, row=("E", 3))
    return params


def _map_dip(inp: _Input) -> dict[str, Any]:
    d = inp.d
    params: dict[str, Any] = {}
    for key, names in (("E1", ("E1",)), ("D", ("D",)), ("b", ("b",)), ("b1", ("b1", "b2")), ("c", ("c",)),
                       ("A", ("A",)), ("A1", ("A1",))):
        _set(params, key, _get(d, *names))
    if "eA" in d:
        params["eA"] = round(nom(d["eA"]), 4)
    elif "E" in d:  # JEDEC E = width across the shoulders: snap to the standard row spacing
        width = nom(d["E"])
        standard = min((7.62, 10.16, 15.24, 22.86), key=lambda s: abs(s - width))
        params["eA"] = standard if abs(standard - width) <= 1.0 else round(width, 4)
    _pitch(params, inp)
    n = _count(inp.extras, d)
    if n:
        params["pins"] = n
    return params


_MAPPERS: dict[str, Callable[[_Input], dict[str, Any]]] = {
    "gullwing": _map_gullwing, "sot23": _map_sot, "sc70": _map_sot, "sot523": _map_sot, "qfp": _map_qfp,
    "nolead": _map_nolead, "bga": _map_bga, "chip": _map_chip, "molded": _map_molded, "sod": _map_sod,
    "do214": _map_do214, "sot89": _map_sot89, "sot223": _map_sot223, "dpak": _map_dpak, "dip": _map_dip,
}


# --------------------------------------------------------------------------- package names

_NAME_RULES: list[tuple[re.Pattern[str], str, Callable[[re.Match[str]], dict[str, Any]]]] = []


def _rule(pattern: str, family: str, extra: Callable[[re.Match[str]], dict[str, Any]] | None = None) -> None:
    _NAME_RULES.append((re.compile(pattern, re.I), family, extra or (lambda m: {})))


def _pins(m: re.Match[str]) -> dict[str, Any]:
    pins = m.groupdict().get("pins")
    return {"pins": int(pins)} if pins else {}


_rule(r"^(?:(?P<kind>R|C|L|FB|D|LED)[-_ ]?)?(?P<size>01005|0201|0402|0603|0805|1008|1206|1210|1808|1812|2010|2220|2512)"
      r"(?:[-_/ ]?(?:\d{4}))?(?:M|METRIC)?$", "chip",
      lambda m: {"size": m.group("size"), **({"kind": m.group("kind").upper()} if m.group("kind") else {})})
_rule(r"^SOIC[-_ ]?(?P<pins>\d+)?", "gullwing", lambda m: {"variant": "SOIC", **_pins(m)})
_rule(r"^(?:H?V?MSOP|VSSOP|USOP)[-_ ]?(?P<pins>\d+)?", "gullwing", lambda m: {"variant": "MSOP", **_pins(m)})
_rule(r"^(?:H?T)?SSOP[-_ ]?(?P<pins>\d+)?", "gullwing",
      lambda m: {"variant": "TSSOP" if "TSSOP" in m.group(0).upper() else "SSOP", **_pins(m)})
_rule(r"^QSOP[-_ ]?(?P<pins>\d+)?", "gullwing", lambda m: {"variant": "QSOP", **_pins(m)})
_rule(r"^SOP[-_ ]?(?P<pins>\d+)?", "gullwing", lambda m: {"variant": "SOP", **_pins(m)})
_rule(r"^LFCSP(?:[-_]?(?P<t>[A-Z]{1,3}))?[-_ ]?(?P<pins>\d+)?", "nolead",
      lambda m: {"variant": "DFN" if (m.group("t") or "").endswith("D") else "QFN", **_pins(m)})
_rule(r"^(?:[VWUX])?(?:QFN|MLF|MLP)[-_ ]?(?P<pins>\d+)?", "nolead", lambda m: {"variant": "QFN", **_pins(m)})
_rule(r"^(?:[VWUXT])?DFN[-_ ]?(?P<pins>\d+)?", "nolead", lambda m: {"variant": "DFN", **_pins(m)})
_rule(r"^(?:[VWUX])?SON[-_ ]?(?P<pins>\d+)?", "nolead", lambda m: {"variant": "SON", **_pins(m)})
_rule(r"^(?P<v>LQFP|TQFP|QFP|HTQFP|PQFP)[-_ ]?(?P<pins>\d+)?", "qfp",
      lambda m: {"variant": {"LQFP": "LQFP", "TQFP": "TQFP", "HTQFP": "TQFP"}.get(m.group("v").upper(), "QFP"),
                 **_pins(m)})
_rule(r"BGA", "bga")
_rule(r"^SOT[-_ ]?23(?:[-_ ]?(?P<pins>[356]))?$", "sot23", lambda m: {"pins": m.group("pins") or "3"})
_rule(r"^(?:TO[-_ ]?236|SC[-_ ]?59)", "sot23", lambda m: {"pins": "3"})
_rule(r"^SOT[-_ ]?323$|^SC[-_ ]?70(?:[-_ ]?3)?$", "sc70", lambda m: {"pins": "3"})
_rule(r"^SOT[-_ ]?353$|^SC[-_ ]?70[-_ ]?5$|^SC[-_ ]?88A$", "sc70", lambda m: {"pins": "5"})
_rule(r"^SOT[-_ ]?363$|^SC[-_ ]?70[-_ ]?6$|^SC[-_ ]?88$", "sc70", lambda m: {"pins": "6"})
_rule(r"^SOT[-_ ]?523", "sot523", lambda m: {"pins": "3"})
_rule(r"^SC[-_ ]?75|^SOT[-_ ]?416", "sot523", lambda m: {"pins": "3", "preset": "SC-75"})
_rule(r"^SOT[-_ ]?89|^TO[-_ ]?243|^SC[-_ ]?62", "sot89")
_rule(r"^SOT[-_ ]?223|^TO[-_ ]?261|^SC[-_ ]?73", "sot223")
_rule(r"^(?:D2PAK|DDPAK|TO[-_ ]?263)", "dpak", lambda m: {"variant": "D2PAK"})
_rule(r"^(?:DPAK|TO[-_ ]?252)", "dpak", lambda m: {"variant": "DPAK"})
_rule(r"^SOD[-_ ]?(?P<v>123F|123|323|523|923)", "sod", lambda m: {"variant": f"SOD-{m.group('v').upper()}"})
_rule(r"^(?:SOD[-_ ]?80|LL[-_ ]?34|MINI[-_ ]?MELF)", "melf", lambda m: {"size": "MiniMELF SOD-80"})
_rule(r"^(?:DO[-_ ]?213AB|LL[-_ ]?41|MELF)", "melf", lambda m: {"size": "MELF DO-213AB"})
_rule(r"^(?P<v>SM[ABC])\b|^DO[-_ ]?214(?P<j>A[ABC])", "do214",
      lambda m: {"variant": m.group("v").upper() if m.group("v") else {"AC": "SMA", "AA": "SMB", "AB": "SMC"}[
          m.group("j").upper()]})
_rule(r"^(?:P?DIP|DIL)[-_ ]?(?P<pins>\d+)?", "dip", _pins)
_rule(r"^(?:SMD|SMT|DIP)[-_ ]?(?P<pins>\d+).*GULL", "gullwing", lambda m: {"variant": "SOP", **_pins(m)})
_rule(r"^TO[-_ ]?92", "to92")
_rule(r"^TO[-_ ]?220", "to220")


def resolve_package(name: str) -> tuple[str, dict[str, Any]]:
    """(family key, parameters derived from the name) for a family key, package name or alias.

    Alias names return the parameters they imply (``"smb"`` -> ``variant = SMB``); the special key
    ``preset`` names a preset (``"*"`` = best match) that supplies the remaining dimensions.
    """
    text = str(name).strip()
    if text in registry():
        return text, {}
    compact = re.sub(r"\s+", "", text.upper())
    head = re.split(r"[(\s]", text.upper())[0]
    for candidate in (head, compact):
        for pattern, family, extra in _NAME_RULES:
            m = pattern.search(candidate)
            if m:
                return family, extra(m)
    try:
        fam, implied = resolve(text)
    except ValueError:
        raise ValueError(f"Gehäuse „{name}“ ist keiner Footprint-Familie zugeordnet – bitte Familie wählen.") from None
    return fam.info.key, implied


def _find_preset(presets: list[Preset], key: str) -> Preset | None:
    wanted = key.strip().lower()
    return next((p for p in presets if p.key.lower() == wanted), None)


def request_from_package(
    family: str,
    dims: Mapping[str, Any] | list[Any] | None,
    *,
    density: str | None = None,
    land_pattern: Mapping[str, Any] | None = None,
    name: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> FootprintRequest:
    """Build a generator request from JEDEC-style datasheet dimensions (see module docstring).

    The returned parameters are independent copies (never shared with the module-level presets).
    """
    key, from_name = resolve_package(family)
    from_name = copy.deepcopy(from_name)
    named_preset = from_name.pop("preset", None)
    info = get_family(key).info
    parsed, extras = normalize_dims(dims)
    descriptions = dimension_descriptions(dims)
    mapper = _MAPPERS.get(key, _map_generic)
    known = {spec.name for spec in info.params}
    # first pass: selectors of the datasheet (pins, pitch) choose the preset that fills the gaps
    first = mapper(_Input(parsed, extras, descriptions))
    hints = {**from_name, **{k: v for k, v in first.items() if k in SELECTORS and k in known}}
    base = _find_preset(info.presets, named_preset) if named_preset and named_preset != "*" else None
    base = base or best_preset(info, hints)
    siblings = [p.params for p in info.presets if base is not None and p is not base
                and all(p.params.get(k) == base.params.get(k) for k in ("size", "kind", "variant", "case"))]
    inp = _Input(parsed, extras, descriptions, base=base.params if base is not None else None, siblings=siblings)
    mapped = {k: v for k, v in mapper(inp).items() if k in known}
    explicit: dict[str, Any] = {**from_name, **mapped, **copy.deepcopy(dict(params or {}))}
    base_params = copy.deepcopy(dict(base.params)) if base is not None else {}
    merged = {**base_params, **explicit}
    data: dict[str, Any] = {
        "family": key,
        "params": merged,
        "assumed": sorted(k for k in base_params if k not in explicit),
        "assumed_from": base.key if base is not None else None,
        "notes": inp.notes,
    }
    if density:
        data["density"] = density
    if land_pattern:
        data["land_pattern"] = copy.deepcopy(dict(land_pattern))
    if name:
        data["name"] = name
    return FootprintRequest.model_validate(data)
