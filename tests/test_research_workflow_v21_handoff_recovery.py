"""T4 contracts for human handoff acceptance, rejection and recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "team-human-gate",
        "projectId": "project-human-gate",
        "questionId": "question-human-gate",
        "researchBriefHash": "1" * 64,
        "datasetRefs": ["fixture://dataset/human-gate"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "人工交接能否保持可追溯？"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
            "experiments": 4,
            "computeUnits": 20,
            "maxParallelTasks": 2,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "fixture://environment/human-gate",
        "modelRoutingPolicy": {"reasoning": "reasoning-model"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _prepare_ingestion_completion(service: ResearchWorkflowRuntimeService) -> dict:
    agent_id = "agent-source-ingestor"
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={
                "source_ingestor": agent_id,
                "experiment_planner": "agent-experiment-planner",
            }
        ),
        idempotency_key="create-human-gate",
    )
    node_run = {
        **run["nodeRuns"][0],
        "nodeRunId": f"nr-{run['runId']}-knowledge_ingestion-a1",
        "nodeId": "knowledge_ingestion",
        "agentId": agent_id,
        "status": "ready",
    }
    service._store.update_run(
        run["runId"],
        {
            "runtimeCurrentNodeIds": ["knowledge_ingestion"],
            "nodeRuns": [node_run],
        },
    )
    service.apply_node_command(
        run["runId"],
        "knowledge_ingestion",
        "start_execution",
        payload={
            "idempotencyKey": "start-ingestion",
            "leaseOwner": "worker-ingestion",
        },
    )
    return service.apply_node_command(
        run["runId"],
        "knowledge_ingestion",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-ingestion",
            "leaseOwner": "worker-ingestion",
            "artifactManifests": [
                {
                    "artifactId": "knowledge_package_draft:draft-1",
                    "contentHash": "2" * 64,
                    "schemaVersion": "1",
                    "producerNodeRunId": node_run["nodeRunId"],
                    "producerAttempt": 1,
                    "inputSnapshotHash": node_run["inputSnapshotHash"],
                    "configHash": "3" * 64,
                    "environmentSnapshotHash": "4" * 64,
                    "toolVersionHash": "5" * 64,
                    "sourceArtifactIds": [],
                    "cacheDisposition": "produced",
                    "createdAt": "2026-08-09T08:00:00Z",
                }
            ],
        },
    )


def test_completion_before_human_gate_creates_one_waiting_task_and_node_run(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    run = _prepare_ingestion_completion(service)

    pending = [task for task in run["humanTasks"] if task["status"] == "pending"]
    gate_runs = [
        node_run
        for node_run in run["nodeRuns"]
        if node_run["nodeId"] == "knowledge_handoff"
    ]
    handoffs = [
        item for item in run["handoffs"] if item["edgeId"] == "e_ingest_handoff"
    ]
    assert len(pending) == 1
    assert pending[0]["nodeId"] == "knowledge_handoff"
    assert pending[0]["nodeRunId"] == gate_runs[0]["nodeRunId"]
    assert len(gate_runs) == 1
    assert gate_runs[0]["status"] == "waiting_human"
    assert len(handoffs) == 1
    assert handoffs[0]["status"] == "waiting_human"
    assert handoffs[0]["humanTaskId"] == pending[0]["taskId"]
    listed = service.list_handoffs(run["runId"])
    detail = service.get_handoff_detail(run["runId"], handoffs[0]["handoffId"])
    assert listed["handoffs"] == handoffs
    assert detail["handoff"] == handoffs[0]
    assert detail["fromNodeRun"]["nodeId"] == "knowledge_ingestion"
    assert detail["toNodeRun"]["nodeId"] == "knowledge_handoff"
    assert detail["humanTask"]["taskId"] == pending[0]["taskId"]
    assert detail["artifactManifests"][0]["artifactId"] == (
        "knowledge_package_draft:draft-1"
    )


def test_accept_human_gate_creates_real_gate_artifact_and_one_successor_handoff(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    waiting = _prepare_ingestion_completion(service)
    task = next(item for item in waiting["humanTasks"] if item["status"] == "pending")

    accepted = service.resolve_human_task(
        waiting["runId"],
        task["taskId"],
        decision="accept",
        resolved_by="operator",
        idempotency_key="accept-knowledge-package",
    )
    replay = service.resolve_human_task(
        waiting["runId"],
        task["taskId"],
        decision="accept",
        resolved_by="operator",
        idempotency_key="accept-knowledge-package",
    )

    gate_run = next(
        item
        for item in accepted["nodeRuns"]
        if item["nodeId"] == "knowledge_handoff"
    )
    next_run = next(
        item
        for item in accepted["nodeRuns"]
        if item["nodeId"] == "hypothesis_design"
    )
    gate_task = next(
        item for item in accepted["humanTasks"] if item["taskId"] == task["taskId"]
    )
    package_artifacts = [
        item
        for item in accepted["artifactManifests"]
        if item["artifactId"].startswith("knowledge_package:")
    ]
    successor_handoffs = [
        item for item in accepted["handoffs"] if item["edgeId"] == "e_kc_hypothesis"
    ]
    assert gate_run["status"] == "succeeded"
    assert gate_task["status"] == "resolved_accept"
    assert next_run["status"] == "ready"
    assert accepted["runtimeCurrentNodeIds"] == ["hypothesis_design"]
    assert len(package_artifacts) == 1
    assert len(package_artifacts[0]["contentHash"]) == 64
    assert package_artifacts[0]["sourceArtifactIds"] == [
        "knowledge_package_draft:draft-1"
    ]
    assert len(successor_handoffs) == 1
    assert successor_handoffs[0]["status"] == "accepted"
    assert replay == accepted
    assert "hash:" not in str(accepted)


@pytest.mark.parametrize("decision", ["reject", "revise"])
def test_reject_or_revise_human_gate_forks_recoverable_child_from_checkpoint(
    tmp_path: Path,
    decision: str,
) -> None:
    service = _service(tmp_path)
    waiting = _prepare_ingestion_completion(service)
    task = next(item for item in waiting["humanTasks"] if item["status"] == "pending")

    revised = service.resolve_human_task(
        waiting["runId"],
        task["taskId"],
        decision=decision,
        resolved_by="operator",
        idempotency_key=f"{decision}-knowledge-package",
    )
    replay = service.resolve_human_task(
        waiting["runId"],
        task["taskId"],
        decision=decision,
        resolved_by="operator",
        idempotency_key=f"{decision}-knowledge-package",
    )

    assert revised["status"] == "superseded"
    assert revised["runtimeCurrentNodeIds"] == []
    assert len(revised["childRunIds"]) == 1
    child_id = revised["childRunIds"][0]
    child = service.get_run(child_id)
    assert child["parentRunId"] == revised["runId"]
    assert child["supersedesRunId"] == revised["runId"]
    assert child["forkedFromCheckpointId"] == task["checkpointId"]
    assert child["runtimeCurrentNodeIds"] == ["knowledge_ingestion"]
    assert child["nodeRuns"][0]["nodeId"] == "knowledge_ingestion"
    assert child["nodeRuns"][0]["status"] == "ready"
    assert child["langGraph"]["checkpointId"]
    assert child["langGraph"]["checkpointId"] != task["checkpointId"]
    assert replay == revised

    reopened = _service(tmp_path)
    recovered_parent = reopened.get_run(revised["runId"])
    recovered_child = reopened.get_run(child_id)
    assert recovered_parent["childRunIds"] == [child_id]
    assert recovered_child["langGraph"]["checkpointId"] == child["langGraph"][
        "checkpointId"
    ]
