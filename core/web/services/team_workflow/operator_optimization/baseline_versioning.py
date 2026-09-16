"""Read and normalize the single active baseline lineage."""

from __future__ import annotations

import json

from core.research.operator_optimization.contracts import BaselineVersion
from core.research.operator_optimization.measurement import (
    MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
    MeasurementProtocolRef,
)
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from .store import CampaignConflict


def ensure_active_baseline_version(campaign, ledger):
    """Return a campaign with one active version, importing legacy fields once."""

    if campaign.baselineVersions:
        active = next(
            (
                item
                for item in campaign.baselineVersions
                if item.baselineVersionId == campaign.activeBaselineVersionId
            ),
            None,
        )
        if active is None or active.status != "active" or active.baselineRef is None:
            raise CampaignConflict("A verified active baseline version is required")
        return campaign, active

    baseline_run = ledger.get_run(campaign.baselineRunId)
    if baseline_run is None or campaign.baselineRef is None or campaign.baselineCandidateRef is None:
        raise CampaignConflict("A versioned baseline is required")
    frozen = json.loads(baseline_run.input_snapshot_json)
    try:
        protocol_data = frozen["evaluationContract"].get("protocolRef")
        if protocol_data:
            protocol_ref = MeasurementProtocolRef.model_validate(protocol_data)
        else:
            digest = frozen["evaluationContract"]["protocolArtifactHash"]
            envelope = load_scoped_artifact_payload(
                MEASUREMENT_PROTOCOL_ARTIFACT_KIND,
                team_id=campaign.teamId,
                workflow_run_id=campaign.baselineRunId,
                authority_run_id=campaign.baselineRunId,
                content_hash=digest,
            )
            if envelope is None:
                raise KeyError("protocolRef")
            protocol_ref = MeasurementProtocolRef(
                artifactId="protocol-" + digest[:24],
                runId=campaign.baselineRunId,
                sha256=digest,
            )
        environment_ref = frozen["environmentSnapshotRef"]
    except (KeyError, ValueError) as exc:
        raise CampaignConflict("Legacy baseline evidence cannot be versioned") from exc
    version = BaselineVersion(
        baselineVersionId="baseline-version-" + sha256_hex(
            {
                "campaign": campaign.optimizationCampaignId,
                "runId": campaign.baselineRunId,
            }
        )[:24],
        ordinal=1,
        setupId=campaign.baselineSetupId,
        runId=campaign.baselineRunId,
        environmentRef=environment_ref,
        protocolRef=protocol_ref,
        baselineCandidateRef=campaign.baselineCandidateRef,
        baselineRef=campaign.baselineRef,
        status="active",
    )
    normalized = campaign.model_copy(
        update={
            "baselineVersions": (version,),
            "activeBaselineVersionId": version.baselineVersionId,
        }
    )
    return normalized, version
