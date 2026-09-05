from dataclasses import replace

import pytest

from core.research.workflow.contracts import ActorRef, WorkflowCommandKind
from core.research.workflow.contracts.challenge_cup_stage_one_v3 import (
    ActivityExecution, ScientificSemanticRecord,
)
from core.web.services.team_workflow.research_runtime import scientific_semantic_ledger as semantics
from core.web.services.team_workflow.research_runtime.operator_authorization import server_operator_scope
from tests._support.command_helpers import CommandHarness


def test_archive_records_only_lifecycle_with_authenticated_actor_and_replays_once(tmp_path):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(status="succeeded")
        request = harness.request(command=WorkflowCommandKind.ARCHIVE_RUN, node_id=None)
        prior = semantics.append_scientific_semantic_record(
            harness.store, run_id=request.run_id, record_ref="execution:original",
            subject_ref=request.run_id,
            semantic=ScientificSemanticRecord(execution=ActivityExecution(status="succeeded")),
            actor_type="software_agent", actor_ref="executor", recorded_at_ms=1_750_000_000_100,
        )
        request = replace(request, requested_by=ActorRef("agent", "client-display-agent"))
        with server_operator_scope("real-operator", roles=("operator", "admin")):
            first = harness.service.submit(request)
            replay = harness.service.submit(request)
        records = semantics.list_scientific_semantic_records(harness.store, request.run_id)
        assert len(records) == 2
        assert records[0] == prior
        assert records[1]["semantic"]["record"] == {"availability": "archived"}
        assert not {"execution", "result", "assessment"}.intersection(records[1]["semantic"])
        assert records[1]["actor"] == {
            "agentType": "person", "associatedAgentRef": "real-operator",
        }
        assert records[1]["subjectRef"] == request.run_id
        assert harness.store.get_run(request.run_id).status == "archived"
        assert first.command_id == replay.command_id
        assert first.latest_event_sequence == harness.store.latest_event_sequence(request.run_id)
        assert replay.latest_event_sequence == first.latest_event_sequence
    finally:
        harness.close()


def test_archive_semantic_failure_rolls_back_run_command_and_events(tmp_path, monkeypatch):
    harness = CommandHarness(tmp_path / "ledger.sqlite")
    try:
        harness.seed_run(status="succeeded")
        request = harness.request(command=WorkflowCommandKind.ARCHIVE_RUN, node_id=None)
        before_run = harness.store.get_run(request.run_id)
        before_events = harness.store.list_events(request.run_id)
        original = semantics.append_scientific_semantic_record_in_uow

        def write_then_fail(*args, **kwargs):
            original(*args, **kwargs)
            raise RuntimeError("archive semantic crash")

        monkeypatch.setattr(semantics, "append_scientific_semantic_record_in_uow", write_then_fail)
        with pytest.raises(RuntimeError, match="archive semantic crash"):
            harness.service.submit(request)
        assert harness.store.get_run(request.run_id) == before_run
        assert harness.store.list_events(request.run_id) == before_events
        assert harness.store.get_command_by_idempotency(request.run_id, request.idempotency_key) is None
    finally:
        harness.close()
