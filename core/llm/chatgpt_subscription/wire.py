"""Stateless ChatGPT-plan Responses boundary; ordinary API adapters stay unchanged.

Protocol: https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from types import SimpleNamespace
from typing import Any

from ..semantic_messages import InvocationScope, SemanticModelRequest
from ..types import LLMError, TurnOutcome
from ..wire.responses import ResponsesDecodedStream, ResponsesWireAdapter
from ..wire.types import BuiltPayload

SUBSCRIPTION_API_BASE = "https://api.openai.com/v1"
SUBSCRIPTION_TOOL_NAMESPACE = "functions"
UNSUPPORTED_SUBSCRIPTION_FIELDS = frozenset({
    "background", "conversation", "max_output_tokens", "max_tool_calls", "metadata",
    "moderation", "multi_agent", "prompt", "prompt_cache_retention", "safety_identifier",
    "temperature", "top_logprobs", "top_p", "truncation", "user", "previous_response_id",
    "stream_options", "_vibelution_responses_websocket",
})
_BODY_FIELDS = frozenset({
    "model", "input", "instructions", "store", "stream", "tools", "tool_choice",
    "parallel_tool_calls", "reasoning", "include", "text", "prompt_cache_key",
})
_ERROR_POLICIES = {
    "subscription_sharing_usage_limit_exceeded": ("quota_error", False, "ChatGPT 用量已达到当前限制，请查看 ChatGPT 设置中的用量。"),
    "subscription_sharing_usage_unavailable": ("server_error", True, "暂时无法检查 ChatGPT 用量，请稍后重试。"),
    "subscription_sharing_user_unavailable": ("server_error", True, "ChatGPT 用户或工作区信息暂时不可用。"),
    "subscription_sharing_user_not_eligible": ("auth_error", False, "当前 ChatGPT 账号或工作区不允许使用订阅推理。"),
    "subscription_sharing_invalid_user": ("auth_error", False, "ChatGPT 订阅身份验证失败，请检查所选账号。"),
    "subscription_sharing_unsupported_capability": ("capability_error", False, "ChatGPT 订阅不支持此次请求的功能。"),
    "subscription_sharing_route_not_supported": ("configuration_error", False, "ChatGPT 订阅不支持此次请求的接口。"),
    "chatpass_v2_scope_not_authorized": ("auth_error", False, "当前 ChatGPT 授权不允许此次操作。"),
    "chatpass_v2_invalid_authorization_context": ("auth_error", False, "当前 ChatGPT 授权上下文无效。"),
}
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_.:\[\]-]{1,160}\Z")


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy_json(item) for item in value]
    return value


def _object(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return _copy_json(value) if isinstance(value, Mapping) else {}


def _local_tool(tool: Any) -> dict[str, Any]:
    item = _object(tool)
    if item.get("type") not in {"function", "custom"} or not str(item.get("name") or "").strip():
        raise ValueError("ChatGPT subscription requires local function/custom tools")
    if item.get("defer_loading") or any(caller != "direct" for caller in item.get("allowed_callers") or []):
        raise ValueError("ChatGPT subscription does not support deferred or programmatic tool execution")
    return item


def _namespace_tools(tools: Any) -> list[dict[str, Any]]:
    if not isinstance(tools, (list, tuple)):
        raise ValueError("ChatGPT subscription tools must be an array")  # noqa: TRY004 - payload validation contract
    local: list[dict[str, Any]] = []
    for raw in tools:
        item = _object(raw)
        if item.get("type") == "namespace":
            if item.get("name") != SUBSCRIPTION_TOOL_NAMESPACE:
                raise ValueError("ChatGPT subscription tool namespace does not match local tools")
            nested = item.get("tools")
            if not isinstance(nested, list):
                raise ValueError("ChatGPT subscription namespace tools must be an array")
            local.extend(_local_tool(tool) for tool in nested)
        else:
            local.append(_local_tool(item))
    names = [item["name"] for item in local]
    if len(names) != len(set(names)):
        raise ValueError("ChatGPT subscription tool names must be unique")
    return [{
        "type": "namespace", "name": SUBSCRIPTION_TOOL_NAMESPACE,
        "description": "Tools executed by the local Vibelution harness.", "tools": local,
    }] if local else []


def _tool_call(item: dict[str, Any], *, outbound: bool) -> dict[str, Any]:
    namespace = item.get("namespace")
    if namespace not in (None, "", SUBSCRIPTION_TOOL_NAMESPACE):
        raise ValueError("ChatGPT subscription tool call namespace does not match local tools")
    if outbound:
        item["namespace"] = SUBSCRIPTION_TOOL_NAMESPACE
    else:
        item.pop("namespace", None)
    return item


def _input_item(raw: Any) -> dict[str, Any]:
    item = _object(raw)
    if not item:
        raise ValueError("ChatGPT subscription input items must be objects")
    kind = item.get("type")
    if kind in (None, "message"):
        if item.get("role") == "system":
            item["role"] = "developer"
        if item.get("role") not in {"developer", "user", "assistant"}:
            raise ValueError("ChatGPT subscription input message role is unsupported")
        content = item.get("content")
        if isinstance(content, list):
            allowed = {"input_text", "input_image", "input_file", "output_text", "refusal"}
            if any(not isinstance(block, Mapping) or block.get("type") not in allowed for block in content):
                raise ValueError("ChatGPT subscription message content type is unsupported")
        elif not isinstance(content, str):
            raise ValueError("ChatGPT subscription message content must be text or an array")
    elif kind in {"function_call", "custom_tool_call"}:
        _tool_call(item, outbound=True)
    elif kind == "additional_tools":
        item["tools"] = _namespace_tools(item.get("tools"))
    elif kind not in {"reasoning", "function_call_output", "custom_tool_call_output"}:
        raise ValueError("ChatGPT subscription input item type is unsupported")
    return item


def sanitize_subscription_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON body only; transport credentials/options must be split first.

    Idempotent, nonmutating and deliberately rejects unknown body keys. This must
    run after generic sampling/cache/budget composition, before native HTTP send.
    It cannot restore history removed by an earlier continuation encoder.
    """
    unknown = set(payload) - _BODY_FIELDS - UNSUPPORTED_SUBSCRIPTION_FIELDS
    if unknown:
        raise ValueError("ChatGPT subscription payload contains unsupported body or transport fields")
    body = {key: _copy_json(value) for key, value in payload.items() if key in _BODY_FIELDS}
    raw_input = body.get("input")
    if isinstance(raw_input, str):
        raw_input = [{"role": "user", "content": raw_input}]
    if not isinstance(raw_input, list):
        raise ValueError("ChatGPT subscription input must be an array containing full history")  # noqa: TRY004 - payload validation contract
    body["input"] = [_input_item(item) for item in raw_input]
    body.update(store=False, stream=True)
    if "tools" in body:
        body["tools"] = _namespace_tools(body["tools"])
    choice = body.get("tool_choice")
    if choice is not None and (not isinstance(choice, str) or choice not in {"auto", "none", "required"}):
        raise ValueError("ChatGPT subscription tool choice is unsupported")
    return body


