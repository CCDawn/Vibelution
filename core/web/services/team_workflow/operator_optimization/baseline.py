"""Prepare the independent baseline through the canonical Ledger creation path."""
from __future__ import annotations

from core.research.operator_optimization.candidate import (
    CudaCandidateArtifact,
    candidate_ref_from_artifact,
)
from core.research.operator_optimization.contracts import BaselineVersion
from core.research.operator_optimization.cuda_runner import inspect_cuda_environment
from core.research.operator_optimization.evaluation import workload_hash
from core.research.operator_optimization.measurement import (
    MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    MeasurementProtocol,
    MeasurementProtocolRef,
)
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.operator_optimization_definition import (
    OPERATOR_BASELINE_WORKFLOW_ID,
)

from ..research_runtime import run_creation
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.operator_authorization import require_privileged_server_operator
from ..research_runtime.workflow_artifact_store import put_workflow_artifact
from .baseline_versioning import ensure_active_baseline_version
from .run_input import build_operator_run_input
from .store import CampaignConflict, update_campaign


def _prepare_version(campaign, *, protocol, setup_id, repair_evidence=(), created_from_run_id=""):
    if not campaign.budget.authorized or not campaign.authorizedBy:
        raise PermissionError("Campaign budget must be authorized before baseline preparation")
    if {case.dtype for case in protocol.cases} - set(campaign.objective.dtypes):
        raise ValueError("Protocol dtype is outside the campaign objective")
    ordinal = len(campaign.baselineVersions) + 1
    version_id = "baseline-version-" + sha256_hex(
        {"campaign": campaign.optimizationCampaignId, "ordinal": ordinal, "setup": setup_id}
    )[:24]
    environment = inspect_cuda_environment()
    create_key = setup_id
    run_id = run_creation.run_id_for_create(OPERATOR_BASELINE_WORKFLOW_ID, create_key)

    def put(kind, payload, *, artifact_identity):
        row = put_workflow_artifact(
            campaign.teamId,
            kind=kind,
            workflow_run_id=run_id,
            payload=payload,
            artifact_identity=artifact_identity,
        )
        envelope = load_scoped_artifact_payload(
            kind,
            team_id=campaign.teamId,
            workflow_run_id=run_id,
            authority_run_id=run_id,
            record_id=row["recordId"],
        )
        if envelope is None:
            raise CampaignConflict("Baseline artifact could not be read back")
        return row, envelope

    _, environment_envelope = put(
        "operator_environment",
        environment,
        artifact_identity=setup_id + ":operator_environment",
    )
    environment_ref = sha256_hex(environment_envelope)
    protocol_row, protocol_envelope = put(
        MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
        protocol.model_dump(mode="json"),
        artifact_identity=setup_id + ":" + MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    )
    protocol_ref = MeasurementProtocolRef(
        artifactId=protocol_row["recordId"],
        runId=run_id,
        sha256=sha256_hex(protocol_envelope),
    )
    candidate_artifact = CudaCandidateArtifact.default_baseline(
        candidate_id=setup_id + ":operator_candidate",
        optimization_campaign_id=campaign.optimizationCampaignId,
        run_id=run_id,
    )
    candidate_row, candidate_envelope = put(
        "operator_candidate",
        candidate_artifact.model_dump(mode="json"),
        artifact_identity=candidate_artifact.candidateId,
    )
    candidate_ref = candidate_ref_from_artifact(
        candidate_envelope,
        artifact_id=candidate_row["recordId"],
        run_id=run_id,
    )
    run_input = build_operator_run_input(
        campaign,
        environment_ref=environment_ref,
        baseline_candidate_ref=candidate_ref,
        protocol_artifact_id=protocol_ref.artifactId,
        protocol_run_id=run_id,
        protocol_artifact_hash=protocol_ref.sha256,
        protocol_hash=sha256_hex(protocol.model_dump(mode="json")),
        workload_ref=workload_hash(protocol),
        baseline_setup_id=setup_id,
        baseline_version_id=version_id,
    )
    created = run_creation.create_run(
        OPERATOR_BASELINE_WORKFLOW_ID,
        run_input=run_input,
        idempotency_key=create_key,
    )
    version = BaselineVersion(
        baselineVersionId=version_id,
        ordinal=ordinal,
        setupId=setup_id,
        runId=created["runId"],
        environmentRef=environment_ref,
        protocolRef=protocol_ref,
        baselineCandidateRef=candidate_ref,
        repairEvidenceRefs=tuple(repair_evidence),
        createdFromRunId=created_from_run_id,
    )
    return created["runId"], candidate_ref, version


