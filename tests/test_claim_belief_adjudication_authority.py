"""Human adjudication as the acceptance authority for the claim belief gate.

The chain never runs an evidence review round, so an ``accepted`` human
adjudication must exercise its designed acceptance authority before the
fail-closed gate runs: the recommended candidate's pending supporting evidence
(the records its core claim rows cite, plus the candidate-dimension bindings)
is promoted by appending audited accepted twin records to the append-only
claim evidence store.  These tests pin:

- case A: accepted adjudication succeeds on a formal grounded candidate whose
  bridging evidence is only pending (fact and hypothesis roles), the twins
  carry the acceptance audit fields plus the claim scope, replaying the same
  idempotency key appends nothing, and untouched source-fact records stay
  pending;
- case A2: with no contradicts/counter_evidence record at all (the live
  SCI-091 shape: 34 pending supports, zero counters), the counter-review
  requirement is vacuous, so the same accepted adjudication passes the gate
  and the authority record lands;
- case B: a contradicted/contested claim still blocks the adjudication
  (``ClaimBeliefGateBlockedError``) and the authority record is not appended;
- case B2: a single pending contradicts record is belief-neutral (fail-closed
  pending counters) but still demands its accepted version, so the gate stays
  blocked on ``accepted_counter_or_boundary_missing``;
- case C: a ``rejected`` adjudication neither writes acceptances nor runs the
  gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from core.research.evidence import ClaimEvidenceStore
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

_QUESTION_ID = "SCI-091"
_CANDIDATE_ID = "hyp-a"
_ROUND_ID = "hround-authority-1"
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


def _env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, ClaimEvidenceStore]:
    """Isolated chain environment with a real (tmp-rooted) evidence store."""
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
    monkeypatch.setattr(claim_ledger_service, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(
        display_name="Adjudication Coordinator",
        role_key="coordinator",
        created_by="adjudication-authority-test",
    )
    session_service.ensure_agent_direct_session(
        agent_id=agent["agentId"], title="Adjudication Coordinator"
    )
    team_id = team_service.create_team(
        name="Adjudication authority 团队",
        purpose="challenge-workflow-adjudication-authority",
        members=[{"agentId": agent["agentId"], "role": "coordinator"}],
    )["teamId"]
    return team_id, ClaimEvidenceStore(tmp_path)


def _register(
    store: ClaimEvidenceStore,
    team_id: str,
    *,
    claim_id: str,
    candidate_id: str,
    reasoning_role: str = "fact",
    support_level: str = "supports",
    evidence_kind: str = "primary_result",
    quote: str = "",
) -> dict[str, Any]:
    """Register one pending evidence record the way the chain bridges do."""
    record = store.register(
        team_id,
        {
            "claimId": claim_id,
            "candidateId": candidate_id,
            "sourceId": f"artifact:{claim_id}-{candidate_id}-{reasoning_role}",
            "sourceRevision": "sha256:" + "ab" * 32,
            "locator": {"kind": "paper", "section": "abstract"},
            "quote": quote
            or f"{candidate_id}/{reasoning_role} supports {claim_id} with anchored evidence.",
            "evidenceKind": evidence_kind,
            "reasoningRole": reasoning_role,
            "supportLevel": support_level,
            "extractionMethod": "manual",
            "extractorAgentId": "agent-extractor",
        },
    )
    return dict(record)


def _ref(evidence_id: str, *, review: str = "pending") -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "scopeHash": _scope_hash(),
        "reviewStatus": review,
        "supportLevel": "supports",
        "sourceId": f"artifact:{evidence_id}",
    }


def _install_sources(
    monkeypatch: pytest.MonkeyPatch,
    store: ClaimEvidenceStore,
    team_id: str,
    *,
    claim_rows: list[dict[str, Any]],
    formal_candidate_ids: set[str],
) -> None:
    """Pin the gate/acceptance reads onto the real tmp evidence store."""
    monkeypatch.setattr(
        chain,
        "_claim_evidence_records",
        lambda _team_id: [dict(record) for record in store.list(team_id)],
    )
    monkeypatch.setattr(
        chain,
        "_question_claim_rows_for_gate",
        lambda _team_id, _question_id: [dict(row) for row in claim_rows],
    )
    monkeypatch.setattr(
        chain,
        "_formal_grounded_candidate_ids_for_gate",
        lambda _team_id, _question_id: set(formal_candidate_ids),
    )


def _closed_round() -> dict[str, Any]:
    return {
        "roundId": _ROUND_ID,
        "status": "closed",
        "question": _QUESTION_ID,
        "metaReview": {
            "metaReviewId": f"mr-{_ROUND_ID}",
            "reviewerAgentId": "agent-coordinator",
            "recommendationCandidateId": _CANDIDATE_ID,
            "rationale": "证据最完整",
            "riskNotes": "",
            "accepted": True,
        },
        "meetingRefs": [{"kind": "meeting_round", "id": "meeting-authority-1"}],
    }


def _install_round_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    round_record = _closed_round()
    monkeypatch.setattr(
        hrounds,
        "get_hypothesis_round",
        lambda _team_id, _round_id: {"round": dict(round_record)},
    )
    monkeypatch.setattr(
        chain, "_question_hypothesis_rounds", lambda *_args: [dict(round_record)]
    )


def _seed_unconverged_candidate(
    store: ClaimEvidenceStore,
    team_id: str,
    *,
    boundary: str,
) -> dict[str, Any]:
    """Formal grounded candidate whose bridging evidence is only pending.

    Mirrors ``materialize_chain_collection_evidence``: the core claim row cites
    a fact-dimension record (candidateId of the source candidate), while the
    candidate-dimension bindings exist in both fact and hypothesis roles (live
    stores carry both after historical repairs).  ``boundary`` selects the
    refutation flavour:

    - ``"contradicts"`` mixes an accepted contradicted ref into the claim
      (ref snapshot semantics — an unmatched ref keeps its own state — plus
      its store record so the conditional counter check sees it), which must
      keep the adjudication blocked on the disputed belief state;
    - ``"pending_contradicts"`` registers a *pending* contradicts record and
      cites it: belief stays non-blocking (pending counters never demote) but
      the unreviewed counter record still demands its accepted version;
    - ``"none"`` leaves the candidate with zero contradicts/counter_evidence
      records (the live SCI-091 shape), so the counter-review requirement is
      vacuous;
    - ``"counter_evidence"`` seeds an accepted, neutral boundary record the
      formal review produced.
    """
    cited_fact = _register(
        store,
        team_id,
        claim_id="claim-fact-1",
        candidate_id="src-cand-1",
        quote="Anchored source fact cited by the core claim.",
    )
    candidate_fact = _register(
        store,
        team_id,
        claim_id="claim-core",
        candidate_id=_CANDIDATE_ID,
        reasoning_role="fact",
        quote="Candidate-dimension fact binding for the core claim.",
    )
    candidate_hypothesis = _register(
        store,
        team_id,
        claim_id="claim-core",
        candidate_id=_CANDIDATE_ID,
        reasoning_role="hypothesis",
        quote="Candidate-dimension hypothesis binding for the core claim.",
    )
    untouched_fact = _register(
        store,
        team_id,
        claim_id="claim-fact-2",
        candidate_id="src-cand-2",
        quote="Pure source fact on its own claim row, never cited.",
    )
    evidence_refs = [_ref(cited_fact["claimEvidenceId"])]
    if boundary == "contradicts":
        contradicts_record = _register(
            store,
            team_id,
            claim_id="claim-core",
            candidate_id=_CANDIDATE_ID,
            reasoning_role="hypothesis",
            support_level="contradicts",
            quote="Accepted refutation record for the core claim.",
        )
        reviewed = store.review(
            team_id,
            contradicts_record["claimEvidenceId"],
            decision="accepted",
            reviewed_by="agent-reviewer",
        )
        assert reviewed["reviewStatus"] == "accepted"
        # Ref snapshot semantics: the cited id is unmatched in the store, so
        # the ref's own accepted/contradicts snapshot drives the belief.
        evidence_refs.append(
            {
                "claimEvidenceId": "ce-refuted-claim-observation",
                "scopeHash": _scope_hash(),
                "reviewStatus": "accepted",
                "supportLevel": "contradicts",
                "sourceId": "artifact:refuted-claim-observation",
            }
        )
    elif boundary == "pending_contradicts":
        # A pending contradicts record on the core claim, cited by the claim
        # row: pending counters are belief-neutral, but the counter record
        # exists, so its accepted version is required before the gate allows.
        contradicts_record = _register(
            store,
            team_id,
            claim_id="claim-core",
            candidate_id=_CANDIDATE_ID,
            reasoning_role="hypothesis",
            support_level="contradicts",
            quote="Unreviewed refutation record for the core claim.",
        )
        evidence_refs.append(
            {
                "claimEvidenceId": contradicts_record["claimEvidenceId"],
                "scopeHash": _scope_hash(),
                "reviewStatus": "pending",
                "supportLevel": "contradicts",
                "sourceId": contradicts_record["sourceId"],
            }
        )
    elif boundary == "counter_evidence":
        # An accepted, neutral boundary record the formal review produced.
        boundary_record = _register(
            store,
            team_id,
            claim_id="claim-core",
            candidate_id=_CANDIDATE_ID,
            reasoning_role="hypothesis",
            support_level="insufficient",
            evidence_kind="counter_evidence",
            quote="Accepted boundary review record for the core claim.",
        )
        reviewed = store.review(
            team_id,
            boundary_record["claimEvidenceId"],
            decision="accepted",
            reviewed_by="agent-reviewer",
        )
        assert reviewed["reviewStatus"] == "accepted"
    core_claim_row = {
        "schemaVersion": 1,
        "claimId": "claim-core",
        "claim": "The recommended candidate's core claim statement.",
        **_SCOPE_IDENTITY,
        "scopeHash": _scope_hash(),
        "status": "proposed",
        "source": "agent",
        "evidenceRefs": evidence_refs,
        "counterEvidenceRefs": [],
        "supersedesClaimId": "",
        "retractsClaimId": "",
        "meetingPromotionAllowed": False,
        "createdBy": _SCOPE_IDENTITY["agentId"],
        "createdAt": "2026-09-01T00:00:00Z",
    }
    return {
        "claim_rows": [core_claim_row],
        "cited_fact": cited_fact,
        "candidate_fact": candidate_fact,
        "candidate_hypothesis": candidate_hypothesis,
        "untouched_fact": untouched_fact,
    }


def _accepted_twins(store: ClaimEvidenceStore, team_id: str) -> list[dict[str, Any]]:
    return [
        dict(record)
        for record in store.list(team_id)
        if record.get("reviewStatus") == "accepted"
        and record.get("acceptanceSource") == "human_adjudication"
    ]


def _adjudicate(team_id: str, *, decision: str, key: str) -> dict[str, Any]:
    return chain.record_human_adjudication(
        team_id,
        question_id=_QUESTION_ID,
        hypothesis_round_id=_ROUND_ID,
        decision=decision,
        rationale="推进或淘汰该候选",
        idempotency_key=key,
        decided_by="agent-operator",
    )


# ---------------------------------------------------------------------------
# Case A — accepted adjudication exercises the acceptance authority
# ---------------------------------------------------------------------------


def test_accepted_adjudication_upgrades_pending_support_and_passes_gate(
    tmp_path, monkeypatch
):
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_unconverged_candidate(store, team_id, boundary="counter_evidence")
    _install_sources(
        monkeypatch,
        store,
        team_id,
        claim_rows=seed["claim_rows"],
        formal_candidate_ids={_CANDIDATE_ID},
    )
    _install_round_reader(monkeypatch)

    # Precondition: the unchanged gate fails closed before the authority runs.
    pre_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert pre_verdict["status"] == "blocked"
    assert pre_verdict["reason"] == "candidate_evidence_gap"
    # The accepted boundary record already covers the boundary check; the
    # pending-only support is what deadlocks the gate before the authority.
    assert {item["gap"] for item in pre_verdict["evidenceGaps"]} == {
        "accepted_support_missing"
    }

    result = _adjudicate(team_id, decision="accepted", key="authority-accepted-1")
    assert result["status"] == "created"

    # The audited accepted twins exist for exactly the pending support surface.
    twins = _accepted_twins(store, team_id)
    twin_sources = {twin["claimEvidenceId"] for twin in twins}
    assert twin_sources == {
        seed["cited_fact"]["claimEvidenceId"],
        seed["candidate_fact"]["claimEvidenceId"],
        seed["candidate_hypothesis"]["claimEvidenceId"],
    }
    for twin in twins:
        assert twin["acceptedBy"] == "agent-operator"
        assert twin["acceptanceRoundId"] == _ROUND_ID
        assert twin["acceptanceSource"] == "human_adjudication"
        assert isinstance(twin["acceptedAtMs"], int)
        assert twin["reasoningRole"] in {"fact", "hypothesis"}
    cited_twin = next(
        twin
        for twin in twins
        if twin["claimEvidenceId"] == seed["cited_fact"]["claimEvidenceId"]
    )
    # The twin must carry the core claim scope, or belief readers neutralize it.
    assert cited_twin["scopeHash"] == _scope_hash()

    # Pure source-fact records on their own claim rows are never touched.
    untouched = store.list(
        team_id, claim_id="claim-fact-2", candidate_id="src-cand-2"
    )
    assert [record["reviewStatus"] for record in untouched] == ["pending"]

    # The unchanged gate now allows the candidate.
    post_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert post_verdict["status"] == "allowed"
    assert post_verdict["claims"][0]["acceptedSupportCount"] >= 1

    # Replaying the same idempotency key reuses the record and appends nothing.
    records_before = len(store.list(team_id))
    replay = _adjudicate(team_id, decision="accepted", key="authority-accepted-1")
    assert replay["status"] == "reused"
    assert len(store.list(team_id)) == records_before
    assert len(_accepted_twins(store, team_id)) == len(twins)


# ---------------------------------------------------------------------------
# Case A2 — zero counter records: the counter-review requirement is vacuous
# ---------------------------------------------------------------------------


def test_accepted_adjudication_passes_when_no_counter_record_exists(
    tmp_path, monkeypatch
):
    """Evidence-clean strict candidates must not be blocked by a phantom review.

    Live shape (SCI-091): every record under the core claim is a pending
    supports/primary_result record; no contradicts/counter_evidence record
    exists at all.  After the acceptance authority promotes the pending
    supports, the gate must allow the candidate and the adjudication must
    land, instead of demanding an accepted review of a record that does not
    exist.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_unconverged_candidate(store, team_id, boundary="none")
    _install_sources(
        monkeypatch,
        store,
        team_id,
        claim_rows=seed["claim_rows"],
        formal_candidate_ids={_CANDIDATE_ID},
    )
    _install_round_reader(monkeypatch)

    # Precondition: only the missing accepted support blocks; with zero
    # counter records the counter-review requirement is already vacuous.
    pre_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert pre_verdict["status"] == "blocked"
    assert pre_verdict["reason"] == "candidate_evidence_gap"
    assert {item["gap"] for item in pre_verdict["evidenceGaps"]} == {
        "accepted_support_missing"
    }

    result = _adjudicate(team_id, decision="accepted", key="authority-clean-1")
    assert result["status"] == "created"

    # The acceptance authority promoted exactly the pending support surface.
    twins = _accepted_twins(store, team_id)
    assert {twin["claimEvidenceId"] for twin in twins} == {
        seed["cited_fact"]["claimEvidenceId"],
        seed["candidate_fact"]["claimEvidenceId"],
        seed["candidate_hypothesis"]["claimEvidenceId"],
    }

    # The gate now allows the evidence-clean candidate…
    post_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert post_verdict["status"] == "allowed"
    assert post_verdict["claims"][0]["beliefState"] == "supported"
    assert post_verdict["claims"][0]["acceptedCounterCount"] == 0

    # …and the human authority record landed (裁决落账).
    authority_records = [
        dict(item)
        for item in chain._records(team_id)
        if item.get("recordKind") == "human_adjudication"
    ]
    assert len(authority_records) == 1
    assert authority_records[0]["decision"] == "accepted"
    assert authority_records[0]["hypothesisRoundId"] == _ROUND_ID


