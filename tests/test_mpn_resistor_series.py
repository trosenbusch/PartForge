"""Resistor templates (YAGEO RC_L, Panasonic ERJ, KOA RK73H/RK73B, Stackpole RMCF, UNI-ROYAL, Bourns CR):
datasheet ordering examples, value rules and code restrictions."""
from __future__ import annotations

import pytest

from partforge.domain.mpn import decode_mpn, encode_mpn, get_template, resolve


def decoded(template_id: str, mpn: str):
    d = decode_mpn(get_template(template_id), mpn)
    assert d is not None, mpn
    return d


def valid(template_id: str, mpn: str) -> bool:
    return decoded(template_id, mpn).valid


# --------------------------------------------------------------------------- YAGEO RC_L


def test_yageo_examples() -> None:
    d = decoded("yageo-rc-l", "RC0603FR-0710KL")
    assert d.valid and d.size == "0603" and d.value == 10e3
    assert d.fields["Tolerance"] == "±1%" and d.fields["TCR"] == "±100ppm/K" and d.fields["Power"] == "0.1W"
    example = decoded("yageo-rc-l", "RC0402JR-07100KL")  # datasheet ordering example (p. 2)
    assert example.valid and example.value == 100e3 and example.fields["Tolerance"] == "±5%"
    jumper = decoded("yageo-rc-l", "RC0603JR-070RL")
    assert jumper.valid and jumper.jumper and "Tolerance" not in jumper.fields
    assert decoded("yageo-rc-l", "RC0603FR-0710K2L").value == 10.2e3
    assert decoded("yageo-rc-l", "rc0603fr0710kl").mpn == "RC0603FR-0710KL"  # compact form, canonical spelling


def test_yageo_rules() -> None:
    assert valid("yageo-rc-l", "RC0603JR-0722ML")  # 5 % up to 22 MΩ
    assert not valid("yageo-rc-l", "RC0603FR-0722ML")  # 1 % ends at 10 MΩ
    assert valid("yageo-rc-l", "RC2512FK-0710KL")  # 2512: embossed tape K
    assert not valid("yageo-rc-l", "RC2512FR-0710KL")
    double = decoded("yageo-rc-l", "RC1206FR-7W10KL")
    assert double.valid and double.fields["Power"] == "0.5W" and double.fields["TCR"] == "±200ppm/K"
    assert not valid("yageo-rc-l", "RC1210FR-7W10KL")  # double power not for 1210
    assert not valid("yageo-rc-l", "RC0603FR-7W22ML")  # double power only up to 1 MΩ
    tpl = get_template("yageo-rc-l")
    assert decoded("yageo-rc-l", "RC0603FR-074R7L").fields["TCR"] == "±200ppm/K"
    assert decoded("yageo-rc-l", "RC0603JR-0715ML").fields["TCR"] == "±200ppm/K"
    res = resolve(tpl, size="0603", value=4.7e3, fixed={"tolerance": "J"})
    assert encode_mpn(tpl, size="0603", value=4.7e3, codes=res.codes) == "RC0603JR-074K7L"


# --------------------------------------------------------------------------- Panasonic ERJ


def test_panasonic_1pct() -> None:
    d = decoded("panasonic-erj-1pct", "ERJ-3EKF1002V")
    assert d.valid and d.size == "0603" and d.value == 10e3
    assert d.fields["TCR"] == "±100ppm/K" and d.fields["Power"] == "0.1W" and d.fields["Voltage"] == "75V"
    assert decoded("panasonic-erj-1pct", "ERJ3EKF1002V").mpn == "ERJ-3EKF1002V"
    assert valid("panasonic-erj-1pct", "ERJ-3EKF10R0V")
    assert not valid("panasonic-erj-1pct", "ERJ-3EKF4R70V")  # below 10 Ω (ERJ-2RC/… not covered)
    assert valid("panasonic-erj-1pct", "ERJ-6ENF2204V")  # 0805 up to 2.2 MΩ
    assert not valid("panasonic-erj-1pct", "ERJ-3EKF2204V")  # 0603 up to 1 MΩ
    assert valid("panasonic-erj-1pct", "ERJ-2RKF1002X")
    assert not valid("panasonic-erj-1pct", "ERJ-2RKF1002V")  # 0402 ships as X
    assert decoded("panasonic-erj-1pct", "ERJ-8ENF1002V").attrs["lifecycle"] == "NRND"


