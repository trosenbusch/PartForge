"""Errors of the symbol generator (messages are German and shown to the user)."""

from __future__ import annotations

__all__ = ["SymbolError"]


class SymbolError(ValueError):
    """Invalid symbol request (unknown kind, bad parameter, inconsistent pins ...).

    The API maps it to HTTP 400; the message is user-facing German text.
    """
