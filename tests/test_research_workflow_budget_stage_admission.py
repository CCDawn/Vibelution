"""Stage-boundary budget admission guardrail (SCI-091 challenge guardrail).

Covers the three contracts of the precheck mounted at the graph-dispatch
successor boundary:

1. an underfunded stage is blocked BEFORE the attempt starts, with a
   structured ``budget_precheck_blocked`` event and a recoverable blocked run;
2. ``extend_budget`` (budget_settled) alone makes the blocked run retryable
   without manual data repair;
3. a normally funded run advances exactly as before (zero behavioral diff),
   including the no-history conservative-default path.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.web.services.team_workflow.research_runtime.budget_stage_admission import (
    BUDGET_PRECHECK_INSUFFICIENT_CODE,
    DEFAULT_CONSERVATIVE_REFERENCE_TOKENS,
    evaluate_stage_budget_admission,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
)

STAGE = "knowledge_collection"


def _worker(harness: GraphHarness) -> GraphDispatchWorker:
    return GraphDispatchWorker(
        store=harness.commands.store,
        coordinator=ChallengeCupGraphCoordinator(harness.tmp_path / "checkpoints.sqlite"),
        owner_id="graph-worker-budget-precheck",
        now_provider=lambda: FIXED_NOW_MS + 1000,
    )


def _update_input_snapshot(harness: GraphHarness, run_id: str, snapshot: dict) -> None:
    def mutate(uow):
        uow.repository.execute(
            "UPDATE workflow_runs SET input_snapshot_json = ? WHERE run_id = ?",
            (json.dumps(snapshot), run_id),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _seed_history(
    harness: GraphHarness,
    *,
    run_id: str = "run-history",
    node_id: str = "source_finding",
    tokens: int,
) -> None:
    """A settled, usage-observed budget receipt in a sibling run (same question)."""

    harness.commands.seed_run(run_id=run_id)
    node_run_id = f"nr-{run_id}-{node_id}-a1"
    command_id = f"cmd-{run_id}-{node_id}"

    def mutate(uow):
        from tests._support.workflow_ledger_helpers import build_command_record

        uow.repository.insert_command(
            build_command_record(
                command_id=command_id,
                run_id=run_id,
                node_id=node_id,
                idempotency_key=f"key:{command_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=node_run_id,
                run_id=run_id,
                node_id=node_id,
                attempt=1,
                status="succeeded",
                command_id=command_id,
            )
        )
        uow.repository.insert_budget_receipt(
            receipt_id=f"br-{run_id}-{node_id}",
            run_id=run_id,
            node_run_id=node_run_id,
            reservation_id=f"reservation-{node_run_id}",
            stage_id=STAGE,
            policy_hash="",
            reserved_json=json.dumps({"reserved": {"estimatedTokens": tokens}}),
            created_at_ms=FIXED_NOW_MS,
        )
        uow.repository.execute(
            "UPDATE budget_receipts SET status = 'settled', settled_json = ? "
            "WHERE receipt_id = ?",
            (json.dumps({"usage": {"tokens": tokens}}), f"br-{run_id}-{node_id}"),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _consume_run_budget(
    harness: GraphHarness,
    *,
    run_id: str,
    node_run_id: str,
    node_id: str,
    tokens: int,
) -> None:
    """Settle real usage into the current run's stage so remaining shrinks."""

    def mutate(uow):
        uow.repository.insert_budget_receipt(
            receipt_id=f"br-{run_id}-{node_id}-used",
            run_id=run_id,
            node_run_id=node_run_id,
            reservation_id=f"reservation-{node_run_id}",
            stage_id=STAGE,
            policy_hash="",
            reserved_json=json.dumps({"reserved": {"estimatedTokens": tokens}}),
            created_at_ms=FIXED_NOW_MS,
        )
        uow.repository.execute(
            "UPDATE budget_receipts SET status = 'settled', settled_json = ? "
            "WHERE receipt_id = ?",
            (json.dumps({"usage": {"tokens": tokens}}), f"br-{run_id}-{node_id}-used"),
        )

    harness.commands.store.submit(mutate, force_flush=True).result(timeout=10)


def _adapter_pending_node_ids(harness: GraphHarness, run_id: str = "run-test") -> set[str]:
    records = harness.commands.store.list_pending_outbox(run_id)
    return {
        str(json.loads(record.payload_json).get("nodeId"))
        for record in records
        if record.action_kind == "adapter_dispatch"
    }


