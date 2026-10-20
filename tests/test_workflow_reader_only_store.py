"""Readiness facts stay correct on a reader-only (never opened) ledger store."""

from dataclasses import replace
from pathlib import Path

from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger import WorkflowLedgerStore
from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
    _budget_consumed_from_ledger,
    _run_ids_for,
)
from tests._support.workflow_ledger_helpers import build_attempt_record, build_command_record, build_event_record, build_run_record


def _seed_ledger(path: Path) -> None:
    store = WorkflowLedgerStore(path)
    store.open()
    try:
        version = register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId
        record = replace(build_run_record(workflow_version_id=version),
                         last_event_sequence=1)
        def seed(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_command(build_command_record())
            uow.repository.insert_attempt(build_attempt_record(node_run_id="node-test"))
            uow.repository.insert_event(build_event_record(sequence=1))
            uow.repository.insert_budget_receipt(
                receipt_id="receipt-reader", run_id="run-test", node_run_id="node-test",
                reservation_id="reservation-reader", stage_id="knowledge_collection",
                policy_hash="policy", reserved_json='{"tokens":17,"toolCalls":2}',
                created_at_ms=record.created_at_ms,
            )
        store.submit(seed, force_flush=True).result(timeout=10)
    finally:
        store.close()


def test_readiness_facts_work_on_reader_only_store(tmp_path):
    path = tmp_path / "workflow-ledger.sqlite"
    _seed_ledger(path)
    store = WorkflowLedgerStore(path)
    try:
        context = RealDomainReadinessContext(store)
        assert context.recovery_blocker_codes("run-test") == []
        assert context.incoming_handoffs("run-test", "problem_understanding") == []
        assert _run_ids_for(store, "research-team") == ["run-test"]
        assert _budget_consumed_from_ledger(store, "run-test", stage_id="knowledge_collection")["tokens"] == 17
        assert context.accepted_knowledge_invocations("research-team", "run-test") == []
        assert store._writer is None
    finally:
        store.close()
