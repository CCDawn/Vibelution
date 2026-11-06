"""Native subscription transport inside the existing LLM invocation pipeline.

Only this transport owns HTTP. Session state and tool execution remain with
Vibelution; synchronous callers collect the same required SSE terminal event.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from ..errors import LLMError
from .wire import sanitize_subscription_payload, subscription_error_from_event

_API_BASE = "https://api.openai.com/v1"
_TRANSPORT_KEYS = frozenset({"api_key", "base_url", "timeout", "extra_headers", "client", "ssl_verify",
                             "_subscription_collect_response"})
_MAX_EVENT_BYTES = 16 * 1024 * 1024


def prepare_subscription_runtime_payload(payload: dict[str, Any], *, collect_response: bool | None = None) -> dict[str, Any]:
    """Sanitize after generic composition; transport values never enter JSON."""
    transport = {key: value for key, value in payload.items() if key in _TRANSPORT_KEYS}
    body = {key: value for key, value in payload.items() if key not in _TRANSPORT_KEYS}
    try:
        prepared = sanitize_subscription_payload(body)
    except (TypeError, ValueError):
        raise LLMError("capability_error", "此次请求包含 ChatGPT 订阅不支持的内容或参数。", retryable=False) from None
    if collect_response is not None:
        transport["_subscription_collect_response"] = collect_response
    return {**prepared, **transport}


def call_subscription_responses(
    payload: dict[str, Any], *, client_factory: Callable[..., Any],
    check_cancelled: Callable[[], None] = lambda: None,
    auth_rejected: Callable[[str], None] | None = None,
) -> Any:
    endpoint = str(payload.get("base_url") or "")
    if endpoint not in {_API_BASE, _API_BASE + "/responses"}:
        raise LLMError("configuration_error", "ChatGPT 订阅只允许使用官方 Responses 地址。", retryable=False)
    token = str(payload.get("api_key") or "")
    if not token:
        raise LLMError("auth_error", "请先连接 ChatGPT 并授权使用套餐额度。", retryable=False)
    prepared = prepare_subscription_runtime_payload(payload)
    body = {key: value for key, value in prepared.items() if key not in _TRANSPORT_KEYS}
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "Vibelution"}
    extras = payload.get("extra_headers") or {}
    forbidden_headers = {"authorization", "proxy-authorization", "cookie", "set-cookie", "host", "api-key", "x-api-key", "x-goog-api-key"}
    if not isinstance(extras, dict) or any(
        str(key).lower().replace("_", "-") in forbidden_headers
        or any(part in str(key).lower() for part in ("token", "secret", "credential", "password"))
        for key in extras
    ):
        raise LLMError("configuration_error", "ChatGPT 订阅请求不能覆盖身份或目标请求头。", retryable=False)
    headers.update({str(key): str(value) for key, value in extras.items()})

    def events() -> Iterator[dict[str, Any]]:
        check_cancelled()
        client = payload.get("client")
        owns_client = client is None
        if owns_client:
            client = client_factory(timeout=payload.get("timeout"), verify=True)
        terminal = False
        emitted_output = False
        try:
            with client.stream("POST", _API_BASE + "/responses", headers=headers, json=body, follow_redirects=False) as response:
                if response.status_code != 200:
                    if response.status_code == 401 and auth_rejected is not None:
                        auth_rejected(token)
                    # Error responses are bounded and discarded after extracting
                    # an allowlisted code. Provider messages never enter logs.
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        if len(content) + len(chunk) > 64 * 1024:
                            break
                        content.extend(chunk)
                    try:
                        error_body = json.loads(content) if content else {}
                    except (ValueError, TypeError):
                        error_body = {}
                    error = subscription_error_from_event(error_body, status_code=response.status_code)
                    if error is not None:
                        raise error
                    raise LLMError("provider_protocol_error", "ChatGPT 订阅请求未成功。", retryable=False)
                data: list[str] = []
                size = 0
                for line in response.iter_lines():
                    check_cancelled()
                    if line.startswith("data:"):
                        value = line[5:].lstrip(" ")
                        size += len(value.encode("utf-8"))
                        if size > _MAX_EVENT_BYTES:
                            raise LLMError("provider_protocol_error", "ChatGPT 返回的数据超过单个事件上限。", retryable=False)
                        data.append(value)
                    elif line == "" and data:
                        text = "\n".join(data)
                        data, size = [], 0
                        if text == "[DONE]":
                            continue
                        try:
                            event = json.loads(text)
                        except ValueError:
                            raise LLMError("provider_protocol_error", "ChatGPT 返回了无效的流事件。", retryable=False) from None
                        if not isinstance(event, dict):
                            raise LLMError("provider_protocol_error", "ChatGPT 返回了无效的流事件。", retryable=False)
                        error = subscription_error_from_event(event)
                        if error is not None:
                            if emitted_output and error.retryable:
                                error = LLMError(error.category, str(error), retryable=False,
                                                 details={**error.details, "partialOutputPreserved": True})
                            raise error
                        event_type = str(event.get("type") or "")
                        if event_type.startswith(("response.output_", "response.reasoning_", "response.function_call_arguments.")):
                            emitted_output = True
                        if event.get("type") == "response.completed":
                            result = event.get("response")
                            if not isinstance(result, dict) or result.get("status") != "completed":
                                raise LLMError("provider_protocol_error", "ChatGPT 响应未完整完成。", retryable=False)
                            terminal = True
                        yield event
                        if terminal:
                            return
                if not terminal:
                    raise LLMError("network_error", "ChatGPT 连接在回复完成前中断，已保留收到的内容。", retryable=False)
        except httpx.TimeoutException:
            raise LLMError("timeout", "ChatGPT 请求超时，请稍后重试。", retryable=False) from None
        except httpx.RequestError:
            raise LLMError("network_error", "无法连接 ChatGPT，已保留收到的内容。", retryable=False) from None
        finally:
            if owns_client:
                client.close()

    stream = events()
    if not payload.get("_subscription_collect_response"):
        return stream
    try:
        for event in stream:
            if event.get("type") == "response.completed":
                return event["response"]
    finally:
        stream.close()
    raise LLMError("provider_protocol_error", "ChatGPT 回复未完整完成。", retryable=False)
