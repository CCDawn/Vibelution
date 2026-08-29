"""Measure canonical external Agent task usage for budget settlement."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.web.services.session.timebase import parse_timestamp_utc
from .node_execution_support import NodeExecutionError


def parse_task_time(value: object) -> datetime | None:
    # Normalize legacy naive (machine-local) acceptedAt/updatedAt values and
    # tz-aware UTC values onto one time base before wall-clock diffing.
    return parse_timestamp_utc(value)


def _inferred_task_timezone(
    session_detail: dict[str, Any],
    finished: datetime,
):
    if finished.tzinfo is None:
        return None
    local_updated = parse_task_time(session_detail.get("updatedAt"))
    if local_updated is None or local_updated.tzinfo is not None:
        return None
    utc_finished = finished.astimezone(timezone.utc).replace(tzinfo=None)
    raw_offset_seconds = (local_updated - utc_finished).total_seconds()
    rounded_offset_seconds = round(raw_offset_seconds / 900) * 900
    if (
        abs(rounded_offset_seconds) > timedelta(hours=14).total_seconds()
        or abs(raw_offset_seconds - rounded_offset_seconds) > 300
    ):
        return None
    return timezone(timedelta(seconds=rounded_offset_seconds))


def _paired_timestamp_timezone(
    naive_timestamp: datetime,
    aware_reference: datetime | None,
):
    """Infer the writer timezone from near-simultaneous local/UTC timestamps."""
    if naive_timestamp.tzinfo is not None or aware_reference is None:
        return None
    if aware_reference.tzinfo is None:
        return None
    utc_reference = aware_reference.astimezone(timezone.utc).replace(tzinfo=None)
    raw_offset_seconds = (naive_timestamp - utc_reference).total_seconds()
    rounded_offset_seconds = round(raw_offset_seconds / 900) * 900
    if (
        abs(rounded_offset_seconds) > timedelta(hours=14).total_seconds()
        or abs(raw_offset_seconds - rounded_offset_seconds) > 300
    ):
        return None
    return timezone(timedelta(seconds=rounded_offset_seconds))


def _elapsed_seconds(
    session_detail: dict[str, Any],
    started: datetime,
    finished: datetime,
    *,
    started_reference: datetime | None = None,
) -> int:
    if started.tzinfo is None and finished.tzinfo is not None:
        inferred = _paired_timestamp_timezone(started, started_reference)
        if inferred is None:
            inferred = _inferred_task_timezone(session_detail, finished)
        started = started.replace(tzinfo=inferred or finished.tzinfo)
    elif finished.tzinfo is None and started.tzinfo is not None:
        finished = finished.replace(tzinfo=started.tzinfo)
    elapsed = int((finished - started).total_seconds())
    if elapsed < 0:
        raise NodeExecutionError(
            "terminal Agent task has inconsistent wall-clock timestamps",
            code="agent_usage_invalid",
        )
    return elapsed


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
            started_reference = parse_task_time(
                task.get("createdAt") or node_run.get("startedAt")
            )
            raw_seconds = _elapsed_seconds(
                session_detail,
                started,
                finished,
                started_reference=started_reference,
            )
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
