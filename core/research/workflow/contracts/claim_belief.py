"""Five-state claim belief table contract with fail-closed self-consistency.

The belief table is a *derived, read-only projection* over the append-only
claim ledger (:mod:`~core.research.workflow.contracts.claim_ledger`) and its
claim-evidence refs.  It upgrades the implicit claim-to-evidence belief state
into a first-class contract.  It never writes: ledger status (proposed /
supported / superseded / retracted) stays the governance state, while
``beliefState`` below is the evidence belief state derived from counters.

Five-state criteria table (``accepted`` means ``reviewStatus == "accepted"``
AND a direction-bearing ``supportLevel``):

=====================  =============================================
beliefState            criterion
=====================  =============================================
``untested``           accepted support == 0, accepted counter == 0,
                       pending support == 0
``weakly_supported``   accepted support == 0, accepted counter == 0,
                       pending support >= 1
``supported``          accepted support >= 1, accepted counter == 0
``contradicted``       accepted support == 0, accepted counter >= 1
``disputed``           accepted support >= 1 AND accepted counter
                       >= 1 (coexist, unresolved)
=====================  =============================================

Pending evidence never produces effective support or counter-evidence.
Pending *counter* evidence does not change the state at all (fail-closed:
an unreviewed objection cannot demote ``weakly_supported`` nor fabricate
``contradicted``/``disputed``); it is only surfaced through the counters so
human review can prioritize it.  Rejected/stale refs and refs whose
``supportLevel`` is ``insufficient``/``unverified`` are neutral.

``disputed`` is only ever *marked*: adjudication stays in the ledger
(supersede/retract) and in evidence re-review.  The table carries no
adjudication fields, so a disputed claim can never silently re-enter main
ranking through this projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._canonical import sha256_hex
from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_text,
)

CLAIM_BELIEF_SCHEMA_VERSION = 1
CLAIM_BELIEF_RULE_ID = "claim_belief_rule.v1"

CLAIM_BELIEF_STATES = frozenset(
    {"untested", "weakly_supported", "supported", "contradicted", "disputed"}
)


def belief_state_for_counts(
    *,
    accepted_support: int,
    accepted_counter: int,
    pending_support: int,
) -> str:
    """Single source of truth for the five-state criteria table.

    Both the belief service and the contract self-consistency validation
    call this function, so the criteria can never drift between the
    evaluator and the fail-closed gate.
    """
    for name, value in (
        ("accepted_support", accepted_support),
        ("accepted_counter", accepted_counter),
        ("pending_support", pending_support),
    ):
        if value < 0:
            raise ContractValidationError(f"belief count {name} must be non-negative")
    if accepted_counter == 0:
        if accepted_support >= 1:
            return "supported"
        if pending_support >= 1:
            return "weakly_supported"
        return "untested"
    if accepted_support >= 1:
        return "disputed"
    return "contradicted"


@dataclass(frozen=True, slots=True)
class ClaimBeliefTableEntry:
    """One claim's five-state belief with traceable evidence counts."""

    claimId: str
    beliefState: str
    acceptedSupportCount: int
    acceptedCounterCount: int
    pendingSupportCount: int
    pendingCounterCount: int
    neutralCount: int
    supportingEvidenceIds: tuple[str, ...]
    counterEvidenceIds: tuple[str, ...]
    lastEvaluatedAt: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClaimBeliefTableEntry:
        belief_state = require_text(payload, "beliefState").lower()
        if belief_state not in CLAIM_BELIEF_STATES:
            raise ContractValidationError(
                "beliefState must be one of: " + ", ".join(sorted(CLAIM_BELIEF_STATES))
            )
        accepted_support = require_int(payload, "acceptedSupportCount")
        accepted_counter = require_int(payload, "acceptedCounterCount")
        pending_support = require_int(payload, "pendingSupportCount")
        pending_counter = require_int(payload, "pendingCounterCount")
        neutral = require_int(payload, "neutralCount")
        expected_state = belief_state_for_counts(
            accepted_support=accepted_support,
            accepted_counter=accepted_counter,
            pending_support=pending_support,
        )
        if belief_state != expected_state:
            raise ContractValidationError(
                f"beliefState '{belief_state}' does not match the evidence counts "
                f"(criterion table expects '{expected_state}')"
            )
        supporting_ids = tuple(
            sorted({str(item) for item in require_list(payload, "supportingEvidenceIds")})
        )
        counter_ids = tuple(
            sorted({str(item) for item in require_list(payload, "counterEvidenceIds")})
        )
        if len(supporting_ids) != accepted_support:
            raise ContractValidationError(
                "supportingEvidenceIds must list exactly the accepted supporting evidence"
            )
        if len(counter_ids) != accepted_counter:
            raise ContractValidationError(
                "counterEvidenceIds must list exactly the accepted counter evidence"
            )
        if set(supporting_ids) & set(counter_ids):
            raise ContractValidationError(
                "one evidence id cannot be both supporting and counter evidence"
            )
        return cls(
            claimId=require_text(payload, "claimId"),
            beliefState=belief_state,
            acceptedSupportCount=accepted_support,
            acceptedCounterCount=accepted_counter,
            pendingSupportCount=pending_support,
            pendingCounterCount=pending_counter,
            neutralCount=neutral,
            supportingEvidenceIds=supporting_ids,
            counterEvidenceIds=counter_ids,
            lastEvaluatedAt=require_text(payload, "lastEvaluatedAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claimId": self.claimId,
            "beliefState": self.beliefState,
            "acceptedSupportCount": self.acceptedSupportCount,
            "acceptedCounterCount": self.acceptedCounterCount,
            "pendingSupportCount": self.pendingSupportCount,
            "pendingCounterCount": self.pendingCounterCount,
            "neutralCount": self.neutralCount,
            "supportingEvidenceIds": list(self.supportingEvidenceIds),
            "counterEvidenceIds": list(self.counterEvidenceIds),
            "lastEvaluatedAt": self.lastEvaluatedAt,
        }


def _belief_table_hash(entries: tuple[ClaimBeliefTableEntry, ...]) -> str:
    return sha256_hex(
        {
            "schemaVersion": CLAIM_BELIEF_SCHEMA_VERSION,
            "ruleId": CLAIM_BELIEF_RULE_ID,
            "entries": [entry.to_dict() for entry in entries],
        }
    )


@dataclass(frozen=True, slots=True)
class ClaimBeliefTable:
    """Fail-closed container of per-claim belief entries.

    Entries are normalized to ``claimId`` order so the content hash is
    stable for identical evaluations regardless of input ordering.
    """

    schemaVersion: int
    ruleId: str
    entries: tuple[ClaimBeliefTableEntry, ...]
    beliefTableHash: str

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClaimBeliefTable:
        schema_version = payload.get("schemaVersion")
        if schema_version != CLAIM_BELIEF_SCHEMA_VERSION:
            raise ContractValidationError(
                f"claim belief table schemaVersion must be {CLAIM_BELIEF_SCHEMA_VERSION}"
            )
        rule_id = require_text(payload, "ruleId")
        if rule_id != CLAIM_BELIEF_RULE_ID:
            raise ContractValidationError(
                f"claim belief table ruleId must be {CLAIM_BELIEF_RULE_ID}"
            )
        raw_entries = require_list(payload, "entries")
        entries: list[ClaimBeliefTableEntry] = []
        seen_claim_ids: set[str] = set()
        for index, item in enumerate(raw_entries):
            if not isinstance(item, dict):
                raise ContractValidationError(
                    f"belief table entry at index {index} must be an object"
                )
            entry = ClaimBeliefTableEntry.from_dict(item)
            if entry.claimId in seen_claim_ids:
                raise ContractValidationError(
                    f"belief table contains duplicate claimId '{entry.claimId}'"
                )
            seen_claim_ids.add(entry.claimId)
            entries.append(entry)
        entries_tuple = tuple(sorted(entries, key=lambda entry: entry.claimId))
        table_hash = require_text(payload, "beliefTableHash").lower()
        expected_hash = _belief_table_hash(entries_tuple)
        if table_hash != expected_hash:
            raise ContractValidationError(
                "beliefTableHash does not match the canonical entry set"
            )
        return cls(
            schemaVersion=schema_version,
            ruleId=rule_id,
            entries=entries_tuple,
            beliefTableHash=table_hash,
        )

    @classmethod
    def create(cls, entries: tuple[ClaimBeliefTableEntry, ...]) -> ClaimBeliefTable:
        """Build a table from freshly evaluated entries and seal its hash."""
        normalized = tuple(sorted(entries, key=lambda entry: entry.claimId))
        return cls(
            schemaVersion=CLAIM_BELIEF_SCHEMA_VERSION,
            ruleId=CLAIM_BELIEF_RULE_ID,
            entries=normalized,
            beliefTableHash=_belief_table_hash(normalized),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "ruleId": self.ruleId,
            "entries": [entry.to_dict() for entry in self.entries],
            "beliefTableHash": self.beliefTableHash,
        }
