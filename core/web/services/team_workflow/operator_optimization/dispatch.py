"""Durable trial admission, canonical measurement receipt and cost settlement."""
from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import ExitStack, contextmanager, nullcontext
from pathlib import Path
from typing import ContextManager, Literal
from uuid import uuid4

from core.research.operator_optimization.candidate import (
    CudaCandidateRef,
    candidate_ref_from_artifact,
    source_hash,
)
from core.research.operator_optimization.contracts import ArtifactRef, Contract, Digest, Identity
from core.research.operator_optimization.cuda_worker import CudaMeasurementIdentity, CudaTrialRequest
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.atomic_fs import atomic_write_text
from ..storage_durability import _windows_extended_length_path, inter_process_lock
from .budget import release_gpu_reservation, reserve_gpu_time, settle_gpu_usage
from .executor import TrialReceiptTarget, cuda_worker_lease_busy, execute_cuda_trial
from .store import CampaignConflict, campaign_root, read_campaign, update_campaign


_TRIAL_KINDS = ("operator_measurement", "operator_baseline")


class _TrialIntent(Contract):
    schemaVersion: Literal[1] = 1
    kind: Literal["operator_measurement", "operator_baseline"]
    fingerprint: Digest
    identity: CudaMeasurementIdentity
    # Null records that the launch fence was never crossed, or that the
    # previous worker explicitly reported no CUDA lease acquisition.
    launchId: Identity | None

    def persist(self, path: Path) -> None:
        atomic_write_text(path, self.model_dump_json())

    def receipt_target(self, path: Path, launch_id: str) -> TrialReceiptTarget:
        return TrialReceiptTarget(_receipt_path(path), self.fingerprint, launch_id, self.identity)


def _intent_path(team_id: str, project_id: str, artifact_id: str) -> Path:
    return _windows_extended_length_path(
        campaign_root(team_id, project_id) / "trials" / (sha256_hex(artifact_id) + ".json")
    )


def _receipt_path(path: Path) -> Path:
    return _windows_extended_length_path(path.with_suffix(".receipt.json"))


def _read_intent(path: Path) -> _TrialIntent | str | None:
    try:
        encoded = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    if re.fullmatch(r"[a-f0-9]{64}", encoded):
        # Old dispatch recorded only the fingerprint. It did not record
        # whether it had crossed Popen, so a pending reservation is ambiguous.
        return encoded
    try:
        return _TrialIntent.model_validate_json(encoded)
    except ValueError as exc:
        raise CampaignConflict("GPU trial intent cannot be verified") from exc


def _read_trial_receipt(path: Path, intent: _TrialIntent):
    if intent.launchId is None:
        return None
    try:
        return intent.receipt_target(path, intent.launchId).read()
    except ValueError as exc:
        raise CampaignConflict("GPU trial receipt cannot be verified") from exc


def _canonical_ref(team_id: str, run_id: str, artifact_id: str, kind: str,
                   intent: _TrialIntent | None) -> ArtifactRef | None:
    envelope = load_scoped_artifact_payload(
        kind, team_id=team_id, workflow_run_id=run_id, authority_run_id=run_id, record_id=artifact_id
    )
    if envelope is None:
        return None
    if intent is not None and not intent.identity.matches(OperatorMeasurement.model_validate(envelope["payload"])):
        raise CampaignConflict("Canonical GPU measurement differs from the trial intent")
    return ArtifactRef(artifactId=artifact_id, kind=kind, sha256=sha256_hex(envelope))


def _publish_measurement(team_id: str, artifact_id: str,
                         intent: _TrialIntent, measurement: OperatorMeasurement) -> ArtifactRef:
    run_id, kind = intent.identity.runId, intent.kind
    with inter_process_lock(artifacts._path(team_id, kind)):
        artifacts.put_workflow_artifact(team_id, kind=kind, workflow_run_id=run_id,
            artifact_identity=artifact_id, payload=measurement.model_dump(mode="json"))
    ref = _canonical_ref(team_id, run_id, artifact_id, kind, intent)
    if ref is None:
        raise CampaignConflict("Persisted GPU measurement could not be read back")
    return ref


def _recover_trial(team_id: str, run_id: str, artifact_id: str, path: Path,
                   intent: _TrialIntent | None, kinds: tuple[str, ...], *,
                   unsettled: bool) -> tuple[ArtifactRef | None, bool]:
    refs = [ref for kind in kinds if (ref := _canonical_ref(team_id, run_id, artifact_id, kind, intent)) is not None]
    if len(refs) > 1:
        raise CampaignConflict("GPU reservation has more than one canonical measurement")
    if refs:
        return refs[0], False
    if intent is None:
        return None, False
    if intent.launchId is None:
        return None, True
    receipt = _read_trial_receipt(path, intent)
    if receipt is None:
        return None, False
    if receipt.measurement is None:
        return None, True
    if not unsettled:
        raise CampaignConflict("GPU worker receipt has no unsettled reservation")
    return _publish_measurement(team_id, artifact_id, intent, receipt.measurement), False