def test_panasonic_5pct() -> None:
    assert valid("panasonic-erj-5pct", "ERJ-3GEYJ102V")  # datasheet example
    d = decoded("panasonic-erj-5pct", "ERJ-3GEYJ103V")
    assert d.valid and d.value == 10e3 and d.fields["TCR"] == "±200ppm/K"
    assert valid("panasonic-erj-5pct", "ERJ-2GEJ103X")  # 0402 without marking letter Y
    assert not valid("panasonic-erj-5pct", "ERJ-3GEJ103V")  # 0603 needs Y
    jumper = decoded("panasonic-erj-5pct", "ERJ-3GEY0R00V")
    assert jumper.valid and jumper.jumper and jumper.fields["Notes"].startswith("0-Ω-Brücke")
    assert valid("panasonic-erj-5pct", "ERJ-2GE0R00X")
    assert decoded("panasonic-erj-5pct", "ERJ-3GEYJ4R7V").fields["TCR"] == "-100 … +600ppm/K"
    assert valid("panasonic-erj-5pct", "ERJ-1TYJ105U") and not valid("panasonic-erj-5pct", "ERJ-1TYJ225U")


# --------------------------------------------------------------------------- KOA


def test_koa_rk73h() -> None:
    d = decoded("koa-rk73h", "RK73H2BTTD1003F")  # datasheet ordering example
    assert d.valid and d.size == "1206" and d.value == 100e3 and d.fields["TCR"] == "±100ppm/K"
    assert decoded("koa-rk73h", "RK73H1JTTD1002F").fields["Power"] == "0.1W"
    assert decoded("koa-rk73h", "RK73H1JTTD1000F").fields["Power"] == "0.125W"  # 10 Ω … 1 kΩ
    assert valid("koa-rk73h", "RK73H1ETTP1002F")
    assert not valid("koa-rk73h", "RK73H1ETTD1002F")  # 0402 is taped TP
    assert valid("koa-rk73h", "RK73H2BTTD5604F") and not valid("koa-rk73h", "RK73H2BTTD5604D")
    assert valid("koa-rk73h", "RK73H1JATTD1002F")  # heat-shock version
    assert valid("koa-rk73h", "RK73HW3ATTE1002F")


def test_koa_rk73b() -> None:
    d = decoded("koa-rk73b", "RK73B2BTTD102J")  # datasheet ordering example
    assert d.valid and d.value == 1e3 and d.fields["Tolerance"] == "±5%"
    assert decoded("koa-rk73b", "RK73B1JTTD103J").fields["Power"] == "0.1W"
    assert decoded("koa-rk73b", "RK73B1JTTD4R7J").fields["Power"] == "0.125W"
    assert valid("koa-rk73b", "RK73B1JTTD226J") and not valid("koa-rk73b", "RK73B1JTTD226G")


# --------------------------------------------------------------------------- Stackpole RMCF


def test_stackpole_rmcf() -> None:
    assert valid("stackpole-rmcf", "RMCF0603JT4K70")  # datasheet example
    assert valid("stackpole-rmcf", "RMCF0603FT10K0")
    jumper = decoded("stackpole-rmcf", "RMCF0603ZT0R00")
    assert jumper.valid and jumper.jumper
    assert valid("stackpole-rmcf", "RMCF0603FT4K99") and not valid("stackpole-rmcf", "RMCF0603JT4K99")
    assert decoded("stackpole-rmcf", "RMCF0603FTR100").fields["TCR"] == "±500ppm/K"
    assert valid("stackpole-rmcf", "RMCF0402FT22M1") and valid("stackpole-rmcf", "RMCF0402JT22M0")
    assert valid("stackpole-rmcf", "RMCF0603FG10K0") and not valid("stackpole-rmcf", "RMCF0402FG10K0")


# --------------------------------------------------------------------------- UNI-ROYAL


def test_uniohm() -> None:
    d = decoded("uniohm-chip", "0805W8J0103T5E")  # datasheet ordering example
    assert d.valid and d.value == 10e3 and d.fields["Power"] == "0.125W" and d.fields["Tolerance"] == "±5%"
    assert valid("uniohm-chip", "0603WAF1002T5E")
    assert decoded("uniohm-chip", "0603WAF100JT5E").value == 10
    assert decoded("uniohm-chip", "0603WAF470KT5E").value == 4.7
    assert valid("uniohm-chip", "0402WGF1001TCE")
    assert not valid("uniohm-chip", "0603WAF1002TCE")  # quantity code C is for 0402
    assert not valid("uniohm-chip", "0603W8F1002T5E")  # power code of 0805
    assert decode_mpn(get_template("uniohm-chip"), "0603WAJ1002T5E") is None  # 5 %: leading 0, 2 digits
    tpl = get_template("uniohm-chip")
    res = resolve(tpl, size="0603", value=4.7e3, fixed={"tolerance": "J"})
    assert encode_mpn(tpl, size="0603", value=4.7e3, codes=res.codes) == "0603WAJ0472T5E"


