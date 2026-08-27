"""R3.2 bounded auto-revision execution for formal runs (decision #3).

Covers the bounded execution of automatic protocol revision on the
``iteration_decision`` node of :mod:`core.web.services.team_workflow.
research_runtime.service`:

- the first ``MAX_AUTO_REVISION_ROUNDS_DEFAULT`` (2) ``revise_protocol``
  decisions fork their deterministic child runs as before;
- the next decision refuses to fork and parks the parent run in a
  structured, recoverable stop state: ``budget_exceeded`` (the frozen
  retry-taxonomy ``human_required`` outcome code) plus the mandatory
  ``auto_revision_exhausted`` marker;
- the exhaustion is recorded through the canonical evolution-lineage
  projection writer and escalated through ``build_anomaly_inbox`` with the
  frozen kind/severity mapping;
- the revision-round counter is derived from persisted store data, so it
  survives reopening the store (no in-memory counting).

It also covers the R2.2 direct claim-belief hard gate on the formal
hypothesis handoff in ``run_creation``: a blocked handoff hypothesis raises
``ClaimBeliefGateBlockedError`` before any run is created, an allowed one
freezes the handoff and reaches run creation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.research.workflow.bindings import AgentBindingLayers
from core.research.workflow.contracts import (
    DEFAULT_RETRY_TAXONOMY,
    RetryOutcomeClass,
)
from core.research.workflow.contracts.automation_policy import (
    MAX_AUTO_REVISION_ROUNDS_DEFAULT,
)
from core.research.workflow.contracts.evolution_lineage import (
    REVISION_EXHAUSTED_EXCEPTION,
)
from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
from core.web.services.team_workflow import hypothesis_rounds, meeting_rounds
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain,
    run_creation,
    workflow_artifact_store,
)
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
from core.web.services.team_workflow.research_runtime.workflow_artifact_store import (
    list_workflow_artifacts,
)


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
        "researchObjectiveContract": {"question": "自动修订是否有界？"},
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
    import hashlib
    import json

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


_PRE_ITERATION_NODES = [
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


def _advance_to_iteration_decision(
    service: ResearchWorkflowRuntimeService, run: dict[str, Any]
) -> dict[str, Any]:
    """Drive any run of the lineage (root or revision child) to its
    iteration_decision node, mirroring the v21 governance harness."""
    done: list[str] = [
        node_id
        for node_id in _PRE_ITERATION_NODES
        if node_id in (run.get("completedNodeIds") or [])
    ]
    checkpoint_id = run["langGraph"]["checkpointId"]
    for node_id in _PRE_ITERATION_NODES:
        if node_id in done:
            continue
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
    base_node_run = run["nodeRuns"][0]
    iteration_run = {
        **base_node_run,
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
            "completedNodeIds": done,
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


def _create_root_run(service: ResearchWorkflowRuntimeService) -> dict[str, Any]:
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
    return _advance_to_iteration_decision(service, service.get_run(run["runId"]))


def _exhaust_revision_budget(
    service: ResearchWorkflowRuntimeService, tmp_path: Path
) -> tuple[dict[str, Any], dict[str, Any], list[str], str]:
    """Fork the two allowed auto-revision rounds.

    Returns the prepared round-2 child record, the round-2 child record, the
    forked child run ids in round order and the lineage root run id.
    """
    prepared_root = _create_root_run(service)
    root_run_id = prepared_root["runId"]
    parent1 = _complete_iteration(
        service,
        prepared_root,
        kind="revise_protocol",
        decision_id="decision-revise-1",
    )
    assert parent1["status"] == "superseded"
    child1 = service.get_run(parent1["childRunIds"][0])
    prepared1 = _advance_to_iteration_decision(service, child1)
    parent2 = _complete_iteration(
        service,
        prepared1,
        kind="revise_protocol",
        decision_id="decision-revise-2",
    )
    assert parent2["status"] == "superseded"
    child2_id = parent2["childRunIds"][0]
    prepared2 = _advance_to_iteration_decision(service, service.get_run(child2_id))
    return (
        prepared2,
        service.get_run(child2_id),
        [child1["runId"], child2_id],
        root_run_id,
    )


# -- bounded fork execution ---------------------------------------------------


def test_first_two_revise_rounds_fork_deterministic_children(tmp_path: Path) -> None:
    service = _service(tmp_path)
    prepared_root = _create_root_run(service)

    parent1 = _complete_iteration(
        service,
        prepared_root,
        kind="revise_protocol",
        decision_id="decision-revise-1",
    )
    assert parent1["status"] == "superseded"
    child1 = service.get_run(parent1["childRunIds"][0])
    assert child1["parentRunId"] == parent1["runId"]
    assert child1["forkDecisionId"] == "decision-revise-1"
    assert child1["runtimeCurrentNodeIds"] == ["protocol_design"]

    prepared1 = _advance_to_iteration_decision(service, child1)
    parent2 = _complete_iteration(
        service,
        prepared1,
        kind="revise_protocol",
        decision_id="decision-revise-2",
    )
    assert parent2["status"] == "superseded"
    child2 = service.get_run(parent2["childRunIds"][0])
    assert child2["parentRunId"] == parent2["runId"]
    assert child2["forkDecisionId"] == "decision-revise-2"
    assert child2["langGraph"]["checkpointId"]


def test_third_revise_round_parks_run_with_human_required_stop(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared2, child2, _fork_ids, root_run_id = _exhaust_revision_budget(
        service, tmp_path
    )

    parked = _complete_iteration(
        service,
        prepared2,
        kind="revise_protocol",
        decision_id="decision-revise-3",
    )

    # No third child: the parent is parked instead of forked.
    assert parked["runId"] == child2["runId"]
    assert parked["status"] == "blocked"
    assert not (parked.get("childRunIds") or [])
    assert not (parked.get("supersededByRunId") or "")
    # Structured stop reason: frozen taxonomy human_required code.
    assert parked["blockedReason"] == "budget_exceeded"
    assert (
        DEFAULT_RETRY_TAXONOMY.classify(parked["blockedReason"])
        is RetryOutcomeClass.HUMAN_REQUIRED
    )
    auto = parked["autoRevision"]
    assert auto["stopReason"] == REVISION_EXHAUSTED_EXCEPTION
    assert auto["revisionRoundCount"] == MAX_AUTO_REVISION_ROUNDS_DEFAULT
    assert auto["outcomeCode"] == "budget_exceeded"
    assert auto["outcomeClass"] == "human_required"
    assert auto["recommendedAction"] == "reconcile_run"
    assert auto["humanActions"] == ["reconcile_run", "archive_run"]
    assert auto["mandatoryException"] == REVISION_EXHAUSTED_EXCEPTION
    assert auto["lineageRootRunId"] == root_run_id
    assert auto["decisionId"] == "decision-revise-3"
    exhaustion_events = [
        item
        for item in parked["events"]
        if item.get("type") == "AutoRevisionExhausted"
    ]
    assert len(exhaustion_events) == 1
    assert exhaustion_events[0]["summary"]["revisionRoundCount"] == 2
    assert exhaustion_events[0]["summary"]["outcomeClass"] == "human_required"


def test_exhaustion_records_mandatory_lineage_exception_and_anomaly_escalation(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared2, child2, fork_ids, _root_run_id = _exhaust_revision_budget(
        service, tmp_path
    )

    parked = _complete_iteration(
        service,
        prepared2,
        kind="revise_protocol",
        decision_id="decision-revise-3",
    )

    auto = parked["autoRevision"]
    # Mandatory exception recorded through the evolution-lineage writer.
    assert (
        auto["lineageRecord"]["mandatoryExceptionReview"]
        == REVISION_EXHAUSTED_EXCEPTION
    )
    assert auto["lineageRecord"]["status"] == "written"
    rows = list_workflow_artifacts(
        "team-iteration",
        kind="evolution_lineage",
        workflow_run_id=child2["runId"],
    )
    assert len(rows) == 1
    events = rows[0]["payload"]["events"]
    kinds = [item["kind"] for item in events]
    assert kinds[0] == "introduced"
    assert "revision_exhausted" in kinds
    exhausted = next(
        item for item in events if item["kind"] == "revision_exhausted"
    )
    assert exhausted["reason"] == REVISION_EXHAUSTED_EXCEPTION
    assert exhausted["actor"] == "system_policy"
    assert [ref["kind"] for ref in exhausted["evidenceRefs"]] == [
        "fork_run",
        "fork_run",
    ]
    assert [ref["ref"] for ref in exhausted["evidenceRefs"]] == fork_ids

    # Escalation item emitted through the anomaly-inbox projector with the
    # frozen kind/severity mapping.
    escalation = auto["anomalyEscalation"]
    assert escalation["status"] == "emitted"
    items = escalation["items"]
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "budget_exhausted"
    assert item["severity"] == "critical"
    assert item["recommendedAction"] == "reconcile_run"
    assert item["scope"]["teamId"] == "team-iteration"
    assert item["scope"]["questionId"] == "question-iteration"
    assert item["scope"]["runId"] == child2["runId"]
    assert "problem:budget_exceeded" in item["evidence"]


def test_revision_round_count_survives_store_reopen(tmp_path: Path) -> None:
    service = _service(tmp_path)
    _prepared2, child2, _fork_ids, _root_run_id = _exhaust_revision_budget(
        service, tmp_path
    )

    # Reopen: fresh service and store instances over the same durable paths,
    # so the round counter must be derived from persisted data.
    reopened = ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    prepared = _advance_to_iteration_decision(
        reopened, reopened.get_run(child2["runId"])
    )
    parked = _complete_iteration(
        reopened,
        prepared,
        kind="revise_protocol",
        decision_id="decision-revise-3",
    )
    assert parked["status"] == "blocked"
    assert parked["autoRevision"]["revisionRoundCount"] == 2
    assert reopened.get_run(child2["runId"])["childRunIds"] in (None, []) or not (
        reopened.get_run(child2["runId"])["childRunIds"]
    )


def test_idempotent_replay_of_exhausted_decision_keeps_parked_state(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    prepared2, _child2, _fork_ids, _root_run_id = _exhaust_revision_budget(
        service, tmp_path
    )

    first = _complete_iteration(
        service,
        prepared2,
        kind="revise_protocol",
        decision_id="decision-revise-3",
    )
    # Replay the same completed payload: the fork branch is reached again
    # with the budget exhausted, but the deterministic child already exists.
    second = _complete_iteration(
        service,
        first,
        kind="revise_protocol",
        decision_id="decision-revise-3",
    )
    assert second["status"] == "blocked"
    events = [
        item
        for item in second["events"]
        if item.get("type") == "AutoRevisionExhausted"
    ]
    assert len(events) == 1


# -- R2.2: direct claim-belief gate on the formal handoff ---------------------


def _closed_round(*, accepted: bool = True) -> dict[str, Any]:
    from core.research.workflow.contracts import SCORE_DIMENSIONS, scope_hash_for

    scope = {
        "program": "XH-202619",
        "theme": "challenge-cup",
        "campaign": "challenge-cup-research",
        "question": "SCI-003",
        "branch": "main",
        "workflow": "hypothesis_and_plan",
        "agentId": "agent-meta",
        "mode": "formal",
    }
    scope_hash = scope_hash_for(
        program=scope["program"],
        theme=scope["theme"],
        campaign=scope["campaign"],
        question=scope["question"],
        branch=scope["branch"],
        workflow=scope["workflow"],
        agent_id=scope["agentId"],
        mode=scope["mode"],
    )

    def candidate(candidate_id: str, claim: str) -> dict[str, Any]:
        return {
            "candidateId": candidate_id,
            "claim": claim,
            "rationale": f"rationale-{candidate_id}",
            "differenceFromAlternatives": f"difference-{candidate_id}",
            "lineageRefs": [],
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "reviewedBy": f"reviewer-{candidate_id}",
            "status": "proposed",
        }

    return {
        "roundId": "hround-final",
        **scope,
        "scopeHash": scope_hash,
        "status": "closed",
        "candidates": [
            candidate("candidate-confirmed", "confirmed mechanism"),
            candidate("candidate-rejected", "alternative mechanism"),
        ],
        "pairwiseComparisons": [
            {
                "comparisonId": "cmp-final",
                "leftCandidateId": "candidate-confirmed",
                "rightCandidateId": "candidate-rejected",
                "reviewerAgentId": "agent-pairwise",
                "outcome": "left_wins",
                "justification": "confirmed candidate has stronger evidence",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["candidate-confirmed"],
            "dominatedCandidateIds": ["candidate-rejected"],
            "analystAgentId": "agent-pareto",
            "notes": "complete classification",
        },
        "metaReview": {
            "metaReviewId": "meta-final",
            "reviewerAgentId": "agent-meta",
            "recommendationCandidateId": "candidate-confirmed",
            "rationale": "best supported candidate",
            "riskNotes": "bounded risk",
            "accepted": accepted,
        },
        "lineage": [{"kind": "candidate", "id": "candidate-confirmed"}],
        "meetingRefs": [
            {"kind": "meeting_round", "id": "meeting-final"},
            {"kind": "meeting_digest", "id": "digest-final"},
            {"kind": "decision_record", "id": "decision-final"},
        ],
        "createdAt": "2026-08-27T00:00:00Z",
        "closedAt": "2026-08-27T00:10:00Z",
        "closedBy": "agent-meta",
    }


def _install_handoff_authorities(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate_verdicts: dict[str, dict[str, Any]],
) -> None:
    monkeypatch.setattr(
        hypothesis_rounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": _closed_round()},
    )
    monkeypatch.setattr(
        hypothesis_first_chain,
        "evaluate_claim_belief_gate",
        lambda _team_id, _question_id, candidate_ids: {
            candidate_id: gate_verdicts[candidate_id]
            for candidate_id in candidate_ids
        },
    )
    monkeypatch.setattr(
        meeting_rounds,
        "get_meeting_round",
        lambda _team_id, _meeting_id: {
            "meetingRound": {
                "meetingRoundId": "meeting-final",
                "meetingType": "hypothesis_review",
                "status": "closed",
                "question": "SCI-003",
                "digestId": "digest-final",
                "decisionRefs": ["decision-final"],
                "inputArtifactRefs": ["hypothesis_selection:selection-reviewed"],
            }
        },
    )
    monkeypatch.setattr(meeting_rounds, "_digests_path", lambda _team_id: Path("digests"))
    monkeypatch.setattr(
        meeting_rounds,
        "_decisions_path",
        lambda _team_id: Path("decisions"),
    )
    monkeypatch.setattr(
        meeting_rounds,
        "_read_jsonl",
        lambda path: (
            [{"digestId": "digest-final"}]
            if str(path) == "digests"
            else [{"decisionId": "decision-final"}]
        ),
    )


def _blocked_verdict() -> dict[str, dict[str, Any]]:
    return {
        "candidate-confirmed": {
            "candidateId": "candidate-confirmed",
            "status": "blocked",
            "reason": "claim_belief_state_blocked",
            "claims": [],
            "blockedClaims": [
                {"claimId": "claim-1", "beliefState": "contradicted"}
            ],
        }
    }


def _allowed_verdict() -> dict[str, dict[str, Any]]:
    return {
        "candidate-confirmed": {
            "candidateId": "candidate-confirmed",
            "status": "allowed",
            "reason": "",
            "claims": [],
            "blockedClaims": [],
        }
    }


def test_formal_handoff_blocked_hypothesis_raises_claim_belief_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_blocked_verdict())

    with pytest.raises(hypothesis_first_chain.ClaimBeliefGateBlockedError) as exc_info:
        run_creation._formal_hypothesis_handoff(
            "research-team",
            "SCI-003",
            hypothesis_round_id="hround-final",
        )

    assert exc_info.value.code == "claim_belief_gate_blocked"
    assert exc_info.value.stage == "formal_run_handoff"
    assert exc_info.value.candidate_id == "candidate-confirmed"
    blockers = exc_info.value.blockers
    assert blockers and blockers[0]["reason"] == "claim_belief_state_blocked"
    assert blockers[0]["claims"][0]["claimId"] == "claim-1"


def test_formal_handoff_allowed_hypothesis_freezes_and_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_allowed_verdict())

    handoff = run_creation._formal_hypothesis_handoff(
        "research-team",
        "SCI-003",
        hypothesis_round_id="hround-final",
    )

    assert (
        handoff["hypothesisConvergenceHandoff"]["confirmedCandidateId"]
        == "candidate-confirmed"
    )
    assert handoff["hypothesisSelection"]["selectedCandidateIds"] == [
        "candidate-confirmed"
    ]

    created_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(run_creation, "get_write_store", lambda: object())
    monkeypatch.setattr(
        run_creation,
        "build_question_run_input",
        lambda *_args, **_kwargs: {
            "teamId": "research-team",
            "questionId": "SCI-003",
            "researchScopeEnvelope": {},
            "catalogScope": {},
        },
    )
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: created_calls.append(kwargs)
        or {"runId": "run-created"},
    )

    created = run_creation.create_question_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        team_id="research-team",
        question_id="SCI-003",
        safety_limits={},
        idempotency_key="formal-create",
        formal_hypothesis_round_id="hround-final",
    )

    assert created["runId"] == "run-created"
    assert len(created_calls) == 1
    run_input = created_calls[0]["run_input"]
    assert (
        run_input["hypothesisConvergenceHandoff"]["confirmedCandidateId"]
        == "candidate-confirmed"
    )


def test_formal_handoff_gate_failure_blocks_run_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_handoff_authorities(monkeypatch, gate_verdicts=_blocked_verdict())
    created_calls: list[dict[str, Any]] = []
    monkeypatch.setattr(
        run_creation, "assert_writes_allowed", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(run_creation, "get_write_store", lambda: object())
    monkeypatch.setattr(
        run_creation,
        "build_question_run_input",
        lambda *_args, **_kwargs: {
            "researchScopeEnvelope": {},
            "catalogScope": {},
        },
    )
    monkeypatch.setattr(
        run_creation,
        "create_run",
        lambda *_args, **kwargs: created_calls.append(kwargs),
    )

    with pytest.raises(hypothesis_first_chain.ClaimBeliefGateBlockedError):
        run_creation.create_question_run(
            CHALLENGE_CUP_WORKFLOW_ID,
            team_id="research-team",
            question_id="SCI-003",
            safety_limits={},
            idempotency_key="formal-create",
            formal_hypothesis_round_id="hround-final",
        )

    assert created_calls == []
