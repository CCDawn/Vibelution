"""Formal Ledger/outbox coverage for the stage-one node-7 terminal."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from core.research.competition.stage_one_completion_policy import (
    load_stage_one_completion_policy,
)
from core.research.workflow.challenge_cup_runtime import (
    GraphDispatch,
    GraphDispatchResult,
    action_id_for,
)
from core.research.workflow.contracts import PendingAction
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import register_or_resolve
from core.research.workflow.ledger import outbox as outbox_api
from core.research.workflow.models import ActorKind
from core.web.services.team_workflow.research_runtime.action_registry import (
    ActionRegistry,
)
from core.web.services.team_workflow.research_runtime.adapter_dispatch_worker import (
    AdapterDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
    AgentActionAdapter,
)
from core.web.services.team_workflow.research_runtime.graph_dispatch_worker import (
    GraphDispatchWorker,
)
from core.web.services.team_workflow.research_runtime.node_execution_support import (
    NodeExecutionError,
)
from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
    enqueue_ledger_stage_one_closeout,
    evaluate_ledger_stage_one_closeout,
    stage_one_terminal_facts,
)
from tests._support.adapter_fakes import FakeDomainPorts
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)
from tests.test_research_workflow_stage_one_closeout import _payloads


def _stage_one_run(run_id: str = "run-stage-one"):
    definition = build_challenge_cup_workflow_definition()
    identity = register_or_resolve(definition)
    policy = load_stage_one_completion_policy()
    return dataclasses.replace(
        build_run_record(
            run_id=run_id,
            team_id="challenge-stage-one-team",
            workflow_id=definition.workflowId,
            workflow_version_id=identity.workflowVersionId,
            status="running",
            last_event_sequence=1,
        ),
        project_id="challenge-stage-one-project",
        question_id="SCI-091",
        input_snapshot_json=json.dumps(
            {
                "teamId": "challenge-stage-one-team",
                "projectId": "challenge-stage-one-project",
                "questionId": "SCI-091",
                "stageOneCompletionPolicy": policy.to_dict(),
            }
        ),
        structure_hash=identity.structureHash,
        active_node_id="hypothesis_design",
    )


def _action(run_id: str = "run-stage-one") -> PendingAction:
    return PendingAction(
        action_id="act-stage-one",
        run_id=run_id,
        node_run_id=f"nr-{run_id}-hypothesis_design-a1",
        node_id="hypothesis_design",
        attempt=1,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash="a" * 64,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="policy-stage-one",
    )


def _current_receipts(run_id: str) -> tuple[dict[str, str], ...]:
    policy = load_stage_one_completion_policy()
    return tuple(
        {
            "receiptId": f"receipt-{kind}",
            "artifactType": kind,
            "canonicalRef": f"{kind}://challenge-stage-one-team/{run_id}/{'a' * 64}",
            "version": "1.0.0",
            "sha256": "a" * 64,
            "domainRevision": "revision-1",
        }
        for kind in policy.requiredArtifactKinds
    )


def _seed(harness: CommandHarness, action: PendingAction) -> None:
    from core.research.workflow.ledger import OutboxRecord

    run = _stage_one_run(action.run_id)

    def mutate(uow) -> None:
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(
                1,
                run_id=run.run_id,
                event_id=f"evt-created-{run.run_id}",
            )
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-stage-one",
                run_id=run.run_id,
                team_id=run.team_id,
                node_id="hypothesis_design",
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=action.node_run_id,
                run_id=run.run_id,
                node_id="hypothesis_design",
                status="dispatching",
                command_id="cmd-stage-one",
            )
        )
        uow.repository.insert_outbox(
            OutboxRecord(
                action_id="adapter-stage-one",
                run_id=run.run_id,
                command_id="cmd-stage-one",
                node_run_id=action.node_run_id,
                action_kind="adapter_dispatch",
                idempotency_key="adapter:stage-one",
                payload_json=json.dumps(action.to_dict()),
                status="pending",
                attempt_count=0,
                available_at_ms=FIXED_NOW_MS,
                lease_owner=None,
                lease_expires_at_ms=None,
                last_problem_json=None,
                created_at_ms=FIXED_NOW_MS,
                updated_at_ms=FIXED_NOW_MS,
            )
        )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _seed_stage_one_receipts(harness: CommandHarness, action: PendingAction) -> None:
    def mutate(uow) -> None:
        for index, receipt in enumerate(_current_receipts(action.run_id)):
            uow.repository.insert_artifact_receipt(
                receipt_id=f"seed-stage-one-{index}",
                run_id=action.run_id,
                node_run_id=action.node_run_id,
                team_id="challenge-stage-one-team",
                artifact_kind=receipt["artifactType"],
                canonical_ref_json=json.dumps(
                    {"canonicalRef": receipt["canonicalRef"]}
                ),
                artifact_version=receipt["version"],
                sha256=receipt["sha256"],
                domain_revision=receipt["domainRevision"],
                materialized=1,
                verified_at_ms=FIXED_NOW_MS,
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def test_ledger_closeout_reads_run_bound_artifacts_and_rejects_phase_two_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    action = _action()
    try:
        _seed(harness, action)
        payloads = _payloads(action.run_id)

        def load_payload(receipt):
            kind = str(receipt["artifactType"])
            return payloads[f"{kind}:{kind}-artifact"]

        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.stage_one_closeout._load_ledger_artifact_payload",
            load_payload,
        )
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.program_candidate_handoff.handoff_result_package_to_challenge_program",
            lambda **_kwargs: {"status": "NEEDS_CONTEXT"},
        )

        outcome = evaluate_ledger_stage_one_closeout(
            harness.store,
            action=action,
            current_artifact_receipts=_current_receipts(action.run_id),
        )

        assert outcome is not None
        assert outcome.completion_state == ""
        assert outcome.status == "program_review_required"
        assert outcome.accepted is False
        assert set(outcome.receipt_stages) == {"generation", "review", "revision"}

        harness.store.submit(
            lambda uow: uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=f"nr-{action.run_id}-protocol_design-a1",
                    run_id=action.run_id,
                    node_id="protocol_design",
                    command_id="cmd-stage-one",
                )
            ),
            force_flush=True,
        ).result(timeout=10)
        with pytest.raises(NodeExecutionError) as exc:
            evaluate_ledger_stage_one_closeout(
                harness.store,
                action=action,
                current_artifact_receipts=_current_receipts(action.run_id),
            )
        assert exc.value.code == "stage_one_phase_two_attempt_exists"
    finally:
        harness.close()


def test_adapter_commit_emits_terminal_resume_without_phase_two_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    action = _action()
    try:
        _seed(harness, action)
        _seed_stage_one_receipts(harness, action)
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        payloads = _payloads(action.run_id)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.stage_one_closeout._load_ledger_artifact_payload",
            lambda receipt: payloads[
                f"{receipt['artifactType']}:{receipt['artifactType']}-artifact"
            ],
        )
        approved_handoff = {
            "status": "idempotent",
            "workflowRunId": action.run_id,
            "questionId": "SCI-091",
            "recordId": f"SCI-091:{action.run_id}",
            "reviewStatus": "approved",
            "outputSha256": "e" * 64,
            "sourceResultPackageHash": "a" * 64,
            "resultPackage": {"canonicalHash": "b" * 64},
            "officialModelCall": True,
            "receiptStatus": "passed",
            "humanGates": {"allApproved": True, "approvedCount": 4},
        }
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.program_candidate_handoff.handoff_result_package_to_challenge_program",
            lambda **_kwargs: approved_handoff,
        )
        scene_events: list[tuple[str, str, dict]] = []
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.adapter_dispatch_worker._record_scene_event",
            lambda event_code, *, outcome, fields: scene_events.append(
                (event_code, outcome, fields)
            ),
        )
        worker = AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: ("protocol_design",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        )

        worker.run_once()

        handoff = harness.store.read(
            lambda repo: repo.get_handoff_by_from_node(action.run_id, action.node_run_id)
        )
        assert handoff is None
        outboxes = harness.store.list_pending_outbox(action.run_id)
        resume = next(item for item in outboxes if item.action_kind == "graph_dispatch")
        resume_payload = json.loads(resume.payload_json)
        assert resume_payload["stateUpdate"]["stage_one_completion_state"] == (
            "STAGE1_G1_ACCEPTED"
        )
        assert harness.store.latest_attempt(action.run_id, "protocol_design") is None
        assert any(
            event.event_type == "stage_one_closeout_completed"
            for event in harness.store.list_events(action.run_id)
        )
        assert [item[0] for item in scene_events if item[0].startswith("stage_one_closeout.")] == [
            "stage_one_closeout.started",
            "stage_one_closeout.completed",
        ]
        completed_fields = scene_events[-1][2]
        assert completed_fields["programOutputId"] == approved_handoff["recordId"]
        assert completed_fields["packageSha256"] == "b" * 64
        assert completed_fields["programOutputSha256"] == "e" * 64
        assert "detail" not in completed_fields

        leased = outbox_api.lease_ready_actions(
            harness.store,
            owner="graph-stage-one",
            now_ms=FIXED_NOW_MS + 2_000,
            lease_ms=5_000,
            action_kinds=("graph_dispatch",),
        )
        assert len(leased) == 1
        dispatch = GraphDispatch.from_payload(json.loads(leased[0].payload_json))
        GraphDispatchWorker(
            store=harness.store,
            coordinator=object(),  # _commit_dispatch does not call the coordinator.
            owner_id="graph-stage-one",
            now_provider=lambda: FIXED_NOW_MS + 2_100,
        )._commit_dispatch(
            leased[0],
            dispatch,
            GraphDispatchResult(
                dispatch_kind="resume_action",
                pending_action=None,
                next_node_ids=(),
                checkpoint_id="checkpoint-stage-one-terminal",
                state={"stage_one_completion_state": "STAGE1_G1_ACCEPTED"},
                completed=True,
            ),
        )

        closed_run = harness.store.get_run(action.run_id)
        assert closed_run is not None
        assert closed_run.status == "succeeded"
        assert closed_run.completion_kind == "stage_one_g1_accepted"
        assert closed_run.terminal_reason == "STAGE1_G1_ACCEPTED"
        assert harness.store.latest_attempt(action.run_id, "protocol_design") is None
        assert any(
            item.action_kind == "delivery_orchestration"
            for item in harness.store.list_pending_outbox(action.run_id)
        )
    finally:
        harness.close()


def test_adapter_emits_aggregate_scene_when_program_review_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    action = _action()
    try:
        _seed(harness, action)
        _seed_stage_one_receipts(harness, action)
        payloads = _payloads(action.run_id)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.stage_one_closeout._load_ledger_artifact_payload",
            lambda receipt: payloads[
                f"{receipt['artifactType']}:{receipt['artifactType']}-artifact"
            ],
        )
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.program_candidate_handoff.handoff_result_package_to_challenge_program",
            lambda **_kwargs: {
                "status": "idempotent",
                "reviewStatus": "review_required",
            },
        )
        scene_events: list[tuple[str, str, dict]] = []
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.adapter_dispatch_worker._record_scene_event",
            lambda event_code, *, outcome, fields: scene_events.append(
                (event_code, outcome, fields)
            ),
        )
        ports = FakeDomainPorts()
        registry = ActionRegistry()
        registry.register(AgentActionAdapter(ports))
        AdapterDispatchWorker(
            store=harness.store,
            registry=registry,
            ports=ports,
            successor_fn=lambda _node: ("protocol_design",),
            now_provider=lambda: FIXED_NOW_MS + 1_000,
        ).run_once()

        stage_events = [item for item in scene_events if item[0].startswith("stage_one_closeout.")]
        assert [item[0] for item in stage_events] == [
            "stage_one_closeout.started",
            "stage_one_closeout.blocked",
        ]
        assert stage_events[-1][2]["missingCategory"] == "program_review_required"
        assert "detail" not in stage_events[-1][2]
        assert not any(
            item.action_kind == "graph_dispatch"
            for item in harness.store.list_pending_outbox(action.run_id)
        )
    finally:
        harness.close()


def test_review_finalizer_enqueues_one_authoritative_ledger_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    action = _action()
    try:
        _seed(harness, action)
        _seed_stage_one_receipts(harness, action)
        payloads = _payloads(action.run_id)
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.stage_one_closeout._load_ledger_artifact_payload",
            lambda receipt: payloads[
                f"{receipt['artifactType']}:{receipt['artifactType']}-artifact"
            ],
        )
        approved = {
            "status": "idempotent",
            "workflowRunId": action.run_id,
            "questionId": "SCI-091",
            "recordId": f"SCI-091:{action.run_id}",
            "reviewStatus": "approved",
            "outputSha256": "e" * 64,
            "sourceResultPackageHash": "a" * 64,
            "resultPackage": {"canonicalHash": "b" * 64},
            "officialModelCall": True,
            "receiptStatus": "passed",
            "humanGates": {"allApproved": True, "approvedCount": 4},
        }
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime.program_candidate_handoff.handoff_result_package_to_challenge_program",
            lambda **_kwargs: approved,
        )
        outcome = evaluate_ledger_stage_one_closeout(
            harness.store,
            action=action,
            current_artifact_receipts=(),
        )
        assert outcome is not None and outcome.accepted
        harness.store.submit(
            lambda uow: uow.repository.update_attempt_status(
                action.node_run_id,
                "succeeded",
                FIXED_NOW_MS + 500,
                finished_at_ms=FIXED_NOW_MS + 500,
            ),
            force_flush=True,
        ).result(timeout=10)

        for _ in range(2):
            assert enqueue_ledger_stage_one_closeout(
                harness.store,
                workflow_run_id=action.run_id,
                outcome=outcome,
                idempotency_key="review-approved",
                completed_at_ms=FIXED_NOW_MS + 1_000,
            )

        pending = [
            item
            for item in harness.store.list_pending_outbox(action.run_id)
            if item.action_kind == "graph_dispatch"
        ]
        assert len(pending) == 1
        payload = json.loads(pending[0].payload_json)
        assert payload["stateUpdate"]["stage_one_completion_state"] == (
            "STAGE1_G1_ACCEPTED"
        )
        assert payload["receipt"]["actionId"] == action_id_for(
            action.run_id,
            action.node_id,
            action.attempt,
        )
    finally:
        harness.close()


def test_stage_one_terminal_facts_are_policy_and_marker_bound() -> None:
    run = _stage_one_run()

    assert stage_one_terminal_facts(
        run,
        node_id="hypothesis_design",
        state_update={"stage_one_completion_state": "STAGE1_G1_ACCEPTED"},
    ) == ("stage_one_g1_accepted", "STAGE1_G1_ACCEPTED")
    assert (
        stage_one_terminal_facts(
            run,
            node_id="hypothesis_design",
            state_update={},
        )
        is None
    )
    assert (
        stage_one_terminal_facts(
            run,
            node_id="protocol_design",
            state_update={"stage_one_completion_state": "STAGE1_G1_ACCEPTED"},
        )
        is None
    )
