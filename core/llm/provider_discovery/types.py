from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ProviderDiscoveryRequest:
    provider_id: str
    provider: dict[str, Any]
    credential: str = field(default="", repr=False)
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class DiscoveredProviderModel:
    upstream_id: str
    label: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    metadata_source: str = "provider_endpoint"


@dataclass(frozen=True)
class ProviderDiscoveryResult:
    provider_id: str
    adapter_id: str
    attempted_endpoints: tuple[str, ...]
    discovered_at: str
    models: tuple[DiscoveredProviderModel, ...]


class ProviderDiscoveryAdapter(Protocol):
    adapter_id: str

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult: ...


__all__ = [
    "DiscoveredProviderModel",
    "ProviderDiscoveryAdapter",
    "ProviderDiscoveryRequest",
    "ProviderDiscoveryResult",
]
