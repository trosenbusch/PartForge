"""Accuracy of an extraction against the ground truth of the datasheet corpus.

``tests/data/corpus/manifest.json`` (docs/entwicklung/recherche/datasheet-corpus.md) lists for every PDF the
orderable MPNs, the pin tables per package and the package dimensions / land patterns. :func:`compare` scores an
:class:`~.models.ExtractionData` against one manifest entry:

* MPNs: recall of the printed MPNs (plus addendum MPNs, which the extraction may legitimately add),
* pins: pin numbers and names per device and package (names compared without overbars/spaces; the manifest's
  long names such as "Inverting Input" also match the short name in its function text "(-IN)"),
  electrical types reported separately (the mapping in the manifest is DERIVED),
* dimensions: every JEDEC-letter dimension of the manifest (min/nom/max within ±0.005 mm),
* land patterns: pad width/length, pitch and the row centre distance (derived from the reference).

Used by ``tests/test_datasheet_accuracy.py`` and for model/prompt evaluations.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from .models import ExtractionData, LandPatternData, PackageData

__all__ = ["AccuracyReport", "compare", "manifest_entry"]

TOLERANCE_MM = 0.005
_SYMBOL = re.compile(r"^[A-Za-z]{1,2}\d?$")


class Score(BaseModel):
    matched: int = 0
    total: int = 0
    misses: list[str] = Field(default_factory=list)

    @property
    def ratio(self) -> float:
        return self.matched / self.total if self.total else 1.0

    def add(self, ok: bool, label: str) -> None:
        self.total += 1
        if ok:
            self.matched += 1
        else:
            self.misses.append(label)


class AccuracyReport(BaseModel):
    file: str
    mpns: Score = Field(default_factory=Score)
    pins: Score = Field(default_factory=Score)
    pin_types: Score = Field(default_factory=Score)
    dimensions: Score = Field(default_factory=Score)
    land_patterns: Score = Field(default_factory=Score)
    extra_mpns: list[str] = Field(default_factory=list)
    unmatched_packages: list[str] = Field(default_factory=list)

    def summary(self) -> str:
        def fmt(score: Score) -> str:
            return f"{score.matched}/{score.total}"

        return (f"{self.file}: MPNs {fmt(self.mpns)}, Pins {fmt(self.pins)} (Typen {fmt(self.pin_types)}), "
                f"Maße {fmt(self.dimensions)}, Land Pattern {fmt(self.land_patterns)}")


_DASHES = str.maketrans("−–—", "---")


def _fold(text: str) -> str:
    text = str(text or "").replace("\\", "").translate(_DASHES)
    return re.sub(r"[^A-Z0-9+\-/]", "", text.upper())


def manifest_entry(manifest: Mapping[str, Any], file_name: str) -> dict[str, Any]:
    for entry in manifest.get("entries", []):
        if str(entry.get("file", "")).rsplit("/", 1)[-1].casefold() == file_name.casefold():
            return dict(entry)
    raise KeyError(file_name)


# --------------------------------------------------------------------------- packages


def _match_package(key: str, pins: int | None, packages: list[PackageData]) -> PackageData | None:
    code_m = re.search(r"\(([^)]+)\)", key)
    code = code_m.group(1).strip() if code_m else ""
    head = _fold(key.split("(")[0])
    best: tuple[int, PackageData] | None = None
    for pkg in packages:
        score = 0
        if code and _fold(code) == _fold(pkg.code):
            score += 4
        name = _fold(pkg.name)
        if name and (name == head or head.startswith(name) or name.startswith(head)):
            score += 3
        if pins and pkg.pin_count == pins:
            score += 1
        if score >= 3 and (best is None or score > best[0]):
            best = (score, pkg)
    return best[1] if best else None


def _gt_symbols(key: str) -> list[str]:
    tokens = [t for t in key.split("_") if t]
    if not tokens:
        return []
    if tokens[0].upper() == "EP":
        return [t for t in tokens[1:] if _SYMBOL.match(t)]
    if not _SYMBOL.match(tokens[0]):
        return []
    out = [tokens[0]]
    if len(tokens) > 1 and _SYMBOL.match(tokens[1]) and tokens[1][0].isupper():
        out.append(tokens[1])  # "D_E_body"
    return out


def _close(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and abs(a - b) <= TOLERANCE_MM + 1e-9


def _compare_dims(gt: Mapping[str, Any], pkg: PackageData, score: Score, label: str) -> None:
    for key, value in gt.items():
        if not isinstance(value, Mapping):
            continue
        for symbol in _gt_symbols(key):
            dim = pkg.dim(symbol)
            for limit in ("min", "nom", "max"):
                expected = value.get(limit)
                if expected is None:
                    continue
                got = getattr(dim, limit) if dim is not None else None
                if got is None and dim is not None and limit == "nom" and value.get("min") is None \
                        and value.get("max") is None:
                    got = dim.value()  # a basic value may be reported as min = max
                score.add(_close(float(expected), got), f"{label} {symbol}.{limit}: erwartet {expected}, "
                                                        f"erhalten {got}")


def _number(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("nom", value.get("max"))
    if isinstance(value, (list, tuple)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _center_distance(lp: LandPatternData) -> float | None:
    return lp.center_distance()


def _compare_land(gt: Mapping[str, Any], pkg: PackageData, score: Score, label: str) -> None:
    lp = pkg.land_pattern
    pairs = (
        ("pad_width_mm", lp.pad_width), ("X1_pad_width_max_mm", lp.pad_width), ("X_pad_width_max_mm", lp.pad_width),
        ("pad_length_mm", lp.pad_length), ("Y1_pad_length_max_mm", lp.pad_length),
        ("Y_pad_length_max_mm", lp.pad_length), ("pitch_mm", lp.pitch), ("E_pitch_mm", lp.pitch),
    )
    seen: set[str] = set()
    for key, got in pairs:
        expected = _number(gt.get(key))
        what = key.split("_")[0] + ("_w" if "width" in key else "_l" if "length" in key else "")
        if expected is None or what in seen:
            continue
        seen.add(what)
        score.add(_close(expected, got), f"{label} Land Pattern {key}: erwartet {expected}, erhalten {got}")
    center = None
    for key in ("row_center_distance_mm", "row_center_distance_mm_DERIVED", "C_pad_center_spacing_mm"):
        center = _number(gt.get(key))
        if center is not None:
            break
    if center is not None:
        got = _center_distance(lp)
        score.add(got is not None and abs(got - center) <= 0.02,
                  f"{label} Land Pattern Reihenabstand Mitte: erwartet {center}, erhalten {got}")


# --------------------------------------------------------------------------- pins


def _pin_name_ok(got: str, gt: Mapping[str, Any]) -> bool:
    name = _fold(got)
    expected = _fold(str(gt.get("name", "")))
    if name == expected:
        return True
    function = str(gt.get("function", ""))
    for alias in re.findall(r"\(([^)]+)\)", function):
        if _fold(alias) == name:
            return True
    synonyms = {"OUTPUT": "OUT", "NONINVERTINGINPUT": "+IN", "INVERTINGINPUT": "-IN", "N/C": "NC"}
    return synonyms.get(expected) == name


def _compare_pins(entry: Mapping[str, Any], data: ExtractionData, report: AccuracyReport) -> None:
    for gt_device in entry.get("devices", []):
        base = _fold(gt_device.get("base_part", ""))
        device = next((d for d in data.devices if _fold(d.base_part) == base), None)
        if device is None:
            device = next((d for d in data.devices if base and base in _fold(d.base_part)), None)
        for key, gt_pins in (gt_device.get("pin_tables") or {}).items():
            pins_total = len([p for p in gt_pins if not p.get("exposed_pad")])
            pkg = _match_package(key, pins_total, data.packages)
            table = device.pin_table(pkg.code) if device is not None and pkg is not None else None
            label = f"{gt_device.get('base_part')} {key}"
            for gt in gt_pins:
                if gt.get("exposed_pad") and not str(gt.get("number", "")).isdigit():
                    continue  # unnumbered exposed pad: handled by the footprint, not the pin table
                number = _fold(str(gt["number"]))
                pin = next((p for p in table.pins if _fold(p.number) == number), None) if table is not None else None
                report.pins.add(pin is not None and _pin_name_ok(pin.name, gt),
                                f"{label} Pin {gt['number']}: erwartet {gt.get('name')}, "
                                f"erhalten {pin.name if pin else '—'}")
                expected_type = str(gt.get("electrical_type", "")).lower().replace("opencollector", "open_collector")
                report.pin_types.add(pin is not None and pin.electrical == expected_type,
                                     f"{label} Pin {gt['number']}: Typ {expected_type}, erhalten "
                                     f"{pin.electrical if pin else '—'}")


# --------------------------------------------------------------------------- main entry


def compare(data: ExtractionData, entry: Mapping[str, Any]) -> AccuracyReport:
    """Score an extraction against one manifest entry (see module docstring)."""
    report = AccuracyReport(file=str(entry.get("file", "")))
    found = {_fold(m) for m in data.mpns()}
    expected: list[str] = []
    for device in entry.get("devices", []):
        for item in device.get("mpns") or device.get("mpns_DERIVED") or []:
            expected.append(item["mpn"] if isinstance(item, Mapping) else str(item))
    for mpn in expected:
        report.mpns.add(_fold(mpn) in found, f"MPN {mpn} fehlt")
    allowed = {_fold(m) for m in expected}
    for device in entry.get("devices", []):
        allowed |= {_fold(str(m).split(" ")[0]) for m in device.get("additional_orderables_addendum") or []}
    report.extra_mpns = sorted(m for m in data.mpns() if _fold(m) not in allowed)
    _compare_pins(entry, data, report)
    for key, gt_pkg in (entry.get("packages") or {}).items():
        pkg = _match_package(key, gt_pkg.get("pins"), data.packages)
        if pkg is None:
            report.unmatched_packages.append(key)
            continue
        _compare_dims(gt_pkg.get("dims_mm") or {}, pkg, report.dimensions, key)
        if gt_pkg.get("land_pattern"):
            _compare_land(gt_pkg["land_pattern"], pkg, report.land_patterns, key)
    return report
