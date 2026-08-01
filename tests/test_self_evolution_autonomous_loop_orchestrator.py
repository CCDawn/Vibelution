from __future__ import annotations

import subprocess
from pathlib import Path

from core.web.services.self_evolution_autonomous_loop_orchestrator import (
    SelfEvolutionAutonomousLoopOrchestrator,
    build_runtime_dependencies,
)
from core.web.services.self_evolution_autonomous_loop_runtime import (
    build_autonomous_loop_hooks,
)


class _ImmediateExecutor:
    def __init__(self):
        self.submissions = []

    def submit(self, callback, *args):
        self.submissions.append((callback, args))
        callback(*args)


class _FakeService:
    def __init__(self):
        self.calls = []
        self.snapshot = {
            "runId": "self-loop-async",
            "status": "queued",
            "phase": "queued",
        }

    def queue(self, payload):
        self.calls.append(("queue", payload))
        return dict(self.snapshot)

    def run_until_review(self, run_id):
        self.calls.append(("run_until_review", run_id))
        return {
            **self.snapshot,
            "status": "awaiting_user_approval",
            "phase": "reporting",
        }

    def approve(self, run_id, *, decision):
        self.calls.append(("approve", run_id, decision))
        return {"runId": run_id, "status": "completed"}

    def reject(self, run_id, *, decision):
        self.calls.append(("reject", run_id, decision))
        return {"runId": run_id, "status": "rejected"}

    def retry_cleanup(self, run_id):
        self.calls.append(("retry_cleanup", run_id))
        return {"runId": run_id, "status": "completed"}

    def load(self, run_id):
        self.calls.append(("load", run_id))
        return {"runId": run_id, "status": "awaiting_user_approval"}

    def load_active(self):
        self.calls.append(("load_active",))
        return dict(self.snapshot)

    def load_latest(self):
        self.calls.append(("load_latest",))
        return dict(self.snapshot)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Self Evolution Test")
    _git(root, "config", "user.email", "self-evolution@example.invalid")
    (root / "feature.txt").write_text("before\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def test_orchestrator_returns_queued_snapshot_and_runs_worker_outside_request():
    service = _FakeService()
    executor = _ImmediateExecutor()
    orchestrator = SelfEvolutionAutonomousLoopOrchestrator(
        service=service,
        executor=executor,
    )

    queued = orchestrator.start({"goal": "建立自动闭环"})

    assert queued == {
        "runId": "self-loop-async",
        "status": "queued",
        "phase": "queued",
    }
    assert service.calls == [
        ("queue", {"goal": "建立自动闭环"}),
        ("run_until_review", "self-loop-async"),
    ]
    assert len(executor.submissions) == 1


def test_orchestrator_exposes_user_decision_and_recovery_actions():
    service = _FakeService()
    orchestrator = SelfEvolutionAutonomousLoopOrchestrator(
        service=service,
        executor=_ImmediateExecutor(),
    )

    approved = orchestrator.approve(
        "self-loop-async",
        decision={"actorType": "user", "actorId": "local-user"},
    )
    rejected = orchestrator.reject(
        "self-loop-async",
        decision={"actorType": "user", "actorId": "local-user"},
    )
    retried = orchestrator.retry_cleanup("self-loop-async")

    assert approved["status"] == "completed"
    assert rejected["status"] == "rejected"
    assert retried["status"] == "completed"
    assert orchestrator.get("self-loop-async")["runId"] == "self-loop-async"
    assert orchestrator.get_active()["phase"] == "queued"
    assert orchestrator.get_latest()["status"] == "queued"


def test_runtime_dependencies_create_integrate_and_cleanup_one_owned_candidate(
    tmp_path,
):
    root = _repo(tmp_path)
    dependencies = build_runtime_dependencies(
        project_root=root,
        manifest_root=tmp_path / "manifests",
        worktree_root=tmp_path / "candidates",
        bindings_loader=lambda: {
            "observer": {"agentId": "observer"},
            "executor": {"agentId": "executor"},
        },
        role_turn_runner=lambda **_kwargs: {
            "result": {"status": "completed", "summary": "done"},
            "carryover": {},
        },
    )
    hooks = build_autonomous_loop_hooks(dependencies)
    context = {
        "runId": "self-loop-integration",
        "request": {"goal": "修改 feature", "maxIterations": 1},
        "observation": {"summary": "需要修改", "evidence": []},
        "plan": {
            "summary": "修改 feature.txt",
            "steps": [{"id": "modify", "title": "修改"}],
        },
    }

    workspace = dependencies.create_candidate(context)
    candidate_root = Path(workspace["worktreePath"])
    (candidate_root / "feature.txt").write_text("after\n", encoding="utf-8")
    inspection = dependencies.inspect_candidate(
        {
            "runId": context["runId"],
            "snapshot": context,
            "candidateWorkspace": workspace,
            "agentResult": {},
        }
    )
    candidate = {
        **workspace,
        **inspection,
        "summary": "修改完成",
        "verification": [{"command": "test", "outcome": "passed"}],
    }
    approved_context = {
        **context,
        "candidate": candidate,
        "approval": {
            "decision": "approve",
            "actorType": "user",
            "actorId": "local-user",
        },
    }

    integration = hooks.integrate(approved_context)
    cleanup = hooks.cleanup(
        {
            **approved_context,
            "integration": integration,
        }
    )

    assert integration["status"] == "committed"
    assert _git(root, "rev-parse", "HEAD") == integration["commitSha"]
    assert _git(root, "status", "--short") == ""
    assert (root / "feature.txt").read_text(encoding="utf-8") == "after\n"
    assert cleanup["status"] == "cleaned"
    assert not candidate_root.exists()
    assert _git(root, "branch", "--list", workspace["branch"]) == ""
