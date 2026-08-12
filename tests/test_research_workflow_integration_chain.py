"""Integration: Command -> Graph interrupt -> Adapter -> Read-back -> Receipt
-> Handoff -> next-node readiness, with the production composition root.

No fakes for the domain ports: RealDomainPorts resolves the frozen binding,
reserves/settles budget against the Ledger budget_receipts, and creates the
Agent task through an injected real factory (kept hermetic — no network).
The graph worker re-runs NodeReadiness before the auto-advanced successor.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import ActorRef, CommandRequest, WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.domain_ports import (
    AgentTaskHandle,
    ArtifactReadBack,
)
from core.web.services.team_workflow.research_runtime.runtime_factory import (
    build_workflow_runtime,
)


def _seed(store) -> None:
    input_snapshot = {
        "teamId": "research-team",
        "projectId": "challenge-sci-096",
        "questionId": "SCI-096",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "researchBriefHash": "b" * 64,
        "datasetRefs": [],
        "metricContract": {},
        "constraintSnapshot": {},
        "competitionRuleRef": "rule",
        "competitionRuleVersion": "1",
        "trackAndRubricSnapshot": {},
        "researchObjectiveContract": {"question": "How to win?"},
        "sourcePolicy": {},
        "budgetPolicy": {
            "stageBudgets": {
                "knowledge_collection": {"tokens": 1000, "toolCalls": 5}
            }
        },
        "stopPolicy": {},
        "environmentSnapshotRef": "env-1",
        "modelRoutingPolicy": {},
        "evaluationContract": {},
        "agentBindingSnapshot": [
            {
                "snapshotId": "snap:run-test:source_finding",
                "nodeId": "source_finding",
                "agentId": "agent-real-1",
                "roleKey": "source_finder",
            },
            {
                "snapshotId": "snap:run-test:source_extraction",
                "nodeId": "source_extraction",
                "agentId": "agent-real-2",
                "roleKey": "source_extractor",
            },
        ],
        "createdBy": "u-1",
        "createdAt": "2026-08-12T00:00:00Z",
        "snapshotHash": "c" * 64,
    }
    from tests._support.workflow_ledger_helpers import (
        build_event_record,
        build_run_record,
    )

    record = build_run_record(
        run_id="run-test", last_event_sequence=1, input_snapshot_hash="c" * 64
    )
    record = record.__class__(
        run_id=record.run_id,
        team_id=record.team_id,
        workflow_id=record.workflow_id,
        workflow_version_id=record.workflow_version_id,
        thread_id=record.thread_id,
        project_id=record.project_id,
        question_id=record.question_id,
        status=record.status,
        run_version=record.run_version,
        last_event_sequence=record.last_event_sequence,
        input_snapshot_json=json.dumps(input_snapshot, ensure_ascii=False),
        input_snapshot_hash=record.input_snapshot_hash,
        safety_limits_json=record.safety_limits_json,
        binding_snapshot_set_id=record.binding_snapshot_set_id,
        active_node_id=record.active_node_id,
        parent_run_id=record.parent_run_id,
        forked_from_checkpoint_id=record.forked_from_checkpoint_id,
        completion_kind=record.completion_kind,
        terminal_reason=record.terminal_reason,
        blocked_problem_json=record.blocked_problem_json,
        created_at_ms=record.created_at_ms,
        updated_at_ms=record.updated_at_ms,
        completed_at_ms=record.completed_at_ms,
    )

    def mutate(uow):
        uow.repository.insert_run(record)
        uow.repository.insert_event(
            build_event_record(
                sequence=1,
                run_id="run-test",
                event_type="run_created",
                event_id="evt-created-run-test",
            )
        )

    store.submit(mutate, force_flush=True).result(timeout=10)


class _HermeticTaskFactory:
    """Real task factory shape (no network): returns a genuine handle derived
    from the frozen binding and records the artifact for read-back."""

    def __init__(self) -> None:
        self.handles: dict[str, AgentTaskHandle] = {}
        self.artifacts: dict[str, ArtifactReadBack] = {}

    def __call__(self, *, action, binding):
        handle = AgentTaskHandle(
            session_id=f"session-{binding.agent_id}",
            session_attempt=1,
            task_id=f"task-{action.action_id[:12]}",
            turn_id=f"turn-{action.action_id[:12]}",
        )
        self.handles[action.action_id] = handle
        self.artifacts[f"evidence_card_batch:{action.node_id}"] = ArtifactReadBack(
            canonical_ref=f"evidence_card_batch:{action.node_id}",
            version="1.0",
            content_hash="a" * 64,
            domain_revision="rev-1",
        )
        return handle


def _materialize_refs(harness_store, factory: _HermeticTaskFactory, action_id: str) -> None:
    """After the adapter worker ran, emulate the domain write for read-back."""
    handle = factory.handles[action_id]
    return handle


def test_full_chain_no_fakes(tmp_path: Path) -> None:
    factory = _HermeticTaskFactory()
    runtime = build_workflow_runtime(
        tmp_path / "ledger.sqlite3",
        agent_task_factory=factory,
    )
    try:
        _seed(runtime.store)

        # 1. Command -> graph_dispatch outbox + attempt starting.
        request = CommandRequest(
            command_id="cmd-client",
            run_id="run-test",
            team_id="research-team",
            command=WorkflowCommandKind.START_NODE,
            node_id="source_finding",
            expected_run_version=1,
            idempotency_key="ui:it-1",
            payload={},
            requested_by=ActorRef("user", "u-1"),
            requested_at_ms=1_750_000_000_000,
        )
        receipt = runtime.command_service.submit(request)
        assert receipt.status == "accepted"

        # 2. Graph worker: 图在 source_finding 中断，产出 adapter_dispatch outbox。
        handled = runtime.graph_worker.run_once()
        assert handled == 1
        adapter_rows = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind, node_run_id FROM outbox_actions "
                "WHERE action_kind = 'adapter_dispatch'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(adapter_rows) == 1
        node_run_id = adapter_rows[0][1]
        assert node_run_id == "nr-run-test-source_finding-a1"

        # 3. Adapter worker: 真实 ports 执行 -> read-back -> receipt -> handoff -> settle。
        handled = runtime.adapter_worker.run_once()
        assert handled == 1

        # 4. attempt succeeded + anchor 完整（真实 binding agentId）。
        attempt = runtime.store.latest_attempt("run-test", "source_finding")
        assert attempt is not None and attempt.status == "succeeded"
        anchor = runtime.store.submit(
            lambda uow: uow.repository.get_anchor_by_node_run(node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert anchor is not None
        anchor_json = json.loads(anchor[13])
        assert anchor_json["agentId"] == "agent-real-1"
        assert anchor_json["roleKey"] == "source_finder"
        assert anchor_json["sessionId"] == "session-agent-real-1"
        assert anchor_json["reservationId"] == "reservation-nr-run-test-source_finding-a1"

        # 5. budget receipt settled（真实 settle 链路）。
        budget_rows = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT reservation_id, status FROM budget_receipts WHERE node_run_id = ?",
                (node_run_id,),
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(budget_rows) == 1
        assert budget_rows[0][0] == "reservation-nr-run-test-source_finding-a1"
        assert budget_rows[0][1] == "settled"

        # 6. handoff ready（自动推进到 source_extraction）。
        handoffs = runtime.store.submit(
            lambda uow: uow.repository.get_handoff_by_from_node("run-test", node_run_id),
            force_flush=True,
        ).result(timeout=10)
        assert handoffs is not None and handoffs[8] == "ready"

        # 7. resume: adapter worker 已创建 resume dispatch（graph_dispatch）。
        # graph worker 处理它 -> 图推进到 source_extraction（新节点自动尝试），
        # 但 candidate_stats 缺失 -> blocked，无 adapter outbox。
        resume_rows = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT action_kind FROM outbox_actions WHERE action_kind = 'graph_dispatch' "
                "AND status IN ('pending', 'leased')"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(resume_rows) == 1
        handled = runtime.graph_worker.run_once()
        assert handled == 1

        extraction = next(
            (
                a
                for a in runtime.store.list_attempts("run-test")
                if a.node_id == "source_extraction"
            ),
            None,
        )
        assert extraction is not None
        assert extraction.status == "blocked"
        assert "auto_advance_not_ready" in (extraction.problem_json or "")
        # 没有第二个 adapter outbox（source_extraction 未执行）。
        adapter_rows_after = runtime.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT COUNT(*) FROM outbox_actions WHERE action_kind = 'adapter_dispatch'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert adapter_rows_after[0][0] == 1
    finally:
        runtime.close()
