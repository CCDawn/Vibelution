"""Pure state service for policy generations, drain and orphan outcomes.

R3.3 extension of the automation policy service (decision #12): a policy
content-hash change opens a new generation that becomes effective from a
checkpoint, the superseded generation requests a drain, and in-flight
outcomes that still reference the old generation either finish (drain
completes) or are intercepted as orphans when they try to commit across
generations.  This module computes all of that as pure state transitions over
``PolicyGenerationRecord`` / ``DrainTransition`` / ``OrphanOutcomeRecord``
values.  It never forks checkpoints (``checkpoint_lifecycle`` owns that),
never subscribes to the canonical command chain, never executes automation,
and shares nothing with the challenge-cup maintenance-fence drain, which is a
reset coordination boundary with different semantics.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core.research.workflow.contracts.policy_generation import (
    DRAIN_ACTORS,
    DrainTransition,
    OrphanOutcomeRecord,
    PolicyGenerationRecord,
    PolicyGenerationValidationError,
    ensure_drain_mode_transition,
    ensure_orphan_disposition_transition,
)


class PolicyGenerationServiceError(ValueError):
    """Typed fail-closed error for policy generation handling."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _now_or(default: str | None) -> str:
    if default is not None and str(default).strip():
        return str(default).strip()
    return datetime.now(UTC).isoformat()