def prepare_baseline(team_id: str, project_id: str, campaign_id: str, *, protocol: MeasurementProtocol,
    expected_version: int, command_key: str):
    """Freeze setup and create a run, without spending GPU measurement time.

    A deterministic run ID and artifact identities permit replay after a crash
    between Ledger creation and the outer activity update. Creation alone does
    not dispatch an experiment or stand in for a completed baseline.
    """
    require_privileged_server_operator(command="extend_budget")
    if protocol.split != "tuning":
        raise ValueError("The initial baseline needs a tuning protocol")

    def prepare(campaign):
        if campaign.status != "draft" or campaign.baselineRunId:
            raise CampaignConflict("The initial baseline has already been prepared")
        run_id, baseline_candidate_ref, version = _prepare_version(
            campaign, protocol=protocol, setup_id=campaign.baselineSetupId
        )
        return campaign.model_copy(update={
            "baselineRunId": run_id,
            "activeRunId": run_id,
            "baselineCandidateRef": baseline_candidate_ref,
            "baselineVersions": (version,),
            "status": "running",
        })

    return update_campaign(team_id, project_id, campaign_id, expected_version=expected_version,
        command_key=command_key, command={"action": "prepare_baseline", "protocol": protocol.model_dump(mode="json")},
        transform=prepare)


def prepare_baseline_repair(
    team_id: str,
    project_id: str,
    campaign_id: str,
    *,
    expected_version: int,
    command_key: str,
    source_run_id: str,
):
    """Prepare a replacement baseline while retaining the active lineage."""

    def prepare(campaign):
        if campaign.status != "running" or campaign.activeRunId != source_run_id:
            raise CampaignConflict("Baseline repair source is no longer active")
        prior = campaign.rounds[-1] if campaign.rounds else None
        if (
            prior is None
            or prior.runId != source_run_id
            or prior.evaluationRef is None
            or prior.feedbackRef is None
        ):
            raise CampaignConflict("Baseline repair requires concrete evaluation and feedback evidence")
        campaign, active = ensure_active_baseline_version(
            campaign, run_creation.get_write_store()
        )
        envelope = load_scoped_artifact_payload(
            MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
            team_id=team_id,
            workflow_run_id=active.runId,
            authority_run_id=active.runId,
            content_hash=active.protocolRef.sha256,
        )
        if envelope is None:
            raise CampaignConflict("Active baseline protocol cannot be verified")
        protocol = MeasurementProtocol.model_validate(envelope["payload"])
        setup_id = "baseline-repair-" + sha256_hex(
            {"campaign": campaign_id, "sourceRunId": source_run_id, "command": command_key}
        )[:24]
        run_id, _, version = _prepare_version(
            campaign,
            protocol=protocol,
            setup_id=setup_id,
            repair_evidence=(prior.evaluationRef, prior.feedbackRef),
            created_from_run_id=source_run_id,
        )
        return campaign.model_copy(
            update={
                "baselineVersions": (*campaign.baselineVersions, version),
                "activeRunId": run_id,
            }
        )

    return update_campaign(
        team_id,
        project_id,
        campaign_id,
        expected_version=expected_version,
        command_key=command_key,
        command={"action": "repair_baseline", "sourceRunId": source_run_id},
        transform=prepare,
    )
