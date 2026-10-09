"""Merging a verification answer into the first answer of a pass – a verification never loses data.

The verification turn (200 dpi renders) asks Claude for the complete corrected answer, but an answer may also
leave things out: a device, variants, a pin table, dimensions. Taking it wholesale would silently drop that data,
and an answer with fewer items even has fewer plausibility errors. The merge therefore works per item:

* **in scope** (the packages/devices with issues, or everything when the issues name none) – the verified item
  replaces the original one when it is not worse (pin tables: deviation from the package's pin count plus duplicate
  numbers; on a tie only if no pin number is lost); a verified package that lacks dimensions of the original is
  merged dimension by dimension; items the verification does not mention stay as they were,
* **out of scope** – the verified item is taken only when it keeps everything of the original (all pin numbers,
  all dimension letters, an equally complete land pattern), otherwise the original stays,
* devices, variants and parameters always come from the first answer (they are not what the check is about);
  the verification only fills what the first answer left empty,
* warnings of both answers are kept,
* ``keep`` forces the original for items that the caller found worse after the merge (``extract`` compares the
  plausibility checks per item and merges again).

The caller still compares the plausibility checks before and after (``extract._score``) and keeps the first answer
when the merged one is worse.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .models import Issue
from .normalize import is_exposed_pad_pin
from .schema import AiDevice, AiDimension, AiGeometry, AiIdentity, AiLandPattern, AiPackage, AiPackageRef, AiPinTable

__all__ = ["Scope", "merge_geometry", "merge_identity", "scope_from_issues"]

_NA = -1.0


def _fold(text: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


@dataclass
class Scope:
    """What the verification was asked to fix (folded package codes / base part numbers)."""

    packages: set[str] = field(default_factory=set)  # package issues (drawings): every pin table of the package
    devices: set[str] = field(default_factory=set)  # device issues without a package (no pin table …)
    pairs: set[tuple[str, str]] = field(default_factory=set)  # pin-table issues: (device, package)
    everything: bool = False

    def table(self, device: str, package: str) -> bool:
        """Is the pin table of ``device`` for ``package`` in scope?"""
        d, p = _fold(device), _fold(package)
        return self.everything or p in self.packages or d in self.devices or (d, p) in self.pairs

    def package(self, *codes: str) -> bool:
        """Is the package (code or name) in scope?"""
        keys = {_fold(c) for c in codes if c}
        return self.everything or bool(keys & self.packages) or any(p in keys for _, p in self.pairs)


def scope_from_issues(issues: Iterable[Issue]) -> Scope:
    """Scope of a verification turn: the packages and devices its issues name (everything if none is named)."""
    scope = Scope()
    for issue in issues:
        if issue.package and issue.device:
            scope.pairs.add((_fold(issue.device), _fold(issue.package)))
        elif issue.package:
            scope.packages.add(_fold(issue.package))
        elif issue.device:
            scope.devices.add(_fold(issue.device))
        else:
            scope.everything = True
    if not (scope.packages or scope.devices or scope.pairs):
        scope.everything = True
    return scope


def _unique_warnings(*lists: Sequence[str]) -> list[str]:
    out: list[str] = []
    for items in lists:
        for text in items:
            if text and text not in out:
                out.append(text)
    return out


# --------------------------------------------------------------------------- identity


def _match_device(device: AiDevice, verified: Sequence[AiDevice], *, single: bool) -> AiDevice | None:
    wanted = _fold(device.base_part_number)
    match = next((v for v in verified if _fold(v.base_part_number) == wanted), None)
    if match is None and single and len(verified) == 1:
        match = verified[0]  # one device on both sides (the base part number may have been corrected)
    return match


def _table_for(tables: Sequence[AiPinTable], code: str) -> AiPinTable | None:
    wanted = _fold(code)
    return next((t for t in tables if _fold(t.package_code) == wanted), None)


def _pin_numbers(table: AiPinTable) -> set[str]:
    return {_fold(p.number) for p in table.pins}


def _table_score(table: AiPinTable, pin_count: int | None) -> int:
    """How wrong a pin table is: deviation of its leads from the package's pin count plus duplicate numbers."""
    numbers = [_fold(p.number) for p in table.pins]
    duplicates = len(numbers) - len(set(numbers))
    if not pin_count:
        return duplicates
    leads = sum(1 for p in table.pins if not is_exposed_pad_pin(p.number, p.name, p.function, pin_count=pin_count))
    return abs(leads - pin_count) + duplicates