def _require_timestamp(value: str | None, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PolicyGenerationServiceError(
            f"{field} must be a non-empty ISO-8601 timestamp",
            code="invalid_timestamp",
        )
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise PolicyGenerationServiceError(
            f"{field} must be a parseable ISO-8601 timestamp: {text}",
            code="invalid_timestamp",
        ) from exc
    return text


def validate_generation_chain(
    records: Sequence[PolicyGenerationRecord],
) -> list[PolicyGenerationRecord]:
    """Validate chain invariants: one policyId, generations 1..N ascending."""

    chain = list(records)
    if not chain:
        raise PolicyGenerationServiceError(
            "a policy generation chain needs at least one generation",
            code="generation_chain_empty",
        )
    policy_ids = {record.policyId for record in chain}
    if len(policy_ids) != 1:
        raise PolicyGenerationServiceError(
            "all generations in a chain must share one policyId",
            code="policy_id_mismatch",
        )
    expected = list(range(1, len(chain) + 1))
    actual = [record.generation for record in chain]
    if actual != expected:
        raise PolicyGenerationServiceError(
            "generation numbers must be contiguous 1..N in chain order; got "
            f"{actual}",
            code="generation_chain_discontinuous",
        )
    for record in chain[1:]:
        if record.predecessorGeneration != record.generation - 1:
            raise PolicyGenerationServiceError(
                f"generation {record.generation} must reference generation "
                f"{record.generation - 1} as predecessor",
                code="predecessor_mismatch",
            )
    return chain


def latest_generation(
    records: Sequence[PolicyGenerationRecord],
) -> PolicyGenerationRecord:
    """Return the newest (active) generation of a validated chain."""

    return validate_generation_chain(records)[-1]


def _generation_by_number(
    chain: Sequence[PolicyGenerationRecord], generation: int
) -> PolicyGenerationRecord:
    for record in chain:
        if record.generation == generation:
            return record
    raise PolicyGenerationServiceError(
        f"generation {generation} does not exist in the chain",
        code="unknown_generation",
    )


def _replace(
    record: PolicyGenerationRecord, **changes: Any
) -> PolicyGenerationRecord:
    return PolicyGenerationRecord.from_dict(
        {**record.to_dict(), **changes}
    )


@dataclass(frozen=True, slots=True)
class GenerationOpening:
    """Result of opening a new generation on top of an existing chain."""

    newGeneration: PolicyGenerationRecord
    chain: tuple[PolicyGenerationRecord, ...]
    supersededGeneration: PolicyGenerationRecord | None
    supersededTransition: DrainTransition | None


def open_generation(
    records: Sequence[PolicyGenerationRecord],
    *,
    policy_content_hash: str,
    effective_from_checkpoint: str | None,
    actor: str,
    reason: str,
    activated_at: str | None = None,
    now: str | None = None,
) -> GenerationOpening:
    """Open a new generation because the policy content hash changed.

    Preconditions (all fail-closed):

    * no generation may sit in ``requested``/``draining`` (one in-flight
      drain at a time);
    * every superseded generation must already be ``drained`` and the
      latest generation must be quiescent (``none``) or ``drained``;
    * the new hash must differ from the latest hash (an unchanged hash never
      opens a generation);
    * from the second generation on, the new generation becomes effective
      from a declared checkpoint (decision #12).

    The superseded latest generation receives the ``none -> requested``
    downgrade transition carrying the initiator actor and reason; the new
    generation starts at ``drainMode=none`` with ``activatedAt`` null in the
    preview stage.
    """

    chain = validate_generation_chain(records)
    latest = chain[-1]
    timestamp = _now_or(now)

    if str(policy_content_hash or "").strip() == latest.policyContentHash:
        raise PolicyGenerationServiceError(
            "policy content hash is unchanged; a new generation is only "
            "opened by a hash change",
            code="hash_unchanged",
        )
    in_flight = [
        record.generation
        for record in chain
        if record.drainMode in {"requested", "draining"}
    ]
    if in_flight:
        raise PolicyGenerationServiceError(
            "generations "
            + ", ".join(str(item) for item in in_flight)
            + " are still draining; a new generation cannot open while a "
            "drain is in flight",
            code="drain_in_progress",
        )
    non_drained = [
        record.generation
        for record in chain[:-1]
        if record.drainMode != "drained"
    ]
    if non_drained:
        raise PolicyGenerationServiceError(
            "superseded generations "
            + ", ".join(str(item) for item in non_drained)
            + " must be drained before a new generation opens",
            code="superseded_not_drained",
        )
    if latest.drainMode not in {"none", "drained"}:
        raise PolicyGenerationServiceError(
            f"latest generation {latest.generation} is in drainMode "
            f"{latest.drainMode!r}; expected none or drained",
            code="latest_not_quiescent",
        )

    checkpoint = str(effective_from_checkpoint or "").strip()
    new_number = latest.generation + 1
    if not checkpoint:
        raise PolicyGenerationServiceError(
            f"generation {new_number} must become effective from a declared "
            "checkpoint (decision #12: checkpoint + drain)",
            code="checkpoint_required",
        )

    if latest.drainMode == "none":
        superseded_transition = _build_transition(
            latest,
            from_mode="none",
            to_mode="requested",
            actor=actor,
            reason=reason,
            now=timestamp,
        )
        superseded = _replace(latest, drainMode="requested")
    else:
        superseded_transition = None
        superseded = latest

    new_generation = PolicyGenerationRecord.from_dict(
        {
            "policyId": latest.policyId,
            "generation": new_number,
            "policyContentHash": str(policy_content_hash or "").strip(),
            "effectiveFromCheckpoint": checkpoint,
            "drainMode": "none",
            "activatedAt": (
                _require_timestamp(activated_at, field="activatedAt")
                if activated_at is not None
                else None
            ),
            "predecessorGeneration": latest.generation,
        }
    )
    return GenerationOpening(
        newGeneration=new_generation,
        chain=tuple([*chain[:-1], superseded, new_generation]),
        supersededGeneration=superseded if superseded_transition else None,
        supersededTransition=superseded_transition,
    )


def request_drain(
    records: Sequence[PolicyGenerationRecord],
    *,
    actor: str,
    reason: str,
    now: str | None = None,
) -> tuple[DrainTransition, PolicyGenerationRecord]:
    """Request a downgrade of the active generation (none -> requested).

    This is the human- or system-policy-initiated entry point of the drain
    machine; a hash-change-driven switch enters the same state through
    :func:`open_generation`.
    """

    chain = validate_generation_chain(records)
    latest = chain[-1]
    if latest.drainMode != "none":
        raise PolicyGenerationServiceError(
            f"latest generation {latest.generation} is in drainMode "
            f"{latest.drainMode!r}; only a none generation can request a drain",
            code="drain_not_requestable",
        )
    transition = _build_transition(
        latest,
        from_mode="none",
        to_mode="requested",
        actor=actor,
        reason=reason,
        now=_now_or(now),
    )
    return transition, _replace(latest, drainMode="requested")


def _build_transition(
    record: PolicyGenerationRecord,
    *,
    from_mode: str,
    to_mode: str,
    actor: str | None,
    reason: str | None,
    now: str,
    pending_outcome_count: int | None = None,
) -> DrainTransition:
    ensure_drain_mode_transition(from_mode, to_mode)
    try:
        return DrainTransition.from_dict(
            {
                "policyId": record.policyId,
                "generation": record.generation,
                "fromMode": from_mode,
                "toMode": to_mode,
                "transitionedAt": now,
                "actor": actor,
                "reason": reason,
                "pendingOutcomeCount": pending_outcome_count,
            }
        )
    except PolicyGenerationValidationError as exc:
        raise PolicyGenerationServiceError(str(exc), code="drain_transition_invalid") from exc


@dataclass(frozen=True, slots=True)
class DrainAdvancement:
    """Result of a drain advancement check for one generation."""

    generation: int
    advanced: bool
    generationRecord: PolicyGenerationRecord
    transition: DrainTransition | None
    pendingOutcomeCount: int


def pending_orphan_outcomes(
    orphan_outcomes: Sequence[OrphanOutcomeRecord],
    *,
    generation: int,
) -> tuple[OrphanOutcomeRecord, ...]:
    """Undecided orphans of one generation: intercepted and still pending."""

    return tuple(
        item
        for item in orphan_outcomes
        if item.sourceGeneration == generation
        and item.disposition == "pending_manual"
    )


def advance_drain(
    records: Sequence[PolicyGenerationRecord],
    generation: int,
    *,
    pending_outcomes: Sequence[Any],
    now: str | None = None,
) -> DrainAdvancement:
    """Advance the drain of one generation from its undecided outcome set.

    ``pending_outcomes`` is the caller-supplied set of undecided in-flight
    outcomes that still reference this generation (outcome ids, receipts or
    :class:`OrphanOutcomeRecord` values; use :func:`pending_orphan_outcomes`
    to derive the undecided subset from orphan bookkeeping).  From
    ``requested``, any undecided outcome moves the generation to ``draining``
    and an empty set moves it straight to ``drained``.  From ``draining``, an
    empty set moves it to ``drained``; a non-empty set keeps it draining (no
    transition, the advancement is reported as not advanced).  ``none`` and
    ``drained`` generations reject advancement.
    """

    chain = validate_generation_chain(records)
    record = _generation_by_number(chain, generation)
    timestamp = _now_or(now)
    pending_count = len(pending_outcomes)

    if record.drainMode == "requested":
        target = "draining" if pending_count > 0 else "drained"
        transition = _build_transition(
            record,
            from_mode="requested",
            to_mode=target,
            actor=None,
            reason=None,
            now=timestamp,
            pending_outcome_count=pending_count,
        )
        return DrainAdvancement(
            generation=record.generation,
            advanced=True,
            generationRecord=_replace(record, drainMode=target),
            transition=transition,
            pendingOutcomeCount=pending_count,
        )

    if record.drainMode == "draining":
        if pending_count == 0:
            transition = _build_transition(
                record,
                from_mode="draining",
                to_mode="drained",
                actor=None,
                reason=None,
                now=timestamp,
                pending_outcome_count=0,
            )
            return DrainAdvancement(
                generation=record.generation,
                advanced=True,
                generationRecord=_replace(record, drainMode="drained"),
                transition=transition,
                pendingOutcomeCount=0,
            )
        return DrainAdvancement(
            generation=record.generation,
            advanced=False,
            generationRecord=record,
            transition=None,
            pendingOutcomeCount=pending_count,
        )

    raise PolicyGenerationServiceError(
        f"generation {record.generation} is in drainMode {record.drainMode!r}; "
        "only requested or draining generations can advance",
        code="drain_not_in_progress",
    )


def register_orphan_outcome(
    records: Sequence[PolicyGenerationRecord],
    *,
    outcome_id: str,
    source_generation: int,
    intercept_reason: str,
    intercepted_at: str | None = None,
) -> OrphanOutcomeRecord:
    """Intercept a cross-generation outcome as an isolated orphan.

    The outcome never auto-commits as an effective result: it is recorded
    under its source generation together with the generation that intercepted
    it, and stays ``pending_manual`` until a disposition moves it one way.
    """

    chain = validate_generation_chain(records)
    latest = chain[-1]
    if str(outcome_id or "").strip() == "":
        raise PolicyGenerationServiceError(
            "outcomeId must be a non-empty string",
            code="missing_or_empty",
        )
    if str(intercept_reason or "").strip() == "":
        raise PolicyGenerationServiceError(
            "interceptReason must be a non-empty string",
            code="missing_or_empty",
        )
    _generation_by_number(chain, source_generation)
    if source_generation >= latest.generation:
        raise PolicyGenerationServiceError(
            f"outcome {str(outcome_id).strip()} was produced under generation "
            f"{source_generation} which is not older than the active "
            f"generation {latest.generation}; only cross-generation outcomes "
            "are intercepted",
            code="not_cross_generation",
        )
    try:
        return OrphanOutcomeRecord.from_dict(
            {
                "outcomeId": str(outcome_id).strip(),
                "policyId": latest.policyId,
                "sourceGeneration": source_generation,
                "activeGeneration": latest.generation,
                "interceptReason": str(intercept_reason).strip(),
                "interceptedAt": _require_timestamp(
                    intercepted_at, field="interceptedAt"
                )
                if intercepted_at is not None
                else datetime.now(UTC).isoformat(),
                "disposition": "pending_manual",
            }
        )
    except PolicyGenerationValidationError as exc:
        raise PolicyGenerationServiceError(
            str(exc), code="orphan_record_invalid"
        ) from exc


def dispose_orphan_outcome(
    record: OrphanOutcomeRecord,
    *,
    disposition: str,
    actor: str,
    reason: str,
    now: str | None = None,
) -> OrphanOutcomeRecord:
    """Move an orphan outcome one way to ``merged`` or ``dismissed``."""

    timestamp = _now_or(now)
    if str(actor or "").strip() not in DRAIN_ACTORS:
        raise PolicyGenerationServiceError(
            "disposition actor must be one of " + ", ".join(sorted(DRAIN_ACTORS)),
            code="unsupported_actor",
        )
    if str(reason or "").strip() == "":
        raise PolicyGenerationServiceError(
            "disposition reason must be a non-empty string",
            code="missing_or_empty",
        )
    try:
        ensure_orphan_disposition_transition(record.disposition, disposition)
    except PolicyGenerationValidationError as exc:
        raise PolicyGenerationServiceError(
            str(exc), code="disposition_transition_invalid"
        ) from exc
    try:
        return OrphanOutcomeRecord.from_dict(
            {
                **record.to_dict(),
                "disposition": disposition,
                "dispositionActor": str(actor).strip(),
                "dispositionReason": str(reason).strip(),
                "dispositionedAt": timestamp,
            }
        )
    except PolicyGenerationValidationError as exc:
        raise PolicyGenerationServiceError(
            str(exc), code="orphan_record_invalid"
        ) from exc


__all__ = [
    "DrainAdvancement",
    "GenerationOpening",
    "PolicyGenerationServiceError",
    "advance_drain",
    "dispose_orphan_outcome",
    "latest_generation",
    "open_generation",
    "pending_orphan_outcomes",
    "register_orphan_outcome",
    "request_drain",
    "validate_generation_chain",
]
