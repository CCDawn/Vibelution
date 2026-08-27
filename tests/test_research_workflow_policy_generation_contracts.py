"""Fail-closed tests for the R3.3 policy generation/drain/orphan contracts.

Covers the frozen drain transition table (decision #12: checkpoint + drain,
never an immediate residue-free downgrade), the hash-unchanged rejection for
new generations, the drain advancement judgement over undecided outcome sets,
the one-way orphan disposition lifecycle, and the shared drainMode enum
source with the automation policy contracts.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.research.workflow.contracts.automation_policy import (
    AUTO_ADVANCE_DRAIN_MODES,
)
from core.research.workflow.contracts.policy_generation import (
    DRAIN_ACTORS,
    DRAIN_MODE_TRANSITIONS,
    ORPHAN_DISPOSITIONS,
    POLICY_DRAIN_MODES,
    DrainTransition,
    OrphanOutcomeRecord,
    PolicyGenerationRecord,
    PolicyGenerationValidationError,
    ensure_drain_mode_transition,
    ensure_orphan_disposition_transition,
)
from core.web.services.team_workflow.research_runtime import (
    automation_policy_service,
)
from core.web.services.team_workflow.research_runtime import (
    policy_generation_service as svc,
)

NOW = "2026-08-28T09:00:00+08:00"
LATER = "2026-08-28T10:00:00+08:00"
HASH_V1 = "A" * 64
HASH_V2 = "B" * 64
HASH_V3 = "C" * 64

# The frozen drain machine: exactly the four forward steps, everything else
# (12 of 16 from/to pairs, including every self-transition) is rejected.
LEGAL_DRAIN_TRANSITIONS = {
    ("none", "requested"),
    ("requested", "draining"),
    ("requested", "drained"),
    ("draining", "drained"),
}


def _first_generation() -> PolicyGenerationRecord:
    return PolicyGenerationRecord.from_dict(
        {
            "policyId": "cc-auto-advance-policy-002",
            "generation": 1,
            "policyContentHash": HASH_V1,
            "effectiveFromCheckpoint": None,
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": None,
        }
    )


def _drain_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "policyId": "cc-auto-advance-policy-002",
        "generation": 1,
        "fromMode": "none",
        "toMode": "requested",
        "transitionedAt": NOW,
        "actor": "human_operator",
        "reason": "operator initiated downgrade",
        "pendingOutcomeCount": None,
    }
    payload.update(overrides)
    return payload


def _orphan_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "outcomeId": "outcome-1",
        "policyId": "cc-auto-advance-policy-002",
        "sourceGeneration": 1,
        "activeGeneration": 2,
        "interceptReason": "cross_generation_commit_blocked",
        "interceptedAt": NOW,
        "disposition": "pending_manual",
    }
    payload.update(overrides)
    return payload


def _error_codes(exc: PolicyGenerationValidationError) -> set[str]:
    return {item["code"] for item in exc.errors}


# ---------------------------------------------------------------------------
# drain state machine: full transition table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_mode", sorted(AUTO_ADVANCE_DRAIN_MODES))
@pytest.mark.parametrize("to_mode", sorted(AUTO_ADVANCE_DRAIN_MODES))
def test_drain_transition_table_accepts_only_legal_steps(
    from_mode: str, to_mode: str
) -> None:
    should_pass = (from_mode, to_mode) in LEGAL_DRAIN_TRANSITIONS
    if should_pass:
        ensure_drain_mode_transition(from_mode, to_mode)
    else:
        with pytest.raises(PolicyGenerationValidationError) as exc:
            ensure_drain_mode_transition(from_mode, to_mode)
        assert _error_codes(exc.value) == {"illegal_drain_transition"}


def test_drain_transition_map_covers_every_state_and_matches_legal_set() -> None:
    assert set(DRAIN_MODE_TRANSITIONS) == set(AUTO_ADVANCE_DRAIN_MODES)
    reachable = {
        (source, target)
        for source, targets in DRAIN_MODE_TRANSITIONS.items()
        for target in targets
    }
    assert reachable == LEGAL_DRAIN_TRANSITIONS


def test_requested_transition_requires_actor_and_reason() -> None:
    for actor in sorted(DRAIN_ACTORS):
        transition = DrainTransition.from_dict(_drain_payload(actor=actor))
        assert transition.actor == actor

    with pytest.raises(PolicyGenerationValidationError) as missing:
        DrainTransition.from_dict(_drain_payload(actor=None))
    assert {"missing_actor"} <= _error_codes(missing.value)

    with pytest.raises(PolicyGenerationValidationError) as unsupported:
        DrainTransition.from_dict(_drain_payload(actor="autonomous_agent"))
    assert {"unsupported_actor"} <= _error_codes(unsupported.value)

    with pytest.raises(PolicyGenerationValidationError) as no_reason:
        DrainTransition.from_dict(_drain_payload(reason=None))
    assert {"missing_reason"} <= _error_codes(no_reason.value)


def test_pending_outcome_count_rules_match_state_semantics() -> None:
    # draining means undecided in-flight outcomes exist: count >= 1 required.
    with pytest.raises(PolicyGenerationValidationError) as zero:
        DrainTransition.from_dict(
            _drain_payload(
                fromMode="requested",
                toMode="draining",
                actor=None,
                reason=None,
                pendingOutcomeCount=0,
            )
        )
    assert {"invalid_pending_count"} <= _error_codes(zero.value)

    with pytest.raises(PolicyGenerationValidationError) as absent:
        DrainTransition.from_dict(
            _drain_payload(
                fromMode="requested",
                toMode="draining",
                actor=None,
                reason=None,
            )
        )
    assert {"missing_pending_count"} <= _error_codes(absent.value)

    # drained means no undecided outcome remains: count must be exactly 0.
    with pytest.raises(PolicyGenerationValidationError) as residue:
        DrainTransition.from_dict(
            _drain_payload(
                fromMode="draining",
                toMode="drained",
                actor=None,
                reason=None,
                pendingOutcomeCount=2,
            )
        )
    assert {"invalid_pending_count"} <= _error_codes(residue.value)

    with pytest.raises(PolicyGenerationValidationError) as no_evidence:
        DrainTransition.from_dict(
            _drain_payload(
                fromMode="draining",
                toMode="drained",
                actor=None,
                reason=None,
            )
        )
    assert {"missing_pending_count"} <= _error_codes(no_evidence.value)

    # A downgrade request carries no drain evidence yet.
    with pytest.raises(PolicyGenerationValidationError) as premature:
        DrainTransition.from_dict(_drain_payload(pendingOutcomeCount=3))
    assert {"unexpected_pending_count"} <= _error_codes(premature.value)

    assert (
        DrainTransition.from_dict(
            _drain_payload(
                fromMode="draining",
                toMode="drained",
                actor=None,
                reason=None,
                pendingOutcomeCount=0,
            )
        ).pendingOutcomeCount
        == 0
    )


def test_drain_transition_rejects_unknown_modes_and_bad_timestamp() -> None:
    with pytest.raises(PolicyGenerationValidationError) as bad_mode:
        DrainTransition.from_dict(_drain_payload(fromMode="paused", toMode="drained"))
    assert {"unsupported_value"} <= _error_codes(bad_mode.value)

    with pytest.raises(PolicyGenerationValidationError) as bad_time:
        DrainTransition.from_dict(_drain_payload(transitionedAt="not-a-time"))
    assert {"invalid_timestamp"} <= _error_codes(bad_time.value)


# ---------------------------------------------------------------------------
# generation records and chain invariants
# ---------------------------------------------------------------------------


def test_policy_generation_record_roundtrip_and_preview_nulls() -> None:
    record = _first_generation()
    assert record.activatedAt is None
    assert record.effectiveFromCheckpoint is None
    parsed = PolicyGenerationRecord.from_dict(record.to_dict())
    assert parsed == record

    with pytest.raises(FrozenInstanceError):
        record.drainMode = "requested"  # type: ignore[misc]


def test_policy_generation_record_fail_closed_rules() -> None:
    with pytest.raises(PolicyGenerationValidationError) as bad_hash:
        PolicyGenerationRecord.from_dict(
            {**_first_generation().to_dict(), "policyContentHash": "deadbeef"}
        )
    assert {"invalid_content_hash"} <= _error_codes(bad_hash.value)

    with pytest.raises(PolicyGenerationValidationError) as bad_mode:
        PolicyGenerationRecord.from_dict(
            {**_first_generation().to_dict(), "drainMode": "pausing"}
        )
    assert {"unsupported_value"} <= _error_codes(bad_mode.value)

    with pytest.raises(PolicyGenerationValidationError) as bad_time:
        PolicyGenerationRecord.from_dict(
            {**_first_generation().to_dict(), "activatedAt": "yesterday"}
        )
    assert {"invalid_timestamp"} <= _error_codes(bad_time.value)

    with pytest.raises(PolicyGenerationValidationError) as stray_pred:
        PolicyGenerationRecord.from_dict(
            {**_first_generation().to_dict(), "predecessorGeneration": 1}
        )
    assert {"predecessor_forbidden"} <= _error_codes(stray_pred.value)

    later = {**_first_generation().to_dict(), "generation": 2}
    with pytest.raises(PolicyGenerationValidationError) as needs_pred:
        PolicyGenerationRecord.from_dict(later)
    assert {"predecessor_required"} <= _error_codes(needs_pred.value)

    with pytest.raises(PolicyGenerationValidationError) as needs_ckpt:
        PolicyGenerationRecord.from_dict({**later, "predecessorGeneration": 1})
    assert {"checkpoint_required"} <= _error_codes(needs_ckpt.value)

    activated = PolicyGenerationRecord.from_dict(
        {
            **later,
            "predecessorGeneration": 1,
            "effectiveFromCheckpoint": "ckpt-1",
        }
    )
    assert activated.effectiveFromCheckpoint == "ckpt-1"


def test_generation_chain_rejects_gaps_mixed_ids_and_bad_predecessors() -> None:
    gen1 = _first_generation()
    assert svc.validate_generation_chain([gen1]) == [gen1]

    with pytest.raises(svc.PolicyGenerationServiceError) as empty:
        svc.validate_generation_chain([])
    assert empty.value.code == "generation_chain_empty"

    mixed = PolicyGenerationRecord.from_dict({**gen1.to_dict(), "policyId": "other"})
    with pytest.raises(svc.PolicyGenerationServiceError) as ids:
        svc.validate_generation_chain([gen1, mixed])
    assert ids.value.code == "policy_id_mismatch"

    gap = PolicyGenerationRecord.from_dict(
        {
            "policyId": gen1.policyId,
            "generation": 3,
            "policyContentHash": HASH_V2,
            "effectiveFromCheckpoint": "ckpt-2",
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": 1,
        }
    )
    with pytest.raises(svc.PolicyGenerationServiceError) as discontinuous:
        svc.validate_generation_chain([gen1, gap])
    assert discontinuous.value.code == "generation_chain_discontinuous"

    gen2 = PolicyGenerationRecord.from_dict(
        {
            "policyId": gen1.policyId,
            "generation": 2,
            "policyContentHash": HASH_V2,
            "effectiveFromCheckpoint": "ckpt-1",
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": 1,
        }
    )
    # Record-level valid (predecessor < generation) but not the *immediate*
    # predecessor: only the chain invariant catches this.
    wrong_pred = PolicyGenerationRecord.from_dict(
        {
            "policyId": gen1.policyId,
            "generation": 3,
            "policyContentHash": HASH_V3,
            "effectiveFromCheckpoint": "ckpt-2",
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": 1,
        }
    )
    with pytest.raises(svc.PolicyGenerationServiceError) as predecessors:
        svc.validate_generation_chain([gen1, gen2, wrong_pred])
    assert predecessors.value.code == "predecessor_mismatch"


# ---------------------------------------------------------------------------
# opening generations (hash-change driven)
# ---------------------------------------------------------------------------


def test_hash_unchanged_rejects_new_generation() -> None:
    with pytest.raises(svc.PolicyGenerationServiceError) as exc:
        svc.open_generation(
            [_first_generation()],
            policy_content_hash=HASH_V1,
            effective_from_checkpoint="ckpt-1",
            actor="human_operator",
            reason="identical document re-submitted",
            now=NOW,
        )
    assert exc.value.code == "hash_unchanged"


def test_open_generation_requests_drain_and_pins_new_generation_to_checkpoint() -> None:
    gen1 = _first_generation()
    opening = svc.open_generation(
        [gen1],
        policy_content_hash=HASH_V2,
        effective_from_checkpoint="ckpt-1",
        actor="system_policy",
        reason="approved policy document changed",
        now=NOW,
    )
    assert opening.supersededTransition is not None
    assert (opening.supersededTransition.fromMode, opening.supersededTransition.toMode) == (
        "none",
        "requested",
    )
    assert opening.supersededTransition.actor == "system_policy"
    assert opening.supersededGeneration is not None
    assert opening.supersededGeneration.drainMode == "requested"

    new_generation = opening.newGeneration
    assert new_generation.generation == 2
    assert new_generation.policyContentHash == HASH_V2
    assert new_generation.effectiveFromCheckpoint == "ckpt-1"
    assert new_generation.drainMode == "none"
    assert new_generation.predecessorGeneration == 1
    assert new_generation.activatedAt is None  # preview stage
    assert svc.latest_generation(opening.chain) == new_generation
    assert [record.generation for record in opening.chain] == [1, 2]

    with pytest.raises(svc.PolicyGenerationServiceError) as needs_ckpt:
        svc.open_generation(
            [gen1],
            policy_content_hash=HASH_V2,
            effective_from_checkpoint=None,
            actor="human_operator",
            reason="no checkpoint declared",
            now=NOW,
        )
    assert needs_ckpt.value.code == "checkpoint_required"


def test_open_generation_rejects_in_flight_drain_and_requires_drained_history() -> None:
    opening = svc.open_generation(
        [_first_generation()],
        policy_content_hash=HASH_V2,
        effective_from_checkpoint="ckpt-1",
        actor="human_operator",
        reason="switch",
        now=NOW,
    )
    chain = list(opening.chain)

    with pytest.raises(svc.PolicyGenerationServiceError) as in_flight:
        svc.open_generation(
            chain,
            policy_content_hash=HASH_V3,
            effective_from_checkpoint="ckpt-2",
            actor="human_operator",
            reason="stacked switch",
            now=LATER,
        )
    assert in_flight.value.code == "drain_in_progress"

    # Drain generation 1 fully, then generation 3 opens cleanly.
    advancement = svc.advance_drain(
        chain, 1, pending_outcomes=["outcome-1", "outcome-2"], now=LATER
    )
    assert advancement.advanced and advancement.generationRecord.drainMode == "draining"
    drained_chain = [
        advancement.generationRecord if record.generation == 1 else record
        for record in chain
    ]
    final = svc.advance_drain(drained_chain, 1, pending_outcomes=[], now=LATER)
    assert final.generationRecord.drainMode == "drained"
    quiescent_chain = [
        final.generationRecord if record.generation == 1 else record
        for record in drained_chain
    ]
    second = svc.open_generation(
        quiescent_chain,
        policy_content_hash=HASH_V3,
        effective_from_checkpoint="ckpt-2",
        actor="human_operator",
        reason="second switch",
        now=LATER,
    )
    assert [record.generation for record in second.chain] == [1, 2, 3]
    assert second.chain[0].drainMode == "drained"
    assert second.supersededGeneration is not None
    assert second.supersededGeneration.generation == 2
    assert second.supersededTransition is not None


# ---------------------------------------------------------------------------
# explicit downgrade requests (none -> requested)
# ---------------------------------------------------------------------------


def test_request_drain_targets_latest_generation_fail_closed() -> None:
    gen1 = _first_generation()
    transition, requested = svc.request_drain(
        [gen1], actor="human_operator", reason="manual downgrade", now=NOW
    )
    assert (transition.fromMode, transition.toMode) == ("none", "requested")
    assert requested.drainMode == "requested"

    with pytest.raises(svc.PolicyGenerationServiceError) as repeat:
        svc.request_drain(
            [requested], actor="human_operator", reason="again", now=LATER
        )
    assert repeat.value.code == "drain_not_requestable"


# ---------------------------------------------------------------------------
# drain advancement judgement
# ---------------------------------------------------------------------------


def test_advance_drain_from_requested_judges_draining_or_drained() -> None:
    gen1 = _first_generation()
    _, requested = svc.request_drain(
        [gen1], actor="system_policy", reason="downgrade", now=NOW
    )

    draining = svc.advance_drain(
        [requested], 1, pending_outcomes=["outcome-1", "outcome-2"], now=NOW
    )
    assert draining.advanced is True
    assert draining.generationRecord.drainMode == "draining"
    assert draining.pendingOutcomeCount == 2
    assert draining.transition is not None
    assert (draining.transition.fromMode, draining.transition.toMode) == (
        "requested",
        "draining",
    )

    _, requested_again = svc.request_drain(
        [_first_generation()], actor="system_policy", reason="downgrade", now=NOW
    )
    drained = svc.advance_drain(
        [requested_again], 1, pending_outcomes=[], now=NOW
    )
    assert drained.advanced is True
    assert drained.generationRecord.drainMode == "drained"
    assert drained.transition is not None
    assert drained.transition.pendingOutcomeCount == 0


def test_advance_drain_stays_draining_until_set_is_empty() -> None:
    gen1 = _first_generation()
    _, requested = svc.request_drain(
        [gen1], actor="system_policy", reason="downgrade", now=NOW
    )
    draining = svc.advance_drain(
        [requested], 1, pending_outcomes=["outcome-1"], now=NOW
    )
    chain = [draining.generationRecord]

    still = svc.advance_drain(
        chain, 1, pending_outcomes=["outcome-1"], now=LATER
    )
    assert still.advanced is False
    assert still.transition is None
    assert still.generationRecord.drainMode == "draining"

    done = svc.advance_drain(chain, 1, pending_outcomes=[], now=LATER)
    assert done.advanced is True
    assert done.generationRecord.drainMode == "drained"


def test_advance_drain_rejects_none_drained_and_unknown_generations() -> None:
    gen1 = _first_generation()
    with pytest.raises(svc.PolicyGenerationServiceError) as quiescent:
        svc.advance_drain([gen1], 1, pending_outcomes=[], now=NOW)
    assert quiescent.value.code == "drain_not_in_progress"

    drained = PolicyGenerationRecord.from_dict(
        {**gen1.to_dict(), "drainMode": "drained"}
    )
    with pytest.raises(svc.PolicyGenerationServiceError) as terminal:
        svc.advance_drain([drained], 1, pending_outcomes=[], now=NOW)
    assert terminal.value.code == "drain_not_in_progress"

    with pytest.raises(svc.PolicyGenerationServiceError) as unknown:
        svc.advance_drain([gen1], 7, pending_outcomes=[], now=NOW)
    assert unknown.value.code == "unknown_generation"


# ---------------------------------------------------------------------------
# orphan outcome interception and one-way disposition
# ---------------------------------------------------------------------------


def test_orphan_registration_intercepts_cross_generation_outcomes() -> None:
    gen1 = _first_generation()
    opening = svc.open_generation(
        [gen1],
        policy_content_hash=HASH_V2,
        effective_from_checkpoint="ckpt-1",
        actor="human_operator",
        reason="switch",
        now=NOW,
    )
    chain = list(opening.chain)

    orphan = svc.register_orphan_outcome(
        chain,
        outcome_id="outcome-9",
        source_generation=1,
        intercept_reason="late in-flight outcome under old generation",
        intercepted_at=NOW,
    )
    assert orphan.disposition == "pending_manual"
    assert orphan.sourceGeneration == 1
    assert orphan.activeGeneration == 2
    assert OrphanOutcomeRecord.from_dict(orphan.to_dict()) == orphan

    with pytest.raises(svc.PolicyGenerationServiceError) as not_cross:
        svc.register_orphan_outcome(
            chain,
            outcome_id="outcome-10",
            source_generation=2,
            intercept_reason="active generation outcome",
        )
    assert not_cross.value.code == "not_cross_generation"

    with pytest.raises(svc.PolicyGenerationServiceError) as unknown_gen:
        svc.register_orphan_outcome(
            chain,
            outcome_id="outcome-11",
            source_generation=7,
            intercept_reason="no such generation",
        )
    assert unknown_gen.value.code == "unknown_generation"

    with pytest.raises(svc.PolicyGenerationServiceError) as empty_id:
        svc.register_orphan_outcome(
            chain,
            outcome_id="  ",
            source_generation=1,
            intercept_reason="missing identity",
        )
    assert empty_id.value.code == "missing_or_empty"


def _orphan_record(disposition: str) -> OrphanOutcomeRecord:
    payload = _orphan_payload(disposition=disposition)
    if disposition in {"merged", "dismissed"}:
        payload.update(
            dispositionActor="human_operator",
            dispositionReason="prior adjudication",
            dispositionedAt=NOW,
        )
    return OrphanOutcomeRecord.from_dict(payload)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("pending_manual", "merged"),
        ("pending_manual", "dismissed"),
        ("pending_manual", "pending_manual"),
        ("merged", "dismissed"),
        ("merged", "merged"),
        ("dismissed", "merged"),
        ("dismissed", "dismissed"),
    ],
)
def test_orphan_disposition_moves_one_way_only(current: str, target: str) -> None:
    record = _orphan_record(current)
    legal = target in {"merged", "dismissed"} and current == "pending_manual"
    if legal:
        disposed = svc.dispose_orphan_outcome(
            record,
            disposition=target,
            actor="human_operator",
            reason="manual adjudication",
            now=LATER,
        )
        assert disposed.disposition == target
        assert disposed.dispositionActor == "human_operator"
        assert disposed.dispositionedAt == LATER
        assert OrphanOutcomeRecord.from_dict(disposed.to_dict()) == disposed
    else:
        with pytest.raises(svc.PolicyGenerationServiceError) as exc:
            svc.dispose_orphan_outcome(
                record,
                disposition=target,
                actor="human_operator",
                reason="manual adjudication",
                now=LATER,
            )
        assert exc.value.code == "disposition_transition_invalid"


def test_disposition_requires_actor_reason_and_record_keeps_evidence() -> None:
    record = OrphanOutcomeRecord.from_dict(_orphan_payload())

    with pytest.raises(svc.PolicyGenerationServiceError) as bad_actor:
        svc.dispose_orphan_outcome(
            record,
            disposition="merged",
            actor="autonomous_agent",
            reason="merged into new generation",
            now=LATER,
        )
    assert bad_actor.value.code == "unsupported_actor"

    with pytest.raises(svc.PolicyGenerationServiceError) as no_reason:
        svc.dispose_orphan_outcome(
            record,
            disposition="merged",
            actor="human_operator",
            reason=" ",
            now=LATER,
        )
    assert no_reason.value.code == "missing_or_empty"

    merged = svc.dispose_orphan_outcome(
        record,
        disposition="merged",
        actor="system_policy",
        reason="superseded by equivalent new-generation outcome",
        now=LATER,
    )
    with pytest.raises(PolicyGenerationValidationError) as decided_shape:
        OrphanOutcomeRecord.from_dict(
            {
                **merged.to_dict(),
                "dispositionActor": None,
                "dispositionReason": None,
                "dispositionedAt": None,
            }
        )
    assert _error_codes(decided_shape.value) == {
        "missing_actor",
        "missing_reason",
        "missing_or_empty",
    }

    with pytest.raises(PolicyGenerationValidationError) as pending_evidence:
        OrphanOutcomeRecord.from_dict(
            {**_orphan_payload(), "dispositionActor": "human_operator"}
        )
    assert {"unexpected_disposition_evidence"} <= _error_codes(pending_evidence.value)


def test_orphan_record_fail_closed_rules() -> None:
    with pytest.raises(PolicyGenerationValidationError) as same_generation:
        OrphanOutcomeRecord.from_dict(_orphan_payload(activeGeneration=1))
    assert {"not_cross_generation"} <= _error_codes(same_generation.value)

    with pytest.raises(PolicyGenerationValidationError) as bad_disposition:
        OrphanOutcomeRecord.from_dict(_orphan_payload(disposition="auto_merged"))
    assert {"unsupported_value"} <= _error_codes(bad_disposition.value)

    with pytest.raises(PolicyGenerationValidationError) as bad_actor:
        OrphanOutcomeRecord.from_dict(
            _orphan_payload(
                disposition="merged",
                dispositionActor="robot",
                dispositionReason="ok",
                dispositionedAt=LATER,
            )
        )
    assert {"unsupported_actor"} <= _error_codes(bad_actor.value)

    assert set(ORPHAN_DISPOSITIONS) == {"pending_manual", "merged", "dismissed"}
    ensure_orphan_disposition_transition("pending_manual", "dismissed")
    with pytest.raises(PolicyGenerationValidationError):
        ensure_orphan_disposition_transition("dismissed", "merged")


def test_pending_orphan_outcomes_filters_by_generation_and_disposition() -> None:
    gen1 = _first_generation()
    _, requested = svc.request_drain(
        [gen1], actor="human_operator", reason="switch", now=NOW
    )
    gen2 = PolicyGenerationRecord.from_dict(
        {
            "policyId": gen1.policyId,
            "generation": 2,
            "policyContentHash": HASH_V2,
            "effectiveFromCheckpoint": "ckpt-1",
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": 1,
        }
    )
    gen3 = PolicyGenerationRecord.from_dict(
        {
            "policyId": gen1.policyId,
            "generation": 3,
            "policyContentHash": HASH_V3,
            "effectiveFromCheckpoint": "ckpt-2",
            "drainMode": "none",
            "activatedAt": None,
            "predecessorGeneration": 2,
        }
    )
    chain = [requested, gen2, gen3]

    pending = svc.register_orphan_outcome(
        chain,
        outcome_id="outcome-1",
        source_generation=1,
        intercept_reason="in-flight",
        intercepted_at=NOW,
    )
    merged_same_outcome = svc.dispose_orphan_outcome(
        pending, disposition="merged", actor="human_operator", reason="ok", now=LATER
    )
    other_generation = svc.register_orphan_outcome(
        chain,
        outcome_id="outcome-2",
        source_generation=2,
        intercept_reason="in-flight under generation 2",
        intercepted_at=LATER,
    )

    undecided_for_gen1 = svc.pending_orphan_outcomes(
        [pending, merged_same_outcome, other_generation], generation=1
    )
    assert [item.outcomeId for item in undecided_for_gen1] == ["outcome-1"]
    assert svc.pending_orphan_outcomes(
        [pending, merged_same_outcome, other_generation], generation=2
    ) == (other_generation,)

    # Disposing the last pending orphan empties the set and drains generation 1.
    advancement = svc.advance_drain(
        chain, 1, pending_outcomes=undecided_for_gen1, now=LATER
    )
    assert advancement.generationRecord.drainMode == "draining"

    dismissed = svc.dispose_orphan_outcome(
        undecided_for_gen1[0],
        disposition="dismissed",
        actor="human_operator",
        reason="stale partial outcome",
        now=LATER,
    )
    drained = svc.advance_drain(
        [advancement.generationRecord],
        1,
        pending_outcomes=svc.pending_orphan_outcomes([dismissed], generation=1),
        now=LATER,
    )
    assert drained.generationRecord.drainMode == "drained"


# ---------------------------------------------------------------------------
# shared drainMode enum source with automation_policy
# ---------------------------------------------------------------------------


def test_drain_mode_enum_is_shared_not_copied() -> None:
    # Same object, not a re-declared literal set.
    assert POLICY_DRAIN_MODES is AUTO_ADVANCE_DRAIN_MODES
    assert set(DRAIN_MODE_TRANSITIONS) == set(AUTO_ADVANCE_DRAIN_MODES)
    # The automation policy service describes exactly the shared states.
    assert set(automation_policy_service.DRAIN_MODE_DESCRIPTIONS) == set(
        AUTO_ADVANCE_DRAIN_MODES
    )
    # A record outside the shared enum is rejected fail-closed.
    with pytest.raises(PolicyGenerationValidationError):
        PolicyGenerationRecord.from_dict(
            {**_first_generation().to_dict(), "drainMode": "drain_wait"}
        )


# ---------------------------------------------------------------------------
# end-to-end pure scenario (no command chain, no checkpoint execution)
# ---------------------------------------------------------------------------


def test_full_lifecycle_switch_drain_orphan_then_switch_again() -> None:
    chain = [_first_generation()]

    # 1. hash change opens generation 2 from checkpoint; generation 1 drains.
    opening = svc.open_generation(
        chain,
        policy_content_hash=HASH_V2,
        effective_from_checkpoint="ckpt-1",
        actor="system_policy",
        reason="approved policy v2",
        now=NOW,
    )
    chain = list(opening.chain)
    assert chain[0].drainMode == "requested"

    # 2. a late in-flight outcome under generation 1 is intercepted.
    orphan = svc.register_orphan_outcome(
        chain,
        outcome_id="outcome-late",
        source_generation=1,
        intercept_reason="cross_generation_commit_blocked",
        intercepted_at=NOW,
    )
    chain = [
        svc.advance_drain(
            chain, 1, pending_outcomes=[orphan], now=NOW
        ).generationRecord,
        chain[1],
    ]
    assert chain[0].drainMode == "draining"

    # 3. disposition merges the orphan; the set empties and the drain ends.
    merged = svc.dispose_orphan_outcome(
        orphan,
        disposition="merged",
        actor="human_operator",
        reason="outcome re-derived under generation 2",
        now=LATER,
    )
    final = svc.advance_drain(
        chain,
        1,
        pending_outcomes=svc.pending_orphan_outcomes([merged], generation=1),
        now=LATER,
    )
    chain = [final.generationRecord, chain[1]]
    assert chain[0].drainMode == "drained"

    # 4. only now a third generation may open.
    second = svc.open_generation(
        chain,
        policy_content_hash=HASH_V3,
        effective_from_checkpoint="ckpt-2",
        actor="human_operator",
        reason="approved policy v3",
        now=LATER,
    )
    assert [record.generation for record in second.chain] == [1, 2, 3]
    assert second.chain[1].drainMode == "requested"
    assert second.newGeneration.effectiveFromCheckpoint == "ckpt-2"
