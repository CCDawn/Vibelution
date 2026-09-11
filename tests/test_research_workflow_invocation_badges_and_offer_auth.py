"""Snapshot carries knowledge-invocation badges and signed offer authorizations.

Covers the two additive snapshot projections owned by the knowledge-canvas
inspector task:

- per-main-node ``knowledge_invocations`` badge aggregates (totals, running,
  awaiting handoff, absorbed) plus the recent invocation summary lineage;
- the canonical offer authorization envelope: ``requiresOperator`` derived
  from the command service's enforcement set and a server HMAC signature
  binding (scope, run version, validity window).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.contracts.workflow_snapshot import CommandOffer
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    resolve_definition,
    workflow_version_id_for,
)
from core.research.workflow.ledger.records import KnowledgeInvocationRecord
from core.web.services.team_workflow.research_runtime.knowledge_invocation_projection import (
    current_knowledge_node_id,
    project_knowledge_invocation_badges,
)
from core.web.services.team_workflow.research_runtime.offer_authorization import (
    AUTHORIZATION_STATUS_AUTHORIZED,
    AUTHORIZATION_STATUS_OPERATOR_REQUIRED,
    build_offer_authorizations,
    operator_only_command_ids,
    verify_offer_authorization,
)
from core.web.services.team_workflow.research_runtime.projection_builder import (
    ProjectionInputs,
    build_research_workflow_snapshot,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    NodeNotFoundError,
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
)

AUTH_KEY = "test-signing-key"


def _invocation(
    invocation_id: str,
    *,
    parent_node_id: str = "hypothesis_design",
    status: str = "running",
    handoff_state: str = "pending",
    child_run_id: str | None = "child-run-1",
    updated_at_ms: int = FIXED_NOW_MS,
) -> KnowledgeInvocationRecord:
    return KnowledgeInvocationRecord(
        invocation_id=invocation_id,
        parent_run_id="run-snap",
        parent_node_id=parent_node_id,
        parent_node_run_id="nr-parent",
        parent_attempt=1,
        question_id="SCI-096",
        scope_hash="scope",
        request_hash=f"req-{invocation_id}",
        search_envelope_hash="env",
        requirements_hash="req-hash",
        source_policy_version="v1",
        knowledge_child_run_id=child_run_id,
        status=status,
        knowledge_package_ref=None if status != "completed" else "pkg://k1",
        package_content_hash=None,
        handoff_state=handoff_state,
        error_json=None,
        created_at_ms=updated_at_ms - 1000,
        updated_at_ms=updated_at_ms,
    )


def _seed_run_with_invocations(harness: CommandHarness, run_id: str = "run-snap") -> None:
    harness.seed_run(run_id=run_id, status="running", run_version=3)
    # The knowledge child run needs its own run row (node_attempts FK).
    harness.seed_run(
        run_id="child-run-2",
        status="running",
        run_version=1,
        workflow_version_id="",
        parent_run_id=run_id,
    )

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
        uow.repository.insert_knowledge_invocation(
            _invocation("ki-1", parent_node_id="hypothesis_design", status="running")
        )
        uow.repository.insert_knowledge_invocation(
            _invocation(
                "ki-2",
                parent_node_id="hypothesis_design",
                status="awaiting_handoff",
                handoff_state="pending",
                child_run_id="child-run-2",
                updated_at_ms=FIXED_NOW_MS + 500,
            )
        )
        uow.repository.insert_knowledge_invocation(
            _invocation(
                "ki-3",
                parent_node_id="result_evaluation",
                status="completed",
                handoff_state="accepted",
            )
        )
        # Real child-run node attempts: the five-node sideflow progress reads
        # these instead of guessing middle nodes from the invocation status.
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-child-seed",
                run_id="child-run-2",
                node_id="source_finding",
                accepted_run_version=1,
                expected_run_version=1,
                idempotency_key="seed:child-run-2",
            )
        )
        for index, (node_id, status) in enumerate(
            [
                ("source_finding", "succeeded"),
                ("source_extraction", "succeeded"),
                ("evidence_relations", "running"),
            ],
            start=1,
        ):
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=f"nr-child-run-2-{index}",
                    run_id="child-run-2",
                    node_id=node_id,
                    attempt=1,
                    status=status,
                    command_id="cmd-child-seed",
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _query(harness: CommandHarness) -> WorkflowQueryService:
    return WorkflowQueryService(
        store=harness.store,
        readiness_service=harness.readiness,
        readiness_context=lambda: harness.context,
        clock_iso=lambda: "2026-08-28T00:00:00.000Z",
        evaluated_at_ms=lambda: FIXED_NOW_MS,
    )


def test_snapshot_projects_knowledge_invocation_badges(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_run_with_invocations(harness)
        snapshot = _query(harness).get_snapshot(team_id="research-team", run_id="run-snap")

        badges = snapshot.invocation_badges
        assert set(badges) == {"hypothesis_design", "result_evaluation"}
        hypothesis_badge = badges["hypothesis_design"]
        assert hypothesis_badge.total_count == 2
        assert hypothesis_badge.running_count == 1
        assert hypothesis_badge.awaiting_handoff_count == 1
        assert hypothesis_badge.absorbed_count == 0
        # Latest invocation wins by updated_at_ms, not insertion order.
        assert hypothesis_badge.latest is not None
        assert hypothesis_badge.latest.invocation_id == "ki-2"
        assert hypothesis_badge.latest.knowledge_child_run_id == "child-run-2"
        assert hypothesis_badge.latest.status == "awaiting_handoff"
        assert hypothesis_badge.latest.handoff_state == "pending"
        # SCI-049 O-03: the child run's real node attempts decide the live
        # node (evidence_relations is running) — not the invocation-level
        # status derivation, which would have reported the handoff gate.
        assert hypothesis_badge.latest.current_knowledge_node_id == "evidence_relations"
        # Real child-run node states ride along for the five-card progress.
        assert hypothesis_badge.latest.child_node_states == {
            "source_finding": "succeeded",
            "source_extraction": "succeeded",
            "evidence_relations": "running",
        }
        # SCI-049 O-02: the badge quotes the auto-advance sweep cadence and
        # marks the waiting gate as auto-accept pending.
        assert hypothesis_badge.auto_accept == {
            "pending": True,
            "actor": "auto_advance_sweep",
            "intervalMs": 30_000,
        }
        assert badges["result_evaluation"].auto_accept == {
            "pending": False,
            "actor": "auto_advance_sweep",
            "intervalMs": 30_000,
        }

        serialized = snapshot.to_dict()
        assert serialized["invocationBadges"]["hypothesis_design"]["totalCount"] == 2
        latest = serialized["invocationBadges"]["hypothesis_design"]["latest"]
        assert latest["currentKnowledgeNodeId"] == "evidence_relations"
        assert latest["knowledgeChildRunId"] == "child-run-2"
        assert latest["childNodeStates"]["evidence_relations"] == "running"
        assert serialized["invocationBadges"]["hypothesis_design"]["autoAccept"] == {
            "pending": True,
            "actor": "auto_advance_sweep",
            "intervalMs": 30_000,
        }
    finally:
        harness.close()


def test_snapshot_serializes_operator_gate_and_signature_into_offers(
    tmp_path: Path,
) -> None:
    run = build_run_record(run_id="run-auth", status="running", run_version=7)
    offers = (
        CommandOffer(
            command=WorkflowCommandKind.START_NODE,
            node_id="source_finding",
            available=True,
            label="Start",
            reason_code="ok",
            blocker_ids=(),
            idempotency_key="auth:start",
            expected_run_version=7,
        ),
        CommandOffer(
            command=WorkflowCommandKind.CANCEL_RUN,
            node_id=None,
            available=True,
            label="Cancel",
            reason_code="ok",
            blocker_ids=(),
            idempotency_key="auth:cancel",
            expected_run_version=7,
        ),
    )
    snapshot = build_research_workflow_snapshot(
        ProjectionInputs(
            run=run,
            definition=build_challenge_cup_workflow_definition(),
            attempts=(),
            pending_human_tasks=(),
            handoffs=(),
            budget_receipts=(),
            command_offers=offers,
            latest_event_sequence=0,
            generated_at="2026-08-28T00:00:00.000Z",
            authorization_key=AUTH_KEY,
            now_ms=FIXED_NOW_MS,
        )
    )
    assert "cancel_run" in operator_only_command_ids()

    payload = snapshot.to_dict()
    by_key = {item["idempotencyKey"]: item for item in payload["commandOffers"]}
    start = by_key["auth:start"]
    cancel = by_key["auth:cancel"]

    assert start["requiresOperator"] is False
    assert start["authorizationStatus"] == AUTHORIZATION_STATUS_AUTHORIZED
    assert cancel["requiresOperator"] is True
    assert cancel["authorizationStatus"] == AUTHORIZATION_STATUS_OPERATOR_REQUIRED
    assert cancel["authorizationReason"] == "operator_permission_required"
    for offer in (start, cancel):
        assert offer["expectedRunVersion"] == 7
        assert offer["signedAt"] == FIXED_NOW_MS
        assert offer["expiresAt"] > FIXED_NOW_MS
        assert offer["signature"]

    ok, reason = verify_offer_authorization(
        cancel, key=AUTH_KEY, run_id="run-auth", now_ms=FIXED_NOW_MS + 1
    )
    assert ok and reason == "ok"

    tampered = dict(cancel, signature="0" * len(cancel["signature"]))
    ok, reason = verify_offer_authorization(
        tampered, key=AUTH_KEY, run_id="run-auth", now_ms=FIXED_NOW_MS + 1
    )
    assert not ok and reason == "authorization_signature_invalid"

    expired_window = build_offer_authorizations(
        run_id="run-auth",
        run_version=7,
        offers=offers,
        now_ms=FIXED_NOW_MS,
        ttl_ms=0,
        key=AUTH_KEY,
    )
    ok, reason = verify_offer_authorization(
        expired_window[1], key=AUTH_KEY, run_id="run-auth", now_ms=FIXED_NOW_MS + 1
    )
    assert not ok and reason == "authorization_expired"


def test_query_service_resolves_run_pinned_definition(tmp_path: Path) -> None:
    v3 = build_challenge_cup_workflow_definition()
    v3_version_id = workflow_version_id_for(v3.structureHash)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(
            run_id="run-v3",
            status="created",
            run_version=1,
            workflow_version_id=v3_version_id,
            structure_hash=v3.structureHash,
        )
        mismatch_record = replace(
            build_run_record(
                run_id="run-v3-hashmismatch",
                status="created",
                run_version=1,
                workflow_version_id=v3_version_id,
            ),
            structure_hash="f" * 64,
        )

        def _seed_mismatch(uow):
            uow.repository.insert_run(mismatch_record)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id="run-v3-hashmismatch",
                    event_type="run_created",
                    event_id="evt-created-run-v3-hashmismatch",
                )
            )

        harness.store.submit(_seed_mismatch, force_flush=True).result(timeout=10)
        harness.seed_run(
            run_id="run-legacy-unregistered",
            status="created",
            run_version=1,
            workflow_version_id="challenge-cup-research-unregistered",
        )
        harness.seed_run(
            run_id="run-ancient",
            status="created",
            run_version=1,
            workflow_version_id="",
        )
        query = _query(harness)

        resolved = resolve_definition(
            workflow_id="challenge-cup-research",
            workflow_version_id=v3_version_id,
        )
        assert len(resolved.nodes) == 12

        # Registered version id resolves the pinned 3.0.0 graph.
        snapshot_v3 = query.get_snapshot(team_id="research-team", run_id="run-v3")
        assert snapshot_v3.definition["schemaVersion"] == "3.0.0"
        assert len(snapshot_v3.definition["nodes"]) == 12

        for invalid_run_id in (
            "run-v3-hashmismatch",
            "run-legacy-unregistered",
            "run-ancient",
        ):
            with pytest.raises(WorkflowQueryError) as excinfo:
                query.get_snapshot(team_id="research-team", run_id=invalid_run_id)
            assert excinfo.value.code == "workflow_definition_unavailable"
    finally:
        harness.close()


def test_get_node_detail_judges_membership_against_pinned_definition(
    tmp_path: Path,
) -> None:
    v3 = build_challenge_cup_workflow_definition()
    v3_version_id = workflow_version_id_for(v3.structureHash)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run(
            run_id="run-v3",
            status="created",
            run_version=1,
            workflow_version_id=v3_version_id,
            structure_hash=v3.structureHash,
        )
        harness.seed_run(
            run_id="run-ancient",
            status="created",
            run_version=1,
            workflow_version_id="",
        )
        query = _query(harness)

        # knowledge_handoff belongs to the separate knowledge sideflow, so the
        # main run must reject it against its own pinned definition.
        with pytest.raises(NodeNotFoundError):
            query.get_node_detail(
                team_id="research-team", run_id="run-v3", node_id="knowledge_handoff"
            )
        with pytest.raises(WorkflowQueryError) as excinfo:
            query.get_node_detail(
                team_id="research-team",
                run_id="run-ancient",
                node_id="knowledge_handoff",
            )
        assert excinfo.value.code == "workflow_definition_unavailable"
    finally:
        harness.close()


def test_knowledge_invocation_projection_maps_status_to_sideflow_node() -> None:
    assert current_knowledge_node_id("pending") == "source_finding"
    assert current_knowledge_node_id("running") == "source_finding"
    assert current_knowledge_node_id("awaiting_handoff") == "knowledge_handoff"
    assert current_knowledge_node_id("completed") == "knowledge_handoff"
    assert current_knowledge_node_id("failed") is None


def test_current_knowledge_node_id_prefers_child_run_node_states() -> None:
    """SCI-049 O-03: real per-node attempts win; status only degrades.

    A running child run must not read as the chain entry when its latest
    attempts already reached a middle node; the invocation-status derivation
    stays as the fallback for children that expose no attempts.
    """
    from core.web.services.team_workflow.research_runtime.knowledge_invocation_projection import (
        current_knowledge_node_id_from_child_states,
    )

    # First non-terminal node in chain order is the live position.
    assert current_knowledge_node_id_from_child_states(
        {
            "source_finding": "succeeded",
            "source_extraction": "succeeded",
            "evidence_relations": "running",
        },
        fallback_status="running",
    ) == "evidence_relations"
    # A waiting_human gate is the live position.
    assert current_knowledge_node_id_from_child_states(
        {
            "source_finding": "succeeded",
            "knowledge_ingestion": "waiting_human",
        },
        fallback_status="running",
    ) == "knowledge_ingestion"
    # A failed node keeps the attention position instead of disappearing.
    assert current_knowledge_node_id_from_child_states(
        {"source_finding": "succeeded", "source_extraction": "failed"},
        fallback_status=None,
    ) == "source_extraction"
    # All known nodes terminal → the last known node is the honest position.
    assert current_knowledge_node_id_from_child_states(
        {
            "source_finding": "succeeded",
            "source_extraction": "succeeded",
            "knowledge_handoff": "succeeded",
        },
        fallback_status="completed",
    ) == "knowledge_handoff"
    # Unreadable node ids are ignored, not invented into the chain.
    assert current_knowledge_node_id_from_child_states(
        {"rogue_node": "running"},
        fallback_status="running",
    ) == "source_finding"
    # No child states → the invocation-status derivation degrades.
    assert current_knowledge_node_id_from_child_states(
        None,
        fallback_status="awaiting_handoff",
    ) == "knowledge_handoff"
    assert current_knowledge_node_id_from_child_states({}, fallback_status=None) is None

    badges = project_knowledge_invocation_badges(
        [
            _invocation("ki-a", parent_node_id="hypothesis_design", status="running"),
            _invocation("ki-b", parent_node_id="hypothesis_design", status="failed"),
            _invocation(
                "ki-c",
                parent_node_id="result_package",
                status="completed",
                handoff_state="accepted",
            ),
        ]
    )
    hypothesis = badges["hypothesis_design"]
    assert hypothesis["totalCount"] == 2
    assert hypothesis["runningCount"] == 1
    assert hypothesis["failedCount"] == 1
    assert hypothesis["absorbedCount"] == 0
    assert badges["result_package"]["absorbedCount"] == 1


def test_offer_authorizations_derive_requires_operator_from_command_service() -> None:
    run = build_run_record(run_id="run-derive", status="running", run_version=2)
    offers = tuple(
        CommandOffer(
            command=kind,
            node_id=None,
            available=False,
            label=kind.value,
            reason_code="unavailable",
            blocker_ids=(),
            idempotency_key=f"derive:{kind.value}",
            expected_run_version=2,
        )
        for kind in (
            WorkflowCommandKind.RETRY_NODE,
            WorkflowCommandKind.EXTEND_BUDGET,
            WorkflowCommandKind.REBIND_NODE,
            WorkflowCommandKind.RESOLVE_HUMAN_TASK,
        )
    )
    envelopes = build_offer_authorizations(
        run_id=run.run_id,
        run_version=run.run_version,
        offers=offers,
        now_ms=FIXED_NOW_MS,
        key=AUTH_KEY,
    )
    by_command = {item["command"]: item for item in envelopes}
    assert by_command["retry_node"]["requiresOperator"] is False
    for command in ("extend_budget", "rebind_node", "resolve_human_task"):
        assert by_command[command]["requiresOperator"] is True
        assert (
            by_command[command]["authorizationStatus"]
            == AUTHORIZATION_STATUS_OPERATOR_REQUIRED
        )


def test_invocation_badge_without_rows_keeps_snapshot_shape_unchanged() -> None:
    run = build_run_record(run_id="run-empty", status="created", run_version=1)
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
            generated_at="2026-08-28T00:00:00.000Z",
            authorization_key=AUTH_KEY,
            now_ms=FIXED_NOW_MS,
        )
    )
    assert snapshot.invocation_badges == {}
    assert snapshot.command_authorizations == ()
    serialized = snapshot.to_dict()
    assert serialized["invocationBadges"] == {}
    assert serialized["commandOffers"] == []
    # Replace keeps the additive fields optional for old constructors.
    rebuilt = replace(snapshot)
    assert rebuilt.schema_version == snapshot.schema_version
    assert FakeDomainContext is not None
