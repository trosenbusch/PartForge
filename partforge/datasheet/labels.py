"""German display texts of the datasheet import: model names, effort levels („Gründlichkeit“), money.

    model_label("claude-opus-5-5")                 -> "Claude Opus 5.5"
    model_label("claude-haiku-4-5-20251001")       -> "Claude Haiku 4.5"
    effort_label("low")                            -> "niedrig"
    run_label("claude-opus-5-5", "low")            -> "Claude Opus 5.5 · Gründlichkeit niedrig"
    usd(0.2294)                                    -> "0,23 $"

Progress messages, log lines and outcome sentences use these instead of raw model ids or English values. The
effort level is called „Gründlichkeit“ everywhere (Einstellungen › KI, import dialogs, progress texts).
"""
from __future__ import annotations

import re

__all__ = ["EFFORT_LABELS", "effort_label", "model_label", "run_label", "usd"]

EFFORT_LABELS: dict[str, str] = {
    "low": "niedrig",
    "medium": "mittel",
    "high": "hoch",
    "xhigh": "sehr hoch",
    "max": "maximal",
}
_FAMILIES = {"opus": "Opus", "sonnet": "Sonnet", "haiku": "Haiku", "fable": "Fable", "mythos": "Mythos"}
_MODEL = re.compile(r"^claude-(?P<family>[a-z]+)-(?P<version>\d+(?:-\d{1,2})*?)(?:-(?P<date>\d{8}))?$")
_OLD_MODEL = re.compile(r"^claude-(?P<version>\d+(?:-\d{1,2})?)-(?P<family>[a-z]+)(?:-(?P<rest>.+))?$")


def model_label(model: str | None) -> str:
    """Friendly name of a Claude model id (unknown ids are returned unchanged)."""
    text = (model or "").strip()
    if not text:
        return "Claude"
    m = _MODEL.match(text)
    if m and m.group("family") in _FAMILIES:
        return f"Claude {_FAMILIES[m.group('family')]} {m.group('version').replace('-', '.')}"
    m = _OLD_MODEL.match(text)  # claude-3-7-sonnet-latest
    if m and m.group("family") in _FAMILIES:
        return f"Claude {m.group('version').replace('-', '.')} {_FAMILIES[m.group('family')]}"
    return text


def effort_label(effort: str | None) -> str:
    """German effort level – the „Gründlichkeit“ (``None``/empty = the model's default)."""
    if not effort:
        return "Standard"
    return EFFORT_LABELS.get(str(effort).strip().lower(), str(effort))


def run_label(model: str | None, effort: str | None = None) -> str:
    """``Claude Opus 5.5 · Gründlichkeit niedrig`` (without effort: just the model name)."""
    label = model_label(model)
    return f"{label} · Gründlichkeit {effort_label(effort)}" if effort else label


def usd(value: float | None) -> str:
    """Money in German notation: ``0,23 $`` (below 0.10 USD three decimals: ``0,004 $``)."""
    amount = max(0.0, float(value or 0.0))
    digits = 2 if amount >= 0.1 or amount == 0 else 3
    return f"{amount:,.{digits}f}".replace(",", " ").replace(".", ",").replace(" ", ".") + " $"
