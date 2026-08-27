"""Pure five-state claim belief evaluation service (no persistence).

This service turns the implicit claim-to-evidence belief state into an
explicit :class:`ClaimBeliefTable` projection.  It is a deterministic pure
function: no storage access, no threading, no side effects; the same claims,
evidence records and ``evaluated_at`` always produce the identical table
hash.  It never mutates the claim ledger and never adjudicates: a
``disputed`` result is only marked, human adjudication stays in the ledger
(supersede/retract) and in evidence re-review.

Evaluation rules (fail-closed everywhere):

1. Every claim is parsed through :class:`ClaimLedgerEntry`, so ledger-level
   contract validation (scope hash, accepted-evidence gating) applies first.
2. Evidence state resolution: a claim's ``evidenceRefs`` are joined by
   ``claimEvidenceId`` against the optional ``evidence_records`` (the
   authoritative current state of the claim-evidence store, including
   ``stale`` propagation).  A record that matches wins over the ref's
   snapshot; an unmatched ref keeps its own snapshot state.  Records not
   referenced by any claim are ignored (the table is a claim view).
3. Scope is fail-closed: a ref whose resolved ``scopeHash`` differs from the
   claim's ``scopeHash`` is neutral and can never support or contradict,
   mirroring the ledger contract's "supported claims reference only
   scope-consistent evidence".
4. Direction follows ``supportLevel`` exactly like
   ``ClaimEvidenceRef.supports_claim``/``contradicts_claim``: ``supports``
   counts on the supporting side, ``contradicts`` on the counter side, and
   ``insufficient``/``unverified`` (or any unknown value) is neutral.
5. Review status: ``accepted`` is effective; ``pending`` only fills the
   pending counters; every other status (``rejected``, ``stale``, unknown)
   is neutral and can never support or contradict.
6. Pending evidence never promotes or demotes: pending support only lifts
   ``untested`` to ``weakly_supported`` when neither side has accepted
   evidence; pending counter evidence changes nothing (an unreviewed
   objection cannot fabricate ``contradicted``/``disputed``).
7. Duplicate ``claimEvidenceId`` references inside one claim count once
   (first occurrence wins): repeating a reference cannot amplify belief.
8. The belief state itself comes from
   :func:`core.research.workflow.contracts.claim_belief.belief_state_for_counts`,
   the single source of truth shared with the contract's fail-closed
   self-consistency validation.

Superseded/retracted claims are evaluated like any other entry; filtering
which claims to evaluate is the caller's policy, not this projection's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from core.research.workflow.contracts import (
    ACCEPTED_REVIEW_STATUS,
    ClaimBeliefTable,
    ClaimBeliefTableEntry,
    ClaimLedgerEntry,
    belief_state_for_counts,
)

_NEUTRAL = "neutral"
_ACCEPTED_SUPPORT = "accepted_support"
_ACCEPTED_COUNTER = "accepted_counter"
_PENDING_SUPPORT = "pending_support"
_PENDING_COUNTER = "pending_counter"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_claim(entry: Mapping[str, Any] | ClaimLedgerEntry) -> ClaimLedgerEntry:
    if isinstance(entry, ClaimLedgerEntry):
        return entry
    if isinstance(entry, Mapping):
        return ClaimLedgerEntry.from_dict(dict(entry))
    raise ValueError("each claim must be a ClaimLedgerEntry or its mapping payload")


def _resolved_state_index(
    evidence_records: Sequence[Mapping[str, Any]] | None,
) -> dict[str, dict[str, str]]:
    index: dict[str, dict[str, str]] = {}
    for record in evidence_records or ():
        if not isinstance(record, Mapping):
            raise ValueError("each evidence record must be a mapping")
        evidence_id = str(record.get("claimEvidenceId") or "").strip()
        if not evidence_id:
            continue
        index[evidence_id] = {
            "reviewStatus": str(record.get("reviewStatus") or "").strip().lower(),
            "supportLevel": str(record.get("supportLevel") or "").strip().lower(),
            "scopeHash": str(record.get("scopeHash") or "").strip().lower(),
            "sourceId": str(record.get("sourceId") or "").strip(),
        }
    return index


def _classify(review_status: str, support_level: str) -> str:
    if support_level == "supports":
        if review_status == ACCEPTED_REVIEW_STATUS:
            return _ACCEPTED_SUPPORT
        if review_status == "pending":
            return _PENDING_SUPPORT
        return _NEUTRAL
    if support_level == "contradicts":
        if review_status == ACCEPTED_REVIEW_STATUS:
            return _ACCEPTED_COUNTER
        if review_status == "pending":
            return _PENDING_COUNTER
        return _NEUTRAL
    return _NEUTRAL


def _entry_for_claim(
    claim: ClaimLedgerEntry,
    resolved_states: Mapping[str, Mapping[str, str]],
    evaluated_at: str,
) -> ClaimBeliefTableEntry:
    accepted_support = 0
    accepted_counter = 0
    pending_support = 0
    pending_counter = 0
    neutral = 0
    supporting_ids: set[str] = set()
    counter_ids: set[str] = set()
    seen_ids: set[str] = set()
    for ref in claim.evidenceRefs:
        evidence_id = ref.claimEvidenceId
        if evidence_id in seen_ids:
            continue
        seen_ids.add(evidence_id)
        state = resolved_states.get(evidence_id)
        review_status = state["reviewStatus"] if state else ref.reviewStatus
        support_level = state["supportLevel"] if state else ref.supportLevel
        scope_hash = state["scopeHash"] if state else ref.scopeHash
        if scope_hash != claim.scopeHash:
            neutral += 1
            continue
        classification = _classify(review_status, support_level)
        if classification == _ACCEPTED_SUPPORT:
            accepted_support += 1
            supporting_ids.add(evidence_id)
        elif classification == _ACCEPTED_COUNTER:
            accepted_counter += 1
            counter_ids.add(evidence_id)
        elif classification == _PENDING_SUPPORT:
            pending_support += 1
        elif classification == _PENDING_COUNTER:
            pending_counter += 1
        else:
            neutral += 1
    return ClaimBeliefTableEntry.from_dict(
        {
            "claimId": claim.claimId,
            "beliefState": belief_state_for_counts(
                accepted_support=accepted_support,
                accepted_counter=accepted_counter,
                pending_support=pending_support,
            ),
            "acceptedSupportCount": accepted_support,
            "acceptedCounterCount": accepted_counter,
            "pendingSupportCount": pending_support,
            "pendingCounterCount": pending_counter,
            "neutralCount": neutral,
            "supportingEvidenceIds": sorted(supporting_ids),
            "counterEvidenceIds": sorted(counter_ids),
            "lastEvaluatedAt": evaluated_at,
        }
    )


def evaluate_claim_belief(
    claims: Sequence[Mapping[str, Any] | ClaimLedgerEntry],
    evidence_records: Sequence[Mapping[str, Any]] | None = None,
    *,
    evaluated_at: str | None = None,
) -> ClaimBeliefTable:
    """Evaluate the five-state belief table for the given claims.

    ``claims`` are ledger entries (contract payloads or instances);
    ``evidence_records`` optionally carry the authoritative current state of
    each ``claimEvidenceId`` (as stored by the claim-evidence store).  The
    result is sealed by the :class:`ClaimBeliefTable` fail-closed contract.
    """
    resolved_states = _resolved_state_index(evidence_records)
    timestamp = (evaluated_at or "").strip() or _utc_now()
    entries = tuple(
        _entry_for_claim(_normalize_claim(claim), resolved_states, timestamp)
        for claim in claims
    )
    return ClaimBeliefTable.create(entries)
