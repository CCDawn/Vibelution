"""T5 quality, budget, reuse and read-only ledger contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.contracts import ArtifactManifest
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow.research_runtime import (
    problem_understanding_artifact_writer,
    workflow_artifact_store,
)
from core.web.services.team_workflow.research_runtime.artifact_quality_gate import (
    ArtifactQualityError,
    validate_artifact_quality,
)
from core.web.services.team_workflow.research_runtime.artifact_reuse import (
    ArtifactReuseError,
    validate_artifact_reuse,
)
from core.web.services.team_workflow.research_runtime.budget_lifecycle import (
    reserve_node_budget,
    settle_budget_records,
)
from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
    canonical_sha256,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    ResearchWorkflowRuntimeService,
)
from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore


def _run_input() -> dict:
    return {
        "teamId": "team-quality",
        "projectId": "project-quality",
        "questionId": "question-quality",
        "researchBriefHash": "1" * 64,
        "datasetRefs": ["fixture://dataset/quality"],
        "metricContract": {"primary": "score", "direction": "maximize"},
        "constraintSnapshot": {},
        "competitionRuleRef": "fixture://rules/challenge-cup",
        "competitionRuleVersion": "2026-08-09",
        "trackAndRubricSnapshot": {"track": "科技发明制作类"},
        "researchObjectiveContract": {"question": "如何提高科研质量与效率？"},
        "sourcePolicy": {"minimumPrimarySources": 3},
        "budgetPolicy": {
            "tokens": 1000,
            "toolCalls": 20,
            "wallClockSeconds": 600,
            "experiments": 4,
            "computeUnits": 10,
            "maxParallelTasks": 1,
            "maxRetries": 2,
        },
        "stopPolicy": {"maxNoImprovementRounds": 2},
        "environmentSnapshotRef": "fixture://environment/quality",
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


def _service(path: Path) -> ResearchWorkflowRuntimeService:
    return ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(path / "runs"),
        checkpoint_path=str(path / "checkpoints.sqlite"),
    )


def _advance_to_source_finding(
    service: ResearchWorkflowRuntimeService,
    run: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    """Enter the graph through its canonical problem-understanding node.

    These tests exercise source-finding budget behavior.  The production graph
    still requires the entry node to complete first, so build that small
    predecessor transition with the real node/checkpoint completion path rather
    than manufacturing a downstream NodeRun.
    """

    source_collection_run_id = "source-run-quality"
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
            "idempotencyKey": "start-quality-problem-understanding",
            "leaseOwner": "quality-fixture",
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
        "scope": "quality fixture problem scope",
        "subquestions": ["Which quality tradeoffs are testable?"],
        "assumptions": ["fixture data is bounded"],
        "known_unknowns": ["runtime evidence is not produced by this fixture"],
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
    return service.apply_node_command(
        run["runId"],
        "problem_understanding",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-quality-problem-understanding",
            "leaseOwner": "quality-fixture",
            "artifactManifests": [manifest],
        },
    )


def test_run_initializes_stage_ledgers_and_budget_exhaustion_blocks_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-quality-budget",
    )
    assert {item["stageId"] for item in run["budgetLedgers"]} == {
        "knowledge_collection",
        "experiment_design",
        "execution_iteration",
    }
    _advance_to_source_finding(service, run, tmp_path, monkeypatch)

    with pytest.raises(ResearchWorkflowError) as exc:
        service.apply_node_command(
            run["runId"],
            "source_finding",
            "start_agent_task",
            payload={
                "idempotencyKey": "budget-too-large",
                "budgetRequest": {"tokens": 1001},
            },
        )
    assert exc.value.code == "budget_exceeded"
    blocked = service.get_run(run["runId"])
    assert blocked["status"] == "blocked"
    assert blocked["blockedReason"] == "budget_exceeded"
    knowledge_ledger = next(
        item
        for item in blocked["budgetLedgers"]
        if item["stageId"] == "knowledge_collection"
    )
    assert knowledge_ledger["stopReason"] == "budget_exceeded"
    assert blocked.get("taskBundles") in (None, [])


def test_budget_settlement_charges_observed_usage_when_stage_capacity_remains(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-allocation-overrun",
    )
    node_run = dict(run["nodeRuns"][0])
    reservation = reserve_node_budget(
        service._store,
        record=run,
        node_run=node_run,
        stage_id="knowledge_collection",
        request={"tokens": 100, "toolCalls": 2, "wallClockSeconds": 30},
        idempotency_key="reserve-allocation-overrun",
    )
    reserved = service._store.get_run(run["runId"])
    assert reserved is not None

    ledgers, reservations = settle_budget_records(
        reserved,
        reservation_id=reservation["reservationId"],
        actual={"tokens": 101, "toolCalls": 2, "wallClockSeconds": 30},
        settled_at="2026-08-11T12:00:00Z",
    )

    settled = reservations[0]
    ledger = next(
        item for item in ledgers if item["stageId"] == "knowledge_collection"
    )
    assert settled["actual"]["tokens"] == 101
    assert settled["charged"]["tokens"] == 101
    assert settled["allocationOverrun"] == {"tokens": 1}
    assert "overrun" not in settled
    assert ledger["consumed"]["tokens"] == 101
    assert ledger["stopReason"] == ""


def test_agent_completion_settles_budget_and_task_bundle_with_real_artifact(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-budget-settlement",
    )
    _advance_to_source_finding(service, run, tmp_path, monkeypatch)

    def fake_start_stage_task(team_id: str, source_run_id: str, payload: dict) -> dict:
        return {
            "taskId": "task-quality",
            "agentId": payload["agentId"],
            "sessionId": "session-quality",
            "turn": {"turnId": "turn-quality"},
        }

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.stage_session.start_source_collection_stage_session_task",
        fake_start_stage_task,
    )
    monkeypatch.setattr(
        "core.web.services.session_service.get_session_detail",
        lambda *_args, **_kwargs: {
            "id": "session-quality",
            "agentId": "agent-source-finder",
        },
    )
    service.apply_node_command(
        run["runId"],
        "source_finding",
        "start_agent_task",
        payload={
            "idempotencyKey": "start-quality-budget",
            "budgetRequest": {
                "tokens": 100,
                "toolCalls": 2,
                "wallClockSeconds": 30,
            },
        },
    )
    started = service.get_run(run["runId"])
    node_run = next(
        item for item in started["nodeRuns"] if item["nodeId"] == "source_finding"
    )
    manifest = {
        "artifactId": "source_candidate_batch:budget-quality",
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
        "createdAt": "2026-08-09T10:00:00Z",
    }
    completed = service.apply_node_command(
        run["runId"],
        "source_finding",
        "complete_execution",
        payload={
            "idempotencyKey": "complete-quality-budget",
            "leaseOwner": "agent-task:agent-source-finder",
            "artifactManifests": [manifest],
            "artifactPayloads": {
                manifest["artifactId"]: {
                    "perspectives": ["技术", "竞赛价值"],
                    "queries": ["quality query"],
                    "candidateSources": [{"sourceId": "source-quality"}],
                    "counterEvidenceCandidateSources": [
                        {
                            "sourceId": "source-quality-counter",
                            "perspective": "falsification",
                        }
                    ],
                }
            },
            "budgetUsage": {
                "tokens": 80,
                "toolCalls": 2,
                "wallClockSeconds": 20,
            },
        },
    )
    reservation = completed["budgetReservations"][0]
    ledger = next(
        item
        for item in completed["budgetLedgers"]
        if item["stageId"] == "knowledge_collection"
    )
    assert reservation["status"] == "settled"
    assert reservation["actual"]["tokens"] == 80
    assert ledger["reserved"]["tokens"] == 0
    assert ledger["consumed"]["tokens"] == 80
    assert completed["taskBundles"][0]["status"] == "succeeded"
    assert completed["taskBundles"][0]["subtasks"][0][
        "outputArtifactRefs"
    ] == [manifest["artifactId"]]
    assert "BudgetSettled" in {item["type"] for item in completed["events"]}


def test_source_quality_gate_requires_perspectives_queries_and_candidates() -> None:
    record = {"runId": "run-quality"}
    manifest = {"artifactId": "source_candidate_batch:quality"}
    with pytest.raises(ArtifactQualityError):
        validate_artifact_quality(
            record,
            node_id="source_finding",
            manifests=[manifest],
            payloads={manifest["artifactId"]: {"perspectives": ["only-one"]}},
        )

    gate, records = validate_artifact_quality(
        record,
        node_id="source_finding",
        manifests=[manifest],
        payloads={
            manifest["artifactId"]: {
                "perspectives": ["技术", "竞赛价值"],
                "queries": ["query-a"],
                "candidateSources": [{"sourceId": "source-a"}],
                "counterEvidenceCandidateSources": [
                    {
                        "sourceId": "source-counter-a",
                        "perspective": "limitation_or_null",
                    }
                ],
            }
        },
    )
    assert gate is not None and gate["status"] == "passed"
    assert gate["details"]["perspectiveCount"] == 2
    assert gate["details"]["counterEvidenceCandidateCount"] == 1
    assert records == {}


def test_source_quality_gate_rejects_support_only_candidates() -> None:
    manifest = {"artifactId": "source_candidate_batch:support-only"}
    with pytest.raises(
        ArtifactQualityError,
        match="real limitation, null-result or falsification candidate",
    ):
        validate_artifact_quality(
            {"runId": "run-support-only"},
            node_id="source_finding",
            manifests=[manifest],
            payloads={
                manifest["artifactId"]: {
                    "perspectives": ["mechanism", "independent_baseline"],
                    "queries": ["mechanism query", "baseline query"],
                    "candidateSources": [
                        {"sourceId": "source-support", "perspective": "mechanism"}
                    ],
                    "counterEvidenceCandidateSources": [],
                    "searchTrace": [
                        {
                            "perspective": "falsification",
                            "query": "falsification query",
                            "status": "no_credible_source",
                            "resultRefs": [],
                            "failureReason": "no traceable negative result found",
                        }
                    ],
                }
            },
        )


def test_hypothesis_campaign_and_evaluation_gates_enforce_rigor() -> None:
    record = {
        "runId": "run-rigor",
        "inputSnapshot": {
            "evaluationContract": {"minimumClaimEvidenceCoverage": 0.9}
        },
    }
    hypothesis_manifest = {"artifactId": "hypothesis_set:rigor"}
    hypothesis_payload = {
        "portfolioId": "portfolio-1",
        "runId": "run-rigor",
        "maxCandidates": 2,
        "maxEvolutionRounds": 2,
        "currentEvolutionRound": 1,
        "candidates": [
            {
                "candidateId": "candidate-1",
                "claim": "A falsifiable claim",
                "scores": {
                    "novelty": 0.8,
                    "competitionFit": 0.9,
                    "falsifiability": 0.9,
                    "evidenceSupport": 0.7,
                    "feasibility": 0.8,
                },
                "counterEvidenceRefs": ["claim-evidence:counter-1"],
                "derivedFromCandidateIds": [],
                "status": "ranked",
                "reviewRef": "review-1",
            }
        ],
    }
    _, hypothesis_records = validate_artifact_quality(
        record,
        node_id="hypothesis_design",
        manifests=[hypothesis_manifest],
        payloads={hypothesis_manifest["artifactId"]: hypothesis_payload},
    )
    assert hypothesis_records["hypothesisPortfolio"]["candidates"][0][
        "candidateId"
    ] == "candidate-1"

    campaign_manifest = {"artifactId": "run_artifacts:rigor"}
    campaign_payload = {
        "campaignId": "campaign-1",
        "runId": "run-rigor",
        "hypothesisCandidateId": "candidate-1",
        "protocolHash": "2" * 64,
        "environmentSnapshotHash": "3" * 64,
        "datasetSnapshotRefs": ["dataset:1"],
        "baselineRefs": ["baseline:1"],
        "metricContractRef": "metric:1",
        "stage": "ablation_replication",
        "seedSet": [41, 42],
        "replicationCount": 2,
        "budgetLedgerRef": "budget:1",
        "stopCriteria": {"maxRounds": 4},
        "experimentRunRefs": ["experiment:1", "experiment:2"],
        "resultArtifactRefs": ["result:1"],
        "decision": "evaluate",
    }
    _, campaign_records = validate_artifact_quality(
        record,
        node_id="controlled_run",
        manifests=[campaign_manifest],
        payloads={campaign_manifest["artifactId"]: campaign_payload},
    )
    assert campaign_records["experimentCampaign"]["replicationCount"] == 2

    evaluation_manifest = {"artifactId": "evaluation_report:rigor"}
    blocked_evaluation = {
        "evaluationId": "evaluation-1",
        "runId": "run-rigor",
        "rubricVersion": "rubric-v1",
        "dimensionScores": {"innovation": 0.9},
        "claimCoverage": 0.95,
        "evidenceCoverage": 0.9,
        "experimentCoverage": 0.8,
        "deliverableCoverage": 0.7,
        "blockingWarnings": ["missing negative result analysis"],
        "reviewerRefs": ["reviewer:1"],
        "evaluatedAt": "2026-08-09T10:00:00Z",
    }
    with pytest.raises(ArtifactQualityError):
        validate_artifact_quality(
            record,
            node_id="result_evaluation",
            manifests=[evaluation_manifest],
            payloads={evaluation_manifest["artifactId"]: blocked_evaluation},
        )


def test_artifact_reuse_requires_matching_input_config_environment_and_tool() -> None:
    source = {
        "artifactId": "evidence_card_batch:source",
        "contentHash": "a" * 64,
        "inputSnapshotHash": "b" * 64,
        "configHash": "c" * 64,
        "environmentSnapshotHash": "d" * 64,
        "toolVersionHash": "e" * 64,
    }
    reused = ArtifactManifest.from_dict(
        {
            "artifactId": "evidence_card_batch:reuse",
            "contentHash": source["contentHash"],
            "schemaVersion": "1",
            "producerNodeRunId": "node-run-reuse",
            "producerAttempt": 1,
            "inputSnapshotHash": source["inputSnapshotHash"],
            "configHash": source["configHash"],
            "environmentSnapshotHash": source["environmentSnapshotHash"],
            "toolVersionHash": source["toolVersionHash"],
            "sourceArtifactIds": [source["artifactId"]],
            "cacheDisposition": "reused",
            "createdAt": "2026-08-09T10:00:00Z",
        }
    )
    assert validate_artifact_reuse([reused], source_manifests=[source])[0][
        "sourceArtifactIds"
    ] == [source["artifactId"]]

    mismatched = ArtifactManifest.from_dict(
        {**reused.to_dict(), "toolVersionHash": "f" * 64}
    )
    with pytest.raises(ArtifactReuseError) as exc:
        validate_artifact_reuse([mismatched], source_manifests=[source])
    assert exc.value.code == "artifact_reuse_mismatch"


def test_research_ledger_is_read_only_projection_of_canonical_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = _service(tmp_path)
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=_run_input(),
        binding_layers=AgentBindingLayers(
            workflowDefaults={"source_finder": "agent-source-finder"}
        ),
        idempotency_key="create-ledger",
    )
    monkeypatch.setattr(
        "core.web.services.research_evidence_service.list_claim_evidence",
        lambda team_id: {"evidence": [{"claimEvidenceId": "evidence-1"}]},
    )
    monkeypatch.setattr(
        "core.web.services.team_knowledge_service.list_team_knowledge_bases",
        lambda team_id, internal=False: {
            "knowledgeBases": [{"knowledgeBaseId": "knowledge-1"}]
        },
    )
    monkeypatch.setattr(
        "core.web.services.team_workflow.experiment_api.plan.get_experiment_planning_status",
        lambda team_id: {"plans": [{"planId": "plan-1"}]},
    )

    ledger = service.get_research_ledger(run["runId"])
    assert ledger["summary"]["claimEvidenceCount"] == 1
    assert ledger["summary"]["knowledgeBaseCount"] == 1
    assert ledger["experimentPlanning"]["plans"][0]["planId"] == "plan-1"
    assert ledger["boundaries"] == {
        "readOnly": True,
        "persistsCanonicalEvidence": False,
        "writesTeamKnowledge": False,
        "writesExperimentContract": False,
        "writesWorkflowRun": False,
    }
