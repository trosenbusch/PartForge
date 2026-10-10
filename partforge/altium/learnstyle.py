"""Hausstil aus Beispielbibliothek: derive the house style from reference libraries the user made in Altium.

The user keeps a reference component the way every component should look (e.g.
``Components - 09.10.26 - 18.38.zip``: an IntLib with one symbol and one footprint). :func:`learn` reads such
libraries – ``.SchLib``, ``.PcbLib``, ``.IntLib`` (members extracted), a ``.zip`` archive of them or a folder –
with the record codecs and proposes the settings of the workspace house style:

* symbols: house font (designator, Comment, parameters), pin font (Altium "custom font" of the pins → house
  font), pin length of box symbols and of other symbols, box border/fill colour, pin colour;
* footprints: the layer of every role (``LayerMap``: from the header's layer kinds/names and the content –
  ``.Designator``/``.Comment`` texts, centre cross, 3D bodies), line widths (silkscreen, assembly,
  courtyard), the ``.Designator``/``.Comment`` font (stroke or TrueType, name, height), pin-1 dot, courtyard
  centre cross.

Every proposal names its evidence; nothing is saved here – the settings page applies the chosen findings.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..domain.text import plural
from ..workspace import FootprintStyle, LayerMap, SymbolStyle, WorkspaceSettings
from . import compound
from . import conform as C
from . import pcbrecords as R
from . import schrecords as S
from . import stackup
from .libimport import ImportError_, extract_intlib, extract_zip

log = logging.getLogger(__name__)

__all__ = ["StyleFinding", "StyleProposal", "learn", "library_paths"]


class StyleFinding(BaseModel):
    area: Literal["symbol", "footprint", "layers"]
    key: str
    label: str
    current: str
    proposed: str
    value: Any
    evidence: str
    differs: bool


class StyleProposal(BaseModel):
    sources: list[str] = Field(default_factory=list)
    symbols: int = 0
    footprints: int = 0
    findings: list[StyleFinding] = Field(default_factory=list)
    symbol: SymbolStyle
    footprint: FootprintStyle
    layers: LayerMap
    notes: list[str] = Field(default_factory=list)
    message: str = ""


def library_paths(paths: Sequence[str]) -> tuple[list[Path], list[str]]:
    """Library files of the given paths (IntLib members and ZIP archives extracted, folders searched
    recursively)."""
    out: list[Path] = []
    notes: list[str] = []
    for raw in paths:
        path = Path(str(raw).strip().strip('"'))
        if not path.exists():
            notes.append(f"{path} wurde nicht gefunden.")
            continue
        candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in candidates:
            suffix = file.suffix.casefold()
            if suffix in (".schlib", ".pcblib"):
                out.append(file)
            elif suffix in (".intlib", ".zip"):
                try:
                    members = extract_intlib(file) if suffix == ".intlib" else extract_zip(file)
                except ImportError_ as exc:
                    notes.append(str(exc))
                    continue
                out.extend(member for _rel, member, _kind in members)
    unique: dict[str, Path] = {}
    for file in out:
        unique.setdefault(str(file).casefold(), file)
    return list(unique.values()), notes


def _hex(colorref: int) -> str:
    return f"#{colorref & 0xFF:02X}{(colorref >> 8) & 0xFF:02X}{(colorref >> 16) & 0xFF:02X}"


def _most(counter: Counter[Any]) -> Any:
    return counter.most_common(1)[0][0] if counter else None


def _mm(value: float) -> str:
    return f"{value:g}".replace(".", ",") + " mm"


# --------------------------------------------------------------------------- symbols


class _SymbolEvidence:
    def __init__(self) -> None:
        self.text_fonts: Counter[S.SchFont] = Counter()
        self.pin_fonts: Counter[S.SchFont | None] = Counter()
        self.box_lengths: Counter[int] = Counter()
        self.other_lengths: Counter[int] = Counter()
        self.line_colors: Counter[int] = Counter()
        self.fill_colors: Counter[int] = Counter()
        self.pin_colors: Counter[int] = Counter()
        self.symbols = 0
        self.box_symbols = 0

    def add_library(self, path: Path) -> None:
        tree = compound.read_tree_file(path)
        header = tree.get("FileHeader")
        if header is None:
            return
        fonts = S.parse_header(header).fonts()

        def font(fid: str | int | None) -> S.SchFont | None:
            try:
                index = int(fid) if fid is not None else 1
            except ValueError:
                return None
            return fonts[index - 1] if 1 <= index <= len(fonts) else None

        for key, data in tree.items():
            if data is None or not key.endswith("/Data") or key.count("/") != 1:
                continue
            storage = key.split("/", 1)[0]
            try:
                records = S.parse_records(data)
                pin_text = S.parse_pin_text_data(tree.get(f"{storage}/PinTextData"))
            except S.SchRecordError:
                continue
            if not any(not r.binary and r.get("RECORD") == "1" for r in records):
                continue
            self.symbols += 1
            for record in records:
                if record.binary:
                    continue
                kind = record.get("RECORD")
                if kind == "34" or (kind == "41" and record.get("Name") == "Comment"):
                    found = font(record.get("FontID"))
                    if found is not None:
                        self.text_fonts[found] += 1
            pins = [S.PinView(r) for r in records if r.is_pin]
            for index, pin in enumerate(pins):
                custom = pin_text.get(index)
                fid = custom.name.font_id if custom is not None else None
                self.pin_fonts[font(fid) if fid is not None else None] += 1
                self.pin_colors[pin.color] += 1
            box = C.is_box_symbol(records)
            if box:
                self.box_symbols += 1
                for record in records:
                    if not record.binary and record.get("RECORD") == "14":
                        try:
                            self.line_colors[int(record.get("Color") or 0)] += 1
                            self.fill_colors[int(record.get("AreaColor") or 0)] += 1
                        except ValueError:
                            continue
            for pin in pins:
                (self.box_lengths if box else self.other_lengths)[pin.length * 10] += 1


def _symbol_findings(ev: _SymbolEvidence, current: SymbolStyle) -> tuple[list[StyleFinding], SymbolStyle]:
    findings: list[StyleFinding] = []
    proposed = current.model_copy()

    def add(key: str, label: str, value: Any, shown: str, now: str, evidence: str) -> None:
        nonlocal proposed
        differs = getattr(current, key) != value
        findings.append(StyleFinding(area="symbol", key=key, label=label, current=now, proposed=shown, value=value,
                                     evidence=evidence, differs=differs))
        proposed = proposed.model_copy(update={key: value})

    house = _most(ev.text_fonts)
    if house is not None:
        add("font", "Schriftart (Bezeichner, Kommentar, Parameter)", house.name, house.name, current.font,
            plural(sum(ev.text_fonts.values()), "Bezeichner/Kommentar", "Bezeichner/Kommentare"))
        add("font_size", "Schriftgröße", house.size, f"{house.size} pt", f"{current.font_size} pt",
            plural(sum(ev.text_fonts.values()), "Bezeichner/Kommentar", "Bezeichner/Kommentare"))
    if ev.pin_fonts:
        custom = sum(n for f, n in ev.pin_fonts.items() if f is not None)
        mode = "house" if custom * 2 >= sum(ev.pin_fonts.values()) else "system"
        add("pin_font", "Pinnamen und -nummern", mode, "Hausschrift" if mode == "house" else "Systemschrift",
            "Hausschrift" if current.pin_font == "house" else "Systemschrift",
            f"{custom} von {sum(ev.pin_fonts.values())} Pins mit eigener Schrift")
    length = _most(ev.box_lengths)
    if length:
        add("ic_pin_length", "Pinlänge ICs", int(length), f"{length} mil", f"{current.ic_pin_length} mil",
            f"{plural(sum(ev.box_lengths.values()), 'Pin', 'Pins')} in {plural(ev.box_symbols, 'IC-Symbol', 'IC-Symbolen')}")
    other = _most(ev.other_lengths)
    if other:
        add("discrete_pin_length", "Pinlänge diskret", int(other), f"{other} mil", f"{current.discrete_pin_length} mil",
            plural(sum(ev.other_lengths.values()), "Pin", "Pins") + " anderer Symbole")
    line = _most(ev.line_colors)
    if line is not None:
        add("ic_line_color", "IC-Umriss", _hex(line), _hex(line), current.ic_line_color, "Rechteck der IC-Symbole")
    fill = _most(ev.fill_colors)
    if fill is not None:
        add("ic_fill_color", "IC-Füllung", _hex(fill), _hex(fill), current.ic_fill_color, "Rechteck der IC-Symbole")
    pin_color = _most(ev.pin_colors)
    if pin_color is not None:
        add("pin_color", "Pins", _hex(pin_color), _hex(pin_color), current.pin_color,
            plural(sum(ev.pin_colors.values()), "Pin", "Pins"))
    return findings, proposed


# --------------------------------------------------------------------------- footprints


class _FootprintEvidence:
    def __init__(self) -> None:
        self.role_layers: dict[str, Counter[str]] = {}
        self.widths: dict[str, list[float]] = {}
        self.text_fonts: Counter[tuple[str, str | None]] = Counter()
        self.text_heights: list[float] = []
        self.dots: list[float] = []
        self.courtyard_cross = 0
        self.footprints = 0

    def add_library(self, path: Path) -> None:
        footprints = R.read_footprints(path)
        if not footprints:
            return
        try:
            header = stackup.read_pcblib_layers(path)
        except Exception:  # noqa: BLE001 - older headers: content only
            header = {}
        records = [rec for _storage, rec in footprints.values()]
        layer_roles = C.infer_layer_roles(records, header)
        for rec in records:
            self.footprints += 1
            roles = C.primitive_roles(rec, layer_roles)
            center, court = C.center_crosses(rec.primitives, layer_roles)
            crosses = {*center, *court}
            for index, (prim, role) in enumerate(zip(rec.primitives, roles, strict=True)):
                if role is None or prim.layer is None:
                    continue
                if role in C.MAPPED_ROLES:
                    self.role_layers.setdefault(role, Counter())[prim.layer] += 1
                if index in crosses:
                    continue
                if prim.kind in ("track", "arc") and role in ("silkscreen", "assembly", "courtyard"):
                    if prim.kind == "arc" and prim.width >= 1.5 * prim.arc[2]:
                        if role == "silkscreen":
                            self.dots.append(prim.arc[2])
                        continue
                    self.widths.setdefault(role, []).append(round(prim.width, 4))
                if prim.kind == "text" and role in ("designator", "comment"):
                    kind = prim.font_kind
                    self.text_fonts[(kind, prim.font_name if kind == "truetype" else None)] += 1
                    self.text_heights.append(round(prim.height, 3))
            if court:
                self.courtyard_cross += 1


def _footprint_findings(ev: _FootprintEvidence, settings: WorkspaceSettings) -> tuple[
        list[StyleFinding], FootprintStyle, LayerMap]:
    findings: list[StyleFinding] = []
    style = settings.footprint.model_copy()
    layers = settings.layers.model_copy()
    for role in C.MAPPED_ROLES:
        counter = ev.role_layers.get(role)
        layer = _most(counter) if counter else None
        if not layer:
            continue
        now = getattr(settings.layers, role)
        findings.append(StyleFinding(area="layers", key=role, label=C.ROLE_LABELS[role], current=now, proposed=layer,
                                     value=layer, evidence=plural(sum(counter.values()), "Element", "Elemente"),
                                     differs=now != layer))
        layers = layers.model_copy(update={role: layer})

    def add(key: str, label: str, value: Any, shown: str, now: str, evidence: str) -> None:
        nonlocal style
        differs = getattr(settings.footprint, key) != value
        findings.append(StyleFinding(area="footprint", key=key, label=label, current=now, proposed=shown, value=value,
                                     evidence=evidence, differs=differs))
        style = style.model_copy(update={key: value})

    def common(values: list[float]) -> float | None:
        return Counter(values).most_common(1)[0][0] if values else None

    silk = common(ev.widths.get("silkscreen", []))
    if silk:
        add("silk_width", "Bestückungsdruck", silk, _mm(silk), _mm(settings.footprint.silk_width),
            plural(len(ev.widths["silkscreen"]), "Linie", "Linien"))
    assembly = common(ev.widths.get("assembly", []))
    if assembly:
        add("assembly_width", "Bestückungszeichnung", assembly, _mm(assembly), _mm(settings.footprint.assembly_width),
            plural(len(ev.widths["assembly"]), "Linie", "Linien"))
    courtyard = common(ev.widths.get("courtyard", []))
    if courtyard:
        add("courtyard_width", "Courtyard", courtyard, _mm(courtyard), _mm(settings.footprint.courtyard_width),
            plural(len(ev.widths["courtyard"]), "Linie", "Linien"))
    if ev.text_fonts:
        (kind, name), count = ev.text_fonts.most_common(1)[0]
        font = "truetype" if kind == "truetype" else "stroke"
        add("text_font", "Schrift .Designator/.Comment", font, "TrueType" if font == "truetype" else "Strichschrift",
            "TrueType" if settings.footprint.text_font == "truetype" else "Strichschrift", plural(count, "Text", "Texte"))
        if font == "truetype" and name:
            add("text_font_name", "TrueType-Schrift", name, name, settings.footprint.text_font_name,
                plural(count, "Text", "Texte"))
    if ev.text_heights:
        height = statistics.median(ev.text_heights)
        height = round(height, 2)
        add("text_height", "Texthöhe", height, _mm(height), _mm(settings.footprint.text_height),
            plural(len(ev.text_heights), "Text", "Texte") + " (kleine Bauteile erhalten kleinere Texte)")
    if ev.dots:
        radius = round(Counter(ev.dots).most_common(1)[0][0], 3)
        add("pin1_dot_radius", "Pin-1-Punkt (Radius)", radius, _mm(radius), _mm(settings.footprint.pin1_dot_radius),
            plural(len(ev.dots), "Punkt", "Punkte"))
    if ev.footprints:
        cross = ev.courtyard_cross * 2 >= ev.footprints
        add("center_cross", "Kreuz im Courtyard", cross, "ja" if cross else "nein",
            "ja" if settings.footprint.center_cross else "nein",
            f"{ev.courtyard_cross} von {plural(ev.footprints, 'Footprint', 'Footprints')}")
    return findings, style, layers


def learn(paths: Sequence[str], settings: WorkspaceSettings) -> StyleProposal:
    """Proposal of house-style settings from reference libraries (see the module docstring)."""
    files, notes = library_paths(paths)
    if not files:
        raise ImportError_("Keine Symbol- oder Footprint-Bibliothek gefunden (.SchLib, .PcbLib, .IntLib, .zip).",
                           status=400)
    symbols = _SymbolEvidence()
    footprints = _FootprintEvidence()
    for file in files:
        try:
            if file.suffix.casefold() == ".schlib":
                symbols.add_library(file)
            else:
                footprints.add_library(file)
        except Exception as exc:  # noqa: BLE001 - one unreadable reference must not stop the others
            log.warning("Beispielbibliothek %s nicht lesbar: %s", file, exc)
            notes.append(f"{file.name} nicht lesbar: {exc}")
    sym_findings, symbol = _symbol_findings(symbols, settings.symbol)
    fp_findings, footprint, layers = _footprint_findings(footprints, settings)
    proposal = StyleProposal(
        sources=[str(f) for f in files], symbols=symbols.symbols, footprints=footprints.footprints,
        findings=[*sym_findings, *fp_findings], symbol=symbol, footprint=footprint, layers=layers, notes=notes,
    )
    differing = sum(1 for f in proposal.findings if f.differs)
    proposal.message = (
        f"{plural(symbols.symbols, 'Symbol', 'Symbole')} und {plural(footprints.footprints, 'Footprint', 'Footprints')}"
        f" ausgewertet – {plural(differing, 'Einstellung weicht', 'Einstellungen weichen')} vom Hausstil ab."
        if differing else
        f"{plural(symbols.symbols, 'Symbol', 'Symbole')} und {plural(footprints.footprints, 'Footprint', 'Footprints')}"
        " ausgewertet – der Hausstil entspricht dem Beispiel."
    )
    return proposal

