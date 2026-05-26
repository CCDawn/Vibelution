# -*- coding: utf-8 -*-
"""单轮运行状态控制器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, Iterable


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
        self.total_tool_calls += max(0, int(count or 0))
        self.turn_had_progress = True
        self.no_new_evidence_steps = 0
        self.reset_failures()

    def note_response_tools(
        self,
        tool_call_count: int,
        visible_text: str = "",
        tool_names: Iterable[str] | None = None,
    ) -> None:
        if tool_call_count > 0:
            substantive_count = self._substantive_tool_count(tool_call_count, tool_names)
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

    def add_tool_calls(self, count: int) -> None:
        self.total_tool_calls += max(0, int(count or 0))

    @classmethod
    def _substantive_tool_count(cls, tool_call_count: int, tool_names: Iterable[str] | None) -> int:
        if tool_names is None:
            return max(0, int(tool_call_count or 0))
        count = 0
        for name in tool_names:
            normalized = str(name or "").strip()
            if normalized and normalized not in cls.BOOKKEEPING_TOOL_NAMES:
                count += 1
        return count

    def add_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += max(0, int(input_tokens or 0))
        self.total_output_tokens += max(0, int(output_tokens or 0))

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
            "tool_count": self.total_tool_calls + max(0, int(pending_tool_calls or 0)),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }

    def finish_success(self, last_turn_failed: bool) -> bool:
        return self.turn_had_progress and not last_turn_failed

    def final_stats(self) -> Dict[str, int]:
        return {
            "iterations": self.iteration,
            "tool_calls": self.total_tool_calls,
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
        }
