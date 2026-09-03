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
- ``core_hypothesis_coherence`` is reused when a store row was already written
  at generation time (formal scope); when the row is absent — the dev/platform
  round case, where the review executor skips the artifact write — the
  authority is recovered from the round's persisted per-candidate verdicts,
  and verdict data that is absent, incomplete, or not fully passed keeps the
  fail-closed missing-authority blocker instead of being faked;
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


def _round_coherence_result(
    candidate_id: str,
    *,
    passed: bool = True,
) -> dict[str, Any]:
    """Per-candidate coherence verdict exactly as a dev-mode round persists it.

    Mirrors the live chain-driven rounds: five canonical checks, an ``llm``
    reviewer and an empty ``receiptRef`` (dev/platform rounds carry no model
    invocation receipts), with the contract self-verifying ``artifactHash``.
    """
    checks = [
        {
            "checkId": check_id,
            "passed": passed,
            "rationale": (
                f"{check_id} holds for {candidate_id}."
                if passed
                else f"{check_id} fails for {candidate_id}."
            ),
            "claimRefs": [f"claim:{candidate_id}"],
        }
        for check_id in CORE_HYPOTHESIS_COHERENCE_CHECK_IDS
    ]
    return CoreHypothesisCoherenceResult.from_review_payload(
        {"checks": checks},
        candidate_id=candidate_id,
        reviewer="llm",
        receipt_ref="",
    ).to_dict()


