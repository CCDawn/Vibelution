from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from copy import deepcopy

import pytest

from core.runtime_manager.work_run_store import WorkRunStore
from core.web.services.self_evolution_autonomous_loop_service import (
    AutonomousLoopConflictError,
    AutonomousLoopHooks,
    AutonomousLoopValidationError,
    SelfEvolutionAutonomousLoopService,
    _default_process_alive,
)


def _terminated_child_pid() -> int:
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **hidden,
    )
    process.terminate()
    process.wait(timeout=15)
    return process.pid


def test_default_process_alive_rejects_terminated_and_nonpositive_pids():
    """默认探活必须把已终止/非法 pid 判死，把活进程判活。"""
    assert _default_process_alive(0) is False
    assert _default_process_alive(-1) is False
    assert _default_process_alive(os.getpid()) is True
    assert _default_process_alive(_terminated_child_pid()) is False


def test_service_default_probe_keeps_a_live_run_owns_its_lock(tmp_path):
    """回归：无控制台 Windows 上 os.kill 探活会把活 run 的进程误判为死，
    清退仍在执行的自演化任务；默认探活改走共享 kernel32 探活后，
    持有 run 的活进程必须被判活。"""
    service = SelfEvolutionAutonomousLoopService(
        store=WorkRunStore(tmp_path),
        hooks=AutonomousLoopHooks(
            observe=lambda _context: {"summary": "s"},
            plan=lambda _context: {"summary": "p"},
            evolve=lambda _context: {"summary": "e"},
            integrate=lambda _context: {"summary": "i"},
            cleanup=lambda _context: {"status": "cleaned"},
        ),
        process_id=os.getpid(),
    )
    assert service._process_alive(os.getpid()) is True
    assert service._process_alive(0) is False
    assert service._process_alive(_terminated_child_pid()) is False


def _build_service(
    tmp_path,
    *,
    hook_overrides=None,
    process_id=111,
    process_alive=lambda _pid: False,
):
    calls: list[tuple[str, dict]] = []

    def observe(context):
        calls.append(("observe", deepcopy(context)))
        return {
            "summary": "发现 self-evolution 尚未形成用户审批后的自动收口。",
            "evidence": [{"kind": "source", "ref": "core/web/services/self_evolution_control_service.py"}],
            "conversationSessionId": "session-observer",
        }

    def plan(context):
        calls.append(("plan", deepcopy(context)))
        return {
            "summary": "新增独立闭环服务并复用 Git 集成底座。",
            "steps": [
                {"id": "state-machine", "title": "建立持久化状态机"},
                {"id": "integration", "title": "用户批准后自动合并并清理"},
            ],
            "targetFiles": [
                "core/example.py",
                "tests/test_example.py",
            ],
            "conversationSessionId": "session-observer",
        }

    def evolve(context):
        calls.append(("evolve", deepcopy(context)))
        return {
            "summary": "候选改动已在隔离工作树完成。",
            "branch": "codex/self-loop-candidate",
            "worktreePath": "C:/workspace/self-loop-candidate",
            "baseCommit": "a" * 40,
            "headCommit": "a" * 40,
            "changedFiles": [
                {"path": "core/example.py", "changeType": "modified"},
                {"path": "tests/test_example.py", "changeType": "added"},
            ],
            "verification": [{"command": "pytest tests/test_example.py", "outcome": "passed"}],
            "conversationSessionId": "session-executor",
            "variantId": "variant-001",
        }

    def integrate(context):
        calls.append(("integrate", deepcopy(context)))
        return {
            "status": "committed",
            "mechanism": "git_merge_ff",
            "baseCommit": context["candidate"]["baseCommit"],
            "commitSha": "d" * 40,
            "candidateVariantId": context["candidate"]["variantId"],
            "changedFiles": [
                item["path"] for item in context["candidate"]["changedFiles"]
            ],
            "rollbackManifestPath": "C:/workspace/manifests/self-loop-001.json",
            "committedAt": "2026-08-01T00:00:00+00:00",
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
        process_id=process_id,
        process_alive=process_alive,
    )
    return service, calls


