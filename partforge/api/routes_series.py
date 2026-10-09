"""API routes: series assistant (MPN templates, preview, commit as job, decode, user templates).

    GET    /series/templates?category=          template list (built-in + user templates) with example part
    GET    /series/templates/custom             user templates of the open library
    POST   /series/templates/custom             create a user template
    PUT    /series/templates/custom/{id}        replace a user template
    DELETE /series/templates/custom/{id}        delete a user template
    POST   /series/templates/test               draft template + samples -> part numbers (round trip) and the
                                                category's required-field check per sample
    GET    /series/templates/{id}?full=         one template (availability matrix only with full=true)
    POST   /series/preview                      rows with status new/exists/conflict/invalid
    POST   /series/commit                       background job -> {"job": SeriesJobSnapshot}
    POST   /series/decode                       part number -> template + values

Template summaries carry everything a template card shows: a precomputed example part number with
its segments (:class:`TemplateExampleOut`, checked against the category of the open library – or the
built-in category without a library), mode, value range, E-series, jumper and sources.

The commit job holds the library it was requested for (:func:`partforge.jobs.library_hold`): a
library switch cancels it and waits until it stopped; if that library is no longer open when the
job starts, it stops without writing. Its result is :class:`partforge.domain.series.SeriesCommitResult`
(``job.result``; typed in OpenAPI through :class:`SeriesJobSnapshot`), its progress
:class:`~partforge.domain.series.SeriesCommitDetail` (``job.detail``).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..domain import series
from ..domain.mpn import (
    Decoded,
    MpnError,
    MpnTemplate,
    Source,
    TemplateError,
    TemplateNotFound,
    builtin_id_conflict,
    compile_template,
    decode_any,
    decode_mpn,
    delete_custom_template,
    encode_mpn,
    find_option,
    get_builtin,
    get_template,
    list_custom_templates,
    list_templates,
    resolve,
    resolve_size,
    save_custom_template,
)
from ..domain.mpn.engine import base_attrs
from ..domain.mpn.examples import MpnSegment, TemplateExample, TemplateMode, template_example, template_facts
from ..domain.text import plural
from ..domain.units import parse_quantity
from ..jobs import JobContext, JobStatus, jobs, library_hold
from ..workspace import Workspace
from .deps import require_workspace
from .routes_categories import db_errors

log = logging.getLogger(__name__)

router = APIRouter(tags=["series"])


# --------------------------------------------------------------------------- models


class TemplateExampleOut(BaseModel):
    """Example part number of a template card (precomputed; no extra request needed)."""

    mpn: str = Field(description="Beispiel-Teilenummer (typischer Wert in einer gängigen Baugröße)")
    size: str | None = None
    value: float | None = Field(default=None, description="Wert in der Basiseinheit (Ω, F, H)")
    value_text: str | None = Field(default=None, description="Wert als Feldtext, z. B. 10kΩ")
    valid: bool = Field(description="False: die Serie würde dieses Bauteil nicht anlegen (message sagt warum)")
    message: str | None = None
    description: str | None = Field(default=None, description="Beschreibung, wie die Kategorie sie erzeugt")
    missing_fields: list[series.RequiredField] = Field(
        default_factory=list, description="Pflichtfelder der Kategorie, die die Vorlage leer lässt")
    segments: list[MpnSegment] = Field(default_factory=list, description="Teilenummer zerlegt (Code + Bedeutung)")


class TemplateSummary(BaseModel):
    id: str
    manufacturer: str
    series: str
    category: str
    title: str
    description: str = ""
    kind: Literal["pattern", "catalog"]
    pattern: str | None = None
    value_unit: str
    sizes: list[str] = Field(default_factory=list)
    verified: bool
    availability_certain: bool
    builtin: bool
    datasheet_url: str | None = None
    part_count: int | None = None
    availability_count: int | None = None
    mode: TemplateMode = Field(default="rules",
                               description="rules = Wertebereiche, matrix = Lieferbarkeitsmatrix, catalog = feste "
                                           "Teilenummern, open = ohne Gültigkeitsdaten")
    value_range: list[float] | None = Field(default=None,
                                            description="[kleinster, größter] Wert der Serie (Basiseinheit)")
    e_series: list[str] = Field(default_factory=list, description="E-Reihen der Regeln (E24, E96 …)")
    jumper: bool = Field(default=False, description="Die Serie hat 0-Ω-Brücken")
    sources: list[Source] = Field(default_factory=list, description="Quellen (Datenblätter) der Vorlage")
    example: TemplateExampleOut | None = Field(default=None, description="Beispiel-Teilenummer mit Zerlegung")


class TemplateDetail(MpnTemplate):
    """A template as returned by the API (availability matrix only with ``full=true``)."""

    availability_count: int = Field(default=0, description="Zellen der Lieferbarkeitsmatrix")


class SeriesCommitIn(series.SeriesRequest):
    mode: Literal["skip", "update"] = Field(default="skip", description="skip = vorhandene Teile auslassen, "
                                                                         "update = vorhandene Teile aktualisieren")


class JobLogLine(BaseModel):
    ts: float
    level: str = Field(description="info | warn | error | success")
    text: str


class SeriesJobSnapshot(BaseModel):
    """Snapshot of the series job (``partforge.jobs.Job.snapshot()``) with its typed result and progress –
    the same object ``GET /api/jobs/{id}`` and the job events deliver for this job."""

    id: str
    kind: str
    title: str
    status: JobStatus
    progress: float
    message: str = Field(description="Aktueller Schritt; am Ende die Zusammenfassung (= result.message)")
    log: list[JobLogLine] = Field(default_factory=list)
    result: series.SeriesCommitResult | None = Field(default=None, description="Ergebnis (status done)")
    error: str | None = None
    error_type: str | None = None
    detail: series.SeriesCommitDetail = Field(default_factory=series.SeriesCommitDetail,
                                              description="Phase und Zähler (job.detail)")
    cancel_reason: str | None = Field(default=None, description="library_switch = Bibliothek gewechselt, null = Benutzer")
    cancel_requested: bool = False
    created: float
    started: float | None = None
    finished: float | None = None
    version: int
    library: str | None = Field(default=None, description="Bibliotheksordner, für den der Job gestartet wurde")
    library_name: str | None = Field(default=None, description="Name dieser Bibliothek")


class SeriesJobOut(BaseModel):
    job: SeriesJobSnapshot = Field(description="Job „series“; das Ergebnis steht nach dem Ende in job.result")


class DecodeIn(BaseModel):
    mpn: str = Field(min_length=1, max_length=200)
    template_id: str | None = Field(default=None, description="Nur mit dieser Vorlage lesen")


class DecodeOut(BaseModel):
    mpn: str
    best: Decoded | None = None
    matches: list[Decoded] = Field(default_factory=list)


class TemplateSample(BaseModel):
    size: str
    value: str = Field(description="Wert, z. B. 10k, 100n; 0 = Brücke")
    codes: dict[str, str] = Field(default_factory=dict, description="Codes oder Werte je Variable (leer = Vorgabe)")


class TemplateTestIn(BaseModel):
    template: MpnTemplate
    samples: list[TemplateSample] = Field(default_factory=list)
    mpns: list[str] = Field(default_factory=list, description="Teilenummern, die mit der Vorlage gelesen werden sollen")


class TemplateSampleResult(BaseModel):
    sample: TemplateSample
    mpn: str | None = None
    valid: bool = Field(default=False, description="Laut Regeln/Matrix der Vorlage lieferbar")
    roundtrip: bool = False
    decoded: Decoded | None = None
    messages: list[str] = Field(default_factory=list)
    missing_fields: list[series.RequiredField] = Field(
        default_factory=list,
        description="Pflichtfelder der Kategorie, die bei diesem Bauteil leer blieben – die Serie würde es nicht "
                    "anlegen (nur wenn category_checked)")
    not_applicable: list[str] = Field(default_factory=list,
                                      description="Spalten, die für dieses Bauteil nicht gelten (0-Ω-Brücke)")
    values: dict[str, str | None] = Field(
        default_factory=dict, description="Kategoriewerte, wie die Serie sie speichern würde (inkl. Beschreibung)")


class TemplateTestOut(BaseModel):
    samples: list[TemplateSampleResult]
    decoded: list[Decoded | None]
    regex: str | None = None
    category_checked: bool = Field(default=False,
                                   description="Pflichtfelder gegen die Kategorie geprüft (missing_fields gültig)")
    category_note: str | None = Field(default=None, description="Warum die Pflichtfelder nicht geprüft wurden")


class DeleteOut(BaseModel):
    deleted: bool


# --------------------------------------------------------------------------- helpers


@contextmanager
def series_errors() -> Iterator[None]:
    """German HTTP errors: 404 template not found, 400 request/template problems, db errors as usual.

    A template whose data the engine cannot process (pattern that does not compile, code tables
    that do not fit together) is a 400 with a German message, never a 500."""
    try:
        with db_errors():
            yield
    except HTTPException:
        raise
    except TemplateNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (series.SeriesError, MpnError, TemplateError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (re.error, KeyError, IndexError) as exc:
        log.warning("Serienvorlage nicht verarbeitbar: %r", exc, exc_info=True)
        raise HTTPException(status_code=400, detail=f"Die Vorlage ist fehlerhaft und kann nicht verarbeitet werden "
                                                    f"({type(exc).__name__}: {exc}).") from exc


class _Categories:
    """Category of a template for the required-field check: the open library's (missing there: not
    creatable), without a library the built-in category; looked up once per request."""

    def __init__(self) -> None:
        self._found: dict[str, tuple[Any, str | None]] = {}

    def get(self, table: str) -> tuple[Any, str | None]:
        """(CategoryDef | None, German note when there is none)."""
        key = table.casefold()
        if key not in self._found:
            self._found[key] = self._lookup(table)
        return self._found[key]

    @staticmethod
    def _lookup(table: str) -> tuple[Any, str | None]:
        from ..db import categories, core
        from ..db.errors import CategoryNotFound

        if core.is_open():
            try:
                return categories.get_category(table), None
            except CategoryNotFound:
                return None, (f"Die Kategorie „{table}“ gibt es in dieser Bibliothek nicht – bitte anlegen oder eine "
                              "andere Vorlage wählen.")
        builtin = next((c for c in categories.builtin_templates() if c.table.casefold() == table.casefold()), None)
        if builtin is not None:
            return builtin, None
        return None, (f"„{table}“ ist keine eingebaute Kategorie – Pflichtfelder lassen sich erst mit geöffneter "
                      "Bibliothek prüfen.")


def _missing_text(table_label: str, missing: list[series.RequiredField]) -> str:
    labels = ", ".join(f.label for f in missing)
    return (f"{plural(len(missing), 'Pflichtfeld', 'Pflichtfelder', with_count=False)} der Kategorie „{table_label}“ "
            f"{'bleibt' if len(missing) == 1 else 'bleiben'} leer: {labels} – die Serie würde dieses Bauteil nicht "
            "anlegen.")


def _example_out(template: MpnTemplate, example: TemplateExample, cats: _Categories) -> TemplateExampleOut:
    out = TemplateExampleOut(mpn=example.mpn, size=example.size, value=example.value,
                             value_text=example.value_text, valid=example.valid, message=example.message,
                             segments=example.segments)
    cat, note = cats.get(template.category)
    if cat is None:
        out.valid = False
        out.message = out.message or note
        return out
    check = series.sample_check(template, cat, example.attrs, example.mpn)
    out.description = check.values.get("Description")
    out.missing_fields = check.missing
    problems = list(check.errors)
    if check.missing:
        problems.append(_missing_text(cat.label, check.missing))
    if problems and out.valid:
        out.valid = False
        out.message = " ".join(problems)
    return out


def _summary(template: MpnTemplate, cats: _Categories | None = None) -> TemplateSummary:
    data: dict[str, Any] = {**template.summary(), **template_facts(template).model_dump(),
                            "sources": template.sources}
    example = template_example(template)
    if example is not None:
        try:
            data["example"] = _example_out(template, example, cats or _Categories())
        except (ValueError, KeyError, IndexError, TypeError):  # one odd user template must not break the list
            log.warning("Beispiel der Serienvorlage %s nicht prüfbar", template.id, exc_info=True)
    return TemplateSummary.model_validate(data)


def _template_out(template: MpnTemplate, full: bool) -> TemplateDetail:
    exclude = None if full else {"availability"}
    data = template.model_dump(exclude=exclude)
    return TemplateDetail.model_validate({**data, "availability_count": len(template.availability)})


# --------------------------------------------------------------------------- templates


@router.get("/series/templates", response_model=list[TemplateSummary])
def get_templates(category: str | None = Query(default=None, description="Kategorietabelle, z. B. Resistors")
                  ) -> list[TemplateSummary]:
    """Built-in templates plus the user templates of the open library – each with its example part
    number (segments, description, required-field check) and key facts for the template cards."""
    with series_errors():
        cats = _Categories()
        return [_summary(t, cats) for t in list_templates(category)]


@router.get("/series/templates/custom", response_model=list[TemplateSummary],
            dependencies=[Depends(require_workspace)])
def get_custom_templates(category: str | None = None) -> list[TemplateSummary]:
    with series_errors():
        cats = _Categories()
        return [_summary(t, cats) for t in list_custom_templates(category)]


@router.post("/series/templates/custom", response_model=TemplateDetail, dependencies=[Depends(require_workspace)])
def create_custom_template(template: MpnTemplate) -> TemplateDetail:
    """Create a user template (409 if the id is taken – letter case does not count)."""
    with series_errors():
        wanted = template.id.casefold()
        if builtin_id_conflict(template.id) is not None or any(t.id.casefold() == wanted
                                                               for t in list_custom_templates()):
            raise HTTPException(status_code=409, detail=f"Eine Vorlage mit der ID „{template.id}“ gibt es bereits.")
        compile_template(template)  # pattern / regex problems -> 400 instead of a broken stored template
        return _template_out(save_custom_template(template), full=True)


@router.put("/series/templates/custom/{template_id}", response_model=TemplateDetail,
            dependencies=[Depends(require_workspace)])
def update_custom_template(template_id: str, template: MpnTemplate) -> TemplateDetail:
    with series_errors():
        if get_builtin(template_id) is not None:
            raise HTTPException(status_code=400, detail="Eingebaute Vorlagen können nicht geändert werden – bitte "
                                                        "als eigene Vorlage mit neuer ID speichern.")
        if not any(t.id == template_id for t in list_custom_templates()):
            raise HTTPException(status_code=404, detail=f"Eigene Vorlage „{template_id}“ nicht gefunden.")
        if template.id != template_id:
            raise HTTPException(status_code=400, detail="Die ID der Vorlage kann nicht geändert werden.")
        compile_template(template)
        return _template_out(save_custom_template(template), full=True)


@router.delete("/series/templates/custom/{template_id}", response_model=DeleteOut,
               dependencies=[Depends(require_workspace)])
def remove_custom_template(template_id: str) -> DeleteOut:
    with series_errors():
        if not delete_custom_template(template_id):
            raise HTTPException(status_code=404, detail=f"Eigene Vorlage „{template_id}“ nicht gefunden.")
        return DeleteOut(deleted=True)


def _sample_codes(template: MpnTemplate, sample: TemplateSample) -> tuple[str, dict[str, str]]:
    ct = compile_template(template)
    size = sample.size.strip()
    if size not in ct.size_code:
        size = resolve_size(template, size)  # name, code, label or metric code – never numeric similarity
    codes: dict[str, str] = {}
    for name, text in sample.codes.items():
        var = ct.variables.get(name)
        if var is None:
            raise MpnError(f"Die Vorlage hat keine Variable „{name}“.")
        option = find_option(var, text, size)
        if option is None:
            raise MpnError(f"„{text}“ ist kein Code der Variable „{var.label}“.")
        codes[name] = option.code
    return size, codes


@router.post("/series/templates/test", response_model=TemplateTestOut)
def test_template(body: TemplateTestIn) -> TemplateTestOut:
    """Build part numbers for sample values with a (draft) template and read them back; each sample is
    also checked against the required fields of the template's category (open library, else the
    built-in category) like the series preview would check it."""
    with series_errors():
        template = body.template
        ct = compile_template(template)
        cat, note = _Categories().get(template.category)
        results: list[TemplateSampleResult] = []
        for sample in body.samples:
            result = TemplateSampleResult(sample=sample)
            try:
                size, fixed = _sample_codes(template, sample)
                q = parse_quantity(sample.value, template.value_unit)
                if q is None or (q.unit and q.unit != template.value_unit):
                    raise MpnError(f"„{sample.value}“ ist kein gültiger Wert (Einheit {template.value_unit}).")
                jumper = q.value == 0
                res = resolve(template, size=size, value=q.value, fixed=fixed, jumper=jumper)
                mpn = encode_mpn(template, size=size, value=q.value, codes=res.codes, jumper=jumper)
                decoded = decode_mpn(template, mpn)
                result.mpn = mpn
                result.valid = res.ok
                result.decoded = decoded
                result.roundtrip = decoded is not None and decoded.mpn == mpn and decoded.size == size and \
                    decoded.value is not None and abs(decoded.value - q.value) <= abs(q.value) * 1e-9
                result.messages = list(res.messages)
                if not result.roundtrip:
                    result.messages.append("Die Teilenummer lässt sich mit dem Muster nicht eindeutig zurücklesen.")
                if cat is not None:
                    attrs = {**res.attrs, **base_attrs(template, size, q.value, mpn)}
                    check = series.sample_check(template, cat, attrs, mpn)
                    result.missing_fields = check.missing
                    result.not_applicable = check.not_applicable
                    result.values = check.values
                    result.messages.extend(check.errors)
                    if check.missing:
                        result.messages.append(_missing_text(cat.label, check.missing))
            except (MpnError, ValueError) as exc:
                result.messages.append(str(exc))
            results.append(result)
        decoded_list = [_decode_one(template, mpn) for mpn in body.mpns]
        return TemplateTestOut(samples=results, decoded=decoded_list, regex=ct.regex.pattern if ct.regex else None,
                               category_checked=cat is not None, category_note=note)


def _decode_one(template: MpnTemplate, mpn: str) -> Decoded | None:
    """One test part number: a single unreadable entry must not fail the whole template test."""
    try:
        return decode_mpn(template, mpn)
    except ValueError as exc:
        log.info("Teilenummer %s mit Vorlagenentwurf %s nicht lesbar: %s", mpn, template.id, exc)
        return None


@router.get("/series/templates/{template_id}", response_model=TemplateDetail,
            response_model_exclude_unset=False)
def get_template_detail(template_id: str, full: bool = Query(default=False, description="Mit Lieferbarkeitsmatrix")
                        ) -> TemplateDetail:
    """One template (code tables, sizes, rules, catalog; the availability matrix only with ``full``)."""
    with series_errors():
        return _template_out(get_template(template_id), full)


# --------------------------------------------------------------------------- preview / commit / decode


@router.post("/series/preview", response_model=series.SeriesPreview, dependencies=[Depends(require_workspace)])
def post_preview(body: series.SeriesRequest) -> series.SeriesPreview:
    """Rows of the series with status new / exists / conflict / invalid (nothing is written)."""
    with series_errors():
        return series.preview(body)


def commit_job(ctx: JobContext, request: series.SeriesRequest, mode: series.CommitMode, *,
               library: Path) -> dict[str, Any]:
    """Job "series": create the series in the library at ``library`` while holding it
    (:func:`partforge.jobs.library_hold`; ``LibraryChanged`` if it is no longer open)."""
    with library_hold(ctx, library):
        return series.commit(ctx, request, mode, library=library)


@router.post("/series/commit", response_model=SeriesJobOut)
def post_commit(body: SeriesCommitIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Create the series as a background job (symbol, footprints, parts) in the library open now –
    the job holds that library; it stops without writing if another library is open by the time it runs.
    ``job.result`` is a :class:`SeriesCommitResult`, ``job.detail`` a :class:`SeriesCommitDetail`."""
    with series_errors():
        request = series.SeriesRequest.model_validate(body.model_dump(exclude={"mode"}))
        series.validate(request)  # fail fast (400/404) instead of a failed job
        template = get_template(request.template_id)
    job = jobs.submit("series", f"Serie {template.title}", commit_job, request, body.mode, library=ws.root)
    return {"job": job.snapshot()}


@router.post("/series/decode", response_model=DecodeOut)
def post_decode(body: DecodeIn) -> DecodeOut:
    """Read a part number with every template (or one): template, size, value and field values."""
    with series_errors():
        if body.template_id:
            decoded = decode_mpn(get_template(body.template_id), body.mpn)
            matches = [decoded] if decoded is not None else []
        else:
            matches = decode_any(body.mpn)
        return DecodeOut(mpn=body.mpn.strip(), best=matches[0] if matches else None, matches=matches)


__all__ = ["commit_job", "router", "series_errors"]
