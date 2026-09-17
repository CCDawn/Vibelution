# -*- coding: utf-8 -*-
"""Regression: the candidate evidence protocol must run outside the sandbox terminal.

Windows 上通用沙箱终端对非 danger_full_access 的直 shell fail-closed 拒绝
（SANDBOX_UNVERIFIED），候选证据子进程结构性无法启动（swte-823fac5f4081
定案：复跑 Agent 完整通过验收，证据子进程零输出即失败）。证据协议的命令
由服务方全权构造、输入有界、纯本地计算，改走专用直子进程。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.web.services.supervised_candidate_runtime_service import (
    CandidateRuntimeExecutionError,
    _run_candidate_evidence_subprocess,
)


def test_evidence_subprocess_returns_stdout(tmp_path: Path) -> None:
    output = _run_candidate_evidence_subprocess(
        [sys.executable, "-c", "print('evidence-ok')"],
        timeout=60,
        cwd=str(tmp_path),
    )
    assert output.strip() == "evidence-ok"


def test_evidence_subprocess_reports_nonzero_exit(tmp_path: Path) -> None:
    with pytest.raises(CandidateRuntimeExecutionError) as excinfo:
        _run_candidate_evidence_subprocess(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            timeout=60,
            cwd=str(tmp_path),
        )
    assert "exited with 3" in str(excinfo.value)
    assert "boom" in str(excinfo.value)


def test_evidence_subprocess_rejects_other_environment_policies(tmp_path: Path) -> None:
    with pytest.raises(CandidateRuntimeExecutionError):
        _run_candidate_evidence_subprocess(
            [sys.executable, "-c", "print('x')"],
            timeout=60,
            cwd=str(tmp_path),
            _environment_policy="default",
        )


def test_evidence_subprocess_honors_cancel_checker(tmp_path: Path) -> None:
    with pytest.raises(CandidateRuntimeExecutionError) as excinfo:
        _run_candidate_evidence_subprocess(
            [sys.executable, "-c", "print('never')"],
            timeout=60,
            cwd=str(tmp_path),
            _cancel_checker=lambda: "test_cancelled",
        )
    assert "test_cancelled" in str(excinfo.value)


def test_evidence_subprocess_enforces_output_limit(tmp_path: Path) -> None:
    from core.web.services import supervised_candidate_runtime_service as service

    original_limit = service._CANDIDATE_RUNTIME_OUTPUT_LIMIT
    service._CANDIDATE_RUNTIME_OUTPUT_LIMIT = 16
    try:
        with pytest.raises(CandidateRuntimeExecutionError) as excinfo:
            _run_candidate_evidence_subprocess(
                [sys.executable, "-c", "print('a' * 64)"],
                timeout=60,
                cwd=str(tmp_path),
            )
        assert "output exceeded" in str(excinfo.value)
    finally:
        service._CANDIDATE_RUNTIME_OUTPUT_LIMIT = original_limit
