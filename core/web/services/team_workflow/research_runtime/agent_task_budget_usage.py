"""Measure canonical external Agent task usage for budget settlement."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .node_execution_support import NodeExecutionError


def parse_task_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def collect_agent_task_budget_usage(
    record: dict[str, Any],
    node_run: dict[str, Any],
    task: dict[str, Any],
    session_detail: dict[str, Any],
) -> dict[str, int]:
    reservation = next(
        (
            dict(item)
            for item in record.get("budgetReservations") or []
            if item.get("reservationId") == node_run.get("budgetLedgerRef")
        ),
        None,
    )
    if reservation is None:
        return {}
    requested = dict(reservation.get("requested") or {})
    task_result = dict(task.get("result") or {})
    explicit = task_result.get("budgetUsage")
    explicit_usage = dict(explicit) if isinstance(explicit, dict) else {}
    usage: dict[str, int] = {}

    llm_usage = session_detail.get("llmUsage")
    llm_usage = dict(llm_usage) if isinstance(llm_usage, dict) else {}
    if "tokens" in requested:
        raw_tokens = explicit_usage.get("tokens", llm_usage.get("totalTokens"))
        if isinstance(raw_tokens, bool) or not isinstance(raw_tokens, int):
            raise NodeExecutionError(
                "terminal Agent task is missing provider token usage",
                code="agent_usage_missing",
            )
        usage["tokens"] = raw_tokens

    progress = task.get("taskToolProgress")
    progress = dict(progress) if isinstance(progress, dict) else {}
    context_usage = session_detail.get("contextUsage")
    context_usage = dict(context_usage) if isinstance(context_usage, dict) else {}
    if "toolCalls" in requested:
        raw_tool_calls = explicit_usage.get(
            "toolCalls",
            progress.get("toolCallCount", context_usage.get("toolCallCount")),
        )
        if isinstance(raw_tool_calls, bool) or not isinstance(raw_tool_calls, int):
            raise NodeExecutionError(
                "terminal Agent task is missing tool-call usage",
                code="agent_usage_missing",
            )
        usage["toolCalls"] = raw_tool_calls

    if "wallClockSeconds" in requested:
        raw_seconds = explicit_usage.get("wallClockSeconds")
        if isinstance(raw_seconds, bool):
            raw_seconds = None
        if not isinstance(raw_seconds, int):
            turn = task.get("turn")
            turn = dict(turn) if isinstance(turn, dict) else {}
            started = parse_task_time(
                turn.get("acceptedAt")
                or task.get("startedAt")
                or task.get("createdAt")
                or node_run.get("startedAt")
            )
            finished = parse_task_time(task.get("updatedAt"))
            if started is None or finished is None:
                raise NodeExecutionError(
                    "terminal Agent task is missing wall-clock usage",
                    code="agent_usage_missing",
                )
            if started.tzinfo is None and finished.tzinfo is not None:
                started = started.replace(tzinfo=finished.tzinfo)
            elif finished.tzinfo is None and started.tzinfo is not None:
                finished = finished.replace(tzinfo=started.tzinfo)
            raw_seconds = max(0, int((finished - started).total_seconds()))
        usage["wallClockSeconds"] = raw_seconds

    for counter in ("experiments", "computeUnits"):
        if counter not in requested:
            continue
        raw_value = explicit_usage.get(counter, 0)
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            raise NodeExecutionError(
                f"terminal Agent task has invalid {counter} usage",
                code="agent_usage_invalid",
            )
        usage[counter] = raw_value
    return usage
