"""Parsing and validation of generator parameters (``FootprintRequest.params``).

Accepted value forms for toleranced dimensions (``ParamSpec.kind == "tol"``):

* number ``1.27`` (min = nom = max), numeric string ``"1,27"``
* ``{"min": 0.31, "max": 0.51}``, ``{"min": .., "nom": .., "max": ..}``, ``{"nom": 3.0}``,
  ``{"max": 1.75}`` (only a limit given), ``-1`` sentinels (datasheet AI) count as missing
* ``[min, max]`` / ``[min, nom, max]`` / ``"0.31..0.51"`` / ``"6.0±0.2"``

All errors are raised as :class:`ParamError` (a ``ValueError``) with a German message.
"""
from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

from .models import ParamSpec, Tol

_T = TypeVar("_T")

_SENTINEL = -1.0
MAX_DIMENSION = 1000.0  # mm: plausibility bound for every length (protects names, maths and writers)


class ParamError(ValueError):
    """Invalid generator parameter (German message).

    ``params`` names the request parameters (``FootprintRequest.params`` keys) the error is
    about, e.g. ``("E1",)``; empty when the error is not tied to a parameter. The API reports
    them as ``detail.params`` so the UI can mark the fields.
    """

    def __init__(self, message: str, *, params: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.params: tuple[str, ...] = tuple(params)


def _named(method: Callable[..., _T]) -> Callable[..., _T]:
    """Accessor decorator: a :class:`ParamError` without parameter names gets the accessor's ``name``."""

    @functools.wraps(method)
    def wrapper(self: Params, name: str, *args: Any, **kwargs: Any) -> _T:
        try:
            return method(self, name, *args, **kwargs)
        except ParamError as exc:
            if not exc.params:
                exc.params = (name,)
            raise

    return wrapper


def _num(value: Any, label: str, *, sentinel: bool = False) -> float | None:
    """Parse a single number; ``None``/``""`` (and the -1 sentinel if enabled) -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ParamError(f"„{label}“: Zahl erwartet, nicht {value!r}.")
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        text = value.strip().replace("mm", "").replace(" ", "").replace(",", ".")
        if text == "":
            return None
        try:
            v = float(text)
        except ValueError as exc:
            raise ParamError(f"„{label}“: „{value}“ ist keine gültige Zahl.") from exc
    else:
        raise ParamError(f"„{label}“: Zahl erwartet, nicht {type(value).__name__}.")
    if not math.isfinite(v):
        raise ParamError(f"„{label}“: Wert muss endlich sein.")
    if sentinel and v == _SENTINEL:
        return None
    return v


_RANGE_RE = re.compile(r"^\s*([-+]?\d*[.,]?\d+)\s*(?:\.\.|…|~|bis|to|–|—|-(?=\s*\d))\s*([-+]?\d*[.,]?\d+)\s*(?:mm)?\s*$")
_PM_RE = re.compile(r"^\s*([-+]?\d*[.,]?\d+)\s*(?:±|\+/-|\+-)\s*(\d*[.,]?\d+)\s*(?:mm)?\s*$")


def parse_tol(value: Any, label: str = "Maß") -> Tol | None:
    """Parse a toleranced dimension; ``None`` when no value is given."""
    if value is None:
        return None
    if isinstance(value, Tol):
        return value
    if isinstance(value, bool):
        raise ParamError(f"„{label}“: Zahl erwartet, nicht {value!r}.")
    if isinstance(value, str):
        m = _PM_RE.match(value)
        if m:
            centre = float(m.group(1).replace(",", "."))
            tol = float(m.group(2).replace(",", "."))
            return Tol(min=centre - tol, max=centre + tol, nom=centre)
        m = _RANGE_RE.match(value)
        if m:
            a = float(m.group(1).replace(",", "."))
            b = float(m.group(2).replace(",", "."))
            return Tol(min=min(a, b), max=max(a, b))
        v = _num(value, label)
        return None if v is None else Tol(min=v, max=v, nom=v)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        v = _num(value, label)
        return None if v is None else Tol(min=v, max=v, nom=v)
    if isinstance(value, Mapping):  # datasheet-AI form: -1 means "not given"
        lo = _num(value.get("min"), label, sentinel=True)
        mid = _num(value.get("nom", value.get("typ")), label, sentinel=True)
        hi = _num(value.get("max"), label, sentinel=True)
        return _tol_from_parts(lo, mid, hi, label)
    if isinstance(value, (list, tuple)):
        parts = [_num(v, label) for v in value]
        if len(parts) == 1:
            return _tol_from_parts(None, parts[0], None, label)
        if len(parts) == 2:
            return _tol_from_parts(parts[0], None, parts[1], label)
        if len(parts) == 3:
            return _tol_from_parts(parts[0], parts[1], parts[2], label)
        raise ParamError(f"„{label}“: Liste mit 1 bis 3 Werten erwartet (min, nom, max).")
    raise ParamError(f"„{label}“: ungültige Maßangabe {value!r}.")


def _tol_from_parts(mn: float | None, nom: float | None, mx: float | None, label: str) -> Tol | None:
    if mn is None and nom is None and mx is None:
        return None
    if mn is not None and mx is not None:
        if mx < mn:
            mn, mx = mx, mn
        if nom is not None and not (mn - 1e-9 <= nom <= mx + 1e-9):
            raise ParamError(f"„{label}“: Nennwert {nom} liegt nicht zwischen {mn} und {mx}.")
        return Tol(min=mn, max=mx, nom=nom)
    if nom is not None:
        if mn is not None:  # symmetric completion
            return Tol(min=mn, max=max(nom, 2 * nom - mn), nom=nom)
        if mx is not None:
            return Tol(min=max(0.0, min(nom, 2 * nom - mx)), max=mx, nom=nom)
        return Tol(min=nom, max=nom, nom=nom)
    single = mn if mn is not None else mx
    assert single is not None
    return Tol(min=single, max=single, nom=single)


def tol_to_json(t: Tol) -> dict[str, float]:
    nom = t.nom if t.nom is not None else (t.min + t.max) / 2
    return {"min": round(t.min, 6), "nom": round(nom, 6), "max": round(t.max, 6)}


def nom(t: Tol) -> float:
    return t.nom if t.nom is not None else (t.min + t.max) / 2


class Params:
    """Typed access to request parameters with defaults from the family's ``ParamSpec`` list.

    Every value read is recorded (normalised, JSON-serialisable) in :attr:`resolved`, which is
    stored in ``FootprintSpec.generator`` for exact regeneration.
    """

    def __init__(self, raw: Mapping[str, Any], specs: Iterable[ParamSpec]):
        self._raw = dict(raw)
        self._specs: dict[str, ParamSpec] = {s.name: s for s in specs}
        self.resolved: dict[str, Any] = {}

    # -- helpers ------------------------------------------------------------------------
    def label(self, name: str) -> str:
        spec = self._specs.get(name)
        return spec.label if spec else name

    def _raw_value(self, name: str) -> Any:
        value = self._raw.get(name)
        if isinstance(value, str) and value.strip() == "":
            value = None
        if value is None:
            spec = self._specs.get(name)
            value = spec.default if spec else None
        return value

    @_named
    def given(self, name: str) -> bool:
        """True if the request itself (not the default) carries a value."""
        value = self._raw.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            return False
        if isinstance(value, Mapping):
            return any(_num(value.get(k), name, sentinel=True) is not None for k in ("min", "nom", "max", "typ"))
        return True

    def _check_magnitude(self, name: str, value: float) -> None:
        if abs(value) > MAX_DIMENSION:
            raise ParamError(f"„{self.label(name)}“: {value:g} ist unplausibel groß "
                             f"(höchstens {MAX_DIMENSION:g} mm).")

    def _check_range(self, name: str, value: float) -> None:
        spec = self._specs.get(name)
        if spec is None:
            return
        if spec.kind in ("tol", "float"):
            self._check_magnitude(name, value)
        unit = f" {spec.unit}" if spec.unit else ""
        if spec.minimum is not None and value < spec.minimum - 1e-9:
            raise ParamError(f"„{spec.label}“: {value:g}{unit} ist kleiner als das Minimum {spec.minimum:g}{unit}.")
        if spec.maximum is not None and value > spec.maximum + 1e-9:
            raise ParamError(f"„{spec.label}“: {value:g}{unit} ist größer als das Maximum {spec.maximum:g}{unit}.")

    def _missing(self, name: str) -> ParamError:
        return ParamError(f"Parameter „{self.label(name)}“ fehlt.", params=(name,))

    # -- typed accessors ----------------------------------------------------------------
    @_named
    def tol_opt(self, name: str) -> Tol | None:
        t = parse_tol(self._raw_value(name), self.label(name))
        if t is None:
            return None
        self._check_magnitude(name, t.min)
        self._check_magnitude(name, t.max)
        spec = self._specs.get(name)
        if spec is None or spec.minimum is None:
            if t.min < -1e-9:
                raise ParamError(f"„{self.label(name)}“: negative Maße sind nicht zulässig.")
        else:
            self._check_range(name, t.min)
        if spec is not None and spec.maximum is not None:
            self._check_range(name, t.max)
        self.resolved[name] = tol_to_json(t)
        return t

    @_named
    def tol(self, name: str, default: Tol | None = None) -> Tol:
        t = self.tol_opt(name)
        if t is None:
            if default is None:
                raise self._missing(name)
            t = default
            self.resolved[name] = tol_to_json(t)
        return t

    @_named
    def tol_or(self, name: str, default: Tol | None) -> Tol:
        """The request value if one is given, else ``default`` (which takes precedence over the
        ParamSpec default, e.g. dimensions of the selected size or variant)."""
        if self.given(name) or default is None:
            return self.tol(name)
        self.resolved[name] = tol_to_json(default)
        return default

    @_named
    def float_or(self, name: str, default: float | None) -> float:
        """Like :meth:`tol_or` for plain numbers."""
        if self.given(name) or default is None:
            return self.float(name)
        self.resolved[name] = default
        return default

    @_named
    def float_opt(self, name: str) -> float | None:
        v = _num(self._raw_value(name), self.label(name))
        if v is None:
            return None
        self._check_range(name, v)
        self.resolved[name] = v
        return v

    @_named
    def float(self, name: str, default: float | None = None) -> float:
        v = self.float_opt(name)
        if v is None:
            if default is None:
                raise self._missing(name)
            v = default
            self.resolved[name] = v
        return v

    @_named
    def int(self, name: str, default: int | None = None) -> int:
        raw = self._raw_value(name)
        if raw is None:
            if default is None:
                raise self._missing(name)
            raw = default
        if isinstance(raw, bool):
            raise ParamError(f"„{self.label(name)}“: ganze Zahl erwartet.")
        try:
            f = float(str(raw).replace(",", ".")) if isinstance(raw, str) else float(raw)
        except (TypeError, ValueError) as exc:
            raise ParamError(f"„{self.label(name)}“: „{raw}“ ist keine ganze Zahl.") from exc
        if not math.isfinite(f) or abs(f - round(f)) > 1e-9:
            raise ParamError(f"„{self.label(name)}“: „{raw}“ ist keine ganze Zahl.")
        v = round(f)
        self._check_range(name, v)
        self.resolved[name] = v
        return v

    @_named
    def enum(self, name: str, default: str | None = None) -> str:
        raw = self._raw_value(name)
        if raw is None:
            if default is None:
                raise self._missing(name)
            raw = default
        value = str(raw).strip()
        spec = self._specs.get(name)
        if spec and spec.options:
            match = next((o for o in spec.options if o.lower() == value.lower()), None)
            if match is None:
                raise ParamError(
                    f"„{spec.label}“: „{value}“ ist nicht zulässig (erlaubt: {', '.join(spec.options)})."
                )
            value = match
        self.resolved[name] = value
        return value

    @_named
    def bool(self, name: str, default: bool | None = None) -> bool:
        raw = self._raw_value(name)
        if raw is None:
            if default is None:
                raise self._missing(name)
            raw = default
        if isinstance(raw, bool):
            value = raw
        elif isinstance(raw, (int, float)):
            value = bool(raw)
        else:
            text = str(raw).strip().lower()
            if text in ("1", "true", "ja", "yes", "y", "j", "an", "on"):
                value = True
            elif text in ("0", "false", "nein", "no", "n", "aus", "off"):
                value = False
            else:
                raise ParamError(f"„{self.label(name)}“: Ja/Nein erwartet, nicht „{raw}“.")
        self.resolved[name] = value
        return value

    def text(self, name: str, default: str = "") -> str:
        raw = self._raw_value(name)
        value = default if raw is None else str(raw).strip()
        if value:
            self.resolved[name] = value
        return value
