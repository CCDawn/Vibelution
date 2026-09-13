"""Execute exactly the trials in the canonical frozen operator plan."""

from __future__ import annotations

import json

from core.research.operator_optimization.cuda_worker import CudaTrialRequest
from core.research.operator_optimization.plan import OptimizationPlan
from core.research.workflow.contracts._canonical import sha256_hex

from ..research_runtime.artifact_readback_registry import (
    build_canonical_ref,
    load_scoped_artifact_payload,
)
from ..research_runtime.formal_write_runtime import get_write_store
from .dispatch import dispatch_trial
from .knowledge import read_ref, round_context
from .planning import planning_input, validate_plan_candidates
from .store import CampaignConflict


def execute_plan(action, snapshot: dict) -> list[dict[str, str]]:
    store = get_write_store()
    run = store.get_run(action.run_id)
    attempt = store.latest_attempt(action.run_id, "operator_execution")
    if (
        run is None
        or run.workflow_id != "operator-optimization"
        or run.status not in {"running", "blocked"}
        or attempt is None
        or attempt.node_run_id != action.node_run_id
        or attempt.finished_at_ms is not None
        or action.node_id != "operator_execution"
    ):
        raise CampaignConflict("Execution requires the active operator NodeRun")
    frozen = json.loads(run.input_snapshot_json)
    if (snapshot.get("teamId"), snapshot.get("projectId")) != (
        run.team_id,
        run.project_id,
    ):
        raise CampaignConflict("Execution locator differs from its Ledger run")
    campaign, record, _ = round_context(run.team_id, run.run_id)
    if not campaign.budget.authorized or not campaign.authorizedBy:
        raise CampaignConflict("Execution budget is not authorized")
    if record.planRef is None or record.planRef.kind != "optimization_plan":
        raise CampaignConflict("Execution requires a frozen optimization plan")
    plan = OptimizationPlan.model_validate(
        read_ref(run.team_id, run.run_id, record.planRef)
    )
    inputs = planning_input(run.team_id, run.run_id)
    for key in (
        "optimizationCampaignId",
        "roundId",
        "hypothesisRef",
        "knowledgeRef",
        "protocolRef",
        "baselineCandidateRef",
        "parentCandidateRef",
    ):
        value = getattr(plan, key)
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        if value != inputs[key]:
            raise CampaignConflict("Execution plan differs from its frozen round")
    validate_plan_candidates(
        run.team_id,
        run.run_id,
        campaign,
        record,
        (plan.baselineCandidateRef, plan.parentCandidateRef, plan.candidateRef),
    )
    if (
        plan.trialCount > campaign.budget.maxTrialsPerRound
        or plan.trialTimeoutSeconds > campaign.budget.trialTimeoutSeconds
    ):
        raise CampaignConflict("Frozen plan exceeds the authorized trial limits")
    environment = load_scoped_artifact_payload(
        "operator_environment",
        team_id=run.team_id,
        workflow_run_id=run.run_id,
        authority_run_id=run.run_id,
        content_hash=frozen["environmentSnapshotRef"],
    )
    if environment is None:
        raise CampaignConflict("Execution environment cannot be read back")
    refs = []
    for index in range(plan.trialCount):
        # Stable across node retries: dispatch_trial owns durable admission,
        # terminal receipt recovery and settlement, including failed trials.
        request = CudaTrialRequest(
            protocol=inputs["protocol"],
            baseline=plan.baselineCandidateRef.candidate,
            parent=plan.parentCandidateRef.candidate,
            candidate=plan.candidateRef.candidate,
            campaign_id=campaign.optimizationCampaignId,
            run_id=run.run_id,
            measurement_id="trial-"
            + sha256_hex(
                {"runId": run.run_id, "planHash": record.planRef.sha256, "index": index}
            )[:24],
            expected_environment_hash=sha256_hex(environment["payload"]),
            max_seconds=plan.trialTimeoutSeconds,
        )
        ref = dispatch_trial(
            run.team_id,
            run.project_id,
            request,
            device_name=environment["payload"]["deviceName"],
        )
        refs.append(
            {
                "kind": ref.kind,
                "sha256": ref.sha256,
                "canonicalRef": build_canonical_ref(
                    kind=ref.kind,
                    team_id=run.team_id,
                    authority_run_id=run.run_id,
                    content_hash=ref.sha256,
                ),
            }
        )
    return refs