def test_run_stops_at_user_approval_without_evaluation_or_git_integration(tmp_path):
    service, calls = _build_service(tmp_path)

    result = service.start(
        {
            "goal": "根据当前状态持续改进自进化流程",
            "maxIterations": 1,
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
    assert result["observation"]["conversationSessionId"] == "session-observer"
    assert result["plan"]["steps"][0]["id"] == "state-machine"
    assert result["plan"]["targetFiles"] == [
        "core/example.py",
        "tests/test_example.py",
    ]
    assert result["plan"]["conversationSessionId"] == "session-observer"
    evolve_context = calls[2][1]
    assert evolve_context["plan"]["targetFiles"] == [
        "core/example.py",
        "tests/test_example.py",
    ]
    assert result["candidate"]["branch"] == "codex/self-loop-candidate"
    assert result["candidate"]["changedFiles"][0] == {
        "path": "core/example.py",
        "changeType": "modified",
    }
    assert result["candidate"]["conversationSessionId"] == "session-executor"
    assert result["candidate"]["variantId"] == "variant-001"
    assert result["resultReport"]["summary"] == "候选改动已在隔离工作树完成。"
    assert "evaluation" not in result
    assert "judge" not in result
    assert "score" not in result
    assert service.load("self-loop-001") == result


def test_run_rejects_unimplemented_multi_candidate_iteration_contract(tmp_path):
    service, _calls = _build_service(tmp_path)

    with pytest.raises(
        AutonomousLoopValidationError,
        match="maxIterations must be 1",
    ):
        service.start({"goal": "建立自动闭环", "maxIterations": 2})


def test_queue_returns_before_agent_work_and_worker_resumes_persisted_run(tmp_path):
    service, calls = _build_service(tmp_path)

    queued = service.queue({"goal": "建立异步自动闭环"})

    assert calls == []
    assert queued["status"] == "queued"
    assert queued["phase"] == "queued"
    assert service.load("self-loop-001") == queued

    awaiting_review = service.run_until_review("self-loop-001")

    assert [name for name, _ in calls] == ["observe", "plan", "evolve"]
    assert awaiting_review["status"] == "awaiting_user_approval"
    assert awaiting_review["phase"] == "reporting"


def test_restart_persists_stop_and_late_worker_cannot_advance(tmp_path):
    evolve_started = threading.Event()
    release_evolve = threading.Event()

    def evolve(context):
        calls.append(("evolve", deepcopy(context)))
        evolve_started.set()
        assert release_evolve.wait(timeout=5)
        return {
            "summary": "候选工作树在中断前已经生成。",
            "branch": "codex/self-loop-candidate",
            "worktreePath": "C:/workspace/self-loop-candidate",
            "baseCommit": "a" * 40,
            "headCommit": "a" * 40,
            "changedFiles": [
                {"path": "core/example.py", "changeType": "modified"},
            ],
            "verification": [
                {"command": "pytest tests/test_example.py", "outcome": "passed"},
            ],
            "conversationSessionId": "session-executor",
            "variantId": "variant-001",
        }

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"evolve": evolve},
    )
    queued = service.queue({"goal": "重启期间停止旧 worker"})
    worker_results = []
    worker = threading.Thread(
        target=lambda: worker_results.append(
            service.run_until_review(str(queued["runId"]))
        ),
        daemon=True,
    )
    worker.start()

    assert evolve_started.wait(timeout=3)
    stopped = service.interrupt_active_for_restart("operator requested restart")

    assert len(stopped) == 1
    assert stopped[0]["status"] == "stopped"
    assert stopped[0]["phase"] == "evolving"
    assert stopped[0]["interruptedByRestart"] is True
    assert stopped[0]["stopReason"] == "operator requested restart"
    assert service.load_active() is None

    release_evolve.set()
    worker.join(timeout=3)

    assert not worker.is_alive()
    persisted = service.load("self-loop-001")
    assert worker_results == [persisted]
    assert persisted["status"] == "stopped"
    assert persisted["phase"] == "evolving"
    assert persisted["candidate"]["worktreePath"] == (
        "C:/workspace/self-loop-candidate"
    )
    assert persisted["resultReport"]["summary"] == (
        "候选工作树在中断前已经生成。"
    )
    assert persisted["interruptedByRestart"] is True
    assert [name for name, _ in calls] == ["observe", "plan", "evolve"]


