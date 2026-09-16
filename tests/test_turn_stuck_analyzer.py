"""Turn-scoped stuck-loop analyzer + continuation-loop hook contracts.

Pins the OpenHands-style stuck detection adapted for the session worker's
continuation tool loop:

- three core patterns (same tool+args+observation run >= 4, same action
  failing >= 3, same error text >= 3) plus the alternating A/B loop (>= 6),
  each with hit/miss boundary coverage;
- semantic normalization ignores invocation ids, timestamps and embedded
  random values, so a retried call with a fresh call id still counts as a
  repeat while genuinely different arguments never do;
- statistics are turn-scoped: the caller resets records per turn and the
  analyzer inspects only a bounded trailing window;
- fail-open everywhere: an analyzer crash or a disabled switch leaves the
  normal turn untouched;
- the worker hook (`worker._evaluate_turn_stuck`) accumulates per-round
  records across continuation rounds and surfaces a stuck verdict without
  ever raising.
"""

from __future__ import annotations

import pytest
from typing import Any

from core.web.services.session import turn_stuck_analyzer
from core.web.services.session import worker
from core.web.services.session.turn_stuck_analyzer import (
    PATTERN_ALTERNATING_ACTION_OBSERVATION,
    PATTERN_REPEATED_ACTION_ERROR,
    PATTERN_REPEATED_ACTION_OBSERVATION,
    PATTERN_REPEATED_ERROR_TEXT,
    STUCK_LOOP_PAUSE_REASON,
    ToolCallRecord,
    analyze_tool_call_records,
    append_tool_call_records,
    is_turn_stuck_detection_enabled,
    normalize_tool_value,
    records_from_tool_trace,
    thresholds_from_env,
)


@pytest.fixture(autouse=True)
def _clean_stuck_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        turn_stuck_analyzer.TURN_STUCK_ENABLED_ENV,
        turn_stuck_analyzer.TURN_STUCK_ACTION_OBSERVATION_THRESHOLD_ENV,
        turn_stuck_analyzer.TURN_STUCK_ACTION_ERROR_THRESHOLD_ENV,
        turn_stuck_analyzer.TURN_STUCK_ERROR_TEXT_THRESHOLD_ENV,
        turn_stuck_analyzer.TURN_STUCK_ALTERNATING_THRESHOLD_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _record(
    name: str = "grep",
    arguments: Any = None,
    *,
    failed: bool = False,
    error_text: str = "",
) -> ToolCallRecord:
    return ToolCallRecord(
        tool_name=name,
        arguments=arguments if arguments is not None else {"pattern": "x"},
        failed=failed,
        error_text=error_text,
    )


def _tool_trace_entry(
    name: str = "grep",
    arguments: Any = None,
    *,
    status: str = "done",
    error: str | None = None,
    result_text: str = "ok",
) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": name, "arguments": arguments or {}}
    if status != "done":
        entry["semanticStatus"] = status
    if error is not None:
        entry["error"] = error
    if result_text is not None:
        entry["result"] = result_text
    return entry


# ---------------------------------------------------------------------------
# Mode 1: same tool + same args + same observation, >= 4 trailing runs.
# ---------------------------------------------------------------------------


def test_repeated_action_observation_hits_at_threshold() -> None:
    records = [_record() for _ in range(4)]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ACTION_OBSERVATION
    assert verdict.tool_name == "grep"
    assert verdict.repeat_count == 4
    assert "grep" in verdict.evidence


def test_repeated_action_observation_below_threshold_not_stuck() -> None:
    assert analyze_tool_call_records([_record() for _ in range(3)]).stuck is False


def test_repeated_action_observation_requires_trailing_run() -> None:
    # OpenHands semantics: only the trailing run counts; an identical streak
    # broken by a different call is not stuck.
    records = [_record() for _ in range(4)] + [_record(arguments={"pattern": "y"})]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is False


