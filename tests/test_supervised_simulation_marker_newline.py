# -*- coding: utf-8 -*-
"""Regression: the simulation candidate marker must stay LF-only.

``_simulation_candidate_modifier`` 用 ``Path.write_text`` 重写仓库里已提交的
标记文件；Windows 文本模式默认把 ``\n`` 翻译成 ``\r\n``，导致受控提交被
pre-commit 的 ``git diff --cached --check`` 以 trailing whitespace 拒绝，
监督进化 simulation 链在最后一步失败（swte-7f06b70537f9 实弹验收定案）。
"""

from __future__ import annotations

from pathlib import Path

from core.web.services.supervised_worktree_evolution_service import (
    _simulation_candidate_modifier,
)


def test_simulation_candidate_modifier_writes_lf_only(tmp_path: Path) -> None:
    result = _simulation_candidate_modifier(tmp_path, "prompt", {"runId": "run"})

    marker = tmp_path / "tests" / "supervised_worktree_candidate_marker.py"
    content = marker.read_bytes()
    assert b"\r" not in content
    assert content.endswith(b"CANDIDATE_SELF_EDITED = True\n")
    assert result["status"] == "success"
    assert result["changedPath"] == "tests/supervised_worktree_candidate_marker.py"