def _run_id(harness: GraphHarness, run_id: str = "run-test") -> int:
    record = harness.commands.store.get_run(run_id)
    assert record is not None
    return record.run_version


def _seed_underfunded_stage(harness: GraphHarness) -> None:
    """400K stage budget, 300K already consumed, 300K historical typical node."""

    harness.seed()
    harness.start_thread_to("source_finding")
    _update_input_snapshot(
        harness,
        "run-test",
        {"budgetPolicy": {"stageBudgets": {STAGE: {"tokens": 400_000}}}},
    )
    _seed_history(harness, tokens=300_000)
    _consume_run_budget(
        harness,
        run_id="run-test",
        node_run_id="nr-run-test-problem_understanding-a1",
        node_id="problem_understanding",
        tokens=300_000,
    )


def test_insufficient_stage_blocks_successor_with_structured_event(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_underfunded_stage(harness)
        harness.worker = _worker(harness)
        pending = harness.latest_adapter_pending()
        assert pending is not None
        harness.consume_adapter(pending.action_id)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=json.loads(pending.payload_json)["actionId"],
        )
        handled = harness.worker.run_once()
        assert handled == 1

        attempts = harness.commands.store.list_attempts("run-test")
        extraction = next(
            (a for a in attempts if a.node_id == "source_extraction"), None
        )
        assert extraction is not None
        assert extraction.status == "blocked"
        problem = json.loads(extraction.problem_json or "{}")
        assert problem["code"] == BUDGET_PRECHECK_INSUFFICIENT_CODE
        assert problem["stageId"] == STAGE
        assert problem["remainingTokens"] == 100_000
        assert problem["referenceTokens"] == 300_000
        assert problem["referenceBasis"] == "historical_median_stage"
        assert problem["suggestedExtensionTokens"] == 200_000
        assert problem["recovery"]["command"] == "extend_budget"
        assert problem["recovery"]["then"] == "retry_node"

        events = harness.commands.store.list_events("run-test")
        blocked_events = [
            e for e in events if e.event_type == "budget_precheck_blocked"
        ]
        assert len(blocked_events) == 1
        payload = json.loads(blocked_events[0].payload_json)
        assert payload["code"] == BUDGET_PRECHECK_INSUFFICIENT_CODE
        assert payload["nodeId"] == "source_extraction"
        assert payload["stageId"] == STAGE
        assert payload["remainingTokens"] == 100_000
        assert payload["referenceTokens"] == 300_000
        assert payload["suggestedExtensionTokens"] == 200_000
        assert payload["recovery"]["command"] == "extend_budget"

        run = harness.commands.store.get_run("run-test")
        assert run is not None
        assert run.status == "blocked"
        assert json.loads(run.blocked_problem_json or "{}")["code"] == (
            BUDGET_PRECHECK_INSUFFICIENT_CODE
        )
        # 后继不建 adapter outbox：被拦的 stage 不启动。
        assert "source_extraction" not in _adapter_pending_node_ids(harness)
    finally:
        harness.close()


def test_extend_budget_then_retry_recovers_without_data_repair(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        _seed_underfunded_stage(harness)
        harness.worker = _worker(harness)
        pending = harness.latest_adapter_pending()
        assert pending is not None
        harness.consume_adapter(pending.action_id)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=json.loads(pending.payload_json)["actionId"],
        )
        harness.worker.run_once()
        run = harness.commands.store.get_run("run-test")
        assert run is not None and run.status == "blocked"

        # Operator recovery: extend_budget alone (budget_settled), no data fix.
        receipt = harness.commands.service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.EXTEND_BUDGET,
                node_id=None,
                payload={"limits": {"stageTokens": {STAGE: 2_000_000}}},
                expected_run_version=_run_id(harness),
                idempotency_key="ui:extend-budget-1",
            )
        )
        assert receipt.status == "accepted"
        events = harness.commands.store.list_events("run-test")
        assert any(e.event_type == "budget_settled" for e in events)

        decision = evaluate_stage_budget_admission(
            harness.commands.store,
            run_id="run-test",
            node_id="source_extraction",
            actor_kind="agent",
        )
        assert decision.admitted is True
        assert decision.remaining_tokens == 1_700_000

        # Existing retry command path now admits the node again.
        retry_receipt = harness.commands.service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id="source_extraction",
                payload={},
                expected_run_version=_run_id(harness),
                idempotency_key="ui:retry-1",
            )
        )
        assert retry_receipt.status == "accepted"
        attempts = harness.commands.store.list_attempts("run-test")
        extraction_attempts = sorted(
            (a for a in attempts if a.node_id == "source_extraction"),
            key=lambda a: a.attempt,
        )
        assert [a.attempt for a in extraction_attempts] == [1, 2]
        # 既有 retry 契约：旧 attempt 置 stale，新 attempt 接管。
        assert extraction_attempts[0].status == "stale"
        assert extraction_attempts[1].status in {"starting", "dispatching"}
        retried_run = harness.commands.store.get_run("run-test")
        assert retried_run is not None
        assert retried_run.status in {"running", "queued"}
    finally:
        harness.close()


