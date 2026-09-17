# -*- coding: utf-8 -*-
"""Regression: the simulation candidate marker must be LF-only and per-run.

``_simulation_candidate_modifier`` 重写仓库里已提交的标记文件，两个历史缺陷
都发生在这里（swte-7f06b70537f9 / swte-6fb5b3fe25f4 实弹验收定案）：

1. Windows 文本模式把 ``\n`` 翻译成 ``\r\n``，受控提交被 pre-commit 的
   ``git diff --cached --check`` 以 trailing whitespace 拒绝。
2. 写入内容与 main 已提交的 fixture 字节相同 → 候选零 diff →
   ``CandidateModificationNoChanges`` fail-closed 拦停。修复为每轮写入
   唯一 ``SIMULATION_RUN_ID``，保证对 main 恒有可复跑 diff。
"""

from __future__ import annotations

from pathlib import Path

from core.web.services.supervised_worktree_evolution_service import (
    _simulation_candidate_modifier,
)


def test_simulation_candidate_modifier_writes_lf_only_with_run_id(
    tmp_path: Path,
) -> None:
    result = _simulation_candidate_modifier(tmp_path, "prompt", {"runId": "swte-abc"})

    marker = tmp_path / "tests" / "supervised_worktree_candidate_marker.py"
    content = marker.read_bytes()
    assert b"\r" not in content
    assert b"CANDIDATE_SELF_EDITED = True\n" in content
    assert content.endswith(b'SIMULATION_RUN_ID = "swte-abc"\n')
    assert result["status"] == "success"
    assert result["changedPath"] == "tests/supervised_worktree_candidate_marker.py"


def test_simulation_candidate_marker_differs_between_runs(tmp_path: Path) -> None:
    _simulation_candidate_modifier(tmp_path, "prompt", {"runId": "swte-one"})
    first = (tmp_path / "tests" / "supervised_worktree_candidate_marker.py").read_bytes()
    _simulation_candidate_modifier(tmp_path, "prompt", {"runId": "swte-two"})
    second = (tmp_path / "tests" / "supervised_worktree_candidate_marker.py").read_bytes()
    assert first != second
