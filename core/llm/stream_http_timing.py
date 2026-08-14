# -*- coding: utf-8 -*-
"""Observe HTTP milestones for the active LLM stream without logging payloads.

LiteLLM owns the httpx client, so the hook is installed once on httpx transports
and becomes active only while ``capture_stream_http_timings`` is in scope.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

_STREAM_HTTP_TIMINGS: ContextVar["StreamHttpTimings | None"] = ContextVar(
    "vibelution_stream_http_timings",
    default=None,
)
_PATCH_LOCK = threading.Lock()
_PATCHED = False
_ORIGINAL_SYNC_HANDLE_REQUEST: Callable[..., Any] | None = None
_ORIGINAL_ASYNC_HANDLE_REQUEST: Callable[..., Any] | None = None


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else {}
    if value is not None and hasattr(value, "__dict__"):
        return dict(getattr(value, "__dict__", {}) or {})
    return {}


def _normalize_host(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    return str(value or "").strip().lower().rstrip(".").strip("[]")


def classify_raw_stream_event(raw: Any) -> str:
    """Classify the first provider object without copying response content."""

    data = _coerce_dict(raw)
    if not data:
        return "empty"
    event_type = str(data.get("type") or "").strip()
    if event_type:
        return event_type[:48]
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "object"
    choice = _coerce_dict(choices[0])
    delta = _coerce_dict(choice.get("delta"))
    if delta.get("reasoning_content") or delta.get("reasoning"):
        return "reasoning"
    content = delta.get("content")
    if isinstance(content, str) and content:
        return "content"
    if delta.get("tool_calls"):
        return "tool_call"
    role = str(delta.get("role") or "").strip()
    if role:
        return "role"
    if not delta:
        return "empty_delta"
    return "delta"


@dataclass
class StreamHttpTimings:
    started_at: float = field(default_factory=time.perf_counter)
    connect_started_ms: int | None = None
    connect_ms: int | None = None
    tls_ms: int | None = None
    request_headers_sent_ms: int | None = None
    request_body_sent_ms: int | None = None
    http_headers_ms: int | None = None
    first_raw_event_ms: int | None = None
    first_projected_chunk_ms: int | None = None
    http_status: int | None = None
    via_proxy: bool | None = None
    origin_host: str = ""
    expected_origin_host: str = ""
    connect_host: str = ""
    proxy_host: str = ""
    first_raw_event_kind: str = ""
    header_receive_count: int = 0
    headers_emitted: bool = False
    summary_emitted: bool = False
    on_http_headers: Callable[["StreamHttpTimings"], None] | None = None

    def elapsed_ms(self) -> int:
        return _elapsed_ms(self.started_at)

    def tracks_request(self, request: Any) -> bool:
        expected = _normalize_host(self.expected_origin_host)
        return not expected or _request_host(request) == expected

    def note_request(self, request: Any) -> None:
        host = _request_host(request)
        if host:
            self.origin_host = host

    def observe_trace(self, name: str, info: dict[str, Any] | None) -> None:
        event_name = str(name or "")
        payload = info if isinstance(info, dict) else {}
        now = self.elapsed_ms()
        if event_name.endswith("connect_tcp.started"):
            if self.connect_started_ms is None:
                self.connect_started_ms = now
            connect_host = _normalize_host(payload.get("host"))
            if connect_host:
                self.connect_host = connect_host
                origin_host = _normalize_host(self.origin_host or self.expected_origin_host)
                if origin_host:
                    self.via_proxy = connect_host != origin_host
                    self.proxy_host = connect_host if self.via_proxy else ""
            return
        if event_name.endswith("connect_tcp.complete") and self.connect_ms is None:
            self.connect_ms = now
            return
        if event_name.endswith("start_tls.complete") and self.tls_ms is None:
            self.tls_ms = now
            return
        if event_name.endswith("send_request_headers.complete"):
            self.request_headers_sent_ms = now
            return
        if event_name.endswith("send_request_body.complete"):
            self.request_body_sent_ms = now
            return
        if event_name.endswith("receive_response_headers.complete"):
            self.header_receive_count += 1
            self.http_headers_ms = now
            status = _status_from_trace_info(payload)
            if status is not None:
                self.http_status = status

    def mark_http_response(self, status_code: Any) -> None:
        if self.http_headers_ms is None:
            self.http_headers_ms = self.elapsed_ms()
        if self.http_status is None:
            try:
                self.http_status = int(status_code)
            except (TypeError, ValueError):
                pass
        self.emit_headers_if_needed()

    def mark_first_raw_event(self, kind: str) -> None:
        if self.first_raw_event_ms is None:
            self.first_raw_event_ms = self.elapsed_ms()
            self.first_raw_event_kind = str(kind or "")[:48]

    def mark_first_projected_chunk(self) -> None:
        if self.first_projected_chunk_ms is None:
            self.first_projected_chunk_ms = self.elapsed_ms()

    def emit_headers_if_needed(self) -> None:
        if self.headers_emitted or self.on_http_headers is None:
            return
        self.headers_emitted = True
        try:
            self.on_http_headers(self)
        except Exception:
            return

    def headers_scene_fields(self) -> dict[str, Any]:
        return {
            "connectStartedMs": self.connect_started_ms,
            "connectMs": self.connect_ms,
            "tlsMs": self.tls_ms,
            "requestBodySentMs": self.request_body_sent_ms,
            "httpHeadersMs": self.http_headers_ms,
            "httpStatus": self.http_status,
            "viaProxy": self.via_proxy,
            "originHost": self.origin_host,
            "proxyHost": self.proxy_host,
            "headerReceiveCount": self.header_receive_count,
        }

    def summary_scene_fields(self) -> dict[str, Any]:
        return {
            **self.headers_scene_fields(),
            "firstRawEventMs": self.first_raw_event_ms,
            "firstProjectedChunkMs": self.first_projected_chunk_ms,
            "firstRawEventKind": self.first_raw_event_kind,
        }

    def first_chunk_scene_fields(self) -> dict[str, Any]:
        return {
            "connectStartedMs": self.connect_started_ms,
            "connectMs": self.connect_ms,
            "tlsMs": self.tls_ms,
            "requestBodySentMs": self.request_body_sent_ms,
            "httpHeadersMs": self.http_headers_ms,
            "firstRawEventMs": self.first_raw_event_ms,
        }


def _request_host(request: Any) -> str:
    try:
        return _normalize_host(getattr(getattr(request, "url", None), "host", ""))
    except Exception:
        return ""


def _status_from_trace_info(info: dict[str, Any]) -> int | None:
    value = info.get("return_value")
    if isinstance(value, tuple) and len(value) >= 2:
        try:
            return int(value[1])
        except (TypeError, ValueError):
            return None
    return None


def current_stream_http_timings() -> StreamHttpTimings | None:
    return _STREAM_HTTP_TIMINGS.get()


def install_httpx_stream_timing_hooks() -> None:
    global _PATCHED, _ORIGINAL_SYNC_HANDLE_REQUEST, _ORIGINAL_ASYNC_HANDLE_REQUEST
    with _PATCH_LOCK:
        if _PATCHED:
            return
        import httpx

        _ORIGINAL_SYNC_HANDLE_REQUEST = httpx.HTTPTransport.handle_request
        _ORIGINAL_ASYNC_HANDLE_REQUEST = httpx.AsyncHTTPTransport.handle_async_request
        httpx.HTTPTransport.handle_request = _timed_handle_request  # type: ignore[method-assign]
        httpx.AsyncHTTPTransport.handle_async_request = _timed_handle_async_request  # type: ignore[method-assign]
        _PATCHED = True


def _timed_handle_request(transport: Any, request: Any) -> Any:
    original = _ORIGINAL_SYNC_HANDLE_REQUEST
    if original is None:
        raise RuntimeError("httpx sync timing hook is not installed")
    timings = current_stream_http_timings()
    if timings is None or not timings.tracks_request(request):
        return original(transport, request)
    timings.note_request(request)
    _attach_sync_trace(request, timings)
    response = original(transport, request)
    timings.mark_http_response(getattr(response, "status_code", None))
    return response


async def _timed_handle_async_request(transport: Any, request: Any) -> Any:
    original = _ORIGINAL_ASYNC_HANDLE_REQUEST
    if original is None:
        raise RuntimeError("httpx async timing hook is not installed")
    timings = current_stream_http_timings()
    if timings is None or not timings.tracks_request(request):
        return await original(transport, request)
    timings.note_request(request)
    _attach_async_trace(request, timings)
    response = await original(transport, request)
    timings.mark_http_response(getattr(response, "status_code", None))
    return response


def _attach_sync_trace(request: Any, timings: StreamHttpTimings) -> None:
    extensions = getattr(request, "extensions", None)
    if not isinstance(extensions, dict):
        return
    existing = extensions.get("trace")

    def trace(name: str, info: dict[str, Any] | None) -> None:
        timings.observe_trace(name, info)
        if callable(existing):
            existing(name, info)

    extensions["trace"] = trace


def _attach_async_trace(request: Any, timings: StreamHttpTimings) -> None:
    extensions = getattr(request, "extensions", None)
    if not isinstance(extensions, dict):
        return
    existing = extensions.get("trace")

    async def trace(name: str, info: dict[str, Any] | None) -> None:
        timings.observe_trace(name, info)
        if callable(existing):
            result = existing(name, info)
            if hasattr(result, "__await__"):
                await result

    extensions["trace"] = trace


@contextmanager
def capture_stream_http_timings(
    *,
    on_http_headers: Callable[[StreamHttpTimings], None] | None = None,
    origin_host: str = "",
) -> Iterator[StreamHttpTimings]:
    install_httpx_stream_timing_hooks()
    timings = StreamHttpTimings(
        on_http_headers=on_http_headers,
        expected_origin_host=_normalize_host(origin_host),
    )
    token = _STREAM_HTTP_TIMINGS.set(timings)
    try:
        yield timings
    finally:
        _STREAM_HTTP_TIMINGS.reset(token)
