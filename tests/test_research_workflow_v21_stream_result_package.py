"""T6 contracts for SSE replay and strict same-fact result packaging."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.web.services.team_workflow.research_runtime.event_stream import (
    initial_sse_frames,
    replay_sse_frames,
)
from core.web.services.team_workflow.research_runtime.result_package import (
    ResultPackageError,
    build_result_package,
)


def _event(sequence: int, event_type: str) -> dict[str, Any]:
    return {
        "eventId": f"evt-{sequence}",
        "sequence": sequence,
        "runId": "run-stream",
        "type": event_type,
        "summary": {"sequence": sequence},
    }


def _decode_frame(frame: str) -> tuple[str, str, dict[str, Any]]:
    lines = frame.strip().splitlines()
    frame_id = next(line[4:] for line in lines if line.startswith("id: "))
    event = next(line[7:] for line in lines if line.startswith("event: "))
    data = json.loads(next(line[6:] for line in lines if line.startswith("data: ")))
    return frame_id, event, data


def test_sse_initial_snapshot_and_last_event_id_replay_are_monotonic() -> None:
    record = {
        "runId": "run-stream",
        "status": "running",
        "runtimeCurrentNodeIds": ["controlled_run"],
        "bindingSnapshots": [],
        "handoffs": [],
        "humanTasks": [],
        "langGraph": {"checkpointId": "checkpoint-3"},
        "events": [
            _event(1, "ActionIssued"),
            _event(2, "ObservationRecorded"),
            _event(3, "NodeRunTransitioned"),
        ],
    }

    initial = initial_sse_frames(record)
    replay = replay_sse_frames(record, after_sequence=1)

    assert len(initial) == 1
    initial_id, initial_type, snapshot = _decode_frame(initial[0])
    assert (initial_id, initial_type) == ("3", "snapshot")
    assert snapshot["cursor"] == 3
    assert snapshot["snapshot"]["runtimeCurrentNodeIds"] == ["controlled_run"]
    assert [int(_decode_frame(frame)[0]) for frame in replay] == [2, 3]
    assert [_decode_frame(frame)[1] for frame in replay] == [
        "ObservationRecorded",
        "NodeRunTransitioned",
    ]
    assert replay_sse_frames(record, after_sequence=3) == []


_REQUIRED_KINDS = (
    "source_candidate_batch",
    "evidence_card_batch",
    "evidence_relation_graph",
    "knowledge_package_draft",
    "knowledge_package",
    "hypothesis_set",
    "protocol_draft",
    "protocol_review_report",
    "frozen_protocol",
    "smoke_evidence",
    "smoke_release",
    "run_artifacts",
    "evaluation_report",
    "iteration_decision",
    "version_governance_record",
)


def _terminal_record() -> tuple[dict[str, Any], dict[str, Any]]:
    manifests = [
        {
            "artifactId": f"{kind}:{index}",
            "contentHash": f"{index + 1:064x}",
            "schemaVersion": "1.0.0",
            "producerNodeRunId": f"nr-{kind}",
            "producerAttempt": 1,
            "inputSnapshotHash": "a" * 64,
            "configHash": "b" * 64,
            "environmentSnapshotHash": "c" * 64,
            "toolVersionHash": "d" * 64,
            "sourceArtifactIds": [],
            "cacheDisposition": "produced",
            "createdAt": "2026-08-09T10:00:00Z",
        }
        for index, kind in enumerate(_REQUIRED_KINDS)
    ]
    record = {
        "runId": "run-package",
        "workflowId": "challenge-cup-research-v2",
        "workflowVersionId": "workflow-version-v2.1",
        "teamId": "team-package",
        "projectId": "project-package",
        "status": "succeeded",
        "completionKind": "stopped",
        "terminalReason": "evidence_saturated",
        "runtimeCurrentNodeIds": [],
        "completedNodeIds": [*_REQUIRED_KINDS, "version_governance"],
        "inputSnapshot": {
            "questionId": "question-package",
            "datasetRefs": ["dataset:fixed-v1"],
            "metricContract": {"primary": "score"},
            "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9},
        },
        "humanTasks": [],
        "artifactManifests": manifests,
        "artifactPayloads": {},
        "nodeRuns": [
            {
                "nodeId": "version_governance",
                "nodeRunId": "nr-version-governance",
                "status": "succeeded",
            }
        ],
        "iterationDecisions": [
            {
                "decisionId": "decision-stop",
                "decisionKind": "stop",
                "selectedCandidateRef": "candidate:best",
                "decidedAt": "2026-08-09T09:00:00Z",
            }
        ],
        "officialCandidateRef": "candidate:best",
        "officialVersion": {
            "versionId": "official-v3",
            "candidateRef": "candidate:best",
            "status": "official",
            "governedAt": "2026-08-09T09:30:00Z",
        },
        "competitionEvaluations": [
            {
                "evaluationId": "eval-package",
                "runId": "run-package",
                "rubricVersion": "rubric-v1",
                "dimensionScores": {"innovation": 0.92},
                "claimCoverage": 0.95,
                "evidenceCoverage": 0.94,
                "experimentCoverage": 0.93,
                "deliverableCoverage": 0.91,
                "blockingWarnings": [],
                "reviewerRefs": ["agent:reviewer"],
                "evaluatedAt": "2026-08-09T09:00:00Z",
            }
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
        "budgetReservations": [
            {"reservationId": "budget-res-1", "status": "settled"}
        ],
        "budgetLedgers": [
            {
                "budgetLedgerId": "budget-execution",
                "stageId": "execution_iteration",
                "reserved": {"tokens": 0},
            }
        ],
        "experimentCampaigns": [
            {
                "campaignId": "campaign-package",
                "experimentRunRefs": ["experiment-run:1"],
                "resultArtifactRefs": ["run_artifacts:11"],
            }
        ],
    }
    ledger = {
        "runId": "run-package",
        "claimEvidence": [
            {
                "claimId": "claim-1",
                "evidenceRefs": ["evidence_card_batch:1"],
            }
        ],
        "teamKnowledge": [{"knowledgeBaseId": "kb-1"}],
        "experimentPlanning": {"activePlanId": "plan-v1"},
        "artifactManifests": manifests,
        "boundaries": {"readOnly": True, "writesWorkflowRun": False},
    }
    return record, ledger


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda record: record.update(status="running"), "run_not_terminal"),
        (
            lambda record: record["humanTasks"].append(
                {"taskId": "pending-1", "status": "pending"}
            ),
            "pending_human_task",
        ),
        (
            lambda record: record["artifactManifests"].pop(),
            "required_artifact_missing",
        ),
        (
            lambda record: record["competitionEvaluations"][0][
                "blockingWarnings"
            ].append("claim gap"),
            "blocking_warning",
        ),
    ],
)
def test_result_package_rejects_incomplete_terminal_facts(
    mutation: Any,
    code: str,
) -> None:
    record, ledger = _terminal_record()
    mutation(record)

    with pytest.raises(ResultPackageError) as exc:
        build_result_package(record, research_ledger=ledger)

    assert exc.value.code == code


def test_result_package_is_deterministic_and_compiles_one_fact_chain() -> None:
    record, ledger = _terminal_record()

    first = build_result_package(record, research_ledger=ledger)
    second = build_result_package(record, research_ledger=ledger)

    assert first == second
    assert first["packageId"].startswith("rrp:run-package:")
    assert len(first["contentHash"]) == 64
    assert first["officialVersion"]["versionId"] == "official-v3"
    hashes = {
        deliverable["factChainHash"]
        for deliverable in first["deliverables"].values()
    }
    assert hashes == {first["factChainHash"]}
    assert set(first["deliverables"]) == {
        "report",
        "defenseSlides",
        "demoScript",
        "experimentAppendix",
        "limitations",
    }
    assert first["traceability"]["claimCount"] == 1
    assert first["traceability"]["artifactCount"] == len(_REQUIRED_KINDS)