def _seed_closed_round(
    team_id: str,
    *,
    round_id: str,
    accepted: bool,
    revision_envelope: dict[str, Any] | None = None,
    coherence_passed: bool | None = True,
) -> dict[str, Any]:
    """Seed one closed hypothesis round plus its review meeting (dev review).

    ``coherence_passed=True`` attaches valid all-passed coherence verdicts to
    every candidate (the default live shape); ``False`` attaches failing
    verdicts; ``None`` omits the verdicts entirely (no recoverable data).
    """
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
        candidate = {
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
        if coherence_passed is not None:
            candidate["coreHypothesisCoherence"] = _round_coherence_result(
                candidate_id, passed=coherence_passed
            )
        return candidate

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


def test_dev_mode_round_recovers_coherence_authority_from_round(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev/platform rounds recover the coherence authority from round verdicts.

    A chain-driven review round runs with ``executionMode=dev`` and no model
    invocation receipts, so the review executor never writes the coherence
    artifact at generation time.  The verdicts themselves persist on the round
    candidates, so the node materialization must recover and persist them
    (``require_receipts=False``) instead of blocking; the node verify gate then
    resolves every required ref including the recovered authority.
    """
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
    action = _pending_action("action-stage-one-coherence")
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

    ref_kinds = {item["kind"] for item in result.materialized_refs}
    assert ref_kinds == set(required_kinds)

    # The node verify gate that blocked dev-mode runs now succeeds.
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

    # The recovered authority is the round's persisted verdicts, replayed
    # through the same contract (empty receiptRefs, self-verifying hashes).
    rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="core_hypothesis_coherence", workflow_run_id=_RUN_ID
    )
    assert len(rows) == 1
    payload = rows[-1]["payload"]
    assert payload["reviewContextId"] == "ctx-stage-one-authority"
    assert payload["passed"] is True
    parsed = [
        CoreHypothesisCoherenceResult.from_dict(item)
        for item in payload["results"]
    ]
    assert {item.candidateId for item in parsed} == {"cand-a", "cand-b"}
    assert all(item.passed for item in parsed)
    assert all(item.receiptRef == "" for item in parsed)

    # Idempotent replay: the recovered row is probed and reused, not rewritten.
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
    assert (
        len(
            workflow_artifact_store.list_workflow_artifacts(
                team_id, kind="core_hypothesis_coherence", workflow_run_id=_RUN_ID
            )
        )
        == 1
    )


def test_round_without_coherence_verdicts_stays_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No persisted verdicts on the round: the blocker stays, nothing faked."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=True,
        revision_envelope=_revision_envelope(),
        coherence_passed=None,
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

    assert report["status"] == "blocked"
    assert report["missingKinds"] == ["core_hypothesis_coherence"]
    assert report["blockerCodes"] == {
        "core_hypothesis_coherence": ["core_hypothesis_coherence_authority_missing"]
    }
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="core_hypothesis_coherence", workflow_run_id=_RUN_ID
    )


def test_round_with_failing_coherence_verdict_stays_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A not-fully-passed verdict set is never materialized as satisfied."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_closed_round(
        team_id,
        round_id="hround-stage-one-authority-1",
        accepted=True,
        revision_envelope=_revision_envelope(),
        coherence_passed=False,
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

    assert report["status"] == "blocked"
    assert report["missingKinds"] == ["core_hypothesis_coherence"]
    assert report["blockerCodes"] == {
        "core_hypothesis_coherence": ["core_hypothesis_coherence_authority_missing"]
    }
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="core_hypothesis_coherence", workflow_run_id=_RUN_ID
    )


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


# ---------------------------------------------------------------------------
# Chain-shaped launches: the live run-882610596ddb shape (chain-driven review
# rounds in dev/platform mode, no revisionEnvelope, claim-evidence citations,
# no approved question authority).  The materializer must recover the
# feedback-iteration authority from the chain's own persisted iteration
# evidence, and the launch-shape gate must waive exactly the authorities no
# such launch can ever produce -- with persisted evidence, never faked.
# ---------------------------------------------------------------------------

_ROUND_ID = "hround-stage-one-authority-chain"
_ITER_R1_B = "meeting-stage-one-iter-r1-b"
_ITER_R2_A = "meeting-stage-one-iter-r2-a"
_ITER_R2_B = "meeting-stage-one-iter-r2-b"
_ITER_R3_A = "meeting-stage-one-iter-r3-a"
_ITER_R3_B = "meeting-stage-one-iter-r3-b"
_ITER_REQUEST_1 = "hfcr-iter-one"
_ITER_REQUEST_2 = "hfcr-iter-two"
_ITER_DECISION_1 = "decision-iter-one"
_ITER_DECISION_2 = "decision-iter-two"
_CLAIM_EVIDENCE_REF = "candidate-20260902170937-fb8353ea"
_REQUEST_1_HASH = "b" * 64
_REQUEST_2_HASH = "c" * 64


def _seed_chain_shape_round(team_id: str, *, drop_dimension: str = "") -> dict[str, Any]:
    """Seed the accepted convergence round exactly as a chain launch persists it.

    Differs from ``_seed_closed_round`` in the two live-shape facts: the audit
    rows cite claim-evidence ledger ids (never canonical artifact refs) and no
    input snapshot hash exists anywhere in the chain shape.
    """
    meeting = {
        "schemaVersion": 1,
        "meetingRoundId": _MEETING_ID,
        "meetingType": "hypothesis_review",
        "question": _QUESTION_ID,
        "status": "closed",
        **_scope_identity(),
        "inputArtifactRefs": [f"hypothesis_selection:{_SELECTION_ID}"],
        "discussionItemRefs": [
            "hypothesis_candidate:cand-a",
            "hypothesis_candidate:cand-b",
        ],
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

    def _candidate(candidate_id: str, claim: str) -> dict[str, Any]:
        dimensions = [
            "evidence_support",
            "factual_accuracy",
            "novelty",
            "falsifiability",
            "plan_feasibility",
            "risk_and_ethics",
            "counterexample_coverage",
        ]
        if drop_dimension:
            dimensions = [item for item in dimensions if item != drop_dimension]
        return {
            "candidateId": candidate_id,
            "claim": claim,
            "rationale": f"rationale for {candidate_id}",
            "differenceFromAlternatives": (
                "bounded proxy on the encoder path"
                if candidate_id == "cand-a"
                else "decoder capacity change instead of a proxy"
            ),
            "lineageRefs": [_CLAIM_EVIDENCE_REF],
            "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
            "reviewedBy": _REVIEWER,
            "status": "reviewed",
            "coreHypothesisCoherence": _round_coherence_result(
                candidate_id, passed=True
            ),
            "dimensionReviews": [
                {
                    "hypothesis_id": candidate_id,
                    "dimension": dimension,
                    "rating": "mixed",
                    "rationale": f"{dimension} evidence reviewed for {candidate_id}",
                    "reviewer": _REVIEWER,
                    "evidence_refs": [_CLAIM_EVIDENCE_REF],
                }
                for dimension in dimensions
            ],
        }

    payload: dict[str, Any] = {
        **_scope_identity(),
        "roundId": _ROUND_ID,
        "candidates": [
            _candidate(
                "cand-a",
                "A bounded proxy improves reconstruction under noise.",
            ),
            _candidate(
                "cand-b",
                "A higher-capacity decoder generalizes better on held-out data.",
            ),
        ],
        "lineage": [{"kind": "candidate", "id": "cand-root-0"}],
        "meetingRefs": [
            {"kind": "meeting_round", "id": _MEETING_ID},
            {"kind": "meeting_round", "id": _ITER_R3_A},
            {"kind": "meeting_round", "id": _ITER_R3_B},
            {"kind": "meeting_digest", "id": "digest-iter-r3-a"},
            {"kind": "meeting_digest", "id": "digest-iter-r3-b"},
            {"kind": "decision_record", "id": _ITER_DECISION_2},
        ],
        "status": "closed",
        "closedBy": "agent-coordinator",
        "closedAt": "2026-09-01T05:00:00Z",
        "pairwiseComparisons": [
            {
                "comparisonId": f"cmp-{_ROUND_ID}",
                "leftCandidateId": "cand-a",
                "rightCandidateId": "cand-b",
                "reviewerAgentId": "agent-pairwise",
                "outcome": "left_wins",
                "justification": "cand-a dominates on feasibility and evidence support.",
            }
        ],
        "pareto": {
            "paretoFrontCandidateIds": ["cand-a", "cand-b"],
            "dominatedCandidateIds": [],
            "analystAgentId": "agent-pareto",
            "notes": "Both candidates share the Pareto front.",
        },
        "metaReview": {
            "metaReviewId": f"meta-{_ROUND_ID}",
            "reviewerAgentId": "agent-meta",
            "recommendationCandidateId": "cand-a",
            "rationale": "cand-a is strongest across the review matrix.",
            "riskNotes": "Falsifiability remains weakest.",
            "accepted": True,
        },
        "reviewContextId": "ctx-stage-one-authority",
        "executionMode": "dev",
        "positionSeed": "seed-stage-one-authority",
        "roles": {"metareview": "agent-meta"},
        "modelInvocationReceipts": [],
    }
    created = hrounds.create_hypothesis_round(team_id, payload)
    return created["round"]


def _seed_chain_iteration_evidence(
    team_id: str,
    *,
    complete_requests: bool = True,
) -> None:
    """Seed the chain ledger's review-round iteration history (r1 -> r2 -> r3).

    Mirrors the live run-882610596ddb ledger: per-candidate review-round links,
    one shared completed collection request per consecutive round pair, and the
    adopted ``request_new_evidence`` decision that opened it.
    """
    round_digests = {
        _MEETING_ID: ("digest-iter-r1-a", "1" * 64),
        _ITER_R1_B: ("digest-iter-r1-b", "2" * 64),
        _ITER_R2_A: ("digest-iter-r2-a", "3" * 64),
        _ITER_R2_B: ("digest-iter-r2-b", "4" * 64),
        _ITER_R3_A: ("digest-iter-r3-a", "5" * 64),
        _ITER_R3_B: ("digest-iter-r3-b", "6" * 64),
    }
    request_by_meeting = {
        _ITER_R2_A: _ITER_REQUEST_1,
        _ITER_R2_B: _ITER_REQUEST_1,
        _ITER_R3_A: _ITER_REQUEST_2,
        _ITER_R3_B: _ITER_REQUEST_2,
    }
    for meeting_id, (digest_id, content_hash) in round_digests.items():
        meetings._append_jsonl(
            meetings._rounds_path(team_id),
            {
                "schemaVersion": 1,
                "meetingRoundId": meeting_id,
                "meetingType": "hypothesis_review",
                "question": _QUESTION_ID,
                "status": "closed",
                **_scope_identity(),
                "inputArtifactRefs": [f"hypothesis_selection:{_SELECTION_ID}"],
                "discussionItemRefs": ["hypothesis_candidate:cand-a"],
                "selectedCandidateIds": ["cand-a", "cand-b"],
                "digestId": digest_id,
                "discussionScope": {"workflowRunId": _RUN_ID},
                "modelInvocationReceiptAuthority": {
                    "workflowRunId": _RUN_ID,
                    "sourceCollectionRunId": _SC_RUN_ID,
                    "questionId": _QUESTION_ID,
                    "nodeRunId": _PREV_NODE_RUN_ID,
                },
                "collectionRequestId": request_by_meeting.get(meeting_id, ""),
            },
        )
        meetings._append_jsonl(
            meetings._digests_path(team_id),
            {
                "schemaVersion": 1,
                "digestId": digest_id,
                "meetingRoundId": meeting_id,
                "contentHash": content_hash,
                "risks": [
                    f"unresolved review risk recorded at {meeting_id}",
                ],
            },
        )

    links = [
        ("cand-a", 1, _MEETING_ID, ""),
        ("cand-b", 1, _ITER_R1_B, ""),
        ("cand-a", 2, _ITER_R2_A, _ITER_REQUEST_1),
        ("cand-b", 2, _ITER_R2_B, _ITER_REQUEST_1),
        ("cand-a", 3, _ITER_R3_A, _ITER_REQUEST_2),
        ("cand-b", 3, _ITER_R3_B, _ITER_REQUEST_2),
    ]
    for order, (candidate_id, round_index, meeting_id, request_id) in enumerate(links):
        chain._append_jsonl(
            chain._storage_path(team_id),
            {
                "recordKind": "review_round_link",
                "linkId": f"hf-link-{order}",
                "questionId": _QUESTION_ID,
                "selectionId": _SELECTION_ID,
                "candidateId": candidate_id,
                "candidateOrder": order % 2,
                "roundIndex": round_index,
                "meetingRoundId": meeting_id,
                "previousMeetingRoundId": "",
                "collectionRequestId": request_id,
                "createdAt": "2026-09-01T06:00:00Z",
            },
        )
    for decision_id in (_ITER_DECISION_1, _ITER_DECISION_2):
        meetings._append_jsonl(
            meetings._decisions_path(team_id),
            {
                "schemaVersion": 2,
                "decisionId": decision_id,
                "decision": "request_new_evidence",
                "status": "adopted",
                "decidedBy": "operator",
                "rationale": (
                    "review found a falsifiability gap that needs new evidence"
                ),
                "candidateRefs": ["cand-a", "cand-b"],
                "meetingRoundId": _MEETING_ID,
            },
        )
    for request_id, decision_id, request_hash in (
        (_ITER_REQUEST_1, _ITER_DECISION_1, _REQUEST_1_HASH),
        (_ITER_REQUEST_2, _ITER_DECISION_2, _REQUEST_2_HASH),
    ):
        chain._append_jsonl(
            chain._storage_path(team_id),
            {
                "recordKind": "collection_request",
                "requestId": request_id,
                "questionId": _QUESTION_ID,
                "decisionId": decision_id,
                "collectionRunId": f"dprun-for-{request_id}",
                "collectionRunStatus": (
                    "completed" if complete_requests else "running"
                ),
                "handoffRef": (
                    f"source_collection_run:dprun-for-{request_id}"
                    if complete_requests
                    else ""
                ),
                "requestHash": request_hash,
                "hypothesisCandidateIds": ["cand-a", "cand-b"],
                "meetingRoundId": _MEETING_ID,
                "searchEnvelope": {
                    "keywords": ["roofline model", "dennard scaling"],
                },
            },
        )


def _ready_fan_in() -> dict[str, Any]:
    return {
        "status": "ready",
        "selectionId": _SELECTION_ID,
        "meetings": [],
        "selectedCandidateIds": ["cand-a", "cand-b"],
    }


def test_chain_iteration_feedback_recovered_for_live_node_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No revisionEnvelope: the authority recovers from chain iteration evidence.

    The chain-driven review shape appends its iteration history to the
    review-round link / collection-request / decision ledgers, so the
    materializer recovers it and replays the canonical writer instead of
    blocking on ``hypothesis_revision_evidence_missing``.
    """
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime.human_gate_artifacts import (
        canonical_sha256,
    )

    team_id = _env(tmp_path, monkeypatch)
    _seed_chain_shape_round(team_id)
    _seed_chain_iteration_evidence(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    monkeypatch.setattr(
        chain, "_review_meeting_fan_in_group", lambda _team, _meeting: _ready_fan_in()
    )

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
    )

    assert report["status"] == "blocked", report
    # feedback_iterations is now real; the other three are the live run's
    # structural blockers and stay missing without a launch-shape waiver.
    assert "feedback_iterations" in report["writtenKinds"]
    assert report["missingKinds"] == [
        "dimension_reviews",
        "stage1_research_plan",
        "competition_alignment",
    ]
    assert "feedback_iterations" not in report["blockerCodes"]

    rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="feedback_iterations", workflow_run_id=_RUN_ID
    )
    assert [row["payload"]["iterationRound"] for row in rows] == [1, 2]
    assert [row["payload"]["revisionPhase"] for row in rows] == [
        "grounded_revision",
        "review_revision",
    ]
    first = rows[0]["payload"]
    assert first["nodeId"] == "hypothesis_design"
    assert first["nodeRunId"] == _NODE_RUN_ID
    assert first["feedbackIteration"]["trigger"] == "request_new_evidence"
    assert first["inputHash"] == _REQUEST_1_HASH
    # The output hash is the derived content address over the persisted
    # round-2 digest hashes, never an invented value.
    assert first["outputHash"] == canonical_sha256(["3" * 64, "4" * 64])
    assert first["outputRefs"] == [
        f"meeting_round:{_ITER_R2_A}",
        f"meeting_round:{_ITER_R2_B}",
        "meeting_digest:digest-iter-r2-a",
        "meeting_digest:digest-iter-r2-b",
    ]

    # Idempotent replay: the recovered rows are probed and reused.
    replay = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
    )
    assert "feedback_iterations" in replay["reusedKinds"]
    assert "feedback_iterations" not in replay["writtenKinds"]
    assert (
        len(
            workflow_artifact_store.list_workflow_artifacts(
                team_id, kind="feedback_iterations", workflow_run_id=_RUN_ID
            )
        )
        == 2
    )


