# -*- coding: utf-8 -*-
"""Agent 模式策略与模式扩展入口。

把运行模式定义、模式策略和模式级输入协议收口在 core/orchestration，
避免把未来的 chat / plan / query 等扩展继续堆在 agent.py。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from core.infrastructure.runtime_input import (
    build_chat_user_message,
    build_external_request_message,
    build_supervised_evolution_request_message,
)

if TYPE_CHECKING:
    from config import AppConfig


class AgentMode(str, Enum):
    CHAT = "chat"
    SELF_EVOLUTION = "self_evolution"
    SUPERVISED_EVOLUTION = "supervised_evolution"


def _decode_binary(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    return value


def _maybe_json(value: Any) -> Any:
    value = _decode_binary(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _mapping_get(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            return mapping.get(key)
    return None


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    value = _decode_binary(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    return default


def _normalize_mode_text(value: Any, *, default: str) -> str:
    value = _maybe_json(value)
    if isinstance(value, AgentMode):
        value = value.value
    if isinstance(value, Mapping):
        extracted = _mapping_get(
            value, "mode", "value", "text", "name", "agentMode", "agent_mode"
        )
        if extracted is None:
            value = default
        else:
            return _normalize_mode_text(extracted, default=default)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        if len(value) == 1:
            return _normalize_mode_text(value[0], default=default)
        value = default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    text = str(value if value is not None else default).strip().lower()
    text = text.replace("-", "_").replace(" ", "_")
    if text:
        return text
    fallback = str(default or AgentMode.SELF_EVOLUTION.value).strip().lower()
    fallback = fallback.replace("-", "_").replace(" ", "_")
    return fallback or AgentMode.SELF_EVOLUTION.value


@dataclass(frozen=True)
class ModePolicy:
    mode: AgentMode
    orchestrator_kind: str
    keep_multi_turn_context: bool
    allow_auto_loop: bool
    capture_chat_dataset_candidates: bool
    reset_context_before_turn: bool
    reset_context_between_cases: bool
    allow_direct_supervised_payload: bool
    finish_after_direct_response: bool
    runtime_input_builder: Callable[[str], object]


def normalize_agent_mode(value: str | AgentMode | None, *, default: str = AgentMode.SELF_EVOLUTION.value) -> AgentMode:
    if isinstance(value, AgentMode):
        return value
    text = _normalize_mode_text(value, default=default)
    try:
        return AgentMode(text)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in AgentMode)
        raise ValueError(f"未知 Agent mode: {value!r}；可选: {allowed}") from exc


def is_mode_enabled(mode: AgentMode, config: "AppConfig") -> bool:
    modes_cfg = getattr(getattr(config, "agent", None), "modes", None)
    text = _normalize_mode_text(getattr(mode, "value", mode), default="")
    if text == AgentMode.CHAT:
        return _coerce_bool(getattr(modes_cfg, "chat_enabled", True), True)
    if text == AgentMode.SUPERVISED_EVOLUTION:
        return _coerce_bool(getattr(modes_cfg, "supervised_evolution_enabled", True), True)
    return _coerce_bool(getattr(modes_cfg, "self_evolution_enabled", True), True)


def resolve_mode_policy(mode: str | AgentMode | None, config: "AppConfig") -> ModePolicy:
    agent_cfg = getattr(config, "agent", None)
    default_mode = getattr(agent_cfg, "default_mode", AgentMode.SELF_EVOLUTION.value)
    normalized = normalize_agent_mode(mode, default=default_mode)
    if not is_mode_enabled(normalized, config):
        raise ValueError(f"Agent mode `{normalized.value}` 当前已在配置中禁用")

    if normalized == AgentMode.CHAT:
        return ModePolicy(
            mode=normalized,
            orchestrator_kind="chat",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=True,
            reset_context_before_turn=False,
            reset_context_between_cases=False,
            allow_direct_supervised_payload=False,
            finish_after_direct_response=False,
            runtime_input_builder=build_chat_user_message,
        )
    if normalized == AgentMode.SUPERVISED_EVOLUTION:
        return ModePolicy(
            mode=normalized,
            orchestrator_kind="evolution",
            keep_multi_turn_context=True,
            allow_auto_loop=False,
            capture_chat_dataset_candidates=False,
            reset_context_before_turn=True,
            reset_context_between_cases=True,
            allow_direct_supervised_payload=True,
            finish_after_direct_response=False,
            runtime_input_builder=build_supervised_evolution_request_message,
        )
    return ModePolicy(
        mode=normalized,
        orchestrator_kind="evolution",
        keep_multi_turn_context=True,
        allow_auto_loop=True,
        capture_chat_dataset_candidates=False,
        reset_context_before_turn=False,
        reset_context_between_cases=False,
        allow_direct_supervised_payload=False,
        finish_after_direct_response=False,
        runtime_input_builder=build_external_request_message,
    )


__all__ = [
    "AgentMode",
    "ModePolicy",
    "is_mode_enabled",
    "normalize_agent_mode",
    "resolve_mode_policy",
]
