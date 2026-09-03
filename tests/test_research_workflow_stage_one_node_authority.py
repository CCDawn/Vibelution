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

from collections.abc import Sequence
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

# Live real-batch shapes: bare source-candidate evidence ids (no canonical
# scheme), review round meetings r1..r3 per candidate, no revision envelope.
_BARE_SOURCE_IDS = (
    "candidate-20260902090000-aaaa0001",
    "candidate-20260902090000-aaaa0002",
    "candidate-20260902090000-aaaa0003",
    "candidate-20260902090000-aaaa0004",
)
_REVIEW_DIMENSIONS = (
    "evidence_support",
    "factual_accuracy",
    "novelty",
    "falsifiability",
    "plan_feasibility",
    "risk_and_ethics",
    "counterexample_coverage",
)
_REAL_BATCH_CANDIDATES = ("cand-a", "cand-b")
_REVIEW_SELECTION_ID = "hsel-stage-one-real-batch"
_REVIEW_PREFIX = "hf-review-hsel-stage-one-real-batch"
_CANDGEN_MEETING_ID = "hf-candgen-stage-one-real-batch-r1"


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
# Real-batch (chain-driven dev/platform round) authority recovery.
#
# The live real-batch topology never creates legacy question-run records,
# formal revision envelopes, or canonical evidence refs, so three authorities
# blocked: stage1_research_plan/competition_alignment (no question authority),
# dimension_reviews (bare candidate evidence refs), and feedback_iterations
# (no revision envelope despite recorded r1→rN review rounds).  The seeds
# below replicate the exact live shapes read from the field instance.


def _fake_candidate_store(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sc_run_id: str,
    candidate_ids: Sequence[str],
    duplicate_across_runs: bool = False,
) -> None:
    """Serve live-shaped source_manifest rows from the team candidate store."""
    rows = [
        {
            "candidateId": candidate_id,
            "candidateType": "source_manifest",
            "title": f"source {candidate_id}",
            "sourceUrl": f"https://example.com/{candidate_id}",
            "metadata": {
                "sourceCollectionRunId": sc_run_id,
                "workflowRunId": _RUN_ID,
            },
        }
        for candidate_id in candidate_ids
    ]
    if duplicate_across_runs and rows:
        ambiguous = dict(rows[0])
        ambiguous["metadata"] = {
            "sourceCollectionRunId": f"{sc_run_id}-other",
            "workflowRunId": _RUN_ID,
        }
        rows.append(ambiguous)

    def fake_list_candidate_store(
        team_id: str, limit: int = 500, *, run_id: str = ""
    ):
        _ = (team_id, limit)
        if run_id and run_id != sc_run_id:
            return {"candidates": []}
        return {"candidates": [dict(item) for item in rows]}

    monkeypatch.setattr(
        "core.web.services.team_workflow.source_collection.candidates."
        "list_candidate_store",
        fake_list_candidate_store,
    )


def _seed_review_meeting(
    team_id: str,
    *,
    meeting_round_id: str,
    candidate_id: str,
) -> None:
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 1,
            "meetingRoundId": meeting_round_id,
            "meetingType": "hypothesis_review",
            "question": _QUESTION_ID,
            "status": "closed",
            "closedBy": "agent-coordinator",
            **_scope_identity(),
            "inputArtifactRefs": [f"hypothesis_selection:{_REVIEW_SELECTION_ID}"],
            "discussionItemRefs": [f"hypothesis_candidate:{candidate_id}"],
            "inputSnapshotHash": _SNAPSHOT_HASH,
            "modelInvocationReceiptAuthority": {
                "workflowRunId": _RUN_ID,
                "sourceCollectionRunId": _SC_RUN_ID,
                "questionId": _QUESTION_ID,
                "nodeRunId": _PREV_NODE_RUN_ID,
            },
            "digestId": f"digest-{meeting_round_id}",
            "decisionRefs": [f"decision-{meeting_round_id}"],
            "discussionScope": {
                "candidateId": candidate_id,
                "kind": "candidate_review",
                "questionId": _QUESTION_ID,
                "selectionId": _REVIEW_SELECTION_ID,
                "workflowRunId": _RUN_ID,
                "workflowNodeId": "hypothesis_design",
                "version": 1,
            },
        },
    )


