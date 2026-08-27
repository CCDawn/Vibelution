"""Policy generation, drain state machine and orphan outcome contracts (R3.3).

Decision #12 of the challenge-cup record: automation policy switching uses
checkpoint + drain semantics.  A policy content-hash change opens a *new
generation* that takes effect from a checkpoint; the previous generation is
never force-stopped and an immediate residue-free downgrade is explicitly NOT
promised.  Instead the old generation requests a drain, finishes its in-flight
work, and any late outcome that tries to commit across generations is
intercepted as an *orphan* awaiting manual disposition.

The four-state drain machine (``drainMode``) reuses the exact enumeration of
the automation policy contract: ``AUTO_ADVANCE_DRAIN_MODES`` is imported from
``automation_policy`` and never re-declared, so a policy document, its
generation record and every drain transition share one source of truth:

    none -> requested -> draining -> drained

``none`` is the active generation's quiescent state, ``requested`` marks a
human- or policy-initiated downgrade (it must carry the initiator actor and a
reason), ``draining`` means in-flight outcomes still reference this old
generation, and ``drained`` means no undecided outcome remains.  Every
transition outside the frozen map is rejected fail-closed (for example
``none -> draining`` and ``drained -> draining``).

Scope guard: this module is pure state bookkeeping.  It does not fork
checkpoints (see ``checkpoint_lifecycle.fork_checkpoint_at_node``), does not
subscribe to the canonical command chain, does not execute automation, and is
unrelated to the challenge-cup *maintenance fence* drain, which is a
reset/maintenance coordination boundary with different semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ._validation import ContractValidationError
from .automation_policy import (
    AUTO_ADVANCE_DRAIN_MODES,
    POLICY_CONTENT_HASH_RULE,
)

POLICY_GENERATION_SCHEMA_VERSION = "1.0.0-preview.1"

# drainMode is shared with automation_policy (decision #10/#12): one enum, no
# copied string literals.
POLICY_DRAIN_MODES = AUTO_ADVANCE_DRAIN_MODES

# Who may initiate a downgrade (the none -> requested transition).
DRAIN_ACTORS: frozenset[str] = frozenset({"human_operator", "system_policy"})

# Frozen drain transition map.  Keys mirror POLICY_DRAIN_MODES; a transition
# absent from the target set is rejected fail-closed.
DRAIN_MODE_TRANSITIONS: dict[str, frozenset[str]] = {
    "none": frozenset({"requested"}),
    "requested": frozenset({"draining", "drained"}),
    "draining": frozenset({"drained"}),
    "drained": frozenset(),
}

# Orphan disposition lifecycle: strictly one-way, terminal on both outcomes.
ORPHAN_DISPOSITIONS: frozenset[str] = frozenset(
    {"pending_manual", "merged", "dismissed"}
)
ORPHAN_DISPOSITION_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_manual": frozenset({"merged", "dismissed"}),
    "merged": frozenset(),
    "dismissed": frozenset(),
}


class PolicyGenerationValidationError(ContractValidationError):
    """A generation/drain/orphan record failed fail-closed validation.

    ``errors`` carries structured entries (``code`` / ``field`` / ``message``)
    so callers can surface precise rejection reasons.
    """

    def __init__(self, errors: Sequence[Mapping[str, str]]) -> None:
        self.errors: list[dict[str, str]] = [dict(item) for item in errors]
        summary = "; ".join(
            f"{item.get('code', 'invalid')}[{item.get('field', '')}]: "
            f"{item.get('message', '')}"
            for item in self.errors
        )
        super().__init__(f"policy generation rejected: {summary}")


def _error(code: str, field_name: str, message: str) -> dict[str, str]:
    return {"code": code, "field": field_name, "message": message}


def _require_text(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        errors.append(_error("missing_or_empty", key, "must be a non-empty string"))
    return value


def _require_int(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        errors.append(_error("missing_or_invalid", key, "must be an integer >= 1"))
        return 0
    return value


def _require_upper_sha256(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> str:
    value = str(payload.get(key) or "").strip()
    if len(value) != 64 or any(char not in "0123456789ABCDEF" for char in value):
        errors.append(
            _error(
                "invalid_content_hash",
                key,
                "must be an uppercase sha256 hex digest",
            )
        )
        return ""
    return value


def _require_iso_timestamp(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        errors.append(_error("missing_or_empty", key, "must be a non-empty ISO-8601 timestamp"))
        return ""
    try:
        datetime.fromisoformat(value)
    except ValueError:
        errors.append(
            _error("invalid_timestamp", key, "must be a parseable ISO-8601 timestamp")
        )
    return value


def _optional_text(
    errors: list[dict[str, str]], payload: Mapping[str, Any], key: str
) -> str | None:
    raw = payload.get(key)
    if raw is None:
        return None
    value = str(raw).strip()
    if not value:
        errors.append(_error("invalid_optional", key, "must be null or a non-empty string"))
        return None
    return value


def ensure_drain_mode_transition(current: str, target: str) -> None:
    """Fail closed on any drainMode transition outside the frozen map."""

    normalized_current = str(current or "").strip()
    normalized_target = str(target or "").strip()
    if normalized_current not in POLICY_DRAIN_MODES:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "unsupported_value",
                    "fromMode",
                    "drainMode must be one of "
                    + ", ".join(sorted(POLICY_DRAIN_MODES))
                    + f"; got {normalized_current!r}",
                )
            ]
        )
    if normalized_target not in POLICY_DRAIN_MODES:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "unsupported_value",
                    "toMode",
                    "drainMode must be one of "
                    + ", ".join(sorted(POLICY_DRAIN_MODES))
                    + f"; got {normalized_target!r}",
                )
            ]
        )
    allowed = DRAIN_MODE_TRANSITIONS[normalized_current]
    if normalized_target not in allowed:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "illegal_drain_transition",
                    "drainMode",
                    f"drainMode transition {normalized_current} -> "
                    f"{normalized_target} is not allowed; legal targets: "
                    + (", ".join(sorted(allowed)) if allowed else "(none, terminal)"),
                )
            ]
        )


def ensure_orphan_disposition_transition(current: str, target: str) -> None:
    """Fail closed on any orphan disposition transition outside the frozen map."""

    normalized_current = str(current or "").strip()
    normalized_target = str(target or "").strip()
    if normalized_current not in ORPHAN_DISPOSITIONS:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "unsupported_value",
                    "disposition",
                    "disposition must be one of "
                    + ", ".join(sorted(ORPHAN_DISPOSITIONS))
                    + f"; got {normalized_current!r}",
                )
            ]
        )
    if normalized_target not in ORPHAN_DISPOSITIONS:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "unsupported_value",
                    "disposition",
                    "disposition must be one of "
                    + ", ".join(sorted(ORPHAN_DISPOSITIONS))
                    + f"; got {normalized_target!r}",
                )
            ]
        )
    allowed = ORPHAN_DISPOSITION_TRANSITIONS[normalized_current]
    if normalized_target not in allowed:
        raise PolicyGenerationValidationError(
            [
                _error(
                    "illegal_disposition_transition",
                    "disposition",
                    f"disposition transition {normalized_current} -> "
                    f"{normalized_target} is not allowed; orphan outcomes move "
                    "one way only (pending_manual -> merged | dismissed)",
                )
            ]
        )


@dataclass(frozen=True, slots=True)
class PolicyGenerationRecord:
    """One generation of an automation policy (decision #12).

    A generation is pinned by its policy content hash.  The first generation
    may take effect immediately; every later generation must declare the
    checkpoint it becomes effective from (checkpoint + drain, never an
    immediate in-place switch).  ``drainMode`` tracks the generation's own
    drain lifecycle and uses the shared ``AUTO_ADVANCE_DRAIN_MODES`` enum.
    ``activatedAt`` stays null in the preview stage until activation exists.
    """

    policyId: str
    generation: int
    policyContentHash: str
    effectiveFromCheckpoint: str | None
    drainMode: str
    activatedAt: str | None
    predecessorGeneration: int | None
    schemaVersion: str = POLICY_GENERATION_SCHEMA_VERSION
    contentHashRule: str = POLICY_CONTENT_HASH_RULE

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> PolicyGenerationRecord:
        errors: list[dict[str, str]] = []
        policy_id = _require_text(errors, payload, "policyId")
        generation = _require_int(errors, payload, "generation")
        content_hash = _require_upper_sha256(errors, payload, "policyContentHash")

        checkpoint = payload.get("effectiveFromCheckpoint")
        if checkpoint is not None and not (
            isinstance(checkpoint, str) and checkpoint.strip()
        ):
            errors.append(
                _error(
                    "invalid_checkpoint",
                    "effectiveFromCheckpoint",
                    "must be a non-empty string or null",
                )
            )
            checkpoint = None

        drain_mode = str(payload.get("drainMode") or "").strip()
        if drain_mode not in POLICY_DRAIN_MODES:
            errors.append(
                _error(
                    "unsupported_value",
                    "drainMode",
                    "must be one of " + ", ".join(sorted(POLICY_DRAIN_MODES)),
                )
            )

        activated_at = payload.get("activatedAt")
        if activated_at is not None and not (
            isinstance(activated_at, str) and activated_at.strip()
        ):
            errors.append(
                _error(
                    "invalid_timestamp",
                    "activatedAt",
                    "must be a parseable ISO-8601 timestamp or null",
                )
            )
            activated_at = None
        elif isinstance(activated_at, str) and activated_at.strip():
            try:
                datetime.fromisoformat(activated_at.strip())
            except ValueError:
                errors.append(
                    _error(
                        "invalid_timestamp",
                        "activatedAt",
                        "must be a parseable ISO-8601 timestamp or null",
                    )
                )

        predecessor = payload.get("predecessorGeneration")
        if isinstance(predecessor, bool) or not isinstance(predecessor, int):
            predecessor = None
        if generation >= 1:
            if generation == 1 and predecessor is not None:
                errors.append(
                    _error(
                        "predecessor_forbidden",
                        "predecessorGeneration",
                        "the first generation has no predecessor",
                    )
                )
            if generation > 1 and (predecessor is None or predecessor < 1 or predecessor >= generation):
                errors.append(
                    _error(
                        "predecessor_required",
                        "predecessorGeneration",
                        "a later generation must reference its immediate "
                        "predecessor (an integer >= 1 and < generation)",
                    )
                )
            if generation > 1 and not (
                isinstance(checkpoint, str) and checkpoint.strip()
            ):
                errors.append(
                    _error(
                        "checkpoint_required",
                        "effectiveFromCheckpoint",
                        "a later generation becomes effective from a declared "
                        "checkpoint (decision #12: checkpoint + drain)",
                    )
                )

        if errors:
            raise PolicyGenerationValidationError(errors)

        return cls(
            policyId=policy_id,
            generation=generation,
            policyContentHash=content_hash,
            effectiveFromCheckpoint=str(checkpoint).strip() if checkpoint else None,
            drainMode=drain_mode,
            activatedAt=str(activated_at).strip() if activated_at else None,
            predecessorGeneration=predecessor,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policyId,
            "generation": self.generation,
            "policyContentHash": self.policyContentHash,
            "effectiveFromCheckpoint": self.effectiveFromCheckpoint,
            "drainMode": self.drainMode,
            "activatedAt": self.activatedAt,
            "predecessorGeneration": self.predecessorGeneration,
            "schemaVersion": self.schemaVersion,
            "contentHashRule": self.contentHashRule,
        }


@dataclass(frozen=True, slots=True)
class DrainTransition:
    """One fail-closed step of the generation drain state machine.

    ``actor`` and ``reason`` are mandatory for the downgrade request
    (``toMode == "requested"``) and must name a ``DRAIN_ACTORS`` initiator.
    ``pendingOutcomeCount`` is the drain evidence: it is forbidden on a
    request, must be >= 1 when entering ``draining`` (draining means
    undecided in-flight outcomes exist) and must be exactly 0 when entering
    ``drained``.
    """

    policyId: str
    generation: int
    fromMode: str
    toMode: str
    transitionedAt: str
    actor: str | None = None
    reason: str | None = None
    pendingOutcomeCount: int | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DrainTransition:
        errors: list[dict[str, str]] = []
        policy_id = _require_text(errors, payload, "policyId")
        generation = _require_int(errors, payload, "generation")
        from_mode = str(payload.get("fromMode") or "").strip()
        to_mode = str(payload.get("toMode") or "").strip()
        transitioned_at = _require_iso_timestamp(errors, payload, "transitionedAt")

        for key, value in (("fromMode", from_mode), ("toMode", to_mode)):
            if value not in POLICY_DRAIN_MODES:
                errors.append(
                    _error(
                        "unsupported_value",
                        key,
                        "drainMode must be one of "
                        + ", ".join(sorted(POLICY_DRAIN_MODES))
                        + f"; got {value!r}",
                    )
                )
        if not errors:
            try:
                ensure_drain_mode_transition(from_mode, to_mode)
            except PolicyGenerationValidationError as exc:
                errors.extend(exc.errors)

        actor = _optional_text(errors, payload, "actor")
        reason = _optional_text(errors, payload, "reason")
        if to_mode == "requested":
            if actor is None:
                errors.append(
                    _error(
                        "missing_actor",
                        "actor",
                        "a downgrade request must name its initiator: "
                        + ", ".join(sorted(DRAIN_ACTORS)),
                    )
                )
            elif actor not in DRAIN_ACTORS:
                errors.append(
                    _error(
                        "unsupported_actor",
                        "actor",
                        "must be one of " + ", ".join(sorted(DRAIN_ACTORS)),
                    )
                )
            if reason is None:
                errors.append(
                    _error(
                        "missing_reason",
                        "reason",
                        "a downgrade request must carry a reason",
                    )
                )
        elif actor is not None and actor not in DRAIN_ACTORS:
            errors.append(
                _error(
                    "unsupported_actor",
                    "actor",
                    "must be one of " + ", ".join(sorted(DRAIN_ACTORS)),
                )
            )

        raw_count = payload.get("pendingOutcomeCount")
        if raw_count is None:
            pending_count = None
        elif isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count < 0:
            errors.append(
                _error(
                    "missing_or_invalid",
                    "pendingOutcomeCount",
                    "must be an integer >= 0 or null",
                )
            )
            pending_count = None
        else:
            pending_count = raw_count
        if to_mode == "requested" and pending_count is not None:
            errors.append(
                _error(
                    "unexpected_pending_count",
                    "pendingOutcomeCount",
                    "a downgrade request carries no drain evidence yet",
                )
            )
        if to_mode == "draining":
            if pending_count is None:
                errors.append(
                    _error(
                        "missing_pending_count",
                        "pendingOutcomeCount",
                        "entering draining requires the count of undecided "
                        "in-flight outcomes",
                    )
                )
            elif pending_count < 1:
                errors.append(
                    _error(
                        "invalid_pending_count",
                        "pendingOutcomeCount",
                        "draining means undecided in-flight outcomes exist; "
                        "the count must be >= 1 (use drained for 0)",
                    )
                )
        if to_mode == "drained":
            if pending_count is None:
                errors.append(
                    _error(
                        "missing_pending_count",
                        "pendingOutcomeCount",
                        "entering drained requires the count of undecided "
                        "in-flight outcomes",
                    )
                )
            elif pending_count != 0:
                errors.append(
                    _error(
                        "invalid_pending_count",
                        "pendingOutcomeCount",
                        "drained means no undecided in-flight outcome remains; "
                        f"got {pending_count}",
                    )
                )

        if errors:
            raise PolicyGenerationValidationError(errors)

        return cls(
            policyId=policy_id,
            generation=generation,
            fromMode=from_mode,
            toMode=to_mode,
            transitionedAt=transitioned_at,
            actor=actor,
            reason=reason,
            pendingOutcomeCount=pending_count,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "policyId": self.policyId,
            "generation": self.generation,
            "fromMode": self.fromMode,
            "toMode": self.toMode,
            "transitionedAt": self.transitionedAt,
            "actor": self.actor,
            "reason": self.reason,
            "pendingOutcomeCount": self.pendingOutcomeCount,
        }


@dataclass(frozen=True, slots=True)
class OrphanOutcomeRecord:
    """An intercepted cross-generation outcome, quarantined for disposition.

    An outcome produced under ``sourceGeneration`` while ``activeGeneration``
    is newer never auto-commits as an effective result (decision #12: no
    immediate residue-free downgrade).  It is isolated as an orphan with the
    interception time and moves one way through the disposition lifecycle
    ``pending_manual -> merged | dismissed``; both terminal states reject any
    further transition.
    """

    outcomeId: str
    policyId: str
    sourceGeneration: int
    activeGeneration: int
    interceptReason: str
    interceptedAt: str
    disposition: str
    dispositionActor: str | None = None
    dispositionReason: str | None = None
    dispositionedAt: str | None = None
    schemaVersion: str = POLICY_GENERATION_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> OrphanOutcomeRecord:
        errors: list[dict[str, str]] = []
        outcome_id = _require_text(errors, payload, "outcomeId")
        policy_id = _require_text(errors, payload, "policyId")
        source_generation = _require_int(errors, payload, "sourceGeneration")
        active_generation = _require_int(errors, payload, "activeGeneration")
        if (
            not errors
            and source_generation >= 1
            and active_generation >= 1
            and active_generation <= source_generation
        ):
            errors.append(
                _error(
                    "not_cross_generation",
                    "activeGeneration",
                    "an orphan outcome is only defined when the intercepting "
                    "generation is newer than the source generation",
                )
            )
        intercept_reason = _require_text(errors, payload, "interceptReason")
        intercepted_at = _require_iso_timestamp(errors, payload, "interceptedAt")

        disposition = str(payload.get("disposition") or "").strip()
        if disposition not in ORPHAN_DISPOSITIONS:
            errors.append(
                _error(
                    "unsupported_value",
                    "disposition",
                    "must be one of " + ", ".join(sorted(ORPHAN_DISPOSITIONS)),
                )
            )

        disposition_actor = _optional_text(errors, payload, "dispositionActor")
        if disposition_actor is not None and disposition_actor not in DRAIN_ACTORS:
            errors.append(
                _error(
                    "unsupported_actor",
                    "dispositionActor",
                    "must be one of " + ", ".join(sorted(DRAIN_ACTORS)),
                )
            )
        disposition_reason = _optional_text(errors, payload, "dispositionReason")
        raw_dispositioned_at = payload.get("dispositionedAt")
        dispositioned_at: str | None = None
        if raw_dispositioned_at is not None:
            dispositioned_at = _require_iso_timestamp(errors, payload, "dispositionedAt")

        decided = disposition in {"merged", "dismissed"}
        if decided:
            if disposition_actor is None:
                errors.append(
                    _error(
                        "missing_actor",
                        "dispositionActor",
                        "a decided orphan must name the disposing actor: "
                        + ", ".join(sorted(DRAIN_ACTORS)),
                    )
                )
            if disposition_reason is None:
                errors.append(
                    _error(
                        "missing_reason",
                        "dispositionReason",
                        "a decided orphan must carry the disposition reason",
                    )
                )
            if dispositioned_at is None:
                errors.append(
                    _error(
                        "missing_or_empty",
                        "dispositionedAt",
                        "a decided orphan must carry the disposition time",
                    )
                )
        else:
            for key, value in (
                ("dispositionActor", disposition_actor),
                ("dispositionReason", disposition_reason),
                ("dispositionedAt", dispositioned_at),
            ):
                if value is not None:
                    errors.append(
                        _error(
                            "unexpected_disposition_evidence",
                            key,
                            "a pending_manual orphan carries no disposition "
                            "evidence yet",
                        )
                    )

        if errors:
            raise PolicyGenerationValidationError(errors)

        return cls(
            outcomeId=outcome_id,
            policyId=policy_id,
            sourceGeneration=source_generation,
            activeGeneration=active_generation,
            interceptReason=intercept_reason,
            interceptedAt=intercepted_at,
            disposition=disposition,
            dispositionActor=disposition_actor,
            dispositionReason=disposition_reason,
            dispositionedAt=dispositioned_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcomeId": self.outcomeId,
            "policyId": self.policyId,
            "sourceGeneration": self.sourceGeneration,
            "activeGeneration": self.activeGeneration,
            "interceptReason": self.interceptReason,
            "interceptedAt": self.interceptedAt,
            "disposition": self.disposition,
            "dispositionActor": self.dispositionActor,
            "dispositionReason": self.dispositionReason,
            "dispositionedAt": self.dispositionedAt,
            "schemaVersion": self.schemaVersion,
        }


__all__ = [
    "AUTO_ADVANCE_DRAIN_MODES",
    "DRAIN_ACTORS",
    "DRAIN_MODE_TRANSITIONS",
    "ORPHAN_DISPOSITIONS",
    "ORPHAN_DISPOSITION_TRANSITIONS",
    "POLICY_CONTENT_HASH_RULE",
    "POLICY_DRAIN_MODES",
    "POLICY_GENERATION_SCHEMA_VERSION",
    "DrainTransition",
    "OrphanOutcomeRecord",
    "PolicyGenerationRecord",
    "PolicyGenerationValidationError",
    "ensure_drain_mode_transition",
    "ensure_orphan_disposition_transition",
]
