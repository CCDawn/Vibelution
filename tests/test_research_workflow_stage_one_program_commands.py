"""Stage-one G1 closeout operator commands on the ledger command service.

The two commands are first-class ledger WorkflowCommandService commands (the
legacy file-store ``apply_node_command`` path stays untouched and keeps its
own coverage).  These tests pin:

* build: artifact receipt + ``stage_one_package_registered`` event + Challenge
  Program registration + idempotent replay with zero side effects;
* finalize: fail-closed Program gates, terminal run facts, completion
  manifest receipt and the two checkpoint-sync branches (live interrupt ->
  authoritative resume dispatch; thread already END -> direct checkpoint
  state write);
* the operator gate and the thin HTTP facade wiring (team scope, runVersion
  CAS, error mapping).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.research.workflow.challenge_cup_runtime import ChallengeCupGraphCoordinator
from core.research.workflow.contracts import WorkflowCommandKind
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes.team_workflows import research_runtime as research_runtime_module
from core.web.services.team_workflow.research_runtime import (
    artifact_readback_registry,
    operator_authorization,
    program_candidate_handoff,
    result_package_system_adapter,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime import (
    stage_one_closeout as stage_one_closeout_module,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
    StageOneCommandError,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    configure_formal_write_runtime,
    reset_formal_write_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    ServerOperatorContext,
    server_operator_scope,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
)
from tests.test_research_workflow_ledger_stage_one_closeout import (
    _current_receipts,
    _stage_one_run,
)
from tests.test_research_workflow_stage_one_closeout import _payloads

TEAM_ID = "challenge-stage-one-team"
RUN_ID = "run-stage-one"
CLOSURE_NODE = "hypothesis_design"
CONTROL = {CONTROL_TOKEN_HEADER: get_control_token()}


# --------------------------------------------------------------- fixtures


def _seed(harness: CommandHarness) -> None:
    run = dataclasses.replace(_stage_one_run(RUN_ID), status="waiting_human")

    def mutate(uow) -> None:
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(1, run_id=RUN_ID, event_id=f"evt-created-{RUN_ID}")
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-stage-one",
                run_id=RUN_ID,
                team_id=TEAM_ID,
                node_id=CLOSURE_NODE,
            )
        )
        uow.repository.insert_attempt(
            build_attempt_record(
                node_run_id=f"nr-{RUN_ID}-{CLOSURE_NODE}-a1",
                run_id=RUN_ID,
                node_id=CLOSURE_NODE,
                status="succeeded",
                command_id="cmd-stage-one",
            )
        )
        for index, receipt in enumerate(_current_receipts(RUN_ID)):
            uow.repository.insert_artifact_receipt(
                receipt_id=f"seed-stage-one-{index}",
                run_id=RUN_ID,
                node_run_id=f"nr-{RUN_ID}-{CLOSURE_NODE}-a1",
                team_id=TEAM_ID,
                artifact_kind=receipt["artifactType"],
                canonical_ref_json=json.dumps({"canonicalRef": receipt["canonicalRef"]}),
                artifact_version=receipt["version"],
                sha256=receipt["sha256"],
                domain_revision=receipt["domainRevision"],
                materialized=1,
                verified_at_ms=FIXED_NOW_MS,
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _patch_domain(monkeypatch: pytest.MonkeyPatch, *, handoff: Any = None):
    """Patch the idempotent domain IO behind the command service.

    Returns ``(handoff_calls, artifact_puts)`` recorders.  ``handoff`` may be
    a dict (returned verbatim) or a zero-arg callable.
    """
    payloads = _payloads(RUN_ID)
    monkeypatch.setattr(
        stage_one_closeout_module,
        "_load_ledger_artifact_payload",
        lambda receipt: payloads[
            f"{receipt['artifactType']}:{receipt['artifactType']}-artifact"
        ],
    )
    monkeypatch.setattr(
        artifact_readback_registry,
        "load_scoped_artifact_payload",
        lambda *_args, **_kwargs: {"payload": {"objective": "bounded plan"}},
    )
    puts: list[dict[str, Any]] = []

    def _put(team_id, *, kind, workflow_run_id, payload, source_collection_run_id="", artifact_identity=""):
        puts.append(
            {
                "teamId": team_id,
                "kind": kind,
                "workflowRunId": workflow_run_id,
                "sourceCollectionRunId": source_collection_run_id,
                "artifactIdentity": artifact_identity,
                "payload": payload,
            }
        )
        return {"recordId": artifact_identity, "contentHash": "0" * 64}

    monkeypatch.setattr(workflow_artifact_store, "put_workflow_artifact", _put)

    package = {
        "packageId": "rrp-v2:stage-one",
        "factChainHash": "f" * 64,
        "contentHash": "c" * 64,
    }
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_proposal_result_package_base",
        lambda _record: {"factChainHash": "f" * 64},
    )
    monkeypatch.setattr(
        result_package_system_adapter,
        "build_challenge_result_package_v2",
        lambda **_kwargs: dict(package),
    )

    handoff_calls: list[dict[str, Any]] = []
    default_handoff = {
        "status": "registered",
        "reviewStatus": "review_required",
        "workflowRunId": RUN_ID,
        "questionId": "SCI-091",
        "recordId": f"SCI-091:{RUN_ID}",
        "sourceResultPackageHash": "a" * 64,
        "outputSha256": "d" * 64,
    }
    selected = default_handoff if handoff is None else handoff

    def _handoff(**kwargs):
        handoff_calls.append(kwargs)
        return dict(selected) if isinstance(selected, dict) else selected()

    monkeypatch.setattr(
        program_candidate_handoff,
        "handoff_result_package_to_challenge_program",
        _handoff,
    )
    return handoff_calls, puts


def _submit(harness: CommandHarness, request: Any) -> Any:
    # requestedBy carries the display actor "u-1"; the server scope must agree.
    with server_operator_scope("u-1", roles=("operator", "admin")):
        return harness.command_service.submit(request)


def _request(
    harness: CommandHarness,
    *,
    command: WorkflowCommandKind,
    key: str,
    expected_version: int = 1,
    node_id: str | None = None,
) -> Any:
    return harness.request(
        command=command,
        node_id=node_id,
        run_id=RUN_ID,
        team_id=TEAM_ID,
        expected_run_version=expected_version,
        idempotency_key=key,
        payload={},
    )


def _approved_handoff() -> dict[str, Any]:
    return {
        "status": "idempotent",
        "workflowRunId": RUN_ID,
        "questionId": "SCI-091",
        "recordId": f"SCI-091:{RUN_ID}",
        "reviewStatus": "approved",
        "outputSha256": "e" * 64,
        "sourceResultPackageHash": "a" * 64,
        "resultPackage": {"canonicalHash": "b" * 64},
        "officialModelCall": True,
        "receiptStatus": "passed",
        "humanGates": {"allApproved": True, "approvedCount": 4},
    }


class _RecordingCoordinator:
    """Coordinator double: ``pending`` decides which sync branch is live."""

    def __init__(self, *, pending: bool) -> None:
        self._pending = pending
        self.snapshots = 0
        self.updates: list[tuple[str, str, dict[str, Any]]] = []

    def snapshot(self, run_id: str, workflow_version_id: str = "") -> dict[str, Any]:
        self.snapshots += 1
        return {
            "checkpointId": "cp-1",
            "nextNodeIds": [CLOSURE_NODE] if self._pending else [],
            "values": {},
            "pendingAction": (
                {"actionId": "act-x", "nodeId": CLOSURE_NODE, "runId": run_id}
                if self._pending
                else None
            ),
        }

    def apply_state_update(
        self, run_id: str, workflow_version_id: str = "", update: Any = None
    ) -> str:
        self.updates.append((run_id, workflow_version_id, dict(update or {})))
        return "cp-2"


def _bind_coordinator(harness: CommandHarness, coordinator: Any) -> None:
    harness.command_service._coordinator_factory = lambda: coordinator


# ------------------------------------------------------------ build tests


def test_build_registers_receipt_event_and_program_record(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        handoff_calls, puts = _patch_domain(monkeypatch)

        receipt = _submit(harness, _request(harness, command=WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE, key="stage-one-build"))

        assert receipt.status == "accepted"
        assert receipt.accepted_run_version == 2
        result = dict(receipt.result or {})
        assert result["idempotent"] is False
        assert result["packageId"] == "rrp-v2:stage-one"
        assert result["programRecordId"] == f"SCI-091:{RUN_ID}"
        assert result["programReviewStatus"] == "review_required"
        assert result["artifactRef"].startswith("research_result_package://")

        rows = harness.store.read(
            lambda repo: repo.list_artifact_receipts_for_run(RUN_ID)
        )
        package_rows = [row for row in rows if str(row[4]) == "research_result_package"]
        assert len(package_rows) == 1
        assert json.loads(str(package_rows[0][5]))["canonicalRef"] == result["artifactRef"]
        events = harness.store.list_events(RUN_ID)
        registered = [
            item for item in events if item.event_type == "stage_one_package_registered"
        ]
        assert len(registered) == 1
        assert json.loads(str(registered[0].payload_json))["result"]["packageId"] == (
            "rrp-v2:stage-one"
        )
        assert [item["kind"] for item in puts] == [
            "research_plan",
            "research_result_package",
        ]
        assert handoff_calls[0]["registered_by"] == "stage_one_command_service"
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 2
        assert run.status == "waiting_human"
    finally:
        harness.close()


def test_build_replay_is_zero_side_effect(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch)
        first = _submit(harness, _request(harness, command=WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE, key="stage-one-build"))
        assert first.result["idempotent"] is False

        events_before = len(harness.store.list_events(RUN_ID))
        rows_before = len(
            harness.store.read(lambda repo: repo.list_artifact_receipts_for_run(RUN_ID))
        )

        # New idempotency key against the same run: the canonical package
        # receipt replays the registered facts with zero side effects.
        replay = _submit(
            harness,
            _request(
                harness,
                command=WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE,
                key="stage-one-build-2",
                expected_version=2,
            ),
        )
        assert replay.status == "accepted"
        assert replay.result["replayed"] is True
        assert replay.result["idempotent"] is True
        assert replay.result["packageId"] == "rrp-v2:stage-one"
        assert replay.accepted_run_version == 2
        assert len(harness.store.list_events(RUN_ID)) == events_before
        assert (
            len(harness.store.read(lambda repo: repo.list_artifact_receipts_for_run(RUN_ID)))
            == rows_before
        )
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 2

        # Same-key replay goes through the command idempotency lookup and
        # carries the original result payload.
        same_key = _submit(
            harness,
            _request(harness, command=WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE, key="stage-one-build"),
        )
        assert same_key.status == "accepted"
        assert same_key.result["packageId"] == "rrp-v2:stage-one"
    finally:
        harness.close()


def test_build_maps_missing_program_record_to_typed_conflict(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(
            monkeypatch,
            handoff={"status": "NEEDS_CONTEXT", "reason": "no canonical package"},
        )
        with pytest.raises(StageOneCommandError) as exc:
            _submit(harness, _request(harness, command=WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE, key="stage-one-build"))
        assert exc.value.code == "stage_one_result_package_missing"
        rows = harness.store.read(
            lambda repo: repo.list_artifact_receipts_for_run(RUN_ID)
        )
        assert not [row for row in rows if str(row[4]) == "research_result_package"]
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 1
    finally:
        harness.close()


# --------------------------------------------------------- finalize tests


def test_finalize_requires_registered_package(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(
            monkeypatch,
            handoff={"status": "NEEDS_CONTEXT", "reason": "not registered"},
        )
        with pytest.raises(StageOneCommandError) as exc:
            _submit(harness, _request(harness, command=WorkflowCommandKind.FINALIZE_STAGE_ONE, key="stage-one-finalize"))
        assert exc.value.code == "stage_one_result_package_missing"
        run = harness.store.get_run(RUN_ID)
        assert run is not None
        assert run.status == "waiting_human"
        assert run.run_version == 1
    finally:
        harness.close()


def test_finalize_requires_approved_program_review(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch)  # review_required registration
        with pytest.raises(StageOneCommandError) as exc:
            _submit(harness, _request(harness, command=WorkflowCommandKind.FINALIZE_STAGE_ONE, key="stage-one-finalize"))
        assert exc.value.code == "stage_one_program_review_not_approved"
        run = harness.store.get_run(RUN_ID)
        assert run is not None
        assert run.status == "waiting_human"
        assert not run.completion_kind
    finally:
        harness.close()


def test_finalize_with_live_interrupt_enqueues_resume_dispatch(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch, handoff=_approved_handoff())
        coordinator = _RecordingCoordinator(pending=True)
        _bind_coordinator(harness, coordinator)

        receipt = _submit(harness, _request(harness, command=WorkflowCommandKind.FINALIZE_STAGE_ONE, key="stage-one-finalize"))

        assert receipt.status == "accepted"
        assert receipt.result["completionState"] == "STAGE1_G1_ACCEPTED"
        run = harness.store.get_run(RUN_ID)
        assert run is not None
        assert run.status == "succeeded"
        assert run.completion_kind == "stage_one_g1_accepted"
        assert run.terminal_reason == "STAGE1_G1_ACCEPTED"
        rows = harness.store.read(
            lambda repo: repo.list_artifact_receipts_for_run(RUN_ID)
        )
        assert [str(row[4]) for row in rows].count("stage_one_completion_manifest") == 1
        events = harness.store.list_events(RUN_ID)
        assert any(
            item.event_type == "stage_one_closeout_completed" for item in events
        )
        pending = [
            item
            for item in harness.store.list_pending_outbox(RUN_ID)
            if item.action_kind == "graph_dispatch"
        ]
        assert len(pending) == 1
        payload = json.loads(pending[0].payload_json)
        assert payload["dispatchKind"] == "resume_action"
        assert payload["stateUpdate"]["stage_one_completion_state"] == "STAGE1_G1_ACCEPTED"
        assert payload["stateUpdate"]["stage_one_closeout"]["accepted"] is True
        assert coordinator.updates == []
        assert harness.wake_count >= 1
    finally:
        harness.close()


def test_finalize_without_interrupt_writes_checkpoint_state_directly(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch, handoff=_approved_handoff())
        coordinator = _RecordingCoordinator(pending=False)
        _bind_coordinator(harness, coordinator)

        receipt = _submit(harness, _request(harness, command=WorkflowCommandKind.FINALIZE_STAGE_ONE, key="stage-one-finalize"))

        assert receipt.status == "accepted"
        run = harness.store.get_run(RUN_ID)
        assert run is not None
        assert run.status == "succeeded"
        assert run.completion_kind == "stage_one_g1_accepted"
        assert coordinator.snapshots == 1
        assert len(coordinator.updates) == 1
        update_run_id, update_version, update = coordinator.updates[0]
        assert update_run_id == RUN_ID
        assert update_version == run.workflow_version_id
        assert update["stage_one_completion_state"] == "STAGE1_G1_ACCEPTED"
        assert update["stage_one_closeout"]["accepted"] is True
        assert not [
            item
            for item in harness.store.list_pending_outbox(RUN_ID)
            if item.action_kind == "graph_dispatch"
        ]
    finally:
        harness.close()


def test_finalize_is_noop_after_acceptance(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch, handoff=_approved_handoff())
        _bind_coordinator(harness, _RecordingCoordinator(pending=False))
        first = _submit(harness, _request(harness, command=WorkflowCommandKind.FINALIZE_STAGE_ONE, key="stage-one-finalize"))
        assert first.result.get("replayed") is None

        events_before = len(harness.store.list_events(RUN_ID))
        second = _submit(
            harness,
            _request(
                harness,
                command=WorkflowCommandKind.FINALIZE_STAGE_ONE,
                key="stage-one-finalize-2",
                expected_version=2,
            ),
        )
        assert second.status == "accepted"
        assert second.result["replayed"] is True
        assert second.result["idempotent"] is True
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 2
        assert len(harness.store.list_events(RUN_ID)) == events_before
    finally:
        harness.close()


def test_stage_one_commands_require_privileged_operator(tmp_path, monkeypatch) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed(harness)
        _patch_domain(monkeypatch)
        for command in (
            WorkflowCommandKind.BUILD_STAGE_ONE_PACKAGE,
            WorkflowCommandKind.FINALIZE_STAGE_ONE,
        ):
            with (
                server_operator_scope("op-viewer", roles=("viewer",)),
                pytest.raises(CommandForbiddenError),
            ):
                harness.command_service.submit(
                    _request(harness, command=command, key=f"gate-{command.value}")
                )
            with pytest.raises(CommandForbiddenError):
                # No server operator bound at all: never self-declared.
                harness.command_service.submit(
                    _request(harness, command=command, key=f"anon-{command.value}")
                )
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 1
    finally:
        harness.close()


# ------------------------------------------------- real checkpoint write


def test_real_coordinator_direct_write_lands_marker_in_checkpoint(tmp_path) -> None:
    coordinator = ChallengeCupGraphCoordinator(tmp_path / "checkpoints.sqlite3")
    checkpoint_id = coordinator.apply_state_update(
        RUN_ID,
        "",
        {
            "stage_one_completion_state": "STAGE1_G1_ACCEPTED",
            "stage_one_closeout": {"status": "accepted", "accepted": True},
        },
    )
    snapshot = coordinator.snapshot(RUN_ID, "")
    assert snapshot["values"]["stage_one_completion_state"] == "STAGE1_G1_ACCEPTED"
    assert snapshot["values"]["stage_one_closeout"]["accepted"] is True
    assert snapshot["pendingAction"] is None
    assert isinstance(checkpoint_id, str)


# ------------------------------------------------------- facade route


def _route_client(tmp_path: Path) -> CommandHarness:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    _seed(harness)
    reset_formal_write_runtime_for_tests()
    configure_formal_write_runtime(
        store=harness.store, command_service=harness.command_service
    )
    return harness


def _post(client: TestClient, body: dict[str, Any]):
    return client.post(
        f"/api/research/workflow-runs/{RUN_ID}/stage-one/commands",
        headers=CONTROL,
        json=body,
    )


def test_stage_one_facade_route_submits_ledger_commands(tmp_path, monkeypatch) -> None:
    harness = _route_client(tmp_path)
    try:
        handoff_calls, _puts = _patch_domain(monkeypatch)
        app = FastAPI()
        app.include_router(research_runtime_module.router, prefix="/api")
        client = TestClient(app)

        body = {
            "teamId": TEAM_ID,
            "command": "build_stage_one_package",
            "expectedRunVersion": 1,
            "idempotencyKey": "stage-one-route-build",
            "nodeId": "",
            "payload": {},
        }
        first = _post(client, body)
        assert first.status_code == 200, first.text
        payload = first.json()
        assert payload["status"] == "accepted"
        assert payload["result"]["packageId"] == "rrp-v2:stage-one"

        stale = _post(
            client,
            {
                **body,
                "idempotencyKey": "stage-one-route-build-stale",
                "expectedRunVersion": 99,
            },
        )
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "run_version_conflict"

        wrong_team = _post(
            client, {**body, "idempotencyKey": "stage-one-route-build-team", "teamId": "another-team"}
        )
        assert wrong_team.status_code == 404, wrong_team.text
        assert wrong_team.json()["detail"]["code"] == "team_scope_mismatch"

        unknown_run = client.post(
            "/api/research/workflow-runs/run-absent/stage-one/commands",
            headers=CONTROL,
            json={**body, "idempotencyKey": "stage-one-route-build-absent"},
        )
        assert unknown_run.status_code == 404, unknown_run.text
        assert unknown_run.json()["detail"]["code"] == "run_not_found"

        finalize_body = {
            "teamId": TEAM_ID,
            "command": "finalize_stage_one",
            "expectedRunVersion": 2,
            "idempotencyKey": "stage-one-route-finalize",
            "payload": {},
        }
        not_approved = _post(client, finalize_body)
        assert not_approved.status_code == 409, not_approved.text
        assert (
            not_approved.json()["detail"]["code"]
            == "stage_one_program_review_not_approved"
        )
        assert handoff_calls[-1]["registered_by"] == "stage_one_closeout_finalizer"
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.status == "waiting_human"
    finally:
        reset_formal_write_runtime_for_tests()
        harness.close()


def test_stage_one_facade_route_requires_privileged_operator(
    tmp_path, monkeypatch
) -> None:
    harness = _route_client(tmp_path)
    try:
        _patch_domain(monkeypatch)
        monkeypatch.setattr(
            operator_authorization,
            "local_control_operator",
            lambda: ServerOperatorContext(
                operator_id="weak-operator", display_name="weak", roles=("viewer",)
            ),
        )
        app = FastAPI()
        app.include_router(research_runtime_module.router, prefix="/api")
        response = _post(
            TestClient(app),
            {
                "teamId": TEAM_ID,
                "command": "build_stage_one_package",
                "expectedRunVersion": 1,
                "idempotencyKey": "stage-one-route-forbidden",
                "payload": {},
            },
        )
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == "command_forbidden"
        run = harness.store.get_run(RUN_ID)
        assert run is not None and run.run_version == 1
    finally:
        reset_formal_write_runtime_for_tests()
        harness.close()
