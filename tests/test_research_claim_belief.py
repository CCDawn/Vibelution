"""R2.1 five-state claim belief table: criteria, fail-closed contract, service.

Covers the belief criteria table (two or more constructed scenarios per
state), the fail-closed self-consistency gates of ``ClaimBeliefTableEntry`` /
``ClaimBeliefTable``, the pure evaluation service rules (pending handling,
scope fail-closed, duplicate refs, evidence-store override, determinism,
empty-ledger boundary) and the disputed-only-marks semantics.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from core.research.workflow.contracts import (
    CLAIM_BELIEF_RULE_ID,
    CLAIM_BELIEF_SCHEMA_VERSION,
    ClaimBeliefTable,
    ClaimBeliefTableEntry,
    ContractValidationError,
    belief_state_for_counts,
    scope_hash_for,
)
from core.web.services.team_workflow.research_runtime import claim_belief_service

_EVALUATED_AT = "2026-08-28T00:00:00Z"

_SCOPE_FIELDS = {
    "program": "XH-202619",
    "theme": "cc-gpu-operator-001",
    "campaign": "cc-campaign-gpu-operator-001",
    "question": "SCI-091",
    "branch": "main",
    "workflow": "hypothesis_and_plan",
}


def _scope_hash() -> str:
    return scope_hash_for(**_SCOPE_FIELDS, agent_id="agent-evaluator", mode="formal")


def _ref(
    evidence_id: str,
    scope: str,
    *,
    review: str = "accepted",
    support: str = "supports",
) -> dict[str, Any]:
    return {
        "claimEvidenceId": evidence_id,
        "scopeHash": scope,
        "reviewStatus": review,
        "supportLevel": support,
        "sourceId": f"artifact:{evidence_id}",
    }


def _claim(
    claim_id: str,
    refs: list[dict[str, Any]],
    *,
    status: str = "proposed",
    scope: str | None = None,
) -> dict[str, Any]:
    resolved_scope = scope or _scope_hash()
    return {
        **_SCOPE_FIELDS,
        "agentId": "agent-evaluator",
        "mode": "formal",
        "scopeHash": resolved_scope,
        "claimId": claim_id,
        "claim": f"Claim {claim_id} under evaluation.",
        "status": status,
        "source": "agent",
        "evidenceRefs": refs,
        "counterEvidenceRefs": [],
        "supersedesClaimId": "",
        "retractsClaimId": "",
        "meetingPromotionAllowed": False,
        "createdBy": "agent-evaluator",
        "createdAt": _EVALUATED_AT,
    }


def _evaluate(*claims: dict[str, Any], records: list[dict[str, Any]] | None = None):
    return claim_belief_service.evaluate_claim_belief(
        list(claims),
        records,
        evaluated_at=_EVALUATED_AT,
    )


def _state_of(table: ClaimBeliefTable, claim_id: str) -> ClaimBeliefTableEntry:
    return next(entry for entry in table.entries if entry.claimId == claim_id)


# ---------------------------------------------------------------------------
# Criteria table (contract-level, single source of truth)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("accepted_support", "accepted_counter", "pending_support", "expected"),
    [
        # untested
        (0, 0, 0, "untested"),
        (0, 0, 0, "untested"),
        # weakly_supported
        (0, 0, 1, "weakly_supported"),
        (0, 0, 3, "weakly_supported"),
        # supported
        (1, 0, 0, "supported"),
        (2, 0, 1, "supported"),
        # contradicted
        (0, 1, 0, "contradicted"),
        (0, 2, 1, "contradicted"),
        # disputed
        (1, 1, 0, "disputed"),
        (2, 2, 1, "disputed"),
    ],
)
def test_belief_state_criteria_table(accepted_support, accepted_counter, pending_support, expected):
    assert (
        belief_state_for_counts(
            accepted_support=accepted_support,
            accepted_counter=accepted_counter,
            pending_support=pending_support,
        )
        == expected
    )


# ---------------------------------------------------------------------------
# Service-level five-state scenarios (>= 2 constructed scenarios per state)
# ---------------------------------------------------------------------------


def test_untested_scenarios():
    scope = _scope_hash()
    # a) proposed claim without any evidence ref
    table = _evaluate(_claim("claim-a", []))
    entry = _state_of(table, "claim-a")
    assert entry.beliefState == "untested"
    # b) only a rejected supporting ref
    table = _evaluate(
        _claim("claim-b", [_ref("ev-1", scope, review="rejected", support="supports")])
    )
    assert _state_of(table, "claim-b").beliefState == "untested"
    assert _state_of(table, "claim-b").neutralCount == 1
    # c) only a pending counter ref: unreviewed objection changes nothing
    table = _evaluate(
        _claim("claim-c", [_ref("ev-2", scope, review="pending", support="contradicts")])
    )
    entry = _state_of(table, "claim-c")
    assert entry.beliefState == "untested"
    assert entry.pendingCounterCount == 1
    # d) only an accepted-but-insufficient ref (neutral direction)
    table = _evaluate(
        _claim("claim-d", [_ref("ev-3", scope, review="accepted", support="insufficient")])
    )
    assert _state_of(table, "claim-d").beliefState == "untested"


def test_weakly_supported_scenarios():
    scope = _scope_hash()
    # a) one pending supporting ref only
    table = _evaluate(
        _claim("claim-a", [_ref("ev-1", scope, review="pending", support="supports")])
    )
    entry = _state_of(table, "claim-a")
    assert entry.beliefState == "weakly_supported"
    assert entry.pendingSupportCount == 1
    assert entry.supportingEvidenceIds == ()
    # b) pending supports plus a pending counter: unreviewed objection cannot demote
    table = _evaluate(
        _claim(
            "claim-b",
            [
                _ref("ev-1", scope, review="pending", support="supports"),
                _ref("ev-2", scope, review="pending", support="supports"),
                _ref("ev-3", scope, review="pending", support="contradicts"),
            ],
        )
    )
    entry = _state_of(table, "claim-b")
    assert entry.beliefState == "weakly_supported"
    assert entry.pendingSupportCount == 2
    assert entry.pendingCounterCount == 1
    # c) rejected support plus pending support
    table = _evaluate(
        _claim(
            "claim-c",
            [
                _ref("ev-1", scope, review="rejected", support="supports"),
                _ref("ev-2", scope, review="pending", support="supports"),
            ],
        )
    )
    assert _state_of(table, "claim-c").beliefState == "weakly_supported"


def test_supported_scenarios():
    scope = _scope_hash()
    # a) one accepted supporting ref
    table = _evaluate(
        _claim("claim-a", [_ref("ev-1", scope)], status="supported")
    )
    entry = _state_of(table, "claim-a")
    assert entry.beliefState == "supported"
    assert entry.supportingEvidenceIds == ("ev-1",)
    # b) accepted supports plus a pending counter: unreviewed objection cannot demote
    table = _evaluate(
        _claim(
            "claim-b",
            [
                _ref("ev-1", scope),
                _ref("ev-2", scope),
                _ref("ev-3", scope, review="pending", support="contradicts"),
            ],
            status="proposed",
        )
    )
    entry = _state_of(table, "claim-b")
    assert entry.beliefState == "supported"
    assert entry.acceptedSupportCount == 2
    assert entry.pendingCounterCount == 1
    # c) accepted support plus accepted-but-insufficient ref (neutral)
    table = _evaluate(
        _claim(
            "claim-c",
            [
                _ref("ev-1", scope),
                _ref("ev-2", scope, review="accepted", support="unverified"),
            ],
        )
    )
    entry = _state_of(table, "claim-c")
    assert entry.beliefState == "supported"
    assert entry.neutralCount == 1


def test_contradicted_scenarios():
    scope = _scope_hash()
    # a) one accepted counter ref, no accepted support
    table = _evaluate(
        _claim("claim-a", [_ref("ev-1", scope, support="contradicts")])
    )
    entry = _state_of(table, "claim-a")
    assert entry.beliefState == "contradicted"
    assert entry.counterEvidenceIds == ("ev-1",)
    # b) accepted counter plus rejected supporting ref
    table = _evaluate(
        _claim(
            "claim-b",
            [
                _ref("ev-1", scope, support="contradicts"),
                _ref("ev-2", scope, review="rejected", support="supports"),
            ],
        )
    )
    entry = _state_of(table, "claim-b")
    assert entry.beliefState == "contradicted"
    assert entry.neutralCount == 1
    # c) accepted counter plus pending supporting ref: pending cannot rescue
    table = _evaluate(
        _claim(
            "claim-c",
            [
                _ref("ev-1", scope, support="contradicts"),
                _ref("ev-2", scope, review="pending", support="supports"),
            ],
        )
    )
    entry = _state_of(table, "claim-c")
    assert entry.beliefState == "contradicted"
    assert entry.pendingSupportCount == 1


def test_disputed_scenarios_only_mark_without_adjudication():
    scope = _scope_hash()
    # a) one accepted support and one accepted counter coexist
    table = _evaluate(
        _claim(
            "claim-a",
            [
                _ref("ev-support", scope),
                _ref("ev-counter", scope, support="contradicts"),
            ],
        )
    )
    entry = _state_of(table, "claim-a")
    assert entry.beliefState == "disputed"
    assert entry.supportingEvidenceIds == ("ev-support",)
    assert entry.counterEvidenceIds == ("ev-counter",)
    # b) richer disputed mix with pending refs on both sides
    table = _evaluate(
        _claim(
            "claim-b",
            [
                _ref("ev-support-1", scope),
                _ref("ev-support-2", scope),
                _ref("ev-counter-1", scope, support="contradicts"),
                _ref("ev-counter-2", scope, support="contradicts"),
                _ref("ev-pending", scope, review="pending", support="supports"),
            ],
        )
    )
    entry = _state_of(table, "claim-b")
    assert entry.beliefState == "disputed"
    assert entry.pendingSupportCount == 1
    # disputed is only marked: no adjudication fields exist on the entry and
    # the table carries no resolution action; the ledger payload is untouched.
    assert set(entry.to_dict()) == {
        "claimId",
        "beliefState",
        "acceptedSupportCount",
        "acceptedCounterCount",
        "pendingSupportCount",
        "pendingCounterCount",
        "neutralCount",
        "supportingEvidenceIds",
        "counterEvidenceIds",
        "lastEvaluatedAt",
    }
    assert "resolvedBy" not in entry.to_dict()
    assert "adjudication" not in table.to_dict()


# ---------------------------------------------------------------------------
# Fail-closed contract self-consistency gates
# ---------------------------------------------------------------------------


def _entry_payload(**overrides) -> dict[str, Any]:
    payload = {
        "claimId": "claim-1",
        "beliefState": "supported",
        "acceptedSupportCount": 1,
        "acceptedCounterCount": 0,
        "pendingSupportCount": 0,
        "pendingCounterCount": 0,
        "neutralCount": 0,
        "supportingEvidenceIds": ["ev-1"],
        "counterEvidenceIds": [],
        "lastEvaluatedAt": _EVALUATED_AT,
    }
    payload.update(overrides)
    return payload


def test_contract_rejects_state_count_mismatches():
    # claimed supported but zero accepted supporting evidence
    with pytest.raises(ContractValidationError, match="does not match"):
        ClaimBeliefTableEntry.from_dict(
            _entry_payload(
                beliefState="supported",
                acceptedSupportCount=0,
                supportingEvidenceIds=[],
            )
        )
    # claimed untested but one accepted supporting evidence
    with pytest.raises(ContractValidationError, match="does not match"):
        ClaimBeliefTableEntry.from_dict(_entry_payload(beliefState="untested"))
    # claimed contradicted while support and counter coexist (must be disputed)
    with pytest.raises(ContractValidationError, match="does not match"):
        ClaimBeliefTableEntry.from_dict(
            _entry_payload(
                beliefState="contradicted",
                acceptedCounterCount=1,
                counterEvidenceIds=["ev-c"],
            )
        )
    # unknown belief state
    with pytest.raises(ContractValidationError, match="beliefState must be one of"):
        ClaimBeliefTableEntry.from_dict(_entry_payload(beliefState="probably_true"))
    # evidence id list does not match the accepted counter
    with pytest.raises(ContractValidationError, match="supportingEvidenceIds"):
        ClaimBeliefTableEntry.from_dict(
            _entry_payload(supportingEvidenceIds=["ev-1", "ev-2"])
        )
    with pytest.raises(ContractValidationError, match="counterEvidenceIds"):
        ClaimBeliefTableEntry.from_dict(
            _entry_payload(
                beliefState="disputed",
                acceptedCounterCount=1,
                counterEvidenceIds=["ev-x", "ev-y"],
            )
        )
    # one evidence id cannot be both supporting and counter
    with pytest.raises(ContractValidationError, match="both supporting and counter"):
        ClaimBeliefTableEntry.from_dict(
            _entry_payload(
                acceptedCounterCount=1,
                counterEvidenceIds=["ev-1"],
                beliefState="disputed",
            )
        )


def test_contract_rejects_duplicate_claim_ids():
    entry_a = _entry_payload()
    entry_b = _entry_payload(claimId="claim-1", supportingEvidenceIds=["ev-2"])
    table = {
        "schemaVersion": CLAIM_BELIEF_SCHEMA_VERSION,
        "ruleId": CLAIM_BELIEF_RULE_ID,
        "entries": [entry_a, entry_b],
        "beliefTableHash": "0" * 64,
    }
    with pytest.raises(ContractValidationError, match="duplicate claimId"):
        ClaimBeliefTable.from_dict(table)


def test_contract_rejects_hash_and_version_mismatch():
    entry = _entry_payload()
    valid = ClaimBeliefTable.create((ClaimBeliefTableEntry.from_dict(entry),))
    assert valid.to_dict()["beliefTableHash"]

    tampered = valid.to_dict()
    tampered["entries"][0]["neutralCount"] = 1
    with pytest.raises(ContractValidationError, match="beliefTableHash"):
        ClaimBeliefTable.from_dict(tampered)

    wrong_version = valid.to_dict()
    wrong_version["schemaVersion"] = CLAIM_BELIEF_SCHEMA_VERSION + 1
    with pytest.raises(ContractValidationError, match="schemaVersion"):
        ClaimBeliefTable.from_dict(wrong_version)

    wrong_rule = valid.to_dict()
    wrong_rule["ruleId"] = "claim_belief_rule.v0"
    with pytest.raises(ContractValidationError, match="ruleId"):
        ClaimBeliefTable.from_dict(wrong_rule)


def test_table_round_trip_normalizes_claim_order():
    first = _state_of(
        _evaluate(_claim("claim-a", []), _claim("claim-b", [])), "claim-a"
    )
    second = _state_of(
        _evaluate(_claim("claim-b", []), _claim("claim-a", [])), "claim-a"
    )
    table_a = _evaluate(_claim("claim-a", []), _claim("claim-b", []))
    table_b = _evaluate(_claim("claim-b", []), _claim("claim-a", []))
    assert first == second
    assert table_a.beliefTableHash == table_b.beliefTableHash
    assert [entry.claimId for entry in table_a.entries] == ["claim-a", "claim-b"]
    assert ClaimBeliefTable.from_dict(copy.deepcopy(table_a.to_dict())) == table_a


# ---------------------------------------------------------------------------
# Service rules: boundaries, evidence-store override, scope, determinism
# ---------------------------------------------------------------------------


def test_empty_ledger_produces_empty_sealed_table():
    table = _evaluate()
    assert table.entries == ()
    assert ClaimBeliefTable.from_dict(table.to_dict()) == table


def test_evidence_record_override_uses_authoritative_review_state():
    scope = _scope_hash()
    snapshot_pending = _claim(
        "claim-1", [_ref("ev-1", scope, review="pending", support="supports")]
    )
    assert _state_of(_evaluate(snapshot_pending), "claim-1").beliefState == (
        "weakly_supported"
    )
    accepted_record = [
        {
            "claimEvidenceId": "ev-1",
            "scopeHash": scope,
            "reviewStatus": "accepted",
            "supportLevel": "supports",
            "sourceId": "artifact:ev-1",
        }
    ]
    promoted = _evaluate(snapshot_pending, records=accepted_record)
    entry = _state_of(promoted, "claim-1")
    assert entry.beliefState == "supported"
    assert entry.supportingEvidenceIds == ("ev-1",)


def test_scope_mismatched_evidence_is_neutral():
    scope = _scope_hash()
    foreign_scope = "f" * 64
    table = _evaluate(_claim("claim-1", [_ref("ev-1", foreign_scope)]))
    entry = _state_of(table, "claim-1")
    assert entry.beliefState == "untested"
    assert entry.neutralCount == 1
    # the same holds when the evidence store reports a foreign scope
    record = [
        {
            "claimEvidenceId": "ev-1",
            "scopeHash": foreign_scope,
            "reviewStatus": "accepted",
            "supportLevel": "supports",
            "sourceId": "artifact:ev-1",
        }
    ]
    entry = _state_of(_evaluate(_claim("claim-1", [_ref("ev-1", scope)]), records=record), "claim-1")
    assert entry.beliefState == "untested"


def test_duplicate_evidence_refs_count_once():
    scope = _scope_hash()
    duplicate_ref = _ref("ev-1", scope)
    table = _evaluate(_claim("claim-1", [duplicate_ref, dict(duplicate_ref)], status="supported"))
    entry = _state_of(table, "claim-1")
    assert entry.beliefState == "supported"
    assert entry.acceptedSupportCount == 1
    assert entry.supportingEvidenceIds == ("ev-1",)


def test_unreferenced_evidence_records_are_ignored():
    scope = _scope_hash()
    unrelated = [
        {
            "claimEvidenceId": "ev-other",
            "scopeHash": scope,
            "reviewStatus": "accepted",
            "supportLevel": "supports",
            "sourceId": "artifact:ev-other",
        }
    ]
    table = _evaluate(_claim("claim-1", []), records=unrelated)
    assert _state_of(table, "claim-1").beliefState == "untested"


def test_service_is_deterministic_for_identical_inputs():
    scope = _scope_hash()
    claim = _claim(
        "claim-1",
        [
            _ref("ev-1", scope),
            _ref("ev-2", scope, review="pending", support="supports"),
        ],
    )
    first = _evaluate(claim)
    second = _evaluate(claim)
    assert first.to_dict() == second.to_dict()


def test_superseded_and_retracted_claims_still_evaluate():
    scope = _scope_hash()
    table = _evaluate(
        _claim("claim-superseded", [_ref("ev-1", scope)], status="superseded"),
        _claim("claim-retracted", [_ref("ev-2", scope)], status="retracted"),
    )
    assert _state_of(table, "claim-superseded").beliefState == "supported"
    assert _state_of(table, "claim-retracted").beliefState == "supported"
