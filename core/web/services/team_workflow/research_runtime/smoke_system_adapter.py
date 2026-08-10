"""Real Smoke execution bound to the pending smoke HumanTask."""

from __future__ import annotations

from typing import Any

from core.web.services.team_workflow.experiment_api.smoke import (
    run_experiment_smoke_run,
)

from .node_execution_support import latest_node_run
from .store import WorkflowRunStore
from .system_action_records import (
    SystemActionError,
    begin_system_action,
    complete_system_action,
    fail_system_action,
    find_system_action,
)
from .system_artifact_builder import build_system_artifact


def _frozen_protocol(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = next(
        (
            dict(item)
            for item in reversed(record.get("artifactManifests") or [])
            if str(item.get("artifactId") or "").startswith("frozen_protocol:")
        ),
        None,
    )
    if manifest is None:
        raise SystemActionError(
            "Smoke requires a frozen_protocol ArtifactManifest",
            code="required_artifact_missing",
        )
    payload = dict(
        (record.get("artifactPayloads") or {}).get(manifest["artifactId"]) or {}
    )
    return manifest, payload


def execute_smoke_action(
    store: WorkflowRunStore,
    *,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> dict[str, Any]:
    idempotency_key = str(payload.get("idempotencyKey") or "").strip()
    plan_id = str(payload.get("planId") or "").strip()
    if not idempotency_key or not plan_id:
        raise SystemActionError(
            "run_smoke requires planId and idempotencyKey",
            code="invalid_system_action",
        )
    node_run = latest_node_run(record, "smoke_gate")
    if node_run.get("status") != "waiting_human":
        raise SystemActionError(
            "smoke_gate must be waiting_human",
            code="invalid_node_state",
        )
    frozen_manifest, frozen_payload = _frozen_protocol(record)
    frozen_plan_id = str(frozen_payload.get("planId") or "").strip()
    if frozen_plan_id and frozen_plan_id != plan_id:
        raise SystemActionError(
            "planId does not match the frozen protocol",
            code="frozen_plan_mismatch",
        )
    existing = find_system_action(
        record,
        node_id="smoke_gate",
        command="run_smoke",
        idempotency_key=idempotency_key,
    )
    if existing is not None and existing.get("status") == "succeeded":
        return {"command": "run_smoke", "systemAction": existing}
    action, created = begin_system_action(
        store,
        record=record,
        node_id="smoke_gate",
        node_run_id=str(node_run["nodeRunId"]),
        attempt=int(node_run["attempt"]),
        command="run_smoke",
        idempotency_key=idempotency_key,
        input_summary={
            "planId": plan_id,
            "frozenProtocolRef": frozen_manifest["artifactId"],
        },
    )
    if not created:
        return {"command": "run_smoke", "systemAction": action}
    try:
        result = run_experiment_smoke_run(
            str(record["teamId"]),
            plan_id,
            {
                key: value
                for key, value in payload.items()
                if key not in {"idempotencyKey", "planId"}
            },
        )
    except Exception as exc:
        fail_system_action(
            store,
            run_id=str(record["runId"]),
            action=action,
            error_code="smoke_execution_failed",
            message=str(exc),
        )
        raise SystemActionError(
            str(exc),
            code="smoke_execution_failed",
        ) from exc
    smoke_run = dict(result.get("smokeRun") or {})
    status = str(result.get("status") or smoke_run.get("status") or "unknown")
    smoke_run_id = str(smoke_run.get("smokeRunId") or "").strip()
    if not smoke_run_id:
        fail_system_action(
            store,
            run_id=str(record["runId"]),
            action=action,
            error_code="invalid_smoke_observation",
            message="Smoke result has no smokeRunId",
        )
        raise SystemActionError(
            "Smoke result has no smokeRunId",
            code="invalid_smoke_observation",
        )
    observation = {
        "status": status,
        "observationRef": f"smoke-run:{smoke_run_id}",
        "smokeRunId": smoke_run_id,
        "planId": plan_id,
        "artifactHash": str(smoke_run.get("artifactHash") or ""),
    }
    artifact_payload = {
        "runId": record["runId"],
        "nodeId": "smoke_gate",
        "planId": plan_id,
        "frozenProtocolRef": frozen_manifest["artifactId"],
        **observation,
    }
    manifest = build_system_artifact(
        record=record,
        node_run=node_run,
        artifact_kind="smoke_observation",
        payload=artifact_payload,
        source_artifact_ids=[frozen_manifest["artifactId"]],
        adapter_name="smoke_system_adapter",
    )
    completed = complete_system_action(
        store,
        run_id=str(record["runId"]),
        action=action,
        observation=observation,
        artifact_manifest=manifest.to_dict(),
        artifact_payload=artifact_payload,
    )
    return {"command": "run_smoke", "systemAction": completed}