def _better_table(original: AiPinTable, verified: AiPinTable, pin_counts: Mapping[str, int]) -> bool:
    count = pin_counts.get(_fold(original.package_code)) or None
    old, new = _table_score(original, count), _table_score(verified, count)
    return new < old or (new == old and _pin_numbers(verified) >= _pin_numbers(original))


def _merge_device(original: AiDevice, verified: AiDevice | None, scope: Scope, keep: Scope,
                  pin_counts: Mapping[str, int], notes: list[str]) -> AiDevice:
    merged = original.model_copy(deep=True)
    if verified is None:
        return merged
    base = original.base_part_number
    tables: list[AiPinTable] = []
    for table in original.pin_tables:
        new = _table_for(verified.pin_tables, table.package_code)
        if new is None or keep.table(base, table.package_code):
            tables.append(table.model_copy(deep=True))
            continue
        if scope.table(base, table.package_code):
            if _better_table(table, new, pin_counts):
                if new.model_dump() != table.model_dump():
                    notes.append(f"Pintabelle {base}/{table.package_code} nach der Kontrolle korrigiert.")
                tables.append(new.model_copy(deep=True))
            else:
                tables.append(table.model_copy(deep=True))
        elif _pin_numbers(new) >= _pin_numbers(table):
            tables.append(new.model_copy(deep=True))  # same or more pins: corrections of names/types are taken
        else:
            tables.append(table.model_copy(deep=True))
    known = {_fold(t.package_code) for t in tables}
    for table in verified.pin_tables:  # tables the first answer did not have
        if _fold(table.package_code) not in known and not keep.table(base, table.package_code):
            tables.append(table.model_copy(deep=True))
            known.add(_fold(table.package_code))
    merged.pin_tables = tables
    if not merged.variants and verified.variants:
        merged.variants = [v.model_copy(deep=True) for v in verified.variants]
    if not merged.parameters and verified.parameters:
        merged.parameters = [p.model_copy(deep=True) for p in verified.parameters]
    if not merged.description.strip():
        merged.description = verified.description
    if not merged.category.strip():
        merged.category = verified.category
    return merged


def _referenced(identity: AiIdentity) -> set[str]:
    codes = set()
    for device in identity.devices:
        codes.update(_fold(t.package_code) for t in device.pin_tables)
        codes.update(_fold(v.package_code) for v in device.variants)
    return codes


def merge_identity(original: AiIdentity, verified: AiIdentity, scope: Scope,
                   keep: Scope | None = None) -> tuple[AiIdentity, list[str]]:
    """Merged identity answer and German notes on what the verification changed (see module docstring)."""
    keep = keep or Scope()
    notes: list[str] = []
    if keep.everything:
        return original.model_copy(deep=True), []
    if not original.devices:
        merged = verified.model_copy(deep=True)
        merged.warnings = _unique_warnings(original.warnings, verified.warnings)
        return merged, ["Bauteile erst nach der Kontrolle erkannt."] if verified.devices else []
    refs: list[AiPackageRef] = []
    for ref in original.packages:
        new = next((r for r in verified.packages if _fold(r.package_code) == _fold(ref.package_code)), None)
        if new is not None and scope.package(ref.package_code, ref.package_name) and not keep.package(
                ref.package_code, ref.package_name):
            refs.append(new.model_copy(deep=True))
        else:
            refs.append(ref.model_copy(deep=True))
    pin_counts = {_fold(r.package_code): r.pin_count for r in refs if r.pin_count > 0}
    single = len(original.devices) == 1
    devices = [_merge_device(d, _match_device(d, verified.devices, single=single), scope, keep, pin_counts, notes)
               for d in original.devices]
    merged = original.model_copy(deep=True)
    merged.devices = devices
    known = {_fold(r.package_code) for r in refs}
    needed = _referenced(merged)
    for ref in verified.packages:  # packages that only the merged pin tables reference
        key = _fold(ref.package_code)
        if key not in known and key in needed:
            refs.append(ref.model_copy(deep=True))
            known.add(key)
    merged.packages = refs
    for name in ("manufacturer", "document_id", "document_title", "document_date"):
        if not str(getattr(merged, name) or "").strip():
            setattr(merged, name, getattr(verified, name))
    merged.warnings = _unique_warnings(original.warnings, verified.warnings)
    return merged, notes


