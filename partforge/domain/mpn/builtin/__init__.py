"""Built-in MPN templates (one factory per manufacturer series), built lazily and cached."""
from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable

from ..model import MpnTemplate
from .capacitors import CAPACITOR_TEMPLATES
from .inductors import INDUCTOR_TEMPLATES
from .resistors import RESISTOR_TEMPLATES

log = logging.getLogger(__name__)

__all__ = ["BUILTIN_FACTORIES", "builtin_templates"]

BUILTIN_FACTORIES: list[Callable[[], MpnTemplate]] = [*RESISTOR_TEMPLATES, *CAPACITOR_TEMPLATES, *INDUCTOR_TEMPLATES]

_lock = threading.Lock()


@functools.cache
def _build() -> tuple[MpnTemplate, ...]:
    templates = tuple(factory() for factory in BUILTIN_FACTORIES)
    ids = [t.id for t in templates]
    if len(ids) != len(set(ids)):  # pragma: no cover - programming error
        raise RuntimeError("Doppelte IDs in den eingebauten Serienvorlagen.")
    log.debug("%d eingebaute Serienvorlagen geladen", len(templates))
    return templates


def builtin_templates() -> tuple[MpnTemplate, ...]:
    """All built-in templates (built once, thread-safe). Treat them as read-only."""
    with _lock:
        return _build()
