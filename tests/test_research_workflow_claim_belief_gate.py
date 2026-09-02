"""R2.2 claim belief hard gate on the hypothesis-first chain (fail-closed).

Covers the two formal decision points of
:mod:`core.web.services.team_workflow.research_runtime.hypothesis_first_chain`:

- ``record_human_adjudication`` (review-closure 入选/淘汰 authority): an
  ``accepted`` adjudication is blocked when the recommended candidate's core
  claims are ``contradicted``/``disputed`` or the claim data cannot be
  evaluated; ``rejected`` (elimination) is never gated and idempotent replays
  are not re-gated;
- ``chain_state`` convergence: the accepted meta-review recommendation must
  carry an evaluable, unrefuted belief table entry, otherwise convergence is
  withheld and the structured ``claimBeliefGate`` block plus
  ``convergenceDetail`` expose the blocked claim ids for the UI/API.

The belief states come exclusively from the already-merged
``claim_belief_service.evaluate_claim_belief`` five-state projection; these
tests never re-derive them.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.research.workflow.contracts import scope_hash_for
from core.web.services import (
    agent_directory_service,
    session_service,
    team_service,
)
from core.web.services.team_workflow import hypothesis_rounds as hrounds
from core.web.services.team_workflow.research_runtime import (
    hypothesis_first_chain as chain,
)
from tests._support.team_workflow.helpers import _use_tmp_project_root

_QUESTION_ID = "SCI-096"
_CANDIDATE_ID = "hyp-a"
_SCOPE_IDENTITY = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": _QUESTION_ID,
    "branch": "main",
    "workflow": "hypothesis_first",
    "agentId": "operator",
    "mode": "dev",
}


def _scope_hash() -> str:
    return scope_hash_for(
        program=_SCOPE_IDENTITY["program"],
        theme=_SCOPE_IDENTITY["theme"],
        campaign=_SCOPE_IDENTITY["campaign"],
        question=_SCOPE_IDENTITY["question"],
        branch=_SCOPE_IDENTITY["branch"],
        workflow=_SCOPE_IDENTITY["workflow"],
        agent_id=_SCOPE_IDENTITY["agentId"],
        mode=_SCOPE_IDENTITY["mode"],
    )


def _ref(
    evidence_id: str,
    *,
    review: str = "accepted",
    support: str = "supports",
) -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "scopeHash": _scope_hash(),
        "reviewStatus": review,
        "supportLevel": support,
        "sourceId": f"artifact:{evidence_id}",
    }


def _claim_row(
    claim_id: str,
    refs: list[dict[str, Any]],
    *,
    status: str = "proposed",
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "claimId": claim_id,
        "claim": f"Claim {claim_id} statement.",
        **_SCOPE_IDENTITY,
        "scopeHash": _scope_hash(),
        "status": status,
        "source": "agent",
        "evidenceRefs": refs,
        "counterEvidenceRefs": [],
        "supersedesClaimId": "",
        "retractsClaimId": "",
        "meetingPromotionAllowed": False,
        "createdBy": _SCOPE_IDENTITY["agentId"],
        "createdAt": "2026-08-28T00:00:00Z",
    }


def _evidence_record(
    evidence_id: str,
    claim_id: str,
    candidate_id: str,
    *,
    review: str = "accepted",
    support: str = "supports",
    reasoning_role: str = "fact",
    evidence_kind: str = "primary_result",
) -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "claimId": claim_id,
        "candidateId": candidate_id,
        "sourceId": f"artifact:{evidence_id}",
        "reviewStatus": review,
        "supportLevel": support,
        "reasoningRole": reasoning_role,
        "evidenceKind": evidence_kind,
        "scopeHash": _scope_hash(),
    }


def _install_claim_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claim_rows: list[dict[str, Any]] | None = None,
    evidence_records: list[dict[str, Any]] | None = None,
    claims_raise: bool = False,
    evidence_raise: bool = False,
    formal_candidate_ids: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        chain,
        "_formal_grounded_candidate_ids_for_gate",
        lambda _team_id, _question_id: set(formal_candidate_ids or set()),
    )
    if claims_raise:

        def _raise_claims(_team_id: str, _question_id: str) -> list[dict[str, Any]]:
            raise OSError("claim ledger unavailable")

        monkeypatch.setattr(chain, "_question_claim_rows_for_gate", _raise_claims)
    else:
        monkeypatch.setattr(
            chain,
            "_question_claim_rows_for_gate",
            lambda _team_id, _question_id: [dict(row) for row in claim_rows or []],
        )
    if evidence_raise:

        def _raise_records(_team_id: str) -> list[dict[str, Any]]:
            raise OSError("claim evidence store unavailable")

        monkeypatch.setattr(chain, "_claim_evidence_records", _raise_records)
    else:
        monkeypatch.setattr(
            chain,
            "_claim_evidence_records",
            lambda _team_id: [dict(record) for record in evidence_records or []],
        )


def _gate_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Minimal hypothesis-first chain environment (one team, tmp stores)."""
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service
    from core.web.services.team_workflow import hypothesis_selection as selections
    from core.web.services.team_workflow import meeting_rounds as meetings
    from core.web.services.team_workflow import research_templates as templates

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(hrounds, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(selections, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(meetings, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(templates, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(chain, "PROJECT_ROOT", tmp_path)
    # The gate reads the claim ledger through the owning service; pin its
    # store root to the tmp workspace so tests never touch the real one.
    monkeypatch.setattr(claim_ledger_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="Gate Coordinator",
        role_key="coordinator",
        created_by="claim-gate-test",
    )
    session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"], title="Gate Coordinator"
    )
    return team_service.create_team(
        name="Claim belief gate 团队",
        purpose="challenge-workflow-claim-gate",
        members=[{"agentId": agent["agentId"], "role": "coordinator"}],
    )["teamId"]


def _closed_round(
    round_id: str = "hround-gate-1",
    *,
    accepted: bool = True,
    candidate_id: str = _CANDIDATE_ID,
) -> dict[str, Any]:
    return {
        "roundId": round_id,
        "status": "closed",
        "question": _QUESTION_ID,
        "metaReview": {
            "metaReviewId": f"mr-{round_id}",
            "reviewerAgentId": "agent-coordinator",
            "recommendationCandidateId": candidate_id,
            "rationale": "证据最完整",
            "riskNotes": "",
            "accepted": accepted,
        },
        "meetingRefs": [{"kind": "meeting_round", "id": "meeting-1"}],
    }


def _install_convergence_source(
    monkeypatch: pytest.MonkeyPatch,
    rounds: list[dict[str, Any]],
) -> None:
    monkeypatch.setattr(chain, "_question_hypothesis_rounds", lambda *_args: rounds)


def _supported_candidate_sources() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]]
]:
    claim_rows = [
        _claim_row("claim-1", [_ref("ce-1")], status="supported"),
    ]
    evidence_records = [_evidence_record("ce-1", "claim-1", _CANDIDATE_ID)]
    return claim_rows, evidence_records


