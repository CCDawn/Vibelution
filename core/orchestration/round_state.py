# -*- coding: utf-8 -*-
"""单轮运行状态控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterable


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        try:
            return max(0, int(default or 0))
        except (TypeError, ValueError):
            return 0


@dataclass
class RoundStateController:
    """集中管理 think_and_act() 的单轮局部状态。"""

    max_iterations: int
    iteration: int = 0
    consecutive_failures: int = 0
    turn_had_progress: bool = False
    total_tool_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    no_new_evidence_steps: int = 0
    consecutive_tool_only_steps: int = 0
    consecutive_bookkeeping_tool_only_steps: int = 0
    delegation_failures: int = 0
    substantive_tool_calls: int = 0
    last_response_tool_call_count: int = 0
    last_response_visible_text: str = ""
    last_turn_outcome_kind: str = ""
    lifecycle_completed: bool = False

    BOOKKEEPING_TOOL_NAMES: ClassVar[set[str]] = {
        "get_git_status_summary_tool",
        "get_recent_changes_tool",
        "task_create_tool",
        "task_update_tool",
        "task_list_tool",
        "get_current_goal_tool",
        "get_core_context_tool",
        "get_memory_summary_tool",
    }

    def next_iteration(self) -> int:
        self.iteration += 1
        return self.iteration

    def note_delegation(self, useful: bool) -> None:
        self.turn_had_progress = True
        if useful:
            self.no_new_evidence_steps = 0
            self.delegation_failures = 0
        else:
            self.no_new_evidence_steps += 1
            self.delegation_failures += 1

    def note_llm_failure(self) -> int:
        self.consecutive_failures += 1
        return self.consecutive_failures

    def reset_failures(self) -> None:
        self.consecutive_failures = 0

    def note_progress(self) -> None:
        self.turn_had_progress = True
        self.reset_failures()

    def add_xml_tool_calls(self, count: int) -> None:
        self.total_tool_calls += _coerce_nonnegative_int(count)
        self.turn_had_progress = True
        self.no_new_evidence_steps = 0
        self.reset_failures()

    def note_response_tools(
        self,
        tool_call_count: int,
        visible_text: str = "",
        tool_names: Iterable[str] | None = None,
    ) -> None:
        count = _coerce_nonnegative_int(tool_call_count)
        self.last_response_tool_call_count = count
        self.last_response_visible_text = str(visible_text or "")
        if count > 0:
            substantive_count = self._substantive_tool_count(count, tool_names)
            self.substantive_tool_calls += substantive_count
            if str(visible_text or "").strip():
                self.consecutive_tool_only_steps = 0
                self.consecutive_bookkeeping_tool_only_steps = 0
                self.no_new_evidence_steps = 0
            elif substantive_count > 0:
                self.no_new_evidence_steps = 0
                self.consecutive_bookkeeping_tool_only_steps = 0
                self.consecutive_tool_only_steps += 1
            else:
                self.no_new_evidence_steps += 1
                self.consecutive_tool_only_steps = 0
                self.consecutive_bookkeeping_tool_only_steps += 1
        else:
            self.no_new_evidence_steps += 1
            self.consecutive_tool_only_steps = 0
            self.consecutive_bookkeeping_tool_only_steps = 0

    def note_turn_outcome(self, kind: str) -> None:
        self.last_turn_outcome_kind = str(kind or "").strip().lower()

    def note_lifecycle_completion(self) -> None:
        self.lifecycle_completed = True

    def add_tool_calls(self, count: int) -> None:
        self.total_tool_calls += _coerce_nonnegative_int(count)

    @classmethod
    def _substantive_tool_count(cls, tool_call_count: int, tool_names: Iterable[str] | None) -> int:
        count = _coerce_nonnegative_int(tool_call_count)
        if tool_names is None:
            return count
        named = [str(name or "").strip() for name in tool_names]
        named = [name for name in named if name]
        if not named:
            return count
        return sum(1 for name in named if name not in cls.BOOKKEEPING_TOOL_NAMES)

    def add_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += _coerce_nonnegative_int(input_tokens)
        self.total_output_tokens += _coerce_nonnegative_int(output_tokens)

    def thinking_status(self, goal: str = "") -> Dict[str, int | str]:
        return {
            "goal": goal,
            "iterations": self.iteration,
            "tool_count": self.total_tool_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }

    def runtime_telemetry(self) -> Dict[str, int]:
        return {
            "consecutive_tool_only_steps": self.consecutive_tool_only_steps,
            "consecutive_bookkeeping_tool_only_steps": self.consecutive_bookkeeping_tool_only_steps,
            "no_new_evidence_steps": self.no_new_evidence_steps,
            "delegation_failures": self.delegation_failures,
        }

    def current_status(self) -> Dict[str, int]:
        return {
            "iterations": self.iteration,
            "tool_count": self.total_tool_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }

    def acting_status(self, pending_tool_calls: int) -> Dict[str, int]:
        return {
            "iterations": self.iteration,
            "tool_count": self.total_tool_calls + _coerce_nonnegative_int(pending_tool_calls),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }

    def finish_success(self, last_turn_failed: bool) -> bool:
        if self.lifecycle_completed:
            return self.turn_had_progress and not last_turn_failed
        if self.last_turn_outcome_kind:
            return (
                self.turn_had_progress
                and not last_turn_failed
                and self.last_turn_outcome_kind == "final_answer"
            )
        return self.turn_had_progress and not last_turn_failed and not self.exhausted_without_final_answer()

    def exhausted_without_final_answer(self) -> bool:
        if self.lifecycle_completed:
            return False
        if self.iteration < self.max_iterations:
            return False
        if self.last_turn_outcome_kind:
            return self.last_turn_outcome_kind != "final_answer"
        return self.last_response_tool_call_count > 0 or not self.last_response_visible_text.strip()

    def final_stats(self) -> Dict[str, int]:
        return {
            "iterations": self.iteration,
            "tool_calls": self.total_tool_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }
