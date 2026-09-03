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
  gate;
- case D (defect-10, 方案A): on the live chain-collection shape the strict
  gate used to read ``candidate_claim_binding_missing`` forever (the only
  hypothesis-role writer ran on the formal side, after this adjudication).
  The accepted adjudication now materializes the recommended candidate's
  strict bindings probe-first and idempotently before the unchanged gate —
  and keeps the gate fail-closed when no evidence is bindable, while
  rejected adjudications never materialize.
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


# ---------------------------------------------------------------------------
# Case D — chain-level strict binding materialization (defect-10, 方案A)
#
# The strict claim belief gate requires hypothesis-role claim binding
# records, but the only writer ran on the formal side — after the formal run
# exists — while chain-level adjudication happens strictly before it.  An
# accepted adjudication therefore could never satisfy the gate
# (``candidate_claim_binding_missing``, SCI-091 2026-09-02).  These tests pin
# the chain-level fix: before the gate, the accepted adjudication
# materializes the recommended candidate's strict bindings probe-first and
# idempotently from its already-collected lineage evidence; with no bindable
# evidence the gate keeps its original fail-closed verdict; rejected
# adjudications never materialize.
# ---------------------------------------------------------------------------


def _register_source(
    store: ClaimEvidenceStore,
    team_id: str,
    *,
    claim_id: str,
    candidate_id: str,
    source_id: str,
    quote: str,
    workflow_run_id: str = "",
    source_collection_run_id: str = "",
) -> dict[str, Any]:
    payload = {
        "claimId": claim_id,
        "candidateId": candidate_id,
        "sourceId": source_id,
        "sourceRevision": "sha256:" + "cd" * 32,
        "locator": {"kind": "paper", "section": "abstract"},
        "quote": quote,
        "evidenceKind": "primary_result",
        "reasoningRole": "fact",
        "supportLevel": "supports",
        "extractionMethod": "manual",
        "extractorAgentId": "agent-extractor",
    }
    if workflow_run_id:
        payload["workflowRunId"] = workflow_run_id
    if source_collection_run_id:
        payload["sourceCollectionRunId"] = source_collection_run_id
    return dict(store.register(team_id, payload))


def _strict_records(store: ClaimEvidenceStore, team_id: str) -> list[dict[str, Any]]:
    """Hypothesis-role records bound to the recommended candidate."""
    return [
        dict(record)
        for record in store.list(team_id)
        if str(record.get("candidateId") or "") == _CANDIDATE_ID
        and str(record.get("reasoningRole") or "") == "hypothesis"
    ]


def _append_chain_candidate(
    team_id: str,
    *,
    statement: str,
    lineage_refs: list[str],
) -> None:
    chain._append_jsonl(
        chain._storage_path(team_id),
        {
            "schemaVersion": chain.SCHEMA_VERSION,
            "recordKind": chain.CANDIDATE_KIND,
            "candidateId": _CANDIDATE_ID,
            "questionId": _QUESTION_ID,
            "statement": statement,
            "candidateAuthority": chain.FORMAL_GROUNDED_CANDIDATE_AUTHORITY,
            "lineageRefs": lineage_refs,
            "meetingRoundId": "meeting-authority-1",
            "createdAt": "2026-09-01T00:00:00Z",
        },
    )


def _seed_chain_collection_shape(
    store: ClaimEvidenceStore,
    team_id: str,
    *,
    with_core_claim_row: bool = True,
) -> dict[str, Any]:
    """The live defect shape: the chain collection bridge ran, strict
    bindings never did.

    Mirrors ``materialize_chain_collection_evidence`` output: a fact claim
    row plus a fact-role evidence record on the source dimension, the
    candidate's core-claim ledger row citing the collected ref, and the
    candidate-dimension FACT-role record.  No hypothesis-role record exists
    anywhere, so the unchanged strict gate reads
    ``candidate_claim_binding_missing``.
    """
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service

    statement = "The chain candidate's core claim awaiting strict bindings."
    scope = chain._question_scope_envelope(team_id, _QUESTION_ID)
    identity = {
        field: scope[field]
        for field in ("program", "theme", "campaign", "question", "branch", "workflow")
    }
    fact_claim = claim_ledger_service.propose_claim(
        team_id,
        {
            **identity,
            "agentId": scope["agentId"],
            "mode": scope["mode"],
            "claim": "Collected anchored source fact for the candidate lineage.",
            "createdBy": scope["agentId"],
            "source": "agent",
        },
    )["claim"]
    cited_fact = _register_source(
        store,
        team_id,
        claim_id=fact_claim["claimId"],
        candidate_id="src-cand-1",
        source_id="source-ref-1",
        quote="Collected anchored source fact for the candidate lineage.",
    )
    core_claim_id = ""
    if with_core_claim_row:
        from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
            _ledger_claim_id,
        )

        core_claim_id = _ledger_claim_id(
            question_scope=scope,
            claim_text=statement,
            candidate_id=_CANDIDATE_ID,
        )
        core_claim = claim_ledger_service.propose_claim(
            team_id,
            {
                **identity,
                "agentId": scope["agentId"],
                "mode": scope["mode"],
                "claim": statement,
                "claimId": core_claim_id,
                "createdBy": scope["agentId"],
                "source": "agent",
                "evidenceRefs": [
                    {
                        "claimEvidenceId": cited_fact["claimEvidenceId"],
                        "scopeHash": fact_claim["scopeHash"],
                        "reviewStatus": "pending",
                        "supportLevel": "supports",
                        "sourceId": "source-ref-1",
                    }
                ],
            },
        )["claim"]
        core_claim_id = core_claim["claimId"]
        candidate_fact = _register_source(
            store,
            team_id,
            claim_id=core_claim_id,
            candidate_id=_CANDIDATE_ID,
            source_id="source-ref-1",
            quote="Collected anchored source fact for the candidate lineage.",
        )
    else:
        candidate_fact = {}
    _append_chain_candidate(
        team_id, statement=statement, lineage_refs=["source-ref-1"]
    )
    return {
        "statement": statement,
        "core_claim_id": core_claim_id,
        "cited_fact": cited_fact,
        "candidate_fact": candidate_fact,
    }


