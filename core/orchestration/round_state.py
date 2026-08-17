# -*- coding: utf-8 -*-
"""单轮运行状态控制器。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Iterable


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
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "{[":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _flag_enabled(value: Any, default: bool = True) -> bool:
    value = _maybe_json(value)
    if isinstance(value, Mapping):
        nested = value.get("enabled")
        if nested is None:
            nested = value.get("visible")
        return _coerce_bool(nested, default)
    return _coerce_bool(value, default)


def _coerce_nonnegative_int(value: Any, *, default: int = 0) -> int:
    if isinstance(default, bool) or default is None:
        fallback = 0
    else:
        try:
            fallback = max(0, int(default))
        except (TypeError, ValueError):
            fallback = 0
    if isinstance(value, bool) or value is None:
        return fallback
    if isinstance(value, (bytes, bytearray, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return fallback


def _coerce_name_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    value = _maybe_json(value)
    if value is None:
        return None
    if isinstance(value, (str, bytes, bytearray, memoryview)):
        text = _coerce_text(value).strip()
        parsed = _maybe_json(text)
        if parsed is not text and not isinstance(parsed, (str, bytes, bytearray, memoryview)):
            return _coerce_name_list(parsed)
        return [text] if text else []
    if isinstance(value, Mapping):
        for key in ("items", "tools", "names", "tool_names", "toolNames"):
            if key not in value:
                continue
            nested = value.get(key)
            if nested is None or isinstance(nested, (bool, int, float)):
                continue
            return _coerce_name_list(nested)
        if "name" in value or "toolName" in value:
            if not _flag_enabled(value, True):
                return []
            name = _coerce_text(value.get("name") or value.get("toolName")).strip()
            return [name] if name else []
        names: list[str] = []
        for key, enabled in value.items():
            name = _coerce_text(key).strip()
            if name and _flag_enabled(enabled, True):
                names.append(name)
        return names
    try:
        items = list(value)
    except TypeError:
        text = _coerce_text(value).strip()
        return [text] if text else []
    names: list[str] = []
    for item in items:
        item = _maybe_json(item)
        if isinstance(item, Mapping):
            if not _flag_enabled(item, True):
                continue
            name = _coerce_text(item.get("name") or item.get("toolName") or item.get("id") or "").strip()
        else:
            name = _coerce_text(item).strip()
        if name:
            names.append(name)
    return names


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

    def __post_init__(self) -> None:
        self.max_iterations = _coerce_nonnegative_int(self.max_iterations)
        self.iteration = _coerce_nonnegative_int(self.iteration)
        self.consecutive_failures = _coerce_nonnegative_int(self.consecutive_failures)
        self.turn_had_progress = _coerce_bool(self.turn_had_progress, False)
        self.total_tool_calls = _coerce_nonnegative_int(self.total_tool_calls)
        self.total_input_tokens = _coerce_nonnegative_int(self.total_input_tokens)
        self.total_output_tokens = _coerce_nonnegative_int(self.total_output_tokens)
        self.no_new_evidence_steps = _coerce_nonnegative_int(self.no_new_evidence_steps)
        self.consecutive_tool_only_steps = _coerce_nonnegative_int(self.consecutive_tool_only_steps)
        self.consecutive_bookkeeping_tool_only_steps = _coerce_nonnegative_int(
            self.consecutive_bookkeeping_tool_only_steps
        )
        self.delegation_failures = _coerce_nonnegative_int(self.delegation_failures)
        self.substantive_tool_calls = _coerce_nonnegative_int(self.substantive_tool_calls)
        self.last_response_tool_call_count = _coerce_nonnegative_int(self.last_response_tool_call_count)
        self.last_response_visible_text = _coerce_text(self.last_response_visible_text)
        self.last_turn_outcome_kind = _coerce_text(self.last_turn_outcome_kind).strip().lower()
        self.lifecycle_completed = _coerce_bool(self.lifecycle_completed, False)

    def next_iteration(self) -> int:
        self.iteration += 1
        return self.iteration

    def note_delegation(self, useful: bool) -> None:
        self.turn_had_progress = True
        if _coerce_bool(useful, False):
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
        visible = _coerce_text(visible_text)
        self.last_response_tool_call_count = count
        self.last_response_visible_text = visible
        if count > 0:
            substantive_count = self._substantive_tool_count(count, tool_names)
            self.substantive_tool_calls += substantive_count
            if visible.strip():
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
        self.last_turn_outcome_kind = _coerce_text(kind).strip().lower()

    def note_lifecycle_completion(self) -> None:
        self.lifecycle_completed = True

    def add_tool_calls(self, count: int) -> None:
        self.total_tool_calls += _coerce_nonnegative_int(count)

    @classmethod
    def _substantive_tool_count(cls, tool_call_count: int, tool_names: Iterable[str] | None) -> int:
        count = _coerce_nonnegative_int(tool_call_count)
        named = _coerce_name_list(tool_names)
        if named is None:
            return count
        named = [name for name in named if name]
        if named:
            return sum(1 for name in named if name not in cls.BOOKKEEPING_TOOL_NAMES)
        parsed = _maybe_json(tool_names)
        if isinstance(parsed, Mapping):
            return 0
        if isinstance(parsed, (list, tuple)) and parsed:
            return 0
        return count

    def add_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += _coerce_nonnegative_int(input_tokens)
        self.total_output_tokens += _coerce_nonnegative_int(output_tokens)

    def thinking_status(self, goal: str = "") -> Dict[str, int | str]:
        return {
            "goal": _coerce_text(goal),
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
        failed = _coerce_bool(last_turn_failed, False)
        if self.lifecycle_completed:
            return self.turn_had_progress and not failed
        if self.last_turn_outcome_kind:
            return (
                self.turn_had_progress
                and not failed
                and self.last_turn_outcome_kind == "final_answer"
            )
        return self.turn_had_progress and not failed and not self.exhausted_without_final_answer()

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
