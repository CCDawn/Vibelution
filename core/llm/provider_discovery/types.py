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


def assert_no_credential_taint(value: Any, credential: str) -> None:
    """Fail closed when provider-controlled data contains the active credential."""

    secret = str(credential or "")
    if not secret:
        return
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if secret in current:
                raise ValueError("provider discovery response contains credential material")
            continue
        if isinstance(current, dict):
            pending.extend(current.keys())
            pending.extend(current.values())
            continue
        if isinstance(current, (list, tuple, set, frozenset)):
            pending.extend(current)


__all__ = [
    "DiscoveredProviderModel",
    "ProviderDiscoveryAdapter",
    "ProviderDiscoveryRequest",
    "ProviderDiscoveryResult",
    "assert_no_credential_taint",
]
