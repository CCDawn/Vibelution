# -*- coding: utf-8 -*-
"""Regression: failed supervised worktree runs must not leak resources.

Historically candidate cleanup hung only on the manual ``discard`` action, so
failure exits (``CandidateModificationNoChanges``, controlled-commit gate
rejection) leaked the harness worktree, the ``codex/supervised-<runId>``
branch, and any claim registered by the pre-commit guard during a failed
commit attempt (swte-7f06b70537f9 / swte-6fb5b3fe25f4 实弹验收定案).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from core.infrastructure import developer_sandbox
from core.web.services import supervised_worktree_evolution_service as service


def _run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "test@example.local")
    _run_git(repo, "config", "user.name", "Test User")


def _write_bundle(project_root: Path, name: str = "closed_loop_v1") -> None:
    bundle = {
        "bundle_name": name,
        "benchmark": "unit",
        "cases": [
            {"case_id": "one", "prompt": "case one"},
            {"case_id": "two", "prompt": "case two"},
        ],
    }
    payload = json.dumps(bundle, ensure_ascii=False, indent=2)
    bundle_paths = {
        project_root / "workspace" / "evaluation" / "bundles" / f"{name}.json",
        developer_sandbox.seeded_sandbox_workspace_path(
            project_root, "evaluation", "bundles", f"{name}.json"
        ),
    }
    for bundle_path in bundle_paths:
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(payload, encoding="utf-8")


def _fake_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    successes = 1 if role == "baseline" else 2
    return {
        "role": role,
        "status": "success",
        "score": successes * 50.0,
        "successes": successes,
        "total": 2,
        "failures": 2 - successes,
        "bundleName": bundle_name,
        "summary": f"{role} fake score",
    }


def _no_change_modifier(_: Path, __: str, ___: dict) -> dict:
    return {
        "status": "success",
        "summary": "candidate only inspected files",
        "conversationSummary": {
            "conversation_backend": {
                "enabled": True,
                "session_id": "session-improver",
                "observed_active_turn_id": "turn-improve",
            }
        },
    }


def _exploding_judge_after_rubric(_: Path, __: str, phase: str, context: dict) -> dict:
    if phase in {"rubric", "baseline"}:
        return service._simulation_judge_runner(_, __, phase, context)
    # "rerun" judgment runs only after the candidate worktree existed.
    raise RuntimeError("judge exploded after the candidate worktree existed")


def _run_failing_flow(tmp_path: Path, *, keep_worktree: bool = False) -> tuple[Path, dict]:
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    snapshot = service.run_supervised_worktree_flow(
        {
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "manual",
            "keepWorktree": keep_worktree,
        },
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=_no_change_modifier,
            judge_runner=_exploding_judge_after_rubric,
        ),
    )
    return project_root, snapshot


def test_failed_run_auto_cleans_worktree_and_branch(tmp_path: Path) -> None:
    project_root, snapshot = _run_failing_flow(tmp_path)

    assert snapshot["status"] == "failed"
    worktree = snapshot["candidateWorktree"]
    assert str(worktree.get("path") or "")
    assert not Path(str(worktree["path"])).exists()
    auto_cleanup = worktree["autoCleanup"]
    assert auto_cleanup["status"] == "removed"
    assert auto_cleanup["branchRemoval"]["status"] == "deleted"

    run_id = str(snapshot["runId"])
    remaining = _run_git(project_root, "branch", "--list", f"codex/supervised-{run_id}")
    assert remaining == ""


def test_failed_run_preserves_worktree_when_keep_worktree(tmp_path: Path) -> None:
    _, snapshot = _run_failing_flow(tmp_path, keep_worktree=True)

    assert snapshot["status"] == "failed"
    worktree = snapshot["candidateWorktree"]
    assert Path(str(worktree["path"])).exists()
    assert "autoCleanup" not in worktree


def test_auto_cleanup_skips_non_failed_terminal_states(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate-kept"
    candidate.mkdir()
    snapshot = {
        "runId": "swte-done",
        "status": "done",
        "keepWorktree": False,
        "projectRoot": str(tmp_path),
        "candidateWorktree": {"path": str(candidate)},
    }
    updated = service._auto_cleanup_failed_candidate(dict(snapshot))
    assert updated == snapshot
    assert candidate.exists()


def test_release_harness_claims_releases_only_matching_claims(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_coordination_call(root, *arguments):
        calls.append(tuple(str(item) for item in arguments))
        if arguments and arguments[0] == "status":
            return {
                "claims": [
                    {
                        "claim_id": "claim-match",
                        "branch": "codex/supervised-swte-x1",
                        "task": "Develop codex/supervised-swte-x1",
                    },
                    {
                        "claim_id": "claim-other",
                        "branch": "codex/unrelated",
                        "task": "Develop codex/unrelated",
                    },
                ]
            }
        return {"ok": True}

    monkeypatch.setattr(service, "coordination_call", fake_coordination_call)
    snapshot = {
        "runId": "swte-x1",
        "projectRoot": str(tmp_path),
        "candidateWorktree": {"path": str(tmp_path / "candidate")},
    }
    result = service._release_harness_claims(snapshot)

    assert result["status"] == "released"
    assert result["released"] == ["claim-match"]
    release_calls = [call for call in calls if call and call[0] == "release"]
    assert len(release_calls) == 1
    assert "claim-match" in release_calls[0]
    assert "claim-other" not in json.dumps([list(call) for call in calls])


def test_release_harness_claims_tolerates_coordination_outage(
    tmp_path: Path, monkeypatch
) -> None:
    def fake_coordination_call(root, *arguments):
        raise RuntimeError("coordination offline")

    monkeypatch.setattr(service, "coordination_call", fake_coordination_call)
    snapshot = {
        "runId": "swte-x2",
        "projectRoot": str(tmp_path),
        "candidateWorktree": {"path": str(tmp_path / "candidate")},
    }
    result = service._release_harness_claims(snapshot)
    assert result["status"] == "skipped"
    assert result["reason"] == "coordination_unavailable"
    assert result["released"] == []
