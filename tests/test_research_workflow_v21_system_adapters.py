"""T6 contracts for real Smoke and controlled-run System adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime.checkpoint_lifecycle import (
    advance_checkpoint,
)
from core.web.services.team_workflow.research_runtime import workflow_artifact_store
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    server_operator_scope,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


@pytest.fixture(autouse=True)
def _bind_server_operator(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow_artifact_store, "PROJECT_ROOT", tmp_path)
    with server_operator_scope("test-operator", roles=("operator",)):
        yield


def _run_input() -> dict[str, Any]:
    return {
        "teamId": "team-system-adapter",
        "projectId": "project-system-adapter",
        "questionId": "question-system-adapter",
        "researchBriefHash": "1" * 64,
        "datasetRefs": ["fixture://dataset/system-adapter"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "真实执行器能否保持可追溯？"},
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
        "environmentSnapshotRef": "fixture://environment/system-adapter",
        "modelRoutingPolicy": {"reasoning": "reasoning-model"},
        "evaluationContract": {
            "minimumClaimEvidenceCoverage": 0.9,
            "requiredSeeds": [11, 29, 47],
        },
        "createdBy": "test-operator",
    }


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _prepare_smoke_gate(service: ResearchWorkflowRuntimeService) -> dict[str, Any]:
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        idempotency_key="create-system-adapter",
    )
    completed = [
        "source_finding",
        "source_extraction",
        "evidence_relations",
        "knowledge_ingestion",
        "knowledge_handoff",
        "hypothesis_design",
        "protocol_design",
        "protocol_review",
        "protocol_freeze",
    ]
    checkpoint_id = run["langGraph"]["checkpointId"]
    done: list[str] = []
    for node_id in completed:
        done.append(node_id)
        checkpoint_id, _next = advance_checkpoint(
            service._checkpoint_path,
            thread_id=run["threadId"],
            checkpoint_id=checkpoint_id,
            completed_node_id=node_id,
            state_patch={
                "current_node_id": node_id,
                "completed_node_ids": list(done),
            },
        )
    node_run_id = f"nr-{run['runId']}-smoke_gate-a1"
    task_id = f"ht-{run['runId']}-smoke_gate"
    handoff_id = f"ho-{run['runId']}-freeze-smoke"
    frozen_artifact_id = "frozen_protocol:protocol-v1"
    node_run = {
        **run["nodeRuns"][0],
        "nodeRunId": node_run_id,
        "nodeId": "smoke_gate",
        "actorType": "human",
        "agentId": "",
        "status": "waiting_human",
        "checkpointId": checkpoint_id,
        "inputSnapshotHash": "2" * 64,
    }
    service._store.update_run(
        run["runId"],
        {
            "status": "waiting_human",
            "completedNodeIds": completed,
            "runtimeCurrentNodeIds": ["smoke_gate"],
            "nodeRuns": [node_run],
            "artifactManifests": [
                {
                    "artifactId": frozen_artifact_id,
                    "contentHash": "3" * 64,
                    "schemaVersion": "1.0.0",
                    "producerNodeRunId": f"nr-{run['runId']}-protocol_freeze-a1",
                    "producerAttempt": 1,
                    "inputSnapshotHash": "4" * 64,
                    "configHash": "5" * 64,
                    "environmentSnapshotHash": "6" * 64,
                    "toolVersionHash": "7" * 64,
                    "sourceArtifactIds": [],
                    "cacheDisposition": "produced",
                    "createdAt": "2026-08-09T08:00:00Z",
                }
            ],
            "artifactPayloads": {
                frozen_artifact_id: {
                    "planId": "plan-system-v1",
                    "protocolHash": "3" * 64,
                }
            },
            "humanTasks": [
                {
                    "taskId": task_id,
                    "runId": run["runId"],
                    "nodeId": "smoke_gate",
                    "nodeRunId": node_run_id,
                    "handoffId": handoff_id,
                    "checkpointId": checkpoint_id,
                    "status": "pending",
                }
            ],
            "handoffs": [
                {
                    "handoffId": handoff_id,
                    "runId": run["runId"],
                    "fromNodeId": "protocol_freeze",
                    "fromNodeRunId": f"nr-{run['runId']}-protocol_freeze-a1",
                    "toNodeId": "smoke_gate",
                    "toNodeRunId": node_run_id,
                    "edgeId": "e_freeze_smoke",
                    "status": "waiting_human",
                    "humanTaskId": task_id,
                    "outputArtifactRefs": [
                        {
                            "artifactId": frozen_artifact_id,
                            "kind": "frozen_protocol",
                            "version": "1.0.0",
                            "contentHash": "3" * 64,
                        }
                    ],
                }
            ],
            "langGraph": {**run["langGraph"], "checkpointId": checkpoint_id},
        },
    )
    return service.get_run(run["runId"])


def test_smoke_action_is_durable_idempotent_and_required_before_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    waiting = _prepare_smoke_gate(service)
    task = waiting["humanTasks"][0]

    with pytest.raises(ResearchWorkflowError) as exc:
        service.resolve_human_task(
            waiting["runId"],
            task["taskId"],
            decision="accept",
            resolved_by="operator",
            idempotency_key="release-without-smoke",
        )
    assert exc.value.code == "smoke_evidence_missing"

    calls: list[tuple[str, str]] = []

    def fake_smoke(team_id: str, plan_id: str, _payload: dict) -> dict:
        calls.append((team_id, plan_id))
        return {
            "teamId": team_id,
            "planId": plan_id,
            "status": "passed",
            "smokeRun": {
                "smokeRunId": "smoke-real-1",
                "status": "passed",
                "artifactHash": "8" * 64,
            },
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.smoke_system_adapter.run_experiment_smoke_run",
        fake_smoke,
    )
    first = service.apply_node_command(
        waiting["runId"],
        "smoke_gate",
        "run_smoke",
        payload={"planId": "plan-system-v1", "idempotencyKey": "smoke-once"},
    )
    replay = service.apply_node_command(
        waiting["runId"],
        "smoke_gate",
        "run_smoke",
        payload={"planId": "plan-system-v1", "idempotencyKey": "smoke-once"},
    )

    assert calls == [("team-system-adapter", "plan-system-v1")]
    assert first["systemAction"]["status"] == "succeeded"
    assert replay["systemAction"]["actionId"] == first["systemAction"]["actionId"]
    persisted = service.get_run(waiting["runId"])
    event_types = [event["type"] for event in persisted["events"]]
    assert "ActionIssued" in event_types
    assert "ObservationRecorded" in event_types
    assert "CommandReceiptRecorded" in event_types

    accepted = service.resolve_human_task(
        waiting["runId"],
        task["taskId"],
        decision="accept",
        resolved_by="operator",
        idempotency_key="release-after-smoke",
    )
    smoke_payload = next(
        payload
        for artifact_id, payload in accepted["artifactPayloads"].items()
        if artifact_id.startswith("smoke_evidence:")
    )
    assert smoke_payload["planId"] == "plan-system-v1"
    assert smoke_payload["smokeRunId"] == "smoke-real-1"
    assert accepted["runtimeCurrentNodeIds"] == ["controlled_run"]


def test_controlled_run_uses_real_execution_and_completes_system_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    waiting = _prepare_smoke_gate(service)

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.smoke_system_adapter.run_experiment_smoke_run",
        lambda team_id, plan_id, _payload: {
            "teamId": team_id,
            "planId": plan_id,
            "status": "passed",
            "smokeRun": {
                "smokeRunId": "smoke-real-2",
                "status": "passed",
                "artifactHash": "8" * 64,
            },
        },
    )
    service.apply_node_command(
        waiting["runId"],
        "smoke_gate",
        "run_smoke",
        payload={"planId": "plan-system-v1", "idempotencyKey": "smoke-before-run"},
    )
    ready = service.resolve_human_task(
        waiting["runId"],
        waiting["humanTasks"][0]["taskId"],
        decision="accept",
        resolved_by="operator",
        idempotency_key="release-before-run",
    )
    calls: list[str] = []

    def fake_full_run(team_id: str, plan_id: str, _payload: dict) -> dict:
        calls.append(plan_id)
        return {
            "workflowId": "domain-workflow-1",
            "execution": {
                "executionId": "execution-real-1",
                "status": "completed",
                "result": {"metric": 0.91},
            },
            "plan": {"planId": plan_id},
            "team": {"teamId": team_id},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.research_runtime.controlled_run_system_adapter.execute_experiment_full_run",
        fake_full_run,
    )
    command_payload = {
        "planId": "plan-system-v1",
        "idempotencyKey": "controlled-once",
        "campaign": {
            "campaignId": "campaign-system-1",
            "runId": ready["runId"],
            "hypothesisCandidateId": "hypothesis-1",
            "protocolHash": "3" * 64,
            "environmentSnapshotHash": "6" * 64,
            "datasetSnapshotRefs": ["fixture://dataset/system-adapter"],
            "baselineRefs": ["baseline:control"],
            "metricContractRef": "metric:score",
            "stage": "ablation_replication",
            "seedSet": [11, 29, 47],
            "replicationCount": 3,
            "budgetLedgerRef": ready["budgetLedgers"][2]["budgetLedgerId"],
            "stopCriteria": {"maxNoImprovementRounds": 2},
            "experimentRunRefs": [],
            "resultArtifactRefs": [],
            "decision": "completed",
        },
    }
    result = service.apply_node_command(
        ready["runId"],
        "controlled_run",
        "start_controlled_run",
        payload=command_payload,
    )
    replay = service.apply_node_command(
        ready["runId"],
        "controlled_run",
        "start_controlled_run",
        payload=command_payload,
    )

    assert calls == ["plan-system-v1"]
    assert result["systemAction"]["status"] == "succeeded"
    assert replay["systemAction"]["actionId"] == result["systemAction"]["actionId"]
    persisted = service.get_run(ready["runId"])
    controlled = next(
        item for item in persisted["nodeRuns"] if item["nodeId"] == "controlled_run"
    )
    assert controlled["status"] == "succeeded"
    assert persisted["runtimeCurrentNodeIds"] == ["result_evaluation"]
    assert persisted["experimentCampaigns"][0]["experimentRunRefs"] == [
        "experiment-run:execution-real-1"
    ]
    event_types = [event["type"] for event in persisted["events"]]
    assert "ActionIssued" in event_types
    assert "ObservationRecorded" in event_types
    assert "ArtifactProduced" in event_types
