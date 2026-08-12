"""T5/T6 contracts for decision routing, revision forks and governance."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


@pytest.fixture(autouse=True)
def _bind_server_operator(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    with server_operator_scope("test-operator", roles=("operator",)):
        yield


def _input() -> dict[str, Any]:
    return {
        "teamId": "team-iteration",
        "projectId": "project-iteration",
        "questionId": "question-iteration",
        "researchBriefHash": "1" * 64,
        "datasetRefs": ["fixture://dataset/iteration"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "迭代是否可恢复？"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
            "experiments": 3,
            "computeUnits": 20,
            "maxParallelTasks": 2,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "fixture://environment/iteration",
        "modelRoutingPolicy": {
            "reasoning": "reasoning-model",
            "governance": "governance-model",
        },
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _manifest(
    *,
    kind: str,
    node_run: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    artifact_id = f"{kind}:{content_hash[:16]}"
    return (
        {
            "artifactId": artifact_id,
            "contentHash": content_hash,
            "schemaVersion": "1.0.0",
            "producerNodeRunId": node_run["nodeRunId"],
            "producerAttempt": node_run["attempt"],
            "inputSnapshotHash": node_run["inputSnapshotHash"],
            "configHash": "2" * 64,
            "environmentSnapshotHash": "3" * 64,
            "toolVersionHash": "4" * 64,
            "sourceArtifactIds": [],
            "cacheDisposition": "produced",
            "createdAt": "2026-08-09T10:00:00Z",
        },
        {artifact_id: payload},
    )


def _prepare_iteration_node(service: ResearchWorkflowRuntimeService) -> dict[str, Any]:
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={
                "iteration_planner": "agent-iteration",
                "iteration_versioning": "agent-versioning",
                "formal_runner": "agent-runner",
            }
        ),
    )
    predecessors = [
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "knowledge_ingestion",
        "knowledge_handoff",
        "hypothesis_design",
        "protocol_design",
        "protocol_review",
        "protocol_freeze",
        "smoke_gate",
        "controlled_run",
        "result_evaluation",
    ]
    checkpoint_id = run["langGraph"]["checkpointId"]
    done: list[str] = []
    for node_id in predecessors:
        done.append(node_id)
        checkpoint_id, _ = advance_checkpoint(
            service._checkpoint_path,
            thread_id=run["threadId"],
            checkpoint_id=checkpoint_id,
            completed_node_id=node_id,
            state_patch={
                "current_node_id": node_id,
                "completed_node_ids": list(done),
                **(
                    {"controlled_run_attempt": 1}
                    if node_id == "controlled_run"
                    else {}
                ),
            },
        )
    iteration_run = {
        **run["nodeRuns"][0],
        "nodeRunId": f"nr-{run['runId']}-iteration_decision-a1",
        "nodeId": "iteration_decision",
        "attempt": 1,
        "actorType": "agent",
        "agentId": "agent-iteration",
        "status": "ready",
        "checkpointId": checkpoint_id,
        "inputSnapshotHash": "5" * 64,
    }
    controlled_run = {
        **iteration_run,
        "nodeRunId": f"nr-{run['runId']}-controlled_run-a1",
        "nodeId": "controlled_run",
        "actorType": "system",
        "agentId": "",
        "status": "succeeded",
    }
    artifacts = [
        {
            "artifactId": "frozen_protocol:protocol-v1",
            "contentHash": "6" * 64,
            "schemaVersion": "1.0.0",
            "producerNodeRunId": f"nr-{run['runId']}-protocol_freeze-a1",
            "producerAttempt": 1,
            "inputSnapshotHash": "7" * 64,
            "configHash": "8" * 64,
            "environmentSnapshotHash": "9" * 64,
            "toolVersionHash": "a" * 64,
            "sourceArtifactIds": [],
            "cacheDisposition": "produced",
            "createdAt": "2026-08-09T09:00:00Z",
        },
        {
            "artifactId": "evaluation_report:evaluation-v1",
            "contentHash": "b" * 64,
            "schemaVersion": "1.0.0",
            "producerNodeRunId": f"nr-{run['runId']}-result_evaluation-a1",
            "producerAttempt": 1,
            "inputSnapshotHash": "c" * 64,
            "configHash": "d" * 64,
            "environmentSnapshotHash": "e" * 64,
            "toolVersionHash": "f" * 64,
            "sourceArtifactIds": [],
            "cacheDisposition": "produced",
            "createdAt": "2026-08-09T09:30:00Z",
        },
    ]
    service._store.update_run(
        run["runId"],
        {
            "status": "running",
            "completedNodeIds": predecessors,
            "runtimeCurrentNodeIds": ["iteration_decision"],
            "nodeRuns": [controlled_run, iteration_run],
            "artifactManifests": artifacts,
            "langGraph": {**run["langGraph"], "checkpointId": checkpoint_id},
        },
    )
    return service.get_run(run["runId"])


def _complete_iteration(
    service: ResearchWorkflowRuntimeService,
    record: dict[str, Any],
    *,
    kind: str,
    decision_id: str,
) -> dict[str, Any]:
    service.apply_node_command(
        record["runId"],
        "iteration_decision",
        "start_execution",
        payload={
            "idempotencyKey": f"start-{decision_id}",
            "leaseOwner": "worker-iteration",
        },
    )
    node_run = next(
        item
        for item in service.get_run(record["runId"])["nodeRuns"]
        if item["nodeId"] == "iteration_decision"
    )
    payload = {
        "decisionId": decision_id,
        "decisionKind": kind,
        "runId": record["runId"],
        "nodeRunId": node_run["nodeRunId"],
        "iterationAttempt": 1,
        "selectedCandidateRef": "candidate:best",
        "frozenProtocolRef": "frozen_protocol:protocol-v1",
        "evaluationReportRef": "evaluation_report:evaluation-v1",
        "reason": "bounded decision",
        "terminalReason": "evidence_saturated" if kind == "stop" else "",
        "decidedBy": "agent-iteration",
        "decidedAt": "2026-08-09T10:00:00Z",
        "idempotencyKey": f"decision-{decision_id}",
        "budgetMax": 3,
    }
    manifest, payloads = _manifest(
        kind="iteration_decision",
        node_run=node_run,
        payload=payload,
    )
    return service.apply_node_command(
        record["runId"],
        "iteration_decision",
        "complete_execution",
        payload={
            "idempotencyKey": f"complete-{decision_id}",
            "leaseOwner": "worker-iteration",
            "artifactManifests": [manifest],
            "artifactPayloads": payloads,
        },
    )


def test_rerun_decision_schedules_new_controlled_attempt(tmp_path: Path) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)

    completed = _complete_iteration(
        service,
        prepared,
        kind="rerun_same_protocol",
        decision_id="decision-rerun",
    )

    rerun = max(
        (
            item
            for item in completed["nodeRuns"]
            if item["nodeId"] == "controlled_run"
        ),
        key=lambda item: item["attempt"],
    )
    assert rerun["attempt"] == 2
    assert rerun["status"] == "ready"
    assert completed["runtimeCurrentNodeIds"] == ["controlled_run"]
    assert completed["iterationDecisions"][-1]["decisionId"] == "decision-rerun"
    handoff = next(
        item for item in completed["handoffs"] if item["edgeId"] == "e_decision_rerun"
    )
    assert {item["kind"] for item in handoff["outputArtifactRefs"]} == {
        "iteration_decision",
        "frozen_protocol",
    }


def test_revise_protocol_creates_checkpoint_child_and_supersedes_parent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)

    parent = _complete_iteration(
        service,
        prepared,
        kind="revise_protocol",
        decision_id="decision-revise",
    )

    assert parent["status"] == "superseded"
    assert len(parent["childRunIds"]) == 1
    child = service.get_run(parent["childRunIds"][0])
    assert child["parentRunId"] == parent["runId"]
    assert child["forkDecisionId"] == "decision-revise"
    assert child["runtimeCurrentNodeIds"] == ["protocol_design"]
    assert child["nodeRuns"][0]["nodeId"] == "protocol_design"
    assert child["langGraph"]["checkpointId"]


def test_stop_flows_through_version_governance_to_result_package(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)
    governance_ready = _complete_iteration(
        service,
        prepared,
        kind="stop",
        decision_id="decision-stop",
    )
    assert governance_ready["runtimeCurrentNodeIds"] == ["version_governance"]

    service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "start_execution",
        payload={
            "idempotencyKey": "start-version-stop",
            "leaseOwner": "worker-version",
        },
    )
    node_run = max(
        (
            item
            for item in service.get_run(prepared["runId"])["nodeRuns"]
            if item["nodeId"] == "version_governance"
        ),
        key=lambda item: item["attempt"],
    )
    governance_payload = {
        "governanceId": "governance-stop",
        "runId": prepared["runId"],
        "decisionId": "decision-stop",
        "operation": "stop",
        "candidateRef": "candidate:best",
        "versionId": "official-stop-v1",
        "status": "official",
        "terminalReason": "evidence_saturated",
        "governedAt": "2026-08-09T10:30:00Z",
    }
    manifest, payloads = _manifest(
        kind="version_governance_record",
        node_run=node_run,
        payload=governance_payload,
    )
    completed = service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-version-stop",
            "leaseOwner": "worker-version",
            "artifactManifests": [manifest],
            "artifactPayloads": payloads,
        },
    )

    assert completed["runtimeCurrentNodeIds"] == ["result_package"]
    assert completed["officialCandidateRef"] == "candidate:best"
    assert completed["officialVersion"] == {
        "versionId": "official-stop-v1",
        "candidateRef": "candidate:best",
        "status": "official",
        "operation": "stop",
        "decisionId": "decision-stop",
        "governedAt": "2026-08-09T10:30:00Z",
    }
    assert completed["completionKind"] == "stopped"
    assert completed["terminalReason"] == "evidence_saturated"
    package_run = next(
        item for item in completed["nodeRuns"] if item["nodeId"] == "result_package"
    )
    assert package_run["status"] == "ready"


def test_result_package_system_node_commits_same_fact_package_once(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)
    _complete_iteration(
        service,
        prepared,
        kind="stop",
        decision_id="decision-package",
    )
    service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "start_execution",
        payload={
            "idempotencyKey": "start-version-package",
            "leaseOwner": "worker-version",
        },
    )
    version_run = max(
        (
            item
            for item in service.get_run(prepared["runId"])["nodeRuns"]
            if item["nodeId"] == "version_governance"
        ),
        key=lambda item: item["attempt"],
    )
    governance_payload = {
        "governanceId": "governance-package",
        "runId": prepared["runId"],
        "decisionId": "decision-package",
        "operation": "stop",
        "candidateRef": "candidate:best",
        "versionId": "official-package-v1",
        "status": "official",
        "terminalReason": "evidence_saturated",
        "governedAt": "2026-08-09T10:30:00Z",
    }
    manifest, payloads = _manifest(
        kind="version_governance_record",
        node_run=version_run,
        payload=governance_payload,
    )
    package_ready = service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-version-package",
            "leaseOwner": "worker-version",
            "artifactManifests": [manifest],
            "artifactPayloads": payloads,
        },
    )
    required_missing = (
        "source_candidate_batch",
        "evidence_card_batch",
        "evidence_relation_graph",
        "knowledge_package_draft",
        "knowledge_package",
        "hypothesis_set",
        "protocol_draft",
        "protocol_review_report",
        "smoke_evidence",
        "smoke_release",
        "run_artifacts",
    )
    additional_manifests = []
    for index, kind in enumerate(required_missing, start=1):
        additional_manifests.append(
            {
                "artifactId": f"{kind}:package-{index}",
                "contentHash": f"{index + 100:064x}",
                "schemaVersion": "1.0.0",
                "producerNodeRunId": f"nr-{kind}",
                "producerAttempt": 1,
                "inputSnapshotHash": "1" * 64,
                "configHash": "2" * 64,
                "environmentSnapshotHash": "3" * 64,
                "toolVersionHash": "4" * 64,
                "sourceArtifactIds": [],
                "cacheDisposition": "produced",
                "createdAt": "2026-08-09T10:00:00Z",
            }
        )
    service._store.update_run(
        prepared["runId"],
        {
            "artifactManifests": [
                *package_ready["artifactManifests"],
                *additional_manifests,
            ],
            "qualityGateEvaluations": [
                {"nodeId": node_id, "status": "passed"}
                for node_id in (
                    "source_finding",
                    "source_extraction",
                    "evidence_relations",
                    "hypothesis_design",
                    "controlled_run",
                    "result_evaluation",
                )
            ],
            "competitionEvaluations": [
                {
                    "evaluationId": "evaluation-package",
                    "runId": prepared["runId"],
                    "rubricVersion": "rubric-v1",
                    "dimensionScores": {"innovation": 0.92},
                    "claimCoverage": 0.95,
                    "evidenceCoverage": 0.94,
                    "experimentCoverage": 0.93,
                    "deliverableCoverage": 0.91,
                    "blockingWarnings": [],
                    "reviewerRefs": ["agent:reviewer"],
                    "evaluatedAt": "2026-08-09T10:00:00Z",
                }
            ],
            "experimentCampaigns": [
                {
                    "campaignId": "campaign-package",
                    "experimentRunRefs": ["experiment-run:1"],
                    "resultArtifactRefs": ["run_artifacts:package-11"],
                }
            ],
        },
    )
    ledger = {
        "runId": prepared["runId"],
        "claimEvidence": [
            {"claimId": "claim-1", "evidenceRefs": ["evidence_card_batch:1"]}
        ],
        "teamKnowledge": [{"knowledgeBaseId": "kb-1"}],
        "experimentPlanning": {"activePlanId": "plan-1"},
        "boundaries": {"readOnly": True, "writesWorkflowRun": False},
    }
    service.get_research_ledger = lambda _run_id: ledger  # type: ignore[method-assign]

    first = service.apply_node_command(
        prepared["runId"],
        "result_package",
        "build_package",
        payload={"idempotencyKey": "package-once"},
    )
    replay = service.apply_node_command(
        prepared["runId"],
        "result_package",
        "build_package",
        payload={"idempotencyKey": "package-once"},
    )

    assert first["resultPackage"] == replay["resultPackage"]
    assert first["systemAction"]["actionId"] == replay["systemAction"]["actionId"]
    terminal = service.get_run(prepared["runId"])
    assert terminal["status"] == "succeeded"
    assert terminal["runtimeCurrentNodeIds"] == []
    assert terminal["resultPackage"]["factChainHash"]
    packages = [
        item
        for item in terminal["artifactManifests"]
        if item["artifactId"].startswith("research_result_package:")
    ]
    assert len(packages) == 1


def test_promote_candidate_requires_human_confirmation_before_official_version(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)
    _complete_iteration(
        service,
        prepared,
        kind="promote_candidate",
        decision_id="decision-promote",
    )
    service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "start_execution",
        payload={
            "idempotencyKey": "start-version-promote",
            "leaseOwner": "worker-version",
        },
    )
    version_run = max(
        (
            item
            for item in service.get_run(prepared["runId"])["nodeRuns"]
            if item["nodeId"] == "version_governance"
        ),
        key=lambda item: item["attempt"],
    )
    governance_payload = {
        "governanceId": "governance-promote",
        "runId": prepared["runId"],
        "decisionId": "decision-promote",
        "operation": "promote",
        "candidateRef": "candidate:best",
        "versionId": "candidate-version-v2",
        "status": "proposed",
        "governedAt": "2026-08-09T10:30:00Z",
    }
    manifest, payloads = _manifest(
        kind="version_governance_record",
        node_run=version_run,
        payload=governance_payload,
    )
    waiting = service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-version-promote",
            "leaseOwner": "worker-version",
            "artifactManifests": [manifest],
            "artifactPayloads": payloads,
        },
    )

    assert waiting["runtimeCurrentNodeIds"] == ["candidate_promotion"]
    assert waiting["proposedVersion"]["status"] == "proposed"
    assert waiting["officialCandidateRef"] == ""
    task = next(
        item
        for item in waiting["humanTasks"]
        if item["nodeId"] == "candidate_promotion" and item["status"] == "pending"
    )
    accepted = service.resolve_human_task(
        prepared["runId"],
        task["taskId"],
        decision="accept",
        resolved_by="operator",
        idempotency_key="accept-promotion",
    )

    assert accepted["runtimeCurrentNodeIds"] == ["result_package"]
    assert accepted["officialCandidateRef"] == "candidate:best"
    assert accepted["officialVersion"]["status"] == "official"
    assert accepted["officialVersion"]["versionId"] == "candidate-version-v2"
    assert accepted["completionKind"] == "promoted"
    assert accepted["promotionProposals"][0]["status"] == "accepted"
    promotion_artifact = next(
        item
        for item in accepted["artifactManifests"]
        if item["artifactId"].startswith("promotion_proposal:")
    )
    assert (
        accepted["artifactPayloads"][promotion_artifact["artifactId"]]["versionId"]
        == "candidate-version-v2"
    )


def test_rollback_candidate_becomes_official_before_result_package(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared = _prepare_iteration_node(service)
    _complete_iteration(
        service,
        prepared,
        kind="rollback_candidate",
        decision_id="decision-rollback",
    )
    service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "start_execution",
        payload={
            "idempotencyKey": "start-version-rollback",
            "leaseOwner": "worker-version",
        },
    )
    version_run = max(
        (
            item
            for item in service.get_run(prepared["runId"])["nodeRuns"]
            if item["nodeId"] == "version_governance"
        ),
        key=lambda item: item["attempt"],
    )
    governance_payload = {
        "governanceId": "governance-rollback",
        "runId": prepared["runId"],
        "decisionId": "decision-rollback",
        "operation": "rollback",
        "candidateRef": "candidate:best",
        "versionId": "rollback-official-v1",
        "status": "official",
        "governedAt": "2026-08-09T10:30:00Z",
    }
    manifest, payloads = _manifest(
        kind="version_governance_record",
        node_run=version_run,
        payload=governance_payload,
    )
    completed = service.apply_node_command(
        prepared["runId"],
        "version_governance",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-version-rollback",
            "leaseOwner": "worker-version",
            "artifactManifests": [manifest],
            "artifactPayloads": payloads,
        },
    )

    assert completed["runtimeCurrentNodeIds"] == ["result_package"]
    assert completed["completionKind"] == "rolled_back"
    assert completed["officialVersion"]["operation"] == "rollback"
