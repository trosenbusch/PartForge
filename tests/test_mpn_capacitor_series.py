"""MLCC templates: YAGEO CC X7R and Samsung CL X7R (availability matrices), Murata GRM catalog."""
from __future__ import annotations

import pytest

from partforge.domain.mpn import decode_mpn, encode_mpn, get_template, resolve
from partforge.domain.mpn.builtin.capacitors import _SAMSUNG_THICKNESS, _YAGEO_CC_THICKNESS, samsung_thickness_rows


def decoded(template_id: str, mpn: str):
    d = decode_mpn(get_template(template_id), mpn)
    assert d is not None, mpn
    return d


# --------------------------------------------------------------------------- YAGEO CC


def test_yageo_cc_examples() -> None:
    d = decoded("yageo-cc-x7r", "CC0603KRX7R9BB104")
    assert d.valid and d.size == "0603" and d.value == pytest.approx(100e-9)
    assert d.fields["Voltage"] == "50V" and d.fields["Tolerance"] == "±10%" and d.fields["Dielectric"] == "X7R"
    assert d.attrs["thickness_code"] == "DA" and d.fields["Height"] == "0.9mm"
    blister = decoded("yageo-cc-x7r", "CC0805KKX7R7BB105")  # 1.25 mm -> blister tape K
    assert blister.valid and blister.attrs["tape"] == "blister"
    wrong = decoded("yageo-cc-x7r", "CC0805KRX7R7BB105")
    assert not wrong.valid and "passend: K" in wrong.messages[0]
    assert decoded("yageo-cc-x7r", "CC0805KPX7R7BB104").valid  # 13" paper reel
    assert not decoded("yageo-cc-x7r", "CC0402KRX7R7BB225").valid  # 2.2 µF only at 6.3 V
    assert decoded("yageo-cc-x7r", "CC0402KRX7R5BB225").valid


def test_yageo_cc_generation_picks_the_tape_of_each_cell() -> None:
    tpl = get_template("yageo-cc-x7r")
    thin = resolve(tpl, size="0805", value=100e-12, fixed={"tolerance": "K", "voltage": "7"})
    thick = resolve(tpl, size="0805", value=10e-6, fixed={"tolerance": "K", "voltage": "7"})
    assert thin.ok and thin.codes["packing"] == "R"
    assert thick.ok and thick.codes["packing"] == "K"
    assert encode_mpn(tpl, size="0805", value=10e-6, codes=thick.codes) == "CC0805KKX7R7BB106"
    note = resolve(tpl, size="0603", value=100e-9, fixed={"tolerance": "J", "voltage": "9"})
    assert note.ok and "anfragen" in note.attrs["row_note"]


def test_yageo_cc_matrix_integrity() -> None:
    tpl = get_template("yageo-cc-x7r")
    assert len(tpl.availability) == 949
    for cell in tpl.availability:
        assert cell.attrs["thickness_code"] in _YAGEO_CC_THICKNESS
        assert cell.attrs["tape"] in ("paper", "blister")
        assert cell.attrs["thickness_code"][0] == {"0201": "B", "0402": "C", "0603": "D", "0805": "E", "1206": "F",
                                                   "1210": "G", "1812": "J", "2220": "K"}[cell.size]


# --------------------------------------------------------------------------- Samsung CL


def test_samsung_examples() -> None:
    d = decoded("samsung-cl-x7r", "CL10B104KB8NNNC")
    assert d.valid and d.size == "0603" and d.value == pytest.approx(100e-9) and d.fields["Voltage"] == "50V"
    assert any("nicht geprüft" in m for m in d.messages)  # availability is marked uncertain
    assert decoded("samsung-cl-x7r", "CL21B105KBFNNNE").valid
    assert decoded("samsung-cl-x7r", "CL21B104KBCNNNC").valid
    assert decoded("samsung-cl-x7r", "CL21B104KBFNNNE").valid  # second thickness variant of the same value
    paper = decoded("samsung-cl-x7r", "CL21B105KBFNNNC")
    assert not paper.valid and "passend: E" in paper.messages[0]
    assert decoded("samsung-cl-x7r", "CL31B106KBHNNNE").valid
    assert not decoded("samsung-cl-x7r", "CL10B106KB8NNNC").valid  # not in the catalog lineup


def test_samsung_lineup_thickness_table_matches_catalog_maxima() -> None:
    rows = samsung_thickness_rows()
    assert len(rows) == 404
    for size, _v, _cap, _tol, thick, t_max in rows:
        nominal, tol = _SAMSUNG_THICKNESS[(size, thick)]
        assert nominal + tol == pytest.approx(t_max), (size, thick)


