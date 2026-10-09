"""ASCII exchange format of the DelphiScript bridge (escaping, numbers, request/response)."""
from __future__ import annotations

import locale
import re
from pathlib import Path

import pytest

from partforge.altium.bridge.core import SCRIPTS_DIR
from partforge.altium.bridge.protocol import (
    SAFE_CHARS,
    BridgeProtocolError,
    escape_field,
    fmt_num,
    parse_response,
    render_request,
    transliterate,
    unescape_field,
)


@pytest.mark.parametrize(
    "text",
    ["plain", "a|b", "100%", "line1\r\nline2", "Widerstände ±1 % µF °C ß", "R\\E\\S\\E\\T\\", "", "tab\tend", "'quote' \"dq\""],
)
def test_escape_roundtrip_latin1(text):
    escaped = escape_field(text)
    assert escaped.isascii()
    assert "|" not in escaped and "\r" not in escaped and "\n" not in escaped
    assert unescape_field(escaped) == text


def test_escape_uses_percent_u_and_keeps_safe_chars():
    assert escape_field("A|B%C") == "A%u007CB%u0025C"
    assert escape_field("ä") == "%u00E4"
    assert escape_field("C:\\Lib\\PF_Passives.SchLib") == "C:\\Lib\\PF_Passives.SchLib"


def test_characters_above_latin1_are_transliterated_by_default():
    assert unescape_field(escape_field("10 kΩ")) == "10 kOhm"
    assert unescape_field(escape_field("μC")) == "µC"
    assert unescape_field(escape_field("≤ 5 V – max…")) == "<= 5 V - max..."
    assert unescape_field(escape_field("Čech")) == "Cech"
    assert unescape_field(escape_field("漢")) == "?"
    assert transliterate("€") == "EUR"


def test_unicode_text_mode_keeps_characters():
    text = "10 kΩ €"
    escaped = escape_field(text, unicode_text=True)
    assert "%u03A9" in escaped and "%u20AC" in escaped
    assert unescape_field(escaped) == text
    assert escape_field("😀", unicode_text=True) == "%u003F"


def test_unescape_handles_surrogates_and_ansi_bytes():
    assert unescape_field("%uD83D%uDE00") == "😀"
    assert unescape_field("%u0080") == "€"  # cp1252 byte from an AnsiString
    assert unescape_field("x%uD800y") == "x\ufffdy"
    assert unescape_field("%u00") == "%u00"  # malformed escapes stay literal


def test_safe_chars_match_pascal_constant():
    text = (SCRIPTS_DIR / "PFUtils.pas").read_text(encoding="ascii")
    m = re.search(r"PF_SAFE = '([^']*)';", text)
    assert m is not None
    assert m.group(1) == SAFE_CHARS


@pytest.mark.parametrize(
    ("value", "text"),
    [(0.55, "0.55"), (-0.8, "-0.8"), (5, "5"), (-0.0, "0"), (1e-7, "0"), (123456.7891234, "123456.789123"), (2.54, "2.54"), (-1e-9, "0")],
)
def test_fmt_num(value, text):
    assert fmt_num(value) == text


def test_fmt_num_rejects_non_finite():
    with pytest.raises(ValueError, match="Ungültige Zahl"):
        fmt_num(float("nan"))
    with pytest.raises(ValueError):
        fmt_num(float("inf"))


def test_fmt_num_ignores_german_locale():
    old = locale.setlocale(locale.LC_NUMERIC)
    for name in ("German_Germany.1252", "de_DE.UTF-8", "de_DE"):
        try:
            locale.setlocale(locale.LC_NUMERIC, name)
            break
        except locale.Error:
            continue
    else:
        pytest.skip("keine deutsche Locale verfügbar")
    try:
        assert locale.localeconv()["decimal_point"] == ","
        assert fmt_num(0.55) == "0.55"
    finally:
        locale.setlocale(locale.LC_NUMERIC, old)


def test_render_request():
    text = render_request("0123456789ab", "install_library", {"path": "C:\\Bibliothek\\Widerstände.DbLib", "x": "a|b"})
    assert text.endswith("\r\n") and text.isascii()
    lines = text.split("\r\n")[:-1]
    assert lines == [
        "PFREQ|1",
        "ID|0123456789ab",
        "COMMAND|install_library",
        "ARG|path|C:\\Bibliothek\\Widerst%u00E4nde.DbLib",
        "ARG|x|a%u007Cb",
        "END|0123456789ab",
    ]


@pytest.mark.parametrize(
    ("rid", "command", "args"),
    [("XYZ", "ping", {}), ("abc", "Ping!", {}), ("abc", "ping", {"Bad Key": "1"}), ("", "ping", {})],
)
def test_render_request_rejects_bad_input(rid, command, args):
    with pytest.raises(BridgeProtocolError):
        render_request(rid, command, args)


def test_parse_response_complete():
    text = "\r\n".join(
        [
            "PFRES|1",
            "ID|abc",
            "STATUS|OK",
            "KV|version|26.10.1.5",
            "KV|path|C:\\x%u007Cy",
            "ITEM|libraries|A.IntLib",
            "ITEM|libraries|B%u00E4.DbLib",
            "ROW|models|PCBLIB|RESC1608X55N|1",
            "WARN|Achtung %u00B1",
            "END|abc",
            "",
        ]
    )
    resp = parse_response(text, "abc")
    assert resp is not None and resp.ok and resp.error is None
    assert resp.value("version") == "26.10.1.5" and resp.value("path") == "C:\\x|y"
    assert resp.items["libraries"] == ["A.IntLib", "Bä.DbLib"]
    assert resp.rows["models"] == [["PCBLIB", "RESC1608X55N", "1"]]
    assert resp.warnings == ["Achtung ±"]
    assert resp.value("missing", "default") == "default" and not resp.flag("missing")


def test_parse_response_error_and_incomplete():
    assert parse_response("PFRES|1\r\nID|abc\r\nSTATUS|OK\r\n", "abc") is None
    assert parse_response("", "abc") is None
    resp = parse_response("PFRES|1\nID|abc\nSTATUS|ERROR\nERROR|spec file not found: C:%u005Cx\nEND|abc\n", "abc")
    assert resp is not None and not resp.ok and resp.error == "spec file not found: C:\\x"
    with pytest.raises(BridgeProtocolError):
        parse_response("XXX|1\nEND|abc\n", "abc")
    with pytest.raises(BridgeProtocolError):
        parse_response("PFRES|1\nID|other\nSTATUS|OK\nEND|abc\n", "abc")
    with pytest.raises(BridgeProtocolError):
        parse_response("PFRES|1\nID|abc\nEND|abc\n", "abc")


def test_scripts_folder_exists():
    assert isinstance(SCRIPTS_DIR, Path) and (SCRIPTS_DIR / "PartForgeBridge.PrjScr").is_file()
