"""Stage-one closure authorities bind to the live hypothesis_design node run.

Integration repair for the challenge-cup hypothesis-first closure node: the
HypothesisRound is generated (and its canonical authorities materialized)
before adjudication and inside whatever node context triggered the review, so
a later ``hypothesis_design`` attempt could find no readable closure authority
and block on ``required_artifact_missing`` even though the chain had fully
converged.  These tests pin the repair:

- an accepted closed round is re-materialized through the same fail-closed
  writer set, re-bound to the CURRENT node run (nodeRunId in every binding and
  identity), and the completion-gate readback then resolves all seven chain
  authority kinds;
- ``core_hypothesis_coherence`` is reuse-only (its verdicts are not persisted
  in the round), so a store row written at generation time is reused and an
  absent one is reported as a missing authority instead of being faked;
- replaying the materialization reuses existing rows (append-only store,
  no ``WorkflowArtifactConflictError``) and writes nothing new;
- the agent-turn path runs the materialization before the completion gate and
  the node verification succeeds;
- a skipped materialization keeps the existing fail-closed blocked semantics
  while naming the chain reason in the blocked problem.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts import PendingAction, SCORE_DIMENSIONS
from core.research.workflow.models import ActorKind
from core.research.workflow.contracts.core_hypothesis_coherence import (
    CORE_HYPOTHESIS_COHERENCE_CHECK_IDS,
    CoreHypothesisCoherenceResult,
)
from core.web.services import team_service
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow import meeting_rounds as meetings
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from core.web.services.team_workflow.research_runtime import (
    workflow_artifact_store,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root

_QUESTION_ID = "SCI-091"
_RUN_ID = "run-stage-one-authority"
_SC_RUN_ID = "sc-stage-one-authority"
_NODE_RUN_ID = "nr-run-stage-one-authority-hypothesis_design-a2"
_PREV_NODE_RUN_ID = "nr-run-stage-one-authority-hypothesis_design-a1"
_SNAPSHOT_HASH = "a" * 64
_MEETING_ID = "meeting-stage-one-authority-1"
_SELECTION_ID = "sel-stage-one-authority"
_REVIEWER = "agent-reviewer-1"

_CHAIN_KINDS_WITH_NODE_BINDING = (
    "dimension_reviews",
    "review_independence",
    "review_disagreement",
    "feedback_iterations",
)
_CHAIN_KINDS_WITH_NODE_IDENTITY = (
    "stage1_research_plan",
    "competition_alignment",
)


def _scope_identity() -> dict[str, str]:
    return {
        "program": "XH-202619",
        "theme": "cc-gpu-operator-001",
        "campaign": "cc-campaign-gpu-operator-001",
        "question": _QUESTION_ID,
        "branch": "main",
        "workflow": "hypothesis_first",
        "agentId": "operator",
        "mode": "formal",
    }


def _env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Isolated project root plus a real team; returns the team id."""
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    team_id = team_service.create_team(
        name="Stage-one node authority 团队",
        purpose="challenge-stage-one-node-authority",
    )["teamId"]
    return team_id


def _seed_evidence_ref(team_id: str) -> str:
    """Seed one readable problem_understanding authority for review rows."""
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        build_canonical_ref,
    )
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    payload = {"summary": "seeded stage-one evidence for dimension rows"}
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="problem_understanding",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload=payload,
    )
    envelope = {
        "teamId": team_id,
        "kind": "problem_understanding",
        "workflowRunId": _RUN_ID,
        "sourceCollectionRunId": _SC_RUN_ID,
        "payload": payload,
    }
    return build_canonical_ref(
        kind="problem_understanding",
        team_id=team_id,
        authority_run_id=_SC_RUN_ID,
        content_hash=canonical_sha256(envelope),
    )


