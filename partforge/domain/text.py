"""Text hygiene for everything that ends up in Altium files.

Altium stores free text unescaped inside ``|KEY=value|`` records, so ``|`` and control
characters must never reach a SchLib/PcbLib (the Rust writer rejects them). Component
names (Library Ref / Footprint Ref) must be plain ASCII.

    clean_free_text("Op-Amp | rail-to-rail\\n")  -> "Op-Amp / rail-to-rail"
    ascii_name("RES 10kΩ ±1% µ-Serie")         -> "RES 10kOhm +-1% u-Serie"
    latin1_text("Ω-Wert")                       -> "Ohm-Wert"

Identity fields (Part Number, Manufacturer Part Number) are stored without invisible format
characters (Unicode category Cf: soft hyphen, zero-width space, BOM, bidi marks/overrides …) in NFC
(:func:`identity_text`) and compared by :func:`identity_key` (NFKC, format characters removed,
case-folded: "GRM188\u00adR71" = "grm188r71", "UNIQ-STRASSE" = "uniq-straße").
"""
from __future__ import annotations

import re
import unicodedata

__all__ = [
    "clean_free_text", "ascii_name", "latin1_text", "plural", "TRANSLITERATION", "NAME_PATTERN",
    "FORMAT_CHARS", "strip_format_chars", "identity_text", "identity_key",
]

TRANSLITERATION = {
    "Ω": "Ohm", "Ω": "Ohm", "µ": "u", "μ": "u", "±": "+-", "°": "deg", "²": "2", "³": "3",
    "×": "x", "÷": "/", "–": "-", "—": "-", "‐": "-", "−": "-", "’": "'", "‘": "'", "“": '"', "”": '"',
    "…": "...", "≤": "<=", "≥": ">=", "≈": "~", "→": "->", "ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe",
    "Ü": "Ue", "ß": "ss", "€": "EUR", "®": "(R)", "™": "(TM)", "©": "(C)", " ": " ", " ": " ",
}

# Characters allowed in Library Ref / Footprint Ref names (matches the writers' validation).
NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.\-+() ]+$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_SPACES = re.compile(r"\s+")


#: Invisible format characters (Unicode 15.1 category Cf: soft hyphen, Arabic number signs, zero-width
#: space/joiners, LRM/RLM, bidi embeddings/overrides/isolates, word joiner, invisible operators, BOM,
#: interlinear annotation, tags …) – copied along with MPNs from web pages and PDFs. Never a meaningful
#: part of a part number; written as escapes on purpose (no invisible characters in the source).
FORMAT_CHARS = re.compile("[\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890-\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb\U000110bd\U000110cd\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f]")


def strip_format_chars(text: str) -> str:
    """``text`` without invisible format characters (:data:`FORMAT_CHARS`)."""
    return FORMAT_CHARS.sub("", text)


def identity_text(text: str) -> str:
    """Stored spelling of an identity value (part number, MPN): NFC, without format characters,
    trimmed – "UNIQ-A\u0308-2" -> "UNIQ-\u00c4-2", "GRM188\u00adR71\u200b" -> "GRM188R71"."""
    if text.isascii():
        return text.strip()
    return strip_format_chars(unicodedata.normalize("NFC", text)).strip()


def identity_key(text: str) -> str:
    """Comparison key of an identity value: NFKC, without format characters, trimmed, case-folded
    (ASCII: just lower-cased) – look-alike spellings of one part number get the same key."""
    if text.isascii():
        return text.strip().lower()
    return strip_format_chars(unicodedata.normalize("NFKC", text)).strip().casefold()


def clean_free_text(text: str | None, *, max_len: int | None = None) -> str:
    """Make free text safe for Altium records: no '|', no control characters, single spaces."""
    if not text:
        return ""
    t = _CONTROL.sub(" ", str(text)).replace("|", "/")
    t = _SPACES.sub(" ", t).strip()
    if max_len is not None and len(t) > max_len:
        t = t[: max(0, max_len - 1)].rstrip() + "…"
    return t


def _transliterate(text: str) -> str:
    out = "".join(TRANSLITERATION.get(ch, ch) for ch in text)
    # strip remaining accents (é -> e) and drop what is still non-ASCII
    out = unicodedata.normalize("NFKD", out)
    return "".join(ch for ch in out if ord(ch) < 128 and not unicodedata.combining(ch))


def ascii_name(text: str | None, *, max_len: int = 64, fallback: str = "Bauteil") -> str:
    """A valid ASCII component name for SchLib/PcbLib (Library Ref / Footprint Ref)."""
    t = _transliterate(clean_free_text(text))
    t = t.replace("/", "-").replace("\\", "-").replace(":", "-").replace("*", "x")
    t = re.sub(r"[?\"<>|]", "", t)
    t = re.sub(r"[^A-Za-z0-9_.\-+() ]", "_", t)
    t = _SPACES.sub(" ", t).strip(" ._")
    if len(t) > max_len:
        t = t[:max_len].rstrip(" ._")
    return t or fallback


def latin1_text(text: str | None) -> str:
    """Text for fields Altium stores as Latin-1 (PcbLib descriptions): Ω -> Ohm, µ stays."""
    t = clean_free_text(text)
    out = []
    for ch in t:
        try:
            ch.encode("latin-1")
            out.append(ch)
        except UnicodeEncodeError:
            out.append(_transliterate(ch) or "?")
    return "".join(out)


def plural(count: int, one: str, many: str, *, with_count: bool = True) -> str:
    """German count phrase for user messages: ``plural(1, "Bauteil", "Bauteile")`` -> "1 Bauteil",
    ``plural(3, …)`` -> "3 Bauteile" (thousands with a dot: "1.250 Bauteile")."""
    word = one if count == 1 else many
    if not with_count:
        return word
    return f"{count:,}".replace(",", ".") + f" {word}"
