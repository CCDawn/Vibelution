"""Independent operator identities and bounded, explicit research inputs."""
import pytest
from pydantic import ValidationError

from core.research.operator_optimization.candidate import (
    CudaCandidate,
    CudaCandidateArtifact,
    CudaCandidateRef,
    candidate_ref_from_artifact,
    ensure_current_source_hash,
    source_hash,
)
from core.research.operator_optimization.contracts import (
    ArtifactRef,
    CampaignBudget,
    MeasurementProtocolRef,
    OptimizationHypothesis,
    OptimizationCampaign,
    OptimizationRound,
    OperatorObjective,
)
from core.research.operator_optimization.plan import OptimizationPlan
from core.research.workflow.contracts._canonical import sha256_hex


def candidate_ref(candidate=None):
    candidate = candidate or CudaCandidate(implementation="torch_softmax")
    candidate_id = "candidate-1"
    run_id = "run-1"
    artifact = CudaCandidateArtifact(
        candidateId=candidate_id,
        optimizationCampaignId="opt-1",
        runId=run_id,
        candidate=candidate,
        sourceHash=source_hash(candidate),
    )
    envelope = {
        "teamId": "team-1",
        "kind": "operator_candidate",
        "workflowRunId": run_id,
        "sourceCollectionRunId": run_id,
        "payload": artifact.model_dump(mode="json"),
    }
    return CudaCandidateRef(
        artifactId=candidate_id,
        runId=run_id,
        sha256=sha256_hex(envelope),
        candidate=candidate,
        sourceHash=source_hash(candidate),
    )


def test_operator_defaults_preserve_semantics_and_require_bounded_budget():
    assert OperatorObjective().primaryMetric == "latency_ms"
    assert OperatorObjective().preserveSemantics is True
    with pytest.raises(ValidationError):
        OperatorObjective(preserveSemantics=False)
    for invalid in [float("inf"), float("nan"), -1]:
        with pytest.raises(ValidationError):
            CampaignBudget(modelCostLimit=invalid)
    assert CampaignBudget().authorized is False


def test_hypothesis_requires_observation_prediction_and_counterevidence():
    with pytest.raises(ValidationError):
        OptimizationHypothesis(hypothesisId="hyp-1", proposedChange="more warps")
    ref = ArtifactRef(artifactId="baseline-1", kind="baseline", sha256="a" * 64)
    candidate = candidate_ref()
    hypothesis = OptimizationHypothesis(
        hypothesisId="hyp-1", optimizationCampaignId="opt-1", roundId="round-1",
        parentCandidateRef=candidate, observationRefs=(ref,), proposedChange="more warps",
        mechanism="reduce per-thread reduction work", prediction="lower wide-row latency",
        counterevidence="register pressure may outweigh parallelism", roi="high",
        roiReason="one bounded parameter change", evidenceGaps=("occupancy limits",),
    )
    assert hypothesis.optimizationCampaignId == "opt-1"
    assert "campaignId" not in hypothesis.model_dump()
    with pytest.raises(ValidationError):
        ArtifactRef(artifactId="x", kind="baseline", sha256="invalid")


def test_candidate_ref_carries_recoverable_parameters_and_source_identity():
    ref = candidate_ref(CudaCandidate(implementation="triton_row_softmax", numWarps=8))
    assert ref.kind == "operator_candidate"
    assert ref.runId == "run-1"
    assert ref.candidate.implementation == "triton_row_softmax"
    assert ref.candidate.numWarps == 8
    assert ref.sourceHash == source_hash(ref.candidate)
    historical = ref.model_copy(update={"sourceHash": "a" * 64})
    assert historical.sourceHash == "a" * 64
    with pytest.raises(ValueError, match="current controlled implementation"):
        ensure_current_source_hash(historical.candidate, historical.sourceHash)


def test_historical_candidate_artifact_remains_readable_until_execution_admission():
    candidate = CudaCandidate(implementation="torch_softmax")
    artifact = CudaCandidateArtifact(
        candidateId="candidate-history",
        optimizationCampaignId="opt-1",
        runId="run-1",
        candidate=candidate,
        sourceHash="a" * 64,
    )
    envelope = {
        "recordId": artifact.candidateId,
        "kind": "operator_candidate",
        "workflowRunId": artifact.runId,
        "payload": artifact.model_dump(mode="json"),
    }
    ref = candidate_ref_from_artifact(
        envelope, artifact_id=artifact.candidateId, run_id=artifact.runId,
    )
    assert ref.sourceHash == "a" * 64
    with pytest.raises(ValueError, match="current controlled implementation"):
        ensure_current_source_hash(ref.candidate, ref.sourceHash)


def test_round_plan_references_frozen_protocol_and_records_candidates():
    parent = candidate_ref()
    protocol = MeasurementProtocolRef(
        artifactId="protocol-1", runId="run-1", sha256="a" * 64,
    )
    plan = OptimizationPlan(
        planId="plan-1",
        optimizationCampaignId="opt-1",
        roundId="round-1",
        protocolRef=protocol,
        baselineCandidateRef=parent,
        parentCandidateRef=parent,
        candidateRef=parent,
        objective="Compare the proposed candidate against the fixed parent",
        evaluation="Use the frozen paired latency and correctness protocol",
    )
    assert plan.protocolRef.kind == "operator_measurement_protocol"
    assert plan.parentCandidateRef.candidate == parent.candidate
    assert plan.candidateRef.sourceHash == parent.sourceHash


def test_campaign_json_roundtrip_preserves_protocol_ref_run_id():
    parent = candidate_ref()
    protocol = MeasurementProtocolRef(
        artifactId="protocol-round-1", runId="run-round-1", sha256="b" * 64,
    )
    round_record = OptimizationRound(
        roundId="round-1",
        runId="run-round-1",
        ordinal=1,
        baselineCandidateRef=parent,
        parentCandidateRef=parent,
        protocolRef=protocol,
    )
    campaign = OptimizationCampaign(
        optimizationCampaignId="opt-1",
        teamId="team-1",
        researchProjectId="project-1",
        title="Softmax",
        objective=OperatorObjective(),
        budget=CampaignBudget(),
        status="running",
        baselineSetupId="baseline-setup-1",
        baselineCandidateRef=parent,
        rounds=(round_record,),
        createdAt="2026-09-08T00:00:00Z",
        updatedAt="2026-09-08T00:00:00Z",
    )

    restored = OptimizationCampaign.model_validate_json(campaign.model_dump_json())

    assert isinstance(restored.rounds[0].protocolRef, MeasurementProtocolRef)
    assert restored.rounds[0].protocolRef.runId == "run-round-1"