def _seed_review_digest(
    team_id: str,
    *,
    meeting_round_id: str,
    candidate_id: str,
    statement: str,
    with_proposal: bool,
) -> None:
    digest_id = f"digest-{meeting_round_id}"
    meetings._append_jsonl(
        meetings._digests_path(team_id),
        {
            "schemaVersion": 1,
            "digestId": digest_id,
            "meetingRoundId": meeting_round_id,
            "summary": f"review round summary for {candidate_id}",
            "proposedCandidates": (
                [
                    {
                        "candidateId": candidate_id,
                        "statement": statement,
                        "rationale": f"{statement} (mechanism)",
                        "testablePrediction": (
                            f"{statement} predicts a measurable delta"
                        ),
                        "falsifier": (
                            f"{statement} is refuted when the delta is absent"
                        ),
                        "axisProfile": {"mechanism": f"axis-{statement}"},
                        "lineageRefs": list(_BARE_SOURCE_IDS),
                        "proposedBy": "agent-coordinator",
                    }
                ]
                if with_proposal
                else []
            ),
            "decisionRefs": [f"decision-{meeting_round_id}"],
        },
    )
    meetings._append_jsonl(
        meetings._decisions_path(team_id),
        {
            "schemaVersion": 1,
            "decisionId": f"decision-{meeting_round_id}",
            "meetingRoundId": meeting_round_id,
            "candidateRefs": [candidate_id],
            "decision": "request_new_evidence",
            "decidedBy": "operator-console",
            "rationale": (
                f"round {meeting_round_id}: evidence requests stay open for "
                f"{candidate_id}; lineage must close before promotion"
            ),
            "evidenceRefs": [f"meeting_round:{meeting_round_id}"],
        },
    )


def _seed_review_round_link(
    team_id: str,
    *,
    meeting_round_id: str,
    round_index: int,
    candidate_id: str,
    candidate_order: int,
    created_at: str,
) -> None:
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": "review_round_link",
            "linkId": f"hf-link-{meeting_round_id}",
            "meetingRoundId": meeting_round_id,
            "selectionId": _REVIEW_SELECTION_ID,
            "questionId": _QUESTION_ID,
            "roundIndex": round_index,
            "candidateId": candidate_id,
            "candidateOrder": candidate_order,
            "createdAt": created_at,
        },
    )


def _review_meeting_id(candidate_id: str, round_index: int) -> str:
    return (
        f"{_REVIEW_PREFIX}-{candidate_id.replace('cand-', '')}-r{round_index}"
    )


def _seed_real_batch_chain(
    team_id: str,
    *,
    rounds: int,
    proposal_rounds: Sequence[int] = (1, 2),
) -> None:
    """Seed the live real-batch review chain shape around one accepted round.

    ``rounds`` review meetings exist per candidate (each closed with digest +
    decision); ``proposal_rounds`` are the rounds whose digest proposes a
    revised candidate.  The ledger candidates carry bare lineage ids exactly
    like the field instance.
    """
    from core.web.services.team_workflow import hypothesis_selection as selections

    selections._append_jsonl(
        selections._storage_path(team_id),
        {
            "schemaVersion": 1,
            "selectionId": _REVIEW_SELECTION_ID,
            "questionId": _QUESTION_ID,
            "workflowRunId": _RUN_ID,
            "selectedCandidateIds": list(_REAL_BATCH_CANDIDATES),
            "selectionHash": "2036c3a527714398",
        },
    )
    # Candidate generation meeting + ledger candidates (round-0 input state).
    meetings._append_jsonl(
        meetings._rounds_path(team_id),
        {
            "schemaVersion": 1,
            "meetingRoundId": _CANDGEN_MEETING_ID,
            "meetingType": "hypothesis_candidate_generation",
            "question": _QUESTION_ID,
            "status": "closed",
            **_scope_identity(),
            "modelInvocationReceiptAuthority": {
                "workflowRunId": _RUN_ID,
                "questionId": _QUESTION_ID,
            },
        },
    )
    for order, candidate_id in enumerate(_REAL_BATCH_CANDIDATES):
        chain._append_jsonl(
            chain._storage_path(team_id),
            {
                "schemaVersion": 1,
                "recordKind": "hypothesis_candidate",
                "candidateId": candidate_id,
                "questionId": _QUESTION_ID,
                "meetingRoundId": _CANDGEN_MEETING_ID,
                "statement": f"generated hypothesis {candidate_id}",
                "rationale": f"generated mechanism for {candidate_id}",
                "testablePrediction": f"{candidate_id} predicts a measurable delta",
                "falsifier": (
                    f"{candidate_id} is refuted when the delta is absent"
                ),
                "axisProfile": {"mechanism": f"generated axis for {candidate_id}"},
                "lineageRefs": list(_BARE_SOURCE_IDS),
                "candidateAuthority": "formal_grounded_candidate",
                "revisionOrdinal": 1,
            },
        )
        _seed_review_round_link(
            team_id,
            meeting_round_id=_CANDGEN_MEETING_ID,
            round_index=0,
            candidate_id=candidate_id,
            candidate_order=order,
            created_at="2026-09-02T09:00:00.000000Z",
        )
    for round_index in range(1, rounds + 1):
        for order, candidate_id in enumerate(_REAL_BATCH_CANDIDATES):
            meeting_round_id = _review_meeting_id(candidate_id, round_index)
            _seed_review_meeting(
                team_id,
                meeting_round_id=meeting_round_id,
                candidate_id=candidate_id,
            )
            _seed_review_digest(
                team_id,
                meeting_round_id=meeting_round_id,
                candidate_id=candidate_id,
                statement=f"revised r{round_index} hypothesis {candidate_id}",
                with_proposal=round_index in proposal_rounds,
            )
            _seed_review_round_link(
                team_id,
                meeting_round_id=meeting_round_id,
                round_index=round_index,
                candidate_id=candidate_id,
                candidate_order=order,
                created_at=(
                    f"2026-09-02T10:{round_index:02d}:{order:02d}.000000Z"
                ),
            )


