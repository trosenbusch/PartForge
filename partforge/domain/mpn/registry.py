"""Template registry: built-in templates plus user templates stored in the open library.

User templates live in ``pf_mpn_templates`` (:mod:`partforge.db.mpn_templates`) as the JSON of
:class:`~partforge.domain.mpn.model.MpnTemplate`; their ids must not collide with built-in ids.
Without an open library only the built-in templates are available.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic import ValidationError

from .builtin import builtin_templates
from .engine import Decoded, compile_template, decode_mpn
from .model import MpnTemplate

log = logging.getLogger(__name__)

__all__ = [
    "RESERVED_IDS",
    "TemplateError",
    "TemplateNotFound",
    "builtin_id_conflict",
    "decode_any",
    "delete_custom_template",
    "get_builtin",
    "get_template",
    "list_custom_templates",
    "list_templates",
    "save_custom_template",
]


class TemplateNotFound(KeyError):
    """No template with this id (German message)."""

    def __init__(self, template_id: str) -> None:
        super().__init__(template_id)
        self.template_id = template_id

    def __str__(self) -> str:
        return f"Serienvorlage „{self.template_id}“ nicht gefunden."


class TemplateError(ValueError):
    """A user template cannot be saved (German message)."""


#: Ids the API uses as path segments under /series/templates/ (a template with such an id could not be fetched).
RESERVED_IDS = frozenset({"custom", "test"})


def get_builtin(template_id: str) -> MpnTemplate | None:
    return next((t for t in builtin_templates() if t.id == template_id), None)


def builtin_id_conflict(template_id: str) -> str | None:
    """Id of a built-in template that equals ``template_id`` apart from letter case, else None."""
    wanted = template_id.casefold()
    return next((t.id for t in builtin_templates() if t.id.casefold() == wanted), None)


def _db_available() -> bool:
    from ...db import core

    return core.is_open()


def list_custom_templates(category: str | None = None) -> list[MpnTemplate]:
    """User templates of the open library, optionally of one category table (any letter case);
    invalid stored entries are skipped and logged."""
    if not _db_available():
        return []
    from ...db import mpn_templates

    wanted = category.casefold() if category else None
    out: list[MpnTemplate] = []
    for row in mpn_templates.list_mpn_templates():
        try:
            template = MpnTemplate.model_validate({**row["data"], "id": row["key"], "builtin": False})
        except ValidationError as exc:
            log.warning("Eigene Serienvorlage %s ist ungültig und wird ignoriert: %s", row["key"], exc)
            continue
        if wanted is None or template.category.casefold() == wanted:
            out.append(template)
    return out


def _get_custom(template_id: str) -> MpnTemplate | None:
    if not _db_available():
        return None
    from ...db import mpn_templates

    row = mpn_templates.get_mpn_template(template_id)
    if row is None:
        return None
    try:
        return MpnTemplate.model_validate({**row["data"], "id": row["key"], "builtin": False})
    except ValidationError as exc:
        raise TemplateError(f"Die gespeicherte Vorlage „{template_id}“ ist ungültig: {_validation_text(exc)}") from exc


def get_template(template_id: str) -> MpnTemplate:
    """Built-in or user template; raises :class:`TemplateNotFound`."""
    template = get_builtin(template_id) or _get_custom(template_id)
    if template is None:
        raise TemplateNotFound(template_id)
    return template


def list_templates(category: str | None = None) -> list[MpnTemplate]:
    """Built-in templates followed by user templates, optionally for one category table."""
    wanted = category.casefold() if category else None
    builtins = [t for t in builtin_templates() if wanted is None or t.category.casefold() == wanted]
    customs = [t for t in list_custom_templates() if wanted is None or t.category.casefold() == wanted]
    return [*builtins, *customs]


def _validation_text(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts)


def save_custom_template(template: MpnTemplate) -> MpnTemplate:
    """Insert or replace a user template in the open library (the engine must be able to compile it)."""
    builtin = builtin_id_conflict(template.id)
    if builtin is not None:
        raise TemplateError(f"Die ID „{template.id}“ gehört zu einer eingebauten Vorlage ({builtin}) – "
                            "bitte eine andere ID wählen.")
    if template.id.casefold() in RESERVED_IDS:
        raise TemplateError(f"Die ID „{template.id}“ ist reserviert – bitte eine andere ID wählen.")
    from ...db import mpn_templates

    compile_template(template)  # MpnError (German) instead of a stored template that fails later

    data = template.model_dump(mode="json", exclude={"builtin"})
    data.pop("id", None)
    mpn_templates.save_mpn_template(template.id, template.title, data, category=template.category)
    log.info("Eigene Serienvorlage %s gespeichert", template.id)
    return template.model_copy(update={"builtin": False})


def delete_custom_template(template_id: str) -> bool:
    if get_builtin(template_id) is not None:
        raise TemplateError("Eingebaute Vorlagen können nicht gelöscht werden.")
    if not _db_available():
        return False
    from ...db import mpn_templates

    return mpn_templates.delete_mpn_template(template_id)


def decode_any(mpn: str, templates: Iterable[MpnTemplate] | None = None) -> list[Decoded]:
    """Read ``mpn`` with every template; matches sorted valid first, then by template order."""
    candidates = list(templates) if templates is not None else list_templates()
    results: list[Decoded] = []
    for template in candidates:
        try:
            decoded = decode_mpn(template, mpn)
        except ValueError as exc:  # a broken user template (German message) must not break decoding
            log.warning("Teilenummer %s: Vorlage %s nicht auswertbar: %s", mpn, template.id, exc)
            continue
        except Exception:  # noqa: BLE001 - unexpected: keep the trace, but go on with the other templates
            log.exception("Teilenummer %s: Vorlage %s nicht auswertbar", mpn, template.id)
            continue
        if decoded is not None:
            results.append(decoded)
    results.sort(key=lambda d: (not d.valid, len(d.messages)))
    return results