# --------------------------------------------------------------------------- Bourns CR


def test_bourns_cr() -> None:
    d = decoded("bourns-cr", "CR1206-FX-1003ELF")  # datasheet ordering example
    assert d.valid and d.value == 100e3 and d.fields["TCR"] == "±100ppm/K"
    assert decoded("bourns-cr", "CR0603FX1002ELF").mpn == "CR0603-FX-1002ELF"
    assert valid("bourns-cr", "CR0603-JW-103ELF")
    jumper = decoded("bourns-cr", "CR0603-J/-000ELF")
    assert jumper.valid and jumper.jumper
    low = decoded("bourns-cr", "CR0603-F/-4R70ELF")
    assert low.valid and low.fields["TCR"] == "±200ppm/K"
    assert not valid("bourns-cr", "CR0603-FX-4R70ELF")
    assert valid("bourns-cr", "CR0603-FW-2004ELF") and not valid("bourns-cr", "CR0603-FX-2004ELF")
    assert valid("bourns-cr", "CR0402-JZ-156GLF")
    assert not valid("bourns-cr", "CR0603-FX-1002GLF")


@pytest.mark.parametrize(("tolerance", "value", "tcr"), [
    ("F", 10e3, "X"), ("F", 4.7, "/"), ("F", 2e6, "W"), ("J", 15e6, "Z"), ("J", 10e3, "W"), ("J", 4.7, "/"),
])
def test_bourns_cr_derived_tcr_code(tolerance: str, value: float, tcr: str) -> None:
    res = resolve(get_template("bourns-cr"), size="0603", value=value, fixed={"tolerance": tolerance})
    assert res.ok and res.codes["tcr"] == tcr


def test_tcr_filter_without_tcr_code() -> None:
    """Templates whose part number has no TCR code filter the rules by the TCR attribute."""
    tpl = get_template("koa-rk73h")
    assert resolve(tpl, size="0805", value=10e3, fixed={"tolerance": "F"}, attr_filters={"tcr": 100}).ok
    rejected = resolve(tpl, size="0805", value=10e3, fixed={"tolerance": "F"}, attr_filters={"tcr": 200})
    assert not rejected.ok and rejected.messages == ["10kΩ gibt es nur mit ±100ppm/K."]


def test_yageo_reel_codes() -> None:
    """Datasheet V.14 p. 2: 7D = 7" reel with twice the quantity (0201/0402), 3W = 13" reel with twice the
    power; Table 4: no 13" reel for 1218/2512 (regression: both codes were missing)."""
    assert valid("yageo-rc-l", "RC0402FR-7D10KL") and valid("yageo-rc-l", "RC0201JR-7D10KL")
    assert not valid("yageo-rc-l", "RC0603FR-7D10KL")
    double = decoded("yageo-rc-l", "RC0603FR-3W10KL")
    assert double.valid and double.fields["Power"] == "0.2W" and double.fields["TCR"] == "±200ppm/K"
    assert not valid("yageo-rc-l", "RC0603FR-3W22ML")  # double power only up to 1 MΩ
    assert not valid("yageo-rc-l", "RC2512FK-3W10KL") and valid("yageo-rc-l", "RC2512FK-7W10KL")
    assert valid("yageo-rc-l", "RC2010FK-1310KL") and not valid("yageo-rc-l", "RC2512FK-1310KL")


@pytest.mark.parametrize(("mpn", "ok"), [
    ("RC0603JR-070RL", True), ("RC0603JR-100RL", True), ("RC0603JR-130RL", True), ("RC0402JR-7D0RL", True),
    ("RC0603JR-7W0RL", False), ("RC0603JR-3W0RL", False), ("RC0603FR-070RL", False),
])
def test_yageo_jumper_reels(mpn: str, ok: bool) -> None:
    d = decoded("yageo-rc-l", mpn)
    assert d.jumper and d.valid is ok, d.messages


def test_yageo_jumper_follows_the_requested_reel() -> None:
    tpl = get_template("yageo-rc-l")
    res = resolve(tpl, size="0603", value=0.0, fixed={"packaging": "13"}, jumper=True)
    assert res.ok and encode_mpn(tpl, size="0603", value=0.0, codes=res.codes, jumper=True) == "RC0603JR-130RL"
    res = resolve(tpl, size="0603", value=0.0, fixed={"packaging": "7W"}, jumper=True)
    assert res.ok and res.codes["packaging"] == "07"
    assert res.messages == ["Brücken gibt es nicht mit Rolle / Leistung „7W“ – „07“ verwendet."]
