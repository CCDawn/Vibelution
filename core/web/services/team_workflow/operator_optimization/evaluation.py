"""Evaluate every planned, settled trial without selecting a lucky repeat."""

from core.research.operator_optimization.measurement import (
    MeasurementProtocol,
    OperatorMeasurement,
)
from core.research.operator_optimization.evaluation import evaluate_measurement
from core.research.workflow.contracts._canonical import sha256_hex

from .execution import load_frozen_plan, require_active_node, trial_measurement_id
from .knowledge import read_ref, attach_round_ref
from .discussion import _write_readback
from .store import CampaignConflict

POLICY = "all_planned_trials_pass_v1"


def evaluate_round(run):
    campaign, record, plan, inputs, environment = load_frozen_plan(run)
    protocol = MeasurementProtocol.model_validate(inputs["protocol"])
    trials = []
    for index in range(plan.trialCount):
        identity = trial_measurement_id(run.run_id, record.planRef.sha256, index)
        reservation = next(
            (r for r in campaign.gpuReservations if r.reservationId == identity), None
        )
        if (
            reservation is None
            or reservation.runId != run.run_id
            or reservation.phase != "tuning"
            or reservation.measurementRef is None
            or reservation.consumedSeconds is None
            or reservation.measurementRef.kind != "operator_measurement"
        ):
            raise CampaignConflict(
                "Evaluation requires every planned trial to be settled"
            )
        measured = OperatorMeasurement.model_validate(
            read_ref(run.team_id, run.run_id, reservation.measurementRef)
        )
        if (
            measured.measurementId != identity
            or measured.runId != run.run_id
            or measured.optimizationCampaignId != campaign.optimizationCampaignId
            or measured.candidateSourceHash != plan.candidateRef.sourceHash
            or measured.status != reservation.outcome
            or measured.gpuSeconds != reservation.consumedSeconds
            or measured.protocolHash != reservation.protocolHash
        ):
            raise CampaignConflict(
                "Measurement differs from its planned trial and settlement"
            )
        result = evaluate_measurement(
            protocol,
            measured,
            expected_environment_hash=sha256_hex(environment),
            expected_baseline_hash=plan.baselineCandidateRef.sourceHash,
            expected_parent_hash=plan.parentCandidateRef.sourceHash,
        )
        # A correctness flag alone cannot stand in for a measured error.
        if any(
            c.correctnessPassed and c.maxAbsoluteError is None for c in measured.cases
        ):
            result["reasons"].append("missing_correctness_error")
            result.update(comparable=False, promote=False)
        trials.append(
            {
                "measurementRef": reservation.measurementRef.model_dump(mode="json"),
                "executionStatus": measured.status,
                "failureReason": measured.failureReason,
                **result,
            }
        )
    return (
        campaign,
        record,
        plan,
        {
            "schemaVersion": 1,
            "runId": run.run_id,
            "roundId": record.roundId,
            "optimizationCampaignId": campaign.optimizationCampaignId,
            "planRef": record.planRef.model_dump(mode="json"),
            "candidateRef": plan.candidateRef.model_dump(mode="json"),
            "parentCandidateRef": plan.parentCandidateRef.model_dump(mode="json"),
            "policy": POLICY,
            "split": "tuning",
            "trials": trials,
            "promote": all(t["promote"] for t in trials),
            "gpuSeconds": sum(t["gpuSeconds"] for t in trials),
            "uncertaintyScope": "per_trial_within_run_paired_samples",
        },
    )


def publish_evaluation(action, snapshot):
    run = require_active_node(action, snapshot, "operator_evaluation")
    campaign, record, _, payload = evaluate_round(run)
    _, ref = _write_readback(
        run.team_id,
        run.run_id,
        kind="operator_evaluation",
        identity="operator-evaluation:" + record.roundId,
        payload=payload,
    )
    attach_round_ref(
        run.team_id, run.run_id, campaign, record, field="evaluationRef", ref=ref
    )
    return ref
