"""Turn-scoped stuck-loop analyzer for the session continuation tool loop.

A pure-function guard against the agent burning the turn budget by repeating
the same tool action (or the same error) inside one chat turn. Input is the
flat sequence of tool calls observed in THIS turn (tool name + normalized
arguments + result status/error summary); output is a stuck verdict with a
machine-stable pattern id and a user-facing evidence summary. Cross-turn
accumulation is deliberately out of scope: the caller resets the record list
per turn.

Pattern semantics are borrowed from the OpenHands StuckDetector
(``openhands-sdk/openhands/sdk/conversation/stuck_detector.py``, recorded as
EXTERNAL reuse evidence): semantic event equality that ignores invocation ids
and metrics, a bounded trailing scan window, and trailing-run thresholds of
4 (same action + same observation) / 3 (same action + error) / 6 (alternating
A-B loop). Adaptations for this codebase:

- OpenHands compares separate action and observation events; here each tool
  call already binds action and outcome in one record, so "same action +
  same observation" collapses into one full-signature trailing run.
- ``repeated_error_text`` generalizes OpenHands' action-error mode: three
  consecutive failed calls sharing the same normalized error text even when
  the agent varies arguments between attempts (a real retry shape the
  same-action rule cannot see).
- Monologue mode is NOT ported: the analyzer only sees tool-call records, and
  consecutive tool-less agent rounds are already guarded by the continuation
  loop's ``consecutive_no_progress_turns`` / ``auto_continue_turn_limit``
  fuse (worker.py), which owns that failure surface.
- Context-window-error mode is NOT ported: OpenHands itself stubs it to
  ``return False`` (agent-sdk issue #282), and Vibelution routes context
  budget failures through the token fuse + ``context_budget_exhausted``
  problem-code pipeline instead.

Failure contract: every entry point is fail-open. Any exception inside the
analyzer degrades to "not stuck"; the caller additionally wraps the hook, so
a broken detector can never fail a healthy turn.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Iterable

__all__ = [
    "PATTERN_ALTERNATING_ACTION_OBSERVATION",
    "PATTERN_REPEATED_ACTION_ERROR",
    "PATTERN_REPEATED_ACTION_OBSERVATION",
    "PATTERN_REPEATED_ERROR_TEXT",
    "MAX_RECORDS_TO_SCAN",
    "STUCK_LOOP_PAUSE_REASON",
    "TOOL_CALL_RECORD_NOISY_KEYS",
    "TurnStuckThresholds",
    "ToolCallRecord",
    "StuckVerdict",
    "analyze_tool_call_records",
    "append_tool_call_records",
    "is_turn_stuck_detection_enabled",
    "normalize_tool_value",
    "records_from_tool_trace",
    "thresholds_from_env",
]

# Total switch + per-threshold env overrides. Defaults mirror OpenHands'
# StuckDetectionThresholds (action_observation=4, action_error=3,
# alternating=6); error-text mode reuses the action-error bar.
TURN_STUCK_ENABLED_ENV = "VIBELUTION_TURN_STUCK_DETECTION"
TURN_STUCK_ACTION_OBSERVATION_THRESHOLD_ENV = "VIBELUTION_TURN_STUCK_ACTION_OBSERVATION_THRESHOLD"
TURN_STUCK_ACTION_ERROR_THRESHOLD_ENV = "VIBELUTION_TURN_STUCK_ACTION_ERROR_THRESHOLD"
TURN_STUCK_ERROR_TEXT_THRESHOLD_ENV = "VIBELUTION_TURN_STUCK_ERROR_TEXT_THRESHOLD"
TURN_STUCK_ALTERNATING_THRESHOLD_ENV = "VIBELUTION_TURN_STUCK_ALTERNATING_THRESHOLD"

DEFAULT_ACTION_OBSERVATION_THRESHOLD = 4
DEFAULT_ACTION_ERROR_THRESHOLD = 3
DEFAULT_ERROR_TEXT_THRESHOLD = 3
DEFAULT_ALTERNATING_THRESHOLD = 6

# Bounded trailing window (mirrors OpenHands MAX_EVENTS_TO_SCAN_FOR_STUCK_
# DETECTION=20 scaled down: the largest default need is 6 alternating records,
# plus headroom so a raised threshold still has material to inspect).
MAX_RECORDS_TO_SCAN = 16

# Machine-stable pattern ids (surface in metadata/lifecycle events only).
PATTERN_REPEATED_ACTION_OBSERVATION = "repeated_action_observation"
PATTERN_REPEATED_ACTION_ERROR = "repeated_action_error"
PATTERN_REPEATED_ERROR_TEXT = "repeated_error_text"
PATTERN_ALTERNATING_ACTION_OBSERVATION = "alternating_action_observation"

# Terminal pause reason surfaced via metadata.continuation_pause_reason on the
# existing paused_limit pipeline (no new terminal status is introduced).
STUCK_LOOP_PAUSE_REASON = "stuck_loop_detected"

# Invocation-local noise dropped before comparison (aligned with worker's
# `_normalized_tool_signature_value` plus a few id/time shapes so embedded
# random values cannot defeat the signature).
TOOL_CALL_RECORD_NOISY_KEYS = frozenset(
    {
        "callid",
        "toolcallid",
        "tool_call_id",
        "id",
        "requestid",
        "request_id",
        "messageid",
        "message_id",
        "durationms",
        "duration_ms",
        "elapsedms",
        "elapsed_ms",
        "timestamp",
        "createdat",
        "updatedat",
        "nonce",
        "traceid",
        "trace_id",
        "spanid",
        "span_id",
    }
)

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_ISO_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)

_ERROR_PREVIEW_MAX_CHARS = 120


@dataclass(frozen=True)
class ToolCallRecord:
    """One observable tool call inside a turn."""

    tool_name: str
    arguments: Any = None
    failed: bool = False
    error_text: str = ""


@dataclass(frozen=True)
class TurnStuckThresholds:
    """Trailing-run thresholds; defaults mirror OpenHands."""

    action_observation: int = DEFAULT_ACTION_OBSERVATION_THRESHOLD
    action_error: int = DEFAULT_ACTION_ERROR_THRESHOLD
    error_text: int = DEFAULT_ERROR_TEXT_THRESHOLD
    alternating_pattern: int = DEFAULT_ALTERNATING_THRESHOLD


@dataclass(frozen=True)
class StuckVerdict:
    """Analyzer output; ``stuck=False`` verdicts carry no pattern."""

    stuck: bool = False
    pattern: str = ""
    tool_name: str = ""
    repeat_count: int = 0
    evidence: str = ""


_NOT_STUCK = StuckVerdict()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 1 else default


def thresholds_from_env() -> TurnStuckThresholds:
    """Resolve thresholds from env with module defaults as fallback."""

    return TurnStuckThresholds(
        action_observation=_env_int(
            TURN_STUCK_ACTION_OBSERVATION_THRESHOLD_ENV,
            DEFAULT_ACTION_OBSERVATION_THRESHOLD,
        ),
        action_error=_env_int(
            TURN_STUCK_ACTION_ERROR_THRESHOLD_ENV,
            DEFAULT_ACTION_ERROR_THRESHOLD,
        ),
        error_text=_env_int(
            TURN_STUCK_ERROR_TEXT_THRESHOLD_ENV,
            DEFAULT_ERROR_TEXT_THRESHOLD,
        ),
        alternating_pattern=_env_int(
            TURN_STUCK_ALTERNATING_THRESHOLD_ENV,
            DEFAULT_ALTERNATING_THRESHOLD,
        ),
    )


def is_turn_stuck_detection_enabled() -> bool:
    """Total switch; enabled unless the env explicitly turns it off."""

    raw = os.environ.get(TURN_STUCK_ENABLED_ENV, "").strip().lower()
    return raw not in {"0", "false", "off", "no", "disabled"}


def normalize_tool_value(value: Any) -> Any:
    """Recursively strip invocation-local noise for stable comparison.

    Dict keys carrying call-local identity/timing are dropped, dict order is
    canonicalized, UUID and ISO-timestamp substrings inside strings are
    blanked, and JSON-looking strings are decoded so quoting differences do
    not defeat equality (OpenHands compares semantic content, not object
    identity).
    """

    if isinstance(value, dict):
        return {
            str(key): normalize_tool_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key).lower() not in TOOL_CALL_RECORD_NOISY_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [normalize_tool_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = " ".join(str(value).split())
    if text.startswith(("{", "[")):
        try:
            return normalize_tool_value(json.loads(text))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    text = _UUID_PATTERN.sub("<uuid>", text)
    text = _ISO_TIMESTAMP_PATTERN.sub("<ts>", text)
    return text


def _full_signature(record: ToolCallRecord) -> str:
    """Signature binding tool name + arguments + outcome + observation."""

    payload = {
        "name": normalize_tool_value(record.tool_name),
        "arguments": normalize_tool_value(record.arguments),
        "failed": bool(record.failed),
        "observation": normalize_tool_value(record.error_text),
    }
    return _canonical_hash(payload)


def _action_signature(record: ToolCallRecord) -> str:
    """Signature binding tool name + arguments only (error-agnostic)."""

    payload = {
        "name": normalize_tool_value(record.tool_name),
        "arguments": normalize_tool_value(record.arguments),
    }
    return _canonical_hash(payload)


def _error_signature(record: ToolCallRecord) -> str:
    """Signature of the normalized error text alone."""

    return _canonical_hash({"error": normalize_tool_value(record.error_text)})


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _extract_tool_name(raw: dict[str, Any]) -> str:
    for key in ("name", "tool", "toolName", "tool_name"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
    value = function.get("name")
    return value.strip() if isinstance(value, str) else ""


def _extract_arguments(raw: dict[str, Any], function: dict[str, Any]) -> Any:
    for source in (raw, function):
        for key in ("arguments", "args", "input"):
            if key in source and source.get(key) is not None:
                return source.get(key)
    return None


def records_from_tool_trace(tool_trace: Any) -> list[ToolCallRecord]:
    """Extract per-call records from a result ``tool_trace``/``tool_calls`` list.

    Field fallbacks deliberately mirror worker's ``_continuation_tool_
    observations`` so the two views of a tool call stay aligned.
    """

    if not isinstance(tool_trace, (list, tuple)):
        return []
    records: list[ToolCallRecord] = []
    for raw in tool_trace:
        if not isinstance(raw, dict):
            continue
        name = _extract_tool_name(raw)
        if not name:
            continue
        function = raw.get("function") if isinstance(raw.get("function"), dict) else {}
        arguments = _extract_arguments(raw, function)
        error_code = str(raw.get("errorCode") or raw.get("error_code") or "").strip()
        error = raw.get("error")
        result_value = raw.get("result")
        if result_value is None:
            result_value = raw.get("resultPreview") or raw.get("result_preview")
        if result_value is None:
            result_value = raw.get("summary")
        status = str(raw.get("semanticStatus") or raw.get("status") or "done").strip().lower()
        failure_statuses = {"error", "failed", "failure", "timeout", "timed_out"}
        failed = bool(
            status in failure_statuses or error_code or error
        )
        error_text = str(
            error_code or (error if error is not None else "") or result_value or ""
        ).strip()
        records.append(
            ToolCallRecord(
                tool_name=name,
                arguments=arguments,
                failed=failed,
                error_text=error_text,
            )
        )
    return records


def append_tool_call_records(result: Any, accumulated: list[ToolCallRecord]) -> None:
    """Append one LLM round's tool-call records to the per-turn sequence."""

    if not isinstance(result, dict):
        return
    trace = result.get("tool_trace") or result.get("tool_calls")
    accumulated.extend(records_from_tool_trace(trace))


