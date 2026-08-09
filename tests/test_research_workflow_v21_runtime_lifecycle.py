"""T2 lifecycle contracts: create is durable preparation, never execution."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
    reset_research_workflow_runtime_service_for_tests,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

SOURCE_BINDING = AgentBindingLayers(
    workflowDefaults={"source_finder": "agent-source-finder"}
)


def run_input_request(*, team_id: str = "acceptance-research-team") -> dict:
    return {
        "teamId": team_id,
        "projectId": "acceptance-energy-anomaly-project",
        "questionId": "question-energy-anomaly-gate-v1",
        "researchBriefHash": "7d6fced411fcc0e33a40ca2186a08f4d0d744ab5c7b6851bb4746bb373e3bd2a",
        "datasetRefs": ["fixture://challenge-cup/energy-anomaly-v1"],
        "metricContract": {
            "primary": "invalid_iteration_rate",
            "direction": "minimize",
        },
        "constraintSnapshot": {"formalWrites": False},
        "competitionRuleRef": "fixture://challenge-cup/rules-v1",
        "competitionRuleVersion": "fixture-2026-08-09",
        "trackAndRubricSnapshot": {
            "track": "科技发明制作类",
            "blockingRules": ["claim_without_evidence"],
        },
        "researchObjectiveContract": {
            "question": "稀疏重构误差门控能否降低无效迭代？",
            "falsifiableOutcome": "无效迭代率未下降",
        },
        "sourcePolicy": {"minimumPrimarySources": 3, "requireCounterEvidence": True},
        "budgetPolicy": {
            "tokens": 100000,
            "toolCalls": 120,
            "wallClockSeconds": 14400,
            "experiments": 12,
            "computeUnits": 100,
            "maxParallelTasks": 3,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2, "stopOnBudgetExhaustion": True},
        "environmentSnapshotRef": "fixture://challenge-cup/environment-v1",
        "modelRoutingPolicy": {
            "reasoning": "fixture-strong-model",
            "extraction": "fixture-light-model",
        },
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11, 29, 47],
        },
        "createdBy": "acceptance-fixture",
    }


def _service(tmp_path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )


def test_create_run_freezes_input_and_only_prepares_first_node(tmp_path: Path) -> None:
    service = _service(tmp_path)

    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        idempotency_key="create-v21-1",
    )

    assert run["status"] == "queued"
    assert run["teamId"] == "acceptance-research-team"
    assert run["projectId"] == "acceptance-energy-anomaly-project"
    assert run["questionId"] == "question-energy-anomaly-gate-v1"
    assert run["inputSnapshot"]["snapshotHash"]
    assert run["inputSnapshot"]["workflowVersionId"] == run["workflowVersionId"]
    assert run["runtimeCurrentNodeIds"] == ["source_finding"]
    assert run["completedNodeIds"] == []
    assert run["humanTasks"] == []
    assert run["handoffs"] == []
    assert run["artifactManifests"] == []
    assert len(run["nodeRuns"]) == 1
    assert {
        key: run["nodeRuns"][0][key]
        for key in ("nodeId", "attempt", "status", "actorType")
    } == {
        "nodeId": "source_finding",
        "attempt": 1,
        "status": "ready",
        "actorType": "agent",
    }
    assert "hash:" not in str(run)


def test_create_run_rejects_incomplete_input_without_writing(tmp_path: Path) -> None:
    service = _service(tmp_path)
    incomplete = run_input_request()
    incomplete.pop("evaluationContract")

    with pytest.raises(ResearchWorkflowError) as exc:
        service.create_run(CHALLENGE_CUP_WORKFLOW_ID, run_input=incomplete)

    assert exc.value.code == "invalid_run_input"
    assert service.list_runs(CHALLENGE_CUP_WORKFLOW_ID, team_id="acceptance-research-team")["runs"] == []


def test_canvas_projection_uses_real_node_runs_not_legacy_attempt_counters(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        binding_layers=SOURCE_BINDING,
    )

    canvas = service.get_canvas_projection(run["runId"])

    assert canvas["run"]["runtimeCurrentNodeIds"] == ["source_finding"]
    assert canvas["run"]["nodeRuns"]["source_finding"]["status"] == "ready"
    assert (
        canvas["run"]["nodeRuns"]["source_finding"]["nodeRunId"]
        == run["nodeRuns"][0]["nodeRunId"]
    )


def test_create_run_idempotency_and_restart_preserve_same_initial_facts(tmp_path: Path) -> None:
    first_service = _service(tmp_path)
    first = first_service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        idempotency_key="create-v21-stable",
    )
    again = first_service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        idempotency_key="create-v21-stable",
    )
    reopened = _service(tmp_path).get_run(first["runId"])

    assert again["runId"] == first["runId"]
    assert reopened["nodeRuns"] == first["nodeRuns"]
    assert reopened["inputSnapshot"] == first["inputSnapshot"]
    assert reopened["events"] == first["events"]


def test_http_create_requires_full_frozen_input_contract(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    reset_research_workflow_runtime_service_for_tests(
        run_store=store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    rejected = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={"teamId": "acceptance-research-team"},
    )
    accepted = client.post(
        f"/api/research/workflows/{CHALLENGE_CUP_WORKFLOW_ID}/runs",
        json={
            **run_input_request(),
            "createdBy": "spoofed-client-identity",
            "idempotencyKey": "http-v21-1",
        },
    )

    assert rejected.status_code == 422
    assert accepted.status_code == 201
    assert accepted.json()["nodeRuns"][0]["status"] == "ready"
    assert accepted.json()["inputSnapshot"]["createdBy"] == "operator"


def test_node_start_uses_one_durable_lease_and_rejects_owner_mismatch(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        binding_layers=SOURCE_BINDING,
        idempotency_key="lease-run",
    )

    started = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "start-source-1",
            "leaseOwner": "worker-1",
            "leaseSeconds": 60,
            "deadlineSeconds": 900,
        },
    )
    repeated = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "start-source-1",
            "leaseOwner": "worker-1",
            "leaseSeconds": 60,
            "deadlineSeconds": 900,
        },
    )

    assert len(started["taskLeases"]) == 1
    assert len(repeated["taskLeases"]) == 1
    assert started["nodeRuns"][0]["status"] == "running"
    assert started["status"] == "running"
    assert repeated["taskLeases"][0]["idempotencyKey"] == "start-source-1"

    detail = service.get_node_detail(run["runId"], "source_finding")
    assert detail["executionEnvelope"]["nodeRunId"] == started["nodeRuns"][0]["nodeRunId"]
    assert detail["taskLease"]["leaseOwner"] == "worker-1"
    assert detail["qualityGateEvaluation"] is None
    assert detail["artifactManifests"] == []
    assert detail["artifactReuseCount"] == 0

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "source_finding",
            "heartbeat_execution",
            payload={
                "idempotencyKey": "heartbeat-owner-mismatch",
                "leaseOwner": "worker-other",
                "leaseSeconds": 60,
            },
        )
    assert exc.value.code == "lease_owner_mismatch"


def test_node_completion_records_real_artifact_receipt_handoff_and_next_ready_node(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        binding_layers=SOURCE_BINDING,
        idempotency_key="complete-run",
    )
    started = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "start-source-complete",
            "leaseOwner": "worker-1",
            "leaseSeconds": 60,
            "deadlineSeconds": 900,
        },
    )
    node_run = started["nodeRuns"][0]
    manifest = {
        "artifactId": "source_candidate_batch:fixture:1",
        "contentHash": "a" * 64,
        "schemaVersion": "1",
        "producerNodeRunId": node_run["nodeRunId"],
        "producerAttempt": 1,
        "inputSnapshotHash": node_run["inputSnapshotHash"],
        "configHash": "b" * 64,
        "environmentSnapshotHash": "c" * 64,
        "toolVersionHash": "d" * 64,
        "sourceArtifactIds": [],
        "cacheDisposition": "produced",
        "createdAt": "2026-08-09T09:00:00Z",
    }
    artifact_payloads = {
        manifest["artifactId"]: {
            "perspectives": ["技术路线", "可验证性"],
            "queries": ["predictive coding evidence", "challenge cup baseline"],
            "candidateSources": [
                {"sourceId": "source-1", "url": "https://example.test/source-1"}
            ],
        }
    }

    completed = service.apply_node_command(
        run["runId"],
        "source_finding",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-source-1",
            "leaseOwner": "worker-1",
            "artifactManifests": [manifest],
            "artifactPayloads": artifact_payloads,
        },
    )
    repeated = service.apply_node_command(
        run["runId"],
        "source_finding",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-source-1",
            "leaseOwner": "worker-1",
            "artifactManifests": [manifest],
            "artifactPayloads": artifact_payloads,
        },
    )

    by_node = {item["nodeId"]: item for item in completed["nodeRuns"]}
    assert by_node["source_finding"]["status"] == "succeeded"
    assert by_node["source_extraction"]["status"] == "ready"
    assert completed["runtimeCurrentNodeIds"] == ["source_extraction"]
    assert len(completed["artifactManifests"]) == 1
    assert len(completed["commandReceipts"]) == 1
    assert len(completed["outbox"]) == 1
    assert len(completed["handoffs"]) == 1
    assert completed["qualityGateEvaluations"][0]["status"] == "passed"
    assert completed["handoffs"][0]["outputArtifactRefs"][0]["contentHash"] == "a" * 64
    assert repeated["commandReceipts"] == completed["commandReceipts"]
    assert repeated["handoffs"] == completed["handoffs"]
    assert "hash:" not in str(completed)


def test_node_completion_rejects_placeholder_artifact(tmp_path: Path) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        binding_layers=SOURCE_BINDING,
    )
    started = service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "start-invalid-artifact",
            "leaseOwner": "worker-1",
            "leaseSeconds": 60,
            "deadlineSeconds": 900,
        },
    )
    node_run = started["nodeRuns"][0]

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "source_finding",
            "complete_execution",
            payload={
                "idempotencyKey": "complete-invalid-artifact",
                "leaseOwner": "worker-1",
                "artifactManifests": [
                    {
                        "artifactId": "source_candidate_batch:fixture:bad",
                        "contentHash": "hash:placeholder",
                        "schemaVersion": "1",
                        "producerNodeRunId": node_run["nodeRunId"],
                        "producerAttempt": 1,
                        "inputSnapshotHash": node_run["inputSnapshotHash"],
                        "configHash": "b" * 64,
                        "environmentSnapshotHash": "c" * 64,
                        "toolVersionHash": "d" * 64,
                        "sourceArtifactIds": [],
                        "cacheDisposition": "produced",
                        "createdAt": "2026-08-09T09:00:00Z",
                    }
                ],
            },
        )
    assert exc.value.code == "invalid_artifact"


def test_expired_lease_is_diagnosed_and_retry_creates_new_attempt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=run_input_request(),
        binding_layers=SOURCE_BINDING,
        idempotency_key="stuck-run",
    )
    service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_execution",
        payload={
            "idempotencyKey": "start-stuck-source",
            "leaseOwner": "worker-stuck",
            "leaseSeconds": 1,
            "deadlineSeconds": 60,
        },
    )

    stuck = service.apply_node_command(
        run["runId"],
        "source_finding",
        "reconcile_execution",
        payload={"observedAt": "2100-01-01T00:00:00Z"},
    )
    retried = service.apply_node_command(
        run["runId"],
        "source_finding",
        "retry_execution",
        payload={"idempotencyKey": "retry-stuck-source"},
    )
    repeated = service.apply_node_command(
        run["runId"],
        "source_finding",
        "retry_execution",
        payload={"idempotencyKey": "retry-stuck-source"},
    )

    assert stuck["status"] == "blocked"
    assert stuck["blockedReason"] == "lease_expired"
    assert stuck["taskLeases"][0]["status"] == "stuck"
    assert stuck["nodeRuns"][0]["status"] == "blocked"
    assert [item["attempt"] for item in retried["nodeRuns"]] == [1, 2]
    assert retried["nodeRuns"][-1]["status"] == "ready"
    assert retried["nodeRuns"][-1]["supersedesNodeRunId"] == retried["nodeRuns"][0]["nodeRunId"]
    assert repeated["nodeRuns"] == retried["nodeRuns"]