def subscription_error_from_event(
    event: Any, *, status_code: int | None = None, request_id: str = "",
) -> LLMError | None:
    """Classify structured terminal/HTTP errors without retaining provider text."""
    raw = _object(event)
    response = _object(raw.get("response"))
    error = _object(response.get("error")) or _object(raw.get("error"))
    event_type = str(getattr(raw.get("type"), "value", raw.get("type")) or "")
    failed = event_type in {"response.failed", "response.error", "error"} or response.get("status") == "failed"
    if not error and not failed and not (status_code is not None and status_code >= 400):
        return None
    code = str(error.get("code") or raw.get("code") or "")
    code = code if _SAFE_TOKEN.fullmatch(code) else ""
    category, retryable, message = _ERROR_POLICIES.get(
        code, ("provider_protocol_error", False, "ChatGPT 订阅请求失败。"),
    )
    if not code and status_code is not None:
        if status_code in {401, 403}:
            category, message = "auth_error", "ChatGPT 订阅身份或权限验证失败。"
        elif status_code in {429}:
            category, message = "quota_error", "ChatGPT 订阅请求受用量限制。"
        elif status_code >= 500:
            category, retryable, message = "server_error", True, "ChatGPT 订阅服务暂时不可用。"
    details: dict[str, Any] = {"billingPath": "chatgpt_subscription"}
    if code:
        details["providerErrorCode"] = code
        message = f"{message} ({code})"
    param = str(error.get("param") or "")
    if _SAFE_TOKEN.fullmatch(param):
        details["providerErrorParam"] = param
    if status_code is not None:
        details["httpStatus"] = status_code
    if _SAFE_TOKEN.fullmatch(request_id):
        details["requestId"] = request_id
    return LLMError(category, message, retryable=retryable, details=details)


