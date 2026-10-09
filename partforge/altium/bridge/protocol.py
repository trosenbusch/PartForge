"""Line-based ASCII exchange format between PartForge and the DelphiScript bridge.

DelphiScript has no JSON parser and its ``StrToFloat``/``FloatToStr`` follow the
Windows locale (German decimal comma, VERIFIED in altium-live.md §5). Every file
exchanged with Altium therefore is plain ASCII, one record per line, fields separated
by ``|``:

* Text fields are escaped with :func:`escape_field`: characters outside
  :data:`SAFE_CHARS` (and ``|``/``%``) become ``%uHHHH``; the Pascal side decodes them
  with ``Chr``. DelphiScript's ``Chr`` wraps modulo 256 (VERIFIED, altium-verify-2
  §3.5), so requests never carry code points above U+00FF: they are transliterated
  (``Ω`` -> ``Ohm``). Responses escape every non-ASCII character as ``%uHHHH`` from
  ``Ord`` and therefore arrive loss-free.
* Numbers use ``.`` with at most six decimals (:func:`fmt_num`) and are parsed in
  Pascal by an own digit parser (``PFParseNum``), never by the locale.

Request (``request.txt``)::

    PFREQ|1
    ID|<12 hex>
    COMMAND|<name>
    ARG|<key>|<escaped value>
    END|<id>

Response (``response_<id>.txt``)::

    PFRES|1
    ID|<id>
    STATUS|OK            (or STATUS|ERROR + ERROR|<msg>)
    KV|<key>|<value>     ITEM|<list>|<value>   ROW|<list>|<f1>|<f2>…   WARN|<msg>
    END|<id>             (written last: a response without it is still being written)
"""
from __future__ import annotations

import math
import re
import string
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "SAFE_CHARS",
    "BridgeProtocolError",
    "BridgeResponse",
    "escape_field",
    "unescape_field",
    "transliterate",
    "fmt_num",
    "render_request",
    "parse_response",
    "REQUEST_ID_RE",
]

#: Characters passed through verbatim (must equal ``PF_SAFE`` in PFUtils.pas).
SAFE_CHARS: Final[str] = string.ascii_uppercase + string.ascii_lowercase + string.digits + " -_.:\\/()+,;=#&@!?*$~^[]<>"
_SAFE_SET: Final = frozenset(SAFE_CHARS)
REQUEST_ID_RE: Final = re.compile(r"^[0-9a-f]{1,32}$")
_KEY_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

_TRANSLIT: Final[dict[str, str]] = {
    "Ω": "Ohm",  # Ω greek capital omega
    "Ω": "Ohm",  # Ω ohm sign
    "μ": "µ",  # greek mu -> micro sign (Latin-1)
    "−": "-",
    "–": "-",
    "—": "-",
    "‐": "-",
    "‑": "-",
    "‘": "'",
    "’": "'",
    "‚": ",",
    "“": '"',
    "”": '"',
    "„": '"',
    "…": "...",
    "≤": "<=",
    "≥": ">=",
    "≈": "~",
    "≠": "!=",
    "→": "->",
    "←": "<-",
    "•": "*",
    "€": "EUR",
    "™": "(TM)",
    "∞": "inf",
    "Δ": "Delta",
    "π": "pi",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "τ": "tau",
    "ω": "omega",
    "℃": "°C",
}


class BridgeProtocolError(RuntimeError):
    """Malformed request/response file (German message)."""


def transliterate(ch: str) -> str:
    """Replacement for a character above U+00FF (Latin-1 or ASCII)."""
    if ch in _TRANSLIT:
        return _TRANSLIT[ch]
    decomposed = unicodedata.normalize("NFKD", ch)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return ascii_only or "?"


def escape_field(text: str, *, unicode_text: bool = False) -> str:
    """Escape one text field for the ASCII exchange files (see module docstring).

    ``unicode_text`` keeps characters above U+00FF as escapes; it must stay ``False`` for
    anything sent to DelphiScript (``Chr`` wraps modulo 256).
    """
    out: list[str] = []
    for ch in str(text):
        if ch in _SAFE_SET:
            out.append(ch)
            continue
        code = ord(ch)
        if code > 0xFF and not unicode_text:
            out.append(escape_field(transliterate(ch), unicode_text=False))
            continue
        if code > 0xFFFF:
            out.append("%u003F")
            continue
        out.append(f"%u{code:04X}")
    return "".join(out)


_ESC_RE: Final = re.compile(r"%u([0-9A-Fa-f]{4})")