def _trailing_run_size(records: list[ToolCallRecord], signature_of) -> int:
    """Length of the trailing run sharing the most recent record's signature."""

    if not records:
        return 0
    reference = signature_of(records[-1])
    count = 0
    for record in reversed(records):
        if signature_of(record) != reference:
            break
        count += 1
    return count


def _detect_repeated_action_observation(
    records: list[ToolCallRecord], thresholds: TurnStuckThresholds
) -> StuckVerdict:
    run = _trailing_run_size(records, _full_signature)
    if run >= thresholds.action_observation:
        last = records[-1]
        return StuckVerdict(
            stuck=True,
            pattern=PATTERN_REPEATED_ACTION_OBSERVATION,
            tool_name=last.tool_name,
            repeat_count=run,
            evidence=(
                f"工具 {last.tool_name} 以相同参数与相同结果连续执行 {run} 次"
            ),
        )
    return _NOT_STUCK


def _detect_repeated_action_error(
    records: list[ToolCallRecord], thresholds: TurnStuckThresholds
) -> StuckVerdict:
    if not records:
        return _NOT_STUCK
    reference = _action_signature(records[-1])
    count = 0
    for record in reversed(records):
        if _action_signature(record) != reference or not record.failed:
            break
        count += 1
    if count >= thresholds.action_error:
        last = records[-1]
        return StuckVerdict(
            stuck=True,
            pattern=PATTERN_REPEATED_ACTION_ERROR,
            tool_name=last.tool_name,
            repeat_count=count,
            evidence=(
                f"工具 {last.tool_name} 以相同参数连续失败 {count} 次："
                f"{_error_preview(last.error_text)}"
            ),
        )
    return _NOT_STUCK