def _real_batch_candidate(
    candidate_id: str,
    lineage_refs: Sequence[str],
) -> dict[str, Any]:
    """Round candidate in the live real-batch shape: bare evidence refs."""
    rows = []
    for index, dimension in enumerate(_REVIEW_DIMENSIONS):
        # Live shape: analysis rows cite bare source ids; every third row
        # (novelty / risk_and_ethics) cites nothing at all.
        refs = (
            []
            if index % 3 == 2
            else [lineage_refs[index % len(lineage_refs)]] if lineage_refs else []
        )
        rows.append(
            {
                "hypothesis_id": candidate_id,
                "dimension": dimension,
                "rating": "mixed",
                "rationale": f"{dimension} reviewed for {candidate_id}",
                "reviewer": _REVIEWER,
                "evidence_refs": list(refs),
            }
        )
    return {
        "candidateId": candidate_id,
        "claim": f"generated hypothesis {candidate_id}",
        "rationale": f"generated mechanism for {candidate_id}",
        "differenceFromAlternatives": f"{candidate_id} changes the mechanism axis",
        "lineageRefs": list(lineage_refs),
        "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
        "reviewedBy": _REVIEWER,
        "status": "reviewed",
        "dimensionReviews": rows,
        "coreHypothesisCoherence": _round_coherence_result(candidate_id),
    }


def _seed_real_batch_round(
    team_id: str,
    *,
    round_id: str,
    lineage: dict[str, list[str]] | None = None,
    binding_round_index: int = 2,
) -> dict[str, Any]:
    """Accepted closed round in the live real-batch shape (no envelope)."""
    resolved_lineage = lineage or {
        candidate_id: list(_BARE_SOURCE_IDS)
        for candidate_id in _REAL_BATCH_CANDIDATES
    }
    meeting_refs: list[dict[str, str]] = []
    for candidate_id in _REAL_BATCH_CANDIDATES:
        meeting_id = _review_meeting_id(candidate_id, binding_round_index)
        meeting_refs.append({"kind": "meeting_round", "id": meeting_id})
        meeting_refs.append(
            {"kind": "meeting_digest", "id": f"digest-{meeting_id}"}
        )
        meeting_refs.append(
            {"kind": "decision_record", "id": f"decision-{meeting_id}"}
        )
    payload: dict[str, Any] = {
        **_scope_identity(),
        "roundId": round_id,
        "candidates": [
            _real_batch_candidate(
                candidate_id,
                resolved_lineage.get(candidate_id) or [],
            )
            for candidate_id in _REAL_BATCH_CANDIDATES
        ],
        "lineage": [{"kind": "candidate", "id": "cand-root-0"}],
        "meetingRefs": meeting_refs,
        "status": "closed",
        "closedBy": "agent-coordinator",
        "closedAt": "2026-09-02T12:00:00Z",
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
            "accepted": True,
        },
        "reviewContextId": "ctx-stage-one-real-batch",
        "executionMode": "dev",
        "positionSeed": "seed-stage-one-real-batch",
        "roles": {"metareview": "agent-meta"},
        "modelInvocationReceipts": [],
    }
    return hrounds.create_hypothesis_round(team_id, payload)["round"]


