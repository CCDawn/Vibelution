"""Create a scoped optimization round from terminal, canonical evidence."""
from __future__ import annotations

import json

from core.research.operator_optimization.candidate import (
    CudaCandidateArtifact,
    CudaCandidateRef,
)
from core.research.operator_optimization.contracts import ArtifactRef, OptimizationRound
from core.research.operator_optimization.measurement import (
    MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    MeasurementProtocolRef,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.operator_optimization_definition import OPERATOR_WORKFLOW_ID

from ..research_runtime import run_creation
from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..storage_durability import inter_process_lock
from .budget import budget_summary
from .run_input import build_operator_run_input
from .store import CampaignConflict, update_campaign


def prepare_round(team_id: str, project_id: str, campaign_id: str, *, expected_version: int, command_key: str):
    def prepare(campaign):
        if campaign.status != "running" or not campaign.budget.authorized or not campaign.authorizedBy:
            raise CampaignConflict("Campaign is not admitting optimization rounds")
        if not campaign.baselineRef:
            raise CampaignConflict("A verified initial baseline is required")
        if not campaign.baselineCandidateRef:
            raise CampaignConflict("A recoverable baseline candidate is required")
        if len(campaign.rounds) >= campaign.budget.maxRounds:
            raise CampaignConflict("Maximum optimization rounds reached")
        if campaign.budget.modelCostLimit <= 0 or budget_summary(campaign)["gpuTuningAvailableSeconds"] <= 0:
            raise CampaignConflict("Optimization budget is unavailable")
        ledger = run_creation.get_write_store()
        baseline_run = ledger.get_run(campaign.baselineRunId)
        prior = campaign.rounds[-1] if campaign.rounds else None
        previous_run = ledger.get_run(prior.runId if prior else campaign.baselineRunId)
        if baseline_run is None or baseline_run.status != "succeeded":
            raise CampaignConflict("Baseline Ledger run has not completed")
        if previous_run is None or previous_run.status not in {"succeeded", "failed"}:
            raise CampaignConflict("Previous run has not reached a terminal state")
        if campaign.activeRunId != previous_run.run_id:
            raise CampaignConflict("Active run differs from the previous round")
        for run in (baseline_run, previous_run):
            if (run.team_id, run.project_id) != (team_id, project_id):
                raise CampaignConflict("Previous run belongs to another project")
        observations = [campaign.baselineRef]
        def read(ref, run_id):
            envelope = load_scoped_artifact_payload(ref.kind, team_id=team_id, workflow_run_id=run_id,
                authority_run_id=run_id, record_id=ref.artifactId, content_hash=ref.sha256)
            if envelope is None:
                raise CampaignConflict("Round source evidence cannot be verified")
            return envelope["payload"]
        measured = read(campaign.baselineRef, campaign.baselineRunId)
        if measured.get("status") != "succeeded" or measured.get("optimizationCampaignId") != campaign_id:
            raise CampaignConflict("Initial baseline is not a successful measurement for this activity")

        def read_candidate(ref: CudaCandidateRef) -> CudaCandidateArtifact:
            envelope = load_scoped_artifact_payload(
                "operator_candidate",
                team_id=team_id,
                workflow_run_id=ref.runId,
                authority_run_id=ref.runId,
                record_id=ref.artifactId,
                content_hash=ref.sha256,
            )
            if envelope is None:
                raise CampaignConflict("Candidate implementation artifact cannot be verified")
            try:
                artifact = CudaCandidateArtifact.model_validate(envelope["payload"])
            except ValueError as exc:
                raise CampaignConflict("Candidate implementation artifact is invalid") from exc
            if (
                artifact.candidateId != ref.artifactId
                or artifact.runId != ref.runId
                or artifact.candidate != ref.candidate
                or artifact.sourceHash != ref.sourceHash
                or artifact.optimizationCampaignId != campaign_id
            ):
                raise CampaignConflict("Candidate implementation identity differs")
            return artifact

        baseline_candidate = campaign.baselineCandidateRef
        read_candidate(baseline_candidate)
        if baseline_candidate.runId != campaign.baselineRunId:
            raise CampaignConflict("Baseline candidate belongs to another run")
        if prior:
            if not prior.feedbackRef:
                raise CampaignConflict("Previous round requires canonical feedback before another discussion")
            for ref in (prior.evaluationRef, prior.feedbackRef):
                if ref is not None:
                    read(ref, prior.runId)
                    observations.append(ref)
            for reservation in campaign.gpuReservations:
                if reservation.runId == prior.runId and reservation.phase == "tuning" and reservation.measurementRef:
                    read(reservation.measurementRef, prior.runId)
                    observations.append(reservation.measurementRef)
        parent = campaign.bestCandidateRef or baseline_candidate
        if parent != baseline_candidate:
            read_candidate(parent)
            parent_measured = False
            for reservation in campaign.gpuReservations:
                if reservation.phase != "tuning" or reservation.outcome != "succeeded" or not reservation.measurementRef:
                    continue
                payload = read(reservation.measurementRef, reservation.runId)
                if payload.get("candidateSourceHash") == parent.sourceHash:
                    parent_measured = True
                    break
            if not parent_measured:
                raise CampaignConflict("Parent candidate lacks a successful measurement receipt")
        round_id = "round-" + sha256_hex({"campaign": campaign_id, "ordinal": len(campaign.rounds) + 1})[:24]
        run_id = run_creation.run_id_for_create(OPERATOR_WORKFLOW_ID, round_id)
        frozen = json.loads(baseline_run.input_snapshot_json)
        def copy_frozen(kind: str, digest: str) -> str | ArtifactRef:
            envelope = load_scoped_artifact_payload(kind, team_id=team_id, workflow_run_id=campaign.baselineRunId,
                authority_run_id=campaign.baselineRunId, content_hash=digest)
            if not digest or envelope is None:
                raise CampaignConflict("Baseline environment or protocol cannot be verified")
            payload = envelope["payload"]
            artifact_identity = round_id + ":" + kind
            with inter_process_lock(artifacts._path(team_id, kind)):
                row = artifacts.put_workflow_artifact(team_id, kind=kind, workflow_run_id=run_id,
                    artifact_identity=artifact_identity, payload=payload)
            copied = load_scoped_artifact_payload(kind, team_id=team_id,
                workflow_run_id=run_id, authority_run_id=run_id,
                record_id=row["recordId"])
            if copied is None:
                raise CampaignConflict("Frozen artifact copy could not be read back")
            digest = sha256_hex(copied)
            if kind == MEASUREMENT_PROTOCOL_ARTIFACT_KIND:
                return MeasurementProtocolRef(
                    artifactId=row["recordId"], runId=run_id, sha256=digest,
                )
            return digest
        environment_hash = copy_frozen("operator_environment", frozen["environmentSnapshotRef"])
        protocol_ref = copy_frozen(MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
            frozen["evaluationContract"]["protocolArtifactHash"])
        if not isinstance(protocol_ref, MeasurementProtocolRef):
            raise CampaignConflict("Frozen measurement protocol reference is invalid")
        record = OptimizationRound(
            roundId=round_id,
            runId=run_id,
            ordinal=len(campaign.rounds) + 1,
            baselineCandidateRef=baseline_candidate,
            parentCandidateRef=parent,
            protocolRef=protocol_ref,
        )
        run_input = build_operator_run_input(campaign, record, environment_ref=environment_hash,
            protocol_artifact_id=protocol_ref.artifactId,
            protocol_run_id=run_id,
            protocol_artifact_hash=protocol_ref.sha256,
            protocol_hash=frozen["evaluationContract"]["protocolHash"],
            workload_ref=frozen["datasetRefs"][0], observation_refs=tuple(observations))
        run_creation.create_run(OPERATOR_WORKFLOW_ID, run_input=run_input, idempotency_key=round_id)
        return campaign.model_copy(update={"rounds": (*campaign.rounds, record), "activeRunId": run_id})
    return update_campaign(team_id, project_id, campaign_id, expected_version=expected_version,
        command_key=command_key, command={"action": "prepare_round"}, transform=prepare)