def _detect_repeated_error_text(
    records: list[ToolCallRecord], thresholds: TurnStuckThresholds
) -> StuckVerdict:
    if not records:
        return _NOT_STUCK
    last = records[-1]
    if not last.failed or not normalize_tool_value(last.error_text):
        return _NOT_STUCK
    reference = _error_signature(last)
    count = 0
    for record in reversed(records):
        if not record.failed or _error_signature(record) != reference:
            break
        count += 1
    if count >= thresholds.error_text:
        return StuckVerdict(
            stuck=True,
            pattern=PATTERN_REPEATED_ERROR_TEXT,
            tool_name=last.tool_name,
            repeat_count=count,
            evidence=(
                f"连续 {count} 次工具调用返回相同错误："
                f"{_error_preview(last.error_text)}"
            ),
        )
    return _NOT_STUCK


def _detect_alternating_action_observation(
    records: list[ToolCallRecord], thresholds: TurnStuckThresholds
) -> StuckVerdict:
    threshold = thresholds.alternating_pattern
    if len(records) < threshold:
        return _NOT_STUCK
    tail = records[-threshold:]
    head_signature = _full_signature(tail[0])
    next_signature = _full_signature(tail[1])
    # Two distinct phases must strictly alternate (A,B,A,B,...); an
    # all-identical run is mode 1's territory.
    if head_signature == next_signature:
        return _NOT_STUCK
    for index in range(threshold - 2):
        if _full_signature(tail[index]) != _full_signature(tail[index + 2]):
            return _NOT_STUCK
    return StuckVerdict(
        stuck=True,
        pattern=PATTERN_ALTERNATING_ACTION_OBSERVATION,
        tool_name=tail[-1].tool_name,
        repeat_count=threshold,
        evidence=(
            f"工具 {tail[0].tool_name} 与 {tail[1].tool_name} "
            f"交替执行 {threshold} 次无进展"
        ),
    )


