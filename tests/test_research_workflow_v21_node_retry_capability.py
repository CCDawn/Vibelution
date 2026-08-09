"""Blocked workflow Agent nodes expose one durable retry capability."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "team-retry-capability",
        "projectId": "project-retry-capability",
        "questionId": "question-retry-capability",
        "researchBriefHash": "a" * 64,
        "datasetRefs": ["fixture://dataset/retry"],
        "metricContract": {"primary": "score"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-10",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "如何补齐反证？"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
            "experiments": 4,
            "computeUnits": 20,
            "maxParallelTasks": 1,
            "maxRetries": 1,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "fixture://environment/retry",
        "modelRoutingPolicy": {"source_discovery": "source-model"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _block_latest(store: WorkflowRunStore, run_id: str) -> dict:
    run = store.get_run(run_id)
    assert run is not None
    node_runs = [dict(item) for item in run["nodeRuns"]]
    node_runs[-1].update(
        {
            "status": "blocked",
            "failureCode": "counter_evidence_missing",
            "failureSummary": "counter-evidence is required",
        }
    )
    return store.update_run(
        run_id,
        {
            "status": "blocked",
            "blockedReason": "counter_evidence_missing",
            "nodeRuns": node_runs,
        },
    )


def test_blocked_agent_node_retries_as_a_new_lineage_attempt(tmp_path: Path) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    service = ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    created = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-retry-capability",
    )
    blocked = _block_latest(store, created["runId"])

    detail = service.get_node_detail(blocked["runId"], "source_finding")
    retry = next(
        item for item in detail["commands"] if item["command"] == "retry_execution"
    )

    assert retry["available"] is True
    assert retry["idempotencyKey"].endswith(":a2")
    retried = service.apply_node_command(
        blocked["runId"],
        "source_finding",
        "retry_execution",
        payload={"idempotencyKey": retry["idempotencyKey"]},
    )
    replay = service.apply_node_command(
        blocked["runId"],
        "source_finding",
        "retry_execution",
        payload={"idempotencyKey": retry["idempotencyKey"]},
    )

    attempts = [
        item for item in replay["nodeRuns"] if item["nodeId"] == "source_finding"
    ]
    assert retried["status"] == "queued"
    assert len(attempts) == 2
    assert attempts[-1]["status"] == "ready"
    assert attempts[-1]["attempt"] == 2
    assert attempts[-1]["supersedesNodeRunId"] == attempts[0]["nodeRunId"]

    exhausted = _block_latest(store, blocked["runId"])
    exhausted_detail = service.get_node_detail(exhausted["runId"], "source_finding")
    exhausted_retry = next(
        item
        for item in exhausted_detail["commands"]
        if item["command"] == "retry_execution"
    )
    assert exhausted_retry["available"] is False
    assert "重试预算已耗尽" in exhausted_retry["reason"]
