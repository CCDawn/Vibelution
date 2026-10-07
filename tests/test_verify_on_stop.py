"""收工证据门：改了可验证代码之后，没有新的通过记录就不能口头收工。"""

from __future__ import annotations

import pytest

from core.orchestration.tool_lifecycle import ToolLifecycleBridge
from core.orchestration.verify_on_stop import (
    decide_verify_finish,
    note_tool_outcome,
    reset_verify_on_stop_turn,
    take_verify_finish,
)


@pytest.fixture(autouse=True)
def _fresh_turn(monkeypatch):
    monkeypatch.delenv("VIBELUTION_VERIFY_ON_STOP", raising=False)
    reset_verify_on_stop_turn()
    yield
    reset_verify_on_stop_turn()


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_VERIFY_ON_STOP", "1")


def test_gate_is_off_by_default_after_a_code_edit():
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )

    decision = decide_verify_finish()

    assert decision.action == "allow"
    assert decision.text == ""


def test_docs_only_edit_does_not_ask_for_a_check(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "docs/guide.md"},
        result="wrote",
    )
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "LICENSE"},
        result="wrote",
    )

    assert decide_verify_finish().action == "allow"


def test_code_edit_without_a_pass_asks_twice_then_allows_close(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )

    first = take_verify_finish(can_continue=True)
    second = take_verify_finish(can_continue=True)
    third = decide_verify_finish()

    assert first.action == "nudge"
    assert "core/foo.py" in first.text
    assert "整仓" in first.text
    assert second.action == "nudge"
    assert third.action == "allow_unverified"
    assert third.reason == "nudge_cap"


def test_pass_after_the_last_edit_allows_close(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="apply_diff_edit_tool",
        args={"file_path": "web/src/app.tsx"},
        result="edited",
    )
    note_tool_outcome(
        tool_name="cli_tool",
        args={"command": "npx vitest run web/src/app.tsx"},
        result="passed",
    )

    assert decide_verify_finish().action == "allow"


def test_pass_is_stale_after_another_code_edit(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )
    note_tool_outcome(
        tool_name="exec_command",
        args={"command": "pytest -q tests/test_foo.py"},
        result="passed",
    )
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/bar.py"},
        result="wrote",
    )

    decision = decide_verify_finish()

    assert decision.action == "nudge"
    assert "core/bar.py" in decision.text


def test_failed_or_unrelated_command_is_not_a_pass(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )
    note_tool_outcome(
        tool_name="cli_tool",
        args={"command": "pytest -q"},
        result="[错误] 2 failed",
    )
    note_tool_outcome(
        tool_name="cli_tool",
        args={"command": "git status"},
        result="clean",
    )

    assert decide_verify_finish().action == "nudge"


def test_doc_only_patch_does_not_ask_and_code_patch_does(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="apply_patch_tool",
        args={"patch_text": "*** Update File: README.md\n-old\n+new\n"},
        result="patched",
    )
    assert decide_verify_finish().action == "allow"

    note_tool_outcome(
        tool_name="apply_patch_tool",
        args={"patch_text": "*** Update File: core/foo.py\n-old\n+new\n"},
        result="patched",
    )
    assert decide_verify_finish().action == "nudge"


def test_python_lint_success_counts_as_a_fresh_pass(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )
    note_tool_outcome(tool_name="python_lint_tool", args={"target": "core/foo.py"}, result="clean")

    assert decide_verify_finish().action == "allow"


def test_no_remaining_iteration_does_not_spend_a_nudge(monkeypatch):
    _enable(monkeypatch)
    note_tool_outcome(
        tool_name="write_file_tool",
        args={"file_path": "core/foo.py"},
        result="wrote",
    )

    blocked = take_verify_finish(can_continue=False)
    still_open = decide_verify_finish()

    assert blocked.action == "allow_unverified"
    assert blocked.reason == "iteration_budget"
    assert still_open.action == "nudge"


def test_tool_result_bridge_records_a_verifiable_edit(monkeypatch):
    _enable(monkeypatch)
    ToolLifecycleBridge.handle_tool_result(
        {"name": "write_file_tool", "id": "call-verify", "args": {"file_path": "core/foo.py"}},
        "wrote",
        None,
        [],
    )

    assert decide_verify_finish().action == "nudge"