def test_accepted_adjudication_materializes_strict_bindings_and_passes_gate(
    tmp_path, monkeypatch
):
    """Live defect shape, real stores: materialization unlocks the gate.

    The chain bridge proposed the core-claim row WITH its cited refs, so the
    materialization must reuse that row's claim id (a ref-less re-proposal
    would collide with the ledger's content binding) and register the
    hypothesis-role records against it.  The acceptance authority promotes
    the cited pending support, the unchanged gate reads accepted support on
    the strict binding, and the adjudication lands.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_chain_collection_shape(store, team_id, with_core_claim_row=True)
    _install_round_reader(monkeypatch)

    # Precondition: the unchanged gate fails closed exactly as the field did.
    pre_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert pre_verdict["status"] == "blocked"
    assert pre_verdict["reason"] == "candidate_claim_binding_missing"
    assert _strict_records(store, team_id) == []

    result = _adjudicate(team_id, decision="accepted", key="materialize-accepted-1")
    assert result["status"] == "created"

    # Materialization happened: hypothesis-role bindings on the existing row.
    strict = _strict_records(store, team_id)
    assert {record["claimId"] for record in strict} == {seed["core_claim_id"]}
    assert {record["sourceId"] for record in strict} == {"source-ref-1"}

    # The acceptance authority promoted exactly the pending support surface.
    twins = _accepted_twins(store, team_id)
    assert {twin["claimEvidenceId"] for twin in twins} == {
        seed["cited_fact"]["claimEvidenceId"],
        seed["candidate_fact"]["claimEvidenceId"],
    }

    # The unchanged gate now allows the candidate and the record landed.
    post_verdict = chain.evaluate_claim_belief_gate(
        team_id, _QUESTION_ID, [_CANDIDATE_ID]
    )[_CANDIDATE_ID]
    assert post_verdict["status"] == "allowed"
    assert post_verdict["claims"][0]["acceptedSupportCount"] >= 1
    authority_records = [
        dict(item)
        for item in chain._records(team_id)
        if item.get("recordKind") == "human_adjudication"
    ]
    assert [record["decision"] for record in authority_records] == ["accepted"]

    # Idempotent replay: the same key reuses the record and writes nothing.
    store_count = len(store.list(team_id))
    replay = _adjudicate(team_id, decision="accepted", key="materialize-accepted-1")
    assert replay["status"] == "reused"
    assert len(store.list(team_id)) == store_count
    assert len(_strict_records(store, team_id)) == len(strict)


def test_accepted_adjudication_after_materialization_replays_write_free(
    tmp_path, monkeypatch
):
    """A distinct accepted authority (human after auto) never rewrites bindings.

    The probe-first check short-circuits when strict bindings already exist,
    so a second accepted adjudication with a fresh idempotency key appends
    only its authority record — no duplicate hypothesis-role rows, no
    duplicate ledger proposals, no duplicate acceptance twins.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    _seed_chain_collection_shape(store, team_id, with_core_claim_row=True)
    _install_round_reader(monkeypatch)

    first = _adjudicate(team_id, decision="accepted", key="materialize-auto-1")
    assert first["status"] == "created"
    strict_after_first = _strict_records(store, team_id)
    twins_after_first = _accepted_twins(store, team_id)
    assert strict_after_first

    second = _adjudicate(team_id, decision="accepted", key="materialize-human-1")
    assert second["status"] == "created"
    # The materialization guarantee: binding identities never duplicate.  The
    # second acceptance re-promotes its pending surface as accepted twins
    # (same evidence ids, its own pre-existing semantics), but no NEW
    # hypothesis-role binding id may appear.
    first_ids = {record["claimEvidenceId"] for record in strict_after_first}
    second_ids = {
        record["claimEvidenceId"] for record in _strict_records(store, team_id)
    }
    assert second_ids == first_ids
    authority_records = [
        dict(item)
        for item in chain._records(team_id)
        if item.get("recordKind") == "human_adjudication"
    ]
    assert [record["decision"] for record in authority_records] == [
        "accepted",
        "accepted",
    ]


