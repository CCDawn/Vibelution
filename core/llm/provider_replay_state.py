"""Bounded, route-scoped provider replay state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .protocols import WireProtocol

MAX_REPLAY_ITEMS = 32
MAX_REPLAY_BYTES = 256 * 1024


def endpoint_fingerprint(endpoint: str) -> str:
    raw = str(endpoint or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        host = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
        normalized = f"{parsed.scheme.lower()}://{host}{port}{parsed.path.rstrip('/')}"
    else:
        normalized = raw.rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OpaqueReplayItem:
    item_id: str
    payload: bytes = field(repr=False)
    kind: str = "provider_replay"

    def __post_init__(self) -> None:
        if not self.item_id.strip():
            raise ValueError("opaque replay item requires item_id")
        if not isinstance(self.payload, bytes):
            raise TypeError("opaque replay payload must be bytes")


class ReplayStateMismatchError(ValueError):
    """Raised before send when opaque state belongs to another route."""


@dataclass(frozen=True)
class ProviderReplayState:
    issuer: str
    provider_id: str
    endpoint_fingerprint: str
    model_id: str
    wire_protocol: WireProtocol
    opaque_items: tuple[OpaqueReplayItem, ...] = field(repr=False)
    response_id: str = field(default="", repr=False)
    pending_call_ids: tuple[str, ...] = field(default=(), repr=False)
    byte_size: int = field(init=False)

    def __post_init__(self) -> None:
        required = (self.issuer, self.provider_id, self.endpoint_fingerprint, self.model_id)
        if any(not str(value).strip() for value in required):
            raise ValueError("provider replay identity fields must be non-empty")
        items = tuple(self.opaque_items)
        if len(items) > MAX_REPLAY_ITEMS:
            raise ValueError("provider replay item limit exceeded")
        byte_size = sum(len(item.payload) for item in items)
        if byte_size > MAX_REPLAY_BYTES:
            raise ValueError("provider replay byte limit exceeded")
        response_id = str(self.response_id or "").strip()
        if len(response_id.encode("utf-8")) > 1024:
            raise ValueError("provider replay response id limit exceeded")
        pending_call_ids = tuple(str(item or "").strip() for item in self.pending_call_ids)
        if any(not item for item in pending_call_ids):
            raise ValueError("provider replay pending call ids must be non-empty")
        if len(set(pending_call_ids)) != len(pending_call_ids):
            raise ValueError("provider replay pending call ids must be unique")
        if len(pending_call_ids) > MAX_REPLAY_ITEMS:
            raise ValueError("provider replay pending call id limit exceeded")
        if any(len(item.encode("utf-8")) > 1024 for item in pending_call_ids):
            raise ValueError("provider replay pending call id byte limit exceeded")
        object.__setattr__(self, "opaque_items", items)
        object.__setattr__(self, "response_id", response_id)
        object.__setattr__(self, "pending_call_ids", pending_call_ids)
        object.__setattr__(self, "byte_size", byte_size)

    def require_compatible(
        self,
        *,
        issuer: str,
        provider_id: str,
        endpoint_fingerprint: str,
        model_id: str,
        wire_protocol: WireProtocol,
    ) -> ProviderReplayState:
        expected = {
            "issuer": str(issuer),
            "provider_id": str(provider_id),
            "endpoint_fingerprint": str(endpoint_fingerprint),
            "model_id": str(model_id),
            "wire_protocol": wire_protocol,
        }
        for field_name, value in expected.items():
            if getattr(self, field_name) != value:
                raise ReplayStateMismatchError(f"provider replay route identity mismatch: {field_name}")
        return self

    def without_response_id(self) -> ProviderReplayState:
        return ProviderReplayState(
            issuer=self.issuer,
            provider_id=self.provider_id,
            endpoint_fingerprint=self.endpoint_fingerprint,
            model_id=self.model_id,
            wire_protocol=self.wire_protocol,
            opaque_items=self.opaque_items,
            response_id="",
            pending_call_ids=(),
        )

    def without_opaque_items(self) -> ProviderReplayState:
        return ProviderReplayState(
            issuer=self.issuer,
            provider_id=self.provider_id,
            endpoint_fingerprint=self.endpoint_fingerprint,
            model_id=self.model_id,
            wire_protocol=self.wire_protocol,
            opaque_items=(),
            response_id=self.response_id,
            pending_call_ids=self.pending_call_ids,
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "issuer": self.issuer,
            "providerId": self.provider_id,
            "endpointFingerprint": self.endpoint_fingerprint,
            "modelId": self.model_id,
            "wireProtocol": self.wire_protocol.value,
            "itemCount": len(self.opaque_items),
            "byteSize": self.byte_size,
            "hasResponseId": bool(self.response_id),
            "pendingCallCount": len(self.pending_call_ids),
        }
