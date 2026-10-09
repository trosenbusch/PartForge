"""Models shared by the Altium-facing modules (library writers, sync, DbLib)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WriteResult(BaseModel):
    library: str  # absolute path
    backend: Literal["rust", "altium"]
    written: list[str] = Field(default_factory=list)  # component names created or updated
    deleted: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)  # component name -> message
    duration_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.errors


class ComponentInfo(BaseModel):
    name: str
    library: str  # absolute path
    kind: Literal["symbol", "footprint"]
    description: str | None = None
    pin_count: int | None = None  # symbols: pins, footprints: pads
    part_count: int | None = None
    has_3d: bool | None = None


class BackendStatus(BaseModel):
    name: Literal["rust", "altium"]
    available: bool
    message: str
    version: str | None = None
    path: str | None = None
