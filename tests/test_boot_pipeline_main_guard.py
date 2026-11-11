"""Startup self-check surfaces a dirty main checkout instead of hiding it."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core.infrastructure import boot_pipeline
from scripts import main_guard


def _payload(status: str, *, files=(), owners=()):
    return {
        "schemaVersion": 1,
        "status": status,
        "repoRoot": "repo",
        "fileLines": list(files),
        "owners": list(owners),
        "nextAction": "ask the suspected owner to commit or revert them." if files else "",
    }


def test_clean_checkout_is_silent(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(main_guard, "inspect_main_checkout", lambda root: _payload("clean"))
    boot_pipeline._report_dirty_main_worktree(tmp_path)
    assert capsys.readouterr().err == ""


def test_dirty_checkout_names_the_owner(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("VIBELUTION_MAIN_GUARD", raising=False)
    monkeypatch.setattr(
        main_guard,
        "inspect_main_checkout",
        lambda root: _payload(
            "dirty",
            files=("dirty_main_file:  M core/web/services/session_service.py",),
            owners=("agent worktree-abc (branch codex/other) via claim claim-1",),
        ),
    )
    boot_pipeline._report_dirty_main_worktree(tmp_path)
    err = capsys.readouterr().err
    assert "main 工作区有未提交改动" in err
    assert "dirty_main_file:  M core/web/services/session_service.py" in err
    assert "dirty_main_suspected_owner: agent worktree-abc" in err


def test_block_mode_refuses_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBELUTION_MAIN_GUARD", "block")
    monkeypatch.setattr(
        main_guard,
        "inspect_main_checkout",
        lambda root: _payload("dirty", files=("dirty_main_file:  M a.py",), owners=("agent x",)),
    )
    with pytest.raises(RuntimeError, match="已阻止启动"):
        boot_pipeline._report_dirty_main_worktree(tmp_path)


def test_inspection_failure_never_blocks_startup(monkeypatch, tmp_path):
    def explode(root):
        raise RuntimeError("git status failed")

    monkeypatch.setattr(main_guard, "inspect_main_checkout", explode)
    boot_pipeline._report_dirty_main_worktree(tmp_path)


def test_preflight_runs_the_guard_before_other_checks(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(boot_pipeline, "_report_dirty_main_worktree", lambda root: calls.append(root))
    monkeypatch.setattr(boot_pipeline, "project_venv_python", lambda root: sys.executable)
    monkeypatch.setattr(boot_pipeline.sys, "platform", "linux")
    config = SimpleNamespace(
        runtime=SimpleNamespace(preflight_doctor=True, require_venv=False)
    )
    boot_pipeline.run_preflight_doctor(config, project_root=tmp_path)
    assert calls == [tmp_path]


def test_preflight_respects_the_disable_switch(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(boot_pipeline, "_report_dirty_main_worktree", lambda root: calls.append(root))
    config = SimpleNamespace(
        runtime=SimpleNamespace(preflight_doctor=False, require_venv=False)
    )
    boot_pipeline.run_preflight_doctor(config, project_root=tmp_path)
    assert calls == []