def unescape_field(text: str) -> str:
    """Inverse of :func:`escape_field` (also maps cp1252 bytes 0x80–0x9F and surrogate pairs)."""
    codes: list[int] = []
    out: list[str] = []
    pos = 0
    for m in _ESC_RE.finditer(text):
        if m.start() > pos:
            out.append(_flush(codes))
            out.append(text[pos : m.start()])
        codes.append(int(m.group(1), 16))
        pos = m.end()
    out.append(_flush(codes))
    out.append(text[pos:])
    return "".join(out)


def _flush(codes: list[int]) -> str:
    chars: list[str] = []
    i = 0
    while i < len(codes):
        code = codes[i]
        if 0xD800 <= code <= 0xDBFF and i + 1 < len(codes) and 0xDC00 <= codes[i + 1] <= 0xDFFF:
            chars.append(chr(0x10000 + ((code - 0xD800) << 10) + (codes[i + 1] - 0xDC00)))
            i += 2
            continue
        if 0x80 <= code <= 0x9F:  # ANSI (cp1252) byte from an AnsiString
            chars.append(bytes([code]).decode("cp1252", errors="replace"))
        elif 0xD800 <= code <= 0xDFFF:
            chars.append("�")
        else:
            chars.append(chr(code))
        i += 1
    codes.clear()
    return "".join(chars)


def fmt_num(value: float, digits: int = 6) -> str:
    """Locale-independent number: ``.`` as decimal separator, no exponent, ≤ ``digits`` decimals."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"Ungültige Zahl für die Altium-Brücke: {value!r}")
    text = f"{round(number, digits):.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", "", "-"):
        text = "0"
    return text


def render_request(request_id: str, command: str, args: Mapping[str, str]) -> str:
    """Request file content (CRLF, ASCII)."""
    if not REQUEST_ID_RE.match(request_id):
        raise BridgeProtocolError(f"Ungültige Anfrage-ID {request_id!r}.")
    if not _KEY_RE.match(command):
        raise BridgeProtocolError(f"Ungültiger Befehl {command!r}.")
    lines = ["PFREQ|1", f"ID|{request_id}", f"COMMAND|{command}"]
    for key, value in args.items():
        if not _KEY_RE.match(key):
            raise BridgeProtocolError(f"Ungültiger Parametername {key!r}.")
        lines.append(f"ARG|{key}|{escape_field(str(value))}")
    lines.append(f"END|{request_id}")
    return "\r\n".join(lines) + "\r\n"


@dataclass
class BridgeResponse:
    """Parsed response of one bridge command."""

    request_id: str
    ok: bool
    error: str | None = None
    values: dict[str, str] = field(default_factory=dict)
    items: dict[str, list[str]] = field(default_factory=dict)
    rows: dict[str, list[list[str]]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    raw: str = ""

    def value(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    def flag(self, key: str) -> bool:
        return self.values.get(key, "0") == "1"


def parse_response(text: str, request_id: str) -> BridgeResponse | None:
    """Parse a response file; ``None`` while it is incomplete (no ``END|<id>`` yet)."""
    lines = [line.rstrip("\r") for line in text.splitlines() if line.strip()]
    if not lines or lines[-1].strip() != f"END|{request_id}":
        return None
    if lines[0].strip() != "PFRES|1":
        raise BridgeProtocolError("Antwort der Altium-Brücke hat ein unbekanntes Format.")
    response = BridgeResponse(request_id=request_id, ok=False, raw=text)
    status_seen = False
    for line in lines[1:-1]:
        tag, _, rest = line.partition("|")
        if tag == "ID":
            if rest.strip() != request_id:
                raise BridgeProtocolError(f"Antwort gehört zu einer anderen Anfrage ({rest.strip()}).")
        elif tag == "STATUS":
            status_seen = True
            response.ok = rest.strip() == "OK"
        elif tag == "ERROR":
            response.error = unescape_field(rest)
        elif tag == "KV":
            key, _, value = rest.partition("|")
            response.values[key] = unescape_field(value)
        elif tag == "ITEM":
            key, _, value = rest.partition("|")
            response.items.setdefault(key, []).append(unescape_field(value))
        elif tag == "ROW":
            key, _, value = rest.partition("|")
            response.rows.setdefault(key, []).append([unescape_field(f) for f in value.split("|")])
        elif tag == "WARN":
            response.warnings.append(unescape_field(rest))
    if not status_seen:
        raise BridgeProtocolError("Antwort der Altium-Brücke enthält keinen Status.")
    return response
