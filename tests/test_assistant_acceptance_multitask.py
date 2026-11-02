"""Fail-closed checks for scheduling evidence, without simulated E2E claims."""
from pathlib import Path

import pytest

from scripts import acceptance_assistant_multitask as case


def test_parallel_interval_and_dependency_use_real_boundaries():
    first, second, third = ({"startEpoch": 1, "endEpoch": 8}, {"startEpoch": 3, "endEpoch": 9}, {"startEpoch": 12})
    assert case.concurrency_and_dependency(first, second, third, [10, 11], 11.5)["parallelOverlapSeconds"] == 5


@pytest.mark.parametrize("first,second,third,receipts,dispatch,code", [
    ({"startEpoch": 1, "endEpoch": 3}, {"startEpoch": 3, "endEpoch": 9}, {"startEpoch": 12}, [10, 11], 11.5, "parallel_native_execution_not_observed"),
    ({"startEpoch": 1, "endEpoch": 8}, {"startEpoch": 3, "endEpoch": 9}, {"startEpoch": 12}, [10], 11.5, "successful_prerequisite_receipts_missing"),
    ({"startEpoch": 1, "endEpoch": 8}, {"startEpoch": 3, "endEpoch": 9}, {"startEpoch": 12}, [10, 11], 9.5, "dependent_task_started_before_prerequisites"),
    ({"startEpoch": 1, "endEpoch": 8}, {"startEpoch": 3, "endEpoch": 9}, {"startEpoch": 10}, [10, 11], 11.5, "dependent_task_started_before_prerequisites"),
])
def test_parallel_and_dependency_claims_fail_closed(first, second, third, receipts, dispatch, code):
    with pytest.raises(case.AcceptanceFailure, match=code):
        case.concurrency_and_dependency(first, second, third, receipts, dispatch)


@pytest.mark.parametrize("answer,expected", [("ALPHA_TOTAL=164", True), ("**ALPHA_TOTAL**=`164`", True),
    ("ALPHA_TOTAL=164.3", False), ("ALPHA_TOTAL=1640", False), ("ALPHA_TOTAL=164; ALPHA_TOTAL=999", False),
    ("164 is the result", False), ("XALPHA_TOTAL=164", False),
    ("| ALPHA_TOTAL | **164** | verified input |", True),
    ("| ALPHA_TOTAL | 164.3 |", False), ("| XALPHA_TOTAL | 164 |", False),
    ("| ALPHA_TOTAL | 164 |\nALPHA_TOTAL=999", False)])
def test_result_tags_require_exact_unambiguous_values(answer, expected):
    assert case.tagged_value(answer, "ALPHA_TOTAL", 164) is expected


def test_prompt_does_not_disclose_fixture_values():
    message = case.task_message("project", ["agent-a", "agent-b"], "goal", ["a", "b", "c"],
                                [Path("alpha.json"), Path("beta.json")])
    snapshots = [case.input_snapshot(case.base.SOURCE_ROOT / case.INPUT_DIR / name) for name in ("alpha.json", "beta.json")]
    assert all(str(snapshot["total"]) not in message for snapshot in snapshots)
    assert "max_tasks=3" in message and "title" in message


def read_events(path, content):
    return [{"eventType": "tool_result", "toolCallId": "read-1", "payload": {"toolCall": {
        "name": "read_file_tool", "arguments": {"file_path": str(path), "max_lines": 0}, "result": content}}}]


def test_real_read_requires_the_bound_file_content(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"rows":[{"quantity":3,"unit_value":17}]}', encoding="utf-8")
    snapshot = case.input_snapshot(path)
    rendered = "[文件] " + str(path) + "\n第     1 行 | " + snapshot["text"]
    proof = case.read_proof(read_events(path, rendered), snapshot)
    assert proof["inputSha256"] == snapshot["sha256"]
    assert "quantity" not in str(proof)
    with pytest.raises(case.AcceptanceFailure, match="real_input_file_read_not_observed"):
        case.read_proof(read_events(path, "read success; sum=51"), snapshot)
    with pytest.raises(case.AcceptanceFailure, match="real_input_file_read_not_observed"):
        case.read_proof(read_events(tmp_path / "other.json", rendered), snapshot)


def test_native_status_alone_cannot_prove_business_success():
    task = {"taskId": "native-1", "sessionId": "s1", "turnId": "t1", "status": "succeeded"}
    rows = [{"eventType": "turn_started", "turnId": "t1", "timestamp": "2026-01-01T00:00:00Z"},
            {"eventType": "user_message", "turnId": "t1"},
            {"eventType": "turn_completed", "turnId": "t1", "timestamp": "2026-01-01T00:00:03Z"}]
    with pytest.raises(case.AcceptanceFailure, match="native_arithmetic_result_incorrect"):
        case.native_proof(task, rows, rows, {"ALPHA_TOTAL": 51}, [])


def test_duplicate_native_admission_cannot_pass():
    task = {"taskId": "native-1", "sessionId": "s1", "turnId": "t1", "status": "succeeded"}
    rows = [{"eventType": "user_message", "turnId": "t1"}] * 2
    with pytest.raises(case.AcceptanceFailure, match="native_user_admission_not_unique"):
        case.native_proof(task, rows, rows, {}, [])


def test_journal_times_must_have_timezone():
    with pytest.raises(case.AcceptanceFailure, match="journal_timestamp_not_qualified"):
        case.event_time({"timestamp": "2026-01-01T00:00:00"})
