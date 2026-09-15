"""Explicit Stage 2 admission into the versioned Stage 3 workflow."""

from __future__ import annotations

from typing import Literal

from core.research.operator_optimization.decision import is_stage3_operator_run
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime import run_creation
from ..research_runtime.artifact_readback_registry import load_scoped_artifact_payload
from ..research_runtime import workflow_artifact_store as artifacts
from ..storage_durability import inter_process_lock
from .rounds import prepare_round
from .stage3_seed import read_stage2_seed
from .store import CampaignConflict

MigrationAction = Literal["discuss", "collect_knowledge", "plan_candidate", "retest"]


def migrate_stage2_run_to_stage3(
    team_id: str,
    project_id: str,
    campaign_id: str,
    *,
    source_run_id: str,
    initial_action: MigrationAction,
    expected_version: int,
    command_key: str,
):
    """Create a new v1.2 run; the historical run and decision stay untouched."""

    if initial_action not in {"discuss", "collect_knowledge", "plan_candidate", "retest"}:
        raise ValueError("Migration requires one explicit Stage 3 action")
    campaign = prepare_round(
        team_id,
        project_id,
        campaign_id,
        expected_version=expected_version,
        command_key="stage2-migration:" + command_key,
        iteration_action=initial_action,
        stage2_source_run_id=source_run_id,
    )
    record = campaign.rounds[-1]
    if record.stage2SeedRef is None:
        raise CampaignConflict("Stage 2 migration did not create a frozen seed")
    seed = read_stage2_seed(team_id, record.stage2SeedRef)
    if seed.sourceRunId != source_run_id:
        raise CampaignConflict("Stage 2 migration seed differs from its source")
    ledger = run_creation.get_write_store()
    source = ledger.get_run(source_run_id)
    target = ledger.get_run(record.runId)
    if source is None or target is None or not is_stage3_operator_run(target):
        raise CampaignConflict("Stage 3 migration run identity is invalid")
    payload = {
        "schemaVersion": 1,
        "optimizationCampaignId": campaign_id,
        "sourceRunId": source_run_id,
        "sourceWorkflowVersionId": source.workflow_version_id,
        "targetRunId": target.run_id,
        "targetWorkflowVersionId": target.workflow_version_id,
        "initialAction": initial_action,
        "stage2SeedRef": record.stage2SeedRef.model_dump(mode="json"),
    }
    with inter_process_lock(artifacts._path(team_id, "operator_stage2_migration_receipt")):
        row = artifacts.put_workflow_artifact(
            team_id,
            kind="operator_stage2_migration_receipt",
            workflow_run_id=target.run_id,
            artifact_identity="operator-stage2-migration:" + sha256_hex(
                {"sourceRunId": source_run_id, "commandKey": command_key}
            )[:24],
            payload=payload,
        )
    if load_scoped_artifact_payload(
        "operator_stage2_migration_receipt",
        team_id=team_id,
        workflow_run_id=target.run_id,
        authority_run_id=target.run_id,
        record_id=row["recordId"],
    ) is None:
        raise CampaignConflict("Stage 2 migration receipt could not be read back")
    return campaign