# ---------------------------------------------------------------------------
# Case B — contradicted claims still block the adjudication
# ---------------------------------------------------------------------------


def test_accepted_adjudication_still_blocked_by_contradicted_claim(
    tmp_path, monkeypatch
):
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_unconverged_candidate(store, team_id, boundary="contradicts")
    _install_sources(
        monkeypatch,
        store,
        team_id,
        claim_rows=seed["claim_rows"],
        formal_candidate_ids={_CANDIDATE_ID},
    )
    _install_round_reader(monkeypatch)

    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        _adjudicate(team_id, decision="accepted", key="authority-blocked-1")
    error = excinfo.value
    assert error.code == "claim_belief_gate_blocked"
    assert error.status_code == 422
    assert error.stage == "human_adjudication"
    assert error.candidate_id == _CANDIDATE_ID
    assert error.blockers[0]["claims"][0]["beliefState"] == "disputed"

    # The acceptance write ran before the gate (per its audit semantics), but
    # the blocked authority record itself was never appended.
    assert len(_accepted_twins(store, team_id)) == 3
    assert chain._records(team_id) == []


# ---------------------------------------------------------------------------
# Case B2 — an unreviewed contradicts record still demands its accepted version
# ---------------------------------------------------------------------------


def test_accepted_adjudication_blocked_by_pending_contradicts_record(
    tmp_path, monkeypatch
):
    """A pending counter record is belief-neutral but not review-free.

    The conditional counter check only relaxes the requirement when *no*
    counter record exists.  A single pending contradicts record keeps the
    belief state non-blocking (fail-closed pending counters never demote),
    yet the gate must still block until that record has its accepted
    version — refuting material cannot slip through unreviewed.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_unconverged_candidate(
        store, team_id, boundary="pending_contradicts"
    )
    _install_sources(
        monkeypatch,
        store,
        team_id,
        claim_rows=seed["claim_rows"],
        formal_candidate_ids={_CANDIDATE_ID},
    )
    _install_round_reader(monkeypatch)

    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        _adjudicate(team_id, decision="accepted", key="authority-pending-counter-1")
    error = excinfo.value
    assert error.code == "claim_belief_gate_blocked"
    assert error.status_code == 422
    assert error.stage == "human_adjudication"
    assert error.candidate_id == _CANDIDATE_ID
    blocker = error.blockers[0]
    # Pending counters never demote the belief (accepted supports win), so
    # the block comes from the unreviewed counter record, not the state: the
    # blocker carries no blocked claim and the gap names the missing review.
    assert blocker["reason"] == "candidate_evidence_gap"
    assert blocker["claims"] == []
    assert {
        (item["claimId"], item["gap"]) for item in blocker["evidenceGaps"]
    } == {("claim-core", "accepted_counter_or_boundary_missing")}
    post_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert post_verdict["claims"][0]["beliefState"] == "supported"
    assert post_verdict["claims"][0]["acceptedCounterCount"] == 0

    # The acceptance write ran before the gate, the contradicts record stayed
    # pending, and the blocked authority record was never appended.
    assert len(_accepted_twins(store, team_id)) == 3
    contradicts_states = [
        record["reviewStatus"]
        for record in store.list(team_id)
        if record.get("supportLevel") == "contradicts"
    ]
    assert contradicts_states == ["pending"]
    assert chain._records(team_id) == []


# ---------------------------------------------------------------------------
# Case C — rejected adjudication neither writes acceptances nor gates
# ---------------------------------------------------------------------------


def test_rejected_adjudication_writes_no_acceptance_and_never_gates(
    tmp_path, monkeypatch
):
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_unconverged_candidate(store, team_id, boundary="counter_evidence")
    _install_sources(
        monkeypatch,
        store,
        team_id,
        claim_rows=seed["claim_rows"],
        formal_candidate_ids={_CANDIDATE_ID},
    )
    _install_round_reader(monkeypatch)

    result = _adjudicate(team_id, decision="rejected", key="authority-rejected-1")
    assert result["status"] == "created"
    assert result["adjudication"]["decision"] == "rejected"
    # A pending-only candidate would fail the strict gate, so success here
    # proves the rejected branch never gated — and it wrote no acceptances.
    assert _accepted_twins(store, team_id) == []
    assert len(store.list(team_id)) == 5
