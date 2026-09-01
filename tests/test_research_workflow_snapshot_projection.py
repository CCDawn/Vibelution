"""T6 RED/GREEN: Snapshot projection from Ledger + Domain refs (no UI state)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import CommandOffer, WorkflowCommandKind
from core.research.workflow.contracts.discussion_scope import WorkflowDiscussionScopeV1
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.command_offer_builder import (
    build_command_offers,
)
from core.web.services.team_workflow.research_runtime.projection_builder import (
    ProjectionInputs,
    build_research_workflow_snapshot,
)
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    question_launch,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    TeamScopeMismatchError,
    WorkflowLedgerUnavailable,
    WorkflowQueryService,
    _discussion_inputs_from_run,
    _delivery_projection_from_events,
    _launch_context_from_run,
    _read_bounded_events,
)
from tests._support.command_helpers import CommandHarness
from tests._support.readiness_fakes import FakeDomainContext
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)

FIXED_GENERATED_AT = "2026-08-12T14:00:00.000Z"


def _discussion_scope_for_projection() -> WorkflowDiscussionScopeV1:
    return WorkflowDiscussionScopeV1.generation(
        teamId="research-team",
        researchProjectId="challenge-sci-096",
        workflowRunId="run-discussion-anchor",
        workflowNodeId="hypothesis_design",
        questionId="SCI-096",
    )


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


def test_snapshot_projects_formal_runtime_semantics_for_waiting_human() -> None:
    run = replace(
        build_run_record(run_id="run-v2-human"),
        status="waiting_human",
        active_node_id="protocol_freeze",
    )
    attempt = build_attempt_record(
        node_run_id="nr-run-v2-human-protocol_freeze-a1",
        run_id=run.run_id,
        node_id="protocol_freeze",
        actor_kind="human",
        status="waiting_human",
        command_id="cmd-v2-human",
    )
    task = {
        "taskId": "task-v2-human",
        "runId": run.run_id,
        "nodeRunId": attempt.node_run_id,
        "nodeId": attempt.node_id,
        "handoffId": "handoff-v2-human",
        "taskKind": "protocol_freeze",
        "status": "pending",
        "createdAtMs": FIXED_NOW_MS,
    }

    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(attempt,),
            pending_human_tasks=(task,),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    )

    payload = snapshot.to_dict()
    assert payload["schemaVersion"] == 2
    assert payload["currentTask"] == {
        "key": "task-v2-human",
        "nodeId": "protocol_freeze",
        "stageId": "experiment_design",
        "nodeRunId": attempt.node_run_id,
        "attempt": 1,
        "actorKind": "human",
        "taskId": "task-v2-human",
        "sessionId": None,
        "turnId": None,
        "executionAnchorId": None,
        "status": "waiting_human",
        "state": "waiting_user",
        "kind": "human_gate",
        "label": "协议冻结",
        "detail": None,
        "responsibility": "user",
        "maxAttempts": None,
        "automaticNextStep": None,
        "blockedReason": None,
        "recovery": {
            "status": "none",
            "retryable": False,
            "code": None,
            "detail": None,
            "retryScope": "none",
            "recoveryPoint": None,
            "nextRetryAt": None,
            "requiresOperator": False,
            "afterSubmit": None,
        },
        "authority": "formal_runtime",
    }
    assert payload["progress"]["currentNodeId"] == "protocol_freeze"
    assert payload["progress"]["total"] == len(snapshot.definition["nodes"])
    assert payload["recovery"]["status"] == "none"
    assert payload["retry"]["available"] is False


@pytest.mark.parametrize(
    ("status", "active_node_id", "attempt_status", "expected_task_status"),
    [
        ("created", None, None, None),
        ("running", "source_finding", "running", "running"),
        ("succeeded", None, "succeeded", None),
    ],
)
def test_snapshot_projects_no_active_auto_running_and_completed_states(
    status: str,
    active_node_id: str | None,
    attempt_status: str | None,
    expected_task_status: str | None,
) -> None:
    run = replace(
        build_run_record(run_id=f"run-v2-{status}"),
        status=status,
        active_node_id=active_node_id,
    )
    attempts = ()
    if attempt_status is not None:
        attempts = (
            build_attempt_record(
                node_run_id=f"nr-run-v2-{status}-source_finding-a1",
                run_id=run.run_id,
                node_id="source_finding",
                status=attempt_status,
                command_id=f"cmd-v2-{status}",
            ),
        )
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=attempts,
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    if expected_task_status is None:
        if status == "succeeded":
            assert payload["currentTask"]["state"] == "completed"
        else:
            assert payload["currentTask"] is None
    else:
        assert payload["currentTask"]["status"] == expected_task_status
        assert payload["currentTask"]["key"] == (
            f"nr-run-v2-{status}-source_finding-a1"
        )
        assert payload["currentTask"]["responsibility"] == "system"
        assert payload["currentTask"]["automaticNextStep"] is None
    assert payload["progress"]["status"] == (
        "not_started" if status == "created" else
        "auto_running" if status == "running" else
        "completed"
    )


def test_snapshot_does_not_guess_auto_running_from_history_only() -> None:
    run = replace(
        build_run_record(run_id="run-v2-history-only"),
        status="running",
        active_node_id=None,
    )
    historical_attempt = build_attempt_record(
        node_run_id="nr-v2-history-only-source-finding",
        run_id=run.run_id,
        node_id="source_finding",
        status="succeeded",
        command_id="cmd-v2-history-only",
    )
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(historical_attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()

    assert payload["currentTask"] is None
    assert payload["progress"]["status"] == "unknown"


def test_snapshot_projects_retryable_and_terminal_blocked_semantics() -> None:
    definition = build_challenge_cup_workflow_definition()
    retryable_run = replace(
        build_run_record(run_id="run-v2-retryable"),
        status="blocked",
        active_node_id="source_extraction",
        blocked_problem_json=json.dumps(
            {
                "code": "provider_timeout",
                "detail": "upstream timed out",
                "failureClass": "provider_transport",
                "message": "Provider did not answer before the deadline",
                "blockerIds": ["provider-unavailable"],
                "retryable": True,
            }
        ),
    )
    retryable_attempt = build_attempt_record(
        node_run_id="nr-run-v2-retryable-source_extraction-a1",
        run_id=retryable_run.run_id,
        node_id="source_extraction",
        status="failed",
        command_id="cmd-v2-retryable",
        problem_json=json.dumps(
            {
                "code": "provider_timeout",
                "detail": "upstream timed out",
                "failureClass": "provider_transport",
                "message": "Provider did not answer before the deadline",
                "blockerIds": ["attempt-timeout"],
                "retryable": True,
            }
        ),
    )
    retry_offer = CommandOffer(
        command=WorkflowCommandKind.RETRY_NODE,
        node_id="source_extraction",
        available=True,
        label="重试 资料提炼",
        reason_code="retry_available",
        blocker_ids=("retry-budget-ready",),
        idempotency_key="offer:retryable",
        expected_run_version=retryable_run.run_version,
        payload={"retryKind": "same_node"},
    )
    retryable = build_research_workflow_snapshot(
        ProjectionInputs(
            run=retryable_run,
            definition=definition,
            attempts=(retryable_attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(retry_offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert retryable["currentTask"]["status"] == "blocked"
    assert retryable["currentTask"]["key"] == retryable_attempt.node_run_id
    assert retryable["currentTask"]["responsibility"] == "user"
    assert retryable["currentTask"]["blockedReason"] == {
        "code": "provider_timeout",
        "detail": "upstream timed out",
        "retryable": True,
        "failureClass": "provider_transport",
        "message": "Provider did not answer before the deadline",
        "blockerIds": ["attempt-timeout", "retry-budget-ready"],
    }
    assert retryable["retry"] == {
        "available": True,
        "command": "retry_node",
        "nodeId": "source_extraction",
        "reasonCode": "retry_available",
        "idempotencyKey": "offer:retryable",
        "expectedRunVersion": retryable_run.run_version,
    }
    assert retryable["recovery"] == {
        "status": "retryable",
        "retryable": True,
        "code": "provider_timeout",
        "detail": "upstream timed out",
        "retryScope": "task",
        "recoveryPoint": "source_extraction",
        "nextRetryAt": None,
        "requiresOperator": False,
        "afterSubmit": None,
    }
    assert retryable["currentTask"]["recovery"] == {
        "status": "retryable",
        "retryable": True,
        "code": "provider_timeout",
        "detail": "upstream timed out",
        "retryScope": "task",
        "recoveryPoint": "source_extraction",
        "nextRetryAt": None,
        "requiresOperator": False,
        "afterSubmit": None,
    }

    terminal_run = replace(
        retryable_run,
        run_id="run-v2-terminal",
        terminal_reason="operator_cancelled",
        blocked_problem_json=json.dumps(
            {
                "code": "operator_cancelled",
                "detail": "operator stopped the run",
                "retryable": False,
            }
        ),
    )
    terminal_attempt = replace(
        retryable_attempt,
        run_id=terminal_run.run_id,
        node_run_id="nr-run-v2-terminal-source_extraction-a1",
        problem_json=terminal_run.blocked_problem_json,
    )
    terminal = build_research_workflow_snapshot(
        ProjectionInputs(
            run=terminal_run,
            definition=definition,
            attempts=(terminal_attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(retry_offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert terminal["retry"]["available"] is False
    assert terminal["recovery"]["status"] == "terminal"
    assert terminal["recovery"]["retryable"] is False
    assert terminal["currentTask"]["responsibility"] == "operator"
    assert terminal["currentTask"]["recovery"]["retryScope"] == "none"
    assert terminal["currentTask"]["recovery"]["recoveryPoint"] is None
    assert terminal["currentTask"]["recovery"]["requiresOperator"] is True


def test_snapshot_live_attempt_owns_auto_running_state_over_start_offer() -> None:
    run = replace(
        build_run_record(run_id="run-v2-live-with-start-offer"),
        status="running",
        active_node_id="source_finding",
    )
    attempt = build_attempt_record(
        node_run_id="nr-v2-live-with-start-offer",
        run_id=run.run_id,
        node_id="source_finding",
        status="running",
        actor_kind="agent",
    )
    offer = CommandOffer(
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        available=True,
        label="启动资料发现",
        reason_code="start_available",
        blocker_ids=(),
        idempotency_key="offer:live-start",
        expected_run_version=run.run_version,
    )
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert payload["currentTask"]["state"] == "auto_running"
    assert payload["currentTask"]["responsibility"] == "system"
    assert payload["currentTask"]["automaticNextStep"] is None


def test_snapshot_current_task_surfaces_live_agent_task_identity_from_execution_anchor() -> None:
    """Dispatch-time anchor: currentTask shows the live Agent task immediately."""

    run = replace(
        build_run_record(run_id="run-v2-anchor-current-task"),
        status="running",
        active_node_id="source_finding",
    )
    attempt = replace(
        build_attempt_record(
            node_run_id="nr-v2-anchor-current-task",
            run_id=run.run_id,
            node_id="source_finding",
            status="running",
            actor_kind="agent",
        ),
        execution_anchor_id="anchor-provisional-1",
    )
    anchor = {
        "anchorId": "anchor-provisional-1",
        "nodeRunId": "nr-v2-anchor-current-task",
        "agentId": "agent-finder",
        "roleKey": "source_finder",
        "sessionId": "session-live-finding",
        "sessionAttempt": 1,
        "taskId": "stagetask-live-finding",
        "turnId": "turn-live-finding",
        "status": "running",
    }

    def _build(with_anchor: bool):
        return build_research_workflow_snapshot(
            ProjectionInputs(
                run=run,
                definition=build_challenge_cup_workflow_definition(),
                attempts=(attempt,),
                pending_human_tasks=(),
                handoffs=(),
                budget_receipts=(),
                command_offers=(),
                execution_anchors=(anchor,) if with_anchor else (),
                latest_event_sequence=1,
                generated_at=FIXED_GENERATED_AT,
            )
        ).to_dict()

    payload = _build(True)
    assert payload["currentTask"]["state"] == "auto_running"
    assert payload["currentTask"]["taskId"] == "stagetask-live-finding"
    assert payload["currentTask"]["sessionId"] == "session-live-finding"
    assert payload["currentTask"]["turnId"] == "turn-live-finding"
    assert payload["currentTask"]["executionAnchorId"] == "anchor-provisional-1"
    assert payload["currentTask"]["key"] == "stagetask-live-finding"

    bare = _build(False)
    assert bare["currentTask"]["state"] == "auto_running"
    assert bare["currentTask"]["taskId"] is None
    assert bare["currentTask"]["sessionId"] is None
    assert bare["currentTask"]["turnId"] is None
    # The attempt's own anchor pointer is still surfaced without the row.
    assert bare["currentTask"]["executionAnchorId"] == "anchor-provisional-1"


def test_snapshot_ignores_stale_human_task_when_current_node_run_id_is_known() -> None:
    run = replace(
        build_run_record(run_id="run-v2-stale-human-task"),
        status="running",
        active_node_id="source_finding",
    )
    current_node_run_id = "nr-v2-stale-human-task-current"
    attempt = build_attempt_record(
        node_run_id=current_node_run_id,
        run_id=run.run_id,
        node_id="source_finding",
        status="running",
        actor_kind="agent",
    )
    stale_task = {
        "taskId": "task-v2-stale-human",
        "runId": run.run_id,
        "nodeRunId": "nr-v2-stale-human-task-old",
        "nodeId": "source_finding",
        "taskKind": "old_gate",
        "status": "pending",
        "createdAtMs": FIXED_NOW_MS - 100,
    }
    current_task = {
        "taskId": "task-v2-current-human",
        "runId": run.run_id,
        "nodeRunId": current_node_run_id,
        "nodeId": "source_finding",
        "taskKind": "current_gate",
        "status": "pending",
        "createdAtMs": FIXED_NOW_MS,
    }
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(attempt,),
            pending_human_tasks=(stale_task,),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()

    assert payload["currentTask"]["state"] == "auto_running"

    exact_payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(attempt,),
            pending_human_tasks=(stale_task, current_task),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert exact_payload["currentTask"]["state"] == "waiting_user"
    assert exact_payload["currentTask"]["taskId"] == "task-v2-current-human"


def test_snapshot_current_task_key_uses_formal_identity_priority_and_no_role_key() -> None:
    definition = build_challenge_cup_workflow_definition()
    run = replace(
        build_run_record(run_id="run-v2-key-priority"),
        status="waiting_human",
        active_node_id="protocol_freeze",
    )
    attempt = build_attempt_record(
        node_run_id="nr-v2-key-priority",
        run_id=run.run_id,
        node_id="protocol_freeze",
        status="waiting_human",
        actor_kind="human",
    )
    task = {
        "taskId": "task-v2-key-priority",
        "nodeRunId": attempt.node_run_id,
        "nodeId": attempt.node_id,
        "roleKey": "must-not-be-used-as-task-key",
    }
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=definition,
            attempts=(attempt,),
            pending_human_tasks=(task,),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert payload["currentTask"]["key"] == "task-v2-key-priority"
    assert payload["currentTask"]["responsibility"] == "user"
    assert "roleKey" not in payload["currentTask"]


def test_snapshot_unknown_recovery_scope_is_fail_closed_without_retry_offer() -> None:
    run = replace(
        build_run_record(run_id="run-v2-unknown-recovery"),
        status="blocked",
        active_node_id="source_extraction",
        blocked_problem_json=json.dumps(
            {
                "code": "provider_timeout",
                "detail": "unknown retry authority",
                "retryable": True,
            }
        ),
    )
    attempt = build_attempt_record(
        node_run_id="nr-v2-unknown-recovery",
        run_id=run.run_id,
        node_id="source_extraction",
        status="blocked",
        problem_json=run.blocked_problem_json,
    )
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert payload["currentTask"]["state"] == "blocked_terminal"
    assert payload["currentTask"]["responsibility"] == "operator"
    assert payload["currentTask"]["recovery"]["retryScope"] == "none"
    assert payload["currentTask"]["recovery"]["recoveryPoint"] is None
    assert payload["currentTask"]["recovery"]["requiresOperator"] is True


def test_snapshot_projects_artifacts_delivery_and_launch_context() -> None:
    run = replace(
        build_run_record(run_id="run-v2-delivery"),
        status="succeeded",
        active_node_id=None,
        input_snapshot_json=json.dumps(
            {
                "teamId": "research-team",
                "projectId": "challenge-sci-096",
                "questionId": "SCI-096",
                "sourceCollectionRunId": "source-run-1",
                "constraintSnapshot": {"launchSource": "catalog"},
            }
        ),
    )
    artifact = {
        "receiptId": "receipt-v2-1",
        "nodeRunId": "nr-result-package-1",
        "artifactKind": "research_result_package",
        "canonicalRef": "workflow://research_result_package/result-v2",
        "artifactVersion": "1.0.0",
        "sha256": "b" * 64,
        "domainRevision": "rev-1",
        "materialized": True,
        "verifiedAtMs": FIXED_NOW_MS,
    }
    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            artifact_receipts=(artifact,),
            delivery_status="succeeded",
            launch_context={
                "source": "catalog",
                "sourceCollectionRunId": "source-run-1",
                "authorizationId": "auth-1",
            },
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert snapshot["deliveryStatus"] == "succeeded"
    assert snapshot["stageOne"] == {
        "authority": "challenge_program",
        "completionState": "pending",
        "formalTopology": {
            "workflowId": run.workflow_id,
            "workflowVersionId": run.workflow_version_id,
            "definitionResolution": "pinned",
            "role": "execution_authority",
        },
        "hypothesisView": {
            "nodePrefix": "hf_",
            "role": "operator_projection",
        },
        "knowledgeFlow": {
            "topology": "child_workflow",
            "rolloutMode": snapshot["knowledgeSideflowMode"],
            "role": "optional_child_workflow",
        },
    }
    assert snapshot["artifactSummary"] == {
        "count": 1,
        "materializedCount": 1,
        "kinds": ["research_result_package"],
        "finalArtifactId": None,
        "finalArtifactLocator": None,
        "refs": [
            {
                "receiptId": "receipt-v2-1",
                "nodeRunId": "nr-result-package-1",
                "kind": "research_result_package",
                "version": "1.0.0",
                "canonicalRef": "workflow://research_result_package/result-v2",
                "sha256": "b" * 64,
                "domainRevision": "rev-1",
                "materialized": True,
                "verifiedAtMs": FIXED_NOW_MS,
            }
        ],
    }
    assert snapshot["launchContext"] == {
        "source": "catalog",
        "sourceCollectionRunId": "source-run-1",
        "authorizationId": "auth-1",
        "planId": None,
        "questionId": "SCI-096",
        "hypothesisSelectionId": None,
        "catalogAuthorizationId": "auth-1",
        "readinessReportSha256": None,
        "chainCorrelationId": None,
        "inputSnapshotHash": "a" * 64,
    }


def test_snapshot_v2_current_task_and_stage_progress_are_explicit() -> None:
    definition = build_challenge_cup_workflow_definition()
    run = replace(
        build_run_record(run_id="run-v2-explicit-task"),
        status="created",
        active_node_id="source_finding",
        safety_limits_json=json.dumps({"maxAttempts": 4}),
    )
    offer = CommandOffer(
        command=WorkflowCommandKind.START_NODE,
        node_id="source_finding",
        available=True,
        label="启动 资料寻找",
        reason_code="ready",
        blocker_ids=(),
        idempotency_key="offer:explicit-start",
        expected_run_version=run.run_version,
        payload={},
    )

    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=definition,
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()

    task = payload["currentTask"]
    assert task is not None
    assert task["key"] == "offer:explicit-start"
    assert task["stageId"] == "knowledge_collection"
    assert task["state"] == "waiting_user"
    assert task["responsibility"] == "user"
    assert task["maxAttempts"] == 4
    assert task["automaticNextStep"] is None
    assert task["blockedReason"] is None
    assert task["recovery"] == {
        "status": "none",
        "retryable": False,
        "code": None,
        "detail": None,
        "retryScope": "none",
        "recoveryPoint": None,
        "nextRetryAt": None,
        "requiresOperator": False,
        "afterSubmit": None,
    }

    progress = payload["progress"]
    assert progress["status"] == "waiting_user"
    assert progress["currentStageId"] == "knowledge_collection"
    assert progress["completedNodes"] == 0
    assert progress["totalNodes"] == len(definition.nodes)
    assert progress["blockedNodes"] == 0
    assert progress["completedNodeIds"] == []
    assert progress["blockedNodeIds"] == []
    assert progress["stages"] == [
        {
            "id": "knowledge_collection",
            "completed": 0,
            "total": 6,
            "blocked": 0,
            "state": "current",
        },
        {
            "id": "experiment_design",
            "completed": 0,
            "total": 5,
            "blocked": 0,
            "state": "upcoming",
        },
        {
            "id": "execution_iteration",
            "completed": 0,
            "total": 6,
            "blocked": 0,
            "state": "upcoming",
        },
    ]


def test_snapshot_v2_waiting_user_stale_blocked_completed_and_terminal_states() -> None:
    definition = build_challenge_cup_workflow_definition()
    waiting_run = replace(
        build_run_record(run_id="run-v2-waiting-user"),
        status="waiting_human",
        active_node_id="protocol_freeze",
    )
    waiting_attempt = build_attempt_record(
        node_run_id="nr-v2-waiting-user",
        run_id=waiting_run.run_id,
        node_id="protocol_freeze",
        actor_kind="human",
        status="waiting_human",
    )
    waiting_payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=waiting_run,
            definition=definition,
            attempts=(waiting_attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert waiting_payload["currentTask"]["state"] == "waiting_user"
    assert waiting_payload["currentTask"]["responsibility"] == "user"
    assert waiting_payload["currentTask"]["stageId"] == "experiment_design"
    assert waiting_payload["progress"]["status"] == "waiting_user"
    assert waiting_payload["progress"]["currentStageId"] == "experiment_design"

    stale_blocked_run = replace(
        build_run_record(run_id="run-v2-stale-blocked"),
        status="running",
        active_node_id="source_extraction",
    )
    stale_blocked_attempt = build_attempt_record(
        node_run_id="nr-v2-stale-blocked",
        run_id=stale_blocked_run.run_id,
        node_id="source_extraction",
        status="blocked",
        problem_json=json.dumps(
            {"code": "provider_timeout", "detail": "timed out", "retryable": True}
        ),
    )
    retry_offer = CommandOffer(
        command=WorkflowCommandKind.RETRY_NODE,
        node_id="source_extraction",
        available=True,
        label="重试 资料提炼",
        reason_code="retry_available",
        blocker_ids=(),
        idempotency_key="offer:stale-retry",
        expected_run_version=stale_blocked_run.run_version,
        payload={"retryKind": "same_node"},
    )
    stale_payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=stale_blocked_run,
            definition=definition,
            attempts=(stale_blocked_attempt,),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(retry_offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert stale_payload["run"]["status"] == "blocked"
    assert stale_payload["currentTask"]["state"] == "blocked_retryable"
    assert stale_payload["progress"]["status"] == "blocked_retryable"
    assert stale_payload["progress"]["blockedNodes"] == 1
    assert stale_payload["progress"]["blockedNodeIds"] == ["source_extraction"]
    assert stale_payload["progress"]["stages"][0]["blocked"] == 1

    completed_run = replace(
        build_run_record(run_id="run-v2-completed"),
        status="succeeded",
        active_node_id=None,
    )
    completed_payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=completed_run,
            definition=definition,
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert completed_payload["currentTask"]["state"] == "completed"
    assert completed_payload["currentTask"]["responsibility"] == "system"
    assert completed_payload["progress"]["status"] == "completed"
    assert completed_payload["progress"]["percent"] == 100
    assert completed_payload["progress"]["completedNodes"] == len(definition.nodes)
    assert completed_payload["progress"]["completedNodeIds"] == [
        node.nodeId for node in definition.nodes
    ]
    assert all(stage["state"] == "completed" for stage in completed_payload["progress"]["stages"])

    terminal_run = replace(
        build_run_record(run_id="run-v2-terminal-explicit"),
        status="cancelled",
        active_node_id="source_finding",
        terminal_reason="operator_cancelled",
        blocked_problem_json=json.dumps(
            {"code": "operator_cancelled", "detail": "stopped", "retryable": False}
        ),
    )
    terminal_payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=terminal_run,
            definition=definition,
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert terminal_payload["currentTask"]["state"] == "blocked_terminal"
    assert terminal_payload["currentTask"]["responsibility"] == "operator"
    assert terminal_payload["currentTask"]["blockedReason"] == {
        "code": "operator_cancelled",
        "detail": "stopped",
        "retryable": False,
        "failureClass": None,
        "message": None,
        "blockerIds": [],
    }
    assert terminal_payload["currentTask"]["recovery"]["status"] == "terminal"
    assert terminal_payload["currentTask"]["recovery"]["retryScope"] == "none"
    assert terminal_payload["currentTask"]["recovery"]["recoveryPoint"] is None
    assert terminal_payload["currentTask"]["recovery"]["requiresOperator"] is True
    assert terminal_payload["progress"]["status"] == "blocked_terminal"


def test_snapshot_v2_delivery_event_is_authority_for_final_artifact_and_launch_names() -> None:
    run = replace(
        build_run_record(run_id="run-v2-final-artifact"),
        status="succeeded",
        input_snapshot_json=json.dumps(
            {
                "questionId": "SCI-096",
                "hypothesisSelectionId": "selection-1",
                "chainCorrelationId": "chain-input",
            }
        ),
    )
    locator = "delivery_orchestration_result://research-team/run-v2-final-artifact/hash"
    receipt = {
        "receiptId": "receipt-final",
        "nodeRunId": "nr-result-package",
        "artifactKind": "delivery_orchestration_result",
        "canonicalRef": locator,
        "artifactVersion": "1",
        "sha256": "a" * 64,
        "domainRevision": "rev-1",
        "materialized": True,
        "verifiedAtMs": FIXED_NOW_MS,
    }
    authorization_event = replace(
        build_event_record(
            sequence=2,
            run_id=run.run_id,
            event_type="catalog_run_authorized",
            event_id="evt-v2-catalog-auth",
            correlation_id="chain-event",
        ),
        payload_json=json.dumps(
            {
                "authorizationId": "catalog-auth-1",
                "readinessReportSha256": "b" * 64,
            }
        ),
    )
    delivery_event = replace(
        build_event_record(
            sequence=3,
            run_id=run.run_id,
            event_type="delivery_orchestration_completed",
            event_id="evt-v2-delivery-completed",
        ),
        payload_json=json.dumps(
            {
                "deliveryStatus": "succeeded",
                "artifactKind": "delivery_orchestration_result",
                "artifactRef": locator,
            }
        ),
    )
    delivery_status, delivery_artifact = _delivery_projection_from_events(
        [authorization_event, delivery_event],
        run_status=run.status,
    )
    launch_context = _launch_context_from_run(run, [authorization_event])
    assert delivery_status == "succeeded"
    assert delivery_artifact == {
        "artifactKind": "delivery_orchestration_result",
        "artifactRef": locator,
        "artifactId": None,
    }
    assert launch_context["catalogAuthorizationId"] == "catalog-auth-1"
    assert launch_context["readinessReportSha256"] == "b" * 64
    assert launch_context["chainCorrelationId"] == "chain-input"

    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            artifact_receipts=(receipt,),
            delivery_status=delivery_status,
            delivery_artifact=delivery_artifact,
            launch_context=launch_context,
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    assert payload["artifactSummary"]["finalArtifactId"] == "receipt-final"
    assert payload["artifactSummary"]["finalArtifactLocator"] == locator
    assert payload["launchContext"] == {
        "questionId": "SCI-096",
        "hypothesisSelectionId": "selection-1",
        "catalogAuthorizationId": "catalog-auth-1",
        "readinessReportSha256": "b" * 64,
        "chainCorrelationId": "chain-input",
        "source": None,
        "sourceCollectionRunId": None,
        "authorizationId": "catalog-auth-1",
        "planId": None,
        "inputSnapshotHash": "a" * 64,
    }


def test_launch_context_does_not_invent_chain_correlation_from_event_envelope() -> None:
    run = replace(
        build_run_record(run_id="run-v2-generic-correlation"),
        input_snapshot_json=json.dumps({"questionId": "SCI-096"}),
    )
    generic_event = replace(
        build_event_record(
            sequence=2,
            run_id=run.run_id,
            event_type="catalog_run_authorized",
            event_id="evt-v2-generic-correlation",
            correlation_id="transport-correlation-only",
        ),
        payload_json=json.dumps({"authorizationId": "catalog-auth-2"}),
    )
    explicit_event = replace(
        generic_event,
        payload_json=json.dumps(
            {
                "authorizationId": "catalog-auth-2",
                "chainCorrelationId": "chain-explicit",
            }
        ),
    )

    assert _launch_context_from_run(run, [generic_event])["chainCorrelationId"] is None
    assert _launch_context_from_run(run, [explicit_event])["chainCorrelationId"] == (
        "chain-explicit"
    )


def test_snapshot_query_reads_bounded_event_head_and_tail() -> None:
    class FakeRepo:
        def __init__(self):
            self.events = list(range(1, 601))
            self.calls: list[tuple[int, int]] = []

        def list_events(self, run_id: str, after_sequence: int = 0, limit: int = 500):
            self.calls.append((after_sequence, limit))
            return [
                sequence
                for sequence in self.events
                if sequence > after_sequence
            ][:limit]

    repo = FakeRepo()
    events = _read_bounded_events(repo, "run-v2-many-events", latest_sequence=600)
    assert len(events) == 500
    assert events[0] == 1
    assert events[-1] == 600
    assert repo.calls == [(0, 250), (350, 500)]


def test_snapshot_projection_exposes_server_active_discussion_anchor() -> None:
    scope = _discussion_scope_for_projection()
    run = build_run_record(run_id="run-discussion-anchor")
    meeting = {
        "meetingRoundId": "meeting-discussion-anchor",
        "discussionScope": scope.to_dict(),
        "scopeHash": scope.scope_hash,
        "linkedChatRoomId": "room-discussion-anchor",
        "status": "open",
    }
    room = {
        "roomId": "room-discussion-anchor",
        "status": "active",
        "config": {
            "discussionScope": scope.to_dict(),
            "scopeHash": scope.scope_hash,
        },
    }
    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=0,
            generated_at=FIXED_GENERATED_AT,
            discussion_projection={"scope": scope.to_dict()},
            discussion_meetings=(meeting,),
            discussion_rooms=(room,),
        )
    )

    anchor = snapshot.to_dict()["launchContext"]["activeDiscussionAnchor"]
    assert anchor["status"] == "ready"
    assert anchor["scopeHash"] == scope.scope_hash
    assert anchor["roomId"] == "room-discussion-anchor"
    assert anchor["meetingRoundId"] == "meeting-discussion-anchor"
    assert anchor["deepLink"].startswith("/chat?room=room-discussion-anchor&returnTo=")
    assert anchor["returnTo"] == (
        "/teams?teamId=research-team&researchView=workflow"
        "&runId=run-discussion-anchor&node=hypothesis_design"
    )


def test_snapshot_projection_keeps_missing_discussion_authority_degraded() -> None:
    scope = _discussion_scope_for_projection()
    run = build_run_record(run_id="run-discussion-degraded")
    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(),
            latest_event_sequence=0,
            generated_at=FIXED_GENERATED_AT,
            discussion_projection={"scope": scope.to_dict()},
            discussion_meetings=(),
            discussion_rooms=(),
        )
    )

    anchor = snapshot.to_dict()["launchContext"]["activeDiscussionAnchor"]
    assert anchor["status"] == "degraded"
    assert anchor["degradedReason"] == "meeting_missing"
    assert anchor["roomId"] == ""
    assert anchor["deepLink"] == ""


def test_discussion_query_uses_formal_meeting_read_and_raw_room_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = _discussion_scope_for_projection()
    run = replace(
        build_run_record(run_id="run-discussion-read-owner"),
        input_snapshot_json=json.dumps({"discussionScope": scope.to_dict()}),
    )
    from core.web.services import chat_room_service
    from core.web.services.team_workflow import meeting_rounds

    meeting_calls: list[str] = []
    monkeypatch.setattr(
        meeting_rounds,
        "list_meeting_rounds",
        lambda team_id: meeting_calls.append(team_id) or {"meetings": []},
    )

    class ReadOnlyRoomStore:
        def load(self) -> dict[str, object]:
            return {"rooms": []}

    monkeypatch.setattr(chat_room_service, "_store", lambda: ReadOnlyRoomStore())
    projection, meetings, rooms = _discussion_inputs_from_run(run, [], {})

    assert projection == {"scope": scope.to_dict()}
    assert meetings == []
    assert rooms == []
    assert meeting_calls == ["research-team"]


def test_hypothesis_first_discussion_projection_uses_current_run_chain_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = replace(
        build_run_record(run_id="run-current"),
        input_snapshot_json=json.dumps(
            {
                "questionId": "SCI-096",
                "researchObjectiveContract": {"hypothesisFirst": True},
                "discussionAuthority": {"meetings": [], "rooms": []},
            }
        ),
    )
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.query_service._discussion_projection_from_sources",
        lambda *_args: None,
    )

    def chain_state(team_id, question_id, *, workflow_run_id=""):
        calls.append((team_id, question_id, workflow_run_id))
        return {
            "activeDiscussionAnchor": {
                "workflowRunId": workflow_run_id or "run-sibling",
                "meetingRoundId": "meeting-current",
            }
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.hypothesis_first_chain.chain_state",
        chain_state,
    )

    projection, meetings, rooms = _discussion_inputs_from_run(run, [], {})

    assert projection == {
        "workflowRunId": "run-current",
        "meetingRoundId": "meeting-current",
    }
    assert meetings == []
    assert rooms == []
    assert calls == [("research-team", "SCI-096", "run-current")]


def test_round_candidate_ledger_fallback_uses_meeting_workflow_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = WorkflowDiscussionScopeV1.generation(
        teamId="research-team",
        researchProjectId="challenge-sci-096",
        workflowRunId="run-current",
        workflowNodeId="hypothesis_design",
        questionId="SCI-096",
    ).to_dict()
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(question_launch, "_approved_details", lambda _team_id: {})

    def list_candidates(team_id, *, question_id="", workflow_run_id=""):
        calls.append((team_id, question_id, workflow_run_id))
        return {
            "candidates": [
                {
                    "candidateId": "candidate-current",
                    "statement": "current claim",
                    "rationale": "current rationale",
                    "differenceFromAlternatives": "current difference",
                }
            ]
        }

    monkeypatch.setattr(
        hypothesis_first_chain,
        "list_hypothesis_candidates",
        list_candidates,
    )

    candidates = hypothesis_first_chain._build_round_candidates(
        "research-team",
        {
            "question": "SCI-096",
            "discussionScope": scope,
            "discussionItemRefs": ["hypothesis_candidate:candidate-current"],
        },
    )

    assert calls == [("research-team", "SCI-096", "run-current")]
    assert candidates == [
        {
            "candidateId": "candidate-current",
            "claim": "current claim",
            "rationale": "current rationale",
            "differenceFromAlternatives": "current difference",
        }
    ]

    selection_candidates = hypothesis_first_chain._build_round_candidates(
        "research-team",
        {
            "question": "SCI-096",
            "discussionItemRefs": ["hypothesis_candidate:candidate-current"],
        },
        workflow_run_id="run-selection",
    )
    assert selection_candidates == candidates
    assert calls[-1] == ("research-team", "SCI-096", "run-selection")


def test_snapshot_current_task_points_at_rerun_target_for_hollow_success() -> None:
    """A run blocked because a "succeeded" idempotent node never materialized
    its artifacts must project the re-run of that node as the current task;
    the wedged successor cannot recover itself."""
    definition = build_challenge_cup_workflow_definition()
    run = replace(
        build_run_record(run_id="run-hollow-finding"),
        status="blocked",
        active_node_id="source_extraction",
        blocked_problem_json=json.dumps(
            {"code": "auto_advance_not_ready", "detail": "source_candidates_missing"}
        ),
    )
    finding_attempt = build_attempt_record(
        node_run_id="nr-run-hollow-finding-source_finding-a3",
        run_id=run.run_id,
        node_id="source_finding",
        status="succeeded",
        attempt=3,
    )
    extraction_attempt = build_attempt_record(
        node_run_id="nr-run-hollow-finding-source_extraction-a1",
        run_id=run.run_id,
        node_id="source_extraction",
        status="blocked",
        attempt=1,
    )
    rerun_offer = CommandOffer(
        command=WorkflowCommandKind.RETRY_NODE,
        node_id="source_finding",
        available=True,
        label="重跑 资料寻找",
        reason_code="retry_available",
        blocker_ids=(),
        idempotency_key=(
            "offer:run-hollow-finding:source_finding:retry_node:a4:v2"
        ),
        expected_run_version=run.run_version,
    )
    payload = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=definition,
            attempts=(finding_attempt, extraction_attempt),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=(rerun_offer,),
            latest_event_sequence=1,
            generated_at=FIXED_GENERATED_AT,
        )
    ).to_dict()
    task = payload["currentTask"]
    assert task["nodeId"] == "source_finding"
    assert task["key"] == finding_attempt.node_run_id
    assert task["state"] == "blocked_retryable"
    assert payload["retry"]["nodeId"] == "source_finding"
    assert payload["retry"]["idempotencyKey"] == rerun_offer.idempotency_key