def _error_preview(error_text: str) -> str:
    normalized = str(normalize_tool_value(error_text) or "").strip()
    if len(normalized) > _ERROR_PREVIEW_MAX_CHARS:
        return normalized[: _ERROR_PREVIEW_MAX_CHARS] + "…"
    return normalized or "（无错误详情）"


def analyze_tool_call_records(
    records: Iterable[ToolCallRecord],
    *,
    thresholds: TurnStuckThresholds | None = None,
) -> StuckVerdict:
    """Analyze one turn's tool-call sequence; fail-open to "not stuck".

    Only the trailing ``MAX_RECORDS_TO_SCAN`` records are inspected (OpenHands
    scans a bounded window for the same reason), and only THIS turn's calls
    are ever passed in, so cross-turn accumulation cannot occur.
    """

    try:
        window = [record for record in records if isinstance(record, ToolCallRecord)]
        window = window[-MAX_RECORDS_TO_SCAN:]
        if not window:
            return _NOT_STUCK
        effective_thresholds = thresholds or thresholds_from_env()
        for detector in (
            _detect_repeated_action_observation,
            _detect_repeated_action_error,
            _detect_repeated_error_text,
            _detect_alternating_action_observation,
        ):
            verdict = detector(window, effective_thresholds)
            if verdict is not None and verdict.stuck:
                return verdict
        return _NOT_STUCK
    except Exception:
        return _NOT_STUCK