def normalize_subscription_event(event: Any) -> dict[str, Any]:
    """Project the fixed local namespace onto the existing canonical decoder."""
    raw = _object(event)
    event_type = raw.get("type")
    raw["type"] = str(getattr(event_type, "value", event_type) or "")
    for key in ("item",):
        item = _object(raw.get(key))
        if item.get("type") in {"function_call", "custom_tool_call"}:
            raw[key] = _tool_call(item, outbound=False)
    response = _object(raw.get("response"))
    if response:
        if isinstance(response.get("output"), list):
            response["output"] = [
                _tool_call(_object(item), outbound=False)
                if _object(item).get("type") in {"function_call", "custom_tool_call"}
                else item for item in response["output"]
            ]
        raw["response"] = response
    if raw["type"] == "response.done":
        raw["type"] = "response.incomplete"
        response["status"] = "incomplete"
        response["incomplete_details"] = {"reason": "subscription_missing_response_completed"}
        raw["response"] = response
    error = subscription_error_from_event(raw)
    if error is not None:
        safe_error = {"message": str(error)}
        if "providerErrorCode" in error.details:
            safe_error["code"] = error.details["providerErrorCode"]
        if "providerErrorParam" in error.details:
            safe_error["param"] = error.details["providerErrorParam"]
        if response:
            response["error"] = safe_error
            response.pop("status_details", None)
        if "error" in raw or not response:
            raw["error"] = safe_error
        raw.pop("message", None)
    return raw


class ChatGPTSubscriptionWireAdapter(ResponsesWireAdapter):
    """Reuse canonical Responses with a distinct, stateless replay issuer."""

    adapter_id = "chatgpt_subscription_responses"

    def encode_request(self, request: SemanticModelRequest, *, route: Any) -> BuiltPayload:
        if str(getattr(route, "runtime_endpoint", "")) not in {
            SUBSCRIPTION_API_BASE, SUBSCRIPTION_API_BASE + "/responses",
        }:
            raise ValueError("ChatGPT subscription requires the public OpenAI Responses origin")
        stateless_route = SimpleNamespace(
            provider_id=route.provider_id, model_id=route.model_id,
            effective_model=route.effective_model, runtime_endpoint=route.runtime_endpoint,
            compat=SimpleNamespace(responses_continuation=False, responses_websocket=False),
        )
        encoded = super().encode_request(request, route=stateless_route)
        body = sanitize_subscription_payload(encoded.body)
        # Stateless reasoning history requires the encrypted provider replay item.
        body["include"] = ["reasoning.encrypted_content"]
        return BuiltPayload(body=body, endpoint=encoded.endpoint, headers=encoded.headers)

    def decode_stream(
        self, events: Iterable[Any], *, route: Any, scope: InvocationScope,
    ) -> ResponsesDecodedStream:
        return super().decode_stream(
            (normalize_subscription_event(event) for event in events), route=route, scope=scope,
        )

    def decode_response(self, response: Any, *, route: Any, scope: InvocationScope) -> TurnOutcome:
        raw = _object(normalize_subscription_event({"response": response}).get("response"))
        if not raw.get("status"):
            raw["status"] = "incomplete"
            raw["incomplete_details"] = {"reason": "subscription_missing_response_completed"}
        return super().decode_response(raw, route=route, scope=scope)
