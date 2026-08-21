"""T0 contract freeze for the Challenge Cup research workflow v2.1."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.contracts import (
    ArtifactManifest,
    CompetitionEvaluationSnapshot,
    ContractValidationError,
    ExperimentCampaign,
    ExperimentCampaignStage,
    HypothesisPortfolio,
    NodeExecutionEnvelope,
    ResearchBudgetLedger,
    ResearchTaskBundle,
    TaskLease,
    WorkflowRunInputSnapshot,
)
from core.research.workflow.contracts._validation import canonical_sha256
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.web.services.team_workflow.research_runtime.hypothesis_session_scope_mode import (
    HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON,
    evaluate_hypothesis_scope_shadow,
    resolve_hypothesis_scope_activation,
    resolve_hypothesis_session_scope_mode,
)
from core.web.services.team_workflow.research_runtime.run_lifecycle import (
    freeze_run_input,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
)


def _baseline_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["runInput"]


def test_v21_definition_freezes_version_governance_and_schema() -> None:
    definition = build_challenge_cup_workflow_definition()
    node_ids = [node.nodeId for node in definition.nodes]

    assert definition.schemaVersion == "2.1.0"
    assert len(node_ids) == 16
    assert node_ids[-3:] == [
        "version_governance",
        "candidate_promotion",
        "result_package",
    ]


def test_run_input_snapshot_is_complete_and_hash_stable() -> None:
    payload = _baseline_payload()
    snapshot = WorkflowRunInputSnapshot.from_dict(payload)
    reordered = WorkflowRunInputSnapshot.from_dict(
        dict(reversed(list(payload.items())))
    )

    assert snapshot.snapshotHash == reordered.snapshotHash
    assert len(snapshot.snapshotHash) == 64
    assert snapshot.to_dict()["teamId"] == "acceptance-research-team"
    assert snapshot.to_dict()["trackAndRubricSnapshot"]["track"] == "科技发明制作类"
    assert snapshot.workflowSessionScopeV3 == {"hypothesis_design": "off"}


def test_legacy_snapshot_without_scope_mode_defaults_off_and_rehashes() -> None:
    payload = _baseline_payload()
    payload.pop("workflowSessionScopeV3", None)
    legacy_raw_hash = canonical_sha256(payload)
    payload["snapshotHash"] = legacy_raw_hash

    parsed = WorkflowRunInputSnapshot.from_dict(payload)

    assert parsed.workflowSessionScopeV3 == {"hypothesis_design": "off"}
    assert parsed.snapshotHash != legacy_raw_hash
    assert WorkflowRunInputSnapshot.from_dict(parsed.to_dict()).snapshotHash == parsed.snapshotHash


def test_hypothesis_scope_mode_is_server_frozen_and_shadow_is_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            workflow_session_scope_v3=SimpleNamespace(hypothesis_design="shadow")
        ),
    )
    payload = _baseline_payload()
    payload["workflowSessionScopeV3"] = {"hypothesis_design": "on"}
    snapshot = freeze_run_input(
        payload,
        workflow_version_id="2.1.0",
        binding_snapshots=list(payload["agentBindingSnapshot"]),
        created_at="2026-08-22T00:00:00Z",
    )

    assert snapshot.workflowSessionScopeV3 == {"hypothesis_design": "shadow"}
    assert resolve_hypothesis_session_scope_mode(snapshot.to_dict()) == "shadow"
    evaluation = evaluate_hypothesis_scope_shadow(
        {
            "selectionId": "selection-1",
            "selectedCandidateIds": ["H1", "H2"],
        },
        max_parallel=2,
    )
    assert evaluation["candidateCount"] == 2
    assert len(evaluation["scopeHash"]) == 64


def test_hypothesis_scope_activation_preserves_legacy_runs_without_selection() -> None:
    base = {
        "workflowSessionScopeV3": {"hypothesis_design": "on"},
        "researchObjectiveContract": {"question": "legacy run"},
        "teamId": "team-1",
        "questionId": "question-1",
    }

    legacy = resolve_hypothesis_scope_activation(base, chain_state={})
    assert legacy["fanOutEnabled"] is False
    assert legacy["selectionRequired"] is False
    assert legacy["hasAuthoritativeSelection"] is False
    assert legacy["fallbackReason"] == HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON

    hypothesis_first = resolve_hypothesis_scope_activation(
        {
            **base,
            "researchObjectiveContract": {
                "question": "hypothesis-first run",
                "hypothesisFirst": True,
            },
        },
        chain_state={},
    )
    assert hypothesis_first["fanOutEnabled"] is False
    assert hypothesis_first["selectionRequired"] is True
    assert hypothesis_first["fallbackReason"] == ""

    shadow = resolve_hypothesis_scope_activation(
        {
            **base,
            "workflowSessionScopeV3": {"hypothesis_design": "shadow"},
        },
        chain_state={},
    )
    assert shadow["fanOutEnabled"] is False
    assert shadow["selectionRequired"] is False
    assert shadow["fallbackReason"] == HYPOTHESIS_SCOPE_LEGACY_FALLBACK_REASON

    selected = resolve_hypothesis_scope_activation(
        base,
        chain_state={"selectionId": "selection-1"},
    )
    assert selected["fanOutEnabled"] is True
    assert selected["hasAuthoritativeSelection"] is True
    assert selected["selectionId"] == "selection-1"


@pytest.mark.parametrize("configured_mode", ["off", "shadow", "on"])
def test_all_scope_modes_round_trip_from_the_frozen_run_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    configured_mode: str,
) -> None:
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            workflow_session_scope_v3=SimpleNamespace(
                hypothesis_design=configured_mode
            )
        ),
    )
    payload = _baseline_payload()
    payload["workflowSessionScopeV3"] = {
        "hypothesis_design": "on" if configured_mode == "off" else "off"
    }

    snapshot = freeze_run_input(
        payload,
        workflow_version_id="2.1.0",
        binding_snapshots=list(payload["agentBindingSnapshot"]),
        created_at="2026-08-22T00:00:00Z",
    )
    replayed = WorkflowRunInputSnapshot.from_dict(snapshot.to_dict())

    assert snapshot.workflowSessionScopeV3 == {
        "hypothesis_design": configured_mode
    }
    assert resolve_hypothesis_session_scope_mode(snapshot.to_dict()) == configured_mode
    assert replayed.workflowSessionScopeV3 == snapshot.workflowSessionScopeV3
    assert replayed.snapshotHash == snapshot.snapshotHash


def test_run_input_snapshot_rejects_missing_frozen_contract() -> None:
    payload = _baseline_payload()
    payload.pop("budgetPolicy")

    with pytest.raises(ContractValidationError, match="budgetPolicy"):
        WorkflowRunInputSnapshot.from_dict(payload)


def test_execution_and_task_bundle_contracts_are_fail_closed() -> None:
    envelope = NodeExecutionEnvelope.from_dict(
        {
            "runId": "run-1",
            "nodeRunId": "node-run-1",
            "nodeId": "source_finding",
            "attempt": 1,
            "actorType": "agent",
            "agentId": "agent-source-finder",
            "taskId": "task-1",
            "sessionId": "session-1",
            "inputSnapshotHash": "a" * 64,
            "idempotencyKey": "run-1:source_finding:1",
            "leaseOwner": "worker-1",
            "leaseExpiresAt": "2026-08-09T08:10:00Z",
            "heartbeatAt": "2026-08-09T08:00:00Z",
            "deadlineAt": "2026-08-09T08:30:00Z",
            "budgetReservationRef": "budget-reservation-1",
            "status": "running",
            "commandReceiptRef": "",
        }
    )
    lease = TaskLease.from_envelope(envelope)
    bundle = ResearchTaskBundle.from_dict(
        {
            "bundleId": "bundle-1",
            "runId": "run-1",
            "parentNodeRunId": "node-run-1",
            "objective": "查找并核验园区能耗异常检测的一手来源",
            "inputArtifactRefs": ["artifact-question-1"],
            "subtasks": [
                {
                    "subtaskId": "subtask-1",
                    "role": "source_finder",
                    "acceptanceContract": {"minimumPrimarySources": 3},
                    "budgetReservationRef": "budget-reservation-1",
                    "deadlineAt": "2026-08-09T08:20:00Z",
                    "status": "queued",
                    "taskId": "",
                    "sessionId": "",
                    "outputArtifactRefs": [],
                }
            ],
            "maxConcurrency": 1,
            "aggregationContract": {"requiredArtifactKind": "source_candidate_batch"},
            "status": "queued",
        }
    )

    assert lease.idempotencyKey == envelope.idempotencyKey
    assert bundle.maxConcurrency == 1

    with pytest.raises(ContractValidationError, match="idempotencyKey"):
        NodeExecutionEnvelope.from_dict({**envelope.to_dict(), "idempotencyKey": ""})


def test_research_quality_contracts_preserve_lineage() -> None:
    budget = ResearchBudgetLedger.from_dict(
        {
            "budgetLedgerId": "budget-1",
            "runId": "run-1",
            "stageId": "knowledge_collection",
            "policySnapshotHash": "b" * 64,
            "limits": {
                "tokens": 10000,
                "toolCalls": 20,
                "wallClockSeconds": 1800,
                "experiments": 4,
                "computeUnits": 10,
            },
            "reserved": {"tokens": 1000},
            "consumed": {"tokens": 200},
            "stopReason": "",
            "updatedAt": "2026-08-09T08:00:00Z",
        }
    )
    hypotheses = HypothesisPortfolio.from_dict(
        {
            "portfolioId": "portfolio-1",
            "runId": "run-1",
            "maxCandidates": 3,
            "maxEvolutionRounds": 2,
            "candidates": [
                {
                    "candidateId": "hypothesis-1",
                    "claim": "稀疏重构误差门控能降低无效迭代",
                    "scores": {
                        "novelty": 0.7,
                        "competitionFit": 0.9,
                        "falsifiability": 0.9,
                        "evidenceSupport": 0.6,
                        "feasibility": 0.8,
                    },
                    "counterEvidenceRefs": ["evidence-counter-1"],
                    "derivedFromCandidateIds": [],
                    "status": "proposed",
                    "reviewRef": "",
                }
            ],
        }
    )
    campaign = ExperimentCampaign.from_dict(
        {
            "campaignId": "campaign-1",
            "runId": "run-1",
            "hypothesisCandidateId": "hypothesis-1",
            "protocolHash": "c" * 64,
            "environmentSnapshotHash": "d" * 64,
            "datasetSnapshotRefs": ["dataset-energy-anomaly-v1"],
            "baselineRefs": ["baseline-isolation-forest-v1"],
            "metricContractRef": "metric-contract-v1",
            "stage": "feasibility",
            "seedSet": [11, 29, 47],
            "replicationCount": 3,
            "budgetLedgerRef": "budget-1",
            "stopCriteria": {"maxNoImprovementRounds": 2},
            "experimentRunRefs": [],
            "resultArtifactRefs": [],
            "decision": "pending",
        }
    )
    artifact = ArtifactManifest.from_dict(
        {
            "artifactId": "artifact-1",
            "contentHash": "e" * 64,
            "schemaVersion": "1",
            "producerNodeRunId": "node-run-1",
            "producerAttempt": 1,
            "inputSnapshotHash": "a" * 64,
            "configHash": "f" * 64,
            "environmentSnapshotHash": "d" * 64,
            "toolVersionHash": "1" * 64,
            "sourceArtifactIds": ["artifact-question-1"],
            "cacheDisposition": "produced",
            "createdAt": "2026-08-09T08:00:00Z",
        }
    )
    evaluation = CompetitionEvaluationSnapshot.from_dict(
        {
            "evaluationId": "evaluation-1",
            "runId": "run-1",
            "rubricVersion": "challenge-cup-fixture-v1",
            "dimensionScores": {"scientificRigor": 0.8, "innovation": 0.7},
            "claimCoverage": 0.9,
            "evidenceCoverage": 0.9,
            "experimentCoverage": 0.8,
            "deliverableCoverage": 0.0,
            "blockingWarnings": ["result_package_pending"],
            "reviewerRefs": ["reviewer-human-1"],
            "evaluatedAt": "2026-08-09T08:00:00Z",
        }
    )

    assert budget.remaining()["tokens"] == 8800
    assert hypotheses.candidates[0].counterEvidenceRefs == ("evidence-counter-1",)
    assert campaign.stage is ExperimentCampaignStage.FEASIBILITY
    assert artifact.cacheDisposition == "produced"
    assert evaluation.has_blockers is True
