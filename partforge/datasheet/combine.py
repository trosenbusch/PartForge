"""Combine the analyses of two datasheets: the package drawing of one document for the device of another
(ARCHITEKTUR §10 „Gehäuse aus anderem Datenblatt“).

Manufacturers often publish the package drawing (outline, land pattern) as a separate document – TI's package-outline
PDFs (``qfnd819.pdf`` for RGY0019B), package addenda – while the device datasheet only names the package. Both are
analysed on their own; :func:`merge_package` copies the drawing data of a package of one analysis (the *source*) into
a package of another (the *target*, the device datasheet), so the target's proposal builds the footprint from it and
"Bauteil anlegen" creates the complete part.

* Taken over: family, pin count, mounting, outline reference, exposed pad (flag and number), drawing pages, dimensions,
  the manufacturer land pattern and the terminal layout. Kept: the target's package code (its variants and pin tables
  refer to it) and name (the "Package" value of its parts – the source's name if the target has none).
* ``PackageData.origin`` records the source (datasheet, package, file name, title) and the package as it was before the
  first takeover – :func:`unmerge_package` restores it. The pages of a merged package are pages of the source PDF.
* Stored like a user correction (``extract.store_edited_extraction``: same hygiene, plausibility checks recomputed,
  ``edited``) under the metadata lock of the target; a new analysis of the target replaces it like any correction.

:func:`package_sources` lists the packages with drawing data of the other analysed datasheets, best match first (same
pin count, family, exposed pad, name or code, manufacturer; package drawings without device first), with German notes;
:func:`package_targets` the other way round – the packages of device datasheets a drawing could complete (those whose
dimensions are missing first).
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..db import registry
from ..domain.text import plural
from ..workspace import Workspace, current
from . import store
from .errors import DatasheetError, NoExtraction
from .models import ExtractionData, PackageBase, PackageData, PackageOrigin

__all__ = ["MergeResult", "PackageSource", "PackageTarget", "merge_package", "package_sources", "package_targets",
           "unmerge_package"]


class PackageSource(BaseModel):
    """A package of another analysed datasheet whose drawing data can be taken over."""

    datasheet_id: str
    file: str = Field(description="Dateiname des PDFs")
    title: str = ""
    manufacturer: str = ""
    package: str = Field(description="Gehäusecode im anderen Datenblatt")
    label: str = Field(description="„VQFN-19 3.5x4.5 (RGY0019B)“")
    family: str | None = None
    pin_count: int | None = None
    exposed_pad: bool = False
    exposed_pad_number: str = ""
    dimensions: int = Field(default=0, description="Verwertbare Maße (mm)")
    land_pattern: bool = Field(default=False, description="Vollständige Herstellerempfehlung (Land Pattern)")
    layout: bool = Field(default=False, description="Anschlussanordnung angegeben")
    package_only: bool = Field(default=False, description="Das Datenblatt beschreibt kein Bauteil (Gehäusezeichnung)")
    pages: list[int] = Field(default_factory=list)
    score: int = Field(default=0, description="Passung – höher ist besser (Reihenfolge der Liste)")
    matches: list[str] = Field(default_factory=list, description="Was passt (deutsch)")
    problems: list[str] = Field(default_factory=list, description="Was nicht passt (deutsch)")


class PackageTarget(BaseModel):
    """A package of a device datasheet that the drawing of a package drawing could complete."""

    datasheet_id: str
    file: str = Field(description="Dateiname des PDFs")
    title: str = ""
    devices: list[str] = Field(default_factory=list, description="Bauteile des Datenblatts")
    package: str = Field(description="Gehäusecode im Bauteil-Datenblatt")
    label: str
    pin_count: int | None = None
    dimensions: int = Field(default=0, description="Verwertbare Maße, die es schon hat")
    dims_missing: bool = Field(default=False, description="Die Prüfung meldet fehlende Maße")
    merged_from: str = Field(default="", description="Dateiname, aus dem es seine Maße schon übernommen hat")
    score: int = 0
    matches: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class MergeResult(BaseModel):
    extraction: ExtractionData
    notes: list[str] = Field(default_factory=list)  # German hints about the takeover (pin count, exposed pad …)


def _fold(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def _index(data: ExtractionData, code: str) -> int | None:
    wanted = code.strip().casefold()
    return next((i for i, p in enumerate(data.packages) if p.code.casefold() == wanted), None)


def _expected_pins(data: ExtractionData, pkg: PackageData) -> int | None:
    """Pin count of the target package: as drawn/listed, else the leads of its pin tables (without exposed pad)."""
    if pkg.pin_count:
        return pkg.pin_count
    counts = {len([p for p in t.pins if not p.exposed_pad]) for d in data.devices for t in d.pin_tables
              if t.package == pkg.code}
    return counts.pop() if len(counts) == 1 else None


def _usable_dims(pkg: PackageData) -> int:
    return sum(1 for d in pkg.dimensions if d.unit == "mm" and d.value() is not None)


def _code_matches(target: PackageData, source: PackageData) -> bool:
    """The source code extends the target code (TI: ``RGY`` → ``RGY0019B``) or names the same package."""
    t, s = _fold(target.code), _fold(source.code)
    return bool(t and s) and (s == t or (len(t) >= 2 and s.startswith(t)))


def _candidate(target: PackageData, pins: int | None, rec: Any, data: ExtractionData,
               pkg: PackageData, manufacturer: str) -> PackageSource:
    matches: list[str] = []
    problems: list[str] = []
    score = 0
    if pins and pkg.pin_count:
        if pkg.pin_count == pins:
            score += 40
            matches.append(f"gleiche Anschlusszahl ({pins})")
        else:
            score -= 40
            problems.append(f"{pkg.pin_count} statt {pins} Anschlüsse")
    if _code_matches(target, pkg):
        score += 25
        matches.append(f"Gehäusecode passt ({target.code} → {pkg.code})")
    if target.name and _fold(target.name) == _fold(pkg.name):
        score += 20
        matches.append("gleicher Gehäusename")
    if target.family and pkg.family:
        if target.family == pkg.family:
            score += 15
            matches.append("gleiche Gehäusefamilie")
        else:
            score -= 15
            problems.append("andere Gehäusefamilie")
    if target.exposed_pad != pkg.exposed_pad:
        score -= 10
        problems.append("mit Exposed Pad" if pkg.exposed_pad else "ohne Exposed Pad")
    if manufacturer and data.manufacturer and _fold(manufacturer) == _fold(data.manufacturer):
        score += 5
    if not data.devices:
        score += 10
        matches.append("Gehäusezeichnung")
    dims = _usable_dims(pkg)
    score += min(dims, 10) + (5 if pkg.land_pattern.complete() else 0)
    return PackageSource(
        datasheet_id=rec.id, file=rec.original_name, title=data.title or rec.title or "",
        manufacturer=data.manufacturer or rec.manufacturer or "", package=pkg.code, label=pkg.label, family=pkg.family,
        pin_count=pkg.pin_count, exposed_pad=pkg.exposed_pad, exposed_pad_number=pkg.exposed_pad_number,
        dimensions=dims, land_pattern=pkg.land_pattern.complete(), layout=pkg.layout is not None,
        package_only=not data.devices, pages=list(pkg.pages), score=score, matches=matches, problems=problems)


def _target(datasheet_id: str, package: str) -> tuple[Any, ExtractionData, int]:
    rec = store.get_record(datasheet_id)
    data = store.load_meta(rec).extraction
    if data is None:
        raise NoExtraction(datasheet_id)
    index = _index(data, package)
    if index is None:
        raise DatasheetError(f"Das Gehäuse „{package}“ ist in diesem Datenblatt nicht beschrieben.")
    return rec, data, index


def package_sources(datasheet_id: str, package: str) -> list[PackageSource]:
    """Packages with drawing data (dimensions or a land pattern) of the other analysed datasheets of the open library,
    best match for ``package`` first. Packages that were themselves taken over are not listed (their drawing is in
    their own source)."""
    _rec, data, index = _target(datasheet_id, package)
    target = data.packages[index]
    pins = _expected_pins(data, target)
    out: list[PackageSource] = []
    for other in registry.list_datasheets():
        if other.id == datasheet_id:
            continue
        other_data = store.load_meta(other).extraction
        if other_data is None:
            continue
        for pkg in other_data.packages:
            if pkg.origin is None and pkg.has_geometry():
                out.append(_candidate(target, pins, other, other_data, pkg, data.manufacturer))
    out.sort(key=lambda c: (-c.score, c.file.casefold(), c.package.casefold()))
    return out


def package_targets(datasheet_id: str, package: str) -> list[PackageTarget]:
    """Packages of the other analysed datasheets with a device that the drawing of ``package`` of this datasheet could
    complete – best match first (same scoring as :func:`package_sources`; packages whose dimensions are missing get a
    bonus, packages that already took over these drawing data are left out)."""
    src_rec, src_data, index = _target(datasheet_id, package)
    source = src_data.packages[index]
    if not source.has_geometry():
        raise DatasheetError(f"{source.label} hat keine Maße und keine Herstellerempfehlung – es gibt nichts zu übernehmen.")
    if source.origin is not None:
        raise DatasheetError(f"Die Maße von {source.label} stammen selbst aus „{source.origin.file}“ – bitte von dort aus "
                             "übernehmen.")
    out: list[PackageTarget] = []
    for other in registry.list_datasheets():
        if other.id == datasheet_id:
            continue
        data = store.load_meta(other).extraction
        if data is None or not data.devices:
            continue
        for pkg in data.packages:
            if pkg.origin is not None and pkg.origin.datasheet_id == datasheet_id and pkg.origin.package == source.code:
                continue  # took over exactly this drawing already
            fit = _candidate(pkg, _expected_pins(data, pkg), src_rec, src_data, source, data.manufacturer)
            missing = any(i.code == "dims_missing" and i.package == pkg.code for i in data.issues)
            score, matches = fit.score + (10 if missing else 0), [m for m in fit.matches if m != "Gehäusezeichnung"]
            if missing:
                matches.append("Maße fehlen dort")
            out.append(PackageTarget(
                datasheet_id=other.id, file=other.original_name, title=data.title or other.title or "",
                devices=[d.base_part for d in data.devices], package=pkg.code, label=pkg.label, pin_count=pkg.pin_count,
                dimensions=_usable_dims(pkg), dims_missing=missing,
                merged_from=pkg.origin.file if pkg.origin is not None else "", score=score, matches=matches,
                problems=fit.problems))
    out.sort(key=lambda t: (-t.score, t.file.casefold(), t.package.casefold()))
    return out


def _merged(target: PackageData, source: PackageData, origin: PackageOrigin) -> PackageData:
    layout = source.layout or target.layout
    return PackageData(
        code=target.code,
        name=target.name or source.name,
        family=source.family or target.family,
        family_raw=source.family_raw or target.family_raw,
        pin_count=source.pin_count if source.pin_count is not None else target.pin_count,
        mounting=source.mounting or target.mounting,
        outline_reference=source.outline_reference or target.outline_reference,
        exposed_pad=source.exposed_pad,  # the drawing decides
        exposed_pad_number=source.exposed_pad_number or target.exposed_pad_number,
        pages=list(source.pages),
        dimensions=[d.model_copy() for d in source.dimensions],
        land_pattern=source.land_pattern.model_copy(deep=True),
        layout=layout.model_copy(deep=True) if layout is not None else None,
        origin=origin,
    )


def _notes(data: ExtractionData, target: PackageData, source: PackageData, file: str) -> list[str]:
    """German hints about the takeover: what came over and what does not fit the device's pin table."""
    parts = [plural(_usable_dims(source), "Maß", "Maße")]
    if source.land_pattern.complete():
        parts.append("Herstellerempfehlung")
    if source.exposed_pad:
        parts.append(f"Exposed Pad {source.exposed_pad_number}".strip())
    notes = [f"Aus „{file}“ übernommen ({source.label}): {', '.join(parts)}."]
    pins = _expected_pins(data, target)
    if pins and source.pin_count and source.pin_count != pins:
        notes.append(f"Die Gehäusezeichnung hat {source.pin_count} Anschlüsse, das Bauteil {pins} – bitte prüfen, ob "
                     "es das richtige Gehäuse ist.")
    has_ep_pin = any(p.exposed_pad for d in data.devices for t in d.pin_tables if t.package == target.code
                     for p in t.pins)
    if has_ep_pin and not source.exposed_pad:
        notes.append("Die Pintabelle hat ein Exposed Pad, die Gehäusezeichnung keines.")
    return notes


