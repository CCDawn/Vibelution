from __future__ import annotations

import subprocess

from scripts import local_quality_gate as gate
from scripts import task_closeout as closeout


def _context(tmp_path):
    return closeout.CloseoutContext(
        main_root=tmp_path / "main",
        task_root=tmp_path / "task",
        branch="codex/test-task",
    )


def test_summarize_failure_falls_back_to_exit_code_and_argv0() -> None:
    completed = subprocess.CompletedProcess(
        args=["pytest", "-m", "pytest"],
        returncode=3,
        stdout="",
        stderr="",
    )
    summary = gate.summarize_failure(completed, "pytest")
    assert "exit 3" in summary
    assert "pytest" in summary


def test_summarize_failure_keeps_bounded_tail_when_no_diagnostic_line() -> None:
    completed = subprocess.CompletedProcess(
        args=["tool.exe", "--check"],
        returncode=2,
        stdout="",
        stderr="usage: tool.exe [--check]",
    )
    summary = gate.summarize_failure(completed, "tool")
    assert "exit 2" in summary
    assert "usage: tool.exe [--check]" in summary


def test_validation_failure_exposes_structured_failure_details(tmp_path, monkeypatch) -> None:
    failed_command = gate.ProcessResult(
        kind="pytest",
        argv=["python.exe", "-m", "pytest", "tests/test_x.py"],
        cwd=str(tmp_path),
        exit_code=1,
        duration_ms=12,
        status="failed",
        failure_summary="pytest: FAILED tests/test_x.py::test_y",
    )
    monkeypatch.setattr(closeout, "resolve_context", lambda *_a, **_k: _context(tmp_path))
    monkeypatch.setattr(
        closeout,
        "resolve_claim_identity",
        lambda _context, claim_id="", agent_id="": (claim_id or "claim-dev", agent_id or "agent-test"),
    )
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *_a, **_k: None)
    monkeypatch.setattr(closeout, "discover_manifest", lambda _context: None)
    monkeypatch.setattr(
        gate,
        "run_closeout",
        lambda *_a, **_k: gate.GateResult(
            outcome="failed",
            exit_code=1,
            commands=[failed_command],
        ),
    )

    result = closeout.run_managed_closeout(
        tmp_path / "task",
        claim_id="claim-dev",
        agent_id="agent-test",
    )

    assert result.status == "validation_failed"
    # Compatibility: the coarse string list is unchanged.
    assert result.errors == ["failed"]
    # New: the caller learns which command failed, how, and why.
    assert len(result.failures) == 1
    detail = result.failures[0]
    assert detail.code == "failed"
    assert detail.command_kind == "pytest"
    assert detail.argv0 == "python.exe"
    assert detail.exit_code == 1
    assert "FAILED tests/test_x.py::test_y" in detail.summary
