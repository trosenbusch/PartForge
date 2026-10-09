"""Tiny in-process event hub, so modules can react to each other without import cycles.

    from partforge import events
    events.subscribe(events.WORKSPACE_OPENED, lambda ws: ...)
    events.emit(events.WORKSPACE_OPENED, ws)

Handlers run synchronously in the emitting thread; exceptions are logged and never
propagate to the emitter (an event must not break the action that caused it).
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

log = logging.getLogger("partforge.events")

# Event names --------------------------------------------------------------------
WORKSPACE_OPENED = "workspace.opened"  # (ws)
WORKSPACE_CLOSED = "workspace.closed"  # ()
SCHEMA_CHANGED = "db.schema_changed"  # ()  categories/fields added, changed or removed
PARTS_CHANGED = "db.parts_changed"  # (table: str | None, inserted: bool)  rows written
LIBRARIES_WRITTEN = "altium.libraries_written"  # (paths: list[str])  SchLib/PcbLib files rewritten

_lock = threading.RLock()
_handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)


def subscribe(event: str, handler: Callable[..., Any]) -> Callable[[], None]:
    """Register a handler; returns a function that unsubscribes it again."""
    with _lock:
        if handler not in _handlers[event]:
            _handlers[event].append(handler)

    def unsubscribe() -> None:
        with _lock:
            if handler in _handlers[event]:
                _handlers[event].remove(handler)

    return unsubscribe


def emit(event: str, *args: Any, **kwargs: Any) -> None:
    with _lock:
        handlers = list(_handlers.get(event, ()))
    for handler in handlers:
        try:
            handler(*args, **kwargs)
        except Exception:  # noqa: BLE001 - handlers must never break the emitter
            log.exception("Fehler im Ereignis-Handler %r für %s", handler, event)


def clear(event: str | None = None) -> None:
    """Remove handlers (tests)."""
    with _lock:
        if event is None:
            _handlers.clear()
        else:
            _handlers.pop(event, None)