# --------------------------------------------------------------------------- geometry


def _has_value(dim: AiDimension) -> bool:
    return any(abs(v - _NA) > 1e-9 for v in (dim.min, dim.nom, dim.max))


def _symbols(package: AiPackage) -> set[str]:
    return {d.symbol.strip() for d in package.dimensions if d.symbol.strip() and _has_value(d)}


def _land_values(land: AiLandPattern) -> int:
    if not land.present:
        return 0
    values = (land.pad_width, land.pad_length, land.pitch, land.row_spacing, land.thermal_pad_width,
              land.thermal_pad_length)
    return 1 + sum(1 for v in values if abs(v - _NA) > 1e-9)


def _match_package(package: AiPackage, verified: Sequence[AiPackage]) -> AiPackage | None:
    code, name = _fold(package.package_code), _fold(package.package_name)
    match = next((p for p in verified if _fold(p.package_code) == code), None)
    if match is None and name:
        match = next((p for p in verified if _fold(p.package_name) == name), None)
    return match


def _merge_dimensions(original: AiPackage, verified: AiPackage) -> list[AiDimension]:
    """Original dimensions, each replaced by the verified one with the same letter, plus new verified letters."""
    by_symbol = {d.symbol.strip(): d for d in verified.dimensions if d.symbol.strip() and _has_value(d)}
    out: list[AiDimension] = []
    used: set[str] = set()
    for dim in original.dimensions:
        symbol = dim.symbol.strip()
        if symbol in by_symbol and symbol not in used:
            out.append(by_symbol[symbol].model_copy(deep=True))
            used.add(symbol)
        else:
            out.append(dim.model_copy(deep=True))
    for symbol, dim in by_symbol.items():
        if symbol not in used and symbol not in {d.symbol.strip() for d in original.dimensions}:
            out.append(dim.model_copy(deep=True))
    return out


def _merge_package(original: AiPackage, verified: AiPackage, in_scope: bool) -> AiPackage | None:
    """The package to keep (``None`` = keep the original unchanged)."""
    covers = _symbols(verified) >= _symbols(original)
    land_ok = _land_values(verified.land_pattern) >= _land_values(original.land_pattern)
    if covers and land_ok:
        return verified.model_copy(deep=True)
    if not in_scope:
        return None
    merged = verified.model_copy(deep=True)
    if not covers:
        merged.dimensions = _merge_dimensions(original, verified)
    if not land_ok:
        merged.land_pattern = original.land_pattern.model_copy(deep=True)
    if merged.pin_count <= 0 < original.pin_count:
        merged.pin_count = original.pin_count
    if not merged.source_pages:
        merged.source_pages = list(original.source_pages)
    return merged


def merge_geometry(original: AiGeometry, verified: AiGeometry, scope: Scope,
                   keep: Scope | None = None) -> tuple[AiGeometry, list[str]]:
    """Merged geometry answer and German notes on what the verification changed (see module docstring)."""
    keep = keep or Scope()
    if keep.everything:
        return original.model_copy(deep=True), []
    notes: list[str] = []
    packages: list[AiPackage] = []
    matched: set[int] = set()
    for package in original.packages:
        new = _match_package(package, verified.packages)
        if new is not None:
            matched.add(id(new))
        if new is None or keep.package(package.package_code, package.package_name):
            packages.append(package.model_copy(deep=True))
            continue
        in_scope = scope.package(package.package_code, package.package_name)
        merged = _merge_package(package, new, in_scope)
        if merged is None:
            packages.append(package.model_copy(deep=True))
            continue
        if in_scope and merged.model_dump() != package.model_dump():
            notes.append(f"Gehäuse {package.package_code or package.package_name}: Maße nach der Kontrolle korrigiert.")
        packages.append(merged)
    for package in verified.packages:  # packages only the verification describes
        if id(package) in matched or keep.package(package.package_code, package.package_name):
            continue
        if scope.package(package.package_code, package.package_name):
            packages.append(package.model_copy(deep=True))
            notes.append(f"Gehäuse {package.package_code or package.package_name} erst nach der Kontrolle beschrieben.")
    merged_geometry = AiGeometry(packages=packages, warnings=_unique_warnings(original.warnings, verified.warnings))
    return merged_geometry, notes
