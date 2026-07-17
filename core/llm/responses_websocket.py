"""Session-scoped OpenAI Responses WebSocket transport.

The canonical request remains an HTTP-safe full Responses payload.  A private
transport sidecar may carry a WebSocket-only ``previous_response_id`` and
incremental input.  This lets connection setup fall back to HTTP without
dropping conversation history.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Iterator
from urllib.parse import urlsplit


RESPONSES_WEBSOCKET_TRANSPORT_KEY = "_vibelution_responses_websocket"
RESPONSES_WEBSOCKET_BETA = "responses_websockets=2026-02-06"
_TERMINAL_EVENT_TYPES = {
    "error",
    "response.cancelled",
    "response.canceled",
    "response.completed",
    "response.failed",
    "response.incomplete",
}


def _responses_service_root(value: Any) -> str:
    endpoint = str(value or "").strip().rstrip("/")
    if endpoint.lower().endswith("/responses"):
        return endpoint[: -len("/responses")]
    return endpoint


def _provider_model_name(value: Any) -> str:
    model = str(value or "").strip()
    if model.lower().startswith("openai/"):
        return model.split("/", 1)[1]
    return model


def _clean_http_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(payload)
    clean.pop(RESPONSES_WEBSOCKET_TRANSPORT_KEY, None)
    return clean


def _websocket_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean = _clean_http_payload(payload)
    options = payload.get(RESPONSES_WEBSOCKET_TRANSPORT_KEY)
    if isinstance(options, dict):
        previous_response_id = str(options.get("previous_response_id") or "").strip()
        incremental_input = options.get("input")
        if previous_response_id and isinstance(incremental_input, list):
            clean["previous_response_id"] = previous_response_id
            clean["input"] = incremental_input
    clean["model"] = _provider_model_name(clean.get("model"))
    for key in ("api_key", "base_url", "extra_headers", "timeout"):
        clean.pop(key, None)
    return clean


def _websocket_close_code(exc: Exception) -> int | None:
    raw_code = getattr(exc, "code", None)
    if raw_code is None:
        raw_code = getattr(getattr(exc, "rcvd", None), "code", None)
    try:
        return int(raw_code) if raw_code is not None else None
    except (TypeError, ValueError):
        return None


class ResponsesWebSocketBackend:
    """Callable backend compatible with ``LLMClient``'s synchronous stream path."""

    def __init__(
        self,
        http_backend: Callable[[Dict[str, Any]], Any],
        *,
        state_sink: Callable[[str, Dict[str, Any]], None] | None = None,
    ) -> None:
        self._http_backend = http_backend
        self._state_sink = state_sink
        self._lock = threading.RLock()
        self._manager: Any = None
        self._connection: Any = None
        self._identity: tuple[str, str, tuple[tuple[str, str], ...]] | None = None
        self._disabled = False

    def _emit(self, state: str, **fields: Any) -> None:
        if self._state_sink is not None:
            self._state_sink(state, dict(fields))

    @staticmethod
    def _identity_for(payload: Dict[str, Any]) -> tuple[str, str, tuple[tuple[str, str], ...]]:
        service_root = _responses_service_root(payload.get("base_url"))
        api_key = str(payload.get("api_key") or "")
        headers = payload.get("extra_headers")
        header_items = tuple(
            sorted(
                (str(key), str(value))
                for key, value in (headers.items() if isinstance(headers, dict) else ())
            )
        )
        return service_root, api_key, header_items

    def _close_locked(self) -> None:
        manager = self._manager
        self._manager = None
        self._connection = None
        self._identity = None
        if manager is None:
            return
        try:
            manager.__exit__(None, None, None)
        except Exception:
            pass

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _connect_locked(self, payload: Dict[str, Any]) -> tuple[Any, bool]:
        identity = self._identity_for(payload)
        if self._connection is not None and self._identity == identity:
            return self._connection, True
        self._close_locked()

        from openai import OpenAI

        service_root, api_key, header_items = identity
        default_headers = dict(header_items)
        client_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": service_root,
        }
        if default_headers:
            client_kwargs["default_headers"] = default_headers
        if payload.get("timeout") is not None:
            client_kwargs["timeout"] = payload["timeout"]
        client = OpenAI(**client_kwargs)
        manager = client.responses.connect(
            extra_headers={"OpenAI-Beta": RESPONSES_WEBSOCKET_BETA},
            max_retries=0,
        )
        connection = manager.enter()
        self._manager = manager
        self._connection = connection
        self._identity = identity
        self._emit(
            "connected",
            baseUrlHost=urlsplit(service_root).hostname or "",
            connectionReused=False,
        )
        return connection, False

    def __call__(self, payload: Dict[str, Any]) -> Any:
        options = payload.get(RESPONSES_WEBSOCKET_TRANSPORT_KEY)
        if (
            self._disabled
            or not isinstance(options, dict)
            or not bool(options.get("enabled"))
            or not bool(payload.get("stream"))
        ):
            return self._http_backend(_clean_http_payload(payload))

        def events() -> Iterator[Any]:
            with self._lock:
                try:
                    connection, reused = self._connect_locked(payload)
                except Exception as exc:
                    self._disabled = True
                    self._close_locked()
                    self._emit(
                        "fallback",
                        reasonType=type(exc).__name__,
                        fallbackTransport="http",
                    )
                    yield from self._http_backend(_clean_http_payload(payload))
                    return

                if reused:
                    self._emit("reused", connectionReused=True)
                emitted = False
                try:
                    connection.response.create(**_websocket_payload(payload))
                    while True:
                        event = connection.recv()
                        emitted = True
                        yield event
                        if str(getattr(event, "type", "") or "") in _TERMINAL_EVENT_TYPES:
                            return
                except Exception as exc:
                    self._close_locked()
                    close_code = _websocket_close_code(exc)
                    if not emitted and close_code == 1013:
                        self._disabled = True
                        self._emit(
                            "fallback",
                            reasonType=type(exc).__name__,
                            closeCode=close_code,
                            fallbackTransport="http",
                        )
                        yield from self._http_backend(_clean_http_payload(payload))
                        return
                    self._emit("disconnected", connectionReused=reused)
                    raise

        return events()


__all__ = [
    "RESPONSES_WEBSOCKET_BETA",
    "RESPONSES_WEBSOCKET_TRANSPORT_KEY",
    "ResponsesWebSocketBackend",
]
