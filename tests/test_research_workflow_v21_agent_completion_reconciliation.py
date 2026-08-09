"""Regression coverage for external Agent task completion reconciliation."""

from __future__ import annotations

from pathlib import Path

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.external_agent_task_failure import (
    block_external_agent_node_run,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "team-agent-reconcile",
        "projectId": "project-agent-reconcile",
        "questionId": "question-agent-reconcile",
        "researchBriefHash": "a" * 64,
        "datasetRefs": ["fixture://dataset/reconcile"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {"formalWrites": False},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "如何提升科研闭环效率？"},
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
        "environmentSnapshotRef": "fixture://environment/reconcile",
        "modelRoutingPolicy": {
            "source_discovery": "source-model",
            "extraction": "extraction-model",
            "reasoning": "reasoning-model",
            "review": "review-model",
            "governance": "governance-model",
        },
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _terminal_source_task() -> dict:
    leads = [
        {
            "title": "Primary source A",
            "locator": "https://example.test/a",
            "sourceType": "paper",
            "query": "mechanism perspective",
            "summary": "Mechanism evidence.",
        },
        {
            "title": "Primary source B",
            "locator": "https://example.test/b",
            "sourceType": "paper",
            "query": "baseline perspective",
            "summary": "Baseline evidence.",
        },
        {
            "title": "Primary source C",
            "locator": "https://example.test/c",
            "sourceType": "web",
            "query": "implementation perspective",
            "summary": "Implementation evidence.",
        },
    ]
    records = [
        {
            "recordId": f"record-{index}",
            "sourceRef": lead["locator"],
            "title": lead["title"],
        }
        for index, lead in enumerate(leads, start=1)
    ]
    candidates = [
        {
            "candidateId": f"candidate-{index}",
            "recordId": f"record-{index}",
            "title": lead["title"],
        }
        for index, lead in enumerate(leads, start=1)
    ]
    materialized = {
        "status": "completed",
        "sourceLeadCount": 3,
        "createdRecordCount": 3,
        "createdRecords": records,
        "importedCandidateCount": 3,
        "importedCandidates": candidates,
        "failedCount": 0,
        "excludedSourceCount": 0,
    }
    return {
        "taskId": "task-source-finding",
        "stageId": "finding",
        "agentId": "agent-source-finder",
        "sessionId": "session-source-finding",
        "status": "completed",
        "createdAt": "2026-08-09T02:00:00+00:00",
        "updatedAt": "2026-08-09T02:00:12+00:00",
        "turn": {"acceptedAt": "2026-08-09T10:00:02"},
        "result": {
            "candidateLeads": leads,
            "materializedSources": materialized,
        },
        "materializedSources": materialized,
        "taskToolProgress": {"toolCallCount": 2, "complete": True},
        "completionGate": {
            "artifactComplete": True,
            "taskChecklistComplete": True,
            "passed": True,
        },
    }


def _start_source_node(
    service: ResearchWorkflowRuntimeService,
    run: dict,
    terminal: dict,
    observed_status: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.runs.start_source_collection_run",
        lambda _team_id, _payload: {"run": {"runId": "source-run-1"}},
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        lambda _team_id, _run_id, _payload: {
            "taskId": terminal["taskId"],
            "agentId": terminal["agentId"],
            "sessionId": terminal["sessionId"],
            "sessionAttempt": 1,
            "turn": {"turnId": "turn-source-finding"},
            "task": {
                "taskId": terminal["taskId"],
                "agentId": terminal["agentId"],
                "sessionId": terminal["sessionId"],
                "turn": {"turnId": "turn-source-finding"},
            },
        },
    )

    def find_task(_team_id: str, _task_id: str):
        return {
            "runId": "source-run-1",
            "task": {**terminal, "status": observed_status["value"]},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_task_query.get_source_collection_stage_session_task",
        find_task,
    )
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": terminal["sessionId"],
            "currentPhase": "ready",
            "updatedAt": "2026-08-09T10:00:12",
            "llmUsage": {"totalTokens": 90},
        },
    )
    service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_agent_task",
        payload={
            "idempotencyKey": "start-source-finding",
            "budgetRequest": {
                "tokens": 100,
                "toolCalls": 2,
                "wallClockSeconds": 30,
            },
        },
    )


def test_completed_external_source_task_advances_workflow_exactly_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-agent-reconcile",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(service, run, terminal, observed_status, monkeypatch)
    observed_status["value"] = "completed"

    completed = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in completed["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    successor = next(
        item
        for item in completed["nodeRuns"]
        if item["nodeId"] == "source_extraction"
    )
    manifest = completed["artifactManifests"][0]
    payload = completed["artifactPayloads"][manifest["artifactId"]]
    assert source_run["status"] == "succeeded"
    assert successor["status"] == "ready"
    assert completed["runtimeCurrentNodeIds"] == ["source_extraction"]
    assert manifest["artifactId"].startswith("source_candidate_batch:")
    assert len(manifest["contentHash"]) == 64
    assert payload["queries"] == [
        "mechanism perspective",
        "baseline perspective",
        "implementation perspective",
    ]
    assert len(payload["perspectives"]) >= 2
    assert len(payload["candidateSources"]) == 3
    assert completed["qualityGateEvaluations"][0]["status"] == "passed"
    assert completed["budgetReservations"][0]["status"] == "settled"
    assert completed["budgetReservations"][0]["actual"] == {
        "tokens": 90,
        "toolCalls": 2,
        "wallClockSeconds": 10,
    }
    assert completed["taskLeases"][0]["status"] == "succeeded"
    assert completed["taskBundles"][0]["status"] == "succeeded"
    assert [item["edgeId"] for item in completed["handoffs"]] == [
        "e_find_extract"
    ]
    assert len(replay["artifactManifests"]) == 1
    assert len(replay["handoffs"]) == 1
    assert len(
        [item for item in replay["nodeRuns"] if item["nodeId"] == "source_extraction"]
    ) == 1


def test_completed_task_recovers_one_internal_reconciliation_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    store = WorkflowRunStore(tmp_path / "runs")
    service = ResearchWorkflowRuntimeService(
        run_store=store,
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-agent-reconciliation-recovery",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(service, run, terminal, observed_status, monkeypatch)
    running = store.get_run(run["runId"])
    assert running is not None
    node_run = next(
        item for item in running["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    blocked = block_external_agent_node_run(
        store,
        record=running,
        node_run=node_run,
        failure_code="external_task_completion_invalid",
        failure_summary="can't subtract offset-naive and offset-aware datetimes",
    )
    assert blocked["status"] == "blocked"
    observed_status["value"] = "completed"

    completed = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in completed["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    recovery_receipts = [
        item
        for item in replay["commandReceipts"]
        if item["command"] == "retry_external_agent_reconciliation"
    ]
    recovery_events = [
        item
        for item in replay["events"]
        if item["type"] == "ExternalAgentTaskReconciliationRetried"
    ]
    assert source_run["status"] == "succeeded"
    assert source_run["taskId"] == terminal["taskId"]
    assert source_run["sessionId"] == terminal["sessionId"]
    assert len(recovery_receipts) == 1
    assert len(recovery_events) == 1
    assert len(replay["artifactManifests"]) == 1
    assert len(replay["handoffs"]) == 1