def test_accepted_adjudication_without_bindable_evidence_stays_fail_closed(
    tmp_path, monkeypatch
):
    """No lineage evidence: nothing materializes, the gate keeps its verdict.

    The candidate record exists with lineage refs, but no collected evidence
    matches them — the materialization finds nothing to bind, writes no
    hypothesis-role record, and the strict gate still blocks on
    ``candidate_claim_binding_missing`` without appending the authority.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    _append_chain_candidate(
        team_id,
        statement="A candidate whose lineage evidence never existed.",
        lineage_refs=["source-ref-missing"],
    )
    _install_round_reader(monkeypatch)

    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        _adjudicate(team_id, decision="accepted", key="materialize-missing-1")
    error = excinfo.value
    assert error.stage == "human_adjudication"
    assert error.blockers[0]["reason"] == "candidate_claim_binding_missing"
    assert _strict_records(store, team_id) == []
    assert _accepted_twins(store, team_id) == []
    # Only the seeded candidate record exists — the authority never landed.
    assert [
        item
        for item in chain._records(team_id)
        if item.get("recordKind") == "human_adjudication"
    ] == []


def test_accepted_adjudication_fresh_row_keeps_gate_fail_closed(
    tmp_path, monkeypatch
):
    """Fresh materializer path: bindings land, no acceptance is fabricated.

    When the chain bridge never proposed the core-claim row, the formal
    materializer runs unchanged: it proposes the row (ref-less, so the
    belief has no accepted support to count) and binds the lineage evidence.
    The gate now sees the strict binding but still fails closed on the empty
    belief — materialization never invents acceptances or evidence refs.
    """
    team_id, store = _env(tmp_path, monkeypatch)
    statement = "A candidate whose bridge never proposed the core row."
    scope = chain._question_scope_envelope(team_id, _QUESTION_ID)
    identity = {
        field: scope[field]
        for field in ("program", "theme", "campaign", "question", "branch", "workflow")
    }
    from core.web.services.team_workflow import claim_ledger as claim_ledger_service
    from core.web.services.team_workflow.research_runtime.agent_claim_evidence_materializer import (
        _ledger_claim_id,
    )

    fact_claim = claim_ledger_service.propose_claim(
        team_id,
        {
            **identity,
            "agentId": scope["agentId"],
            "mode": scope["mode"],
            "claim": "Orphan collected fact without a candidate core row.",
            "createdBy": scope["agentId"],
            "source": "agent",
        },
    )["claim"]
    orphan_fact = _register_source(
        store,
        team_id,
        claim_id=fact_claim["claimId"],
        candidate_id="src-cand-9",
        source_id="source-ref-9",
        quote="Orphan collected fact without a candidate core row.",
        workflow_run_id="wfr-materialize-fresh-1",
        source_collection_run_id="run-materialize-fresh-1",
    )
    _append_chain_candidate(
        team_id, statement=statement, lineage_refs=["source-ref-9"]
    )
    _install_round_reader(monkeypatch)

    with pytest.raises(chain.ClaimBeliefGateBlockedError) as excinfo:
        _adjudicate(team_id, decision="accepted", key="materialize-fresh-1")
    error = excinfo.value
    assert error.blockers[0]["reason"] == "candidate_evidence_gap"
    assert {
        item["gap"] for item in error.blockers[0]["evidenceGaps"]
    } == {"accepted_support_missing"}

    # The fresh path materialized the strict binding on the materializer's
    # newly proposed (ref-less) candidate row…
    expected_core_id = _ledger_claim_id(
        question_scope=scope, claim_text=statement, candidate_id=_CANDIDATE_ID
    )
    strict = _strict_records(store, team_id)
    assert {record["claimId"] for record in strict} == {expected_core_id}
    assert {record["sourceId"] for record in strict} == {"source-ref-9"}
    core_rows = [
        dict(row)
        for row in claim_ledger_service.list_claims(team_id)["claims"]
        if str(row.get("claimId") or "") == expected_core_id
    ]
    assert len(core_rows) == 1
    assert core_rows[0]["evidenceRefs"] == []
    # …without fabricating acceptances or appending the authority.
    assert _accepted_twins(store, team_id) == []
    assert [
        item
        for item in chain._records(team_id)
        if item.get("recordKind") == "human_adjudication"
    ] == []
    assert orphan_fact["reviewStatus"] == "pending"


def test_rejected_adjudication_never_materializes_bindings(tmp_path, monkeypatch):
    """Elimination keeps the store untouched: rejected never materializes."""
    team_id, store = _env(tmp_path, monkeypatch)
    seed = _seed_chain_collection_shape(store, team_id, with_core_claim_row=True)
    _install_round_reader(monkeypatch)

    result = _adjudicate(team_id, decision="rejected", key="materialize-rejected-1")
    assert result["status"] == "created"
    assert result["adjudication"]["decision"] == "rejected"
    assert _strict_records(store, team_id) == []
    assert _accepted_twins(store, team_id) == []
    assert len(store.list(team_id)) == 2