# ---------------------------------------------------------------------------
# Gate unit behaviour (evaluate_claim_belief_gate)
# ---------------------------------------------------------------------------


def test_gate_allows_candidate_with_supported_claim(monkeypatch):
    claim_rows, evidence_records = _supported_candidate_sources()
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "allowed"
    assert verdict["blockedClaims"] == []
    assert verdict["claims"] == [
        {
            "claimId": "claim-1",
            "beliefState": "supported",
            "acceptedSupportCount": 1,
            "acceptedCounterCount": 0,
            "supportingEvidenceIds": ["ce-1"],
            "counterEvidenceIds": [],
        }
    ]


def test_gate_blocks_candidate_core_claim_without_accepted_support(monkeypatch):
    """Candidate-specific core claims require accepted support, not pending refs."""
    claim_rows = [
        _claim_row("claim-pending", [_ref("ce-1", review="pending")]),
        _claim_row("claim-untested", [_ref("ce-2", review="rejected")]),
    ]
    evidence_records = [
        _evidence_record(
            "ce-1",
            "claim-pending",
            _CANDIDATE_ID,
            review="pending",
            support="supports",
            reasoning_role="hypothesis",
        ),
        _evidence_record(
            "ce-2",
            "claim-untested",
            _CANDIDATE_ID,
            review="rejected",
            support="supports",
            reasoning_role="hypothesis",
        ),
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "candidate_evidence_gap"
    states = {item["claimId"]: item["beliefState"] for item in verdict["claims"]}
    assert states == {"claim-pending": "weakly_supported", "claim-untested": "untested"}
    # Neither claim carries any contradicts/counter_evidence record, so the
    # counter-review requirement is vacuous: only the missing accepted
    # support blocks.
    assert {item["gap"] for item in verdict["evidenceGaps"]} == {
        "accepted_support_missing",
    }


def test_gate_allows_supported_candidate_core_claim_without_any_counter_record(monkeypatch):
    """Zero contradicts/counter_evidence records means nothing to review.

    The counter-review requirement is conditional: with no counter record at
    all (pending or accepted) on the claim+candidate, the requirement is
    vacuously satisfied and an evidence-clean candidate is allowed instead of
    being blocked by a review of a record that does not exist.
    """
    claim_rows = [_claim_row("claim-core", [_ref("ce-support")], status="supported")]
    evidence_records = [
        _evidence_record(
            "ce-support",
            "claim-core",
            _CANDIDATE_ID,
            reasoning_role="hypothesis",
        )
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )

    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]

    assert verdict["status"] == "allowed"
    assert verdict["blockedClaims"] == []
    assert "evidenceGaps" not in verdict or verdict["evidenceGaps"] == []


