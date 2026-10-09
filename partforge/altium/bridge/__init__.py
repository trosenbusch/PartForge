"""PartForge's DelphiScript bridge to a running Altium Designer.

Import-light on purpose: nothing is created or started at import time and the
submodules are loaded lazily (``partforge.altium.bridge.protocol`` can be imported by
the Rust writer without pulling in the bridge core).

* :class:`~partforge.altium.bridge.core.AltiumBridge` – exchange files, launcher, wedge detection, commands.
* :class:`~partforge.altium.bridge.writer.AltiumLibraryWriter` – library writer backend.
* :mod:`~partforge.altium.bridge.spec` / :mod:`~partforge.altium.bridge.protocol` – ASCII exchange formats.
"""
from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - static typing only
    from .core import (
        RECOVERY_HINT,
        AltiumBridge,
        AltiumNotRunning,
        BridgeBusyError,
        BridgeCommandError,
        BridgeError,
        BridgeWedgedError,
        BridgeWriteResult,
        DbComponentResolution,
        DocumentState,
        default_exchange_dir,
    )
    from .process import altium_backend_status, is_process_running
    from .protocol import BridgeProtocolError, BridgeResponse
    from .spec import BridgeSpecError
    from .writer import AltiumDataLossError, AltiumLibraryWriter, AltiumWriterError

_EXPORTS: dict[str, str] = {
    "RECOVERY_HINT": "core",
    "AltiumBridge": "core",
    "AltiumNotRunning": "core",
    "BridgeBusyError": "core",
    "BridgeCommandError": "core",
    "BridgeError": "core",
    "BridgeWedgedError": "core",
    "BridgeWriteResult": "core",
    "DbComponentResolution": "core",
    "DocumentState": "core",
    "default_exchange_dir": "core",
    "altium_backend_status": "process",
    "is_process_running": "process",
    "BridgeProtocolError": "protocol",
    "BridgeResponse": "protocol",
    "BridgeSpecError": "spec",
    "AltiumDataLossError": "writer",
    "AltiumLibraryWriter": "writer",
    "AltiumWriterError": "writer",
}

__all__ = [
    "RECOVERY_HINT",
    "AltiumBridge",
    "AltiumDataLossError",
    "AltiumLibraryWriter",
    "AltiumNotRunning",
    "AltiumWriterError",
    "BridgeBusyError",
    "BridgeCommandError",
    "BridgeError",
    "BridgeProtocolError",
    "BridgeResponse",
    "BridgeSpecError",
    "BridgeWedgedError",
    "BridgeWriteResult",
    "DbComponentResolution",
    "DocumentState",
    "altium_backend_status",
    "default_exchange_dir",
    "is_process_running",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted([*globals(), *_EXPORTS])
