"""Regression coverage for external Agent task completion reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime import (
    agent_task_artifact_builder,
    problem_understanding_artifact_writer,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.external_agent_task_failure import (
    block_external_agent_node_run,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore
from core.web.services.team_workflow.source_collection import search_execution


@pytest.fixture(autouse=True)
def _canonical_team_binding_source(monkeypatch) -> None:
    """Freeze source_finder from Team members, the current binding SSOT."""

    monkeypatch.setattr(
        "core.web.services.team_service.list_team_role_binding_sources",
        lambda _team_id: {
            "team_exists": True,
            "members": [
                {
                    "agentId": "agent-source-finder",
                    "role": "source_finder",
                }
            ],
        },
    )


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
            "perspective": "mechanism",
            "summary": "Mechanism evidence.",
        },
        {
            "title": "Primary source B",
            "locator": "https://example.test/b",
            "sourceType": "paper",
            "query": "baseline perspective",
            "perspective": "independent_baseline",
            "summary": "Baseline evidence.",
        },
        {
            "title": "Primary source C",
            "locator": "https://example.test/c",
            "sourceType": "web",
            "query": "implementation perspective",
            "perspective": "falsification",
            "summary": "Implementation evidence.",
        },
    ]
    for index, lead in enumerate(leads, start=1):
        lead["fingerprint"] = f"url:{lead['locator']}"
        lead["leadId"] = f"lead-fixture-{index}"
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
        "lineage": [
            {
                "fingerprint": lead["fingerprint"],
                "leadId": lead["leadId"],
                "record": {"status": "created", "recordId": f"record-{index}"},
                "candidate": {
                    "status": "created",
                    "candidateId": f"candidate-{index}",
                },
                "reason": "",
            }
            for index, lead in enumerate(leads, start=1)
        ],
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
            "searchTrace": [
                {
                    "perspective": lead["perspective"],
                    "query": lead["query"],
                    "status": "found",
                    "resultRefs": [lead["locator"]],
                }
                for lead in leads
            ],
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


def _advance_to_source_finding(
    service: ResearchWorkflowRuntimeService,
    run: dict,
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Complete the canonical problem_understanding entry node.

    The v2.1 production graph enters through ``problem_understanding``;
    ``source_finding`` only becomes ready after that node completes.  Drive the
    real start/complete path with a written canonical artifact instead of
    manufacturing a downstream NodeRun.
    """

    source_collection_run_id = "source-run-agent-reconcile"
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    service._store.update_run(
        run["runId"],
        {"sourceCollectionRunId": source_collection_run_id},
    )
    service.apply_node_command(
        run["runId"],
        "problem_understanding",
        "start_execution",
        payload={
            "idempotencyKey": "start-reconcile-problem-understanding",
            "leaseOwner": "reconcile-fixture",
            "leaseSeconds": 60,
            "deadlineSeconds": 900,
        },
    )
    started = service.get_run(run["runId"])
    problem_node_run = next(
        item
        for item in started["nodeRuns"]
        if item["nodeId"] == "problem_understanding"
    )
    problem_payload = {
        "scope": "reconcile fixture problem scope",
        "subquestions": ["Which reconciliation invariants must hold?"],
        "assumptions": ["fixture inputs are bounded"],
        "known_unknowns": ["runtime evidence is out of scope here"],
        "human_gate": {
            "required": True,
            "decision": "approved",
            "reviewer": "test-reviewer",
            "decided_at": "2026-08-26T00:00:00Z",
            "rationale": "Fixture precondition accepted.",
        },
    }
    problem_understanding_artifact_writer.write_problem_understanding_artifact(
        team_id=run["teamId"],
        workflow_run_id=run["runId"],
        source_collection_run_id=source_collection_run_id,
        node_run_id=problem_node_run["nodeRunId"],
        problem_understanding=problem_payload,
    )
    content_hash = canonical_sha256(problem_payload)
    manifest = {
        "artifactId": f"problem_understanding:{content_hash[:16]}",
        "contentHash": content_hash,
        "schemaVersion": "1.0.0",
        "producerNodeRunId": problem_node_run["nodeRunId"],
        "producerAttempt": problem_node_run["attempt"],
        "inputSnapshotHash": problem_node_run["inputSnapshotHash"],
        "configHash": "3" * 64,
        "environmentSnapshotHash": "4" * 64,
        "toolVersionHash": "5" * 64,
        "sourceArtifactIds": [],
        "cacheDisposition": "produced",
        "createdAt": "2026-08-26T00:00:00Z",
    }
    service.apply_node_command(
        run["runId"],
        "problem_understanding",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-reconcile-problem-understanding",
            "leaseOwner": "reconcile-fixture",
            "artifactManifests": [manifest],
        },
    )