def merge_package(datasheet_id: str, package: str, source_id: str, source_package: str, *,
                  ws: Workspace | None = None) -> MergeResult:
    """Take over the drawing data of ``source_package`` of datasheet ``source_id`` into ``package`` of
    ``datasheet_id`` (see module docstring); a package taken over before keeps its original for "aufheben"."""
    from .extract import store_edited_extraction

    ws = ws or current()
    if store.check_id(source_id) == datasheet_id:
        raise DatasheetError("Bitte ein anderes Datenblatt wählen – das Gehäuse stammt schon aus diesem.")
    src_rec = store.get_record(source_id)
    src = store.load_meta(src_rec).extraction
    if src is None:
        raise NoExtraction(source_id)
    source = src.package(source_package)
    if source is None:
        raise DatasheetError(f"Das Gehäuse „{source_package}“ ist in „{src_rec.original_name}“ nicht beschrieben.")
    if not source.has_geometry():
        raise DatasheetError(f"„{src_rec.original_name}“ enthält für {source.label} keine Maße und keine "
                             "Herstellerempfehlung – es gibt nichts zu übernehmen.")
    if source.origin is not None:
        raise DatasheetError(f"Die Maße von {source.label} stammen selbst aus „{source.origin.file}“ – bitte direkt "
                             "aus diesem Datenblatt übernehmen.")
    with store.meta_lock(datasheet_id):  # read-modify-write of the target extraction
        _rec, data, index = _target(datasheet_id, package)
        target = data.packages[index]
        replaced = target.origin.replaced if target.origin is not None else PackageBase.model_validate(
            target.model_dump(exclude={"origin"}))
        origin = PackageOrigin(datasheet_id=src_rec.id, package=source.code, file=src_rec.original_name,
                               title=src.title or src_rec.title or "", label=source.label, merged=store.now_iso(),
                               replaced=replaced)
        out = data.model_copy(deep=True)
        out.packages[index] = _merged(target, source, origin)
        notes = _notes(data, target, source, src_rec.original_name)
        clean = store_edited_extraction(datasheet_id, out, ws=ws)
    return MergeResult(extraction=clean, notes=notes)


def unmerge_package(datasheet_id: str, package: str, *, ws: Workspace | None = None) -> ExtractionData:
    """Undo :func:`merge_package`: the package as it was before the first takeover (its code kept)."""
    from .extract import store_edited_extraction

    ws = ws or current()
    with store.meta_lock(datasheet_id):
        _rec, data, index = _target(datasheet_id, package)
        pkg = data.packages[index]
        if pkg.origin is None:
            raise DatasheetError(f"Das Gehäuse {pkg.label} wurde nicht aus einem anderen Datenblatt übernommen.")
        before = pkg.origin.replaced or pkg
        restored = PackageData.model_validate({**before.model_dump(exclude={"origin"}), "code": pkg.code})
        out = data.model_copy(deep=True)
        out.packages[index] = restored
        return store_edited_extraction(datasheet_id, out, ws=ws)
