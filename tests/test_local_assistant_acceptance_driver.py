"""Regression for real assistant replies that format exit codes as Markdown."""

import pytest

from scripts.acceptance_local_assistant_development import reports_exit_zero


@pytest.mark.parametrize("terminal_id,exit_code,expected", [
    ("test-session", 0, 0), ("other-session", 0, None), ("test-session", 1, None),
])
def test_streamed_test_output_is_bound_to_its_terminal_exit(terminal_id, exit_code, expected):
    from scripts.acceptance_local_assistant_development import TEST_COMMAND, tool_evidence

    def result(name, args, value):
        return {"eventType": "tool_result", "payload": {"toolCall": {
            "name": name, "arguments": args, "result": value}}}

    events = [result("exec_command", {"cmd": TEST_COMMAND}, {
        "terminalSessionId": "test-session", "status": "running",
        "stderr": "Ran 3 tests in 0.001s\n\nOK\n"}),
        result("write_stdin", {"session_id": terminal_id}, {
            "terminalSessionId": terminal_id, "status": "completed", "exitCode": exit_code})]
    assert tool_evidence(events)["testExitCode"] == expected


@pytest.mark.parametrize("answer", [
    "退出码：`0`（Ran 3 tests OK）",
    "- **退出码**：**0**",
    "exitCode=0",
    "exitCode: `0`",
])
def test_exit_zero_accepts_plain_and_formatted_reports(answer):
    assert reports_exit_zero(answer)


@pytest.mark.parametrize("answer", [
    "退出码：1，预期 0",
    "exitCode=10",
    "exitCode=0.1",
    "exitCode=00",
    "exitCode=0x1",
    "退出码：-0",
    "Ran 3 tests OK",
])
def test_exit_zero_requires_an_explicit_exact_zero_report(answer):
    assert not reports_exit_zero(answer)
