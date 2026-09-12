"""Durable trial admission, canonical measurement receipt and cost settlement."""
from __future__ import annotations

from core.research.operator_optimization.candidate import (
    CudaCandidateRef,
    candidate_ref_from_artifact,
    source_hash,
)
from core.research.operator_optimization.contracts import ArtifactRef
from core.research.operator_optimization.cuda_worker import CudaTrialRequest
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.atomic_fs import atomic_write_text
from ..storage_durability import inter_process_lock
from .budget import release_gpu_reservation, reserve_gpu_time, settle_gpu_usage
from .executor import execute_cuda_trial
from .store import CampaignConflict, campaign_root, read_campaign, update_campaign


def dispatch_trial(team_id: str, project_id: str, request: CudaTrialRequest, *,
    device_name: str, baseline: bool = False) -> ArtifactRef:
    campaign_id = request.campaign_id
    kind = "operator_baseline" if baseline else "operator_measurement"
    identity = "operator-trial:" + request.measurement_id
    intent = campaign_root(team_id, project_id) / "trials" / (sha256_hex(identity) + ".json")
    fingerprint = sha256_hex({"request": request.model_dump(mode="json"), "kind": kind, "device": device_name})
    with inter_process_lock(intent):
        campaign = read_campaign(team_id, project_id, campaign_id)
        if intent.exists() and intent.read_text(encoding="utf-8") != fingerprint:
            raise CampaignConflict("Trial identity belongs to different frozen inputs")
        envelope = load_scoped_artifact_payload(kind, team_id=team_id, workflow_run_id=request.run_id,
            authority_run_id=request.run_id, record_id=identity)
        if envelope is None:
            if any(r.reservationId == request.measurement_id for r in campaign.gpuReservations):
                raise CampaignConflict("Trial was admitted without a terminal receipt; reconcile before retrying")
            if request.max_seconds != int(request.max_seconds):
                raise ValueError("Device reservation must be an integral number of seconds")
            intent.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(intent, fingerprint)
            reserve_gpu_time(team_id, project_id, campaign_id, run_id=request.run_id,
                reservation_id=request.measurement_id, seconds=int(request.max_seconds),
                protocol_hash=sha256_hex(request.protocol.model_dump(mode="json")), phase=request.protocol.split)
            try:
                measurement = execute_cuda_trial(request, device_name=device_name)
            except BlockingIOError:
                # Device lock contention proves no worker was started. Release
                # the budget admission so a later attempt can acquire the GPU.
                release_gpu_reservation(team_id, project_id, campaign_id,
                    reservation_id=request.measurement_id, reason="device_busy")
                raise
            # Canonical artifact store is the only measurement authority.
            with inter_process_lock(artifacts._path(team_id, kind)):
                artifacts.put_workflow_artifact(team_id, kind=kind, workflow_run_id=request.run_id,
                    artifact_identity=identity, payload=measurement.model_dump(mode="json"))
            envelope = load_scoped_artifact_payload(kind, team_id=team_id, workflow_run_id=request.run_id,
                authority_run_id=request.run_id, record_id=identity)
        if envelope is None:
            raise CampaignConflict("Persisted GPU measurement could not be read back")
        ref = ArtifactRef(artifactId=identity, kind=kind, sha256=sha256_hex(envelope))
        settle_gpu_usage(team_id, project_id, campaign_id,
            reservation_id=request.measurement_id, measurement_ref=ref)
        return ref


def dispatch_baseline(action, snapshot: dict) -> ArtifactRef:
    team_id, project_id = snapshot["teamId"], snapshot["projectId"]
    campaign_id = snapshot["researchObjectiveContract"]["optimizationCampaignId"]
    campaign = read_campaign(team_id, project_id, campaign_id)
    if campaign.baselineRunId != action.run_id:
        raise CampaignConflict("Baseline run does not belong to this campaign")
    def frozen(kind, digest):
        if not digest:
            raise CampaignConflict("Frozen artifact hash is required")
        envelope = load_scoped_artifact_payload(kind, team_id=team_id, workflow_run_id=action.run_id,
            authority_run_id=action.run_id, content_hash=digest)
        if envelope is None:
            raise CampaignConflict("Frozen baseline artifact cannot be verified")
        return envelope["payload"]
    protocol = frozen("operator_measurement_protocol", snapshot["evaluationContract"]["protocolArtifactHash"])
    environment = frozen("operator_environment", snapshot["environmentSnapshotRef"])
    if sha256_hex(protocol) != snapshot["evaluationContract"]["protocolHash"]:
        raise CampaignConflict("Frozen protocol payload hash differs")
    candidate_ref = CudaCandidateRef.model_validate(snapshot["researchObjectiveContract"]["baselineCandidateRef"])
    if candidate_ref != campaign.baselineCandidateRef or candidate_ref.runId != action.run_id:
        raise CampaignConflict("Frozen baseline candidate identity differs")
    candidate_envelope = load_scoped_artifact_payload("operator_candidate", team_id=team_id,
        workflow_run_id=action.run_id, authority_run_id=action.run_id,
        record_id=candidate_ref.artifactId, content_hash=candidate_ref.sha256)
    if candidate_envelope is None or candidate_ref_from_artifact(candidate_envelope,
        artifact_id=candidate_ref.artifactId, run_id=action.run_id) != candidate_ref:
        raise CampaignConflict("Frozen baseline candidate cannot be verified")
    if candidate_ref.sourceHash != source_hash(candidate_ref.candidate):
        raise CampaignConflict("Frozen baseline implementation differs from the current runner")
    spec = candidate_ref.candidate
    request = CudaTrialRequest(protocol=protocol, baseline=spec, parent=spec, candidate=spec,
        campaign_id=campaign_id, run_id=action.run_id,
        measurement_id="baseline-" + sha256_hex({"campaign": campaign_id, "run": action.run_id})[:24],
        expected_environment_hash=sha256_hex(environment), max_seconds=campaign.budget.trialTimeoutSeconds)
    ref = dispatch_trial(team_id, project_id, request, device_name=environment["deviceName"], baseline=True)
    envelope = load_scoped_artifact_payload(ref.kind, team_id=team_id, workflow_run_id=action.run_id,
        authority_run_id=action.run_id, record_id=ref.artifactId, content_hash=ref.sha256)
    if envelope is None or envelope["payload"]["status"] != "succeeded":
        raise RuntimeError("Baseline measurement did not succeed; terminal receipt and incurred cost are preserved")
    measurement = OperatorMeasurement.model_validate(envelope["payload"])
    if ({row.caseId for row in measurement.cases} != {case.caseId for case in request.protocol.cases}
        or any(not row.correctnessPassed or row.maxAbsoluteError is None
            or len(row.timings) != request.protocol.pairs for row in measurement.cases)):
        raise RuntimeError("Baseline measurement lacks complete correctness and paired timing evidence")
    def bind(c):
        if c.baselineRunId != action.run_id or (c.baselineRef is not None and c.baselineRef != ref):
            raise CampaignConflict("Immutable baseline identity differs")
        return c.model_copy(update={"baselineRef": ref})
    update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key="baseline-measured:" + action.run_id,
        command={"action": "baseline_measured", "measurementRef": ref.model_dump(mode="json")}, transform=bind)
    return ref
