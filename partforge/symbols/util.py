"""Small helpers shared by the symbol generator modules."""

from __future__ import annotations

import re

from .errors import SymbolError

__all__ = [
    "MAX_NAME_LENGTH",
    "MAX_PART_COUNT",
    "NAME_RE",
    "PREFIX_RE",
    "check_name",
    "check_prefix",
    "natural_key",
]

NAME_RE = re.compile(r"^[A-Za-z0-9_.\-+() ]{1,64}$")
PREFIX_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,9}$")
MAX_NAME_LENGTH = 64
MAX_PART_COUNT = 64
_SPLIT_RE = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key that orders embedded numbers numerically: ``PA2 < PA10``, ``2 < 10``."""
    out: list[tuple[int, int | str]] = []
    for token in _SPLIT_RE.split(value):
        if not token:
            continue
        out.append((0, int(token)) if token.isdigit() else (1, token.upper()))
    return tuple(out)


def check_name(name: str) -> str:
    """Validate a symbol name (ASCII ``[A-Za-z0-9_.-+() ]``, at most 64 characters)."""
    if not isinstance(name, str) or not name.strip():
        raise SymbolError("Der Symbolname fehlt.")
    if name != name.strip():
        raise SymbolError(f"Der Symbolname {name!r} darf nicht mit Leerzeichen beginnen oder enden.")
    if len(name) > MAX_NAME_LENGTH:
        raise SymbolError(f"Der Symbolname {name!r} ist länger als {MAX_NAME_LENGTH} Zeichen.")
    if not NAME_RE.match(name):
        bad = " ".join(sorted({repr(c) for c in name if not re.match(r"[A-Za-z0-9_.\-+() ]", c)}))
        raise SymbolError(
            f"Der Symbolname {name!r} enthält unzulässige Zeichen ({bad}). Erlaubt sind A–Z, a–z, 0–9, "
            "Leerzeichen und _ . - + ( )."
        )
    if name.startswith("__PF"):
        raise SymbolError(f"Der Symbolname {name!r} ist reserviert (Präfix __PF).")
    return name


def check_prefix(prefix: str) -> str:
    """Validate a designator prefix (letter first, letters/digits/_ , at most 10 characters)."""
    if not isinstance(prefix, str) or not PREFIX_RE.match(prefix):
        raise SymbolError(
            f"Ungültiges Bezeichner-Präfix {prefix!r}: ein Buchstabe, danach Buchstaben, Ziffern oder _ "
            "(höchstens 10 Zeichen), z. B. R, C, U, FB."
        )
    return prefix
