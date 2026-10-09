from partforge.domain.text import NAME_PATTERN, ascii_name, clean_free_text, latin1_text


def test_clean_free_text():
    assert clean_free_text("Op-Amp | rail-to-rail\n\tdual ") == "Op-Amp / rail-to-rail dual"
    assert clean_free_text(None) == ""
    assert clean_free_text("a" * 10, max_len=5) == "aaaa…"
    assert "\x00" not in clean_free_text("x\x00y")


def test_ascii_name():
    assert ascii_name("RES 10kΩ ±1% µ-Serie") == "RES 10kOhm +-1_ u-Serie"
    assert ascii_name("SOT-23/5") == "SOT-23-5"
    assert ascii_name("Größe: Übergang") == "Groesse- Uebergang"
    assert ascii_name("") == "Bauteil"
    for raw in ["LM358 (Dual) | x", "Ω", "a/b\\c:d*e?f\"g<h>i|j", "ünïcödé"]:
        name = ascii_name(raw)
        assert NAME_PATTERN.match(name), (raw, name)


def test_latin1_text():
    assert latin1_text("10kΩ ±1% µ") == "10kOhm ±1% µ"
    assert latin1_text("a|b") == "a/b"