def _seed_problem_understanding(team_id: str) -> None:
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="problem_understanding",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload={
            "scope": (
                "bounded live question scope for the real-batch stage-one "
                "projection"
            ),
            "assumptions": ["catalog entry SCI-091 seeds the theme"],
            "subquestions": [
                "sub-question one for the real-batch plan",
                "sub-question two for the real-batch plan",
            ],
        },
    )


def _list_dimension_rows(team_id: str) -> list[dict[str, Any]]:
    rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )
    return list(rows[-1]["payload"]["dimensionReviews"]) if rows else []


def test_real_batch_chain_materializes_all_authorities_from_live_records(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live real-batch shape closes all seven chain authorities.

    Bare candidate evidence ids repair to the verified source_candidate_batch
    canonical ref, empty review rows inherit the candidate's mapped lineage,
    the r1→r2 review rounds replay as grounded+review feedback iterations, and
    the plan/alignment pair projects from catalog + problem understanding +
    the accepted round — with no legacy question-run record anywhere.
    """
    from core.web.services.team_workflow.research_runtime import question_launch
    from core.web.services.team_workflow.research_runtime.agent_turn_completion import (
        collect_required_artifact_refs,
    )
    from core.web.services.team_workflow.research_runtime.artifact_readback_registry import (
        parse_canonical_ref,
        read_domain_artifact,
    )

    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=3)
    _seed_real_batch_round(team_id, round_id="hround-stage-one-real-batch-1")
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    assert report["missingKinds"] == []
    assert report["blockerCodes"] == {}
    assert set(report["writtenKinds"]) == set(chain.STAGE_ONE_NODE_AUTHORITY_KINDS)
    # The ref repair is auditable: bare ids were rewritten and empty rows
    # inherited the candidates' mapped lineage.
    assert report["dimensionRefRepair"]["repairedRows"] > 0
    assert report["dimensionRefRepair"]["inheritedRows"] > 0
    assert report["dimensionRefRepair"]["unresolvedRefs"] == []

    # Every dimension row now cites readable canonical refs only.
    for row in _list_dimension_rows(team_id):
        assert row["evidence_refs"], row
        for ref in row["evidence_refs"]:
            parsed = parse_canonical_ref(ref)
            assert parsed is not None and parsed.get("legacy") is None, ref
            assert read_domain_artifact(ref) is not None, ref

    # The recorded r1→r2 review chain replays as grounded+review iterations
    # with continuous parent→child hashes bound to real record ids.
    feedback_rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="feedback_iterations", workflow_run_id=_RUN_ID
    )
    assert [row["payload"]["iterationRound"] for row in feedback_rows] == [1, 2]
    assert [row["payload"]["revisionPhase"] for row in feedback_rows] == [
        "grounded_revision",
        "review_revision",
    ]
    first_envelope = feedback_rows[0]["payload"]["revisionEnvelope"]
    second_envelope = feedback_rows[1]["payload"]["revisionEnvelope"]
    assert second_envelope["parentOutput"]["sha256"] == (
        first_envelope["childOutput"]["sha256"]
    )
    input_refs = feedback_rows[0]["payload"]["inputRefs"]
    assert f"hypothesis_selection:{_REVIEW_SELECTION_ID}" in input_refs
    assert any(ref.startswith("meeting_round:") for ref in input_refs)
    assert any(ref.startswith("decision_record:") for ref in input_refs)

    # The plan/alignment pair carries the frozen catalog identity and the
    # accepted-round approval, and stays proposal-only.
    plan_rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="stage1_research_plan", workflow_run_id=_RUN_ID
    )
    assert plan_rows[-1]["payload"]["proposal_only"] is True
    assert plan_rows[-1]["payload"]["human_gate"]["decision"] == "approved"
    alignment_rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="competition_alignment", workflow_run_id=_RUN_ID
    )
    alignment_payload = alignment_rows[-1]["payload"]
    assert alignment_payload["questionIdentity"]["catalog_id"] == (
        "science-125-questions-2021"
    )
    assert alignment_payload["questionIdentity"]["question_id"] == _QUESTION_ID
    assert alignment_payload["selectedHypothesis"]["hypothesisId"] == "cand-a"
    assert "officialRequirementMatrix" in alignment_payload

    # The exact closure readback resolves all eight required kinds.
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="hypothesis_set",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload={"hypotheses": [{"hypothesis_id": "cand-a"}]},
    )
    refs = collect_required_artifact_refs(
        required_kinds=("hypothesis_set", *chain.STAGE_ONE_NODE_AUTHORITY_KINDS),
        team_id=team_id,
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
    )
    assert {item["kind"] for item in refs} == {
        "hypothesis_set",
        *chain.STAGE_ONE_NODE_AUTHORITY_KINDS,
    }

    # Idempotent replay: everything reusable, nothing rewritten.
    row_counts = {
        kind: len(
            workflow_artifact_store.list_workflow_artifacts(
                team_id, kind=kind, workflow_run_id=_RUN_ID
            )
        )
        for kind in ("hypothesis_set", *chain.STAGE_ONE_NODE_AUTHORITY_KINDS)
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


def test_real_batch_bare_refs_stay_fail_closed_without_unique_mapping(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ambiguous store mappings keep the writer's ref blockers, nothing faked."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    # The same bare id scoped to two runs is ambiguous, so no unique canonical
    # mapping exists and the rows must stay untouched.
    _fake_candidate_store(
        monkeypatch,
        sc_run_id=_SC_RUN_ID,
        candidate_ids=_BARE_SOURCE_IDS,
        duplicate_across_runs=True,
    )
    _seed_real_batch_chain(team_id, rounds=3)
    _seed_real_batch_round(team_id, round_id="hround-stage-one-real-batch-1")
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    dimension_blockers = set(report["blockerCodes"]["dimension_reviews"])
    assert dimension_blockers & {
        "dimension_review_evidence_ref_invalid",
        "dimension_review_evidence_refs_missing",
    }
    assert report["dimensionRefRepair"]["unresolvedRefs"]
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )
    # The other recoveries are independent and still materialize.
    assert "stage1_research_plan" in report["satisfiedKinds"]
    assert "feedback_iterations" in report["satisfiedKinds"]


def test_real_batch_empty_rows_stay_fail_closed_without_lineage(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inheritable-empty row without mappable lineage cannot be satisfied."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=3)
    # cand-b has no lineage at all: its empty novelty/risk rows cannot inherit
    # any evidence, so the writer's refs_missing blocker must stay.
    _seed_real_batch_round(
        team_id,
        round_id="hround-stage-one-real-batch-1",
        lineage={"cand-a": list(_BARE_SOURCE_IDS), "cand-b": []},
    )
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    assert "dimension_review_evidence_refs_missing" in set(
        report["blockerCodes"]["dimension_reviews"]
    )
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="dimension_reviews", workflow_run_id=_RUN_ID
    )


def test_real_batch_plan_fallback_stays_fail_closed_without_live_authorities(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No problem-understanding artifact: the plan blocker stays, others pass."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=3)
    _seed_real_batch_round(team_id, round_id="hround-stage-one-real-batch-1")
    # Deliberately NO problem_understanding artifact.
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    assert report["blockerCodes"]["stage1_research_plan"] == [
        "stage_one_question_authority_missing"
    ]
    assert report["blockerCodes"]["competition_alignment"] == [
        "stage_one_question_authority_missing"
    ]
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="stage1_research_plan", workflow_run_id=_RUN_ID
    )
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="competition_alignment", workflow_run_id=_RUN_ID
    )
    # Dimension refs and feedback iterations recover independently.
    assert "dimension_reviews" in report["satisfiedKinds"]
    assert "feedback_iterations" in report["satisfiedKinds"]


def test_real_batch_plan_fallback_stays_fail_closed_without_catalog_entry(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A question outside the frozen catalog keeps the plan blocker."""
    import core.research.competition.resources as competition_resources
    from core.web.services.team_workflow.research_runtime import question_launch

    def empty_catalog():
        return {"catalog_id": "science-125-questions-2021", "questions": []}

    monkeypatch.setattr(
        competition_resources, "load_science_question_catalog", empty_catalog
    )
    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=3)
    _seed_real_batch_round(team_id, round_id="hround-stage-one-real-batch-1")
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    assert report["blockerCodes"]["stage1_research_plan"] == [
        "stage_one_question_authority_missing"
    ]
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="stage1_research_plan", workflow_run_id=_RUN_ID
    )


