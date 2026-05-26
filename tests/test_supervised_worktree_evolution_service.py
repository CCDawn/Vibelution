import json
import subprocess
from pathlib import Path

import pytest

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
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.local")
    _run_git(repo, "config", "user.name", "Test User")


def _write_bundle(project_root: Path, name: str = "closed_loop_v1") -> None:
    bundle_path = project_root / "workspace" / "evaluation" / "bundles" / f"{name}.json"
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_name": name,
                "benchmark": "unit",
                "cases": [
                    {"case_id": "one", "prompt": "case one"},
                    {"case_id": "two", "prompt": "case two"},
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


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


def _retryable_provider_failure_evaluator(_: Path, bundle_name: str, role: str, __: dict) -> dict:
    assert role == "baseline"
    return {
        "role": role,
        "status": "failed",
        "score": 0.0,
        "successes": 0,
        "total": 1,
        "failures": 1,
        "bundleName": bundle_name,
        "summary": "baseline score 0.0",
        "cases": [
            {
                "caseId": "provider-down",
                "status": "failed",
                "reason": "LLM provider 传输异常，未生成可评估输出；请稍后重试",
                "llmFailure": {
                    "detected": True,
                    "category": "provider_transport_error",
                    "retryable": True,
                    "message": "server_error: upstream request failed",
                },
            }
        ],
    }


def _make_candidate_repo(tmp_path: Path, project_root: Path, *, changed_path: str = "agent.py") -> Path:
    candidate = tmp_path / f"candidate-{changed_path.replace('/', '-')}"
    _init_repo(candidate)
    for source in project_root.rglob("*"):
        if not source.is_file():
            continue
        try:
            rel = source.relative_to(project_root)
        except ValueError:
            continue
        if ".git" in rel.parts:
            continue
        target = candidate / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _run_git(candidate, "add", ".")
    _run_git(candidate, "commit", "-m", "base")
    target = candidate / changed_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(target.read_text(encoding="utf-8") + "\n# candidate edit\n", encoding="utf-8")
    return candidate


def test_supervised_worktree_flow_preserves_improved_candidate_and_records_merge_analysis(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def modifier(worktree_path: Path, _: str, __: dict) -> dict:
        _run_git(worktree_path, "status", "--porcelain")
        return {"status": "success", "summary": "candidate edited agent.py"}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "auto"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "done"
    assert snapshot["outcome"] == "preserved"
    assert snapshot["decision"]["scoreDelta"] == 50.0
    assert snapshot["decision"]["recommendedAction"] == "preserve"
    assert snapshot["mergeAnalysis"]["status"] == "ready"
    assert snapshot["mergeAnalysis"]["mergeAllowed"] is True
    assert snapshot["mergeAnalysis"]["changedFiles"][0]["path"] == "agent.py"


def test_self_origin_worktree_flow_carries_goal_and_requires_review(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    captured_prompt: dict[str, str] = {}

    def worktree_factory(root: Path, run_id: str) -> dict:
        candidate = _make_candidate_repo(tmp_path, root)
        return {
            "path": str(candidate),
            "baseHead": "base",
            "checkpointCommit": "base",
            "checkpointRef": "",
            "trackedDirty": False,
            "untrackedFiles": [],
        }

    def modifier(_: Path, prompt: str, __: dict) -> dict:
        captured_prompt["value"] = prompt
        return {"status": "success", "summary": "candidate edited from self goal"}

    snapshot = service.run_supervised_worktree_flow(
        {
            "sourceKind": "bundle",
            "bundleName": "closed_loop_v1",
            "mode": "manual",
            "selfEvolutionGoal": "修复自进化候选回流并补测试",
            "selfEvolutionRiskReason": "goal_write_marker",
            "requiresSupervisedReview": True,
        },
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_fake_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert "修复自进化候选回流并补测试" in captured_prompt["value"]
    assert snapshot["selfEvolutionOrigin"]["sourceTrack"] == "self_evolution"
    assert snapshot["reviewGate"]["required"] is True
    assert snapshot["reviewGate"]["status"] == "pending"
    assert snapshot["mergeAnalysis"]["mergeAllowed"] is False
    assert "supervised_review_pending" in snapshot["mergeAnalysis"]["blockers"]
    assert snapshot["actionStates"]["approveReview"]["enabled"] is True
    assert snapshot["actionStates"]["merge"]["enabled"] is False


def test_supervised_worktree_flow_stops_when_baseline_provider_transport_fails(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)
    calls = {"modifier": 0, "worktree": 0}

    def modifier(*_: object) -> dict:
        calls["modifier"] += 1
        return {"status": "success"}

    def worktree_factory(*_: object) -> dict:
        calls["worktree"] += 1
        return {"path": str(tmp_path / "candidate")}

    snapshot = service.run_supervised_worktree_flow(
        {"sourceKind": "bundle", "bundleName": "closed_loop_v1", "mode": "manual"},
        project_root=project_root,
        dependencies=service.WorktreeRunDependencies(
            evaluation_runner=_retryable_provider_failure_evaluator,
            candidate_modifier=modifier,
            worktree_factory=worktree_factory,
        ),
    )

    assert snapshot["status"] == "failed"
    assert snapshot["phase"] == "baseline_unavailable"
    assert snapshot["outcome"] == "baseline_unavailable"
    assert snapshot["errorType"] == "ProviderTransportError"
    assert "upstream request failed" in snapshot["error"]
    assert snapshot["candidateWorktree"] == {}
    assert snapshot["candidateModification"] == {}
    assert snapshot["candidate"] == {}
    assert calls == {"modifier": 0, "worktree": 0}


def test_merge_analysis_blocks_when_main_workspace_touched_same_file(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    (project_root / "agent.py").write_text("print('user edit')\n", encoding="utf-8")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-conflict",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(candidate), "preserved": True},
    }
    service._persist_snapshot(snapshot, active_run_id="")

    updated = service.execute_supervised_worktree_action("swte-conflict", "analyze_merge")

    assert updated["mergeAnalysis"]["status"] == "blocked"
    assert updated["mergeAnalysis"]["mergeAllowed"] is False
    assert "main_workspace_overlap" in updated["mergeAnalysis"]["blockers"]
    assert updated["mergeAnalysis"]["overlapFiles"] == ["agent.py"]


def test_force_merge_creates_rollback_manifest_and_rollback_restores_file(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    original = "print('base')\n"
    (project_root / "agent.py").write_text(original, encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    (project_root / "agent.py").write_text("print('user edit')\n", encoding="utf-8")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-merge",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(candidate), "preserved": True},
    }
    service._persist_snapshot(snapshot, active_run_id="")

    merged = service.execute_supervised_worktree_action("swte-merge", "merge", force=True)

    assert merged["merge"]["status"] == "merged"
    assert "# candidate edit" in (project_root / "agent.py").read_text(encoding="utf-8")
    manifest_path = Path(merged["rollback"]["manifestPath"])
    assert manifest_path.exists()

    rolled_back = service.execute_supervised_worktree_action("swte-merge", "rollback")

    assert rolled_back["rollback"]["status"] == "rolled_back"
    assert (project_root / "agent.py").read_text(encoding="utf-8") == "print('user edit')\n"


def test_self_origin_merge_requires_review_even_when_forced(tmp_path):
    project_root = tmp_path / "project"
    _init_repo(project_root)
    (project_root / "agent.py").write_text("print('base')\n", encoding="utf-8")
    _write_bundle(project_root)
    _run_git(project_root, "add", ".")
    _run_git(project_root, "commit", "-m", "init")
    candidate = _make_candidate_repo(tmp_path, project_root)
    snapshot = {
        "runId": "swte-self-review",
        "runKind": service.RUN_KIND,
        "status": "done",
        "projectRoot": str(project_root),
        "candidateWorktree": {"path": str(candidate), "preserved": True},
        "selfEvolutionOrigin": {
            "sourceTrack": "self_evolution",
            "goal": "修复核心代码",
            "riskReason": "goal_write_marker",
            "requiresSupervisedReview": True,
        },
        "reviewGate": {
            "required": True,
            "status": "pending",
            "reason": "must review",
            "approvedAt": "",
            "reviewerNote": "",
        },
    }
    service._persist_snapshot(snapshot, active_run_id="")

    blocked = service.execute_supervised_worktree_action("swte-self-review", "analyze_merge")

    assert blocked["mergeAnalysis"]["mergeAllowed"] is False
    assert "supervised_review_pending" in blocked["mergeAnalysis"]["blockers"]
    with pytest.raises(service.SupervisedWorktreeRunActionError, match="pending review"):
        service.execute_supervised_worktree_action("swte-self-review", "merge", force=True)

    approved = service.execute_supervised_worktree_action(
        "swte-self-review",
        "approve_review",
        reviewer_note="reviewed by supervised line",
    )
    merged = service.execute_supervised_worktree_action("swte-self-review", "merge")

    assert approved["reviewGate"]["status"] == "approved"
    assert approved["reviewGate"]["reviewerNote"] == "reviewed by supervised line"
    assert merged["merge"]["status"] == "merged"
    assert "# candidate edit" in (project_root / "agent.py").read_text(encoding="utf-8")


def test_real_llm_mode_requires_explicit_cost_confirmation(tmp_path):
    project_root = tmp_path / "project"
    _write_bundle(project_root)

    with pytest.raises(service.SupervisedWorktreeRunValidationError) as exc_info:
        service.run_supervised_worktree_flow(
            {
                "sourceKind": "bundle",
                "bundleName": "closed_loop_v1",
                "executionMode": "real",
                "confirmRealLlmCost": False,
            },
            project_root=project_root,
            dependencies=service.WorktreeRunDependencies(
                evaluation_runner=_fake_evaluator,
                candidate_modifier=lambda *_: {"status": "success"},
                worktree_factory=lambda *_: {"path": str(tmp_path / "candidate")},
            ),
        )

    assert "预计会发起" in str(exc_info.value)
    assert "tokens" in str(exc_info.value)


def test_candidate_worktree_receives_ignored_runtime_bundle(tmp_path):
    project_root = tmp_path / "project"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    _write_bundle(project_root, "ignored_bundle_v1")

    service._ensure_bundle_available_in_candidate(
        project_root,
        candidate_path=candidate,
        bundle_name="ignored_bundle_v1",
    )

    copied = candidate / "workspace" / "evaluation" / "bundles" / "ignored_bundle_v1.json"
    assert copied.exists()
    assert json.loads(copied.read_text(encoding="utf-8"))["bundle_name"] == "ignored_bundle_v1"


def test_force_cancel_active_supervised_worktree_run_for_shutdown_releases_snapshot(monkeypatch):
    scene_events: list[tuple[str, str, str, dict]] = []

    def record_scene_event(component, phase, event_code, **kwargs):
        scene_events.append((component, phase, event_code, kwargs))
        return {"accepted": True}

    monkeypatch.setattr(service, "record_runtime_scene_event", record_scene_event)
    snapshot = {
        "runId": "swte-shutdown-active",
        "runKind": service.RUN_KIND,
        "leases": service.RUN_LEASES,
        "status": "running",
        "phase": "candidate_modify",
        "runtimeStatus": "running",
        "outcome": "",
        "startedAt": "2026-05-22T10:00:00+00:00",
        "updatedAt": "2026-05-22T10:01:00+00:00",
        "finishedAt": "",
        "latestMessage": "候选 agent 正在反思并修改自身。",
        "decision": {},
        "mergeAnalysis": {},
    }
    service._persist_snapshot(snapshot, active_run_id="swte-shutdown-active")

    closed = service.force_cancel_active_supervised_worktree_runs_for_shutdown("closing")

    assert len(closed) == 1
    assert closed[0]["runId"] == "swte-shutdown-active"
    assert closed[0]["runKind"] == service.RUN_KIND
    assert closed[0]["status"] == "cancelled"
    assert closed[0]["phase"] == "shutdown"
    assert closed[0]["runtimeStatus"] == "cancelled"
    assert closed[0]["outcome"] == "shutdown_cancelled"
    assert closed[0]["latestMessage"] == "工作台关闭前已终止监督工作树进化运行。"
    assert closed[0]["runtimeManagerControl"] == {"reason": "shutdown", "message": "closing"}
    assert closed[0]["finishedAt"]
    assert closed[0]["stages"][-1]["phase"] == "shutdown"
    assert service.get_active_supervised_worktree_run() is None
    persisted = service.get_supervised_worktree_run("swte-shutdown-active")
    assert persisted is not None
    assert persisted["status"] == "cancelled"
    assert persisted["phase"] == "shutdown"
    assert persisted["runtimeManagerControl"]["reason"] == "shutdown"
    cancelled_event = next(item for item in scene_events if item[2] == "supervised_worktree_run.shutdown_cancelled")
    assert cancelled_event[1] == "shutdown"
    assert cancelled_event[3]["lifecycle"] is True