def dispatch_trial(
    team_id: str, project_id: str, request: CudaTrialRequest, *, device_name: str,
    baseline: bool = False, start_fence: Callable[[], ContextManager[None]] | None = None,
) -> ArtifactRef:
    campaign_id, run_id, measurement_id = request.campaign_id, request.run_id, request.measurement_id
    kind = "operator_baseline" if baseline else "operator_measurement"
    artifact_id = "operator-trial:" + measurement_id
    path = _intent_path(team_id, project_id, artifact_id)
    fingerprint = sha256_hex({"request": request.model_dump(mode="json"), "kind": kind, "device": device_name})

    def release_unstarted(reason: str) -> None:
        release_gpu_reservation(team_id, project_id, campaign_id, reservation_id=measurement_id, reason=reason)

    with inter_process_lock(path):
        campaign = read_campaign(team_id, project_id, campaign_id)
        state = _read_intent(path)
        intent = state if isinstance(state, _TrialIntent) else None
        if (intent is not None and (intent.fingerprint, intent.kind) != (fingerprint, kind)
                or isinstance(state, str) and state != fingerprint):
            raise CampaignConflict("Trial identity belongs to different frozen inputs")
        reservation = next((r for r in campaign.gpuReservations if r.reservationId == measurement_id), None)
        ref, unstarted = _recover_trial(
            team_id, run_id, artifact_id, path, intent, (kind,),
            unsettled=reservation is not None and reservation.consumedSeconds is None,
        )
        if ref is None:
            if (reservation is not None and (not unstarted or reservation.consumedSeconds is not None)
                    or intent is not None and intent.launchId is not None and not unstarted):
                raise CampaignConflict("Trial was admitted without a terminal receipt; reconcile before retrying")
            if request.max_seconds != int(request.max_seconds):
                raise ValueError("Device reservation must be an integral number of seconds")

            intent = _TrialIntent(
                kind=kind, fingerprint=fingerprint, identity=CudaMeasurementIdentity.from_request(request, device_name),
                launchId=None,
            )
            intent.persist(path)
            # Record the no-start decision before either releasing budget or
            # replacing the previous attempt's device-busy evidence.
            if reservation is not None:
                release_unstarted("execution_not_started")
            _receipt_path(path).unlink(missing_ok=True)
            with start_fence() if start_fence is not None else nullcontext():
                reserve_gpu_time(team_id, project_id, campaign_id, run_id=run_id,
                    reservation_id=measurement_id, seconds=int(request.max_seconds),
                    protocol_hash=intent.identity.protocolHash, phase=request.protocol.split)
            launch_id = uuid4().hex
            launch = intent.model_copy(update={"launchId": launch_id})
            target = launch.receipt_target(path, launch_id)

            @contextmanager
            def launch_fence():
                with start_fence() if start_fence is not None else nullcontext():
                    launch.persist(path)
                    yield

            try:
                measurement = execute_cuda_trial(request, device_name=device_name,
                    receipt_target=target, start_fence=launch_fence)
            except Exception as exc:
                observed = _read_intent(path)
                if isinstance(observed, _TrialIntent):
                    receipt = _read_trial_receipt(path, observed)
                    if observed.launchId is None or (receipt is not None and receipt.measurement is None):
                        intent.persist(path)
                        release_unstarted("device_busy" if isinstance(exc, BlockingIOError) else "execution_not_started")
                raise

            receipt = target.read()
            if receipt is None:
                # An in-process executor must still deliver a durable
                # measurement under the same admitted launch.
                if _read_intent(path) != launch:
                    raise CampaignConflict("CUDA executor did not cross the launch fence")
                target.persist(measurement)
            elif receipt.measurement != measurement:
                raise CampaignConflict("CUDA executor returned a different terminal receipt")
            ref = _publish_measurement(team_id, artifact_id, launch, measurement)

        settle_gpu_usage(team_id, project_id, campaign_id, reservation_id=measurement_id, measurement_ref=ref)
        return ref


