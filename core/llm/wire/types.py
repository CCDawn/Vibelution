"""Wire adapter boundary values."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class BuiltPayload:
    body: Mapping[str, Any]
    endpoint: str = ""
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "body", MappingProxyType(dict(self.body)))
        object.__setattr__(self, "headers", MappingProxyType(dict(self.headers)))
