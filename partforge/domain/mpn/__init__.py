"""Manufacturer part-number (MPN) templates: encode and decode the part numbers of a series.

Public API::

    list_templates(category=None) -> list[MpnTemplate]      # built-in + user templates of the open library
    get_template(id) -> MpnTemplate                           # TemplateNotFound (KeyError)
    resolve(template, size=, value=, fixed=) -> Resolution    # codes/attributes of one part + validity
    resolve_size(template, text) -> str                       # size name from name/code/label/metric code
    encode_mpn(template, size=, value=, codes=) -> str        # MpnError (ValueError) with German text
    decode_mpn(template, mpn) -> Decoded | None               # one template
    decode_any(mpn) -> list[Decoded]                          # every template, valid matches first
    save_custom_template(t) / delete_custom_template(id)      # pf_mpn_templates
    encode_value(value, fmt) / decode_value(code, fmt)        # value codes (10K0, 4K7, 1002, 104 …)

Importing this package has no side effects (built-in templates are built on first use).
"""
from __future__ import annotations

from .engine import (
    CompiledTemplate,
    Decoded,
    MpnError,
    Resolution,
    compact,
    compile_template,
    decode_mpn,
    encode_mpn,
    find_option,
    format_value,
    in_series,
    parse_series,
    render_fields,
    resolve,
    resolve_size,
    series_of_value,
)
from .formats import ValueCodeError, ValueFormat, decode_value, encode_value, value_regex
from .model import (
    AvailabilityCell,
    CatalogEntry,
    CodeOption,
    FootprintHint,
    FormatOverride,
    JumperSpec,
    MpnTemplate,
    SizeSpec,
    Source,
    ValueRule,
    Variable,
    forbidden_characters,
    parse_pattern,
)
from .registry import (
    RESERVED_IDS,
    TemplateError,
    TemplateNotFound,
    builtin_id_conflict,
    decode_any,
    delete_custom_template,
    get_builtin,
    get_template,
    list_custom_templates,
    list_templates,
    save_custom_template,
)

__all__ = [
    "AvailabilityCell",
    "CatalogEntry",
    "CodeOption",
    "CompiledTemplate",
    "Decoded",
    "FootprintHint",
    "FormatOverride",
    "JumperSpec",
    "MpnError",
    "MpnTemplate",
    "RESERVED_IDS",
    "Resolution",
    "SizeSpec",
    "Source",
    "TemplateError",
    "TemplateNotFound",
    "ValueCodeError",
    "ValueFormat",
    "ValueRule",
    "Variable",
    "builtin_id_conflict",
    "compact",
    "compile_template",
    "decode_any",
    "decode_mpn",
    "decode_value",
    "delete_custom_template",
    "encode_mpn",
    "encode_value",
    "find_option",
    "forbidden_characters",
    "format_value",
    "get_builtin",
    "get_template",
    "in_series",
    "list_custom_templates",
    "list_templates",
    "parse_pattern",
    "parse_series",
    "render_fields",
    "resolve",
    "resolve_size",
    "save_custom_template",
    "series_of_value",
    "value_regex",
]
