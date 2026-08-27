"""Evolution-lineage contract for candidate hypotheses across revision rounds.

Canonical data carrier behind decision #3 of the 13-decision contract
(automatic revision is bounded at two rounds, ``auto_revision_exhausted`` is a
mandatory exception-review marker) and decision #2 (at most three finalists):

:class:`EvolutionLineage` is an append-only, ordered event sequence that records
how one candidate family evolved — draft introduction, screening outcome,
bounded revisions, pairwise advancement, finalist entry, merge/supersession and
convergence — without ever overwriting the old candidate bodies.  Every event
carries its trigger reason plus evidence references (screening artifact id,
review-disagreement artifact id, revision fork run id) so the two-round ceiling
stays auditable after the fact.

Fail-closed invariants (construction is rejected, never silently repaired):

- the lineage opens with ``introduced`` and a draft candidate id can only be
  introduced once, before any other event for that candidate;
- ``revised`` attempts follow the parent chain monotonically (parent + 1) and
  never exceed the frozen ceiling of two rounds;
- at most :data:`FINALIST_LIMIT` distinct candidates ever reach ``finalist``;
- ``superseded`` must reference a successor candidate that exists in the same
  lineage;
- no ``revised`` event may follow a ``revision_exhausted`` marker.

Actor semantics: ``system_policy`` events are recorded verbatim — they inform
the audit trail but are never presented as human-operator decisions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._validation import (
    ContractValidationError,
    require_int,
    require_list,
    require_text,
)
from .automation_policy import (
    MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO,
    MAX_AUTO_REVISION_ROUNDS_DEFAULT,
)
from .candidate_diversity import MAX_FINALIST_LIMIT

EVOLUTION_LINEAGE_SCHEMA_VERSION = 1

#: Decision #2: at most three candidates may enter the finalist set.  Bound
#: to the candidate-diversity screening contract, which owns this ruling.
FINALIST_LIMIT = MAX_FINALIST_LIMIT

#: Decision #3: the mandatory exception-review marker once the revision
#: budget is exhausted (recorded here; executed by the review pipeline only).
REVISION_EXHAUSTED_EXCEPTION = "auto_revision_exhausted"

#: Frozen ceiling for automatic revision rounds (decision #3, G12 may lower
#: it to one at policy level — the contract enforces the absolute ceiling).
MAX_REVISION_ROUNDS = MAX_AUTO_REVISION_ROUNDS_DEFAULT
MIN_ADJUSTABLE_REVISION_ROUNDS = MAX_AUTO_REVISION_ROUNDS_ADJUSTABLE_TO

EVOLUTION_LINEAGE_ACTORS = frozenset({"human_operator", "system_policy", "executor"})

#: Evidence references a lineage event may cite.  ``screened_out`` must cite a
#: screening artifact; ``revised`` must cite at least one evidence reference.
EVOLUTION_LINEAGE_EVIDENCE_KINDS = frozenset(
    {"screening_artifact", "disagreement_artifact", "fork_run"}
)


class EvolutionLineageEventKind(str, Enum):
    """The bounded set of lineage transitions for one candidate family."""

    INTRODUCED = "introduced"
    SCREENED_OUT = "screened_out"
    REVISED = "revised"
    REVISION_EXHAUSTED = "revision_exhausted"
    ADVANCED = "advanced"
    FINALIST = "finalist"
    SUPERSEDED = "superseded"
    CONVERGED = "converged"


EVOLUTION_LINEAGE_EVENT_KINDS = frozenset(kind.value for kind in EvolutionLineageEventKind)

#: Kinds that terminate a candidate's own evolution (advisory metadata only).
TERMINAL_LINEAGE_EVENT_KINDS = frozenset(
    {
        EvolutionLineageEventKind.SCREENED_OUT.value,
        EvolutionLineageEventKind.SUPERSEDED.value,
        EvolutionLineageEventKind.REVISION_EXHAUSTED.value,
        EvolutionLineageEventKind.CONVERGED.value,
    }
)


def _event_kind(value: Any) -> EvolutionLineageEventKind:
    text = str(value or "").strip().lower()
    try:
        return EvolutionLineageEventKind(text)
    except ValueError:
        raise ContractValidationError(
            "lineage event kind must be one of: "
            + ", ".join(sorted(EVOLUTION_LINEAGE_EVENT_KINDS))
        ) from None


@dataclass(frozen=True, slots=True)
class EvolutionLineageEvidenceRef:
    """A pointer to the artifact that justifies one lineage event."""

    kind: str
    ref: str

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvolutionLineageEvidenceRef:
        kind = require_text(payload, "kind").strip()
        if kind not in EVOLUTION_LINEAGE_EVIDENCE_KINDS:
            raise ContractValidationError(
                "lineage evidence kind must be one of: "
                + ", ".join(sorted(EVOLUTION_LINEAGE_EVIDENCE_KINDS))
            )
        return cls(kind=kind, ref=require_text(payload, "ref"))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref}


@dataclass(frozen=True, slots=True)
class EvolutionLineageEvent:
    """One immutable transition of one candidate inside a lineage.

    ``candidateId`` is the subject the event applies to.  For ``revised`` it is
    the revised successor version and ``parentCandidateId`` points at the
    candidate that was revised (old candidates are never overwritten).  For
    ``superseded`` the ``successorCandidateId`` is the merge/alternative target
    that must exist inside the same lineage.
    """

    eventId: str
    candidateId: str
    kind: str
    roundId: str
    reason: str
    occurredAt: str
    actor: str
    revisionAttempt: int = 0
    parentCandidateId: str = ""
    successorCandidateId: str = ""
    evidenceRefs: tuple[EvolutionLineageEvidenceRef, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvolutionLineageEvent:
        kind = _event_kind(payload.get("kind"))
        actor = require_text(payload, "actor")
        if actor not in EVOLUTION_LINEAGE_ACTORS:
            raise ContractValidationError(
                "lineage event actor must be one of: "
                + ", ".join(sorted(EVOLUTION_LINEAGE_ACTORS))
            )
        revision_attempt = require_int(payload, "revisionAttempt", minimum=0)
        evidence_refs = tuple(
            EvolutionLineageEvidenceRef.from_dict(item)
            for item in require_list(payload, "evidenceRefs")
        )
        evidence_ref_ids = [ref.ref for ref in evidence_refs]
        if len(set(evidence_ref_ids)) != len(evidence_ref_ids):
            raise ContractValidationError(
                "lineage event evidence references must be distinct"
            )
        event = cls(
            eventId=require_text(payload, "eventId"),
            candidateId=require_text(payload, "candidateId"),
            kind=kind.value,
            roundId=require_text(payload, "roundId"),
            reason=require_text(payload, "reason"),
            occurredAt=require_text(payload, "occurredAt"),
            actor=actor,
            revisionAttempt=revision_attempt,
            parentCandidateId=str(payload.get("parentCandidateId") or "").strip(),
            successorCandidateId=str(payload.get("successorCandidateId") or "").strip(),
            evidenceRefs=evidence_refs,
        )
        if kind is EvolutionLineageEventKind.REVISED:
            if not event.parentCandidateId:
                raise ContractValidationError(
                    "a revised lineage event requires parentCandidateId: old "
                    "candidates are never overwritten"
                )
            if event.parentCandidateId == event.candidateId:
                raise ContractValidationError(
                    "a revised lineage event cannot target its own parent candidate"
                )
            if revision_attempt < 1:
                raise ContractValidationError(
                    "a revised lineage event requires revisionAttempt >= 1"
                )
            if not event.evidenceRefs:
                raise ContractValidationError(
                    "a revised lineage event requires at least one evidence "
                    "reference (screening / disagreement / fork run)"
                )
        else:
            if revision_attempt != 0:
                raise ContractValidationError(
                    f"a {kind.value} lineage event must not carry a revisionAttempt"
                )
            if event.parentCandidateId:
                raise ContractValidationError(
                    f"a {kind.value} lineage event must not carry parentCandidateId"
                )
        if kind is EvolutionLineageEventKind.SCREENED_OUT:
            if not any(ref.kind == "screening_artifact" for ref in event.evidenceRefs):
                raise ContractValidationError(
                    "a screened_out lineage event must cite its screening "
                    "artifact evidence"
                )
        if kind is EvolutionLineageEventKind.SUPERSEDED and not event.successorCandidateId:
            raise ContractValidationError(
                "a superseded lineage event requires successorCandidateId"
            )
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "eventId": self.eventId,
            "candidateId": self.candidateId,
            "kind": self.kind,
            "roundId": self.roundId,
            "reason": self.reason,
            "occurredAt": self.occurredAt,
            "actor": self.actor,
            "revisionAttempt": self.revisionAttempt,
            "parentCandidateId": self.parentCandidateId,
            "successorCandidateId": self.successorCandidateId,
            "evidenceRefs": [ref.to_dict() for ref in self.evidenceRefs],
        }

    def evidence_refs_of_kind(self, kind: str) -> tuple[EvolutionLineageEvidenceRef, ...]:
        return tuple(ref for ref in self.evidenceRefs if ref.kind == kind)


def _validate_revision_chain(events: Sequence["EvolutionLineageEvent"]) -> None:
    """Revised attempts must follow the parent chain monotonically, <= ceiling.

    The expected attempt of a revision is its parent's attempt plus one (an
    introduced or otherwise non-revised candidate counts as attempt zero), so
    the attempt sequence along any ancestry chain is strictly monotonic and the
    frozen two-round ceiling can never be crossed.
    """

    attempt_by_candidate: dict[str, int] = {}
    exhausted = False
    for event in events:
        if event.kind == EvolutionLineageEventKind.REVISED.value:
            if exhausted:
                raise ContractValidationError(
                    "no revised lineage event may follow revision_exhausted: "
                    f"event {event.eventId} reopens a closed revision budget"
                )
            parent_attempt = attempt_by_candidate.get(event.parentCandidateId)
            if parent_attempt is None:
                raise ContractValidationError(
                    f"revised lineage event {event.eventId} references unknown "
                    f"or future parent candidate {event.parentCandidateId}"
                )
            expected_attempt = parent_attempt + 1
            if event.revisionAttempt != expected_attempt:
                raise ContractValidationError(
                    "revised lineage events must be monotonic along the parent "
                    f"chain: event {event.eventId} carries attempt "
                    f"{event.revisionAttempt}, expected {expected_attempt}"
                )
            if event.revisionAttempt > MAX_REVISION_ROUNDS:
                raise ContractValidationError(
                    "automatic revision is bounded at "
                    f"{MAX_REVISION_ROUNDS} rounds (decision #3): event "
                    f"{event.eventId} carries attempt {event.revisionAttempt}"
                )
            attempt_by_candidate[event.candidateId] = event.revisionAttempt
        elif event.kind == EvolutionLineageEventKind.REVISION_EXHAUSTED.value:
            exhausted = True
        elif event.candidateId not in attempt_by_candidate:
            attempt_by_candidate[event.candidateId] = 0


@dataclass(frozen=True, slots=True)
class EvolutionLineage:
    """Ordered evolution history of one candidate family for one question."""

    lineageId: str
    questionId: str
    roundId: str
    events: tuple[EvolutionLineageEvent, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> EvolutionLineage:
        events = tuple(
            EvolutionLineageEvent.from_dict(item)
            for item in require_list(payload, "events", non_empty=True)
        )
        lineage = cls(
            lineageId=require_text(payload, "lineageId"),
            questionId=require_text(payload, "questionId"),
            roundId=require_text(payload, "roundId"),
            events=events,
        )
        lineage._validate_sequence()
        return lineage

    def _validate_sequence(self) -> None:
        if self.events[0].kind != EvolutionLineageEventKind.INTRODUCED.value:
            raise ContractValidationError(
                "a lineage must open with an introduced event: "
                f"{self.events[0].eventId} is {self.events[0].kind}"
            )
        seen_candidates: set[str] = set()
        seen_event_ids: set[str] = set()
        for event in self.events:
            if event.eventId in seen_event_ids:
                raise ContractValidationError(
                    f"lineage event ids must be unique: {event.eventId}"
                )
            seen_event_ids.add(event.eventId)
            if event.kind == EvolutionLineageEventKind.INTRODUCED.value:
                if event.candidateId in seen_candidates:
                    raise ContractValidationError(
                        "introduced must precede every other lineage event kind "
                        f"of the same candidate: {event.candidateId} already has "
                        f"an earlier event before {event.eventId}"
                    )
            seen_candidates.add(event.candidateId)
        finalist_candidates = [
            event.candidateId
            for event in self.events
            if event.kind == EvolutionLineageEventKind.FINALIST.value
        ]
        if len(set(finalist_candidates)) > FINALIST_LIMIT:
            raise ContractValidationError(
                f"at most {FINALIST_LIMIT} candidates may reach finalist "
                f"(decision #2): {sorted(set(finalist_candidates))}"
            )
        known_candidates = {event.candidateId for event in self.events}
        for event in self.events:
            if event.kind == EvolutionLineageEventKind.SUPERSEDED.value:
                if event.successorCandidateId not in known_candidates:
                    raise ContractValidationError(
                        "a superseded lineage event must reference a successor "
                        f"inside the same lineage: {event.successorCandidateId} "
                        "is unknown"
                    )
        _validate_revision_chain(self.events)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lineageId": self.lineageId,
            "questionId": self.questionId,
            "roundId": self.roundId,
            "events": [event.to_dict() for event in self.events],
        }

    def events_for_candidate(self, candidate_id: str) -> tuple[EvolutionLineageEvent, ...]:
        return tuple(event for event in self.events if event.candidateId == candidate_id)

    def has_revision_exhausted(self) -> bool:
        return any(
            event.kind == EvolutionLineageEventKind.REVISION_EXHAUSTED.value
            for event in self.events
        )

    def max_revision_round(self) -> int:
        return max(
            (
                event.revisionAttempt
                for event in self.events
                if event.kind == EvolutionLineageEventKind.REVISED.value
            ),
            default=0,
        )


def evolution_lineage_summary(lineage: EvolutionLineage) -> dict[str, Any]:
    """Audit summary over one lineage (data only — never a decision)."""

    kind_counts: dict[str, int] = {}
    actor_counts: dict[str, int] = {}
    for event in lineage.events:
        kind_counts[event.kind] = kind_counts.get(event.kind, 0) + 1
        actor_counts[event.actor] = actor_counts.get(event.actor, 0) + 1
    finalists = [
        event.candidateId
        for event in lineage.events
        if event.kind == EvolutionLineageEventKind.FINALIST.value
    ]
    return {
        "eventCount": len(lineage.events),
        "kindCounts": dict(sorted(kind_counts.items())),
        "actorCounts": dict(sorted(actor_counts.items())),
        "systemPolicyEventCount": actor_counts.get("system_policy", 0),
        "revisionRoundCount": lineage.max_revision_round(),
        "finalistCandidateIds": list(dict.fromkeys(finalists)),
        "mandatoryExceptionReview": (
            REVISION_EXHAUSTED_EXCEPTION if lineage.has_revision_exhausted() else ""
        ),
    }


def mandatory_exception_review_required(lineage: EvolutionLineage) -> bool:
    """Whether the lineage hit the revision budget (decision #3 exception)."""

    return lineage.has_revision_exhausted()


__all__ = [
    "EVOLUTION_LINEAGE_ACTORS",
    "EVOLUTION_LINEAGE_EVIDENCE_KINDS",
    "EVOLUTION_LINEAGE_EVENT_KINDS",
    "EVOLUTION_LINEAGE_SCHEMA_VERSION",
    "EvolutionLineage",
    "EvolutionLineageEvent",
    "EvolutionLineageEventKind",
    "EvolutionLineageEvidenceRef",
    "FINALIST_LIMIT",
    "MAX_REVISION_ROUNDS",
    "MIN_ADJUSTABLE_REVISION_ROUNDS",
    "REVISION_EXHAUSTED_EXCEPTION",
    "TERMINAL_LINEAGE_EVENT_KINDS",
    "evolution_lineage_summary",
    "mandatory_exception_review_required",
]