def test_restart_waits_for_inflight_integration_and_preserves_receipt(tmp_path):
    integration_started = threading.Event()
    release_integration = threading.Event()

    def integrate(context):
        calls.append(("integrate", deepcopy(context)))
        integration_started.set()
        assert release_integration.wait(timeout=5)
        candidate = context["candidate"]
        return {
            "status": "committed",
            "mechanism": "git_merge_ff",
            "baseCommit": candidate["baseCommit"],
            "commitSha": "d" * 40,
            "candidateVariantId": candidate["variantId"],
            "changedFiles": [item["path"] for item in candidate["changedFiles"]],
            "rollbackManifestPath": "C:/workspace/manifests/self-loop-001.json",
            "committedAt": "2026-08-01T00:00:00+00:00",
        }

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"integrate": integrate},
    )
    service.start({"goal": "在重启边界保留 Git receipt"})
    approval_results = []
    approve_worker = threading.Thread(
        target=lambda: approval_results.append(
            service.approve(
                "self-loop-001",
                decision={"actorType": "user", "actorId": "local-user"},
            )
        ),
        daemon=True,
    )
    approve_worker.start()

    assert integration_started.wait(timeout=3)
    interrupt_results = []
    interrupt_errors = []

    def interrupt():
        try:
            interrupt_results.extend(
                service.interrupt_active_for_restart("operator requested restart")
            )
        except Exception as exc:  # pragma: no cover - failure is asserted below
            interrupt_errors.append(exc)

    interrupt_worker = threading.Thread(target=interrupt, daemon=True)
    interrupt_worker.start()
    deadline = time.monotonic() + 3
    while (
        "self-loop-001" not in service._restart_requests
        and interrupt_worker.is_alive()
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert "self-loop-001" in service._restart_requests

    release_integration.set()
    interrupt_worker.join(timeout=3)
    approve_worker.join(timeout=3)

    assert not interrupt_worker.is_alive()
    assert not approve_worker.is_alive()
    assert interrupt_errors == []
    assert len(interrupt_results) == 1
    stopped = interrupt_results[0]
    assert stopped["status"] == "stopped"
    assert stopped["phase"] == "cleanup_pending"
    assert stopped["integration"]["status"] == "committed"
    assert stopped["integration"]["commitSha"] == "d" * 40
    assert stopped["stopReason"] == "operator requested restart"
    assert approval_results == [stopped]
    assert [name for name, _ in calls] == [
        "observe",
        "plan",
        "evolve",
        "integrate",
    ]
    assert "cleanup" not in stopped
    assert service.load_active() is None

    with pytest.raises(AutonomousLoopConflictError, match="retiring"):
        service.retry_cleanup("self-loop-001")

    restarted_service, restarted_calls = _build_service(tmp_path)
    completed = restarted_service.retry_cleanup("self-loop-001")

    assert completed["status"] == "completed"
    assert completed["integration"]["commitSha"] == "d" * 40
    assert completed["cleanup"]["status"] == "cleaned"
    assert [name for name, _ in restarted_calls] == ["cleanup"]


def test_only_explicit_user_approval_can_merge_then_cleanup(tmp_path):
    owner_service, owner_calls = _build_service(tmp_path, process_id=111)
    owner_service.start({"goal": "建立自动闭环"})
    service, approval_calls = _build_service(tmp_path, process_id=222)

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

    calls = [*owner_calls, *approval_calls]
    assert [name for name, _ in calls] == [
        "observe",
        "plan",
        "evolve",
        "integrate",
        "cleanup",
    ]
    integration_context = calls[-2][1]
    assert integration_context["candidate"]["headCommit"] == "a" * 40
    assert integration_context["approval"]["actorType"] == "user"
    cleanup_context = calls[-1][1]
    assert cleanup_context["integration"]["commitSha"] == "d" * 40
    assert approved["status"] == "completed"
    assert approved["phase"] == "completed"
    assert approved["reviewGate"]["status"] == "approved"
    assert approved["integration"]["status"] == "committed"
    assert approved["integration"]["commitSha"] == "d" * 40
    assert approved["cleanup"]["worktreeRemoved"] is True
    assert approved["cleanup"]["localBranchDeleted"] is True
    assert approved["runtimeOwner"] == {"pid": 222}


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


def test_explicit_user_reapproval_retries_failed_integration_then_cleans(tmp_path):
    integration_attempts = 0

    def integrate(context):
        nonlocal integration_attempts
        integration_attempts += 1
        if integration_attempts == 1:
            raise RuntimeError("git author identity is missing")
        return {
            "status": "committed",
            "mechanism": "git_merge_ff",
            "baseCommit": context["candidate"]["baseCommit"],
            "commitSha": "d" * 40,
            "candidateVariantId": context["candidate"]["variantId"],
            "changedFiles": [
                item["path"] for item in context["candidate"]["changedFiles"]
            ],
            "rollbackManifestPath": "C:/workspace/manifests/self-loop-001.json",
            "committedAt": "2026-08-01T00:00:00+00:00",
        }

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"integrate": integrate},
    )
    service.start({"goal": "建立自动闭环"})

    failed = service.approve(
        "self-loop-001",
        decision={"actorType": "user", "actorId": "local-user"},
    )
    completed = service.approve(
        "self-loop-001",
        decision={
            "actorType": "user",
            "actorId": "local-user",
            "comment": "修复 Git 环境后重试集成",
        },
    )

    assert failed["status"] == "failed"
    assert failed["phase"] == "integration_failed"
    assert completed["status"] == "completed"
    assert completed["phase"] == "completed"
    assert completed["reviewGate"]["status"] == "approved"
    assert completed["integration"]["status"] == "committed"
    assert completed["cleanup"]["status"] == "cleaned"
    assert completed["integrationRetryCount"] == 1
    assert completed["lastIntegrationError"]["message"] == (
        "git author identity is missing"
    )
    assert "error" not in completed
    assert "finishedAt" in completed
    assert integration_attempts == 2
    assert [name for name, _ in calls] == [
        "observe",
        "plan",
        "evolve",
        "cleanup",
    ]


