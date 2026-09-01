# -*- coding: utf-8 -*-
"""回合停机与收尾控制器。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import AIMessage

from core.llm.types import TurnOutcome as LLMTurnOutcome


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value)


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
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


def _maybe_json(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _as_mapping(value: Any) -> Dict[str, Any]:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _coerce_message_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("messages")
        if nested is None:
            nested = value.get("items")
        if nested is None:
            nested = value.get("history")
        if nested is not None:
            return _coerce_message_list(nested)
        if any(key in value for key in ("role", "content", "type", "tool_calls", "toolCalls")):
            return [dict(value)]
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _coerce_item_list(value: Any) -> list:
    value = _maybe_json(value)
    if value is None or isinstance(value, (str, bytes, bytearray, memoryview)):
        return []
    if isinstance(value, Mapping):
        nested = value.get("tool_calls")
        if nested is None:
            nested = value.get("toolCalls")
        if nested is None:
            nested = value.get("items")
        if nested is not None:
            return _coerce_item_list(nested)
        return [dict(value)] if value else []
    try:
        return list(value)
    except TypeError:
        return []


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, bool) or value is None:
        return max(0, int(default or 0))
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(default or 0))


@dataclass
class LifecycleDecision:
    continue_main_loop: bool = True
    break_round: bool = False
    pending_action: Optional[str] = None
    info_log: Optional[str] = None


@dataclass
class TurnFinalization:
    last_turn_failed: bool
    turn_success: bool
    ui_status: str
    turn_stats: Dict[str, int]
    max_iteration_exhausted_without_final_answer: bool = False
    stop_reason: str = ""


@dataclass
class TurnMessageCarryover:
    messages: Optional[list]
    goal: str
    turn_identity: str = ""
    terminal: bool = False


@dataclass(frozen=True)
class LLMIterationDecision:
    outcome: LLMTurnOutcome
    tool_calls: tuple[Dict[str, Any], ...]
    should_execute_tools: bool
    should_finish: bool
    should_stop_unsuccessfully: bool


class TurnOutcomeController:
    """集中管理停机判定、生命周期出口与回合收尾。"""

    def __init__(
        self,
        *,
        max_consecutive_failures: int,
        get_attention_snapshot: Callable[[], Dict],
    ) -> None:
        self.max_consecutive_failures = max_consecutive_failures
        self._get_attention_snapshot = get_attention_snapshot

    @staticmethod
    def decide_llm_iteration(outcome: LLMTurnOutcome) -> LLMIterationDecision:
        """Derive Agent control flow exclusively from the canonical outcome."""
        if not isinstance(outcome, LLMTurnOutcome):
            raise ValueError("Agent control requires canonical TurnOutcome")
        if not outcome.terminal_event_seen:
            raise ValueError("canonical TurnOutcome is missing terminal evidence")
        tool_calls = tuple(
            {
                "id": call.call_id,
                "name": call.name,
                "args": dict(call.arguments),
                "canonical_tool_call": call,
            }
            for call in outcome.tool_calls
        )
        return LLMIterationDecision(
            outcome=outcome,
            tool_calls=tool_calls,
            should_execute_tools=outcome.kind == "tool_calls" and bool(tool_calls),
            should_finish=outcome.kind == "final_answer",
            should_stop_unsuccessfully=outcome.kind in {"incomplete", "failed", "cancelled"},
        )

    def should_stop_after_llm_failure(
        self,
        *,
        category: Optional[str],
        retryable: bool,
        consecutive_failures: int,
        iteration: int,
        attempts: int = 0,
        max_attempts: int = 0,
    ) -> Optional[str]:
        category_text = _coerce_text(category).strip()
        retryable_flag = _coerce_bool(retryable, True)
        if category_text and not retryable_flag:
            return f"遇到不可重试错误 `{category_text}`，当前轮次直接结束。"
        effective_max_attempts = _coerce_nonnegative_int(max_attempts)
        effective_attempts = _coerce_nonnegative_int(attempts)
        consecutive = _coerce_nonnegative_int(consecutive_failures)
        retry_budget_exhausted = (
            effective_max_attempts > 0
            and max(effective_attempts, consecutive) >= effective_max_attempts
        )
        if category_text in {"server_error", "rate_limit"} and retry_budget_exhausted:
            return f"模型 provider 暂时不可用（`{category_text}`），本轮已用尽重试预算，直接失败收口。"
        if category_text == "network_error" and retry_budget_exhausted:
            return "网络失败已连续出现且重连预算已耗尽，当前轮次提前结束。"
        if category_text == "timeout" and retry_budget_exhausted:
            return "连续超时且重试预算已耗尽，当前轮次提前结束。"
        stop_limit = effective_max_attempts or self.max_consecutive_failures
        if consecutive >= stop_limit:
            return f"LLM 连续失败达到 {stop_limit} 次，当前轮次结束。"
        return None

    @staticmethod
    def is_readonly_platform_judgment_complete(goal: str, visible_text: str) -> bool:
        """识别只读平台兼容性判断已给出明确结论，可直接收束。"""
        goal_text = _coerce_text(goal).strip().lower()
        answer_text = _coerce_text(visible_text).strip().lower()
        if not goal_text or not answer_text:
            return False
        readonly_markers = [
            "不要修改代码",
            "不要改代码",
            "只做一次最小验证",
            "只做最小验证",
            "只做判断",
            "read-only",
        ]
        platform_markers = [
            "windows",
            "当前系统",
            "命令平台",
            "平台识别",
            "/dev/null",
            "tail -5",
            "unix",
        ]
        if not any(marker in goal_text for marker in readonly_markers):
            return False
        if not any(marker in goal_text for marker in platform_markers):
            return False

        conclusion_markers = [
            "不应该执行",
            "不应执行",
            "不能直接执行",
            "无法直接执行",
            "是否应执行 | **否**",
            "是否应执行：否",
            "是否应执行: 否",
        ]
        evidence_markers = [
            "/dev/null",
            "tail",
            "unix",
            "2>$null",
            "select-object",
            "powershell",
        ]
        return any(marker in answer_text for marker in conclusion_markers) and any(
            marker in answer_text for marker in evidence_markers
        )

    @staticmethod
    def has_successful_close_without_restart(messages: list) -> bool:
        def normalize_status(value: Any) -> str:
            return str(value or "").lstrip("\ufeff").strip().lower()

        close_seen = False
        restart_seen = False
        for msg in messages:
            tool_name = getattr(msg, "name", "") or ""
            content = getattr(msg, "content", "") or ""
            if isinstance(content, list):
                content = "\n".join(str(item) for item in content)
            text = str(content or "")
            normalized_content_text = text.replace("\ufeff", "")
            if "close_evolution_transaction_tool" in tool_name:
                payload = None
                if isinstance(content, str):
                    try:
                        parsed = json.loads(text.strip())
                    except (json.JSONDecodeError, TypeError, ValueError):
                        parsed = None
                    else:
                        if isinstance(parsed, dict):
                            payload = parsed
                elif isinstance(content, dict):
                    payload = content
                success_statuses = {"success", "ok"}
                if isinstance(payload, dict):
                    status = normalize_status(payload.get("status"))
                    transaction_status = normalize_status(payload.get("transaction_status"))
                    if status and status not in {"success", "ok"}:
                        continue
                    if transaction_status and transaction_status not in success_statuses:
                        continue
                    if status in success_statuses or transaction_status in success_statuses:
                        close_seen = True
                else:
                    status_match = re.search(r'"status"\s*:\s*"([^"]+)"', normalized_content_text, re.IGNORECASE)
                    if status_match:
                        if normalize_status(status_match.group(1)) in {"success", "ok"}:
                            close_seen = True
                        continue
                    transaction_status_match = re.search(
                        r'"transaction_status"\s*:\s*"([^"]+)"',
                        normalized_content_text,
                        re.IGNORECASE,
                    )
                    if (
                        transaction_status_match
                        and normalize_status(transaction_status_match.group(1)) in {"success", "ok"}
                    ):
                        close_seen = True
            if "trigger_self_restart_tool" in tool_name:
                restart_seen = True
            if "重启触发成功" in text or "触发自我重启" in text:
                restart_seen = True

        return close_seen and not restart_seen

    @staticmethod
    def should_finish_single_turn_after_direct_response(
        *,
        single_turn_mode_active: bool,
        tool_calls: list,
        visible_text: str,
        active_goal: str = "",
        active_evolution_txn_id: Optional[str] = None,
    ) -> bool:
        if not _coerce_bool(single_turn_mode_active, False):
            return False
        if _coerce_text(active_evolution_txn_id).strip():
            return False
        if _coerce_item_list(tool_calls):
            return False
        return bool(_coerce_text(visible_text).strip())

    @staticmethod
    def classify_turn_carryover(
        payload: Optional[Dict[str, Any]],
        *,
        expected_turn_identity: str,
    ) -> str:
        payload_map = _as_mapping(payload)
        if not payload_map:
            return "absent"
        if _coerce_bool(payload_map.get("terminal"), False):
            return "terminal"
        turn_identity = _coerce_text(
            payload_map.get("turnIdentity") or payload_map.get("turn_identity")
        ).strip()
        expected_identity = _coerce_text(expected_turn_identity).strip()
        if not turn_identity or not expected_identity:
            return "missing_identity"
        if turn_identity != expected_identity:
            return "identity_mismatch"
        if not _coerce_text(payload_map.get("goal")).strip() or not _coerce_message_list(
            payload_map.get("messages")
        ):
            return "invalid"
        return "accepted"

    @staticmethod
    def can_resume_turn_messages(
        *,
        active_turn_messages: Optional[list],
        active_turn_goal: str,
        effective_goal: str,
        user_prompt: str,
    ) -> bool:
        if not _coerce_message_list(active_turn_messages):
            return False
        active_goal = _coerce_text(active_turn_goal).strip()
        effective = _coerce_text(effective_goal).strip()
        prompt = _coerce_text(user_prompt)
        if not active_goal:
            return False
        if active_goal != effective:
            return False
        if prompt and prompt != "开始自主进化" and prompt != effective:
            return False
        return True

    @classmethod
    def prepare_turn_messages(
        cls,
        *,
        system_prompt: Any,
        user_prompt: str,
        effective_goal: str,
        active_turn_messages: Optional[list],
        active_turn_goal: str,
        build_system_message: Callable[[Any], Any],
        build_external_request_message: Callable[[str], Any],
        allow_append_user_message: bool = False,
    ) -> tuple[list, bool]:
        if cls.can_resume_turn_messages(
            active_turn_messages=active_turn_messages,
            active_turn_goal=active_turn_goal,
            effective_goal=effective_goal,
            user_prompt=user_prompt,
        ):
            messages = cls.sanitize_provider_turn_carryover(_coerce_message_list(active_turn_messages))
            if messages:
                messages[0] = build_system_message(system_prompt)
            else:
                messages = [
                    build_system_message(system_prompt),
                    build_external_request_message(user_prompt),
                ]
            return messages, True
        if _coerce_bool(allow_append_user_message, False) and _coerce_message_list(active_turn_messages):
            messages = cls.sanitize_provider_turn_carryover(_coerce_message_list(active_turn_messages))
            if messages:
                messages[0] = build_system_message(system_prompt)
            else:
                messages = [build_system_message(system_prompt)]
            messages.append(build_external_request_message(user_prompt))
            return messages, True
        return [
            build_system_message(system_prompt),
            build_external_request_message(user_prompt),
        ], False

    @staticmethod
    def insert_volatile_context_before_current_user(*, messages: list, context_messages: list) -> list:
        """Keep stable chat history before volatile runtime context.

        Chat turns append the current user message last.  Inserting per-turn
        runtime/guidance/skill context immediately before that current user
        keeps the older history as part of the stable provider-cache prefix
        while still making volatile context available to the current turn.
        """

        context = _coerce_message_list(context_messages)
        if not context:
            return _coerce_message_list(messages)
        normalized = TurnOutcomeController.sanitize_provider_turn_carryover(_coerce_message_list(messages))
        # No user-message fallback (resume/carryover payloads without a user
        # turn): append after the tail instead of index 1.  Inserting volatile
        # context right after the system message would place it ahead of the
        # existing history and invalidate the stable provider-cache prefix.
        insert_at = len(normalized)
        for index in range(len(normalized) - 1, -1, -1):
            item = normalized[index]
            role = ""
            if isinstance(item, Mapping):
                role = _coerce_text(item.get("role")).strip().lower()
            else:
                role = _coerce_text(getattr(item, "type", "")).strip().lower()
            if role in {"user", "human"}:
                insert_at = index
                break
        return normalized[:insert_at] + context + normalized[insert_at:]

    @staticmethod
    def insert_static_context_after_system(*, messages: list, context_messages: list) -> list:
        """Place stable runtime context after the primary system prompt.

        This keeps the durable system prompt and stable Agent/project context
        ahead of chat history, while per-turn volatile context can still be
        inserted later immediately before the current user message.
        """

        context = _coerce_message_list(context_messages)
        if not context:
            return _coerce_message_list(messages)
        normalized = _coerce_message_list(messages)
        insert_at = 0
        if normalized:
            first = normalized[0]
            if isinstance(first, Mapping):
                role = _coerce_text(first.get("role")).strip().lower()
            else:
                role = _coerce_text(getattr(first, "type", "")).strip().lower()
            if role in {"system"}:
                insert_at = 1
        return normalized[:insert_at] + context + normalized[insert_at:]

    @staticmethod
    def finish_turn_message_carryover(
        *,
        messages: list,
        lifecycle_action: Optional[str],
        active_goal: str,
        turn_identity: str = "",
    ) -> TurnMessageCarryover:
        if lifecycle_action in {"restart", "hibernated", "turn_complete"}:
            return TurnMessageCarryover(
                messages=None,
                goal="",
                turn_identity=_coerce_text(turn_identity).strip(),
                terminal=True,
            )
        return TurnMessageCarryover(
            messages=TurnOutcomeController.sanitize_provider_turn_carryover(_coerce_message_list(messages)),
            goal=_coerce_text(active_goal),
            turn_identity=_coerce_text(turn_identity).strip(),
            terminal=False,
        )

    @staticmethod
    def sanitize_provider_turn_carryover(messages: list) -> list:
        """Keep resumed turn context provider-safe without discarding useful evidence.

        Complete live pairs are preserved as ``assistant.tool_calls`` followed by
        matching ``ToolMessage``/``role=tool`` messages.  Anything that would be
        illegal in the next provider payload is demoted to ordinary assistant
        text, so a later "继续" can still see what happened without sending a
        dangling tool protocol frame.
        """

        sanitized: list = []
        pending_ids: list[str] = []
        pending_assistant_index = -1
        pending_result_indices: list[int] = []

        def demote_pending_chain() -> None:
            nonlocal pending_ids, pending_assistant_index, pending_result_indices
            if 0 <= pending_assistant_index < len(sanitized):
                sanitized[pending_assistant_index] = _demote_assistant_tool_calls(
                    sanitized[pending_assistant_index]
                )
            for result_index in pending_result_indices:
                if 0 <= result_index < len(sanitized):
                    sanitized[result_index] = _demote_tool_result_message(sanitized[result_index])
            pending_ids = []
            pending_assistant_index = -1
            pending_result_indices = []

        for message in _coerce_message_list(messages):
            role = _message_role(message)
            if role == "assistant":
                if pending_ids:
                    demote_pending_chain()
                sanitized.append(message)
                tool_call_ids = _message_tool_call_ids(message)
                if tool_call_ids:
                    pending_ids = list(tool_call_ids)
                    pending_assistant_index = len(sanitized) - 1
                    pending_result_indices = []
                continue
            if role == "tool":
                tool_call_id = _message_tool_result_id(message)
                if tool_call_id and tool_call_id in pending_ids:
                    sanitized.append(message)
                    pending_result_indices.append(len(sanitized) - 1)
                    pending_ids = [item for item in pending_ids if item != tool_call_id]
                    if not pending_ids:
                        pending_assistant_index = -1
                        pending_result_indices = []
                    continue
                if pending_ids:
                    demote_pending_chain()
                sanitized.append(_demote_tool_result_message(message))
                continue
            if pending_ids:
                demote_pending_chain()
            sanitized.append(message)
        if pending_ids:
            demote_pending_chain()
        return sanitized

    @staticmethod
    def handle_lifecycle_action(lifecycle_action: Optional[str]) -> LifecycleDecision:
        if lifecycle_action == "restart":
            return LifecycleDecision(
                continue_main_loop=False,
                pending_action="restart",
            )
        if lifecycle_action == "hibernated":
            return LifecycleDecision(
                continue_main_loop=False,
                pending_action="hibernated",
            )
        if lifecycle_action == "turn_complete":
            return LifecycleDecision(
                break_round=True,
                info_log="当前演化事务已成功关账，本轮停止并等待下一轮。",
            )
        if lifecycle_action == "tool_budget_exhausted":
            # Hard stop only: do not keep iterating for wrap-up probes.
            # The next user message installs a fresh execution authorization budget.
            return LifecycleDecision(
                break_round=True,
                info_log="本回合工具额度已用尽，停止工具循环；下一用户消息重新计数。",
            )
        return LifecycleDecision()

    def finalize_round(self, *, round_state) -> TurnFinalization:
        last_turn_failed = round_state.consecutive_failures > 0
        exhausted_without_final_answer = round_state.exhausted_without_final_answer()
        turn_success = round_state.finish_success(last_turn_failed)
        stop_reason = ""
        if exhausted_without_final_answer:
            stop_reason = (
                f"已达到本轮最大迭代次数 {round_state.max_iterations}，"
                "模型仍在调用工具或未输出最终可见回答；本轮未完成，请发送“继续”或缩小任务后重试。"
            )
        return TurnFinalization(
            last_turn_failed=last_turn_failed,
            turn_success=turn_success,
            ui_status="SUCCESS" if turn_success else ("ERROR" if last_turn_failed else "IDLE"),
            turn_stats=round_state.final_stats(),
            max_iteration_exhausted_without_final_answer=exhausted_without_final_answer,
            stop_reason=stop_reason,
        )


def _message_role(message: Any) -> str:
    if isinstance(message, Mapping):
        role = _coerce_text(message.get("role")).strip().lower()
    else:
        role = _coerce_text(getattr(message, "type", "")).strip().lower()
    if role == "ai":
        return "assistant"
    if role == "human":
        return "user"
    return role


def _message_tool_call_ids(message: Any) -> list[str]:
    raw_tool_calls: Any = []
    if isinstance(message, Mapping):
        raw_tool_calls = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if not raw_tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, Mapping):
                raw_tool_calls = additional_kwargs.get("tool_calls") or []
    ids: list[str] = []
    for index, item in enumerate(_coerce_item_list(raw_tool_calls)):
        if not isinstance(item, Mapping):
            continue
        tool_call_id = _coerce_text(
            item.get("id") or item.get("tool_call_id") or item.get("toolCallId")
        ).strip()
        if not tool_call_id:
            tool_call_id = f"tool_{index}"
        ids.append(tool_call_id)
    return ids


def _message_tool_result_id(message: Any) -> str:
    if isinstance(message, Mapping):
        return _coerce_text(
            message.get("tool_call_id") or message.get("toolCallId") or message.get("id")
        ).strip()
    return _coerce_text(getattr(message, "tool_call_id", "") or getattr(message, "id", "")).strip()


def _message_content_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, Mapping) else getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, Mapping):
                parts.append(_coerce_text(item.get("text") or item.get("content")))
            else:
                parts.append(_coerce_text(item))
        return "".join(parts).strip()
    return _coerce_text(content).strip()


def _tool_call_name(item: Any) -> str:
    if not isinstance(item, Mapping):
        return "unknown_tool"
    function = _as_mapping(item.get("function"))
    return _coerce_text(
        item.get("name") or item.get("toolName") or function.get("name") or "unknown_tool"
    ).strip()


def _message_tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, Mapping):
        raw_tool_calls = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if not raw_tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, Mapping):
                raw_tool_calls = additional_kwargs.get("tool_calls") or []
    return [dict(item) for item in _coerce_item_list(raw_tool_calls) if isinstance(item, Mapping)]


def _demote_assistant_tool_calls(message: Any) -> AIMessage:
    content_parts = [_message_content_text(message)]
    for item in _message_tool_calls(message):
        content_parts.append(f"历史工具调用未返回结果: {_tool_call_name(item)}")
    content = "\n\n".join(part for part in content_parts if part).strip()
    return AIMessage(content=content or "历史工具调用未返回结果: unknown_tool")


def _demote_tool_result_message(message: Any) -> AIMessage:
    content = _message_content_text(message)
    name = ""
    if isinstance(message, Mapping):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), Mapping) else {}
        name = _coerce_text(
            metadata.get("toolName") or metadata.get("tool_name") or message.get("name")
        ).strip()
    else:
        name = _coerce_text(getattr(message, "name", "")).strip()
    name = name or _tool_name_from_content(content) or "unknown_tool"
    if content.startswith("历史工具结果:"):
        return AIMessage(content=content)
    return AIMessage(content=f"历史工具结果: {name}\n{content}".strip())


def _tool_name_from_content(content: str) -> str:
    first_line = str(content or "").splitlines()[0].strip() if str(content or "").splitlines() else ""
    for marker in ("历史工具调用:", "历史工具调用：", "历史工具结果:", "历史工具结果："):
        if first_line.startswith(marker):
            return first_line[len(marker):].strip().split()[0] if first_line[len(marker):].strip() else ""
    return ""
