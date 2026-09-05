from dataclasses import replace

import pytest

from core.research.workflow.contracts import ActorRef, WorkflowCommandKind
from core.web.services.team_workflow.research_runtime import scientific_semantic_ledger as semantics
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.command_helpers import CommandHarness


def test_cancel_records_authenticated_operator_and_replays_once(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(status="running")
        monkeypatch.setattr(harness.service._inner, "_close_cancel_run_inflight_turns", lambda _: None)
        request = harness.request(command=WorkflowCommandKind.CANCEL_RUN, node_id=None)
        request = replace(request, requested_by=ActorRef("agent", "client-display-agent"))
        with server_operator_scope("real-operator", roles=("operator", "admin")):
            first = harness.service.submit(request)
            replay = harness.service.submit(request)
        records = semantics.list_scientific_semantic_records(harness.store, request.run_id)
        assert len(records) == 1
        assert first.command_id == replay.command_id
        assert first.latest_event_sequence == harness.store.latest_event_sequence(request.run_id)
        assert replay.latest_event_sequence == first.latest_event_sequence
        assert records[0]["semantic"]["execution"] == {
            "status": "cancelled",
            "cancelledByAgentRef": "real-operator",
            "terminationReasonCode": "operator_cancelled",
        }
        assert records[0]["actor"] == {
            "agentType": "person", "associatedAgentRef": "real-operator",
        }
        assert "assessment" not in records[0]["semantic"]
    finally:
        harness.close()


def test_cancel_semantic_failure_rolls_back_run_command_and_cleanup(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(status="running")
        original = semantics.append_scientific_semantic_record_in_uow

        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("cancel semantic crash")

        monkeypatch.setattr(semantics, "append_scientific_semantic_record_in_uow", write_then_fail)
        request = harness.request(command=WorkflowCommandKind.CANCEL_RUN, node_id=None)
        with pytest.raises(RuntimeError, match="cancel semantic crash"):
            harness.service.submit(request)
        assert harness.store.get_run(request.run_id).status == "running"
        assert harness.store.get_command_by_idempotency(request.run_id, request.idempotency_key) is None
        assert harness.store.list_pending_outbox(request.run_id) == []
        assert semantics.list_scientific_semantic_records(harness.store, request.run_id) == []
    finally:
        harness.close()
