"""Session residual: failure signals, history/reply formatting, image retry, cache metadata.

Claim scope: provider/tool failure signals, visible reply/history helpers,
image-retry context cues, and prompt-cache composition metadata left on the
facade after earlier session packs.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
import re
import time
from pathlib import Path
from typing import Any, Mapping


def _service():
    from core.web.services import session_service

    return session_service


def _active_task_content_preview(active_task: Any) -> str:
    s = _service()
    task = s._normalize_session_active_task(active_task)
    if not isinstance(task, dict):
        return ""
    parts = [
        task.get("title"),
        task.get("goal"),
        task.get("latest_summary"),
        task.get("next_action"),
    ]
    return s._compact_preview_text(" | ".join(str(item or "") for item in parts if str(item or "").strip()), max_lines=1, max_chars=240)


def _annotate_continuation_result(
    result: Any,
    turn_count: int,
    *,
    reached_limit: bool,
) -> Any:
    s = _service()
    if not isinstance(result, dict):
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    metadata["continuation_turn_count"] = turn_count
    if reached_limit:
        metadata["continuation_limit_reached"] = True
    else:
        metadata.pop("continuation_limit_reached", None)
    result["metadata"] = metadata
    return result


def _attach_session_prompt_cache_metadata(
    result: Any,
    *,
    prompt_cache_scope: str,
    prompt_cache_partition: str,
    llm_model_id: str,
) -> Any:
    s = _service()
    if not isinstance(result, dict):
        return result
    metadata = dict(result.get("metadata") or {}) if isinstance(result.get("metadata"), dict) else {}
    metadata.setdefault("promptCacheScope", str(prompt_cache_scope or "").strip())
    metadata.setdefault("promptCachePartition", str(prompt_cache_partition or "").strip())
    metadata.setdefault("promptCachePartitionHash", s._short_hash(prompt_cache_partition))
    metadata.setdefault("promptCachePartitionChars", len(str(prompt_cache_partition or "").strip()))
    metadata.setdefault(
        "promptCacheSessionFallback",
        str(prompt_cache_scope or "").strip() == s.SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    )
    metadata.setdefault("llmModelId", str(llm_model_id or "").strip())
    result["metadata"] = metadata
    usage = result.get("llm_usage")
    if isinstance(usage, dict):
        usage.setdefault("promptCacheScope", metadata.get("promptCacheScope") or "")
        usage.setdefault("promptCachePartition", metadata.get("promptCachePartition") or "")
        usage.setdefault("llmModelId", metadata.get("llmModelId") or "")
    return result


def _build_followup_prompt(
    *,
    original_prompt: str,
    effective_prompt: str,
    latest_result: Any,
    history_messages: list[dict[str, Any]],
    turn_index: int,
    guidance_summaries: list[str] | None = None,
) -> str:
    s = _service()
    goal = s._unwrap_continuation_goal(effective_prompt or original_prompt)
    if s._is_continue_request(goal):
        goal = s._unwrap_continuation_goal(s._latest_effective_user_message(history_messages) or original_prompt)
    lines = [goal or str(original_prompt or "").strip() or "继续"]
    guidance_lines = [item for item in list(guidance_summaries or []) if str(item or "").strip()]
    if guidance_lines:
        lines.extend(str(item).strip() for item in guidance_lines[:3])
    return "\n".join(lines)


def _build_message_timeline_items(
    *,
    message_id: str,
    content: Any = "",
    feedback_events: Any = None,
    streaming: bool = False,
    include_assistant_text: bool = True,
    lang: str | None = None,
) -> list[dict[str, Any]]:
    s = _service()
    normalized_message_id = str(message_id or "").strip()
    if not normalized_message_id:
        return []
    normalized_feedback_events = s._normalize_message_feedback_events(feedback_events or [])
    if not normalized_feedback_events:
        return []
    return s.build_conversation_timeline_items(
        message_id=normalized_message_id,
        content=content,
        feedback_events=normalized_feedback_events,
        streaming=streaming,
        lang=str(lang or "").strip() or s.get_web_language(),
        include_assistant_text=include_assistant_text,
    )


def _cache_average_from_usage(cache_usage: dict[str, Any] | None) -> dict[str, int]:
    s = _service()
    if not isinstance(cache_usage, dict):
        return {
            "inputTokens": 0,
            "cachedInputTokens": 0,
            "observedTurnCount": 0,
        }
    input_tokens = s._coerce_nonnegative_int(
        cache_usage.get("totalInputTokens")
        or cache_usage.get("averageInputTokens")
        or 0
    )
    cached_tokens = min(
        s._coerce_nonnegative_int(
            cache_usage.get("totalCachedInputTokens")
            or cache_usage.get("averageCachedInputTokens")
            or 0
        ),
        input_tokens,
    ) if input_tokens else 0
    return {
        "inputTokens": input_tokens,
        "cachedInputTokens": cached_tokens,
        "observedTurnCount": s._coerce_nonnegative_int(
            cache_usage.get("totalObservedTurnCount")
            or cache_usage.get("averageObservedTurnCount")
            or 0
        ),
    }


def _capture_session_chat_candidate(session_id: str, messages: list[dict[str, Any]]) -> None:
    s = _service()
    service = s.ChatDatasetCaptureService(project_root=s.PROJECT_ROOT)
    if not service.should_capture_mode("chat"):
        return
    turns = s._build_chat_turn_records_from_messages(messages)
    if len(turns) < 2:
        return
    try:
        service.capture_candidate(
            mode="chat",
            session_id=session_id or "chat_session",
            source_log_path=s._resolve_chat_source_log_path(),
            turns=turns,
            next_state_signals=s._recent_chat_next_state_signal_summaries(session_id),
        )
    except Exception as exc:
        s._debug_logger.warning(f"web chat candidate capture skipped: {type(exc).__name__}: {exc}", tag="CHAT")


def _compact_preview_text(text: Any, *, max_lines: int = 3, max_chars: int = 180) -> str:
    s = _service()
    lines = [re.sub(r"\s+", " ", str(line or "")).strip() for line in str(text or "").splitlines()]
    visible_lines = [line for line in lines if line]
    if not visible_lines:
        return ""
    preview = " ".join(visible_lines[:max_lines]).strip()
    if len(preview) <= max_chars:
        return preview
    return f"{preview[: max_chars - 1].rstrip()}..."


def _compact_tool_loop_failure_hint(value: Any) -> str:
    s = _service()
    text = str(value or "").strip()
    if not text:
        return ""
    http_match = re.search(r"\bHTTP\s+(\d{3})\b", text, flags=re.IGNORECASE)
    if http_match:
        return f"HTTP {http_match.group(1)}"
    lowered = text.lower()
    if "无法连接" in text or "connection" in lowered or "connect" in lowered:
        return "无法连接"
    if "重定向" in text or "redirect" in lowered:
        return "重定向被拦截"
    if "内容为空" in text or "empty" in lowered:
        return "内容为空"
    if s._looks_like_tool_call_failure_summary(text):
        return s.trim_lines(text, max_lines=1)
    return ""


def _copy_tool_result_fact_fields(source: dict[str, Any], target: dict[str, Any]) -> None:
    s = _service()
    if not isinstance(source, dict):
        return
    for canonical, aliases in s._TOOL_RESULT_FACT_ALIASES.items():
        value = s._first_present_mapping_value(source, aliases)
        if value is None or value == "":
            continue
        if canonical in {"exitCode", "originalLength"}:
            numeric = s._coerce_tool_number(value)
            if numeric is None:
                continue
            target[canonical] = numeric
            continue
        if canonical in {"timedOut", "truncated"}:
            if isinstance(value, str):
                target[canonical] = value.strip().lower() in {"1", "true", "yes", "y", "on"}
            else:
                target[canonical] = bool(value)
            continue
        target[canonical] = str(value).strip()


def _current_session_live_llm_payload_trace(session_id: str) -> dict[str, Any] | None:
    s = _service()
    with s._SESSION_LIVE_OUTPUTS_LOCK:
        state = s._SESSION_LIVE_OUTPUTS.get(session_id)
        if state is None:
            return None
        return s._normalize_session_llm_payload_trace(state.llm_payload_trace)


def _dedupe_turn_error_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    s = _service()
    seen_turn_errors: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for message in messages:
        metadata = message.get("metadata")
        if (
            isinstance(metadata, dict)
            and str(message.get("role") or "").strip().lower() == "assistant"
            and str(metadata.get("kind") or "").strip() == "turn_error"
        ):
            turn_id = str(metadata.get("turnId") or metadata.get("turn_id") or "").strip()
            if turn_id:
                dedupe_key = f"turn_error:{turn_id}"
                if dedupe_key in seen_turn_errors:
                    continue
                seen_turn_errors.add(dedupe_key)
        deduped.append(message)
    return deduped


def _ensure_assistant_visible_text(content: Any, *, result: Any = None, lang: str | None = None) -> str:
    s = _service()
    cleaned = s._sanitize_message_content("assistant", content)
    if cleaned and s._looks_like_provider_error_text(cleaned):
        return s._user_visible_failure_summary(cleaned, lang=lang or s.get_web_language())
    if cleaned:
        return cleaned
    if isinstance(result, dict):
        for key in ("error", "message", "blocked_reason", "required_user_input", "recommended_next_action", "next_action"):
            fallback = s._sanitize_message_content("assistant", result.get(key) or "")
            if fallback:
                if s._looks_like_provider_error_text(fallback):
                    return s._user_visible_failure_summary(fallback, lang=lang or s.get_web_language())
                return fallback
        tool_trace = result.get("tool_trace") or result.get("tool_calls") or []
        if tool_trace:
            return s.text_for(
                lang or s.get_web_language(),
                zh="本轮只记录了工具调用，没有生成可见回答；请发送“继续”让 agent 汇总结果。",
                en='This turn only recorded tool calls and did not produce a visible reply. Send "continue" to summarize the result.',
            )
    return s.text_for(
        lang or s.get_web_language(),
        zh=s._NO_VISIBLE_REPLY_ZH,
        en=s._NO_VISIBLE_REPLY_EN,
    )


def _extract_chat_thought(result: Any, assistant_text: str) -> str:
    s = _service()
    if not isinstance(result, dict):
        return ""

    candidates = [
        result.get("thought"),
        result.get("reasoning_content"),
        s._extract_embedded_thought(result.get("raw_output") or ""),
        s._extract_embedded_thought(result.get("summary") or ""),
        s._extract_embedded_thought(result.get("message") or ""),
    ]
    for candidate in candidates:
        cleaned = s._sanitize_thought_text(candidate)
        if not cleaned:
            continue
        if s._thought_duplicates_reply(cleaned, assistant_text):
            continue
        return cleaned
    return ""


def _extract_embedded_thought(content: Any) -> str:
    s = _service()
    text = str(content or "")
    parts = [
        s._sanitize_thought_text(match)
        for match in re.findall(
            r"<(?:think|thinking)[^>]*>(.*?)</(?:think|thinking)>",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
    ]
    parts = [item for item in parts if item]
    if not parts:
        open_match = re.search(r"<(?:think|thinking)[^>]*>(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if open_match:
            candidate = s._sanitize_thought_text(open_match.group(1))
            if candidate:
                parts.append(candidate)
    if not parts:
        return ""
    return "\n\n".join(parts).strip()


def _extract_provider_http_status_from_json(value: Any) -> int:
    s = _service()
    if isinstance(value, dict):
        for key in ("status", "status_code", "statusCode", "http_status", "httpStatus", "code"):
            status = s._coerce_nonnegative_int(value.get(key))
            if 100 <= status <= 599:
                return status
        for nested in value.values():
            status = s._extract_provider_http_status_from_json(nested)
            if status:
                return status
    if isinstance(value, list):
        for item in value:
            status = s._extract_provider_http_status_from_json(item)
            if status:
                return status
    return 0


def _failure_error_type(raw_error: str, *, exc: Exception | None = None) -> str:
    s = _service()
    value = str(raw_error or "").strip().lower()
    exc_type = type(exc).__name__ if exc is not None else ""
    if "prompt_cache_unsupported" in value:
        return "prompt_cache_unsupported"
    if s._looks_like_provider_error_text(value):
        if any(
            marker in value
            for marker in (
                "upstream_error",
                "badgateway",
                "bad gateway",
                "server_error",
                "serviceunavailable",
                "service unavailable",
                "temporarily unavailable",
                "api_error",
                "gateway timeout",
            )
        ):
            return "provider_upstream_error"
        if "provider_protocol_error" in value or "payload_protocol_error" in value:
            return "provider_protocol_error"
        return "provider_error"
    return exc_type or "runtime_error"


def _find_turn_scoped_assistant_message(messages: list[dict[str, Any]], turn_id: str) -> dict[str, Any] | None:
    s = _service()
    normalized_turn_id = str(turn_id or "").strip()
    if not messages:
        return None
    if normalized_turn_id:
        for message in reversed(messages):
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            if s._message_turn_id(message) == normalized_turn_id:
                return message
        user_index = -1
        for index, message in enumerate(messages):
            if str(message.get("role") or "").strip().lower() == "user" and s._message_turn_id(message) == normalized_turn_id:
                user_index = index
        if user_index >= 0:
            for message in reversed(messages[user_index + 1 :]):
                if str(message.get("role") or "").strip().lower() != "assistant":
                    continue
                message_turn_id = s._message_turn_id(message)
                if message_turn_id and message_turn_id != normalized_turn_id:
                    continue
                return message
        return None
    for message in reversed(messages):
        if str(message.get("role") or "").strip().lower() == "assistant":
            return message
    return None


def _format_visible_reply(result: Any) -> str:
    s = _service()
    if not isinstance(result, dict):
        return s.text_for(
            s.get_web_language(),
            zh="本轮没有产生可见回复。",
            en="This turn did not produce a visible reply.",
        )

    visible = s._sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )
    if visible and s._looks_like_provider_error_text(visible):
        return s._user_visible_failure_summary(visible, lang=s.get_web_language())
    if visible and not s._looks_like_structured_payload(visible):
        return visible

    visible_result = s._visible_reply_candidate(result)
    reply_source = {
        **result,
        "raw_output": visible_result,
        "summary": visible_result,
    }
    summary = s._sanitize_message_content("assistant", s.format_chat_reply(reply_source))
    if summary:
        return summary
    return s.text_for(
        s.get_web_language(),
        zh="本轮没有产生可见回复。",
        en="This turn did not produce a visible reply.",
    )


def _has_image_generation_artifact_evidence(result: Any) -> bool:
    s = _service()
    if not isinstance(result, dict):
        return False
    stack: list[Any] = [result]
    seen: set[int] = set()
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            marker = id(current)
            if marker in seen:
                continue
            seen.add(marker)
            if str(current.get("imageUrl") or current.get("image_url") or "").strip():
                return True
            if str(current.get("artifactId") or current.get("artifact_id") or "").strip():
                kind = str(current.get("kind") or current.get("toolName") or current.get("tool_name") or "").strip()
                if not kind or "image" in kind.lower() or kind == "image2_generate_tool":
                    return True
            for value in current.values():
                if isinstance(value, (dict, list, tuple)):
                    stack.append(value)
        elif isinstance(current, (list, tuple)):
            stack.extend(current)
    return False


def _history_message_turn_id(item: Any) -> str:
    s = _service()
    if not isinstance(item, dict):
        return ""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(
        metadata.get("turnId")
        or metadata.get("turn_id")
        or item.get("turnId")
        or item.get("turn_id")
        or ""
    ).strip()


def _history_messages_for_agent_seed(
    items: Any,
    *,
    exclude_turn_id: str = "",
) -> list[dict[str, Any]]:
    """Build the prompt history view without transient runtime failure notices."""
    s = _service()

    filtered: list[dict[str, Any]] = []
    drop_assistant_until_next_user = False
    normalized_exclude_turn_id = str(exclude_turn_id or "").strip()
    for item in s.normalize_chat_messages(items or []):
        if normalized_exclude_turn_id and s._history_message_turn_id(item) == normalized_exclude_turn_id:
            continue
        role = str(item.get("role") or "").strip().lower()
        if role == "user":
            drop_assistant_until_next_user = False
        if s._should_omit_message_from_agent_history(item):
            if role == "user":
                drop_assistant_until_next_user = True
            continue
        if role == "assistant" and drop_assistant_until_next_user:
            continue
        item = dict(item)
        attachments = s._normalize_message_attachments(item.get("attachments") or item.get("imageAttachments") or [])
        if attachments:
            item["content"] = s._message_content_with_attachment_summary(item.get("content") or "", attachments)
            item.pop("attachments", None)
        filtered.append(item)
    return filtered


def _host_from_provider_url(value: Any) -> str:
    s = _service()
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(raw)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return ""


def _image_context_prompt_for_retry(
    message: str,
    *,
    conversation: dict[str, Any] | None,
    active_task: dict[str, Any] | None = None,
) -> str:
    s = _service()
    request = s._image_context_request_for_retry(message, conversation=conversation)
    return str(request.get("prompt") or "")


def _image_context_request_for_retry(
    message: str,
    *,
    conversation: dict[str, Any] | None,
) -> dict[str, Any]:
    s = _service()
    if not (s._is_continue_request(message) or s._is_contextual_confirmation_message(message)):
        return {}
    if not isinstance(conversation, dict):
        return {}
    conversation_id = str(conversation.get("conversation_id") or conversation.get("id") or "").strip()
    for item in reversed(s._session_ledger_visible_messages(conversation_id)[-8:]):
        if not isinstance(item, dict) or str(item.get("role") or "").strip().lower() != "user":
            continue
        request = s._image_context_request_from_user_message(item)
        if request:
            return request
    return {}


def _image_context_request_from_user_message(message: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    attachments = s._normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
    artifact_ids = [
        str(item.get("artifactId") or "").strip()
        for item in attachments
        if s._is_ready_user_image_attachment(item) and str(item.get("artifactId") or "").strip()
    ]
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    resolved_reference = (
        metadata.get("resolvedRecentImageReference")
        if isinstance(metadata.get("resolvedRecentImageReference"), dict)
        else {}
    )
    resolved_artifact_ids = [
        str(item or "").strip()
        for item in list(resolved_reference.get("artifactIds") or [])
        if str(item or "").strip()
    ]
    if resolved_artifact_ids:
        artifact_ids = resolved_artifact_ids
    if not artifact_ids:
        return {}

    prompt = s.trim_lines(message.get("content") or "", max_lines=4)
    if prompt and s._is_retriable_image_request_prompt(prompt):
        return {"prompt": prompt, "artifactIds": artifact_ids}
    return {}


def _infer_provider_http_status(raw_error: Any) -> int:
    s = _service()
    value = str(raw_error or "").strip()
    lower = value.lower()
    explicit = re.search(r"(?<!\d)([1-5]\d{2})(?!\d)", value)
    if explicit:
        return int(explicit.group(1))
    if "authenticationerror" in lower or "unauthorized" in lower:
        return 401
    if "permissiondenied" in lower or "forbidden" in lower:
        return 403
    if "ratelimiterror" in lower or "rate_limit" in lower or "rate limit" in lower:
        return 429
    if "badgatewayerror" in lower or "bad gateway" in lower:
        return 502
    if "serviceunavailableerror" in lower or "service unavailable" in lower:
        return 503
    if "gateway timeout" in lower or "timeouterror" in lower:
        return 504
    if "internalservererror" in lower:
        return 500
    return 0


def _is_phantom_image_generation_success(
    assistant_text: str,
    result: Any,
    messages: list[dict[str, Any]],
) -> bool:
    s = _service()
    if not s._looks_like_image_generation_success_text(assistant_text):
        return False
    if s._has_image_generation_artifact_evidence(result):
        return False
    if s._result_has_image2_tool_call(result):
        return False
    return not s._latest_message_is_image_generation_artifact(messages)


def _is_provider_failed_result(result: Any) -> bool:
    s = _service()
    if not isinstance(result, dict):
        return False
    if any(
        "prompt_cache_unsupported" in str(result.get(key) or "").lower()
        or "不支持显式 prompt cache" in str(result.get(key) or "")
        for key in ("error", "raw_error", "rawError", "summary", "raw_output")
    ):
        return True
    if any(
        s._looks_like_provider_error_text(result.get(key))
        for key in ("error", "raw_error", "rawError")
    ):
        return True
    status = str(result.get("status") or "").strip().lower()
    if status not in {"failed", "timeout", "error"}:
        return False
    return s._looks_like_provider_error_text(s._provider_failure_raw_error(result))


def _latest_effective_user_message(messages: list[dict[str, Any]]) -> str:
    s = _service()
    content, _index = s._latest_effective_user_message_with_index(messages)
    return content


def _latest_effective_user_message_with_index(messages: list[dict[str, Any]]) -> tuple[str, int]:
    s = _service()
    for index in range(len(messages or []) - 1, -1, -1):
        item = messages[index]
        if not isinstance(item, dict):
            continue
        if not s._is_real_user_message_entry(item):
            continue
        content = s.trim_lines(item.get("content") or "", max_lines=4)
        if s._is_effective_user_message(content):
            return content, index
    return "", -1


def _latest_effective_user_messages(messages: list[dict[str, Any]], *, limit: int = 3) -> list[str]:
    s = _service()
    values: list[str] = []
    seen: set[str] = set()
    for item in reversed(messages):
        if not s._is_real_user_message_entry(item):
            continue
        content = s.trim_lines(item.get("content") or "", max_lines=4)
        if not s._is_effective_user_message(content):
            continue
        dedupe_key = re.sub(r"\s+", "", content)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        values.append(content)
        if len(values) >= max(1, limit):
            break
    return list(reversed(values))


def _latest_message_is_image_generation_artifact(messages: list[dict[str, Any]]) -> bool:
    s = _service()
    for message in reversed(list(messages or [])[-3:]):
        if not isinstance(message, dict):
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        if str(metadata.get("kind") or "").strip() == "image2_generation" and str(metadata.get("imageUrl") or "").strip():
            return True
    return False


def _lightweight_chat_payload_decision(
    context: dict[str, Any],
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    s = _service()
    if list(attachments or []):
        return False, "attachments"
    if list(context.get("session_references") or []):
        return False, "session_references"
    if context.get("skill_invocation"):
        return False, "skill_invocation"
    if s.normalize_active_skill_contract(context.get("active_skill_contract")):
        return False, "active_skill_contract"
    user_message_source = str(context.get("user_message_source") or "").strip()
    if user_message_source == "agent_inbox":
        return False, "agent_inbox"
    if user_message_source == "self_observation":
        return True, "self_observation"

    raw_message = str(context.get("raw_user_message") or "").strip()
    effective_message = str(context.get("user_message") or "").strip()
    message = raw_message or effective_message
    if not message:
        return False, "empty_message"
    return False, "unified_conversation_chain"


def _looks_like_image_generation_success_text(value: Any) -> bool:
    s = _service()
    text = re.sub(r"\s+", "", str(value or "")).strip().lower()
    if not text:
        return False
    exact_success = {
        "已生成图片。",
        "已生成图片",
        "图片已生成。",
        "图片已生成",
        "图片生成完成。",
        "图片生成完成",
        "图片已成功生成！",
        "图片已成功生成!",
        "图片已成功生成",
        "已成功生成图片。",
        "已成功生成图片",
    }
    if text in {item.lower() for item in exact_success}:
        return True
    if len(text) > 60:
        return False
    success_terms = ("已生成", "生成完成", "成功生成", "已成功生成")
    return "图片" in text and any(term in text for term in success_terms)


def _looks_like_image_retry_context(text: Any) -> bool:
    s = _service()
    value = str(text or "").strip().lower()
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return False
    image_terms = ("原图", "原来的图片", "原来的图", "图片", "图像", "画面", "图", "image", "picture")
    retry_terms = (
        "再看",
        "重新看",
        "逼近",
        "调整提示词",
        "继续调整",
        "重绘",
        "生成的图片",
        "完全不一样",
        "参考",
        "match",
        "reference",
        "retry",
    )
    return any(term in compact for term in image_terms) and any(term in compact for term in retry_terms)


def _looks_like_provider_failure_summary_notice(text: Any) -> bool:
    s = _service()
    value = str(text or "").strip().lower()
    if not value:
        return False
    return any(
        marker in value
        for marker in (
            "模型服务上游暂时失败，本轮没有完成",
            "the model provider failed upstream, so this turn did not complete",
        )
    )


def _looks_like_runtime_failure_notice(text: Any) -> bool:
    s = _service()
    value = str(text or "").strip().lower()
    if not value:
        return False
    notices = (
        "上一轮运行已被中断，当前会话已恢复为可继续状态",
        "当前 agent 正在处理上一项任务，本轮已进入队列",
        "the previous turn was interrupted. this session is ready to continue",
        "the agent is handling another task. this turn is queued",
    )
    return any(notice in value for notice in notices) or s._looks_like_tool_unavailable_claim(value)


def _looks_like_tool_unavailable_claim(text: Any) -> bool:
    s = _service()
    value = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not value:
        return False
    compact = re.sub(r"\s+", "", value)
    zh_markers = (
        "无法执行任何工具操作",
        "所有工具当前都显示为不可用",
        "所有工具不可用",
        "无法生成图片",
    )
    en_markers = (
        "all tools are unavailable",
        "tools are unavailable",
        "cannot use any tools",
        "unable to use any tools",
    )
    has_tool_marker = (
        "工具" in value
        or "tool" in value
        or "image2_generate_tool" in value
    )
    return has_tool_marker and (
        any(marker in compact for marker in zh_markers)
        or any(marker in value for marker in en_markers)
    )


def _make_provider_failure_chat_message(
    turn_error: dict[str, Any],
    *,
    error_type: str,
    turn_id: str,
) -> dict[str, Any]:
    s = _service()
    return s._make_turn_error_chat_message(
        turn_error,
        error_type=error_type,
        turn_id=turn_id,
        provider_failure=str(error_type or "").strip() != "prompt_cache_unsupported",
    )


def _merge_continuation_visible_result(
    result: Any,
    visible_result: dict[str, Any] | None,
) -> Any:
    s = _service()
    if not isinstance(result, dict) or not isinstance(visible_result, dict):
        return result
    visible = s._visible_reply_summary_candidate(result)
    if visible:
        return result
    merged = dict(result)
    remembered_visible = s._visible_reply_summary_candidate(visible_result)
    if not remembered_visible:
        return result
    merged["raw_output"] = remembered_visible
    merged["summary"] = remembered_visible
    for key in (
        "read_files",
        "changed_files",
        "verification_status",
        "verification_summary",
        "tool_call_count",
        "tool_trace",
    ):
        if not merged.get(key) and visible_result.get(key):
            merged[key] = visible_result.get(key)
    return merged


def _message_list_chars(messages: list[dict[str, Any]]) -> int:
    s = _service()
    total = 0
    for item in list(messages or []):
        if not isinstance(item, dict):
            continue
        total += len(str(item.get("content") or ""))
        total += len(str(item.get("thought") or ""))
        for tool_call in list(item.get("toolCalls") or item.get("tool_calls") or []):
            if isinstance(tool_call, dict):
                total += len(str(tool_call.get("name") or ""))
                total += len(str(tool_call.get("summary") or ""))
                total += len(str(tool_call.get("resultPreview") or tool_call.get("result_preview") or ""))
                total += len(str(tool_call.get("error") or ""))
    return total


def _message_list_content_preview(messages: list[dict[str, Any]], *, limit: int = 4) -> str:
    s = _service()
    parts: list[str] = []
    for item in list(messages or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "message").strip() or "message"
        content = s._compact_preview_text(item.get("content") or "", max_lines=2, max_chars=120)
        if not content:
            tool_parts = []
            for tool_call in list(item.get("toolCalls") or item.get("tool_calls") or [])[:2]:
                if isinstance(tool_call, dict):
                    tool_parts.append(
                        s._compact_preview_text(
                            tool_call.get("summary")
                            or tool_call.get("resultPreview")
                            or tool_call.get("result_preview")
                            or tool_call.get("name")
                            or "",
                            max_lines=1,
                            max_chars=80,
                        )
                    )
            content = "; ".join(part for part in tool_parts if part)
        if content:
            parts.append(f"{role}: {content}")
    return s._compact_preview_text(" | ".join(parts), max_lines=1, max_chars=240)


def _normalize_latest_preview_messages(conversation_id: str, items: Any, *, scan_limit: int = 12) -> list[dict[str, Any]]:
    s = _service()
    raw_items = list(items or [])
    total_count = len(raw_items)
    for reverse_index, raw in enumerate(reversed(raw_items[-scan_limit:]), start=1):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = s._sanitize_message_content(role, raw.get("content") or "")
        if not content or (role == "assistant" and s._looks_like_runtime_failure_notice(content)):
            continue
        index = total_count - reverse_index + 1
        return [
            {
                "id": f"{conversation_id}-message-{index}",
                "role": role,
                "content": content,
                "timestamp": str(raw.get("timestamp") or "").strip(),
            }
        ]
    return []


def _normalize_llm_payload_trace_counts(value: Any) -> dict[str, int]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    counts: dict[str, int] = {}
    for item_key, item_value in value.items():
        key = str(item_key or "").strip()
        if not key:
            continue
        counts[key] = s._coerce_nonnegative_int(item_value)
    return counts


def _normalize_llm_payload_trace_map(value: Any, allowed_keys: set[str]) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    safe_item: dict[str, Any] = {}
    for key in allowed_keys:
        item_value = value.get(key)
        if item_value in (None, ""):
            continue
        if isinstance(item_value, bool):
            safe_item[key] = item_value
        elif isinstance(item_value, (int, float)):
            safe_item[key] = s._coerce_nonnegative_int(item_value)
        elif isinstance(item_value, str):
            text = item_value.strip()
            if text:
                safe_item[key] = text
    return safe_item


def _normalize_optional_bool(value: Any) -> bool | None:
    s = _service()
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _not_called_cache_composition(*, recorded_at: str = "", reason: str = "") -> dict[str, Any]:
    s = _service()
    return s._normalize_session_cache_composition(
        {
            "recordedAt": str(recorded_at or "").strip() or s._now_timestamp(),
            "source": "not_called",
            "segments": [
                {
                    "key": "missing",
                    "label": "not called",
                    "tokens": 1,
                    "status": str(reason or "not_called").strip() or "not_called",
                }
            ],
        }
    ) or {}


def _provider_failure_partial_visible_reply(result: Any, failure_message: str) -> str:
    s = _service()
    if not isinstance(result, dict):
        return ""
    failure_text = str(failure_message or "").strip()
    for key in ("raw_output", "summary", "message"):
        visible = s._sanitize_message_content("assistant", result.get(key) or "")
        if not visible:
            continue
        if visible == failure_text:
            continue
        if s._looks_like_provider_error_text(visible) or s._looks_like_provider_failure_summary_notice(visible):
            continue
        if s._looks_like_structured_payload(visible):
            continue
        return visible
    return ""


def _provider_failure_raw_error(result: dict[str, Any]) -> str:
    s = _service()
    llm_failure = result.get("llm_failure") if isinstance(result.get("llm_failure"), dict) else {}
    candidates = [
        llm_failure.get("message") if isinstance(llm_failure, dict) else "",
        llm_failure.get("raw_error") if isinstance(llm_failure, dict) else "",
        llm_failure.get("error") if isinstance(llm_failure, dict) else "",
        result.get("raw_error"),
        result.get("rawError"),
        result.get("summary"),
        result.get("raw_output"),
        result.get("error"),
        result.get("message"),
        result.get("blocked_reason"),
    ]
    matched: list[str] = []
    for candidate in candidates:
        text = str(candidate or "").strip()
        if s._looks_like_provider_error_text(text):
            matched.append(text)
    if matched:
        return max(matched, key=lambda item: (len(s._provider_error_reason_detail(item)), len(item)))
    return str(result.get("error") or result.get("summary") or result.get("raw_output") or "").strip()


def _raw_visible_payload_is_control_marker_only(result: dict[str, Any]) -> bool:
    s = _service()
    raw = str(result.get("raw_output") or result.get("summary") or result.get("message") or "").strip()
    if not raw:
        return False
    return bool(
        re.fullmatch(r"\[(?:outcome|task_outcome|status)\s*=\s*[^\]\r\n]*\]", raw, flags=re.IGNORECASE)
        or re.fullmatch(
            r"(?:outcome|task_outcome|status)\s*=\s*(?:done|success|failed|ready|blocked|needs_input|progress)",
            raw,
            flags=re.IGNORECASE,
        )
    )


def _recent_chat_next_state_signal_summaries(session_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
    s = _service()
    try:
        signals = s.list_chat_next_state_signals(
            project_root=s.PROJECT_ROOT,
            session_id=session_id,
            limit=limit,
        )
        return s.summarize_chat_next_state_signals(signals, limit=limit)
    except Exception:
        return []


def _record_chat_next_state_signal(
    *,
    session_id: str,
    turn_id: str = "",
    source: str,
    kind: str,
    polarity: str = "neutral",
    mode: str = "evaluative",
    related_event_code: str = "",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    try:
        return s.append_chat_next_state_signal(
            project_root=s.PROJECT_ROOT,
            session_id=session_id,
            turn_id=turn_id,
            source=source,
            kind=kind,
            polarity=polarity,
            mode=mode,
            related_event_code=related_event_code,
            summary=summary,
            metadata=metadata or {},
        )
    except Exception as exc:
        s._debug_logger.warning(f"chat next-state signal skipped: {type(exc).__name__}: {exc}", tag="CHAT")
        return None


def _record_missing_session_turn_control_recovery(
    session_id: str,
    turn_id: str,
    *,
    reused_active_run: bool,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "conversation",
            "turn_control_recovery",
            "conversation.turn_control_recovered",
            level="warning",
            outcome="reused_active_run" if reused_active_run else "created_new_turn",
            message="Recovered a missing web chat turn controller.",
            fields={
                "sessionId": str(session_id or "").strip(),
                "turnId": str(turn_id or "").strip(),
                "reusedActiveRun": bool(reused_active_run),
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_provider_failure_signal(
    *,
    session_id: str,
    turn_id: str = "",
    error_type: str = "",
    raw_error: str = "",
    related_event_code: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    fields = {
        "errorType": str(error_type or "").strip(),
        "rawErrorPreview": s.trim_lines(raw_error, max_lines=2),
        **(metadata or {}),
    }
    return s._record_chat_next_state_signal(
        session_id=session_id,
        turn_id=turn_id,
        source="runtime",
        kind="provider_failure",
        polarity="negative",
        mode="evaluative",
        related_event_code=related_event_code or "conversation.turn_error",
        summary="Provider failure interrupted the chat turn.",
        metadata=fields,
    )


def _remember_continuation_visible_result(
    result: Any,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    s = _service()
    if not isinstance(result, dict):
        return current
    if s._is_provider_failed_result(result):
        return current
    visible = s._visible_reply_summary_candidate(result)
    if not visible:
        return current
    remembered = dict(result)
    remembered["raw_output"] = visible
    remembered["summary"] = visible
    return remembered


def _required_tool_progress_followup_guidance(required_tool_names: list[str] | None = None) -> str:
    s = _service()
    names = [
        str(item or "").strip()
        for item in list(required_tool_names or [])
        if str(item or "").strip()
    ]
    if names:
        return (
            "上一轮只输出了接收或计划，没有调用阶段任务要求的工具。"
            f"本轮必须先调用这些工具中的相关项：{', '.join(names[:8])}。"
        )
    return "上一轮只输出了接收或计划，没有调用阶段任务要求的工具。本轮必须先调用阶段任务工具取得真实进度。"


def _required_tool_progress_missing(
    result: Any,
    *,
    require_tool_progress: bool,
    required_tool_names: list[str] | None = None,
    observed_tool_names: set[str] | None = None,
) -> bool:
    s = _service()
    if not require_tool_progress or not isinstance(result, dict):
        return False
    if bool(result.get("stop_requested")) or s._is_provider_failed_result(result):
        return False
    if s._explicit_chat_result_outcome(result) == "progress":
        return False
    visible = s._visible_reply_candidate(result)
    if not visible or s._raw_visible_payload_is_control_marker_only(result):
        return False
    required_names = {
        str(item or "").strip()
        for item in list(required_tool_names or [])
        if str(item or "").strip()
    }
    if required_names:
        observed_names = set(observed_tool_names or set()) | s._result_tool_names(result)
        return not required_names.issubset(observed_names)
    if s._coerce_nonnegative_int(result.get("tool_call_count") or 0) > 0:
        return False
    if s._result_tool_names(result):
        return False
    return True


def _restore_missing_session_turn_control(session_id: str) -> Any:
    """Recreate a lost stop controller without changing the active run identity."""
    s = _service()

    active_turn_id = s._active_chat_turn_id_for_session(session_id)
    if active_turn_id:
        s._record_missing_session_turn_control_recovery(session_id, active_turn_id, reused_active_run=True)
        return s._create_session_turn_control(session_id, turn_id=active_turn_id)
    s._record_missing_session_turn_control_recovery(session_id, "", reused_active_run=False)
    return s._create_session_turn_control(session_id)


def _safe_tool_argument_details(value: Any) -> dict[str, Any]:
    s = _service()
    if not isinstance(value, dict):
        return {}
    details: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key or "").strip()
        if not key or key.startswith("_") or key.lower() in {"api_key", "apikey", "token", "secret", "password"}:
            continue
        if raw_value is None or isinstance(raw_value, (bool, int, float)):
            details[key] = raw_value
            continue
        if isinstance(raw_value, str):
            details[key] = s._trim_tool_detail_text(raw_value, max_chars=420, max_lines=4)
            continue
        if isinstance(raw_value, (list, tuple)):
            details[key] = [s._trim_tool_detail_text(item, max_chars=220, max_lines=2) for item in list(raw_value)[:8]]
            continue
        if isinstance(raw_value, dict):
            nested: dict[str, Any] = {}
            for nested_key, nested_value in list(raw_value.items())[:16]:
                nested_name = str(nested_key or "").strip()
                if not nested_name or nested_name.startswith("_") or nested_name.lower() in {"api_key", "apikey", "token", "secret", "password"}:
                    continue
                nested[nested_name] = s._trim_tool_detail_text(nested_value, max_chars=220, max_lines=2)
            details[key] = nested
            continue
        details[key] = s._trim_tool_detail_text(raw_value, max_chars=220, max_lines=2)
    return details


def _session_last_cache_composition(
    conversation: dict[str, Any],
    *,
    llm_usage: dict[str, Any] | None,
    context_composition: dict[str, Any] | None = None,
    average_cache: dict[str, Any] | None = None,
    normalized_last_cache_composition: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    s = _service()
    existing = normalized_last_cache_composition or s._normalize_session_cache_composition(
        conversation.get("lastCacheComposition") or conversation.get("last_cache_composition")
    )
    if existing is not None:
        return s._enrich_session_cache_composition(
            existing,
            context_composition=context_composition,
            average_cache=average_cache,
        )
    usage = s._normalize_turn_llm_usage(llm_usage)
    if usage is None:
        return None
    return s._build_session_cache_composition(
        "",
        usage,
        context_composition=context_composition,
        average_cache=average_cache,
    )


def _session_ledger_visible_messages(session_id: str) -> list[dict[str, Any]]:
    s = _service()
    return s._normalize_messages(session_id, s._ledger_visible_messages_for_session(session_id))


def _session_prompt_cache_log_fields(*, scope: str, partition: str) -> dict[str, Any]:
    s = _service()
    normalized_scope = str(scope or "").strip()
    normalized_partition = str(partition or "").strip()
    return {
        "promptCacheScope": normalized_scope,
        "promptCachePartition": normalized_partition,
        "promptCachePartitionHash": s._short_hash(normalized_partition),
        "promptCachePartitionChars": len(normalized_partition),
        "promptCacheSessionFallback": normalized_scope == s.SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK,
    }


def _session_prompt_cache_scope(*, agent_id: str = "") -> str:
    s = _service()
    if str(agent_id or "").strip():
        return s.SESSION_PROMPT_CACHE_SCOPE_AGENT_STATIC
    return s.SESSION_PROMPT_CACHE_SCOPE_SESSION_FALLBACK


def _should_omit_message_from_agent_history(message: dict[str, Any]) -> bool:
    s = _service()
    role = str(message.get("role") or "").strip().lower()
    content = str(message.get("content") or "").strip()
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and str(metadata.get("kind") or "").strip() == "turn_error":
        return True
    if role == "user" and s._is_system_authored_user_message_entry(message):
        return True
    attachments = s._normalize_message_attachments(message.get("attachments") or message.get("imageAttachments") or [])
    if role == "assistant":
        tool_calls = s._normalize_message_tool_calls(
            message.get("tool_calls") or message.get("toolCalls") or message.get("tools") or []
        )
        if tool_calls:
            return False
    if role != "user":
        return role == "assistant" and (
            not content
            or s._is_protocol_only_assistant_message(content)
            or s._looks_like_provider_error_text(content)
            or s._looks_like_runtime_failure_notice(content)
        )
    return not content and not attachments


def _should_prefer_history_goal_over_active_task(
    active_task: dict[str, Any] | None,
    messages: list[dict[str, Any]],
    *,
    existing_goal: str,
    history_goal: str,
    history_goal_index: int,
) -> bool:
    s = _service()
    if not isinstance(active_task, dict):
        return False
    if not existing_goal or not history_goal:
        return False
    if s._task_goal_dedupe_key(existing_goal) == s._task_goal_dedupe_key(history_goal):
        return False
    existing_goal_index = s._latest_user_message_index_matching_goal(messages, existing_goal)
    if existing_goal_index >= 0 and history_goal_index > existing_goal_index:
        return True
    metadata = active_task.get("metadata") if isinstance(active_task.get("metadata"), dict) else {}
    last_user_message = s.trim_lines(active_task.get("last_user_message") or "", max_lines=4)
    if (
        bool(metadata.get("last_user_message_filtered"))
        and last_user_message
        and not s._is_effective_user_message(last_user_message)
        and s._looks_like_tool_unavailable_claim(active_task.get("latest_summary") or "")
    ):
        return True
    return False


def _source_collection_stage_task_required_tool_names(context: dict[str, Any]) -> list[str]:
    s = _service()
    metadata = context.get("message_metadata") if isinstance(context.get("message_metadata"), dict) else {}
    contract = metadata.get("writebackContract") if isinstance(metadata.get("writebackContract"), dict) else {}
    checklist = contract.get("taskChecklist") or metadata.get("taskChecklist") or []
    names: list[str] = []
    for item in list(checklist or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("requiredTool") or "").strip()
        if name and name not in names:
            names.append(name)
    writeback_tool = str(contract.get("toolName") or "").strip()
    if writeback_tool and writeback_tool not in names:
        names.append(writeback_tool)
    return names


def _source_collection_stage_task_allowed_tool_names(context: dict[str, Any]) -> list[str]:
    """Return a task-scoped provider surface without disabling needed research tools."""

    metadata = (
        context.get("message_metadata")
        if isinstance(context.get("message_metadata"), dict)
        else {}
    )
    stage_id = str(metadata.get("stageId") or "").strip().lower()
    required = _source_collection_stage_task_required_tool_names(context)
    if stage_id in {"relations", "ingestion"}:
        return required
    if stage_id == "extraction":
        return [*required, "web_fetch_tool"]
    # Finding legitimately needs the role's search/fetch providers. Unknown or
    # legacy metadata keeps the frozen Agent policy rather than silently losing
    # capabilities.
    return []


def _task_status_from_result_contract(
    outcome: str,
    *,
    read_files: list[str],
    changed_files: list[str],
    verification_status: str,
) -> str:
    s = _service()
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome == "needs_input":
        return "needs_input"
    if normalized_outcome == "blocked":
        return "blocked"
    if normalized_outcome == "done":
        return "done"
    if verification_status == "passed" and changed_files:
        return "done"
    if changed_files:
        return "editing"
    if read_files:
        return "reading"
    return "idle"


def _unwrap_continuation_goal(value: Any) -> str:
    s = _service()
    text = str(value or "").strip()
    marker = "继续完成同一个用户目标："
    while text.startswith(marker):
        text = text[len(marker) :].strip()
        next_line = text.find("\n")
        if next_line >= 0:
            text = text[:next_line].strip()
    return text


def _visible_reply_candidate(result: dict[str, Any]) -> str:
    s = _service()
    return s._sanitize_message_content(
        "assistant",
        result.get("raw_output") or result.get("summary") or result.get("error") or result.get("message") or "",
    )


def _visible_reply_matches_derived_tool_activity(result: dict[str, Any], visible_result: str) -> bool:
    s = _service()
    visible = s._sanitize_message_content("assistant", visible_result)
    if not visible:
        return False
    if not (result.get("tool_trace") or result.get("tool_calls") or result.get("read_files") or result.get("changed_files")):
        return False
    probe = dict(result)
    probe["raw_output"] = ""
    probe["summary"] = ""
    probe["message"] = ""
    derived = s._sanitize_message_content("assistant", s.format_chat_reply(probe))
    return bool(derived and derived == visible)


def _visible_reply_summary_candidate(result: dict[str, Any]) -> str:
    s = _service()
    if s._raw_visible_payload_is_control_marker_only(result):
        return ""
    visible = s._visible_reply_candidate(result)
    if visible and s._looks_like_provider_error_text(visible):
        return s._user_visible_failure_summary(visible, lang=s.get_web_language())
    if visible and not s._looks_like_structured_payload(visible):
        return visible
    reply = s._format_visible_reply(result)
    if reply and s._NO_VISIBLE_REPLY_ZH not in reply and s._NO_VISIBLE_REPLY_EN not in reply:
        return reply
    return ""


def _visible_session_runtime_notices(
    notices: list[dict[str, Any]],
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    s = _service()
    latest_message_ts = max(
        (s._timestamp_sort_key(str(message.get("timestamp") or "")) for message in list(messages or [])),
        default=0.0,
    )
    visible: list[dict[str, Any]] = []
    for notice in s._normalize_session_runtime_notices(notices):
        notice_ts = s._timestamp_sort_key(str(notice.get("timestamp") or ""))
        if notice_ts and latest_message_ts > notice_ts:
            continue
        visible.append(notice)
    return visible[-1:]


def _weighted_token_allocation(total_tokens: int, weights: list[int]) -> list[int]:
    s = _service()
    total = s._coerce_nonnegative_int(total_tokens)
    normalized_weights = [max(0, s._coerce_nonnegative_int(weight)) for weight in weights]
    weight_total = sum(normalized_weights)
    if total <= 0 or weight_total <= 0:
        return [0 for _ in normalized_weights]
    allocations: list[int] = []
    used = 0
    for index, weight in enumerate(normalized_weights):
        if weight <= 0:
            allocations.append(0)
            continue
        if index == len(normalized_weights) - 1:
            value = max(0, total - used)
        else:
            value = int((total * weight) // weight_total)
        allocations.append(value)
        used += value
    remainder = total - sum(allocations)
    index = 0
    while remainder > 0 and allocations:
        allocations[index % len(allocations)] += 1
        remainder -= 1
        index += 1
    return allocations


def _without_live_turn_ledger_partials(
    messages: list[dict[str, Any]],
    live_message: dict[str, Any],
) -> list[dict[str, Any]]:
    s = _service()
    live_metadata = live_message.get("metadata") if isinstance(live_message.get("metadata"), dict) else {}
    live_turn_id = str(live_metadata.get("turnId") or "").strip()
    if not live_turn_id:
        return list(messages or [])
    filtered: list[dict[str, Any]] = []
    for message in list(messages or []):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if (
            str(message.get("role") or "").strip().lower() == "assistant"
            and str(metadata.get("turnId") or "").strip() == live_turn_id
            and str(metadata.get("kind") or "").strip() == "journal_assistant_partial"
        ):
            continue
        filtered.append(message)
    return filtered
