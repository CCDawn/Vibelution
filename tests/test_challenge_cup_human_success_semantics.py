import json

import pytest

from core.research.workflow.contracts import ExecutionReceipt
from core.web.services.team_workflow.research_runtime import scientific_semantic_ledger as semantics
from tests._support.graph_helpers import GraphHarness
from tests._support.workflow_ledger_helpers import FIXED_NOW_MS


def _enqueue_human_resume(harness, *, outcome="succeeded"):
    harness.seed()
    pending = harness.start_thread_to("protocol_freeze")
    payload = json.loads(pending.payload_json)
    harness.consume_adapter(pending.action_id)
    receipt = ExecutionReceipt(
        action_id=payload["actionId"], node_run_id=payload["nodeRunId"],
        outcome=outcome, artifact_receipt_ids=(), execution_anchor_id=None,
        budget_receipt_id=None, problem=None, completed_at_ms=FIXED_NOW_MS,
    )
    harness.enqueue_graph_dispatch(
        "run-test", "protocol_freeze", int(payload["attempt"]),
        dispatch_kind="resume_human", receipt=receipt,
        idempotency_key="human-accept-once",
    )
    return payload


def test_human_success_is_recorded_once_without_result_or_assessment(tmp_path):
    harness = GraphHarness(tmp_path)
    try:
        payload = _enqueue_human_resume(harness)
        harness.worker.run_once()
        harness.worker.run_once()
        store = harness.commands.store
        records = semantics.list_scientific_semantic_records(store, "run-test")
        assert len(records) == 1
        assert records[0]["subjectRef"] == payload["nodeRunId"]
        assert records[0]["semantic"]["execution"] == {"status": "succeeded"}
        assert not {"result", "assessment"}.intersection(records[0]["semantic"])
        assert records[0]["actor"] == {
            "agentType": "software_agent", "associatedAgentRef": "graph-worker-test",
        }
        assert store.latest_attempt("run-test", "protocol_freeze").status == "succeeded"
    finally:
        harness.close()


def test_human_rejection_is_not_invented_as_failed_scientific_execution(tmp_path):
    harness = GraphHarness(tmp_path)
    try:
        _enqueue_human_resume(harness, outcome="failed")
        harness.worker.run_once()
        assert semantics.list_scientific_semantic_records(harness.commands.store, "run-test") == []
    finally:
        harness.close()


@pytest.mark.parametrize("commit_method", ["_commit_dispatch", "_commit_upstream_accept"])
def test_human_success_semantic_failure_rolls_back_dispatch_commit(tmp_path, monkeypatch, commit_method):
    harness = GraphHarness(tmp_path)
    try:
        _enqueue_human_resume(harness)
        store = harness.commands.store
        before = store.latest_attempt("run-test", "protocol_freeze")
        original = semantics.append_scientific_semantic_record_in_uow

        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("human success semantic crash")

        monkeypatch.setattr(semantics, "append_scientific_semantic_record_in_uow", write_then_fail)
        # Exercise the real graph resume, then its transaction directly so
        # worker retry/error recording cannot obscure the rollback boundary.
        from core.research.workflow.challenge_cup_runtime import GraphDispatch
        from core.research.workflow.ledger import outbox as outbox_api
        outbox = outbox_api.lease_ready_actions(
            store, owner="graph-worker-test", limit=8,
            now_ms=FIXED_NOW_MS + 1000, lease_ms=30_000,
            action_kinds=("graph_dispatch",),
        )[0]
        dispatch = GraphDispatch.from_payload(json.loads(outbox.payload_json))
        result = harness.worker._resume(dispatch)
        with pytest.raises(RuntimeError, match="human success semantic crash"):
            getattr(harness.worker, commit_method)(outbox, dispatch, result)
        assert store.latest_attempt("run-test", "protocol_freeze") == before
        assert store.latest_attempt("run-test", "smoke_gate") is None
        assert semantics.list_scientific_semantic_records(store, "run-test") == []
    finally:
        harness.close()