def test_sufficient_budget_keeps_advancement_unchanged(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        # 默认契约（2M stage 上限、无历史、无消耗）：一切与现在完全一致。
        harness.seed()
        harness.worker = _worker(harness)
        harness.start_thread_to("source_finding")
        pending = harness.latest_adapter_pending()
        assert pending is not None
        harness.consume_adapter(pending.action_id)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=json.loads(pending.payload_json)["actionId"],
        )
        harness.worker.run_once()

        attempts = harness.commands.store.list_attempts("run-test")
        extraction = next(
            (a for a in attempts if a.node_id == "source_extraction"), None
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
        assert extraction.problem_json in (None, "")
        assert "source_extraction" in _adapter_pending_node_ids(harness)
        events = harness.commands.store.list_events("run-test")
        assert not any(
            e.event_type == "budget_precheck_blocked" for e in events
        )
        run = harness.commands.store.get_run("run-test")
        assert run is not None
        assert run.status != "blocked"
    finally:
        harness.close()


def test_no_history_conservative_default_passes_normal_run(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        harness.start_thread_to("source_finding")
        # 无任何历史样本：保守小额定值，远低于真实节点消耗，不误杀。
        decision = evaluate_stage_budget_admission(
            harness.commands.store,
            run_id="run-test",
            node_id="source_extraction",
            actor_kind="agent",
        )
        assert decision.admitted is True
        assert decision.reference_basis == "conservative_default"
        assert decision.reference_tokens == DEFAULT_CONSERVATIVE_REFERENCE_TOKENS
        assert decision.history_samples == 0

        harness.worker = _worker(harness)
        pending = harness.latest_adapter_pending()
        assert pending is not None
        harness.consume_adapter(pending.action_id)
        harness.resume(
            run_id="run-test",
            node_id="source_finding",
            attempt=1,
            action_id=json.loads(pending.payload_json)["actionId"],
        )
        harness.worker.run_once()
        attempts = harness.commands.store.list_attempts("run-test")
        extraction = next(
            (a for a in attempts if a.node_id == "source_extraction"), None
        )
        assert extraction is not None
        assert extraction.status == "dispatching"
    finally:
        harness.close()


def test_node_level_history_wins_over_stage_level(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        # 同 question 两个历史节点：source_extraction 400K、problem_understanding 1M。
        _seed_history(harness, node_id="source_extraction", tokens=400_000)
        _seed_history(
            harness, run_id="run-history-2", node_id="problem_understanding", tokens=1_000_000
        )
        decision = evaluate_stage_budget_admission(
            harness.commands.store,
            run_id="run-test",
            node_id="source_extraction",
            actor_kind="agent",
        )
        assert decision.reference_basis == "historical_median_node"
        assert decision.reference_tokens == 400_000
        assert decision.history_samples == 1
        assert decision.admitted is True
    finally:
        harness.close()


def test_non_agent_node_is_out_of_scope(tmp_path: Path) -> None:
    harness = GraphHarness(tmp_path)
    try:
        harness.seed()
        decision = evaluate_stage_budget_admission(
            harness.commands.store,
            run_id="run-test",
            node_id="protocol_freeze",
            actor_kind="system",
        )
        assert decision.admitted is True
        assert decision.reference_basis.startswith("evaluation_failed_fail_open")
    finally:
        harness.close()


def test_evaluation_failure_fails_open(tmp_path: Path) -> None:
    class ExplodingStore:
        def submit(self, *args, **kwargs):
            raise RuntimeError("ledger unavailable")

    decision = evaluate_stage_budget_admission(
        ExplodingStore(),
        run_id="run-x",
        node_id="source_extraction",
        actor_kind="agent",
    )
    assert decision.admitted is True
    assert decision.reference_basis.startswith("evaluation_failed_fail_open")