def test_restart_reports_real_completion_when_inflight_cleanup_succeeds(tmp_path):
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    def cleanup(context):
        calls.append(("cleanup", deepcopy(context)))
        cleanup_started.set()
        assert release_cleanup.wait(timeout=5)
        return {
            "status": "cleaned",
            "worktreeRemoved": True,
            "localBranchDeleted": True,
        }

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"cleanup": cleanup},
    )
    service.start({"goal": "原子清理收口后再重启"})
    approval_results = []
    approve_worker = threading.Thread(
        target=lambda: approval_results.append(
            service.approve(
                "self-loop-001",
                decision={"actorType": "user", "actorId": "local-user"},
            )
        ),
        daemon=True,
    )
    approve_worker.start()
    assert cleanup_started.wait(timeout=3)

    interrupt_results = []
    interrupt_errors = []

    def interrupt():
        try:
            interrupt_results.extend(
                service.interrupt_active_for_restart("operator requested restart")
            )
        except Exception as exc:  # pragma: no cover - failure is asserted below
            interrupt_errors.append(exc)

    interrupt_worker = threading.Thread(target=interrupt, daemon=True)
    interrupt_worker.start()
    deadline = time.monotonic() + 3
    while (
        "self-loop-001" not in service._restart_requests
        and interrupt_worker.is_alive()
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert "self-loop-001" in service._restart_requests

    release_cleanup.set()
    interrupt_worker.join(timeout=3)
    approve_worker.join(timeout=3)

    assert not interrupt_worker.is_alive()
    assert not approve_worker.is_alive()
    assert interrupt_errors == []
    assert len(interrupt_results) == 1
    assert interrupt_results == approval_results
    assert interrupt_results[0]["status"] == "completed"
    assert interrupt_results[0]["integration"]["status"] == "committed"
    assert interrupt_results[0]["cleanup"]["status"] == "cleaned"
    assert [name for name, _ in calls] == [
        "observe",
        "plan",
        "evolve",
        "integrate",
        "cleanup",
    ]


def test_restart_preserves_cleanup_debt_when_inflight_cleanup_fails(tmp_path):
    cleanup_started = threading.Event()
    release_cleanup = threading.Event()

    def cleanup(context):
        calls.append(("cleanup", deepcopy(context)))
        cleanup_started.set()
        assert release_cleanup.wait(timeout=5)
        raise RuntimeError("candidate branch is still checked out")

    service, calls = _build_service(
        tmp_path,
        hook_overrides={"cleanup": cleanup},
    )
    service.start({"goal": "重启期间保留未完成清理债务"})
    approval_results = []
    approve_worker = threading.Thread(
        target=lambda: approval_results.append(
            service.approve(
                "self-loop-001",
                decision={"actorType": "user", "actorId": "local-user"},
            )
        ),
        daemon=True,
    )
    approve_worker.start()

    assert cleanup_started.wait(timeout=3)
    interrupt_results = []
    interrupt_errors = []

    def interrupt():
        try:
            interrupt_results.extend(
                service.interrupt_active_for_restart("operator requested restart")
            )
        except Exception as exc:  # pragma: no cover - failure is asserted below
            interrupt_errors.append(exc)

    interrupt_worker = threading.Thread(target=interrupt, daemon=True)
    interrupt_worker.start()
    deadline = time.monotonic() + 3
    while (
        "self-loop-001" not in service._restart_requests
        and interrupt_worker.is_alive()
        and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert "self-loop-001" in service._restart_requests

    release_cleanup.set()
    interrupt_worker.join(timeout=3)
    approve_worker.join(timeout=3)

    assert not interrupt_worker.is_alive()
    assert not approve_worker.is_alive()
    assert interrupt_errors == []
    stopped = service.load("self-loop-001")
    assert interrupt_results == [stopped]
    assert approval_results == [stopped]
    assert stopped["status"] == "stopped"
    assert stopped["phase"] == "cleanup_failed"
    assert stopped["integration"]["status"] == "committed"
    assert stopped["integration"]["commitSha"] == "d" * 40
    assert stopped["error"]["message"] == "candidate branch is still checked out"
    assert "cleanup" not in stopped
    assert service.load_active() is None


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
    assert partial["integration"]["status"] == "committed"
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


def test_startup_reconciliation_releases_stale_queued_run(tmp_path):
    service, _calls = _build_service(tmp_path)
    service.queue({"goal": "建立自动闭环"})

    reconciled = service.reconcile_interrupted_on_startup()

    assert reconciled["status"] == "failed"
    assert reconciled["phase"] == "queued_interrupted"
    assert reconciled["error"]["type"] == "ProcessRestart"
    assert service.load_active() is None


def test_startup_reconciliation_preserves_run_owned_by_live_process(tmp_path):
    owner_service, _calls = _build_service(
        tmp_path,
        process_id=111,
        process_alive=lambda pid: pid == 111,
    )
    queued = owner_service.queue({"goal": "建立自动闭环"})
    evolving = owner_service._advance(
        queued,
        status="running",
        phase="evolving",
    )
    observer_service, _calls = _build_service(
        tmp_path,
        process_id=222,
        process_alive=lambda pid: pid == 111,
    )

    reconciled = observer_service.reconcile_interrupted_on_startup()

    assert queued["runtimeOwner"] == {"pid": 111}
    assert reconciled == evolving
    assert observer_service.load_active()["runId"] == "self-loop-001"


def test_startup_reconciliation_preserves_user_review_boundary(tmp_path):
    service, _calls = _build_service(tmp_path)
    pending = service.start({"goal": "建立自动闭环"})

    reconciled = service.reconcile_interrupted_on_startup()

    assert reconciled == pending
    assert service.load_active()["runId"] == "self-loop-001"


def test_operator_restart_preserves_user_review_boundary(tmp_path):
    service, _calls = _build_service(tmp_path)
    pending = service.start({"goal": "等待用户审批"})

    stopped = service.interrupt_active_for_restart("operator requested restart")

    assert stopped == []
    assert service.load_active() == pending
    assert service.load("self-loop-001")["status"] == "awaiting_user_approval"
    with pytest.raises(AutonomousLoopConflictError, match="retiring"):
        service.queue({"goal": "重启期间不能再排队"})
    with pytest.raises(AutonomousLoopConflictError, match="retiring"):
        service.approve(
            "self-loop-001",
            decision={"actorType": "user", "actorId": "local-user"},
        )
    assert service.load("self-loop-001") == pending


def test_operator_restart_does_not_stop_another_process_owner(tmp_path):
    owner_service, _calls = _build_service(
        tmp_path,
        process_id=111,
        process_alive=lambda pid: pid == 111,
    )
    queued = owner_service.queue({"goal": "由另一个后端进程运行"})
    observer_service, _calls = _build_service(
        tmp_path,
        process_id=222,
        process_alive=lambda pid: pid == 111,
    )

    stopped = observer_service.interrupt_active_for_restart(
        "operator requested restart"
    )

    assert stopped == []
    assert observer_service.load_active() == queued


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