def reconcile_run_gpu_receipts(team_id: str, project_id: str, campaign_id: str, run_id: str) -> bool:
    """Publish and settle existing evidence without launching GPU work."""
    complete = True
    for reservation in read_campaign(team_id, project_id, campaign_id).gpuReservations:
        if reservation.runId != run_id or reservation.consumedSeconds is not None:
            continue
        artifact_id = "operator-trial:" + reservation.reservationId
        path = _intent_path(team_id, project_id, artifact_id)
        with ExitStack() as lock:
            try:
                lock.enter_context(inter_process_lock(path, timeout_s=0))
            except OSError:
                complete = False
                continue
            current = read_campaign(team_id, project_id, campaign_id)
            if not any(r.reservationId == reservation.reservationId and r.consumedSeconds is None
                       for r in current.gpuReservations):
                continue
            state = _read_intent(path)
            intent = state if isinstance(state, _TrialIntent) else None
            if intent is not None and (
                intent.identity.runId, intent.identity.optimizationCampaignId,
                intent.identity.measurementId, intent.identity.protocolHash,
            ) != (run_id, campaign_id, reservation.reservationId, reservation.protocolHash):
                raise CampaignConflict("GPU trial intent scope differs from its reservation")
            kinds = (intent.kind,) if intent is not None else _TRIAL_KINDS
            ref, unstarted = _recover_trial(team_id, run_id, artifact_id, path, intent, kinds, unsettled=True)
            if ref is not None:
                settle_gpu_usage(team_id, project_id, campaign_id,
                    reservation_id=reservation.reservationId, measurement_ref=ref)
            elif unstarted:
                intent.model_copy(update={"launchId": None}).persist(path)
                release_gpu_reservation(team_id, project_id, campaign_id,
                    reservation_id=reservation.reservationId, reason="execution_not_started")
            elif intent is not None and cuda_worker_lease_busy():
                complete = False
            else:
                raise CampaignConflict("Admitted GPU trial has no verifiable terminal receipt")
    return complete


def dispatch_baseline(
    action, snapshot: dict, *, start_fence: Callable[[], ContextManager[None]] | None = None,
) -> ArtifactRef:
    team_id, project_id = snapshot["teamId"], snapshot["projectId"]
    campaign_id = snapshot["researchObjectiveContract"]["optimizationCampaignId"]
    campaign = read_campaign(team_id, project_id, campaign_id)
    baseline_version_id = snapshot["researchObjectiveContract"].get("baselineVersionId", "")
    version = next(
        (
            item
            for item in campaign.baselineVersions
            if item.baselineVersionId == baseline_version_id and item.runId == action.run_id
        ),
        None,
    )
    if version is None or version.status not in {"prepared", "active", "failed"}:
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
    if candidate_ref != version.baselineCandidateRef or candidate_ref.runId != action.run_id:
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
    ref = dispatch_trial(team_id, project_id, request, device_name=environment["deviceName"],
        baseline=True, start_fence=start_fence)
    envelope = load_scoped_artifact_payload(ref.kind, team_id=team_id, workflow_run_id=action.run_id,
        authority_run_id=action.run_id, record_id=ref.artifactId, content_hash=ref.sha256)
    if envelope is None or envelope["payload"]["status"] != "succeeded":
        def fail(c):
            versions = tuple(
                item.model_copy(update={"status": "failed"})
                if item.baselineVersionId == baseline_version_id
                else item
                for item in c.baselineVersions
            )
            return c.model_copy(update={"baselineVersions": versions})

        update_campaign(
            team_id,
            project_id,
            campaign_id,
            expected_version=None,
            command_key="baseline-failed:" + action.run_id,
            command={"action": "baseline_failed", "measurementRef": ref.model_dump(mode="json")},
            transform=fail,
        )
        raise RuntimeError("Baseline measurement did not succeed; terminal receipt and incurred cost are preserved")
    measurement = OperatorMeasurement.model_validate(envelope["payload"])
    if ({row.caseId for row in measurement.cases} != {case.caseId for case in request.protocol.cases}
        or any(not row.correctnessPassed or row.maxAbsoluteError is None
            or len(row.timings) != request.protocol.pairs for row in measurement.cases)):
        raise RuntimeError("Baseline measurement lacks complete correctness and paired timing evidence")
    def bind(c):
        current = next(
            (item for item in c.baselineVersions if item.baselineVersionId == baseline_version_id),
            None,
        )
        if current is None or current.runId != action.run_id or current.status not in {"prepared", "active"}:
            raise CampaignConflict("Prepared baseline identity differs")
        versions = tuple(
            item.model_copy(update={"baselineRef": ref, "status": "active"})
            if item.baselineVersionId == baseline_version_id
            else item.model_copy(update={"status": "superseded"})
            if item.status == "active"
            else item
            for item in c.baselineVersions
        )
        return c.model_copy(update={
            "baselineRunId": action.run_id,
            "baselineRef": ref,
            "baselineCandidateRef": current.baselineCandidateRef,
            "bestCandidateRef": current.baselineCandidateRef,
            "activeBaselineVersionId": baseline_version_id,
            "baselineVersions": versions,
        })
    with start_fence() if start_fence is not None else nullcontext():
        update_campaign(team_id, project_id, campaign_id, expected_version=None,
            command_key="baseline-measured:" + action.run_id,
            command={"action": "baseline_measured", "measurementRef": ref.model_dump(mode="json")}, transform=bind)
    return ref
