"""P1-6 RED: fork_revision command + server-side operator authorization.

fork_revision creates a child run (parent_run_id lineage) with its own
graph_dispatch in one transaction; revise_protocol is no longer flattened
into a failed receipt. High-impact commands require a verifiable operator
identity; a forged requested_by is rejected with CommandForbiddenError.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.web.services.team_workflow import challenge_question_runs
from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
    WorkflowCommandError,
)
from tests._support.command_helpers import CommandHarness


def test_fork_revision_creates_child_run_with_lineage_and_dispatch(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        request = harness.request(
            command=WorkflowCommandKind.FORK_REVISION,
            node_id="hypothesis_design",
            expected_run_version=2,
            idempotency_key="ui:fork-1",
            payload={
                "fromNodeId": "hypothesis_design",
                "reason": "revise protocol after failed evaluation",
                "checkpointId": "ckpt-parent-1",
            },
        )
        receipt = harness.service.submit(request)
        assert receipt.status == "accepted"
        assert receipt.accepted_run_version == 3

        child = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id, parent_run_id, status, active_node_id, "
                "workflow_version_id, thread_id, forked_from_checkpoint_id "
                "FROM workflow_runs "
                "WHERE parent_run_id = 'run-test'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(child) == 1
        child_run_id = child[0][0]
        assert child[0][1] == "run-test"
        assert child[0][2] == "created"
        assert child[0][3] == "hypothesis_design"
        assert child[0][5] == child_run_id
        assert child[0][6] == "ckpt-parent-1"

        # Durable checkpoint_fork outbox; graph_dispatch only after fork worker succeeds.
        outbox = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind, run_id, status FROM outbox_actions "
                "WHERE run_id = ?",
                (child_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(outbox) == 1
        assert outbox[0][0] == "checkpoint_fork"
        assert outbox[0][1] == child_run_id
        assert outbox[0][2] == "pending"
        graph_dispatch = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_id FROM outbox_actions "
                "WHERE run_id = ? AND action_kind = 'graph_dispatch'",
                (child_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert graph_dispatch == []

        # 父 run 事件记录 revision_forked。
        events = harness.store.list_events("run-test")
        assert any(e.event_type == "revision_forked" for e in events)
    finally:
        harness.close()


def test_fork_revision_requires_from_node_and_reason(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))
        with pytest.raises(WorkflowCommandError):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    expected_run_version=2,
                    idempotency_key="ui:fork-2",
                    payload={"fromNodeId": "hypothesis_design"},
                )
            )
        with pytest.raises(WorkflowCommandError):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    expected_run_version=2,
                    idempotency_key="ui:fork-3",
                    payload={"fromNodeId": "", "reason": "x"},
                )
            )
    finally:
        harness.close()


def test_succeeded_run_rejects_forged_post_approval_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="succeeded")
        monkeypatch.setattr(
            challenge_question_runs,
            "get_challenge_question_run_detail",
            lambda *_args, **_kwargs: {
                "record": {
                    "recordId": "SCI-096:other-run",
                    "questionId": "SCI-096",
                    "runId": "other-run",
                    "status": "needs_revision",
                    "humanGates": {
                        "decisions": {"H4_external_output": "revision_requested"}
                    },
                }
            },
        )

        with pytest.raises(WorkflowCommandError, match="未授权"):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.FORK_REVISION,
                    expected_run_version=1,
                    idempotency_key="ui:forged-post-approval",
                    payload={
                        "fromNodeId": "hypothesis_design",
                        "reason": "forged terminal fork",
                        "checkpointId": "ckpt-parent-1",
                        "postApprovalRevision": True,
                        "outputRecordId": "SCI-096:run-test",
                    },
                )
            )
    finally:
        harness.close()


def test_succeeded_run_accepts_durable_revision_requested_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(status="succeeded")
        monkeypatch.setattr(
            challenge_question_runs,
            "get_challenge_question_run_detail",
            lambda *_args, **_kwargs: {
                "record": {
                    "recordId": "SCI-096:run-test",
                    "questionId": "SCI-096",
                    "runId": "run-test",
                    "status": "needs_revision",
                    "humanGates": {
                        "decisions": {"H4_external_output": "revision_requested"}
                    },
                }
            },
        )

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.FORK_REVISION,
                expected_run_version=1,
                idempotency_key="ui:authorized-post-approval",
                payload={
                    "fromNodeId": "hypothesis_design",
                    "reason": "revise after H1-H4 review",
                    "checkpointId": "ckpt-parent-1",
                    "postApprovalRevision": True,
                    "outputRecordId": "SCI-096:run-test",
                },
            )
        )

        assert receipt.status == "accepted"
        child_rows = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT parent_run_id FROM workflow_runs WHERE parent_run_id = ?",
                ("run-test",),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert child_rows == [("run-test",)]
    finally:
        harness.close()


def test_high_impact_command_requires_operator_identity(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        # 伪造 requested_by：system 身份执行取消 —— 拒绝。
        request = harness.request(
            command=WorkflowCommandKind.CANCEL_RUN,
            expected_run_version=2,
            idempotency_key="ui:forged-cancel",
            payload={"reason": "x"},
        )
        forged = CommandRequest(
            command_id=request.command_id,
            run_id=request.run_id,
            team_id=request.team_id,
            command=request.command,
            node_id=request.node_id,
            expected_run_version=request.expected_run_version,
            idempotency_key=request.idempotency_key,
            payload=request.payload,
            requested_by=ActorRef("system", "agent-worker"),
            requested_at_ms=request.requested_at_ms,
        )
        with pytest.raises(CommandForbiddenError):
            harness.command_service.submit(forged)

        # 空 operator id —— 拒绝。
        empty = CommandRequest(
            command_id=request.command_id,
            run_id=request.run_id,
            team_id=request.team_id,
            command=request.command,
            node_id=request.node_id,
            expected_run_version=request.expected_run_version,
            idempotency_key=request.idempotency_key,
            payload=request.payload,
            requested_by=ActorRef("operator", ""),
            requested_at_ms=request.requested_at_ms,
        )
        with pytest.raises(CommandForbiddenError):
            harness.command_service.submit(empty)

        # 合法 operator —— 通过。
        ok = CommandRequest(
            command_id=request.command_id,
            run_id=request.run_id,
            team_id=request.team_id,
            command=request.command,
            node_id=request.node_id,
            expected_run_version=2,
            idempotency_key="ui:ok-cancel",
            payload=request.payload,
            requested_by=ActorRef("operator", "operator-1"),
            requested_at_ms=request.requested_at_ms,
        )
        from core.web.services.team_workflow.research_runtime.operator_authorization import (
            server_operator_scope,
        )

        with server_operator_scope("operator-1", roles=("operator",)):
            receipt = harness.command_service.submit(ok)
        assert receipt.status == "accepted"
        run = harness.store.get_run("run-test")
        assert run is not None and run.status == "cancelled"
    finally:
        harness.close()


def test_start_node_allows_system_actor(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        request = harness.request(idempotency_key="ui:key-1")
        receipt = harness.service.submit(request)
        assert receipt.status == "accepted"
    finally:
        harness.close()


def test_human_revise_decision_forks_child_run(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        harness.service.submit(harness.request(idempotency_key="ui:key-1"))

        # 准备一个 pending human task（模拟 knowledge_handoff 人工门）。
        attempt = harness.store.latest_attempt("run-test", "source_finding")

        def seed_human_task(uow):
            from tests._support.workflow_ledger_helpers import FIXED_NOW_MS as NOW

            uow.repository.insert_human_task(
                task_id="ht-revise",
                run_id="run-test",
                node_run_id=attempt.node_run_id,
                handoff_id=None,
                task_kind="gate:knowledge_handoff",
                prompt_json='{"nodeId": "knowledge_handoff"}',
                created_at_ms=NOW,
            )

        harness.store.submit(seed_human_task, force_flush=True).result(timeout=10)

        # operator revise 决策：fork 新 Run，而不是 failed receipt。
        request = CommandRequest(
            command_id="cmd-client",
            run_id="run-test",
            team_id="research-team",
            command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
            node_id="knowledge_handoff",
            expected_run_version=2,
            idempotency_key="ui:revise-1",
            payload={
                "taskId": "ht-revise",
                "decision": "revise",
                "fromNodeId": "hypothesis_design",
                "reason": "revise design after handoff review",
                "checkpointId": "ckpt-revise-1",
            },
            requested_by=ActorRef("operator", "operator-1"),
            requested_at_ms=1_750_000_000_000,
        )
        receipt = harness.service.submit(request)
        assert receipt.status == "accepted"

        child = harness.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id, parent_run_id FROM workflow_runs "
                "WHERE parent_run_id = 'run-test'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(child) == 1
        assert child[0][1] == "run-test"

        # 人工 task 被标记 revised。
        row = harness.store.submit(
            lambda uow: uow.repository.get_human_task("ht-revise"),
            force_flush=True,
        ).result(timeout=10)
        assert row is not None and row[6] == "revised"
    finally:
        harness.close()
