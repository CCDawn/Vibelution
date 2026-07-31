from __future__ import annotations

import json
from copy import deepcopy

import pytest

from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services.self_evolution_autonomous_loop_service import (
    AutonomousLoopConflictError,
    AutonomousLoopHooks,
    AutonomousLoopValidationError,
    SelfEvolutionAutonomousLoopService,
)


def _build_service(tmp_path, *, hook_overrides=None):
    calls: list[tuple[str, dict]] = []

    def observe(context):
        calls.append(("observe", deepcopy(context)))
        return {
            "summary": "发现 self-evolution 尚未形成用户审批后的自动收口。",
            "evidence": [{"kind": "source", "ref": "core/web/services/self_evolution_control_service.py"}],
        }

    def plan(context):
        calls.append(("plan", deepcopy(context)))
        return {
            "summary": "新增独立闭环服务并复用 Git 集成底座。",
            "steps": [
                {"id": "state-machine", "title": "建立持久化状态机"},
                {"id": "integration", "title": "用户批准后自动合并并清理"},
            ],
        }

    def evolve(context):
        calls.append(("evolve", deepcopy(context)))
        return {
            "summary": "候选改动已在隔离工作树完成。",
            "branch": "codex/self-loop-candidate",
            "worktreePath": "C:/workspace/self-loop-candidate",
            "baseCommit": "a" * 40,
            "headCommit": "b" * 40,
            "changedFiles": ["core/example.py", "tests/test_example.py"],
            "verification": [{"command": "pytest tests/test_example.py", "outcome": "passed"}],
        }

    def integrate(context):
        calls.append(("integrate", deepcopy(context)))
        return {
            "status": "merged",
            "targetBranch": "main",
            "previousHead": "c" * 40,
            "mergedHead": "d" * 40,
            "candidateHead": context["candidate"]["headCommit"],
        }

    def cleanup(context):
        calls.append(("cleanup", deepcopy(context)))
        return {
            "status": "cleaned",
            "worktreeRemoved": True,
            "localBranchDeleted": True,
        }

    hook_values = {
        "observe": observe,
        "plan": plan,
        "evolve": evolve,
        "integrate": integrate,
        "cleanup": cleanup,
    }
    hook_values.update(hook_overrides or {})
    service = SelfEvolutionAutonomousLoopService(
        store=WorkRunStore(root=tmp_path / "work-runs"),
        hooks=AutonomousLoopHooks(**hook_values),
        run_id_factory=lambda: "self-loop-001",
        now=lambda: "2026-08-01T00:00:00+00:00",
    )
    return service, calls


def test_run_stops_at_user_approval_without_evaluation_or_git_integration(tmp_path):
    service, calls = _build_service(tmp_path)

    result = service.start(
        {
            "goal": "根据当前状态持续改进自进化流程",
            "maxIterations": 4,
        }
    )

    assert [name for name, _ in calls] == ["observe", "plan", "evolve"]
    assert result["status"] == "awaiting_user_approval"
    assert result["phase"] == "reporting"
    assert result["reviewGate"] == {
        "status": "pending",
        "requiredActorType": "user",
    }
    assert result["observation"]["summary"].startswith("发现")
    assert result["plan"]["steps"][0]["id"] == "state-machine"
    assert result["candidate"]["branch"] == "codex/self-loop-candidate"
    assert result["resultReport"]["summary"] == "候选改动已在隔离工作树完成。"
    assert "evaluation" not in result
    assert "judge" not in result
    assert "score" not in result
    assert service.load("self-loop-001") == result


def test_only_explicit_user_approval_can_merge_then_cleanup(tmp_path):
    service, calls = _build_service(tmp_path)
    service.start({"goal": "建立自动闭环"})

    with pytest.raises(
        AutonomousLoopValidationError,
        match="user approval",
    ):
        service.approve(
            "self-loop-001",
            decision={"actorType": "agent", "actorId": "self-evolution-agent"},
        )

    approved = service.approve(
        "self-loop-001",
        decision={
            "actorType": "user",
            "actorId": "local-user",
            "comment": "审查通过",
        },
    )

    assert [name for name, _ in calls] == [
        "observe",
        "plan",
        "evolve",
        "integrate",
        "cleanup",
    ]
    integration_context = calls[-2][1]
    assert integration_context["candidate"]["headCommit"] == "b" * 40
    assert integration_context["approval"]["actorType"] == "user"
    cleanup_context = calls[-1][1]
    assert cleanup_context["integration"]["mergedHead"] == "d" * 40
    assert approved["status"] == "completed"
    assert approved["phase"] == "completed"
    assert approved["reviewGate"]["status"] == "approved"
    assert approved["integration"]["targetBranch"] == "main"
    assert approved["cleanup"]["worktreeRemoved"] is True
    assert approved["cleanup"]["localBranchDeleted"] is True