def test_real_batch_feedback_stays_fail_closed_without_two_review_rounds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single review round records no feedback→revision iteration."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=1)
    _seed_real_batch_round(
        team_id, round_id="hround-stage-one-real-batch-1", binding_round_index=1
    )
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
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
    assert report["blockerCodes"]["feedback_iterations"] == [
        "hypothesis_revision_evidence_missing"
    ]
    assert not workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="feedback_iterations", workflow_run_id=_RUN_ID
    )
    # Ref repair and the plan fallback are independent and still materialize.
    assert "dimension_reviews" in report["satisfiedKinds"]
    assert "stage1_research_plan" in report["satisfiedKinds"]



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


# ---------------------------------------------------------------------------
# Stage-one closeout human gates: state-v2 matrix readback + hypothesis_set
# human-gate embedding from the real chain human adjudication.
# ---------------------------------------------------------------------------


def _new_shape_alignment_payload() -> dict[str, Any]:
    """competition_alignment payload exactly as the live plan writer emits it."""
    from core.research.competition.stage_one_completion_policy import (
        load_stage_one_completion_policy,
    )
    from core.research.competition.stage_one_requirement_matrix import (
        G1_REQUIRED_EVIDENCE_KINDS,
        evaluate_stage_one_requirement_matrix,
        matrix_to_dict,
    )

    return {
        "schemaVersion": 1,
        "artifactKind": "competition_alignment",
        "questionIdentity": {
            "catalog_id": "science-125-questions-2021",
            "question_id": _QUESTION_ID,
            "question_en": "Canonical question",
        },
        "selectedHypothesis": {
            "hypothesisId": "cand-a",
            "statement": "A bounded proxy improves reconstruction under noise.",
        },
        "competitionResultView": {
            "problem_statement": "Canonical competition problem.",
            "paper_title": "Planned paper",
        },
        "sourceQuestionRunId": _RUN_ID,
        "sourceArtifactSha256": "f" * 64,
        "officialRequirementMatrix": matrix_to_dict(
            evaluate_stage_one_requirement_matrix(
                {
                    requirement_id: tuple(
                        f"{kind}:ref" for kind in kinds
                    )
                    for requirement_id, kinds in G1_REQUIRED_EVIDENCE_KINDS.items()
                }
            ),
            scope_id=load_stage_one_completion_policy().scopeId,
        ),
    }


