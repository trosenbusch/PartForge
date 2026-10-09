"""Redact the session token from log output (QA sec finding 4).

The token travels as ``?token=`` for EventSource, page images, the datasheet PDF and exports (contexts
that cannot set a header). uvicorn's access log writes the full request URL – including that query – so
without this filter the per-process token would land in ``partforge.log`` (and the console in
``--verbose``). The filter rewrites ``token=<value>`` to ``token=<redigiert>`` in every log record before
it is formatted, both for uvicorn's loggers and for PartForge's own.
"""
from __future__ import annotations

import logging
import re

__all__ = ["RedactTokenFilter", "redact_token"]

# token=<value> up to the next separator (& whitespace quote backslash). Case-insensitive for safety.
_TOKEN_RE = re.compile(r"(?i)(token=)[^&\s\"'\\]+")
_REPLACEMENT = r"\1<redigiert>"


def redact_token(text: str) -> str:
    """Replace every ``token=<value>`` in ``text`` with ``token=<redigiert>``."""
    return _TOKEN_RE.sub(_REPLACEMENT, text)


def _maybe(value: object) -> object:
    if isinstance(value, str) and "token=" in value.lower():
        return redact_token(value)
    return value


class RedactTokenFilter(logging.Filter):
    """A logging filter that strips ``token=`` values from a record's message and arguments.

    Attached to the log *handlers* so it also covers records that propagate from uvicorn's loggers
    (``uvicorn.access`` formats the request URL with its query string into the record arguments).
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        try:
            record.msg = _maybe(record.msg)
            args = record.args
            if isinstance(args, tuple):
                record.args = tuple(_maybe(a) for a in args)
            elif isinstance(args, dict):
                record.args = {k: _maybe(v) for k, v in args.items()}
            # a traceback can quote a URL with the token (e.g. in an exception message): format it once
            # here, redacted – Formatter.format() reuses record.exc_text instead of formatting it again
            if record.exc_info and not record.exc_text:
                record.exc_text = _FORMATTER.formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = _maybe(record.exc_text)
            if record.stack_info:
                record.stack_info = _maybe(record.stack_info)
        except Exception:  # noqa: BLE001 - logging must never raise
            pass
        return True


_FORMATTER = logging.Formatter()
