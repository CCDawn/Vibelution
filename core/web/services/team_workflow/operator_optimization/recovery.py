"""Recover a cancelled discussion as a new execution of the same round."""
from __future__ import annotations

import json

from core.research.operator_optimization.measurement import MeasurementProtocolRef
from core.research.workflow.contracts._canonical import sha256_hex
from core.research.workflow.definition_registry import resolve_definition
from core.research.workflow.models import AgentBindingLayers
from core.research.workflow.operator_optimization_definition import OPERATOR_WORKFLOW_ID

from ..research_runtime import run_creation
from ..research_runtime import workflow_artifact_store as artifacts
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime.operator_authorization import require_privileged_server_operator
from ..storage_durability import inter_process_lock
from .store import CampaignConflict, update_campaign


def _copy_frozen(team_id, source_run_id, run_id, kind, digest):
    envelope = load_scoped_artifact_payload(kind, team_id=team_id,
        workflow_run_id=source_run_id, authority_run_id=source_run_id, content_hash=digest)
    if not digest or envelope is None:
        raise CampaignConflict("Recovery frozen evidence cannot be verified")
    with inter_process_lock(artifacts._path(team_id, kind)):
        row = artifacts.put_workflow_artifact(team_id, kind=kind,
            workflow_run_id=run_id, artifact_identity="recover:" + kind, payload=envelope["payload"])
    copied = load_scoped_artifact_payload(kind, team_id=team_id,
        workflow_run_id=run_id, authority_run_id=run_id, record_id=row["recordId"])
    if copied is None:
        raise CampaignConflict("Recovery frozen evidence cannot be read back")
    return row["recordId"], sha256_hex(copied)


def recover_round(team_id: str, project_id: str, campaign_id: str, round_id: str, *,
                  expected_version: int, command_key: str):
    require_privileged_server_operator(command="fork_revision")

    def recover(campaign):
        if campaign.status != "running" or not campaign.budget.authorized or not campaign.authorizedBy:
            raise CampaignConflict("Campaign is not admitting recovery")
        record = campaign.rounds[-1] if campaign.rounds else None
        if record is None or record.roundId != round_id or record.runId != campaign.activeRunId:
            raise CampaignConflict("Recovery requires the active latest round")
        ledger = run_creation.get_write_store()
        old = ledger.get_run(record.runId)
        if old is None or (old.team_id, old.project_id, old.workflow_id) != (team_id, project_id, OPERATOR_WORKFLOW_ID):
            raise CampaignConflict("Recovery run scope differs")
        if old.status != "cancelled":
            raise CampaignConflict("Recovery requires a cancelled run")
        if (old.active_node_id != "optimization_discussion"
                or any((record.hypothesisRef, record.knowledgeRef, record.planRef,
                        record.experimentCampaignId, record.evaluationRef, record.feedbackRef))
                or any(a.node_id != "optimization_discussion" for a in ledger.list_attempts(old.run_id))):
            raise CampaignConflict("Recovery is limited to an unfinished discussion")
        frozen = json.loads(old.input_snapshot_json)
        context = frozen["researchObjectiveContract"]
        if (context.get("optimizationCampaignId"), context.get("roundId")) != (campaign_id, round_id):
            raise CampaignConflict("Recovery frozen round identity differs")
        definition = resolve_definition(workflow_id=old.workflow_id,
            workflow_version_id=old.workflow_version_id, structure_hash=old.structure_hash,
            run_id=old.run_id)
        # One successor per cancelled execution, including a retry after a
        # successful Ledger create but failed campaign persistence.
        recovery_key = "recover-" + sha256_hex({"runId": old.run_id})[:24]
        run_id = run_creation.run_id_for_create(OPERATOR_WORKFLOW_ID, recovery_key)
        _, environment_hash = _copy_frozen(team_id, old.run_id, run_id,
            "operator_environment", frozen["environmentSnapshotRef"])
        artifact_id, protocol_hash = _copy_frozen(team_id, old.run_id, run_id,
            "operator_measurement_protocol", frozen["evaluationContract"]["protocolArtifactHash"])
        protocol_ref = MeasurementProtocolRef(artifactId=artifact_id, runId=run_id, sha256=protocol_hash)
        # Preserve the input policies and all source references. Only envelopes
        # whose authority belongs to the execution receive a new scoped identity.
        frozen["environmentSnapshotRef"] = environment_hash
        frozen["evaluationContract"].update(protocolRef=protocol_ref.model_dump(mode="json"),
            protocolArtifactHash=protocol_hash)
        bindings = AgentBindingLayers(nodeOverrides={b["nodeId"]: b["agentId"]
            for b in frozen["agentBindingSnapshot"] if b.get("agentId")})
        run_creation.create_run(OPERATOR_WORKFLOW_ID, run_input=frozen,
            idempotency_key=recovery_key, binding_layers=bindings, workflow_definition=definition)
        recovered = record.model_copy(update={"runId": run_id, "protocolRef": protocol_ref,
            "previousRunIds": (*record.previousRunIds, old.run_id)})
        return campaign.model_copy(update={"rounds": (*campaign.rounds[:-1], recovered), "activeRunId": run_id})

    return update_campaign(team_id, project_id, campaign_id, expected_version=expected_version,
        command_key=command_key, command={"action": "recover_round", "roundId": round_id}, transform=recover)