def test_state_v2_matrix_readback_parses_nested_alignment_payload(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live alignment payload shape no longer 500s the state-v2 projection.

    ``_latest_requirement_matrix`` must hand the §2.5 matrix member — not the
    whole ``competition_alignment`` wrapper — to ``requirement_matrix_from_dict``;
    feeding the wrapper is what raised ``requirement matrix contains unsupported
    fields`` (a StageOneRequirementMatrixError 500 on state-v2).
    """
    from core.web.services.team_workflow.research_runtime import (
        hypothesis_first_state_v2 as state_v2,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        _validate_requirement_matrices,
    )

    team_id = _env(tmp_path, monkeypatch)
    alignment_payload = _new_shape_alignment_payload()
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="competition_alignment",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload=alignment_payload,
    )

    resolved = state_v2._latest_requirement_matrix(team_id, [_RUN_ID])

    assert resolved == alignment_payload["officialRequirementMatrix"]
    section = state_v2._direction_1a_submission_section(resolved)
    assert section["source"] == "competition_alignment"
    # Every G1_REQUIRED row is evidenced, but stage-one never implies
    # direction-1A submission readiness (the other delivery classes stay
    # not_yet_evidenced).
    assert section["g1RequiredUnmet"] == []
    assert section["submissionReady"] is False
    assert "official_scale_out_125_questions" in section["notYetEvidenced"]
    # The closeout matrix validator accepts the exact same nested payload.
    _validate_requirement_matrices(
        {"competition_alignment": [alignment_payload]}
    )


def _portfolio_payload() -> dict[str, Any]:
    """Ungated node-own hypothesis_set artifact as the writeback records it."""
    return {
        "portfolioId": "portfolio-stage-one-gate",
        "runId": _RUN_ID,
        "maxCandidates": 4,
        "maxEvolutionRounds": 3,
        "candidates": [
            {
                "candidateId": "cand-a",
                "claim": "A bounded proxy improves reconstruction under noise.",
                "scores": {dimension: 0.8 for dimension in SCORE_DIMENSIONS},
                "counterEvidenceRefs": ["artifact:counter-a"],
                "derivedFromCandidateIds": [],
                "status": "reviewed",
                "reviewRef": "review-cand-a",
            },
            {
                "candidateId": "cand-b",
                "claim": "A higher-capacity decoder generalizes better.",
                "scores": {dimension: 0.7 for dimension in SCORE_DIMENSIONS},
                "counterEvidenceRefs": ["artifact:counter-b"],
                "derivedFromCandidateIds": ["cand-a"],
                "status": "reviewed",
                "reviewRef": "review-cand-b",
            },
        ],
        "hypothesis_count": 2,
        "currentEvolutionRound": 1,
        "createdFromTaskId": "task-stage-one-gate",
        "createdFromSessionId": "sess-stage-one-gate",
        "createdFromTurnId": "turn-stage-one-gate",
    }


def _seed_gate_materialization(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> str:
    """Real-batch chain plus the ungated node hypothesis_set artifact."""
    from core.web.services.team_workflow.research_runtime import question_launch

    team_id = _env(tmp_path, monkeypatch)
    _fake_candidate_store(
        monkeypatch, sc_run_id=_SC_RUN_ID, candidate_ids=_BARE_SOURCE_IDS
    )
    _seed_real_batch_chain(team_id, rounds=3)
    _seed_real_batch_round(team_id, round_id="hround-stage-one-real-batch-1")
    _seed_problem_understanding(team_id)
    monkeypatch.setattr(
        question_launch, "_approved_details", lambda _team_id: {}
    )
    workflow_artifact_store.put_workflow_artifact(
        team_id,
        kind="hypothesis_set",
        workflow_run_id=_RUN_ID,
        source_collection_run_id=_SC_RUN_ID,
        payload=_portfolio_payload(),
    )
    return team_id


def _accepted_round(team_id: str) -> dict[str, Any]:
    rounds = chain._question_hypothesis_rounds(team_id, _QUESTION_ID)
    return rounds[-1]


def _append_human_adjudication(
    team_id: str,
    round_record: dict[str, Any],
    *,
    decision: str,
    adjudication_id: str,
) -> None:
    """Append one HUMAN_ADJUDICATION_KIND record in the canonical ledger shape."""
    from collections.abc import Mapping

    meeting_ids = [
        str(ref.get("id") or "")
        for ref in list(round_record.get("meetingRefs") or [])
        if isinstance(ref, Mapping) and str(ref.get("kind") or "") == "meeting_round"
    ]
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": 1,
            "recordKind": chain.HUMAN_ADJUDICATION_KIND,
            "adjudicationId": adjudication_id,
            "idempotencyKey": f"key-{adjudication_id}",
            "questionId": _QUESTION_ID,
            "hypothesisRoundId": str(round_record.get("roundId") or ""),
            "workflowRunId": _RUN_ID,
            "meetingRoundIds": meeting_ids,
            "decision": decision,
            "rationale": "operator accepted the recommended hypothesis",
            "decidedBy": "operator-console",
            "createdAt": "2026-09-02T12:30:00Z",
            "updatedAt": "2026-09-02T12:30:00Z",
        },
    )


def test_accepted_human_adjudication_embeds_hypothesis_set_closeout_gate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real chain adjudication becomes the hypothesis_set human gate.

    Positive path: the accepted-round adjudication is embedded into the node's
    hypothesis_set payload, the closeout gate walk reads required+approved,
    and a closeout that previously died on ``stage_one_human_gate_missing``
    now proceeds past the human-gate demand.
    """
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        evaluate_stage_one_closeout,
        payload_human_gates,
    )
    from tests.test_research_workflow_stage_one_closeout import (
        _receipt,
        _stage_one_record,
    )

    team_id = _seed_gate_materialization(tmp_path, monkeypatch)
    round_record = _accepted_round(team_id)
    _append_human_adjudication(
        team_id,
        round_record,
        decision="accepted",
        adjudication_id="hf-adjudication-stage-one-gate",
    )

    report = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        input_snapshot_hash=_SNAPSHOT_HASH,
        source_collection_run_id=_SC_RUN_ID,
    )

    assert report["hypothesisSetGate"]["status"] == "embedded"
    assert report["hypothesisSetGate"]["adjudicationId"] == (
        "hf-adjudication-stage-one-gate"
    )
    assert "hypothesis_set" not in report["blockerCodes"]
    rows = workflow_artifact_store.list_workflow_artifacts(
        team_id, kind="hypothesis_set", workflow_run_id=_RUN_ID
    )
    assert len(rows) == 2
    # The ungated row stays untouched; the gated payload is a new append-only row.
    assert rows[0]["payload"] == _portfolio_payload()
    gate = rows[-1]["payload"]["human_gate"]
    assert gate["required"] is True
    assert gate["decision"] == "approved"
    assert gate["source"] == "chain_human_adjudication"
    assert gate["adjudicationId"] == "hf-adjudication-stage-one-gate"
    assert gate["hypothesisRoundId"] == round_record["roundId"]
    assert gate["decidedBy"] == "operator-console"

    # The closeout gate walk discovers exactly this gate.
    discovered = list(payload_human_gates(rows[-1]["payload"]))
    assert len(discovered) == 1
    assert discovered[0]["required"] is True
    assert str(discovered[0]["decision"]).lower() == "approved"

    # A closeout record carrying this payload passes the human-gate demand.
    record = _stage_one_record()
    record["artifactPayloads"]["hypothesis_set:hypothesis_set-artifact"] = {
        **rows[-1]["payload"],
        "modelInvocationReceipts": [_receipt("generation", record["runId"])],
    }
    outcome = evaluate_stage_one_closeout(record, node_id="hypothesis_design")
    assert outcome is not None
    assert outcome.status == "program_review_required"

    # Replay is idempotent: the gated row already satisfies the gate probe.
    replay = chain.materialize_stage_one_node_authority(
        team_id,
        _QUESTION_ID,
        workflow_run_id=_RUN_ID,
        node_run_id=_NODE_RUN_ID,
        input_snapshot_hash=_SNAPSHOT_HASH,
        source_collection_run_id=_SC_RUN_ID,
    )
    assert replay["hypothesisSetGate"]["status"] == "present"
    assert len(
        workflow_artifact_store.list_workflow_artifacts(
            team_id, kind="hypothesis_set", workflow_run_id=_RUN_ID
        )
    ) == 2


