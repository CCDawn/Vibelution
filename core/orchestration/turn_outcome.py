# -*- coding: utf-8 -*-
"""回合停机与收尾控制器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


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
        close_seen = False
        restart_seen = False
        for msg in messages:
            tool_name = getattr(msg, "name", "") or ""
            content = getattr(msg, "content", "") or ""
            if isinstance(content, list):
                content = "\n".join(str(item) for item in content)
            text = str(content or "")
            if "close_evolution_transaction_tool" in tool_name:
                close_seen = True
            if "trigger_self_restart_tool" in tool_name:
                restart_seen = True
            if '"transaction_status": "success"' in text or '"transaction_status":"success"' in text:
                close_seen = True
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
            messages = list(active_turn_messages or [])
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
            messages = list(active_turn_messages or [])
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
        normalized = list(messages or [])
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
        return TurnMessageCarryover(messages=list(messages), goal=active_goal)

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
        turn_success = round_state.finish_success(last_turn_failed)
        return TurnFinalization(
            last_turn_failed=last_turn_failed,
            turn_success=turn_success,
            ui_status="SUCCESS" if turn_success else ("ERROR" if last_turn_failed else "IDLE"),
            turn_stats=round_state.final_stats(),
        )