def test_gate_keeps_candidate_specific_evidence_isolated(monkeypatch):
    candidate_b = "hyp-b"
    claim_rows = [_claim_row("claim-a", [_ref("ce-a")], status="supported")]
    evidence_records = [
        _evidence_record(
            "ce-a",
            "claim-a",
            _CANDIDATE_ID,
            reasoning_role="hypothesis",
        ),
        _evidence_record(
            "ce-boundary-a",
            "claim-a",
            _CANDIDATE_ID,
            support="insufficient",
            reasoning_role="hypothesis",
            evidence_kind="counter_evidence",
        ),
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )

    verdicts = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID, candidate_b]
    )

    assert verdicts[_CANDIDATE_ID]["status"] == "allowed"
    assert verdicts[candidate_b] == {
        "candidateId": candidate_b,
        "status": "blocked",
        "reason": "claim_data_missing",
        "claims": [],
        "blockedClaims": [],
    }


def test_formal_candidate_never_uses_historical_source_fact_as_core_claim(monkeypatch):
    claim_rows = [_claim_row("source-fact", [_ref("ce-fact")], status="supported")]
    evidence_records = [
        _evidence_record("ce-fact", "source-fact", _CANDIDATE_ID)
    ]
    _install_claim_sources(
        monkeypatch,
        claim_rows=claim_rows,
        evidence_records=evidence_records,
        formal_candidate_ids={_CANDIDATE_ID},
    )

    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]

    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "candidate_claim_binding_missing"