def test_integration_failure_does_not_cleanup_or_report_completion(tmp_path):
    def fail_integration(_context):
        raise RuntimeError("target main changed")

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"integrate": fail_integration},
    )
    service.start({"goal": "建立自动闭环"})

    failed = service.approve(
        "self-loop-001",
        decision={"actorType": "user", "actorId": "local-user"},
    )

    assert [name for name, _ in calls] == ["observe", "plan", "evolve"]
    assert failed["status"] == "failed"
    assert failed["phase"] == "integration_failed"
    assert failed["reviewGate"]["status"] == "approved"
    assert failed["error"]["type"] == "RuntimeError"
    assert failed["error"]["message"] == "target main changed"
    assert "cleanup" not in failed
    assert failed["candidate"]["branch"] == "codex/self-loop-candidate"


def test_cleanup_failure_preserves_merged_fact_and_can_be_retried(tmp_path):
    cleanup_attempts = 0

    def cleanup(context):
        nonlocal cleanup_attempts
        cleanup_attempts += 1
        if cleanup_attempts == 1:
            raise RuntimeError("branch is still checked out")
        return {
            "status": "cleaned",
            "worktreeRemoved": True,
            "localBranchDeleted": True,
        }

    service, _calls = _build_service(
        tmp_path,
        hook_overrides={"cleanup": cleanup},
    )
    service.start({"goal": "建立自动闭环"})

    partial = service.approve(
        "self-loop-001",
        decision={"actorType": "user", "actorId": "local-user"},
    )

    assert partial["status"] == "partial"
    assert partial["phase"] == "cleanup_failed"
    assert partial["integration"]["status"] == "merged"
    assert partial["error"]["message"] == "branch is still checked out"

    completed = service.retry_cleanup("self-loop-001")

    assert completed["status"] == "completed"
    assert completed["phase"] == "completed"
    assert completed["cleanup"]["worktreeRemoved"] is True
    assert completed["cleanup"]["localBranchDeleted"] is True
    assert "error" not in completed


def test_rejection_retains_candidate_and_never_integrates_or_cleans(tmp_path):
    service, calls = _build_service(tmp_path)
    service.start({"goal": "建立自动闭环"})

    rejected = service.reject(
        "self-loop-001",
        decision={
            "actorType": "user",
            "actorId": "local-user",
            "comment": "需要继续修改",
        },
    )

    assert [name for name, _ in calls] == ["observe", "plan", "evolve"]
    assert rejected["status"] == "rejected"
    assert rejected["phase"] == "rejected"
    assert rejected["reviewGate"]["status"] == "rejected"
    assert rejected["candidate"]["branch"] == "codex/self-loop-candidate"
    assert "integration" not in rejected
    assert "cleanup" not in rejected


def test_second_active_run_is_rejected_until_first_reaches_review_boundary(tmp_path):
    service, _calls = _build_service(tmp_path)
    service.start({"goal": "建立自动闭环"})

    with pytest.raises(
        AutonomousLoopConflictError,
        match="active self-evolution autonomous loop",
    ):
        service.start({"goal": "并发启动第二轮"})


def test_persisted_evidence_is_bounded_and_redacts_common_credentials(tmp_path):
    def observe(_context):
        return {
            "summary": "观察完成",
            "evidence": [
                {
                    "authorization": "Bearer top-secret-token",
                    "detail": "api_key=sk-private-value",
                    "output": "x" * 20_000,
                }
            ],
        }

    service, _calls = _build_service(
        tmp_path,
        hook_overrides={"observe": observe},
    )

    result = service.start({"goal": "建立自动闭环"})
    serialized = json.dumps(result, ensure_ascii=False)

    assert "top-secret-token" not in serialized
    assert "sk-private-value" not in serialized
    assert "[REDACTED]" in serialized
    assert len(result["observation"]["evidence"][0]["output"]) < 9_000


def test_persisted_hook_error_redacts_credential_text(tmp_path):
    def fail_integration(_context):
        raise RuntimeError("request failed: token=top-secret-token")

    service, _calls = _build_service(
        tmp_path,
        hook_overrides={"integrate": fail_integration},
    )
    service.start({"goal": "建立自动闭环"})

    failed = service.approve(
        "self-loop-001",
        decision={"actorType": "user", "actorId": "local-user"},
    )

    assert failed["error"]["message"] == "request failed: token=[REDACTED]"
