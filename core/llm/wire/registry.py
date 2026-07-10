"""Immutable-route dispatch for wire adapters."""

from __future__ import annotations

from typing import Any

from ..protocols import WireProtocol
from ..provider_replay_state import endpoint_fingerprint
from ..semantic_messages import SemanticModelRequest
from .base import WireAdapter
from .types import BuiltPayload


class WireAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, WireAdapter] = {}

    def register(self, adapter: WireAdapter) -> None:
        adapter_id = str(getattr(adapter, "adapter_id", "") or "").strip()
        if not adapter_id:
            raise ValueError("wire adapter requires adapter_id")
        if adapter_id in self._adapters:
            raise ValueError(f"wire adapter `{adapter_id}` is already registered")
        self._adapters[adapter_id] = adapter

    def resolve(self, route: Any) -> WireAdapter:
        adapter_id = str(getattr(route, "adapter_id", "") or "").strip()
        adapter = self._adapters.get(adapter_id)
        if adapter is None:
            raise LookupError(f"wire adapter `{adapter_id}` is not registered")
        route_protocol = getattr(route, "wire_protocol", None)
        if not isinstance(route_protocol, WireProtocol) or adapter.wire_protocol != route_protocol:
            raise ValueError("wire adapter and immutable route wire protocol do not match")
        return adapter

    def encode_request(self, route: Any, request: SemanticModelRequest) -> BuiltPayload:
        adapter = self.resolve(route)
        if request.replay_state is not None:
            request.replay_state.require_compatible(
                issuer=adapter.adapter_id,
                provider_id=str(getattr(route, "provider_id", "") or ""),
                endpoint_fingerprint=endpoint_fingerprint(str(getattr(route, "runtime_endpoint", "") or "")),
                model_id=str(getattr(route, "model_id", "") or ""),
                wire_protocol=route.wire_protocol,
            )
        return adapter.encode_request(request)
