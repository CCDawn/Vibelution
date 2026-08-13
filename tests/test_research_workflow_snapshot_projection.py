"""T6 RED/GREEN: Snapshot projection from Ledger + Domain refs (no UI state)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.command_offer_builder import (
    build_command_offers,
)
from core.web.services.team_workflow.research_runtime.projection_builder import (
    ProjectionInputs,
    build_research_workflow_snapshot,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    TeamScopeMismatchError,
    WorkflowLedgerUnavailable,
    WorkflowQueryError,
    WorkflowQueryService,
)
from tests._support.command_helpers import CommandHarness
from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
    open_ledger_store,
)


FIXED_GENERATED_AT = "2026-08-12T14:00:00.000Z"


def _seed_projection_run(harness: CommandHarness, run_id: str = "run-snap") -> None:
    harness.seed_run(run_id=run_id, status="running", run_version=3)

    def mutate(uow):
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-seed",
                run_id=run_id,
                node_id="source_finding",
                accepted_run_version=2,
                expected_run_version=1,
                idempotency_key=f"seed:{run_id}",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{run_id}-sf-1",
                run_id=run_id,
                node_id="source_finding",
                attempt=1,
                status="succeeded",
                command_id="cmd-seed",
            )
        )
        uow.repository.insert_event(
            build_event_record(
                sequence=2,
                run_id=run_id,
                run_version=2,
                event_type="node_succeeded",
                event_id=f"evt-2-{run_id}",
            )
        )
        uow.repository.insert_event(
            build_event_record(
                sequence=3,
                run_id=run_id,
                run_version=3,
                event_type="command_accepted",
                event_id=f"evt-3-{run_id}",
            )
        )
        uow.repository.execute(
            "UPDATE workflow_runs SET last_event_sequence = 3, run_version = 3, "
            "status = 'running', active_node_id = 'source_extraction', "
            "updated_at_ms = ? WHERE run_id = ?",
            (FIXED_NOW_MS + 50, run_id),
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_snapshot_rebuilds_deterministically_from_ledger(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_projection_run(harness)
        run = harness.store.get_run("run-snap")
        assert run is not None
        attempts = harness.store.list_attempts("run-snap")
        latest_seq = harness.store.latest_event_sequence("run-snap")
        definition = build_challenge_cup_workflow_definition()
        offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id=run.team_id,
            run=run,
            definition=definition,
            pending_human_tasks=(),
            evaluated_at_ms=FIXED_NOW_MS,
        )
        inputs = ProjectionInputs(
            run=run,
            definition=definition,
            attempts=tuple(attempts),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=tuple(offers),
            latest_event_sequence=latest_seq,
            generated_at=FIXED_GENERATED_AT,
        )
        snap_a = build_research_workflow_snapshot(inputs)
        snap_b = build_research_workflow_snapshot(inputs)
        assert snap_a.to_dict() == snap_b.to_dict()
        assert snap_a.latest_event_sequence == latest_seq == 3
        assert snap_a.generated_at == FIXED_GENERATED_AT
        assert snap_a.run.run_id == "run-snap"
        assert snap_a.run.team_id == "research-team"
        assert "source_finding" in snap_a.node_attempts
        assert snap_a.active_node_ids == ("source_extraction",)
        payload = snap_a.to_dict()
        for forbidden in (
            "selectedNodeId",
            "panel",
            "viewport",
            "hover",
            "dialog",
            "urlState",
            "pendingError",
        ):
            assert forbidden not in json.dumps(payload)
    finally:
        harness.close()


def test_snapshot_prefers_live_attempt_over_stale_run_pointer() -> None:
    run = replace(
        build_run_record(run_id="run-human-gate"),
        status="waiting_human",
        active_node_id="protocol_review",
    )
    attempts = (
        build_attempt_record(
            node_run_id="nr-run-human-gate-protocol_review-a4",
            run_id=run.run_id,
            node_id="protocol_review",
            attempt=4,
            status="succeeded",
            command_id="cmd-review",
        ),
        build_attempt_record(
            node_run_id="nr-run-human-gate-protocol_freeze-a1",
            run_id=run.run_id,
            node_id="protocol_freeze",
            attempt=1,
            status="waiting_human",
            command_id="cmd-freeze",
        ),
    )

    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=attempts,
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=4,
            generated_at=FIXED_GENERATED_AT,
        )
    )

    assert snapshot.active_node_ids == ("protocol_freeze",)
    assert snapshot.run.active_node_id == "protocol_freeze"


def test_snapshot_query_is_zero_write(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_projection_run(harness)
        writes = {"count": 0}
        original_submit = harness.store.submit

        def guarded_submit(fn, *, force_flush: bool = False):
            writes["count"] += 1
            raise AssertionError("snapshot query must not write")

        harness.store.submit = guarded_submit  # type: ignore[method-assign]
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        before = harness.store.latest_event_sequence("run-snap")
        snap = query.get_snapshot(team_id="research-team", run_id="run-snap")
        after = harness.store.latest_event_sequence("run-snap")
        assert writes["count"] == 0
        assert before == after == snap.latest_event_sequence
        assert snap.run.run_id == "run-snap"
        harness.store.submit = original_submit  # type: ignore[method-assign]
    finally:
        harness.close()


def test_snapshot_team_id_missing_or_mismatch_fails_explicitly(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_projection_run(harness)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
        )
        with pytest.raises(TeamScopeMismatchError):
            query.get_snapshot(team_id="", run_id="run-snap")
        with pytest.raises(TeamScopeMismatchError):
            query.get_snapshot(team_id="other-team", run_id="run-snap")
    finally:
        harness.close()


def test_command_offer_in_snapshot_accepted_by_command_service(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3", context=FakeDomainContext())
    try:
        harness.seed_run(run_id="run-offer", status="created", run_version=1)
        query = WorkflowQueryService(
            store=harness.store,
            readiness_service=harness.readiness,
            readiness_context=lambda: harness.context,
            clock_iso=lambda: FIXED_GENERATED_AT,
            evaluated_at_ms=lambda: FIXED_NOW_MS,
        )
        snap = query.get_snapshot(team_id="research-team", run_id="run-offer")
        available = [
            offer
            for offer in snap.command_offers
            if offer.available and offer.command == WorkflowCommandKind.START_NODE
        ]
        assert available, "expected at least one available start_node offer"
        offer = available[0]
        assert isinstance(offer, CommandOffer)
        assert offer.expected_run_version == snap.run.run_version
        receipt = harness.service.submit(
            harness.request(
                run_id="run-offer",
                command=offer.command,
                node_id=offer.node_id,
                expected_run_version=offer.expected_run_version,
                idempotency_key=offer.idempotency_key,
                payload=dict(offer.payload),
            )
        )
        assert receipt.status == "accepted"
        assert receipt.idempotency_key == offer.idempotency_key
        # Offer was signed for the pre-accept version; acceptance bumps runVersion.
        assert receipt.accepted_run_version == offer.expected_run_version + 1
    finally:
        harness.close()


def test_ledger_unavailable_does_not_read_legacy_json(tmp_path: Path) -> None:
    class BrokenStore:
        def get_run(self, run_id: str):
            raise WorkflowLedgerUnavailable("ledger down")

        def read(self, fn):
            raise WorkflowLedgerUnavailable("ledger down")

    query = WorkflowQueryService(
        store=BrokenStore(),  # type: ignore[arg-type]
        readiness_service=None,  # type: ignore[arg-type]
        readiness_context=lambda: FakeDomainContext(),
        clock_iso=lambda: FIXED_GENERATED_AT,
    )
    with pytest.raises(WorkflowLedgerUnavailable):
        query.get_snapshot(team_id="research-team", run_id="run-x")


def test_projection_builder_rejects_route_objects() -> None:
    run = build_run_record(run_id="run-x", last_event_sequence=1)
    definition = build_challenge_cup_workflow_definition()
    # ProjectionInputs is a typed dataclass — no request/HTTP fields.
    inputs = ProjectionInputs(
        run=run,
        definition=definition,
        attempts=(),
        pending_human_tasks=(),
        handoffs=(),
        budget_receipts=(),
        command_offers=(),
        latest_event_sequence=1,
        generated_at=FIXED_GENERATED_AT,
    )
    snap = build_research_workflow_snapshot(inputs)
    assert snap.latest_event_sequence == 1
    assert not hasattr(inputs, "request")
    assert not hasattr(inputs, "http_exception")


def test_snapshot_projects_frozen_agent_bindings(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        input_snapshot = {
            "agentBindingSnapshot": [
                {
                    "snapshotId": "snap:run-bind:source_finding",
                    "nodeId": "source_finding",
                    "agentId": "agent-finder",
                    "roleKey": "source_finder",
                    "resolvedFrom": "workflow_default",
                }
            ]
        }
        record = build_run_record(run_id="run-bind", last_event_sequence=1)
        record = record.__class__(
            **{
                **record.__dict__,
                "input_snapshot_json": json.dumps(input_snapshot, ensure_ascii=False),
            }
        )

        def mutate(uow):
            uow.repository.insert_run(record)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id="run-bind",
                    event_type="run_created",
                    event_id="evt-created-run-bind",
                )
            )

        harness.store.submit(mutate, force_flush=True).result(timeout=10)
        run = harness.store.get_run("run-bind")
        assert run is not None
        snap = build_research_workflow_snapshot(
            ProjectionInputs(
                run=run,
                definition=build_challenge_cup_workflow_definition(),
                attempts=(),
                pending_human_tasks=(),
                handoffs=(),
                budget_receipts=(),
                command_offers=(),
                latest_event_sequence=1,
                generated_at=FIXED_GENERATED_AT,
            )
        )
        payload = snap.agent_binding_summary.to_dict()
        assert payload["bindings"] == [
            {
                "nodeId": "source_finding",
                "agentId": "agent-finder",
                "roleKey": "source_finder",
                "resolvedFrom": "workflow_default",
                "snapshotId": "snap:run-bind:source_finding",
            }
        ]
    finally:
        harness.close()
