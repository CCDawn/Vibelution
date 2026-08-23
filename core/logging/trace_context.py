"""Small W3C-compatible correlation context for backend diagnostics."""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

_TRACEPARENT_RE = re.compile(
    r"^(?P<version>[0-9a-f]{2})-"
    r"(?P<trace_id>[0-9a-f]{32})-"
    r"(?P<parent_span_id>[0-9a-f]{16})-"
    r"(?P<trace_flags>[0-9a-f]{2})$"
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_CURRENT_TRACE_CONTEXT: ContextVar[TraceContext | None] = ContextVar(
    "vibelution_trace_context",
    default=None,
)


@dataclass(frozen=True, slots=True)
class ParsedTraceparent:
    trace_id: str
    parent_span_id: str
    trace_flags: str


@dataclass(frozen=True, slots=True)
class TraceContext:
    trace_id: str
    span_id: str
    request_id: str
    parent_span_id: str | None = None
    trace_flags: str = "01"

    def to_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    def to_carrier(self) -> dict[str, str]:
        """Serialize only the bounded fields needed across a worker boundary."""
        carrier = {
            "traceparent": self.to_traceparent(),
            "requestId": self.request_id,
        }
        if self.parent_span_id:
            carrier["parentSpanId"] = self.parent_span_id
        return carrier

    @classmethod
    def from_carrier(cls, carrier: object) -> TraceContext | None:
        """Restore a context previously produced by :meth:`to_carrier`."""
        if not isinstance(carrier, Mapping):
            return None
        parsed = parse_traceparent(carrier.get("traceparent"))
        if parsed is None:
            return None
        parent_span_id = str(carrier.get("parentSpanId") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{16}", parent_span_id) or parent_span_id == "0" * 16:
            parent_span_id = ""
        return cls(
            trace_id=parsed.trace_id,
            span_id=parsed.parent_span_id,
            request_id=_request_id_or_new(carrier.get("requestId")),
            parent_span_id=parent_span_id or None,
            trace_flags=parsed.trace_flags,
        )

    def child_span(self, *, request_id: object = None) -> TraceContext:
        """Create a same-trace child span without mutating this context."""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=_new_nonzero_hex(8),
            request_id=(
                self.request_id
                if request_id is None
                else _request_id_or_new(request_id)
            ),
            parent_span_id=self.span_id,
            trace_flags=self.trace_flags,
        )

    def to_fields(self) -> dict[str, str]:
        fields = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "requestId": self.request_id,
        }
        if self.parent_span_id:
            fields["parentSpanId"] = self.parent_span_id
        return fields


def parse_traceparent(value: object) -> ParsedTraceparent | None:
    """Parse one strict traceparent header; malformed/all-zero ids are rejected."""
    header = str(value or "").strip()
    match = _TRACEPARENT_RE.fullmatch(header)
    if match is None or match.group("version") == "ff":
        return None
    if match.group("version") == "00" and header.count("-") != 3:
        return None
    trace_id = match.group("trace_id")
    parent_span_id = match.group("parent_span_id")
    if trace_id == "0" * 32 or parent_span_id == "0" * 16:
        return None
    return ParsedTraceparent(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        trace_flags=match.group("trace_flags"),
    )


def _new_nonzero_hex(byte_count: int) -> str:
    width = byte_count * 2
    while True:
        value = secrets.token_hex(byte_count)
        if value != "0" * width:
            return value


def _request_id_or_new(value: object) -> str:
    candidate = str(value or "").strip()
    if _REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return _new_nonzero_hex(16)


def new_trace_context(
    *,
    traceparent: object = "",
    request_id: object = "",
) -> TraceContext:
    """Create a server span linked to a valid inbound traceparent when present."""
    parsed = parse_traceparent(traceparent)
    return TraceContext(
        trace_id=parsed.trace_id if parsed else _new_nonzero_hex(16),
        span_id=_new_nonzero_hex(8),
        parent_span_id=parsed.parent_span_id if parsed else None,
        trace_flags=parsed.trace_flags if parsed else "01",
        request_id=_request_id_or_new(request_id),
    )


@contextmanager
def bind_trace_context(context: TraceContext) -> Iterator[TraceContext]:
    token = _CURRENT_TRACE_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_TRACE_CONTEXT.reset(token)


def get_current_trace_context() -> TraceContext | None:
    return _CURRENT_TRACE_CONTEXT.get()


def current_trace_fields() -> dict[str, str]:
    context = get_current_trace_context()
    return context.to_fields() if context is not None else {}


def merge_current_trace_fields(fields: Mapping[str, Any] | None) -> dict[str, Any]:
    """Merge scoped correlation into event fields while preserving explicit values."""
    merged: dict[str, Any] = current_trace_fields()
    if isinstance(fields, Mapping):
        merged.update(fields)
    return merged


__all__ = [
    "ParsedTraceparent",
    "TraceContext",
    "bind_trace_context",
    "current_trace_fields",
    "get_current_trace_context",
    "merge_current_trace_fields",
    "new_trace_context",
    "parse_traceparent",
]
