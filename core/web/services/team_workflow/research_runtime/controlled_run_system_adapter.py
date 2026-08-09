"""Real controlled experiment execution for the controlled_run System node."""

from __future__ import annotations

from typing import Any

from core.research.workflow.contracts import ContractValidationError, ExperimentCampaign
from core.web.services.team_workflow.experiment_api.full_run import (
    execute_experiment_full_run,
)

from .node_completion import complete_node_execution
from .node_execution import start_node_execution
from .node_execution_support import NodeExecutionError, latest_node_run
from .store import WorkflowRunStore
from .system_action_records import (
    SystemActionError,
    begin_system_action,
    complete_system_action,
    fail_system_action,
    find_system_action,
)
from .system_artifact_builder import build_system_artifact


def _required_artifact(record: dict[str, Any], kind: str) -> dict[str, Any]:
    manifest = next(
        (
            dict(item)
            for item in reversed(record.get("artifactManifests") or [])
            if str(item.get("artifactId") or "").startswith(f"{kind}:")
        ),
        None,
    )
    if manifest is None:
        raise SystemActionError(
            f"controlled_run requires {kind}",
            code="required_artifact_missing",
        )
    return manifest


def execute_controlled_run_action(
    store: WorkflowRunStore,
    *,
    checkpoint_path: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    plan_id = str(payload.get("planId") or "").strip()
    if not idempotency_key or not plan_id:
        raise SystemActionError(
            "start_controlled_run requires planId and idempotencyKey",
            code="invalid_system_action",
        )
    existing = find_system_action(
        record,
        node_id="controlled_run",
        command="start_controlled_run",
        idempotency_key=idempotency_key,
    )
    if existing is not None and existing.get("status") == "succeeded":
        return {"command": "start_controlled_run", "systemAction": existing}
    node_run = latest_node_run(record, "controlled_run")
    if node_run.get("status") != "ready":
        raise SystemActionError(
            "controlled_run must be ready",
            code="invalid_node_state",
        )
    frozen_manifest = _required_artifact(record, "frozen_protocol")
    smoke_release = _required_artifact(record, "smoke_release")
    smoke_action = next(
        (
            dict(item)
            for item in reversed(record.get("systemActions") or [])
            if item.get("nodeId") == "smoke_gate"
            and item.get("command") == "run_smoke"
            and item.get("status") == "succeeded"
            and (item.get("observation") or {}).get("status") == "passed"
        ),
        None,
    )
    if smoke_action is None:
        raise SystemActionError(
            "controlled_run requires a passed Smoke observation",
            code="smoke_evidence_missing",
        )
    if (smoke_action.get("observation") or {}).get("planId") != plan_id:
        raise SystemActionError(
            "planId does not match the released Smoke observation",
            code="frozen_plan_mismatch",
        )
    campaign_raw = payload.get("campaign")
    if not isinstance(campaign_raw, dict):
        raise SystemActionError(
            "start_controlled_run requires an ExperimentCampaign",
            code="experiment_campaign_required",
        )
    action, created = begin_system_action(
        store,
        record=record,
        node_id="controlled_run",
        node_run_id=str(node_run["nodeRunId"]),
        attempt=int(node_run["attempt"]),
        command="start_controlled_run",
        idempotency_key=idempotency_key,
        input_summary={
            "planId": plan_id,
            "frozenProtocolRef": frozen_manifest["artifactId"],
            "smokeReleaseRef": smoke_release["artifactId"],
        },
    )
    if not created:
        return {"command": "start_controlled_run", "systemAction": action}
    lease_owner = "system:controlled_run"
    try:
        start_node_execution(
            store,
            run_id=str(record["runId"]),
            node_id="controlled_run",
            payload={
                "idempotencyKey": f"{idempotency_key}:lease",
                "leaseOwner": lease_owner,
                "leaseSeconds": int(payload.get("leaseSeconds") or 300),
                "deadlineSeconds": int(payload.get("deadlineSeconds") or 3600),
            },
        )
        result = execute_experiment_full_run(
            str(record["teamId"]),
            plan_id,
            {
                key: value
                for key, value in payload.items()
                if key not in {"idempotencyKey", "planId", "campaign"}
            },
        )
        execution = dict(result.get("execution") or {})
        execution_id = str(execution.get("executionId") or "").strip()
        if not execution_id or execution.get("status") != "completed":
            raise SystemActionError(
                "controlled run did not return a completed execution",
                code="invalid_controlled_run_observation",
            )
        result_ref = f"experiment-run:{execution_id}"
        campaign_payload = {
            **campaign_raw,
            "runId": record["runId"],
            "experimentRunRefs": [result_ref],
            "resultArtifactRefs": [result_ref],
        }
        try:
            campaign = ExperimentCampaign.from_dict(campaign_payload)
        except ContractValidationError as exc:
            raise SystemActionError(
                str(exc),
                code="invalid_experiment_campaign",
            ) from exc
        manifest = build_system_artifact(
            record=record,
            node_run=node_run,
            artifact_kind="run_artifacts",
            payload=campaign.to_dict(),
            source_artifact_ids=[
                frozen_manifest["artifactId"],
                smoke_release["artifactId"],
            ],
            adapter_name="controlled_run_system_adapter",
        )
        complete_node_execution(
            store,
            checkpoint_path=checkpoint_path,
            run_id=str(record["runId"]),
            node_id="controlled_run",
            payload={
                "idempotencyKey": f"{idempotency_key}:complete",
                "leaseOwner": lease_owner,
                "artifactManifests": [manifest.to_dict()],
                "artifactPayloads": {
                    manifest.artifactId: campaign.to_dict(),
                },
            },
        )
    except (NodeExecutionError, SystemActionError) as exc:
        fail_system_action(
            store,
            run_id=str(record["runId"]),
            action=action,
            error_code=str(getattr(exc, "code", "controlled_run_failed")),
            message=str(exc),
        )
        raise
    except Exception as exc:
        fail_system_action(
            store,
            run_id=str(record["runId"]),
            action=action,
            error_code="controlled_run_failed",
            message=str(exc),
        )
        raise SystemActionError(
            str(exc),
            code="controlled_run_failed",
        ) from exc
    observation = {
        "status": "completed",
        "observationRef": f"experiment-run:{execution_id}",
        "executionId": execution_id,
        "planId": plan_id,
        "runArtifactsRef": manifest.artifactId,
    }
    completed = complete_system_action(
        store,
        run_id=str(record["runId"]),
        action=action,
        observation=observation,
    )
    return {"command": "start_controlled_run", "systemAction": completed}
