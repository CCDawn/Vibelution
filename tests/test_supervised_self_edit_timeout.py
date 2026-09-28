# -*- coding: utf-8 -*-
"""Regression: the real self-edit budget must respect bundle declarations.

``_real_candidate_modifier`` 历史硬编码 900 秒；真实 Agent 在大仓库里
读码-补丁-验证常超预算，被 ``candidate_modify_timeout`` 收口——
swte-28e3980425ef 实弹定案：Agent 已在候选 worktree 产出真实 diff
仍被 900 秒截断。修复后预算 = max(900, bundle default_timeout_seconds)，
经 flow 注入 ``context["timeoutSeconds"]``。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.infrastructure import developer_sandbox
from core.web.services import supervised_worktree_evolution_service as service


def test_self_edit_timeout_defaults_to_floor_when_missing() -> None:
    assert service._real_self_edit_timeout({}) == 900


def test_self_edit_timeout_keeps_floor_when_declared_lower() -> None:
    assert service._real_self_edit_timeout({"timeoutSeconds": 600}) == 900
    assert service._real_self_edit_timeout({"timeoutSeconds": 0}) == 900


def test_self_edit_timeout_respects_higher_declaration() -> None:
    assert service._real_self_edit_timeout({"timeoutSeconds": 1800}) == 1800


def test_self_edit_timeout_tolerates_garbage_values() -> None:
    assert service._real_self_edit_timeout({"timeoutSeconds": "abc"}) == 900
    assert service._real_self_edit_timeout({"timeoutSeconds": None}) == 900


def test_bundle_budget_reads_default_timeout_seconds(tmp_path: Path) -> None:
    payload = json.dumps(
        {
            "bundle_name": "probe_timeout_v1",
            "benchmark": "unit",
            "default_timeout_seconds": 2400,
            "cases": [{"case_id": "one", "prompt": "case one"}],
        }
    )
    sandbox_bundle = developer_sandbox.seeded_sandbox_workspace_path(
        tmp_path, "evaluation", "bundles", "probe_timeout_v1.json"
    )
    for bundle_path in {
        tmp_path / "workspace" / "evaluation" / "bundles" / "probe_timeout_v1.json",
        sandbox_bundle,
    }:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(payload, encoding="utf-8")

    original = service._storage_project_root_arg

    def fake_storage_root(root):
        return tmp_path

    service._storage_project_root_arg = fake_storage_root
    try:
        assert service._bundle_self_edit_timeout_budget(tmp_path, "probe_timeout_v1") == 2400
    finally:
        service._storage_project_root_arg = original
        sandbox_bundle.unlink(missing_ok=True)


def test_bundle_budget_falls_back_to_floor_on_missing_bundle(tmp_path: Path) -> None:
    assert service._bundle_self_edit_timeout_budget(tmp_path, "no_such_bundle") == 900
