"""The workbench boot path reports a dirty main checkout once per lifespan."""

from __future__ import annotations

import logging

from core.web import lifecycle
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


def test_clean_checkout_reports_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VIBELUTION_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(main_guard, "inspect_main_checkout", lambda root: _payload("clean"))

    assert lifecycle._report_dirty_main_worktree_on_startup() is False
    assert capsys.readouterr().err == ""


def test_dirty_checkout_names_the_owner(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VIBELUTION_WORKSPACE_ROOT", str(tmp_path))
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

    assert lifecycle._report_dirty_main_worktree_on_startup() is True
    err = capsys.readouterr().err
    assert "main 工作区有未提交改动" in err
    assert "dirty_main_suspected_owner: agent worktree-abc" in err


def test_block_mode_still_lets_the_workbench_boot(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("VIBELUTION_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("VIBELUTION_MAIN_GUARD", "block")
    monkeypatch.setattr(
        main_guard,
        "inspect_main_checkout",
        lambda root: _payload("dirty", files=("dirty_main_file:  M a.py",), owners=("agent x",)),
    )

    with caplog.at_level(logging.WARNING):
        assert lifecycle._report_dirty_main_worktree_on_startup() is True
    assert "main 工作区不干净" in caplog.text


def test_workspace_root_comes_from_the_environment(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setenv("VIBELUTION_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setattr(
        main_guard,
        "inspect_main_checkout",
        lambda root: seen.append(root) or _payload("clean"),
    )

    lifecycle._report_dirty_main_worktree_on_startup()
    assert seen == [tmp_path.resolve()]


def test_inspection_failure_never_breaks_boot(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("VIBELUTION_WORKSPACE_ROOT", str(tmp_path))

    def explode(root):
        raise RuntimeError("git status failed")

    monkeypatch.setattr(main_guard, "inspect_main_checkout", explode)

    assert lifecycle._report_dirty_main_worktree_on_startup() is False
    assert capsys.readouterr().err == ""
