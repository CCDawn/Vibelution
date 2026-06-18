# -*- coding: utf-8 -*-
"""回合停机与收尾控制器。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import AIMessage


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
        if category and not retryable:
            return f"遇到不可重试错误 `{category}`，当前轮次直接结束。"
        effective_max_attempts = max(0, int(max_attempts or 0))
        effective_attempts = max(0, int(attempts or 0))
        retry_budget_exhausted = (
            effective_max_attempts > 0
            and max(effective_attempts, max(0, int(consecutive_failures or 0))) >= effective_max_attempts
        )
        if category in {"server_error", "rate_limit"} and retry_budget_exhausted:
            return f"模型 provider 暂时不可用（`{category}`），本轮已用尽重试预算，直接失败收口。"
        if category == "network_error" and retry_budget_exhausted:
            return "网络失败已连续出现且重连预算已耗尽，当前轮次提前结束。"
        if category == "timeout" and retry_budget_exhausted:
            return "连续超时且重试预算已耗尽，当前轮次提前结束。"
        stop_limit = effective_max_attempts or self.max_consecutive_failures
        if consecutive_failures >= stop_limit:
            return f"LLM 连续失败达到 {stop_limit} 次，当前轮次结束。"
        return None

    def should_stop_for_convergence(
        self,
        *,
        iteration: int,
        no_new_evidence_steps: int,
        consecutive_tool_only_steps: int = 0,
        consecutive_bookkeeping_tool_only_steps: int = 0,
        delegation_failures: int,
        total_tool_calls: int,
        substantive_tool_calls: int = 0,
    ) -> Optional[str]:
        snapshot = self._get_attention_snapshot() or {}
        if snapshot.get("convergence_state") == "ready_to_stop":
            return snapshot.get("stop_reason") or "当前轮已满足停止条件，直接收束。"
        if delegation_failures >= 1 and snapshot.get("diagnostic_drift") and iteration >= 2:
            return "委派未带来新证据，且当前仍处于诊断漂移，直接结束本轮并等待下一轮重规划。"
        if (
            snapshot.get("scope_frozen")
            and snapshot.get("feedback_loop_ready")
            and no_new_evidence_steps >= 2
            and iteration >= 2
        ):
            detail = snapshot.get("stop_reason") or "当前锚点已完成主要收窄。"
            return f"当前轮范围已冻结，且连续没有新增证据，直接收束。{detail}"
        if (
            not snapshot.get("feedback_loop_ready")
            and total_tool_calls >= 4
            and no_new_evidence_steps >= 2
            and iteration >= 2
        ):
            return "当前仍未形成最小反馈环，且工具调用已开始堆积，本轮先停止并等待下一轮重建观测闭环。"
        if no_new_evidence_steps >= 3 and iteration >= 3:
            return "连续多步没有新增证据，本轮直接收束，避免继续空转。"
        if total_tool_calls >= 6 and not snapshot.get("last_validation_summary") and no_new_evidence_steps >= 2:
            return "工具调用已明显堆积但没有形成验证闭环，本轮直接结束。"
        return None

    @staticmethod
    def is_readonly_platform_judgment_complete(goal: str, visible_text: str) -> bool:
        """识别只读平台兼容性判断已给出明确结论，可直接收束。"""
        goal_text = (goal or "").strip().lower()
        answer_text = (visible_text or "").strip().lower()
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

    @classmethod
    def should_skip_convergence_stop_for_pending_restart(
        cls,
        *,
        expects_restart_after_transaction_close: bool,
        messages: list,
    ) -> bool:
        if not expects_restart_after_transaction_close:
            return False
        return cls.has_successful_close_without_restart(messages)

    @staticmethod
    def should_finish_single_turn_after_direct_response(
        *,
        single_turn_mode_active: bool,
        tool_calls: list,
        visible_text: str,
        active_goal: str = "",
        active_evolution_txn_id: Optional[str] = None,
    ) -> bool:
        if not single_turn_mode_active:
            return False
        if active_evolution_txn_id:
            return False
        if tool_calls:
            return False
        normalized_goal = str(active_goal or "").strip().lower()
        required_tool_markers = (
            "open_evolution_transaction_tool",
            "close_evolution_transaction_tool",
            "write_file_tool",
            "python_lint_tool",
            "trigger_self_restart_tool",
        )
        if any(marker in normalized_goal for marker in required_tool_markers):
            return False
        if TurnOutcomeController._visible_text_promises_future_action(visible_text):
            return False
        return bool((visible_text or "").strip())

    @staticmethod
    def _visible_text_promises_future_action(visible_text: str) -> bool:
        text = re.sub(r"\s+", " ", str(visible_text or "").strip())
        if not text:
            return False
        if re.search(r"(结论|已完成|已经完成|验证通过|测试通过|修复完成|done|completed)", text, re.IGNORECASE):
            return False
        return bool(
            re.search(
                r"(第一步|下一步|接下来|现在开始|我会|我将|让我|先|继续).{0,40}"
                r"(读取|查看|检查|搜索|运行|执行|调用|修改|修复|实现|验证|测试)",
                text,
                re.IGNORECASE,
            )
        )

    @staticmethod
    def can_resume_turn_messages(
        *,
        active_turn_messages: Optional[list],
        active_turn_goal: str,
        effective_goal: str,
        user_prompt: str,
    ) -> bool:
        if not active_turn_messages:
            return False
        if not active_turn_goal:
            return False
        if active_turn_goal != effective_goal:
            return False
        if user_prompt and user_prompt != "开始自主进化" and user_prompt != effective_goal:
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
        if allow_append_user_message and active_turn_messages:
            messages = cls.sanitize_provider_turn_carryover(list(active_turn_messages or []))
            if messages:
                messages[0] = build_system_message(system_prompt)
            else:
                messages = [build_system_message(system_prompt)]
            messages.append(build_external_request_message(user_prompt))
            return messages, True
        if cls.can_resume_turn_messages(
            active_turn_messages=active_turn_messages,
            active_turn_goal=active_turn_goal,
            effective_goal=effective_goal,
            user_prompt=user_prompt,
        ):
            messages = cls.sanitize_provider_turn_carryover(list(active_turn_messages or []))
            if messages:
                messages[0] = build_system_message(system_prompt)
            else:
                messages = [
                    build_system_message(system_prompt),
                    build_external_request_message(user_prompt),
                ]
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

        if not context_messages:
            return list(messages or [])
        normalized = TurnOutcomeController.sanitize_provider_turn_carryover(list(messages or []))
        insert_at = 1 if normalized else 0
        for index in range(len(normalized) - 1, -1, -1):
            item = normalized[index]
            role = ""
            if isinstance(item, dict):
                role = str(item.get("role") or "").strip().lower()
            else:
                role = str(getattr(item, "type", "") or "").strip().lower()
            if role in {"user", "human"}:
                insert_at = index
                break
        return normalized[:insert_at] + list(context_messages or []) + normalized[insert_at:]

    @staticmethod
    def insert_static_context_after_system(*, messages: list, context_messages: list) -> list:
        """Place stable runtime context after the primary system prompt.

        This keeps the durable system prompt and stable Agent/project context
        ahead of chat history, while per-turn volatile context can still be
        inserted later immediately before the current user message.
        """

        if not context_messages:
            return list(messages or [])
        normalized = list(messages or [])
        insert_at = 0
        if normalized:
            first = normalized[0]
            if isinstance(first, dict):
                role = str(first.get("role") or "").strip().lower()
            else:
                role = str(getattr(first, "type", "") or "").strip().lower()
            if role in {"system"}:
                insert_at = 1
        return normalized[:insert_at] + list(context_messages or []) + normalized[insert_at:]

    @staticmethod
    def finish_turn_message_carryover(
        *,
        messages: list,
        lifecycle_action: Optional[str],
        active_goal: str,
    ) -> TurnMessageCarryover:
        if lifecycle_action in {"restart", "hibernated", "turn_complete"}:
            return TurnMessageCarryover(messages=None, goal="")
        return TurnMessageCarryover(
            messages=TurnOutcomeController.sanitize_provider_turn_carryover(list(messages)),
            goal=active_goal,
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

        for message in list(messages or []):
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
    if isinstance(message, dict):
        role = str(message.get("role") or "").strip().lower()
    else:
        role = str(getattr(message, "type", "") or "").strip().lower()
    if role == "ai":
        return "assistant"
    if role == "human":
        return "user"
    return role


def _message_tool_call_ids(message: Any) -> list[str]:
    raw_tool_calls: Any = []
    if isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if not raw_tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, dict):
                raw_tool_calls = additional_kwargs.get("tool_calls") or []
    ids: list[str] = []
    for index, item in enumerate(list(raw_tool_calls or [])):
        if not isinstance(item, dict):
            continue
        tool_call_id = str(item.get("id") or item.get("tool_call_id") or item.get("toolCallId") or "").strip()
        if not tool_call_id:
            tool_call_id = f"tool_{index}"
        ids.append(tool_call_id)
    return ids


def _message_tool_result_id(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("tool_call_id") or message.get("toolCallId") or message.get("id") or "").strip()
    return str(getattr(message, "tool_call_id", "") or getattr(message, "id", "") or "").strip()


def _message_content_text(message: Any) -> str:
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        return "".join(parts).strip()
    return str(content or "").strip()


def _tool_call_name(item: Any) -> str:
    if not isinstance(item, dict):
        return "unknown_tool"
    function = item.get("function") if isinstance(item.get("function"), dict) else {}
    return str(item.get("name") or item.get("toolName") or function.get("name") or "unknown_tool").strip()


def _message_tool_calls(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, dict):
        raw_tool_calls = message.get("tool_calls") or message.get("toolCalls") or []
    else:
        raw_tool_calls = getattr(message, "tool_calls", None) or []
        if not raw_tool_calls:
            additional_kwargs = getattr(message, "additional_kwargs", None)
            if isinstance(additional_kwargs, dict):
                raw_tool_calls = additional_kwargs.get("tool_calls") or []
    return [dict(item) for item in list(raw_tool_calls or []) if isinstance(item, dict)]


def _demote_assistant_tool_calls(message: Any) -> AIMessage:
    content_parts = [_message_content_text(message)]
    for item in _message_tool_calls(message):
        content_parts.append(f"历史工具调用未返回结果: {_tool_call_name(item)}")
    content = "\n\n".join(part for part in content_parts if part).strip()
    return AIMessage(content=content or "历史工具调用未返回结果: unknown_tool")


def _demote_tool_result_message(message: Any) -> AIMessage:
    content = _message_content_text(message)
    name = ""
    if isinstance(message, dict):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        name = str(metadata.get("toolName") or metadata.get("tool_name") or message.get("name") or "").strip()
    else:
        name = str(getattr(message, "name", "") or "").strip()
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
