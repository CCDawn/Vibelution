# -*- coding: utf-8 -*-
"""Contract: a fail-closed context-budget stop must stay user-visible.

Context compression can succeed (tokens dropped, checkpoint written) and still
trip the fail-closed budget/retention gate afterwards. That path used to hit a
bare ``break``: the turn stopped with no runtime notice and no structured turn
diagnostic, so the session looked frozen right after "compression finished".

The agent main loop has no isolated unit-test seam, so this contract pins the
observable source shape of that branch instead of its runtime behaviour.
"""

from __future__ import annotations

from pathlib import Path

AGENT_PATH = Path(__file__).resolve().parents[1] / "agent.py"


def test_fail_closed_compression_stop_emits_notice_and_diagnostic() -> None:
    source = AGENT_PATH.read_text(encoding="utf-8")
    marker = "if should_break:"
    assert source.count(marker) == 1, "expected exactly one fail-closed should_break branch"
    branch = source.split(marker, 1)[1][:4000]

    assert "build_runtime_notice_message" in branch, (
        "a compression stop must append a runtime notice so the user sees why the turn ended"
    )
    assert "_record_turn_failure_diagnostic" in branch, (
        "a compression stop must persist a structured turn failure diagnostic"
    )
    assert "context_budget_exhausted" in branch, (
        "the diagnostic must reuse the context_budget_exhausted reason code"
    )
    assert "compress_context_or_new_session" in branch, (
        "the diagnostic must tell the user how to recover"
    )