def test_without_accepted_adjudication_hypothesis_set_gate_stays_blocked(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No accepted adjudication means no gate — closeout keeps failing closed.

    Both the missing-adjudication and the rejected-adjudication shapes leave
    the node artifact untouched and the closeout blocked on
    ``stage_one_human_gate_missing``.
    """
    from core.web.services.team_workflow.research_runtime.node_execution_support import (
        NodeExecutionError,
    )
    from core.web.services.team_workflow.research_runtime.stage_one_closeout import (
        evaluate_stage_one_closeout,
    )
    from tests.test_research_workflow_stage_one_closeout import (
        _receipt,
        _stage_one_record,
    )

    for decision in (None, "rejected"):
        team_id = _seed_gate_materialization(tmp_path, monkeypatch)
        round_record = _accepted_round(team_id)
        if decision is not None:
            _append_human_adjudication(
                team_id,
                round_record,
                decision=decision,
                adjudication_id=f"hf-adjudication-{decision}",
            )

        report = chain.materialize_stage_one_node_authority(
            team_id,
            _QUESTION_ID,
            workflow_run_id=_RUN_ID,
            node_run_id=_NODE_RUN_ID,
            input_snapshot_hash=_SNAPSHOT_HASH,
            source_collection_run_id=_SC_RUN_ID,
        )

        assert report["hypothesisSetGate"]["status"] == "blocked"
        assert report["hypothesisSetGate"]["blockerCodes"] == [
            "stage_one_human_gate_missing"
        ]
        assert report["blockerCodes"]["hypothesis_set"] == [
            "stage_one_human_gate_missing"
        ]
        rows = workflow_artifact_store.list_workflow_artifacts(
            team_id, kind="hypothesis_set", workflow_run_id=_RUN_ID
        )
        assert len(rows) == 1
        assert rows[0]["payload"] == _portfolio_payload()
        assert "human_gate" not in rows[0]["payload"]

        record = _stage_one_record()
        record["artifactPayloads"]["hypothesis_set:hypothesis_set-artifact"] = {
            **rows[0]["payload"],
            "modelInvocationReceipts": [_receipt("generation", record["runId"])],
        }
        with pytest.raises(NodeExecutionError) as excinfo:
            evaluate_stage_one_closeout(record, node_id="hypothesis_design")
        assert excinfo.value.code == "stage_one_human_gate_missing"
