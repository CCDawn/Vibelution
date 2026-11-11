"""Guard against working on top of a dirty main checkout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import main_guard
from scripts import task_closeout


@pytest.fixture()
def stub_checkout(monkeypatch, tmp_path):
    """Point repository resolution at a throwaway directory.

    Only the git-facing resolution is stubbed; the dirty-main attribution below
    is stubbed separately so each test states which side it exercises.
    """

    monkeypatch.setattr(main_guard, "resolve_main_checkout", lambda start: tmp_path)
    return tmp_path


@pytest.fixture()
def clean_attribution(monkeypatch):
    monkeypatch.setattr(
        task_closeout,
        "describe_dirty_main",
        lambda context: task_closeout.DirtyMainAttribution(
            file_lines=(), owner_lines=(), next_action=""
        ),
    )


@pytest.fixture()
def dirty_attribution(monkeypatch):
    monkeypatch.setattr(
        task_closeout,
        "describe_dirty_main",
        lambda context: task_closeout.DirtyMainAttribution(
            file_lines=("dirty_main_file:  M core/web/services/session_service.py (mtime=2026-11-11T06:29:47Z)",),
            owner_lines=("dirty_main_suspected_owner: agent worktree-abc (branch codex/other) via claim claim-1",),
            next_action="main has uncommitted edits; ask the suspected owner to commit or revert them.",
        ),
    )


def test_clean_main_exits_zero(clean_attribution, stub_checkout):
    assert main_guard.main(["--repo", str(stub_checkout)]) == main_guard.EXIT_CLEAN


def test_dirty_main_exits_one_and_names_the_owner(dirty_attribution, stub_checkout, capsys):
    assert main_guard.main(["--repo", str(stub_checkout)]) == main_guard.EXIT_DIRTY
    output = capsys.readouterr().out
    assert "main_guard: dirty" in output
    assert "dirty_main_file:  M core/web/services/session_service.py" in output
    assert "dirty_main_suspected_owner: agent worktree-abc" in output


def test_json_payload_is_bounded_evidence(dirty_attribution, stub_checkout, capsys):
    assert main_guard.main(["--repo", str(stub_checkout), "--json"]) == main_guard.EXIT_DIRTY
    payload = json.loads(capsys.readouterr().out)
    assert payload["schemaVersion"] == main_guard.SCHEMA_VERSION
    assert payload["status"] == "dirty"
    assert payload["owners"] == ["agent worktree-abc (branch codex/other) via claim claim-1"]
    assert len(payload["fileLines"]) == 1


def test_inspection_failure_exits_two(stub_checkout, monkeypatch):
    def explode(context):
        raise RuntimeError("git status failed")

    monkeypatch.setattr(task_closeout, "describe_dirty_main", explode)
    assert main_guard.main(["--repo", str(stub_checkout)]) == main_guard.EXIT_FAILED


def test_resolve_main_checkout_returns_the_shared_checkout():
    repo_root = main_guard.resolve_main_checkout(Path(__file__).resolve().parents[1])
    assert (repo_root / ".git").exists()


def test_inspect_marks_clean_checkout_without_next_action(clean_attribution, tmp_path):
    payload = main_guard.inspect_main_checkout(tmp_path)
    assert payload["status"] == "clean"
    assert payload["fileLines"] == []
    assert payload["owners"] == []
    assert payload["nextAction"] == ""
