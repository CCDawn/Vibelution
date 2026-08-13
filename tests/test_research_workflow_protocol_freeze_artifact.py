"""The protocol human gate must own one canonical frozen protocol artifact."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.web.services.team_workflow.research_runtime.command_service import (
    WorkflowCommandError,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from tests._support.command_helpers import CommandHarness
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)


def _seed_protocol_freeze_gate(
    harness: CommandHarness,
    *,
    historical_accept: bool = False,
) -> None:
    run = replace(
        build_run_record(
            last_event_sequence=1,
            status="blocked" if historical_accept else "running",
        ),
        active_node_id="smoke_gate" if historical_accept else "protocol_freeze",
        input_snapshot_json=json.dumps(
            {
                "snapshotHash": "a" * 64,
                "sourceCollectionRunId": "sc-run-1",
            }
        ),
        blocked_problem_json=(
            json.dumps({"code": "frozen_protocol_missing"})
            if historical_accept
            else None
        ),
    )
    freeze_attempt = replace(
        build_attempt_record(
            node_run_id="nr-run-test-protocol_freeze-a1",
            node_id="protocol_freeze",
            actor_kind="human",
            status="succeeded" if historical_accept else "waiting_human",
            command_id="cmd-freeze-a1",
        ),
        pending_action_id="act-protocol-freeze",
        finished_at_ms=FIXED_NOW_MS if historical_accept else None,
    )

    def mutate(uow):
        uow.repository.insert_run(run)
        uow.repository.insert_event(
            build_event_record(sequence=1, event_id="evt-created-run-test")
        )
        uow.repository.insert_command(
            build_command_record(
                command_id="cmd-freeze-a1",
                command_kind="start_node",
                node_id="protocol_freeze",
            )
        )
        uow.repository.insert_attempt(freeze_attempt)
        uow.repository.insert_handoff(
            handoff_id="ho-freeze-smoke",
            run_id="run-test",
            edge_id="e-freeze-smoke",
            from_node_run_id=freeze_attempt.node_run_id,
            to_node_id="smoke_gate",
            to_node_run_id=None,
            gate_kind="human",
            input_snapshot_hash="a" * 64,
            offered_at_ms=FIXED_NOW_MS,
        )
        uow.repository.update_handoff_status(
            "ho-freeze-smoke",
            "waiting_human",
            FIXED_NOW_MS,
        )
        if historical_accept:
            uow.repository.update_handoff_status(
                "ho-freeze-smoke",
                "accepted",
                FIXED_NOW_MS,
            )
        uow.repository.insert_human_task(
            task_id="ht-protocol-freeze",
            run_id="run-test",
            node_run_id=freeze_attempt.node_run_id,
            handoff_id="ho-freeze-smoke",
            task_kind="gate:protocol_freeze",
            prompt_json='{"nodeId":"protocol_freeze"}',
            created_at_ms=FIXED_NOW_MS,
        )
        if historical_accept:
            uow.repository.update_human_task_decision(
                "ht-protocol-freeze",
                "accepted",
                FIXED_NOW_MS,
                decision_json='{"decision":"accept"}',
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-smoke-a1",
                    command_kind="start_node",
                    node_id="smoke_gate",
                    idempotency_key="seed-smoke",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id="nr-run-test-smoke_gate-a1",
                    node_id="smoke_gate",
                    actor_kind="human",
                    status="blocked",
                    command_id="cmd-smoke-a1",
                    problem_json=json.dumps({"code": "frozen_protocol_missing"}),
                )
            )

    harness.store.submit(mutate, force_flush=True).result(timeout=10)


def _protocol_artifact(kind: str) -> dict[str, object] | None:
    if kind == "protocol_draft":
        return {
            "teamId": "research-team",
            "kind": kind,
            "workflowRunId": "run-test",
            "sourceCollectionRunId": "sc-run-1",
            "payload": {
                "planId": "exp-plan-1",
                "protocolId": "exp-plan-1",
                "dataset": "SCI-096",
                "metric": "score",
                "seed": [42, 2026],
                "status": "draft",
            },
        }
    if kind == "protocol_review_report":
        return {
            "teamId": "research-team",
            "kind": kind,
            "workflowRunId": "run-test",
            "sourceCollectionRunId": "sc-run-1",
            "payload": {
                "protocolId": "exp-plan-1",
                "status": "approved",
                "blocking_issue_count": 0,
                "open_waivers": 0,
                "checks": [{"checkId": "scope", "status": "pass"}],
            },
        }
    return None


def _install_protocol_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    writes: list[dict[str, object]] = []
    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "protocol_freeze_artifact.load_scoped_artifact_payload",
        lambda kind, **kwargs: _protocol_artifact(kind),
    )

    def capture_put(team_id: str, **kwargs):
        writes.append({"teamId": team_id, **kwargs})
        return {"recordId": kwargs["artifact_identity"], "payload": kwargs["payload"]}

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime."
        "protocol_freeze_artifact.put_workflow_artifact",
        capture_put,
    )
    return writes


def test_accept_materializes_and_binds_frozen_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_protocol_freeze_gate(harness)
        writes = _install_protocol_authority(monkeypatch)
        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                node_id="protocol_freeze",
                expected_run_version=1,
                idempotency_key="ui:accept-protocol-freeze",
                payload={"taskId": "ht-protocol-freeze", "decision": "accept"},
            )
        )

        assert receipt.status == "accepted"
        assert len(writes) == 1
        assert writes[0]["kind"] == "frozen_protocol"
        frozen = writes[0]["payload"]
        assert isinstance(frozen, dict)
        assert frozen["status"] == "frozen"
        assert frozen["decision"] == "accept"
        assert frozen["protocolId"] == "exp-plan-1"
        assert frozen["planId"] == "exp-plan-1"
        assert frozen["resolvedBy"] == "u-1"
        assert frozen["protocolDraftHash"] == canonical_sha256(
            _protocol_artifact("protocol_draft")
        )
        assert frozen["protocolReviewHash"] == canonical_sha256(
            _protocol_artifact("protocol_review_report")
        )
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert len(refs) == 1
        assert refs[0][0] == "ho-freeze-smoke"
        assert refs[0][2] == "frozen_protocol"
        graph_payload = next(
            json.loads(item.payload_json)
            for item in harness.store.read(
                lambda repo: repo.list_pending_outbox("run-test", 20)
            )
            if item.action_kind == "graph_dispatch"
        )
        assert graph_payload["receipt"]["artifactReceiptIds"] == [refs[0][1]]
    finally:
        harness.close()


def test_unapproved_review_fails_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_protocol_freeze_gate(harness)
        writes = _install_protocol_authority(monkeypatch)
        unapproved = _protocol_artifact("protocol_review_report")
        assert isinstance(unapproved, dict)
        review_payload = unapproved["payload"]
        assert isinstance(review_payload, dict)
        review_payload["status"] = "changes_requested"
        monkeypatch.setattr(
            "core.web.services.team_workflow.research_runtime."
            "protocol_freeze_artifact.load_scoped_artifact_payload",
            lambda kind, **kwargs: (
                unapproved if kind == "protocol_review_report" else _protocol_artifact(kind)
            ),
        )

        with pytest.raises(WorkflowCommandError, match="protocol_review_not_approved"):
            harness.service.submit(
                harness.request(
                    command=WorkflowCommandKind.RESOLVE_HUMAN_TASK,
                    node_id="protocol_freeze",
                    expected_run_version=1,
                    idempotency_key="ui:accept-unapproved-protocol",
                    payload={"taskId": "ht-protocol-freeze", "decision": "accept"},
                )
            )

        assert writes == []
        task = harness.store.read(
            lambda repo: repo.get_human_task("ht-protocol-freeze")
        )
        assert task is not None and task[6] == "pending"
        assert harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        ) == []
    finally:
        harness.close()


def test_reconcile_backfills_historical_protocol_freeze_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_protocol_freeze_gate(harness, historical_accept=True)
        writes = _install_protocol_authority(monkeypatch)
        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RECONCILE_RUN,
                node_id="smoke_gate",
                expected_run_version=1,
                idempotency_key="ui:reconcile-frozen-protocol",
            )
        )

        assert receipt.status == "accepted"
        assert len(writes) == 1 and writes[0]["kind"] == "frozen_protocol"
        run = harness.store.get_run("run-test")
        assert run is not None and run.status == "running"
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert len(refs) == 1
        assert refs[0][0] == "ho-freeze-smoke"
        assert refs[0][2] == "frozen_protocol"
    finally:
        harness.close()


def test_visible_smoke_retry_backfills_historical_frozen_protocol(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        _seed_protocol_freeze_gate(harness, historical_accept=True)
        writes = _install_protocol_authority(monkeypatch)

        receipt = harness.service.submit(
            harness.request(
                command=WorkflowCommandKind.RETRY_NODE,
                node_id="smoke_gate",
                expected_run_version=1,
                idempotency_key="ui:retry-smoke-with-frozen-protocol",
            )
        )

        assert receipt.status == "accepted"
        assert len(writes) == 1 and writes[0]["kind"] == "frozen_protocol"
        refs = harness.store.read(
            lambda repo: repo.list_handoff_artifact_refs_for_run("run-test")
        )
        assert len(refs) == 1 and refs[0][2] == "frozen_protocol"
        latest = harness.store.latest_attempt("run-test", "smoke_gate")
        assert latest is not None and latest.attempt == 2
        assert latest.status == "starting"
    finally:
        harness.close()
