"""Reserve before dispatch; settle only from a hash-verified terminal measurement."""
from __future__ import annotations

from decimal import Decimal

from core.research.operator_optimization.contracts import (
    ArtifactRef,
    GpuReservation,
    OptimizationCampaign,
)
from core.research.operator_optimization.measurement import OperatorMeasurement
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from .store import CampaignConflict, read_campaign, update_campaign


def _amount(reservation: GpuReservation) -> Decimal:
    return Decimal(str(reservation.reservedSeconds if reservation.consumedSeconds is None else reservation.consumedSeconds))


def budget_summary(campaign: OptimizationCampaign) -> dict:
    consumed = sum((Decimal(str(r.consumedSeconds)) for r in campaign.gpuReservations if r.consumedSeconds is not None), Decimal(0))
    reserved = sum((Decimal(r.reservedSeconds) for r in campaign.gpuReservations if r.consumedSeconds is None), Decimal(0))
    tuning = sum((_amount(r) for r in campaign.gpuReservations if r.phase == "tuning"), Decimal(0))
    limit = Decimal(campaign.budget.gpuSecondsLimit)
    final = limit * Decimal(str(campaign.budget.finalValidationFraction))
    return {"gpuConsumedSeconds": float(consumed), "gpuReservedSeconds": float(reserved),
        "gpuAvailableSeconds": float(max(Decimal(0), limit - consumed - reserved)),
        "gpuTuningAvailableSeconds": float(max(Decimal(0), min(limit - final - tuning, limit - consumed - reserved))),
        "gpuFinalReserveSeconds": float(final)}


def reserve_gpu_time(team_id: str, project_id: str, campaign_id: str, *, run_id: str,
    reservation_id: str, seconds: int, protocol_hash: str, phase: str) -> OptimizationCampaign:
    requested = GpuReservation(reservationId=reservation_id, runId=run_id,
        protocolHash=protocol_hash, reservedSeconds=seconds, phase=phase)
    command = {"action": "gpu_reserve", **requested.model_dump(mode="json")}

    def reserve(campaign):
        if not campaign.budget.authorized or not campaign.authorizedBy:
            raise PermissionError("Campaign budget is not authorized")
        if campaign.status != "running" or campaign.activeRunId != run_id:
            raise CampaignConflict("Campaign is not admitting work for this run")
        if any(r.reservationId == reservation_id for r in campaign.gpuReservations):
            raise CampaignConflict("GPU reservation identity already exists")
        if seconds > campaign.budget.trialTimeoutSeconds:
            raise CampaignConflict("Trial exceeds the authorized time budget")
        limit = Decimal(campaign.budget.gpuSecondsLimit)
        total = sum((_amount(r) for r in campaign.gpuReservations), Decimal(0))
        if total + seconds > limit:
            raise CampaignConflict("GPU budget exhausted")
        if phase == "tuning":
            tuning = sum((_amount(r) for r in campaign.gpuReservations if r.phase == "tuning"), Decimal(0))
            if tuning + seconds > limit * (1 - Decimal(str(campaign.budget.finalValidationFraction))):
                raise CampaignConflict("Tuning budget exhausted; final validation reserve is protected")
        return campaign.model_copy(update={"gpuReservations": (*campaign.gpuReservations, requested)})

    result = update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key="gpu-reserve:" + reservation_id, command=command, transform=reserve)
    current = read_campaign(team_id, project_id, campaign_id)
    if any(r.reservationId == reservation_id for r in current.gpuReservations):
        return result
    # A known no-start release removes the reservation but keeps the original
    # command for replay.  Re-admit the same frozen trial under a new command
    # key tied to the current revision; ordinary replays remain idempotent.
    if not any(r.reservationId == reservation_id for r in result.gpuReservations):
        return result
    return update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key=f"gpu-reserve:{reservation_id}:retry:{current.revision}",
        command=command, transform=reserve)


def release_gpu_reservation(team_id: str, project_id: str, campaign_id: str, *,
    reservation_id: str, reason: str = "execution_not_started") -> OptimizationCampaign:
    """Release a reservation only when no worker execution could have started."""
    normalized_reason = str(reason or "").strip()
    if not normalized_reason or len(normalized_reason) > 240:
        raise ValueError("A bounded release reason is required")

    def release(campaign):
        reserved = next((r for r in campaign.gpuReservations if r.reservationId == reservation_id), None)
        if reserved is None:
            raise CampaignConflict("GPU reservation is missing")
        if reserved.consumedSeconds is not None:
            raise CampaignConflict("Cannot release a settled GPU reservation")
        return campaign.model_copy(update={
            "gpuReservations": tuple(r for r in campaign.gpuReservations if r.reservationId != reservation_id)
        })

    command = {"action": "gpu_release", "reservationId": reservation_id, "reason": normalized_reason}
    command_key = f"gpu-release:{reservation_id}:{sha256_hex({'reason': normalized_reason})[:16]}"
    result = update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key=command_key, command=command, transform=release)
    current = read_campaign(team_id, project_id, campaign_id)
    if not any(r.reservationId == reservation_id for r in current.gpuReservations):
        return result
    # If this reservation was admitted again after an earlier release, the
    # original release command is a stale replay. Apply a fresh release once.
    return update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key=f"gpu-release:{reservation_id}:retry:{current.revision}",
        command=command, transform=release)


def settle_gpu_usage(team_id: str, project_id: str, campaign_id: str, *, reservation_id: str,
    measurement_ref: ArtifactRef) -> OptimizationCampaign:
    if measurement_ref.kind not in {"operator_measurement", "operator_baseline"}:
        raise ValueError("GPU settlement requires a canonical operator measurement")

    def settle(campaign):
        reserved = next((r for r in campaign.gpuReservations if r.reservationId == reservation_id), None)
        if reserved is None or reserved.consumedSeconds is not None:
            raise CampaignConflict("GPU reservation is missing or already settled")
        envelope = load_scoped_artifact_payload(measurement_ref.kind, team_id=team_id,
            workflow_run_id=reserved.runId, authority_run_id=reserved.runId,
            content_hash=measurement_ref.sha256, record_id=measurement_ref.artifactId)
        if envelope is None:
            raise CampaignConflict("GPU receipt cannot be verified in this scope")
        measured = OperatorMeasurement.model_validate(envelope["payload"])
        # Worker measurement identity is the reserved trial identity. One
        # receipt cannot settle two different reservations in the same run.
        if (measured.runId, measured.optimizationCampaignId, measured.protocolHash, measured.measurementId) != (
            reserved.runId, campaign_id, reserved.protocolHash, reservation_id
        ):
            raise CampaignConflict("GPU measurement scope does not match its reservation")
        settled = reserved.model_copy(update={"consumedSeconds": measured.gpuSeconds,
            "measurementRef": measurement_ref, "outcome": measured.status})
        changes = {"gpuReservations": tuple(settled if r.reservationId == reservation_id else r for r in campaign.gpuReservations)}
        # Never reject real overrun costs or reopen an activity cancelled while
        # its worker was stopping. Keep the measurement and stop new admission.
        if measured.gpuSeconds > reserved.reservedSeconds and campaign.status not in {"cancelled", "completed"}:
            changes["status"] = "blocked"
        return campaign.model_copy(update=changes)

    return update_campaign(team_id, project_id, campaign_id, expected_version=None,
        command_key="gpu-settle:" + reservation_id,
        command={"action": "gpu_settle", "measurementRef": measurement_ref.model_dump(mode="json")}, transform=settle)