def _seed_closed_round(
    team_id: str,
    *,
    round_id: str,
    accepted: bool,
    revision_envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Seed one closed hypothesis round plus its review meeting (dev review)."""
    evidence_ref = _seed_evidence_ref(team_id)
    meeting = {
        "schemaVersion": 1,
        "meetingRoundId": _MEETING_ID,
        "meetingType": "hypothesis_review",
        "question": _QUESTION_ID,
        "status": "closed",
        **_scope_identity(),
        "inputArtifactRefs": [
            f"hypothesis_selection:{_SELECTION_ID}",
            evidence_ref,
        ],
        "discussionItemRefs": [
            "hypothesis_candidate:cand-a",
            "hypothesis_candidate:cand-b",
        ],
        "inputSnapshotHash": _SNAPSHOT_HASH,
        "selectedCandidateIds": ["cand-a", "cand-b"],
        "modelInvocationReceiptAuthority": {
            "workflowRunId": _RUN_ID,
            "sourceCollectionRunId": _SC_RUN_ID,
            "questionId": _QUESTION_ID,
            "nodeRunId": _PREV_NODE_RUN_ID,
        },
        "discussionScope": {"workflowRunId": _RUN_ID},
    }
    meetings._append_jsonl(meetings._rounds_path(team_id), meeting)

    def _candidate(candidate_id: str, claim: str, reviewer: str) -> dict[str, Any]:
        return {
            "candidateId": candidate_id,
            "claim": claim,
            "rationale": f"rationale for {candidate_id}",
            "differenceFromAlternatives": (
                "bounded proxy on the encoder path"
                if candidate_id == "cand-a"
                else "decoder capacity change instead of a proxy"
            ),
            "lineageRefs": [],
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "reviewedBy": reviewer,
            "status": "reviewed",
            "dimensionReviews": [
                {
                    "hypothesis_id": candidate_id,
                    "dimension": dimension,
                    "rating": "mixed",
                    "rationale": f"{dimension} evidence reviewed for {candidate_id}",
                    "reviewer": reviewer,
                    "evidence_refs": [evidence_ref],
                }
                for dimension in (
                    "evidence_support",
                    "factual_accuracy",
                    "novelty",
                    "falsifiability",
                    "plan_feasibility",
                    "risk_and_ethics",
                    "counterexample_coverage",
                )
            ],
        }

    payload: dict[str, Any] = {
        **_scope_identity(),
        "roundId": round_id,
        "candidates": [
            _candidate(
                "cand-a",
                "A bounded proxy improves reconstruction under noise.",
                _REVIEWER,
            ),
            _candidate(
                "cand-b",
                "A higher-capacity decoder generalizes better on held-out data.",
                "agent-reviewer-2",
            ),
        ],
        "lineage": [{"kind": "candidate", "id": "cand-root-0"}],
        "meetingRefs": [
            {"kind": "meeting_round", "id": _MEETING_ID},
            {"kind": "meeting_digest", "id": f"digest-{round_id}"},
            {"kind": "decision_record", "id": f"decision-{round_id}"},
        ],
        "status": "closed",
        "closedBy": "agent-coordinator",
        "closedAt": "2026-09-01T05:00:00Z",
        "pairwiseComparisons": [
            {
                "comparisonId": f"cmp-{round_id}",
                "leftCandidateId": "cand-a",
                "rightCandidateId": "cand-b",
                "reviewerAgentId": "agent-pairwise",
                "outcome": "left_wins",
                "justification": "cand-a dominates on feasibility and evidence support.",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["cand-a"],
            "dominatedCandidateIds": ["cand-b"],
            "analystAgentId": "agent-pareto",
            "notes": "Pareto front verified over all seven dimensions.",
        },
        "metaReview": {
            "metaReviewId": f"meta-{round_id}",
            "reviewerAgentId": "agent-meta",
            "recommendationCandidateId": "cand-a",
            "rationale": "cand-a is strongest across the review matrix.",
            "riskNotes": "Falsifiability remains weakest.",
            "accepted": accepted,
        },
        "reviewContextId": "ctx-stage-one-authority",
        "executionMode": "dev",
        "positionSeed": "seed-stage-one-authority",
        "roles": {"metareview": "agent-meta"},
        "modelInvocationReceipts": [],
    }
    if revision_envelope is not None:
        payload["revisionEnvelope"] = revision_envelope
    created = hrounds.create_hypothesis_round(team_id, payload)
    return created["round"]


def _seed_coherence_authority(team_id: str) -> dict[str, str]:
    """Write the coherence authority exactly like the review executor does."""
    from core.web.services.team_workflow.research_runtime.core_hypothesis_coherence_artifact_writer import (
        record_core_hypothesis_coherence_artifact,
    )

    def _result(candidate_id: str) -> dict[str, Any]:
        checks = [
            {
                "checkId": check_id,
                "passed": True,
                "rationale": f"{check_id} holds for {candidate_id}.",
                "claimRefs": [f"claim:{candidate_id}"],
            }
            for check_id in CORE_HYPOTHESIS_COHERENCE_CHECK_IDS
        ]
        return CoreHypothesisCoherenceResult.from_review_payload(
            {"checks": checks},
            candidate_id=candidate_id,
            reviewer=_REVIEWER,
            receipt_ref=f"receipt-coherence-{candidate_id}",
        ).to_dict()

    return record_core_hypothesis_coherence_artifact(
        team_id=team_id,
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        review_context_id="ctx-stage-one-authority",
        results=[_result("cand-a"), _result("cand-b")],
        require_receipts=True,
    )


def _revision_envelope() -> dict[str, Any]:
    return {
        "phase": "grounded_revision",
        "feedback": {
            "trigger": "grounded_revision",
            "humanFeedback": "narrow the falsifier to a measurable bound",
            "inputRefs": ["hypothesis_candidate:cand-a:r0"],
            "inputHash": "b" * 64,
        },
        "revision": {
            "changes": ["falsifier narrowed to a measurable latency bound"],
            "unresolvedIssues": ["seed uncertainty documented"],
            "outputRefs": ["hypothesis_candidate:cand-a:r1"],
            "outputHash": "c" * 64,
            "status": "revised",
        },
    }


def _question_authority() -> dict[str, dict[str, Any]]:
    """Canonical approved question detail projected by question_launch."""
    detail = {
        "record": {
            "runId": _RUN_ID,
            "questionId": _QUESTION_ID,
            "schemaVersion": 2,
            "status": "approved",
            "validation": {
                "schemaValidation": "passed",
                "citationValidation": "passed",
                "officialModelCall": True,
            },
        },
        "artifact": {"sha256": "f" * 64, "immutable": True},
        "output": {
            "schema_version": 2,
            "identity": {
                "catalog_id": "science-125-questions-2021",
                "question_id": _QUESTION_ID,
                "question_en": "Canonical question",
            },
            "hypotheses": [
                {
                    "hypothesis_id": "cand-a",
                    "statement": (
                        "A bounded proxy improves reconstruction under noise."
                    ),
                },
                {
                    "hypothesis_id": "cand-b",
                    "statement": (
                        "A higher-capacity decoder generalizes better on "
                        "held-out data."
                    ),
                },
            ],
            "selection": {
                "selected_hypothesis_id": "cand-a",
                "human_gate": {"decision": "approved"},
            },
            "research_plan": {
                "proposal_only": True,
                "objective": "Test the selected hypothesis.",
                "human_gate": {"decision": "approved"},
            },
            "competition_result_view": {
                "problem_statement": "Canonical competition problem.",
                "rationale": "Why the selected hypothesis matters.",
                "technical_details": "Bounded technical approach.",
                "datasets": {"planned": ["dataset-a"], "used": ["not executed"]},
                "methods": ["planned method"],
                "experiments": ["planned experiment"],
                "results": ["not executed"],
                "references": ["source://canonical"],
                "paper_title": "Planned paper",
                "paper_abstract": "Proposal only.",
            },
        },
    }
    return {_QUESTION_ID: detail}


def test_accepted_round_materializes_stage_one_authorities_for_live_node_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        collect_required_artifact_refs,
    )

    team_id = _env(tmp_path, monkeypatch)
    _seed_coherence_authority(team_id)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=True,
        revision_envelope=_revision_envelope(),
    )
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: _question_authority(),
    )

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        input_snapshot_hash=_SNAPSHOT_HASH,
        source_collection_run_id=_SC_RUN_ID,
    )

    assert report["status"] == "materialized", report
    assert report["roundId"] == "hround-stage-one-authority-1"
    assert report["missingKinds"] == []
    assert report["blockerCodes"] == {}
    # The coherence authority is reuse-only: it was seeded exactly like the
    # review executor writes it at generation time and must not be rewritten.
    assert set(report["reusedKinds"]) == {"core_hypothesis_coherence"}
    assert set(report["writtenKinds"]) == set(chain.STAGE_ONE_NODE_AUTHORITY_KINDS) - {
        "core_hypothesis_coherence"
    }

    # Every binding-bearing payload carries the CURRENT node run id.
    for kind in _CHAIN_KINDS_WITH_NODE_BINDING:
        rows = workflow_artifact_store.list_workflow_artifacts(
            team_id, kind=kind, workflow_run_id=_RUN_ID
        )
        assert rows, kind
        assert rows[-1]["payload"]["nodeRunId"] == _NODE_RUN_ID, kind
        assert rows[-1]["payload"]["workflowRunId"] == _RUN_ID
    for kind in _CHAIN_KINDS_WITH_NODE_IDENTITY:
        rows = workflow_artifact_store.list_workflow_artifacts(
            team_id, kind=kind, workflow_run_id=_RUN_ID
        )
        assert rows, kind
        assert rows[-1]["recordId"] == f"{kind}:{_NODE_RUN_ID}:{_QUESTION_ID}"

    # The exact closure readback now resolves all seven chain authorities.
    refs = collect_required_artifact_refs(
        required_kinds=chain.STAGE_ONE_NODE_AUTHORITY_KINDS,
        team_id=team_id,
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
    )
    assert {item["kind"] for item in refs} == set(
        chain.STAGE_ONE_NODE_AUTHORITY_KINDS
    )

    # Idempotent replay: reuse everything, write nothing, never conflict.
    row_counts = {
        kind: len(
            workflow_artifact_store.list_workflow_artifacts(
                team_id, kind=kind, workflow_run_id=_RUN_ID
            )
        )
        for kind in chain.STAGE_ONE_NODE_AUTHORITY_KINDS
    }
    replay = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        input_snapshot_hash=_SNAPSHOT_HASH,
        source_collection_run_id=_SC_RUN_ID,
    )
    assert replay["status"] == "materialized"
    assert replay["writtenKinds"] == []
    assert set(replay["reusedKinds"]) == set(chain.STAGE_ONE_NODE_AUTHORITY_KINDS)
    for kind, count in row_counts.items():
        assert (
            len(
                workflow_artifact_store.list_workflow_artifacts(
                    team_id, kind=kind, workflow_run_id=_RUN_ID
                )
            )
            == count
        )


def test_unaccepted_round_is_skipped_and_writes_nothing(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=True,
    )
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-2",
        accepted=False,
    )
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: _question_authority(),
    )

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        input_snapshot_hash=_SNAPSHOT_HASH,
        source_collection_run_id=_SC_RUN_ID,
    )

    assert report["status"] == "skipped"
    assert report["reason"] == "hypothesis_round_not_accepted"
    # Nothing was written for the live node run: fail-closed, no fake success.
    for kind in chain.STAGE_ONE_NODE_AUTHORITY_KINDS:
        rows = workflow_artifact_store.list_workflow_artifacts(
            team_id, kind=kind, workflow_run_id=_RUN_ID
        )
        assert not rows, kind


def _pending_action(action_id: str) -> PendingAction:
    return PendingAction(
        action_id=action_id,
        run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        node_id="hypothesis_design",
        attempt=2,
        actor_kind=ActorKind.AGENT,
        action_kind="start_agent_task",
        input_snapshot_hash=_SNAPSHOT_HASH,
        input_artifact_refs=(),
        binding_snapshot_id=None,
        budget_policy_hash="",
    )


def test_node_agent_turn_materializes_chain_authority_before_completion_gate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        agent_turn_completion,
        question_launch,
        real_domain_ports,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterResult,
    )
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
    )

    team_id = _env(tmp_path, monkeypatch)
    _seed_coherence_authority(team_id)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=True,
        revision_envelope=_revision_envelope(),
    )
    monkeypatch.setattr(
        question_launch,
        "_approved_details",
        lambda _team_id: _question_authority(),
    )
    # The node's own hypothesis_set output (readable from an earlier attempt).
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="hypothesis_set",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload={"hypotheses": [{"hypothesis_id": "cand-a"}]},
    )

    snapshot = {
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "sourceCollectionRunId": _SC_RUN_ID,
    }
    action = _pending_action("action-stage-one-authority")
    required_kinds = ("hypothesis_set", *chain.STAGE_ONE_NODE_AUTHORITY_KINDS)

    def fake_complete(**kwargs):
        refs = agent_turn_completion.collect_required_artifact_refs(
            required_kinds=kwargs["required_kinds"],
            team_id=kwargs["input_snapshot"]["teamId"],
            workflow_run_id=kwargs["action"].run_id,
            source_collection_run_id=(
                kwargs["input_snapshot"].get("sourceCollectionRunId")
                or kwargs["action"].run_id
            ),
        )
        return agent_turn_completion.AgentTurnResult(
            materialized_refs=tuple(refs),
            handle=kwargs["handle"],
            usage=None,
        )

    ports = real_domain_ports.RealDomainPorts(object())
    monkeypatch.setattr(
        ports, "_run_input_snapshot", lambda _run_id: dict(snapshot)
    )
    monkeypatch.setattr(
        ports,
        "required_artifact_kinds",
        lambda _action: required_kinds,
    )
    monkeypatch.setattr(
        agent_turn_completion, "complete_agent_turn_outputs", fake_complete
    )
    handle = AgentTaskHandle(
        session_id="session-stage-one",
        session_attempt=2,
        task_id="task-stage-one",
        turn_id="turn-stage-one",
    )

    result = ports.execute_agent_turn(action=action, handle=handle)

    assert isinstance(result, agent_turn_completion.AgentTurnResult)
    ref_kinds = {item["kind"] for item in result.materialized_refs}
    assert ref_kinds == set(required_kinds)

    # The exact verify gate that blocked the live run now succeeds.
    adapter = AgentActionAdapter(ports)
    verified = adapter.verify(
        action,
        AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=result.materialized_refs,
            anchor={"actionId": action.action_id},
            usage={"estimate_tokens": 1},
            reserved={"reservationId": "res-stage-one"},
        ),
    )
    assert verified.outcome == "succeeded", verified.problem
    receipts = {item["artifactType"] for item in verified.artifact_receipts}
    assert set(required_kinds) <= receipts


def test_blocked_node_problem_carries_chain_authority_reason(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.web.services.team_workflow.research_runtime import (
        agent_turn_completion,
        real_domain_ports,
    )
    from core.web.services.team_workflow.research_runtime.adapters.domain_adapters import (
        AgentActionAdapter,
    )
    from core.web.services.team_workflow.research_runtime.action_registry import (
        AdapterResult,
    )
    from core.web.services.team_workflow.research_runtime.domain_ports import (
        AgentTaskHandle,
    )

    team_id = _env(tmp_path, monkeypatch)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=False,
    )

    snapshot = {
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "sourceCollectionRunId": _SC_RUN_ID,
    }
    action = _pending_action("action-stage-one-blocked")
    ports = real_domain_ports.RealDomainPorts(object())
    monkeypatch.setattr(
        ports, "_run_input_snapshot", lambda _run_id: dict(snapshot)
    )
    monkeypatch.setattr(
        ports,
        "required_artifact_kinds",
        lambda _action: ("hypothesis_set", *chain.STAGE_ONE_NODE_AUTHORITY_KINDS),
    )
    handle = AgentTaskHandle(
        session_id="session-stage-one",
        session_attempt=2,
        task_id="task-stage-one",
        turn_id="turn-stage-one",
    )

    def empty_completion(**kwargs):
        # No turn output materialized: without the chain authorities the gate
        # must keep blocking exactly as before.
        return agent_turn_completion.AgentTurnResult(
            materialized_refs=(),
            handle=kwargs["handle"],
            usage=None,
        )

    monkeypatch.setattr(
        agent_turn_completion, "complete_agent_turn_outputs", empty_completion
    )

    result = ports.execute_agent_turn(action=action, handle=handle)
    assert result.materialized_refs == ()

    # The materialization hook ran and reports the precise chain reason.
    report = ports.chain_authority_materialization_report(action)
    assert report is not None
    assert report["status"] == "skipped"
    assert report["reason"] == "hypothesis_round_not_accepted"

    adapter = AgentActionAdapter(ports)
    verified = adapter.verify(
        action,
        AdapterResult(
            action_id=action.action_id,
            outcome="succeeded",
            materialized_refs=(),
            anchor={"actionId": action.action_id},
            usage={"estimate_tokens": 1},
            reserved={"reservationId": "res-stage-one"},
        ),
    )
    assert verified.outcome == "blocked"
    assert verified.problem is not None
    assert verified.problem["code"] == "required_artifact_missing"
    chain_summary = verified.problem.get("chainAuthorityMaterialization")
    assert chain_summary["reason"] == "hypothesis_round_not_accepted"
    assert chain_summary["status"] == "skipped"
