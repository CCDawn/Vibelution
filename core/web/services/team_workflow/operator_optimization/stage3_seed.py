"""Build and verify the immutable handoff used by Stage 3 operator rounds."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.research.operator_optimization.contracts import (
    STAGE2_SEED_ARTIFACT_KIND,
    ArtifactRef,
    OperatorStage2Seed,
    OptimizationHypothesis,
    Stage2SeedRef,
)
from core.research.operator_optimization.plan import OptimizationPlan
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..storage_durability import inter_process_lock
from .store import CampaignConflict


def read_stage2_seed(team_id: str, ref: Stage2SeedRef | dict) -> OperatorStage2Seed:
    ref = Stage2SeedRef.model_validate(ref)
    envelope = load_scoped_artifact_payload(
        STAGE2_SEED_ARTIFACT_KIND,
        team_id=team_id,
        workflow_run_id=ref.runId,
        authority_run_id=ref.runId,
        record_id=ref.artifactId,
        content_hash=ref.sha256,
    )
    if envelope is None:
        raise CampaignConflict("Stage 2 seed cannot be read back")
    try:
        return OperatorStage2Seed.model_validate(envelope["payload"])
    except ValueError as exc:
        raise CampaignConflict("Stage 2 seed is invalid") from exc


def source_owner(team_id: str, record, field: str) -> str:
    ref = getattr(record, field)
    if ref is None or record.stage2SeedRef is None:
        return record.runId
    inherited_seed = read_stage2_seed(team_id, record.stage2SeedRef)
    if ref != getattr(inherited_seed, field):
        return record.runId
    return getattr(inherited_seed, field.replace("Ref", "RunId")) or record.runId


def inherit_iteration_evidence(
    *,
    team_id: str,
    campaign,
    campaign_id: str,
    prior,
    parent,
    iteration_action: str | None,
    observations: list[ArtifactRef],
    read: Callable[[ArtifactRef, str], dict],
) -> OptimizationHypothesis | None:
    if iteration_action not in {"collect_knowledge", "plan_candidate", "retest"}:
        return None
    if prior is None or prior.parentCandidateRef != parent:
        raise CampaignConflict(
            "Stage 2 hypothesis lineage differs from the current parent candidate"
        )
    if prior.hypothesisRef is None:
        raise CampaignConflict("Stage 2 iteration action requires a hypothesis")
    hypothesis = OptimizationHypothesis.model_validate(
        read(prior.hypothesisRef, source_owner(team_id, prior, "hypothesisRef"))
    )
    if (
        hypothesis.optimizationCampaignId != campaign_id
        or hypothesis.parentCandidateRef != parent
    ):
        raise CampaignConflict(
            "Stage 2 hypothesis differs from the current candidate lineage"
        )
    allowed_observation_owners = {campaign.baselineRef: campaign.baselineRunId}
    for old_round in campaign.rounds:
        for old_ref in (old_round.evaluationRef, old_round.feedbackRef):
            if old_ref is not None:
                allowed_observation_owners[old_ref] = old_round.runId
    for reservation in campaign.gpuReservations:
        if reservation.measurementRef is not None:
            allowed_observation_owners[reservation.measurementRef] = reservation.runId
    for observation_ref in hypothesis.observationRefs:
        owner = allowed_observation_owners.get(observation_ref)
        if owner is None:
            raise CampaignConflict(
                "Inherited hypothesis observation is outside campaign history"
            )
        read(observation_ref, owner)
        if observation_ref not in observations:
            observations.append(observation_ref)
    if len(observations) > 24:
        raise CampaignConflict(
            "Inherited hypothesis exceeds the bounded observation context"
        )
    return hypothesis


def write_stage2_seed(
    *,
    team_id: str,
    campaign,
    campaign_id: str,
    prior,
    inherited_hypothesis: OptimizationHypothesis | None,
    round_id: str,
    run_id: str,
    read: Callable[[ArtifactRef, str], dict],
    read_candidate: Callable[[Any], Any],
) -> Stage2SeedRef:
    if prior is None or prior.evaluationRef is None or prior.feedbackRef is None:
        raise CampaignConflict("Experiment iteration requires a completed foundation round")
    attempted_items = []
    for old_round in campaign.rounds:
        if old_round.planRef is None:
            continue
        plan = OptimizationPlan.model_validate(
            read(old_round.planRef, source_owner(team_id, old_round, "planRef"))
        )
        read_candidate(plan.candidateRef)
        if plan.candidateRef not in attempted_items:
            attempted_items.append(plan.candidateRef)
    hypothesis_owner = (
        source_owner(team_id, prior, "hypothesisRef") if prior.hypothesisRef else ""
    )
    seed_hypothesis = inherited_hypothesis
    if seed_hypothesis is None and prior.hypothesisRef is not None:
        seed_hypothesis = OptimizationHypothesis.model_validate(
            read(prior.hypothesisRef, hypothesis_owner)
        )
    seed = OperatorStage2Seed(
        optimizationCampaignId=campaign_id,
        sourceRoundId=prior.roundId,
        sourceRunId=prior.runId,
        baselineRunId=campaign.baselineRunId,
        baselineRef=campaign.baselineRef,
        protocolRef=prior.protocolRef,
        hypothesisRef=prior.hypothesisRef,
        hypothesisRunId=hypothesis_owner,
        hypothesisRoundId=seed_hypothesis.roundId if seed_hypothesis else "",
        knowledgeRef=prior.knowledgeRef,
        knowledgeRunId=(
            source_owner(team_id, prior, "knowledgeRef") if prior.knowledgeRef else ""
        ),
        planRef=prior.planRef,
        planRunId=source_owner(team_id, prior, "planRef") if prior.planRef else "",
        evaluationRef=prior.evaluationRef,
        feedbackRef=prior.feedbackRef,
        attemptedCandidateRefs=tuple(attempted_items),
    )
    with inter_process_lock(artifacts._path(team_id, STAGE2_SEED_ARTIFACT_KIND)):
        row = artifacts.put_workflow_artifact(
            team_id,
            kind=STAGE2_SEED_ARTIFACT_KIND,
            workflow_run_id=run_id,
            artifact_identity="operator-stage2-seed:" + round_id,
            payload=seed.model_dump(mode="json"),
        )
    envelope = load_scoped_artifact_payload(
        STAGE2_SEED_ARTIFACT_KIND,
        team_id=team_id,
        workflow_run_id=run_id,
        authority_run_id=run_id,
        record_id=row["recordId"],
    )
    if envelope is None:
        raise CampaignConflict("Stage 2 seed could not be read back")
    return Stage2SeedRef(
        artifactId=row["recordId"], runId=run_id, sha256=sha256_hex(envelope)
    )


def bind_retest_plan(
    *,
    team_id: str,
    prior,
    baseline_candidate,
    parent,
    inherited_hypothesis_ref,
    inherited_knowledge_ref,
    protocol_ref,
    round_id: str,
    run_id: str,
    read: Callable[[ArtifactRef, str], dict],
) -> ArtifactRef:
    if prior is None or prior.planRef is None:
        raise CampaignConflict("Retest requires a frozen source plan")
    source_plan = OptimizationPlan.model_validate(
        read(prior.planRef, source_owner(team_id, prior, "planRef"))
    )
    if (
        source_plan.hypothesisRef != inherited_hypothesis_ref
        or source_plan.knowledgeRef != inherited_knowledge_ref
        or source_plan.baselineCandidateRef != baseline_candidate
        or source_plan.parentCandidateRef != parent
    ):
        raise CampaignConflict("Retest source plan differs from the active lineage")
    retest_plan = source_plan.model_copy(
        update={
            "planId": "operator-retest-plan:" + round_id,
            "roundId": round_id,
            "protocolRef": protocol_ref,
        }
    )
    with inter_process_lock(artifacts._path(team_id, "optimization_plan")):
        row = artifacts.put_workflow_artifact(
            team_id,
            kind="optimization_plan",
            workflow_run_id=run_id,
            artifact_identity=retest_plan.planId,
            payload=retest_plan.model_dump(mode="json"),
        )
    envelope = load_scoped_artifact_payload(
        "optimization_plan",
        team_id=team_id,
        workflow_run_id=run_id,
        authority_run_id=run_id,
        record_id=row["recordId"],
    )
    if envelope is None:
        raise CampaignConflict("Retest plan binding could not be read back")
    return ArtifactRef(
        artifactId=row["recordId"],
        kind="optimization_plan",
        sha256=sha256_hex(envelope),
    )