def test_gate_blocks_contradicted_claim_with_structured_claim_state(monkeypatch):
    claim_rows = [_claim_row("claim-1", [_ref("ce-1", support="contradicts")])]
    evidence_records = [
        _evidence_record("ce-1", "claim-1", _CANDIDATE_ID, support="contradicts")
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_belief_state_blocked"
    assert verdict["blockedClaims"] == [
        {
            "claimId": "claim-1",
            "beliefState": "contradicted",
            "acceptedSupportCount": 0,
            "acceptedCounterCount": 1,
            "counterEvidenceIds": ["ce-1"],
        }
    ]


def test_gate_blocks_disputed_claim(monkeypatch):
    claim_rows = [
        _claim_row(
            "claim-1",
            [_ref("ce-1"), _ref("ce-2", support="contradicts")],
        )
    ]
    evidence_records = [
        _evidence_record("ce-1", "claim-1", _CANDIDATE_ID),
        _evidence_record(
            "ce-2", "claim-1", _CANDIDATE_ID, support="contradicts"
        ),
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["blockedClaims"][0]["beliefState"] == "disputed"


def test_gate_fails_closed_when_candidate_has_no_claim_data(monkeypatch):
    _install_claim_sources(monkeypatch, claim_rows=[], evidence_records=[])
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_data_missing"


def test_gate_fails_closed_when_claim_ledger_unreadable(monkeypatch):
    _install_claim_sources(monkeypatch, claims_raise=True)
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_ledger_unavailable"


def test_gate_fails_closed_when_evidence_store_unreadable(monkeypatch):
    _install_claim_sources(monkeypatch, evidence_raise=True)
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_evidence_store_unavailable"


def test_gate_fails_closed_when_ledger_entry_unparsable(monkeypatch):
    broken_row = _claim_row("claim-1", [_ref("ce-1")])
    broken_row["status"] = "not-a-status"
    _install_claim_sources(
        monkeypatch,
        claim_rows=[broken_row],
        evidence_records=[_evidence_record("ce-1", "claim-1", _CANDIDATE_ID)],
    )
    verdict = chain.evaluate_claim_belief_gate(
        "team-gate", _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_ledger_entry_unreadable"
    assert verdict["blockedClaims"][0]["claimId"] == "claim-1"
    assert verdict["blockedClaims"][0]["problem"] == "ledger_entry_invalid"


# ---------------------------------------------------------------------------
# Convergence decision point (chain_state)
# ---------------------------------------------------------------------------


def test_chain_state_convergence_blocked_without_claim_data(tmp_path, monkeypatch):
    team_id = _gate_env(tmp_path, monkeypatch)
    _install_convergence_source(
        monkeypatch, [_closed_round(accepted=True, candidate_id=_CANDIDATE_ID)]
    )
    state = chain.chain_state(team_id, _QUESTION_ID)
    assert state["hypothesisConverged"] is False
    gate = state["claimBeliefGate"]
    assert gate["decisionPoint"] == "converge_question"
    assert gate["candidateId"] == _CANDIDATE_ID
    assert gate["status"] == "blocked"
    assert gate["reason"] == "claim_data_missing"
    assert "claim belief 硬门" in state["convergenceDetail"]
    assert "fail-closed" in state["convergenceDetail"]


def test_chain_state_convergence_allowed_with_supported_claims(tmp_path, monkeypatch):
    team_id = _gate_env(tmp_path, monkeypatch)
    _install_convergence_source(
        monkeypatch, [_closed_round(accepted=True, candidate_id=_CANDIDATE_ID)]
    )
    claim_rows, evidence_records = _supported_candidate_sources()
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    state = chain.chain_state(team_id, _QUESTION_ID)
    assert state["hypothesisConverged"] is True
    assert state["claimBeliefGate"]["status"] == "allowed"
    assert state["claimBeliefGate"]["blockedClaims"] == []
    assert state["convergenceDetail"] == "converged"


def test_chain_state_convergence_blocked_by_contradicted_claim(tmp_path, monkeypatch):
    team_id = _gate_env(tmp_path, monkeypatch)
    _install_convergence_source(
        monkeypatch, [_closed_round(accepted=True, candidate_id=_CANDIDATE_ID)]
    )
    claim_rows = [_claim_row("claim-1", [_ref("ce-1", support="contradicts")])]
    evidence_records = [
        _evidence_record("ce-1", "claim-1", _CANDIDATE_ID, support="contradicts")
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    state = chain.chain_state(team_id, _QUESTION_ID)
    assert state["hypothesisConverged"] is False
    assert state["claimBeliefGate"]["status"] == "blocked"
    assert state["claimBeliefGate"]["reason"] == "claim_belief_state_blocked"
    blocked = state["claimBeliefGate"]["blockedClaims"]
    assert blocked[0]["claimId"] == "claim-1"
    assert blocked[0]["beliefState"] == "contradicted"
    assert "claim-1" in state["convergenceDetail"]


def test_chain_state_gate_not_evaluated_when_structural_gates_fail(
    tmp_path, monkeypatch
):
    """The claim I/O only runs on the otherwise-converged path."""
    team_id = _gate_env(tmp_path, monkeypatch)

    def _explode(_team_id: str, _question_id: str, _candidates: Any) -> dict:
        raise AssertionError("gate must not run when structural gates fail")

    _install_convergence_source(
        monkeypatch, [_closed_round(accepted=False, candidate_id=_CANDIDATE_ID)]
    )
    monkeypatch.setattr(chain, "evaluate_claim_belief_gate", _explode)
    state = chain.chain_state(team_id, _QUESTION_ID)
    assert state["hypothesisConverged"] is False
    assert state["claimBeliefGate"] is None
    assert state["convergenceDetail"].endswith("MetaReview 未 accepted")


# ---------------------------------------------------------------------------
# Formal selection decision point (record_human_adjudication)
# ---------------------------------------------------------------------------


def _install_round_reader(monkeypatch, round_record: dict[str, Any]) -> None:
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": dict(round_record)},
    )
    _install_convergence_source(monkeypatch, [dict(round_record)])


def test_human_adjudication_accepted_blocked_by_contradicted_claim(
    tmp_path, monkeypatch
):
    team_id = _gate_env(tmp_path, monkeypatch)
    round_record = _closed_round(accepted=True, candidate_id=_CANDIDATE_ID)
    _install_round_reader(monkeypatch, round_record)
    claim_rows = [_claim_row("claim-1", [_ref("ce-1", support="contradicts")])]
    evidence_records = [
        _evidence_record("ce-1", "claim-1", _CANDIDATE_ID, support="contradicts")
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        chain.record_human_adjudication(
            team_id,
            question_id=_QUESTION_ID,
            hypothesis_round_id=round_record["roundId"],
            decision="accepted",
            rationale="推进 hyp-a",
            idempotency_key="gate-adj-1",
        )
    error = excinfo.value
    assert error.code == "claim_belief_gate_blocked"
    assert error.status_code == 422
    assert error.stage == "human_adjudication"
    assert error.candidate_id == _CANDIDATE_ID
    blocker = error.blockers[0]
    assert blocker["code"] == "claim_belief_gate_blocked"
    assert blocker["claims"][0]["claimId"] == "claim-1"
    assert blocker["claims"][0]["beliefState"] == "contradicted"
    # The blocked authority must not have been appended.
    assert chain._records(team_id) == []


def test_human_adjudication_accepted_blocked_when_claim_data_missing(
    tmp_path, monkeypatch
):
    team_id = _gate_env(tmp_path, monkeypatch)
    round_record = _closed_round(accepted=True, candidate_id=_CANDIDATE_ID)
    _install_round_reader(monkeypatch, round_record)
    _install_claim_sources(monkeypatch, claim_rows=[], evidence_records=[])
    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        chain.record_human_adjudication(
            team_id,
            question_id=_QUESTION_ID,
            hypothesis_round_id=round_record["roundId"],
            decision="accepted",
            rationale="推进 hyp-a",
            idempotency_key="gate-adj-2",
        )
    assert excinfo.value.blockers[0]["reason"] == "claim_data_missing"
    assert chain._records(team_id) == []


def test_human_adjudication_rejected_decision_is_not_gated(tmp_path, monkeypatch):
    """淘汰 (rejected) never advances a hypothesis, so it is never gated."""
    team_id = _gate_env(tmp_path, monkeypatch)
    round_record = _closed_round(accepted=True, candidate_id=_CANDIDATE_ID)
    _install_round_reader(monkeypatch, round_record)
    claim_rows = [_claim_row("claim-1", [_ref("ce-1", support="contradicts")])]
    evidence_records = [
        _evidence_record("ce-1", "claim-1", _CANDIDATE_ID, support="contradicts")
    ]
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    result = chain.record_human_adjudication(
        team_id,
        question_id=_QUESTION_ID,
        hypothesis_round_id=round_record["roundId"],
        decision="rejected",
        rationale="淘汰被反证的候选",
        idempotency_key="gate-adj-3",
    )
    assert result["status"] == "created"


def test_human_adjudication_allowed_with_supported_claims(tmp_path, monkeypatch):
    team_id = _gate_env(tmp_path, monkeypatch)
    round_record = _closed_round(accepted=True, candidate_id=_CANDIDATE_ID)
    _install_round_reader(monkeypatch, round_record)
    claim_rows, evidence_records = _supported_candidate_sources()
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    result = chain.record_human_adjudication(
        team_id,
        question_id=_QUESTION_ID,
        hypothesis_round_id=round_record["roundId"],
        decision="accepted",
        rationale="推进 hyp-a",
        idempotency_key="gate-adj-4",
    )
    assert result["status"] == "created"


def test_human_adjudication_replay_is_not_regated(tmp_path, monkeypatch):
    """A durably recorded adjudication replays even if the gate now blocks."""
    team_id = _gate_env(tmp_path, monkeypatch)
    round_record = _closed_round(accepted=True, candidate_id=_CANDIDATE_ID)
    _install_round_reader(monkeypatch, round_record)
    claim_rows, evidence_records = _supported_candidate_sources()
    _install_claim_sources(
        monkeypatch, claim_rows=claim_rows, evidence_records=evidence_records
    )
    first = chain.record_human_adjudication(
        team_id,
        question_id=_QUESTION_ID,
        hypothesis_round_id=round_record["roundId"],
        decision="accepted",
        rationale="推进 hyp-a",
        idempotency_key="gate-adj-5",
    )
    assert first["status"] == "created"
    # The claim evidence disappears after the fact: the replay must still be
    # answered from the durable record instead of re-running the gate.
    _install_claim_sources(monkeypatch, claims_raise=True)
    replay = chain.record_human_adjudication(
        team_id,
        question_id=_QUESTION_ID,
        hypothesis_round_id=round_record["roundId"],
        decision="accepted",
        rationale="推进 hyp-a",
        idempotency_key="gate-adj-5",
    )
    assert replay["status"] == "reused"


# ---------------------------------------------------------------------------
# Real claim-ledger integration (gate reads the owning service)
# ---------------------------------------------------------------------------


def test_gate_reads_real_claim_ledger_for_supported_claim(tmp_path, monkeypatch):
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    team_id = _gate_env(tmp_path, monkeypatch)
    created = claim_ledger_service.propose_claim(
        team_id,
        {
            **_SCOPE_IDENTITY,
            "claimId": "claim-real-1",
            "claim": " Spike-timing carries channel information.",
            "createdBy": "operator",
            "source": "agent",
        },
    )
    assert created["status"] == "created"
    supported = claim_ledger_service.support_claim(
        team_id,
        "claim-real-1",
        {
            "evidenceRefs": [_ref("ce-real-1")],
            "supportedBy": "operator",
        },
    )
    assert supported["claim"]["status"] == "supported"
    # The candidate bridge (claimEvidenceId -> candidateId) still comes from
    # the authoritative evidence store seam.
    evidence_records = [_evidence_record("ce-real-1", "claim-real-1", _CANDIDATE_ID)]
    monkeypatch.setattr(
        chain,
        "_claim_evidence_records",
        lambda _team_id: [dict(record) for record in evidence_records],
    )
    verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert verdict["status"] == "allowed"
    assert verdict["claims"][0]["claimId"] == "claim-real-1"
    assert verdict["claims"][0]["beliefState"] == "supported"


def test_gate_reads_real_claim_ledger_scopes_out_other_questions(
    tmp_path, monkeypatch
):
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    team_id = _gate_env(tmp_path, monkeypatch)
    claim_ledger_service.propose_claim(
        team_id,
        {
            **_SCOPE_IDENTITY,
            "question": "SCI-999",
            "claimId": "claim-other-question",
            "claim": "Another question claim.",
            "createdBy": "operator",
            "source": "agent",
        },
    )
    evidence_records = [
        _evidence_record("ce-1", "claim-other-question", _CANDIDATE_ID)
    ]
    monkeypatch.setattr(
        chain,
        "_claim_evidence_records",
        lambda _team_id: [dict(record) for record in evidence_records],
    )
    verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    # The only claim referencing this candidate belongs to another question,
    # so the gate sees no evaluable claim data for this question and blocks.
    assert verdict["status"] == "blocked"
    assert verdict["reason"] == "claim_data_missing"