def test_samsung_resolve_sets_thickness_and_packaging() -> None:
    tpl = get_template("samsung-cl-x7r")
    res = resolve(tpl, size="0805", value=1e-6, fixed={"tolerance": "K", "voltage": "B", "thickness": "F"})
    assert res.ok and res.codes["packaging"] == "E"
    assert encode_mpn(tpl, size="0805", value=1e-6, codes=res.codes) == "CL21B105KBFNNNE"


# --------------------------------------------------------------------------- Murata GRM (catalog)


def test_murata_catalog() -> None:
    """Murata GRM: catalog checked part by part against Murata's product database (2026-10-08) and the
    official part-numbering key (pim.murata.com) – verified, with sources."""
    tpl = get_template("murata-grm-x7r")
    assert tpl.kind == "catalog" and tpl.verified and tpl.availability_certain and len(tpl.catalog) == 28
    assert any("Part Numbering" in s.title and s.url and "pim.murata.com" in s.url for s in tpl.sources)
    assert any("Produktdatenbank" in s.title for s in tpl.sources)
    d = decoded("murata-grm-x7r", "GRM188R71H104KA93D")
    assert d.valid and d.size == "0603" and d.value == pytest.approx(100e-9) and d.fields["Voltage"] == "50V"
    assert d.fields["Tolerance"] == "±10%" and d.fields["Dielectric"] == "X7R" and d.fields["Height"] == "0.9mm"
    assert d.attrs["lifecycle"] == "Abgekündigt" and "GRM155R71H104KE14" in d.attrs["row_note"]  # To be discontinued
    assert d.attrs["datasheet_url"] == "https://pim.murata.com/en-us/pim/details/?partNum=GRM188R71H104KA93%23"
    current = decoded("murata-grm-x7r", "GRM155R71H104KE14D")  # Murata's successor: in production
    assert current.valid and current.size == "0402" and "lifecycle" not in current.attrs
    big = decoded("murata-grm-x7r", "GRM32ER71A476KE15L")
    assert big.valid and big.value == pytest.approx(47e-6) and big.fields["Height"] == "2.7mm"
    assert big.attrs["tape"] == "embossed" and big.fields["Voltage"] == "10V"


@pytest.mark.parametrize(("mpn", "codes"), [
    ("GRM188R71H104KA93D", {"size": "18", "thickness": "8", "dielectric": "R7", "voltage": "1H", "value": "104",
                            "tolerance": "K", "spec": "A93", "packaging": "D"}),
    ("GRM21BR71C105KA01L", {"size": "21", "thickness": "B", "dielectric": "R7", "voltage": "1C", "value": "105",
                            "tolerance": "K", "spec": "A01", "packaging": "L"}),
])
def test_murata_part_numbering(mpn: str, codes: dict[str, str]) -> None:
    """Positions ❶–❾ of Murata's part-numbering key: GRM 18 8 R7 1H 104 K A93 D."""
    from partforge.domain.mpn.builtin.capacitors import murata_codes

    assert murata_codes(mpn) == codes
    tpl = get_template("murata-grm-x7r")
    entry = next(e for e in tpl.catalog if e.mpn == mpn)
    assert encode_mpn(tpl, size=entry.size, value=decoded("murata-grm-x7r", mpn).value or 0.0,
                      codes=entry.codes) == mpn


def test_murata_other_spellings_and_reels() -> None:
    tpl = get_template("murata-grm-x7r")
    reel = decoded("murata-grm-x7r", "GRM188R71H104KA93J")  # same part on the 330 mm paper reel
    assert reel.valid and "Verpackungsvariante" in reel.messages[0] and reel.fields["Height"] == "0.9mm"
    assert not decoded("murata-grm-x7r", "GRM188R71H104KA93L").valid  # embossed reel for a paper-taped part
    other = decoded("murata-grm-x7r", "GRM188R71H104KA01D")  # follows the key, not in the catalog
    assert not other.valid and "nicht im Katalog" in other.messages[0]
    assert decode_mpn(tpl, "GRM188R61H104KA93D") is None  # R6 = X5R: not this template
    gone = decoded("murata-grm-x7r", "GRM32ER71H106KA12L")  # former catalog entry: Murata no longer lists it
    assert not gone.valid and "nicht im Katalog" in gone.messages[0]