def test_hypothesis_first_launch_waives_unproducible_kinds_with_evidence(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live chain shape must not deadlock on structurally absent sources.

    A hypothesis-first launch never creates an approved question authority and
    its review rows cite the claim-evidence ledger, so the shape gate waives
    exactly those kinds -- each with its persisted-evidence reason -- while
    every materializable kind still lands.  Waived kinds stay in
    ``blockerCodes``.
    """
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime.stage_one_shape_gate import (
        REASON_QUESTION_AUTHORITY_SOURCE_ABSENT,
        REASON_ROUND_ROWS_PERSISTED_ON_CHAIN_ROUND,
    )

    team_id = _env(tmp_path, monkeypatch)
    _seed_chain_shape_round(team_id)
    _seed_chain_iteration_evidence(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    monkeypatch.setattr(
        chain, "_review_meeting_fan_in_group", lambda _team, _meeting: _ready_fan_in()
    )
    snapshot = {
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "researchObjectiveContract": {"hypothesisFirst": True},
    }

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        input_snapshot=snapshot,
    )

    assert report["status"] == "materialized", report
    assert report["missingKinds"] == []
    assert report["downgradedKinds"] == {
        "dimension_reviews": REASON_ROUND_ROWS_PERSISTED_ON_CHAIN_ROUND,
        "stage1_research_plan": REASON_QUESTION_AUTHORITY_SOURCE_ABSENT,
        "competition_alignment": REASON_QUESTION_AUTHORITY_SOURCE_ABSENT,
    }
    # The real underlying evidence for each waiver stays on the record.
    assert report["blockerCodes"]["stage1_research_plan"] == [
        "stage_one_question_authority_missing"
    ]
    assert "dimension_reviews" in report["blockerCodes"]
    assert set(report["satisfiedKinds"]) == {
        "review_independence",
        "review_disagreement",
        "feedback_iterations",
        "core_hypothesis_coherence",
    }


def test_question_driven_launch_never_waives(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the hypothesis-first marker the gate demand stays complete."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_chain_shape_round(team_id)
    _seed_chain_iteration_evidence(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    monkeypatch.setattr(
        chain, "_review_meeting_fan_in_group", lambda _team, _meeting: _ready_fan_in()
    )
    snapshot = {
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "researchObjectiveContract": {"hypothesisFirst": False},
    }

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        input_snapshot=snapshot,
    )

    assert report["status"] == "blocked"
    assert report["missingKinds"] == [
        "dimension_reviews",
        "stage1_research_plan",
        "competition_alignment",
    ]
    assert "downgradedKinds" not in report


def test_incomplete_round_rows_keep_dimension_reviews_demanded(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The waiver demands the complete persisted audit, not any round."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_chain_shape_round(team_id, drop_dimension="novelty")
    _seed_chain_iteration_evidence(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    monkeypatch.setattr(
        chain, "_review_meeting_fan_in_group", lambda _team, _meeting: _ready_fan_in()
    )
    snapshot = {
        "teamId": team_id,
        "questionId": _QUESTION_ID,
        "researchObjectiveContract": {"hypothesisFirst": True},
    }

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        input_snapshot=snapshot,
    )

    assert report["status"] == "blocked"
    assert "dimension_reviews" in report["missingKinds"]
    assert set(report.get("downgradedKinds") or {}) == {
        "stage1_research_plan",
        "competition_alignment",
    }


def test_chain_iteration_recovery_stays_fail_closed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An incomplete collection request can never become iteration evidence."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _seed_chain_shape_round(team_id)
    _seed_chain_iteration_evidence(team_id, complete_requests=False)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    monkeypatch.setattr(
        chain, "_review_meeting_fan_in_group", lambda _team, _meeting: _ready_fan_in()
    )

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
    )

    assert report["status"] == "blocked"
    assert "feedback_iterations" in report["missingKinds"]
    assert report["blockerCodes"]["feedback_iterations"] == [
        "hypothesis_revision_evidence_missing"
    ]
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="feedback_iterations", workflow_run_id=_RUN_ID
    )
