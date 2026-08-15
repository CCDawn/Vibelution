# -*- coding: utf-8 -*-
"""Runtime bindings, environment parsing, goal extraction, and diagnostic utilities for Agent orchestrator."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import AIMessage

from config import AppConfig
from core.llm.agent_runtime import (
    AgentLlmResolutionError,
    normalize_agent_llm_bindings,
)
from core.llm.invocation import LLMInvocationContext
from core.logging.logger import debug as _debug_logger


_INTERNAL_TOOL_PROTOCOL_MARKERS = (
    "spawn_agent_tool",
    "_internal_delegate",
)
_SESSION_CHAT_PROMPT_GOAL = "处理当前会话中的用户请求"
_TOOL_POLICY_FAILURE_RE = re.compile(
    r"\[工具策略提示\]\s*`[^`]+`\s*不在该 Agent 的可见工具策略中。?",
)
_NUMBERED_CONFIRMATION_RE = re.compile(
    r"(?:^|[,\n;；])\s*\d+\s*[,，、.．:：]\s*([^,\n;；]+)"
)
_CONFIRMATION_KEYWORDS = (
    "确认",
    "同意",
    "可以",
    "允许",
    "就用",
    "采用",
    "使用",
    "要求",
    "先不",
    "不考虑",
)
_ASSISTANT_GOAL_CONTEXT_KEYWORDS = (
    "需求",
    "目标",
    "方案",
    "确认",
    "问题",
    "规划",
    "实现",
)


def _normalize_goal_from_chat_history(
    user_prompt: str,
    goal_override: Optional[str],
    active_turn_messages: Optional[List[Any]],
) -> str:
    """Keep the requirement context when the user only sends numbered confirmations."""

    override = str(goal_override or "").strip()
    if override:
        return override
    prompt = str(user_prompt or "").strip()
    if not _looks_like_numbered_confirmation(prompt):
        return prompt
    context = _latest_assistant_goal_context(active_turn_messages)
    if not context:
        return prompt
    return f"{context}\n用户确认：{_compact_one_line(prompt, 180)}"


def _looks_like_numbered_confirmation(text: str) -> bool:
    prompt = str(text or "").strip()
    if not prompt or len(prompt) > 280:
        return False
    parts = [part.strip() for part in _NUMBERED_CONFIRMATION_RE.findall(prompt) if part.strip()]
    if len(parts) < 2:
        return False
    short_answers = sum(1 for part in parts if len(part) <= 24)
    if short_answers < max(2, len(parts) - 1):
        return False
    return any(keyword in prompt for keyword in _CONFIRMATION_KEYWORDS)


def _latest_assistant_goal_context(messages: Optional[List[Any]]) -> str:
    for message in reversed(list(messages or [])):
        role = _message_role(message)
        if role not in {"assistant", "ai"}:
            continue
        content = _message_content(message)
        if not content:
            continue
        return _compact_goal_context(content)
    return ""


def _message_role(message: Any) -> str:
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, dict):
        return str(message.get("role") or message.get("kind") or "").strip().lower()
    return str(getattr(message, "type", "") or "").strip().lower()


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        content = message.get("content", "")
    else:
        content = getattr(message, "content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "\n".join(part for part in parts if part.strip())
    return str(content or "").strip()


def _compact_goal_context(text: str, limit: int = 240) -> str:
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip(" \t-•*")
        if line:
            lines.append(line)
    preferred = [
        line
        for line in lines
        if any(keyword in line for keyword in _ASSISTANT_GOAL_CONTEXT_KEYWORDS)
    ]
    source = " ".join((preferred or lines)[:4])
    return _compact_one_line(source, limit)


def _compact_one_line(text: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


_SAFE_LLM_ERROR_DIAGNOSTIC_DETAIL_KEYS = (
    "messageIndex",
    "payloadValidationErrorType",
    "payloadValidationResult",
    "payloadMessageAssistantToolCallCount",
    "payloadMessageToolResultCount",
    "payloadMessageShapeHash",
)


def _safe_llm_error_diagnostic_details(details: Any) -> Dict[str, Any]:
    """Keep only prompt-free scalar projection diagnostics from an LLM error."""
    if not isinstance(details, dict):
        return {}
    safe: Dict[str, Any] = {}
    for key in _SAFE_LLM_ERROR_DIAGNOSTIC_DETAIL_KEYS:
        value = details.get(key)
        if isinstance(value, str):
            compact = _compact_one_line(value, 160)
            if compact:
                safe[key] = compact
        elif isinstance(value, (bool, int, float)):
            safe[key] = value
    return safe


def _provider_rejected_responses_continuation(
    *,
    category: Any,
    message: Any,
    details: Any,
) -> bool:
    diagnostic_text = " ".join(
        [
            str(category or ""),
            str(message or ""),
            str(dict(details or {}) if isinstance(details, dict) else details or ""),
        ]
    ).lower()
    return "previous_response_id" in diagnostic_text and any(
        marker in diagnostic_text
        for marker in ("unsupported", "unknown", "invalid", "not found", "not_found")
    )


_TOOL_SURFACE_GROUPS: Dict[str, str] = {
    "grep_search_tool": "locate",
    "glob_tool": "locate",
    "code_symbol_tool": "inspect",
    "read_file_tool": "read",
    "apply_patch_tool": "edit",
    "apply_diff_edit_tool": "edit",
    "write_file_tool": "edit",
    "cli_tool": "execute",
    "python_lint_tool": "verify",
    "run_test_for_tool": "verify",
    "web_search_tool": "web",
    "web_fetch_tool": "web",
    "image2_generate_tool": "media",
    "conversation_log_inspect_tool": "diagnostics",
    "get_core_context_tool": "memory",
    "get_current_goal_tool": "memory",
    "search_memory_tool": "memory",
    "search_error_archive_tool": "memory",
    "record_learning_tool": "memory",
    "compress_context_tool": "memory",
}
_CORE_CHAT_TOOL_NAMES = {
    "grep_search_tool",
    "code_symbol_tool",
    "read_file_tool",
    "cli_tool",
    "python_lint_tool",
    "run_test_for_tool",
    "search_memory_tool",
    "record_learning_tool",
}


def _agent_api_key_diagnostic(config: AppConfig) -> Dict[str, Any]:
    primary = config.llm.get_profile(role="primary")
    provider = config.llm.get_provider(primary.provider_id)
    model_id, model_entry = config.llm.get_model_library_entry_for_profile(primary)
    if not isinstance(model_entry, dict):
        profile_model = str(getattr(primary, "model", "") or "").strip()
        profile_key_env = str(getattr(primary, "api_key_env", "") or "").strip()
        for candidate_id, item in (getattr(config.llm, "model_library", {}) or {}).items():
            if not isinstance(item, dict):
                continue
            item_model = str(item.get("model") or "").strip()
            item_key_env = str(item.get("api_key_env") or "").strip()
            if item_model == profile_model and (not profile_key_env or item_key_env == profile_key_env):
                model_id = str(candidate_id or "").strip()
                model_entry = item
                break
    model_key_env = str(getattr(primary, "api_key_env", "") or "").strip()
    if isinstance(model_entry, dict):
        model_key_env = model_key_env or str(model_entry.get("api_key_env") or "").strip()
    provider_key_env = str(provider.api_key_env or "").strip()
    try:
        api_key_source = config.get_api_key_source_label()
    except Exception:
        api_key_source = "unknown"
    return {
        "profileId": primary.profile_id,
        "model": primary.model,
        "modelId": str(model_id or "").strip(),
        "providerId": provider.provider_id,
        "providerKind": provider.kind,
        "requiresApiKey": bool(provider.requires_api_key),
        "apiKeySource": api_key_source,
        "modelApiKeyEnv": model_key_env,
        "providerApiKeyEnv": provider_key_env,
    }


def _format_missing_api_key_error(diagnostic: Dict[str, Any]) -> str:
    model_env = str(diagnostic.get("modelApiKeyEnv") or "").strip()
    provider_env = str(diagnostic.get("providerApiKeyEnv") or "").strip()
    candidates = [item for item in (model_env, provider_env) if item]
    candidate_text = "、".join(candidates) if candidates else "当前 provider 对应的环境变量"
    model_id = str(diagnostic.get("modelId") or "").strip() or "未匹配到模型库 ID"
    return (
        "未设置 API Key。\n"
        f"当前会话模型: {diagnostic.get('model') or 'unknown'} "
        f"(modelId={model_id}, provider={diagnostic.get('providerId') or 'unknown'}, "
        f"profile={diagnostic.get('profileId') or 'primary'})。\n"
        f"请设置环境变量 {candidate_text}，或在当前模型/provider 配置中写入 api_key。"
    )


def _record_agent_scene_event(
    phase: str,
    event_code: str,
    *,
    message: str,
    fields: Dict[str, Any] | None = None,
    level: str = "info",
    outcome: str = "observed",
) -> None:
    try:
        from core.web.services.runtime_scene_service import record_runtime_scene_event

        record_runtime_scene_event(
            "agent",
            phase,
            event_code,
            message=message,
            level=level,
            outcome=outcome,
            fields=fields or {},
        )
    except Exception as exc:
        _debug_logger.warning(f"Failed to record agent scene event ({phase}/{event_code}): {exc}")


def _can_reuse_system_prompt(
    *,
    has_cached_prompt: bool,
    prompt_built_with_runtime_key: str,
    current_runtime_state_memory_key: str,
) -> bool:
    """Reuse the built system prompt while runtime state-memory key is unchanged.

    Git is tool-driven and is not part of this decision. Prompt rebuild is only
    needed when runtime state memory actually changes (typically after tools).
    """
    return bool(
        has_cached_prompt
        and prompt_built_with_runtime_key == current_runtime_state_memory_key
    )


_STALL_SIGNAL_THRESHOLDS = {
    "no_new_evidence_steps": 3,
    "consecutive_tool_only_steps": 3,
    "consecutive_bookkeeping_tool_only_steps": 3,
    "delegation_failures": 3,
}


def _stall_signal_threshold_events(telemetry, reported) -> list:
    """返回本次跨越阈值（且未报告过）的卡住信号名列表。

    - reported: {key: True} 已报告集合；值归零后（重置）清除已报告标记，
      下次再跨越阈值会再次报告。
    """
    events = []
    telemetry = dict(telemetry or {})
    reported = dict(reported or {})
    for key, threshold in _STALL_SIGNAL_THRESHOLDS.items():
        value = int(telemetry.get(key) or 0)
        if value >= threshold and not bool(reported.get(key)):
            events.append(key)
    return events


def _reset_stall_signal_reported(telemetry, reported) -> dict:
    """清除已归零信号的已报告标记（与 _stall_signal_threshold_events 配合）。"""
    telemetry = dict(telemetry or {})
    reported = dict(reported or {})
    for key in list(reported):
        if int(telemetry.get(key) or 0) == 0:
            reported.pop(key, None)
    return reported


def _can_reuse_initial_prompt(
    *,
    pending: bool = True,
    initial_runtime_state_memory_key: str = "",
    current_runtime_state_memory_key: str = "",
    # Legacy kwargs kept for call-site compatibility.
    initial_git_state: Any = None,
    current_git_state: Any = None,
    has_cached_prompt: bool = True,
    prompt_built_with_runtime_key: str = "",
) -> bool:
    del initial_git_state, current_git_state
    # Prefer the modern signature when callers pass explicit build-key fields.
    if prompt_built_with_runtime_key or not pending:
        return _can_reuse_system_prompt(
            has_cached_prompt=has_cached_prompt if prompt_built_with_runtime_key else bool(pending),
            prompt_built_with_runtime_key=(
                prompt_built_with_runtime_key or initial_runtime_state_memory_key
            ),
            current_runtime_state_memory_key=current_runtime_state_memory_key,
        )
    return bool(
        pending
        and has_cached_prompt
        and current_runtime_state_memory_key == initial_runtime_state_memory_key
    )


def _llm_effective_route_identity(client: Any) -> tuple[str, ...]:
    identity_builder = getattr(client, "effective_route_identity", None)
    if callable(identity_builder):
        try:
            identity = identity_builder()
            if isinstance(identity, (list, tuple)):
                return tuple(str(part or "").strip() for part in identity)
            if identity not in (None, ""):
                return (str(identity).strip(),)
        except Exception:
            pass
    profile = getattr(client, "profile", None)
    provider = getattr(client, "provider", None)
    route = getattr(client, "protocol_route", None)
    wire_protocol = str(
        getattr(getattr(route, "wire_protocol", None), "value", "")
        or getattr(route, "protocol", "")
        or ""
    ).strip()
    return (
        str(getattr(profile, "provider_id", "") or "").strip(),
        str(getattr(provider, "kind", "") or "").strip(),
        str(getattr(provider, "base_url", "") or "").strip().rstrip("/").lower(),
        str(getattr(client, "profile_id", "") or "").strip(),
        str(getattr(profile, "model", "") or "").strip(),
        wire_protocol,
        str(getattr(route, "adapter_id", "") or "").strip(),
    )


def _llm_effective_route_id(client: Any) -> str:
    route_id_builder = getattr(client, "effective_route_id", None)
    if callable(route_id_builder):
        try:
            route_id = str(route_id_builder() or "").strip()
            if route_id:
                return route_id
        except Exception:
            pass
    material = "\x1f".join(_llm_effective_route_identity(client)).encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def _llm_route_trace_fields(
    invocation_context: LLMInvocationContext,
    client: Any,
    *,
    route_attempt: int,
    route_id: str,
) -> Dict[str, Any]:
    """Build bounded correlation fields shared by route lifecycle events."""
    metadata = invocation_context.to_metadata(client=client)
    route = getattr(client, "protocol_route", None)
    profile = getattr(client, "profile", None)
    provider = getattr(client, "provider", None)
    return {
        "sessionId": str(metadata.get("sessionId") or "").strip(),
        "turnId": str(metadata.get("turnId") or metadata.get("llmRunId") or "").strip(),
        "runId": str(metadata.get("llmRunId") or "").strip(),
        "agentId": str(metadata.get("agentId") or "").strip(),
        "invocationId": str(metadata.get("invocationId") or "").strip(),
        "routeAttempt": max(1, int(route_attempt)),
        "routeId": str(route_id or "").strip(),
        "profileId": str(getattr(client, "profile_id", "") or "").strip(),
        "provider": str(getattr(provider, "kind", "") or "").strip(),
        "model": str(getattr(profile, "model", "") or "").strip(),
        "protocol": str(
            getattr(getattr(route, "wire_protocol", None), "value", "")
            or getattr(route, "protocol", "")
            or ""
        ).strip(),
    }


def _record_llm_route_success(
    *,
    trace_fields: Dict[str, Any],
    duration_ms: int,
    streamed: bool,
    recorder: Any = None,
) -> None:
    """Close one successful provider route without claiming the whole turn ended."""
    fn = recorder or _record_agent_scene_event
    fn(
        "llm_route",
        "llm_route_attempt_succeeded",
        message="LLM effective route attempt succeeded.",
        fields={
            **dict(trace_fields or {}),
            "durationMs": max(0, int(duration_ms or 0)),
            "streamed": bool(streamed),
        },
        outcome="succeeded",
    )


def _record_agent_tool_surface_event(tool_names: List[str], *, recorder: Any = None) -> None:
    fn = recorder or _record_agent_scene_event
    names = [str(name or "").strip() for name in tool_names if str(name or "").strip()]
    group_counts: Dict[str, int] = {}
    for name in names:
        group = _TOOL_SURFACE_GROUPS.get(name, "other")
        group_counts[group] = group_counts.get(group, 0) + 1
    fn(
        "tool_surface",
        "agent.tool_surface.visible",
        message="Agent visible tool surface prepared.",
        fields={
            "toolCount": len(names),
            "groups": group_counts,
            "coreChatToolsPresent": sorted(name for name in _CORE_CHAT_TOOL_NAMES if name in set(names)),
            "restrictedSpecialToolsPresent": sorted(
                name
                for name in names
                if name.startswith("knowledge_")
                or name.startswith("research_")
                or name in {"computer_use_task_tool"}
            ),
        },
    )


def _context_compression_trigger_source(reason: str) -> str:
    normalized = str(reason or "").strip().lower()
    if not normalized:
        return "auto"
    if normalized.startswith("level:"):
        return "auto"
    if "context limit" in normalized or "context_length" in normalized or "超出最大上下文" in normalized:
        return "provider_limit"
    return "manual"


def _format_tool_result_replacement_summary(state: Dict[str, Any]) -> str:
    replacements = list((state or {}).get("replacements") or [])
    if not replacements:
        return ""
    lines = ["工具结果压缩引用:"]
    for item in replacements[:8]:
        reference = str(item.get("reference") or "").strip()
        tool_call_id = str(item.get("toolCallId") or "").strip()
        tool_name = str(item.get("toolName") or "").strip() or "unknown"
        original_chars = int(item.get("originalChars") or 0)
        digest = str(item.get("sha256") or "").strip()[:16]
        lines.append(
            f"- {tool_name} tool_call_id={tool_call_id} reference={reference} chars={original_chars} sha256={digest}"
        )
    if len(replacements) > 8:
        lines.append(f"- 其余 {len(replacements) - 8} 个工具结果也已按同一规则替换。")
    lines.append("说明: 这些替换只发生在上下文压缩输入中，原始工具结果仍以会话历史或 turn journal 为事实源。")
    return "\n".join(lines)


SUBAGENT_RESULT_MARKER = "__VIBELUTION_SUBAGENT_RESULT__"


def _runtime_agent_binding_from_env(
    explicit_binding: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    key_map = {
        "agentId": "VIBELUTION_AGENT_ID",
        "profileId": "VIBELUTION_AGENT_PROFILE_ID",
        "llmSlot": "VIBELUTION_AGENT_LLM_SLOT",
        "directSessionId": "VIBELUTION_AGENT_DIRECT_SESSION_ID",
        "workspacePath": "VIBELUTION_AGENT_WORKSPACE_PATH",
        "supervisedRole": "VIBELUTION_SUPERVISED_ROLE",
    }
    if explicit_binding is not None:
        runtime = {
            target_key: value
            for target_key in key_map
            if (value := str(explicit_binding.get(target_key) or "").strip())
        }
        llm_bindings = normalize_agent_llm_bindings(explicit_binding.get("llmBindings"))
        if llm_bindings:
            runtime["llmBindings"] = llm_bindings
        return runtime
    runtime: Dict[str, Any] = {
        target_key: value
        for target_key, env_key in key_map.items()
        if (value := str(os.environ.get(env_key) or "").strip())
    }
    llm_bindings = _runtime_agent_llm_bindings_from_env(str(runtime.get("llmSlot") or "dialogue"))
    if llm_bindings:
        runtime["llmBindings"] = llm_bindings
    return runtime


def _runtime_agent_llm_bindings_from_env(default_slot: str) -> Dict[str, Dict[str, str]]:
    bindings: Dict[str, Dict[str, str]] = {}
    raw_bindings = str(os.environ.get("VIBELUTION_AGENT_LLM_BINDINGS_JSON") or "").strip()
    if raw_bindings:
        try:
            payload = json.loads(raw_bindings)
        except json.JSONDecodeError as exc:
            raise AgentLlmResolutionError("Runtime Agent LLM bindings env is not valid JSON.") from exc
        bindings = normalize_agent_llm_bindings(payload)
        if not bindings:
            raise AgentLlmResolutionError("Runtime Agent LLM bindings env did not contain any safe modelId.")
    model_id = str(os.environ.get("VIBELUTION_AGENT_LLM_MODEL_ID") or "").strip()
    if model_id:
        slot = str(default_slot or "dialogue").strip() or "dialogue"
        current_model_id = str((bindings.get(slot) or {}).get("modelId") or "").strip()
        if current_model_id and current_model_id != model_id:
            raise AgentLlmResolutionError(
                f"Runtime Agent LLM model id conflicts with bindings JSON for slot {slot}."
            )
        bindings[slot] = {"modelId": model_id}
    return bindings


def _turn_runtime_from_env() -> Dict[str, str]:
    key_map = {
        "mode": "VIBELUTION_TURN_MODE",
        "runKind": "VIBELUTION_TURN_RUN_KIND",
        "runId": "VIBELUTION_TURN_RUN_ID",
        "sessionId": "VIBELUTION_TURN_SESSION_ID",
        "agentId": "VIBELUTION_TURN_AGENT_ID",
        "llmSlot": "VIBELUTION_TURN_LLM_SLOT",
        "modelId": "VIBELUTION_TURN_MODEL_ID",
        "cacheScope": "VIBELUTION_TURN_CACHE_SCOPE",
        "promptCachePartition": "VIBELUTION_TURN_PROMPT_CACHE_PARTITION",
    }
    return {
        target_key: value
        for target_key, env_key in key_map.items()
        if (value := str(os.environ.get(env_key) or "").strip())
    }


def _safe_turn_runtime_metadata(runtime: Dict[str, str]) -> Dict[str, Any]:
    if not runtime:
        return {}
    metadata: Dict[str, Any] = {
        key: value
        for key in ("mode", "runKind", "runId", "sessionId", "agentId", "llmSlot", "modelId", "cacheScope")
        if (value := str(runtime.get(key) or "").strip())
    }
    partition = str(runtime.get("promptCachePartition") or "").strip()
    if partition:
        metadata["promptCachePartitionHash"] = hashlib.sha256(partition.encode("utf-8", errors="ignore")).hexdigest()[:12]
        metadata["promptCachePartitionChars"] = len(partition)
    return metadata


def _runtime_mental_model_override_from_env() -> Optional[bool]:
    raw = str(os.environ.get("VIBELUTION_SUPERVISED_MENTAL_MODEL_ENABLED") or "").strip().lower()
    if raw in {"1", "true", "yes", "on", "enabled"}:
        return True
    if raw in {"0", "false", "no", "off", "disabled"}:
        return False
    mode = str(os.environ.get("VIBELUTION_SUPERVISED_MENTAL_MODEL_MODE") or "").strip().lower()
    if mode == "enabled":
        return True
    if mode == "disabled":
        return False
    return None