def _start_source_node(
    service: ResearchWorkflowRuntimeService,
    run: dict,
    tmp_path: Path,
    terminal: dict,
    observed_status: dict[str, str],
    monkeypatch,
    *,
    budget_request: dict[str, int] | None = None,
) -> None:
    _advance_to_source_finding(service, run, tmp_path, monkeypatch)
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
            "updatedAt": "2026-08-09T10:00:10",
            "llmUsage": {"totalTokens": 90},
        },
    )
    leads = list((terminal.get("result") or {}).get("candidateLeads") or [])
    canonical_trace = [
        {
            "sourceCollectionRunId": "source-run-1",
            "assignmentId": "assignment-source-finder",
            "queryId": f"query-{index}",
            "query": lead.get("query") or "",
            "perspective": lead.get("perspective") or "",
            "provider": "crossref",
            "status": "found",
            "resultRefs": [lead.get("locator") or ""],
            "eventIds": [f"event-{index}"],
        }
        for index, lead in enumerate(leads, start=1)
    ]
    present = {str(item.get("perspective") or "") for item in canonical_trace}
    for perspective in (
        "mechanism",
        "independent_baseline",
        "limitation_or_null",
        "falsification",
    ):
        if perspective in present:
            continue
        canonical_trace.append(
            {
                "sourceCollectionRunId": "source-run-1",
                "assignmentId": "assignment-source-finder",
                "queryId": f"query-{perspective}",
                "query": "implementation perspective",
                "perspective": perspective,
                "provider": "openalex",
                "status": "no_credible_source",
                "resultRefs": [],
                "failureReason": "terminal_provider_receipt_without_results",
                "eventIds": [f"event-{perspective}"],
            }
        )
    monkeypatch.setattr(
        agent_task_artifact_builder,
        "project_source_collection_search_trace",
        lambda *_args, **_kwargs: canonical_trace,
    )
    service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_agent_task",
        payload={
            "idempotencyKey": "start-source-finding",
            "budgetRequest": budget_request or {
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
    terminal["result"]["searchTrace"] = [
        {"queryId": "agent-invented", "status": "found", "provider": "agent"}
    ]
    canonical_trace = [
        {
            "sourceCollectionRunId": "source-run-1",
            "assignmentId": "assignment-source-finder",
            "queryId": f"query-{index}",
            "query": lead["query"],
            "perspective": lead["perspective"],
            "provider": "crossref",
            "status": "found",
            "resultRefs": [lead["locator"]],
            "eventIds": [f"event-{index}"],
        }
        for index, lead in enumerate(terminal["result"]["candidateLeads"], start=1)
    ] + [
        {
            "sourceCollectionRunId": "source-run-1",
            "assignmentId": "assignment-source-finder",
            "queryId": "query-limitation_or_null",
            "query": "implementation perspective",
            "perspective": "limitation_or_null",
            "provider": "openalex",
            "status": "no_credible_source",
            "resultRefs": [],
            "failureReason": "terminal_provider_receipt_without_results",
            "eventIds": ["event-limitation_or_null"],
        }
    ]
    monkeypatch.setattr(
        agent_task_artifact_builder,
        "project_source_collection_search_trace",
        lambda *_args, **_kwargs: canonical_trace,
    )
    observed_status = {"value": "running"}
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
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
    manifest = next(
        item
        for item in completed["artifactManifests"]
        if item["artifactId"].startswith("source_candidate_batch:")
    )
    payload = completed["artifactPayloads"][manifest["artifactId"]]
    assert source_run["status"] == "succeeded"
    assert successor["status"] == "ready"
    assert completed["runtimeCurrentNodeIds"] == ["source_extraction"]
    assert len(manifest["contentHash"]) == 64
    assert payload["queries"] == [
        "mechanism perspective",
        "baseline perspective",
        "implementation perspective",
    ]
    assert len(payload["perspectives"]) >= 2
    assert len(payload["counterEvidenceCandidateSources"]) == 1
    assert len(payload["searchTrace"]) == 4
    assert payload["searchTrace"] == canonical_trace
    assert len(payload["candidateSources"]) == 3
    assert (
        next(
            item
            for item in completed["qualityGateEvaluations"]
            if item["nodeId"] == "source_finding"
        )["status"]
        == "passed"
    )
    assert completed["budgetReservations"][0]["status"] == "settled"
    assert completed["budgetReservations"][0]["actual"] == {
        "tokens": 90,
        "toolCalls": 2,
        "wallClockSeconds": 10,
    }
    assert next(
        item
        for item in completed["taskLeases"]
        if item["idempotencyKey"] == "start-source-finding"
    )["status"] == "succeeded"
    assert completed["taskBundles"][0]["status"] == "succeeded"
    assert [item["edgeId"] for item in completed["handoffs"]] == [
        "e_problem_find",
        "e_find_extract",
    ]
    # Each replay re-derives the same exactly-once artifacts and handoffs.
    assert [
        item["artifactId"].split(":", 1)[0]
        for item in replay["artifactManifests"]
    ] == ["problem_understanding", "source_candidate_batch"]
    assert [item["edgeId"] for item in replay["handoffs"]] == [
        "e_problem_find",
        "e_find_extract",
    ]
    assert len(
        [item for item in replay["nodeRuns"] if item["nodeId"] == "source_extraction"]
    ) == 1


def test_completed_task_exceeding_total_stage_budget_blocks_with_audited_overrun(
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
        idempotency_key="create-agent-budget-overrun",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(
        service,
        run,
        tmp_path,
        terminal,
        observed_status,
        monkeypatch,
        budget_request={
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
        },
    )
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": terminal["sessionId"],
            "currentPhase": "ready",
            "updatedAt": "2026-08-09T10:00:10",
            "llmUsage": {"totalTokens": 10001},
        },
    )
    observed_status["value"] = "completed"

    blocked = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in blocked["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    reservation = blocked["budgetReservations"][0]
    ledger = next(
        item
        for item in blocked["budgetLedgers"]
        if item["stageId"] == "knowledge_collection"
    )
    assert blocked["status"] == "blocked"
    assert blocked["blockedReason"] == "budget_exceeded"
    assert source_run["status"] == "blocked"
    assert source_run["failureCode"] == "budget_exceeded"
    assert "冻结预算" in source_run["failureSummary"]
    assert reservation["status"] == "settled"
    assert reservation["actual"]["tokens"] == 10001
    assert reservation["charged"]["tokens"] == 10000
    assert reservation["allocationOverrun"]["tokens"] == 1
    assert reservation["overrun"]["tokens"] == 1
    assert ledger["reserved"]["tokens"] == 0
    assert ledger["consumed"]["tokens"] == 10000
    assert ledger["remaining"]["tokens"] == 0
    assert ledger["stopReason"] == "budget_exceeded"
    # The entry node's own artifacts exist, but the budget-blocked
    # source_finding produced nothing downstream.
    assert [item["edgeId"] for item in blocked["handoffs"]] == [
        "e_problem_find"
    ]
    assert [
        item["artifactId"].split(":", 1)[0]
        for item in blocked["artifactManifests"]
    ] == ["problem_understanding"]
    assert {event["type"] for event in replay["events"]} >= {
        "BudgetSettled",
        "BudgetOverrun",
    }


def test_failed_task_overrun_uses_budget_exceeded_not_internal_settlement_error(
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
        idempotency_key="create-agent-failed-budget-overrun",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(
        service,
        run,
        tmp_path,
        terminal,
        observed_status,
        monkeypatch,
        budget_request={
            "tokens": 10000,
            "toolCalls": 100,
            "wallClockSeconds": 3600,
        },
    )
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": terminal["sessionId"],
            "updatedAt": "2026-08-09T10:00:10",
            "llmUsage": {"totalTokens": 10001},
        },
    )
    observed_status["value"] = "interrupted"

    blocked = service.get_run(run["runId"])

    source_run = next(
        item for item in blocked["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    reservation = blocked["budgetReservations"][0]
    assert blocked["blockedReason"] == "budget_exceeded"
    assert source_run["failureCode"] == "budget_exceeded"
    assert source_run["failureCode"] != "invalid_budget_settlement"
    assert reservation["actual"]["tokens"] == 10001
    assert reservation["overrun"] == {"tokens": 1}
    assert {event["type"] for event in blocked["events"]} >= {
        "BudgetSettled",
        "BudgetOverrun",
    }


def test_source_task_review_disposition_defers_to_passed_artifact_gates(
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
        idempotency_key="create-agent-review-disposition",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
    observed_status["value"] = "needs_review"

    completed = service.get_run(run["runId"])

    source_run = next(
        item for item in completed["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    assert source_run["status"] == "succeeded"
    assert (
        next(
            item
            for item in completed["qualityGateEvaluations"]
            if item["nodeId"] == "source_finding"
        )["status"]
        == "passed"
    )
    assert completed["runtimeCurrentNodeIds"] == ["source_extraction"]


def test_quality_gate_failure_settles_agent_budget_before_blocking(
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
        idempotency_key="create-agent-quality-failure-budget",
    )
    terminal = _terminal_source_task()
    terminal["result"]["candidateLeads"] = terminal["result"][
        "candidateLeads"
    ][:1]
    terminal["result"]["materializedSources"].update(
        {
            "sourceLeadCount": 1,
            "createdRecordCount": 1,
            "createdRecords": terminal["result"]["materializedSources"][
                "createdRecords"
            ][:1],
            "importedCandidateCount": 1,
            "importedCandidates": terminal["result"]["materializedSources"][
                "importedCandidates"
            ][:1],
        }
    )
    terminal["materializedSources"] = terminal["result"]["materializedSources"]
    observed_status = {"value": "running"}
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
    observed_status["value"] = "needs_review"

    blocked = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in blocked["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    assert source_run["status"] == "blocked"
    assert source_run["failureCode"] == "quality_gate_failed"
    assert blocked["budgetReservations"][0]["status"] == "settled"
    assert blocked["budgetReservations"][0]["actual"] == {
        "tokens": 90,
        "toolCalls": 2,
        "wallClockSeconds": 10,
    }
    assert len(
        [event for event in replay["events"] if event["type"] == "BudgetSettled"]
    ) == 1


def test_interrupted_agent_task_blocks_and_settles_budget(
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
        idempotency_key="create-agent-interrupted-budget",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
    observed_status["value"] = "interrupted"

    blocked = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in blocked["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    assert blocked["status"] == "blocked"
    assert source_run["status"] == "blocked"
    assert source_run["failureCode"] == "external_task_interrupted"
    assert blocked["budgetReservations"][0]["status"] == "settled"
    assert len(
        [event for event in replay["events"] if event["type"] == "BudgetSettled"]
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
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
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
    assert [
        item["artifactId"].split(":", 1)[0]
        for item in replay["artifactManifests"]
    ] == ["problem_understanding", "source_candidate_batch"]
    assert [item["edgeId"] for item in replay["handoffs"]] == [
        "e_problem_find",
        "e_find_extract",
    ]


def test_source_finding_payload_does_not_shift_identity_after_failed_lead() -> None:
    failed_lead = {
        "leadId": "lead-failed",
        "fingerprint": "url:https://example.test/failed",
        "title": "Failed source",
        "locator": "https://example.test/failed",
        "query": "mechanism",
        "perspective": "mechanism",
    }
    accepted_lead = {
        "leadId": "lead-accepted",
        "fingerprint": "url:https://example.test/accepted",
        "title": "Accepted source",
        "locator": "https://example.test/accepted",
        "query": "baseline",
        "perspective": "independent_baseline",
    }
    task = {
        "taskId": "task-lineage-failure",
        "sessionId": "session-lineage-failure",
        "result": {"candidateLeads": [failed_lead, accepted_lead]},
        "materializedSources": {
            "createdRecords": [
                {"recordId": "record-accepted", "sourceRef": accepted_lead["locator"]}
            ],
            "importedCandidates": [
                {"candidateId": "candidate-accepted", "recordId": "record-accepted"}
            ],
            "lineage": [
                {
                    "fingerprint": failed_lead["fingerprint"],
                    "leadId": failed_lead["leadId"],
                    "record": {"status": "failed", "recordId": ""},
                    "candidate": {"status": "not_attempted", "candidateId": ""},
                    "reason": "data_record_create_failed",
                },
                {
                    "fingerprint": accepted_lead["fingerprint"],
                    "leadId": accepted_lead["leadId"],
                    "record": {"status": "created", "recordId": "record-accepted"},
                    "candidate": {
                        "status": "created",
                        "candidateId": "candidate-accepted",
                    },
                    "reason": "",
                },
            ],
        },
    }

    payload = agent_task_artifact_builder._source_finding_payload(
        {"runId": "run-lineage-failure"},
        {"nodeRunId": "node-run-lineage-failure"},
        task,
    )

    assert [item["leadId"] for item in payload["candidateSources"]] == [
        "lead-accepted"
    ]
    assert payload["candidateSources"][0]["recordId"] == "record-accepted"
    assert payload["candidateSources"][0]["candidateId"] == "candidate-accepted"


def test_source_finding_payload_joins_reused_entities_by_lineage() -> None:
    leads = [
        {
            "leadId": "lead-record-reused",
            "fingerprint": "url:https://example.test/record-reused",
            "locator": "https://example.test/record-reused",
        },
        {
            "leadId": "lead-candidate-reused",
            "fingerprint": "url:https://example.test/candidate-reused",
            "locator": "https://example.test/candidate-reused",
        },
    ]
    task = {
        "taskId": "task-lineage-reuse",
        "sessionId": "session-lineage-reuse",
        "result": {"candidateLeads": leads},
        "writeback": {
            "materializedSources": {
                # These legacy diagnostic arrays are deliberately sparse and
                # oppositely ordered; they are not an identity authority.
                "createdRecords": [
                    {"recordId": "record-new", "sourceRef": leads[1]["locator"]}
                ],
                "importedCandidates": [
                    {"candidateId": "candidate-new", "recordId": "record-old"}
                ],
                "lineage": [
                    {
                        "fingerprint": leads[0]["fingerprint"],
                        "leadId": leads[0]["leadId"],
                        "record": {"status": "reused", "recordId": "record-old"},
                        "candidate": {
                            "status": "created",
                            "candidateId": "candidate-new",
                        },
                        "reason": "",
                    },
                    {
                        "fingerprint": leads[1]["fingerprint"],
                        "leadId": leads[1]["leadId"],
                        "record": {"status": "created", "recordId": "record-new"},
                        "candidate": {
                            "status": "reused",
                            "candidateId": "candidate-old",
                        },
                        "reason": "duplicate_source_candidate",
                    },
                ],
            }
        },
    }

    payload = agent_task_artifact_builder._source_finding_payload(
        {"runId": "run-lineage-reuse"},
        {"nodeRunId": "node-run-lineage-reuse"},
        task,
    )

    assert [
        (item["recordId"], item["candidateId"])
        for item in payload["candidateSources"]
    ] == [
        ("record-old", "candidate-new"),
        ("record-new", "candidate-old"),
    ]


def test_unknown_pinned_definition_blocks_external_reconciliation_once(
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
        idempotency_key="create-agent-unknown-definition",
    )
    terminal = _terminal_source_task()
    observed_status = {"value": "running"}
    _start_source_node(service, run, tmp_path, terminal, observed_status, monkeypatch)
    store.update_run(
        run["runId"],
        {"workflowVersionId": "wv-unknown-definition"},
    )
    observed_status["value"] = "completed"

    blocked = service.get_run(run["runId"])
    replay = service.get_run(run["runId"])

    source_run = next(
        item for item in blocked["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    assert source_run["status"] == "blocked"
    assert source_run["failureCode"] == "unknown_workflow_definition_version"
    assert replay["runVersion"] == blocked["runVersion"]


def test_search_trace_projection_uses_event_type_for_terminal_semantics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from core.web.services import team_workflow_orchestration_service

    events = [
        {
            "eventId": "evt-executed-duplicate",
            "eventType": "search.executed",
            "status": "completed",
            "assignmentId": "assignment-1",
            "queryId": "query-duplicate",
            "query": "duplicate query",
            "provider": "crossref",
            "refs": ["search-url"],
            "createdAt": "2026-08-31T01:00:00Z",
        },
        {
            "eventId": "evt-duplicate",
            "eventType": "search.duplicate_skipped",
            "status": "completed",
            "assignmentId": "assignment-1",
            "queryId": "query-duplicate",
            "query": "duplicate query",
            "provider": "crossref",
            "refs": ["record-existing"],
            "createdAt": "2026-08-31T01:00:01Z",
        },
        {
            "eventId": "evt-excluded",
            "eventType": "search.excluded_source_filtered",
            "status": "completed",
            "assignmentId": "assignment-1",
            "queryId": "query-excluded",
            "query": "excluded query",
            "provider": "openalex",
            "refs": ["excluded-key"],
            "createdAt": "2026-08-31T01:00:02Z",
        },
        {
            "eventId": "evt-found",
            "eventType": "storage.source_manifest_imported",
            "status": "completed",
            "assignmentId": "assignment-1",
            "queryId": "query-found",
            "query": "found query",
            "provider": "arxiv",
            "refs": ["candidate-new"],
            "createdAt": "2026-08-31T01:00:03Z",
        },
        {
            "eventId": "evt-empty",
            "eventType": "search.executed",
            "status": "completed",
            "assignmentId": "assignment-1",
            "queryId": "query-empty",
            "query": "negative result query",
            "perspective": "limitation_or_null",
            "provider": "openalex",
            "refs": [],
            "createdAt": "2026-08-31T01:00:04Z",
        },
    ]
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_source_collection_storage_artifact_paths",
        lambda *_args, **_kwargs: {"searchEventsPath": tmp_path / "events.jsonl"},
    )
    monkeypatch.setattr(
        team_workflow_orchestration_service,
        "_read_jsonl",
        lambda _path: events,
    )

    projected = search_execution.project_source_collection_search_trace(
        "team-1",
        "source-run-1",
        assignment_id="assignment-1",
    )

    assert {
        (item["queryId"], item["provider"]): item["status"] for item in projected
    } == {
        ("query-duplicate", "crossref"): "duplicate",
        ("query-excluded", "openalex"): "excluded",
        ("query-found", "arxiv"): "found",
        ("query-empty", "openalex"): "no_credible_source",
    }
    empty = next(item for item in projected if item["queryId"] == "query-empty")
    assert empty["failureReason"] == "terminal_provider_receipt_without_results"
    assert empty["eventIds"] == ["evt-empty"]
