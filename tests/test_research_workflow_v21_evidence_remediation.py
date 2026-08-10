"""Evidence remediation forks for exhausted source-extraction attempts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
)
from core.web.services.team_workflow.research_runtime.external_agent_task_reconciliation import (
    _evidence_failure_context,
)
from core.web.services.team_workflow.research_runtime.node_command_adapter import (
    node_command_capabilities,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "team-evidence-remediation",
        "projectId": "project-evidence-remediation",
        "questionId": "question-evidence-remediation",
        "researchBriefHash": "e" * 64,
        "datasetRefs": ["fixture://dataset/evidence-remediation"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "如何补齐来源证据锚点？"},
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
        "environmentSnapshotRef": "fixture://environment/evidence-remediation",
        "modelRoutingPolicy": {"extraction": "extraction-model"},
        "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        "createdBy": "test-operator",
    }


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _blocked_exhausted_extraction(
    service: ResearchWorkflowRuntimeService,
    *,
    consume_tokens: int = 250,
) -> dict:
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={
                "source_finder": "agent-source-finder",
                "source_extractor": "agent-source-extractor",
            }
        ),
        idempotency_key="create-evidence-remediation",
    )
    checkpoint_id, scheduled = advance_checkpoint(
        service._checkpoint_path,
        thread_id=run["threadId"],
        checkpoint_id=run["langGraph"]["checkpointId"],
        completed_node_id="source_finding",
        state_patch={
            "current_node_id": "source_finding",
            "artifacts": {"source_candidate_batch": "candidate-batch-1"},
        },
    )
    assert scheduled == ["source_extraction"]
    source_run = dict(run["nodeRuns"][0])
    attempts = []
    for attempt in range(1, 4):
        attempts.append(
            {
                **source_run,
                "nodeRunId": f"nr-{run['runId']}-source_extraction-a{attempt}",
                "nodeId": "source_extraction",
                "attempt": attempt,
                "agentId": "agent-source-extractor",
                "status": "blocked" if attempt == 3 else "failed",
                "checkpointId": checkpoint_id,
                "failureCode": "external_task_needs_review",
                "failureSummary": "candidate evidence anchors remain incomplete",
                "failureContext": {
                    "kind": "evidence_quality_gap",
                    "sourceTaskId": "source-task-extraction",
                    "evidenceGapCandidateIds": ["candidate-b", "candidate-a"],
                },
                "countsAgainstRetryBudget": attempt > 1,
                "supersedesNodeRunId": (
                    f"nr-{run['runId']}-source_extraction-a{attempt - 1}"
                    if attempt > 1
                    else ""
                ),
            }
        )
    ledgers = []
    for ledger in run["budgetLedgers"]:
        next_ledger = dict(ledger)
        if next_ledger["stageId"] == "knowledge_collection":
            next_ledger["consumed"] = {
                **dict(next_ledger.get("consumed") or {}),
                "tokens": consume_tokens,
            }
            next_ledger["remaining"] = {
                **dict(next_ledger.get("remaining") or {}),
                "tokens": 10000 - consume_tokens,
            }
        ledgers.append(next_ledger)
    service._store.update_run(
        run["runId"],
        {
            "status": "blocked",
            "blockedReason": "external_task_needs_review",
            "runtimeCurrentNodeIds": ["source_extraction"],
            "completedNodeIds": ["source_finding"],
            "nodeRuns": attempts,
            "sourceCollectionRunId": "source-run-evidence-remediation",
            "budgetLedgers": ledgers,
            "langGraph": {
                **run["langGraph"],
                "checkpointId": checkpoint_id,
                "completedNodeIds": ["source_finding"],
            },
        },
    )
    return service.get_run(run["runId"])


def _command_payload() -> dict:
    return {
        "idempotencyKey": "fork-evidence-remediation-1",
        "resolutionKind": "add_budget",
        "evidenceGapCandidateIds": ["candidate-b", "candidate-a", "candidate-a"],
        "scopeCandidateIds": ["candidate-b", "candidate-a"],
        "additionalBudget": {
            "tokens": 500,
            "toolCalls": 6,
            "wallClockSeconds": 300,
        },
        "operatorReason": "补抓既有 DOI/URL 的正文证据锚点，不扩展检索范围。",
    }


def test_evidence_failure_context_uses_only_durable_blocked_candidate_ids() -> None:
    assert _evidence_failure_context(
        {
            "taskId": "source-task-extraction",
            "writeback": {
                "coverageSummary": {
                    "blockedCandidateIds": ["candidate-b", "candidate-a", "candidate-a"]
                }
            },
        }
    ) == {
        "kind": "evidence_quality_gap",
        "sourceTaskId": "source-task-extraction",
        "evidenceGapCandidateIds": ["candidate-a", "candidate-b"],
    }


def test_exhausted_evidence_gap_forks_child_from_source_checkpoint(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    parent = _blocked_exhausted_extraction(service)

    capabilities = node_command_capabilities(parent, "source_extraction")
    remediation = next(
        item for item in capabilities
        if item["command"] == "fork_evidence_remediation"
    )
    assert remediation["available"] is True
    assert remediation["payload"] == {
        "evidenceGapCandidateIds": ["candidate-a", "candidate-b"],
        "scopeCandidateIds": ["candidate-a", "candidate-b"],
    }

    revised = service.apply_node_command(
        parent["runId"],
        "source_extraction",
        "fork_evidence_remediation",
        payload=_command_payload(),
    )
    replay = service.apply_node_command(
        parent["runId"],
        "source_extraction",
        "fork_evidence_remediation",
        payload=_command_payload(),
    )

    assert revised["status"] == "superseded"
    assert revised["terminalReason"] == "evidence_remediation"
    assert revised["runtimeCurrentNodeIds"] == []
    assert len(revised["childRunIds"]) == 1
    assert replay["childRunIds"] == revised["childRunIds"]
    child = service.get_run(revised["childRunIds"][0])
    assert child["parentRunId"] == parent["runId"]
    assert child["supersedesRunId"] == parent["runId"]
    assert child["forkedFromNodeId"] == "source_extraction"
    assert child["forkedFromCheckpointId"] == parent["langGraph"]["checkpointId"]
    assert child["runtimeCurrentNodeIds"] == ["source_extraction"]
    assert child["completedNodeIds"] == ["source_finding"]
    assert child["sourceCollectionRunId"] == "source-run-evidence-remediation"
    assert child["nodeRuns"] == [
        {
            **child["nodeRuns"][0],
            "nodeId": "source_extraction",
            "attempt": 1,
            "status": "ready",
            "agentId": "agent-source-extractor",
        }
    ]
    contract = child["inputSnapshot"]["evidenceRemediationContract"]
    assert contract == {
        "schemaVersion": 1,
        "parentRunId": parent["runId"],
        "sourceNodeId": "source_extraction",
        "resolutionKind": "add_budget",
        "evidenceGapCandidateIds": ["candidate-a", "candidate-b"],
        "scopeCandidateIds": ["candidate-a", "candidate-b"],
        "requiredExistingLocatorFetch": True,
        "additionalBudget": {
            "tokens": 500,
            "toolCalls": 6,
            "wallClockSeconds": 300,
        },
        "operatorReason": "补抓既有 DOI/URL 的正文证据锚点，不扩展检索范围。",
    }
    knowledge_budget = next(
        item for item in child["budgetLedgers"]
        if item["stageId"] == "knowledge_collection"
    )
    assert knowledge_budget["limits"]["tokens"] == 10250
    assert knowledge_budget["limits"]["toolCalls"] == 106
    assert knowledge_budget["limits"]["wallClockSeconds"] == 3900
    assert child["inputSnapshot"]["snapshotHash"] == child["nodeRuns"][0][
        "inputSnapshotHash"
    ]

    reopened = _service(tmp_path)
    assert reopened.get_run(parent["runId"])["childRunIds"] == [child["runId"]]
    assert reopened.get_run(child["runId"])["evidenceRemediationContract"] == contract


def test_evidence_remediation_requires_exhausted_durable_failure(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    parent = _blocked_exhausted_extraction(service)
    attempts = list(parent["nodeRuns"][:-1])
    service._store.update_run(parent["runId"], {"nodeRuns": attempts})

    with pytest.raises(ResearchWorkflowError) as exc_info:
        service.apply_node_command(
            parent["runId"],
            "source_extraction",
            "fork_evidence_remediation",
            payload=_command_payload(),
        )

    assert exc_info.value.code == "evidence_remediation_not_available"


@pytest.mark.parametrize(
    ("patch", "code"),
    (
        ({"operatorReason": ""}, "invalid_evidence_remediation"),
        ({"evidenceGapCandidateIds": []}, "invalid_evidence_remediation"),
        ({"additionalBudget": {}}, "invalid_evidence_remediation_budget"),
        ({"resolutionKind": "unsupported"}, "invalid_evidence_remediation"),
        (
            {"evidenceGapCandidateIds": ["candidate-a", "candidate-forged"]},
            "invalid_evidence_remediation",
        ),
        (
            {
                "resolutionKind": "add_budget",
                "scopeCandidateIds": ["candidate-a"],
            },
            "invalid_evidence_remediation",
        ),
        (
            {
                "resolutionKind": "reduce_scope",
                "additionalBudget": {},
                "scopeCandidateIds": ["candidate-a", "candidate-b"],
            },
            "invalid_evidence_remediation",
        ),
    ),
)
def test_evidence_remediation_rejects_unfrozen_operator_contract(
    tmp_path: Path,
    patch: dict,
    code: str,
) -> None:
    service = _service(tmp_path)
    parent = _blocked_exhausted_extraction(service)
    payload = {**_command_payload(), **patch}

    with pytest.raises(ResearchWorkflowError) as exc_info:
        service.apply_node_command(
            parent["runId"],
            "source_extraction",
            "fork_evidence_remediation",
            payload=payload,
        )

    assert exc_info.value.code == code