def test_identical_repeats_report_mode_1_not_alternating() -> None:
    records = [_record() for _ in range(6)]
    verdict = analyze_tool_call_records(records)
    assert verdict.pattern == PATTERN_REPEATED_ACTION_OBSERVATION


# ---------------------------------------------------------------------------
# Normalization: ids / timestamps / random values are ignored.
# ---------------------------------------------------------------------------


def test_normalization_ignores_invocation_ids_and_timestamps() -> None:
    records = [
        _record(
            arguments={
                "pattern": "x",
                "callId": f"call-{index}",
                "trace_id": "0f0e0d0c-0b0a-0908-0706-050403020100",
                "requestedAt": f"2026-09-16T10:00:0{index}Z",
                "note": f"run 550e8400-e29b-41d4-a716-44665544000{index}",
            }
        )
        for index in range(4)
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ACTION_OBSERVATION


def test_normalization_keeps_semantic_argument_differences() -> None:
    # Genuinely different arguments (no A/B repetition) are never stuck even
    # though the tool name repeats.
    records = [
        _record(arguments={"pattern": pattern})
        for pattern in ("a", "b", "c", "d", "e", "f")
    ]
    assert analyze_tool_call_records(records).stuck is False


def test_normalize_tool_value_scrubs_uuid_and_iso_timestamp() -> None:
    assert normalize_tool_value("id 550e8400-e29b-41d4-a716-446655440000") == "id <uuid>"
    assert (
        normalize_tool_value("at 2026-09-16T10:00:00Z") == "at <ts>"
    )
    # Noisy dict keys are dropped and key order is canonicalized.
    assert normalize_tool_value({"b": 1, "a": 2, "tool_call_id": "z"}) == {"a": 2, "b": 1}


# ---------------------------------------------------------------------------
# Mode 2: same tool + same args failing, >= 3 trailing runs.
# ---------------------------------------------------------------------------


def test_repeated_action_error_hits_at_threshold() -> None:
    records = [
        _record(failed=True, error_text="permission denied") for _ in range(3)
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ACTION_ERROR
    assert verdict.repeat_count == 3
    assert "permission denied" in verdict.evidence


def test_repeated_action_error_below_threshold_not_stuck() -> None:
    records = [
        _record(failed=True, error_text="permission denied") for _ in range(2)
    ]
    assert analyze_tool_call_records(records).stuck is False


def test_repeated_action_error_requires_same_action() -> None:
    # Same failure count but different actions with different errors:
    # neither mode 2 (action mismatch) nor mode 3 (error mismatch) may fire.
    records = [
        _record("grep", {"pattern": "a"}, failed=True, error_text="err-a"),
        _record("grep", {"pattern": "b"}, failed=True, error_text="err-b"),
        _record("grep", {"pattern": "c"}, failed=True, error_text="err-c"),
    ]
    assert analyze_tool_call_records(records).stuck is False


def test_identical_failed_run_of_four_reports_mode_1_first() -> None:
    # OpenHands checks scenario 1 (identical pairs) before scenario 2.
    records = [
        _record(failed=True, error_text="permission denied") for _ in range(4)
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.pattern == PATTERN_REPEATED_ACTION_OBSERVATION


# ---------------------------------------------------------------------------
# Mode 3: same error text >= 3 consecutive failed calls, any tool/args.
# ---------------------------------------------------------------------------


def test_repeated_error_text_hits_across_different_tools() -> None:
    records = [
        _record("grep", {"pattern": "a"}, failed=True, error_text="quota exhausted"),
        _record("read", {"path": "b"}, failed=True, error_text="quota exhausted"),
        _record("list", {}, failed=True, error_text="quota exhausted"),
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ERROR_TEXT
    assert verdict.repeat_count == 3


def test_repeated_error_text_below_threshold_not_stuck() -> None:
    records = [
        _record("grep", {"pattern": "a"}, failed=True, error_text="quota exhausted"),
        _record("read", {"path": "b"}, failed=True, error_text="quota exhausted"),
    ]
    assert analyze_tool_call_records(records).stuck is False


def test_repeated_error_text_ignores_whitespace_and_ids_in_error() -> None:
    records = [
        _record("grep", {"pattern": str(index)}, failed=True,
                error_text=f"boom call-id=7 trace=550e8400-e29b-41d4-a716-44665544000{index}")
        for index in range(3)
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ERROR_TEXT


def test_repeated_error_text_requires_error_content() -> None:
    # Failed calls without any error text never feed mode 3.
    records = [
        _record("grep", {"pattern": str(index)}, failed=True, error_text="")
        for index in range(4)
    ]
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is False


# ---------------------------------------------------------------------------
# Mode 4: alternating A/B loop, >= threshold rounds.
# ---------------------------------------------------------------------------


def test_alternating_pattern_hits_at_threshold() -> None:
    records = [
        _record("grep", {"pattern": "a"}, error_text="ok-a"),
        _record("read", {"path": "b"}, error_text="ok-b"),
    ] * 3
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_ALTERNATING_ACTION_OBSERVATION
    assert verdict.repeat_count == 6


def test_alternating_pattern_below_threshold_not_stuck() -> None:
    records = [
        _record("grep", {"pattern": "a"}, error_text="ok-a"),
        _record("read", {"path": "b"}, error_text="ok-b"),
    ] * 2 + [
        _record("grep", {"pattern": "a"}, error_text="ok-a"),
    ]
    assert analyze_tool_call_records(records).stuck is False


def test_alternating_pattern_broken_by_new_call_not_stuck() -> None:
    records = [
        _record("grep", {"pattern": "a"}, error_text="ok-a"),
        _record("read", {"path": "b"}, error_text="ok-b"),
    ] * 3 + [
        _record("write", {"path": "c"}),
    ]
    assert analyze_tool_call_records(records).stuck is False


# ---------------------------------------------------------------------------
# Thresholds + switch + fail-open.
# ---------------------------------------------------------------------------


def test_threshold_env_overrides_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        turn_stuck_analyzer.TURN_STUCK_ACTION_OBSERVATION_THRESHOLD_ENV, "2"
    )
    assert thresholds_from_env().action_observation == 2
    verdict = analyze_tool_call_records([_record(), _record()])
    assert verdict.stuck is True
    assert verdict.repeat_count == 2


def test_invalid_threshold_env_falls_back_to_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        turn_stuck_analyzer.TURN_STUCK_ACTION_OBSERVATION_THRESHOLD_ENV, "zero"
    )
    monkeypatch.setenv(
        turn_stuck_analyzer.TURN_STUCK_ALTERNATING_THRESHOLD_ENV, "-3"
    )
    thresholds = thresholds_from_env()
    assert thresholds.action_observation == 4
    assert thresholds.alternating_pattern == 6


def test_detection_switch_defaults_on_and_env_off_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert is_turn_stuck_detection_enabled() is True
    monkeypatch.setenv(turn_stuck_analyzer.TURN_STUCK_ENABLED_ENV, "0")
    assert is_turn_stuck_detection_enabled() is False
    monkeypatch.setenv(turn_stuck_analyzer.TURN_STUCK_ENABLED_ENV, "false")
    assert is_turn_stuck_detection_enabled() is False


def test_analyzer_fail_open_when_detector_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(records, thresholds):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(
        turn_stuck_analyzer, "_detect_repeated_action_observation", _boom
    )
    records = [_record() for _ in range(6)]
    verdict = analyze_tool_call_records(records)
    # Mode 1 is dead but later detectors still run (fail-open per mode).
    assert verdict.stuck is False


def test_analyzer_tolerates_foreign_entries_and_empty_input() -> None:
    records: list[Any] = ["garbage", None, _record(), {"not": "a record"}]
    assert analyze_tool_call_records(records).stuck is False
    assert analyze_tool_call_records([]).stuck is False
    assert analyze_tool_call_records(None).stuck is False  # type: ignore[arg-type]


def test_scan_window_stays_bounded() -> None:
    records = [_record(arguments={"pattern": index}) for index in range(50)]
    records.extend(_record() for _ in range(4))
    verdict = analyze_tool_call_records(records)
    assert verdict.stuck is True
    assert verdict.repeat_count == 4


# ---------------------------------------------------------------------------
# Tool-trace extraction + per-turn accumulation.
# ---------------------------------------------------------------------------


def test_records_from_tool_trace_extracts_fields() -> None:
    trace = [
        _tool_trace_entry("grep", {"pattern": "x"}, result_text="found"),
        _tool_trace_entry(
            "write", {"path": "p"}, status="error", error="permission denied"
        ),
        _tool_trace_entry(
            "list", {"dir": "d"}, status="timeout", error=None, result_text=None
        ),
        {"no_name": True},
        "not-a-dict",
    ]
    records = records_from_tool_trace(trace)
    assert [record.tool_name for record in records] == ["grep", "write", "list"]
    assert records[0].failed is False
    assert records[0].error_text == "found"
    assert records[1].failed is True
    assert records[1].error_text == "permission denied"
    assert records[2].failed is True


def test_append_tool_call_records_accumulates_turn_rounds() -> None:
    accumulated: list[ToolCallRecord] = []
    append_tool_call_records(
        {"tool_trace": [_tool_trace_entry("grep", {"pattern": "a"})]}, accumulated
    )
    append_tool_call_records(
        {"tool_calls": [_tool_trace_entry("read", {"path": "b"}, error="denied",
                                         status="error")]},
        accumulated,
    )
    append_tool_call_records("not-a-dict", accumulated)
    append_tool_call_records({"tool_trace": None}, accumulated)
    assert [record.tool_name for record in accumulated] == ["grep", "read"]
    assert accumulated[1].failed is True


# ---------------------------------------------------------------------------
# Worker hook: enabled switch, accumulation, fail-open.
# ---------------------------------------------------------------------------


def test_worker_hook_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(turn_stuck_analyzer.TURN_STUCK_ENABLED_ENV, "0")
    accumulated: list[ToolCallRecord] = []
    poisoned = {"tool_trace": [_tool_trace_entry("grep", {"pattern": "x"})] * 9}
    assert worker._evaluate_turn_stuck(poisoned, accumulated) is None
    # Zero impact: nothing is accumulated while the switch is off.
    assert accumulated == []


def test_worker_hook_accumulates_rounds_and_returns_verdict() -> None:
    accumulated: list[ToolCallRecord] = []
    first = {"tool_trace": [_tool_trace_entry("grep", {"pattern": "x"})]}
    second = {
        "tool_trace": [
            _tool_trace_entry("grep", {"pattern": "x"}),
            _tool_trace_entry("grep", {"pattern": "x"}),
            _tool_trace_entry("grep", {"pattern": "x"}),
        ]
    }
    assert worker._evaluate_turn_stuck(first, accumulated) is None
    assert len(accumulated) == 1
    verdict = worker._evaluate_turn_stuck(second, accumulated)
    assert verdict is not None
    assert verdict.stuck is True
    assert verdict.pattern == PATTERN_REPEATED_ACTION_OBSERVATION
    assert verdict.repeat_count == 4
    assert len(accumulated) == 4


def test_worker_hook_fail_open_when_analyzer_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(records, *, thresholds=None):
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(
        worker.turn_stuck_analyzer, "analyze_tool_call_records", _boom
    )
    accumulated: list[ToolCallRecord] = []
    stuck_round = {
        "tool_trace": [_tool_trace_entry("grep", {"pattern": "x"})] * 9
    }
    assert worker._evaluate_turn_stuck(stuck_round, accumulated) is None


def test_worker_hook_pause_reason_constant_is_stable() -> None:
    # The pause reason rides the existing paused_limit pipeline via
    # metadata.continuation_pause_reason; keep it machine-stable.
    assert STUCK_LOOP_PAUSE_REASON == "stuck_loop_detected"
